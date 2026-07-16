from __future__ import annotations

import importlib
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from statistics import median
from typing import Any

from .delay import DriftEstimator, automatic_compensation, chunk_frames, compute_compensation
from .models import AudioMode, DelaySettings, PlaybackState, SyncMetrics, VolumeSettings

LOGGER = logging.getLogger(__name__)
SILENCE_OPEN_RMS = 0.0018
SILENCE_CLOSE_RMS = 0.0012
MAX_DRIFT_CORRECTION_PPM = 1200.0
DEVICE_CHECK_SECONDS = 1.0
RECONNECT_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0, 8.0)


class AudioBackendUnavailable(RuntimeError):
    pass


@dataclass
class PlaybackConfig:
    source_id: str | None
    primary_id: str
    secondary_id: str
    delay: DelaySettings
    volume: VolumeSettings
    audio_mode: AudioMode
    automatic_reconnect: bool = True


class _NumpyDelayLine:
    """Persistent delay with an 80 ms crossfade when its live target changes."""

    def __init__(self, sample_rate: int, channels: int, delay_ms: float, numpy_module: Any) -> None:
        self._np = numpy_module
        self._sample_rate = sample_rate
        self._channels = channels
        self._lock = threading.Lock()
        self._max_frames = round(sample_rate * 2.5)
        self._history = self._np.zeros((self._max_frames + 2, channels), dtype=self._np.float32)
        self._current_frames = self._frames(delay_ms)
        self._target_frames = self._current_frames
        self._transition_frames = max(1, round(sample_rate * 0.08))
        self._transition_progress = self._transition_frames

    def _frames(self, delay_ms: float) -> int:
        return min(self._max_frames, round(self._sample_rate * max(0.0, delay_ms) / 1000.0))

    def set_delay(self, sample_rate: int, delay_ms: float) -> None:
        if sample_rate != self._sample_rate:
            raise ValueError("A live delay update cannot change the stream sample rate.")
        with self._lock:
            target = self._frames(delay_ms)
            if target == self._target_frames:
                return
            if self._transition_progress < self._transition_frames:
                fraction = self._transition_progress / self._transition_frames
                self._current_frames = round(
                    self._current_frames + (self._target_frames - self._current_frames) * fraction
                )
            self._target_frames = target
            self._transition_progress = 0

    def process(self, block: Any) -> Any:
        with self._lock:
            block = self._np.asarray(block, dtype=self._np.float32)
            if not len(block):
                return block
            joined = self._np.concatenate([self._history, block], axis=0)
            old_output = self._tap(joined, len(block), self._current_frames)
            if self._transition_progress < self._transition_frames:
                new_output = self._tap(joined, len(block), self._target_frames)
                start = self._transition_progress
                end = min(self._transition_frames, start + len(block))
                alpha = self._np.linspace(start, end, len(block), endpoint=False, dtype=self._np.float32)
                alpha = (alpha / self._transition_frames).reshape((-1, 1))
                output = old_output * (1.0 - alpha) + new_output * alpha
                self._transition_progress = end
                if end >= self._transition_frames:
                    self._current_frames = self._target_frames
            else:
                output = old_output
            self._history = joined[-(self._max_frames + 2) :].copy()
            return output.astype(self._np.float32, copy=False)

    def _tap(self, joined: Any, block_frames: int, delay_frames: int) -> Any:
        base = len(self._history)
        positions = base + self._np.arange(block_frames, dtype=self._np.float64) - delay_frames
        sample_positions = self._np.arange(len(joined), dtype=self._np.float64)
        output = self._np.empty((block_frames, self._channels), dtype=self._np.float32)
        for channel in range(self._channels):
            output[:, channel] = self._np.interp(
                positions, sample_positions, joined[:, channel], left=0.0, right=0.0
            )
        return output


class _NoiseGate:
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.gain = 0.0
        self.open = False
        self.hold_frames = 0

    def process(self, block: Any, np: Any) -> Any:
        if not block.size:
            return block
        rms = float(np.sqrt(np.mean(np.square(block))))
        if rms >= SILENCE_OPEN_RMS:
            self.open = True
            self.hold_frames = round(self.sample_rate * 0.08)
        elif self.open and rms >= SILENCE_CLOSE_RMS:
            self.hold_frames = round(self.sample_rate * 0.08)
        elif self.open and self.hold_frames > 0:
            self.hold_frames = max(0, self.hold_frames - len(block))
        else:
            self.open = False

        target = 1.0 if self.open else 0.0
        duration_frames = max(1, round(self.sample_rate * (0.008 if target else 0.12)))
        next_gain = self.gain + (target - self.gain) * min(1.0, len(block) / duration_frames)
        gains = np.linspace(self.gain, next_gain, len(block), dtype=np.float32).reshape((-1, 1))
        self.gain = next_gain
        return block * gains


class _AdaptiveResampler:
    @staticmethod
    def correction_ppm(queue_depth: int, target_depth: int = 1) -> float:
        return max(
            -MAX_DRIFT_CORRECTION_PPM,
            min(MAX_DRIFT_CORRECTION_PPM, (queue_depth - target_depth) * 300.0),
        )

    @staticmethod
    def process(block: Any, correction_ppm: float, np: Any) -> Any:
        if len(block) < 2 or correction_ppm == 0:
            return block
        output_frames = max(1, round(len(block) / (1.0 + correction_ppm / 1_000_000.0)))
        if output_frames == len(block):
            return block
        source = np.arange(len(block), dtype=np.float64)
        target = np.linspace(0, len(block) - 1, output_frames, dtype=np.float64)
        output = np.empty((output_frames, block.shape[1]), dtype=np.float32)
        for channel in range(block.shape[1]):
            output[:, channel] = np.interp(target, source, block[:, channel])
        return output


class AudioEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._processor_lock = threading.Lock()
        self._failure_lock = threading.Lock()
        self._stop = threading.Event()
        self._cycle_stop = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._output_threads: list[threading.Thread] = []
        self._queues: dict[str, queue.Queue[Any]] = {}
        self._delay_lines: dict[str, _NumpyDelayLine] = {}
        self._config: PlaybackConfig | None = None
        self._metrics = SyncMetrics()
        self._cycle_error: str | None = None
        self._session_counter = 0
        self._gate: _NoiseGate | None = None

    def start(self, config: PlaybackConfig) -> None:
        config.audio_mode.validate()
        config.delay.clamp()
        config.volume.clamp()
        if config.primary_id == config.secondary_id:
            raise ValueError("Primary and secondary speakers must be different devices.")
        self.stop()
        with self._lock:
            self._session_counter += 1
            self._config = config
            self._stop.clear()
            self._cycle_stop.clear()
            primary_auto, secondary_auto = automatic_compensation(config.delay)
            self._metrics = SyncMetrics(
                playback_state=PlaybackState.STARTING,
                buffer_size_ms=config.audio_mode.buffer_ms,
                sample_rate=config.audio_mode.sample_rate,
                bit_depth=config.audio_mode.bit_depth,
                connection_health="starting",
                selected_output_count=2,
                routing_session_count=1,
                automatic_compensation_primary_ms=primary_auto,
                automatic_compensation_secondary_ms=secondary_auto,
            )
            self._capture_thread = threading.Thread(target=self._run, name="twinsync-supervisor", daemon=True)
            self._capture_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._cycle_stop.set()
        current = threading.current_thread()
        for thread in [self._capture_thread, *self._output_threads]:
            if thread and thread is not current and thread.is_alive():
                thread.join(timeout=2.0)
        self._capture_thread = None
        self._output_threads = []
        self._queues = {}
        with self._processor_lock:
            self._delay_lines = {}
        self._metrics.playback_state = PlaybackState.STOPPED
        self._metrics.connection_health = "idle"
        self._metrics.active_output_stream_count = 0
        self._metrics.active_playback_worker_count = 0
        self._metrics.preview_stream_count = 0
        self._metrics.routing_session_count = 0
        self._metrics.queue_depths = {}
        self._metrics.queue_latency_ms = {}
        self._metrics.reconnect_state = "idle"
        self._metrics.routing_mode = "idle"

    def set_delay(self, delay: DelaySettings) -> None:
        delay.clamp()
        if self._config:
            self._config.delay = delay
        primary_ms, secondary_ms = compute_compensation(delay)
        primary_auto, secondary_auto = automatic_compensation(delay)
        self._metrics.current_delay_primary_ms = primary_ms
        self._metrics.current_delay_secondary_ms = secondary_ms
        self._metrics.automatic_compensation_primary_ms = primary_auto
        self._metrics.automatic_compensation_secondary_ms = secondary_auto
        with self._processor_lock:
            for label, value in (("primary", primary_ms), ("secondary", secondary_ms)):
                processor = self._delay_lines.get(label)
                if processor and self._config:
                    processor.set_delay(self._config.audio_mode.sample_rate, value)

    def set_volume(self, volume: VolumeSettings) -> None:
        volume.clamp()
        if self._config:
            self._config.volume = volume

    def status(self) -> SyncMetrics:
        return self._metrics

    def play_test_sound(self, device_id: str, sample_rate: int = 48000) -> None:
        soundcard, np = self._load_audio_modules()
        self._play_pulse(soundcard, np, device_id, sample_rate, 880.0)

    def play_calibration_pulses(self, primary_id: str, secondary_id: str, sample_rate: int = 48000) -> None:
        soundcard, np = self._load_audio_modules()
        self._play_pulse(soundcard, np, primary_id, sample_rate, 660.0)
        time.sleep(0.18)
        self._play_pulse(soundcard, np, secondary_id, sample_rate, 990.0)
        time.sleep(0.18)
        primary = threading.Thread(
            target=self._play_pulse, args=(soundcard, np, primary_id, sample_rate, 760.0), daemon=True
        )
        secondary = threading.Thread(
            target=self._play_pulse, args=(soundcard, np, secondary_id, sample_rate, 760.0), daemon=True
        )
        primary.start()
        secondary.start()
        primary.join()
        secondary.join()

    def measure_acoustic_latency(
        self,
        primary_id: str,
        secondary_id: str,
        measurement_input_id: str,
        sample_rate: int = 48000,
        repeats: int = 3,
    ) -> dict[str, Any]:
        soundcard, np = self._load_audio_modules()
        microphone = self._microphone_by_id(soundcard, measurement_input_id)
        primary = self._speaker_by_id(soundcard, primary_id)
        secondary = self._speaker_by_id(soundcard, secondary_id)
        chirp = self._calibration_chirp(np, sample_rate)
        primary_arrivals: list[float] = []
        secondary_arrivals: list[float] = []
        correlations: list[float] = []
        levels: list[float] = []

        with microphone.recorder(samplerate=sample_rate, channels=1, blocksize=chunk_frames(sample_rate, 20)) as recorder:
            baseline = np.asarray(recorder.record(numframes=round(sample_rate * 0.25)), dtype=np.float32)
            background_rms = float(np.sqrt(np.mean(np.square(baseline)))) if baseline.size else 0.0
            if background_rms > 0.08:
                raise RuntimeError("Microphone background level is too high for reliable calibration.")
            for _ in range(max(3, repeats)):
                primary_ms, primary_score, primary_level = self._record_chirp(
                    recorder, primary, chirp, sample_rate, np
                )
                time.sleep(0.12)
                secondary_ms, secondary_score, secondary_level = self._record_chirp(
                    recorder, secondary, chirp, sample_rate, np
                )
                primary_arrivals.append(primary_ms)
                secondary_arrivals.append(secondary_ms)
                correlations.append(min(primary_score, secondary_score))
                levels.extend((primary_level, secondary_level))
                time.sleep(0.12)

        return {
            "primary_arrivals_ms": primary_arrivals,
            "secondary_arrivals_ms": secondary_arrivals,
            "correlations": correlations,
            "background_noise_rms": background_rms,
            "microphone_level_rms": median(levels),
        }

    def _run(self) -> None:
        config = self._config
        if config is None:
            return
        attempt = 0
        while not self._stop.is_set():
            self._cycle_stop = threading.Event()
            with self._failure_lock:
                self._cycle_error = None
            try:
                self._run_cycle(config)
                if self._stop.is_set():
                    break
                if self._cycle_error:
                    raise RuntimeError(self._cycle_error)
                raise RuntimeError("Audio routing stopped unexpectedly.")
            except Exception as exc:  # Audio failures must reach the UI and shared cancellation path.
                LOGGER.exception("Audio routing cycle failed")
                self._metrics.last_error = str(exc)
            finally:
                self._cycle_stop.set()
                current = threading.current_thread()
                for thread in self._output_threads:
                    if thread is not current and thread.is_alive():
                        thread.join(timeout=1.0)
                self._output_threads = []
                self._queues = {}
                with self._processor_lock:
                    self._delay_lines = {}
                self._metrics.active_output_stream_count = 0
                self._metrics.active_playback_worker_count = 0
                self._metrics.queue_depths = {}
                self._metrics.queue_latency_ms = {}

            if self._stop.is_set():
                break
            if not config.automatic_reconnect:
                self._metrics.playback_state = PlaybackState.ERROR
                self._metrics.connection_health = "error"
                self._metrics.reconnect_state = "disabled"
                break

            attempt += 1
            self._metrics.reconnect_attempts = attempt
            self._metrics.playback_state = PlaybackState.RECONNECTING
            self._metrics.connection_health = "reconnecting"
            self._metrics.reconnect_state = "waiting"
            wait_seconds = RECONNECT_BACKOFF_SECONDS[min(attempt - 1, len(RECONNECT_BACKOFF_SECONDS) - 1)]
            if self._stop.wait(wait_seconds):
                break

    def _run_cycle(self, config: PlaybackConfig) -> None:
        soundcard, np = self._load_audio_modules()
        sample_rate = config.audio_mode.sample_rate
        channels = config.audio_mode.channels
        frames_per_chunk = chunk_frames(sample_rate, config.audio_mode.buffer_ms)
        primary_delay_ms, secondary_delay_ms = compute_compensation(config.delay)
        primary_auto, secondary_auto = automatic_compensation(config.delay)
        self._metrics.current_delay_primary_ms = primary_delay_ms
        self._metrics.current_delay_secondary_ms = secondary_delay_ms
        self._metrics.automatic_compensation_primary_ms = primary_auto
        self._metrics.automatic_compensation_secondary_ms = secondary_auto

        source = self._loopback_source(soundcard, config.source_id)
        capture_ids = self._capture_endpoint_ids(soundcard, config.source_id)
        primary = self._speaker_by_id(soundcard, config.primary_id)
        secondary = self._speaker_by_id(soundcard, config.secondary_id)
        queue_count = max(3, round(250 / max(10, config.audio_mode.buffer_ms)))
        queue_map: dict[str, queue.Queue[Any]] = {}
        uncontrolled_name: str | None = None
        for label, speaker in (("primary", primary), ("secondary", secondary)):
            if self._speaker_matches(speaker, capture_ids):
                uncontrolled_name = str(getattr(speaker, "name", speaker))
            else:
                queue_map[label] = queue.Queue(maxsize=queue_count)
        if not queue_map:
            raise RuntimeError("No TwinSync output stream could be created for the selected speakers.")

        self._queues = queue_map
        self._gate = _NoiseGate(sample_rate)
        delay_values = {"primary": primary_delay_ms, "secondary": secondary_delay_ms}
        speaker_map = {"primary": primary, "secondary": secondary}
        with self._processor_lock:
            self._delay_lines = {
                label: _NumpyDelayLine(sample_rate, channels, delay_values[label], np) for label in queue_map
            }
        self._output_threads = [
            threading.Thread(
                target=self._render_worker,
                name=f"twinsync-{label}-render",
                args=(speaker_map[label], blocks, self._delay_lines[label], label, np),
                daemon=True,
            )
            for label, blocks in queue_map.items()
        ]
        self._metrics.active_output_stream_count = len(self._output_threads)
        self._metrics.active_playback_worker_count = len(self._output_threads)
        self._metrics.routing_mode = "dual-controlled" if len(queue_map) == 2 else "windows-default-plus-controlled"
        self._metrics.uncontrolled_output_name = uncontrolled_name
        self._metrics.routing_warning = (
            f"{uncontrolled_name} is played by Windows and is not volume/delay controlled by TwinSync. "
            "Use a dedicated virtual loopback source to control both selected outputs."
            if uncontrolled_name
            else None
        )
        self._metrics.endpoint_clock_frames = {label: 0 for label in queue_map}
        self._metrics.endpoint_clock_position_ms = {label: 0.0 for label in queue_map}
        self._metrics.drift_correction_ppm = {label: 0.0 for label in queue_map}
        self._metrics.render_latency_ms = {label: 0.0 for label in queue_map}
        for thread in self._output_threads:
            thread.start()

        drift = DriftEstimator(sample_rate=sample_rate)
        self._metrics.playback_state = PlaybackState.PLAYING
        self._metrics.connection_health = "feedback guard active" if uncontrolled_name else "healthy"
        self._metrics.reconnect_state = "stable"
        self._metrics.last_error = None
        last_device_check = time.monotonic()
        with source.recorder(samplerate=sample_rate, channels=channels, blocksize=frames_per_chunk) as recorder:
            while not self._stop.is_set() and not self._cycle_stop.is_set():
                started = time.perf_counter()
                captured = recorder.record(numframes=frames_per_chunk)
                elapsed = time.perf_counter() - started
                block = self._prepare_capture_block(captured, np, config)
                self._enqueue_outputs(block)
                self._metrics.capture_latency_ms = self._smooth(
                    self._metrics.capture_latency_ms, elapsed * 1000.0
                )
                capture_drift = drift.observe(frames_per_chunk, elapsed)
                if len(self._metrics.endpoint_clock_position_ms) < 2:
                    self._metrics.estimated_drift_ms = capture_drift
                now = time.monotonic()
                if now - last_device_check >= DEVICE_CHECK_SECONDS:
                    self._validate_endpoints(soundcard, config, capture_ids)
                    last_device_check = now

        if self._cycle_error and not self._stop.is_set():
            raise RuntimeError(self._cycle_error)

    def _render_worker(
        self,
        speaker: Any,
        blocks: queue.Queue[Any],
        delay: _NumpyDelayLine,
        label: str,
        np: Any,
    ) -> None:
        config = self._config
        if config is None:
            return
        sample_rate = config.audio_mode.sample_rate
        channels = config.audio_mode.channels
        had_audio = False
        fade_frames = max(1, round(sample_rate * 0.15))
        faded_frames = 0
        try:
            with speaker.player(samplerate=sample_rate, channels=channels) as player:
                while not self._stop.is_set() and not self._cycle_stop.is_set():
                    try:
                        block = blocks.get(timeout=0.2)
                    except queue.Empty:
                        if had_audio:
                            self._metrics.buffer_underruns += 1
                            self._metrics.connection_health = "degraded"
                        continue
                    had_audio = True
                    volume = config.volume.primary if label == "primary" else config.volume.secondary
                    if label == "primary":
                        volume *= 1.0 - max(0.0, config.volume.balance)
                    else:
                        volume *= 1.0 + min(0.0, config.volume.balance)
                    output = delay.process(block) * np.float32(volume)
                    if faded_frames < fade_frames:
                        end = min(fade_frames, faded_frames + len(output))
                        fade = np.linspace(faded_frames, end, len(output), endpoint=False, dtype=np.float32)
                        output = output * (fade / fade_frames).reshape((-1, 1))
                        faded_frames = end
                    correction = _AdaptiveResampler.correction_ppm(blocks.qsize())
                    output = _AdaptiveResampler.process(output, correction, np)
                    self._metrics.drift_correction_ppm[label] = correction
                    render_started = time.perf_counter()
                    player.play(output)
                    render_ms = (time.perf_counter() - render_started) * 1000.0
                    self._metrics.render_latency_ms[label] = self._smooth(
                        self._metrics.render_latency_ms.get(label, 0.0), render_ms
                    )
                    frames = self._metrics.endpoint_clock_frames.get(label, 0) + len(output)
                    self._metrics.endpoint_clock_frames[label] = frames
                    self._metrics.endpoint_clock_position_ms[label] = frames * 1000.0 / sample_rate
                    self._metrics.queue_latency_ms[label] = blocks.qsize() * config.audio_mode.buffer_ms
                    clocks = self._metrics.endpoint_clock_position_ms
                    if "primary" in clocks and "secondary" in clocks:
                        error = clocks["secondary"] - clocks["primary"]
                        self._metrics.relative_clock_error_ms = error
                        self._metrics.estimated_drift_ms = error
        except Exception as exc:
            if not self._stop.is_set():
                LOGGER.exception("%s render worker failed", label)
                self._record_cycle_failure(label, exc)

    def _record_cycle_failure(self, label: str, exc: Exception) -> None:
        with self._failure_lock:
            if self._cycle_error is None:
                self._cycle_error = f"{label} output failed: {exc}"
        self._cycle_stop.set()

    def _enqueue_outputs(self, block: Any) -> None:
        queues = list(self._queues.values())
        if not queues:
            return
        if any(target.full() for target in queues):
            for target in queues:
                try:
                    target.get_nowait()
                except queue.Empty:
                    pass
            self._metrics.dropped_frames += len(block)
            self._metrics.buffer_overruns += 1
            self._metrics.connection_health = "degraded"
        for target in queues:
            target.put_nowait(block.copy())
        self._metrics.queue_depths = {label: target.qsize() for label, target in self._queues.items()}
        if self._config:
            self._metrics.queue_latency_ms = {
                label: target.qsize() * self._config.audio_mode.buffer_ms
                for label, target in self._queues.items()
            }

    def _prepare_capture_block(self, block: Any, np: Any, config: PlaybackConfig) -> Any:
        output = np.asarray(block, dtype=np.float32)
        output = np.nan_to_num(output, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        if output.ndim == 1:
            output = output.reshape((-1, 1))
        if output.shape[1] < config.audio_mode.channels:
            output = np.repeat(output, config.audio_mode.channels, axis=1)
        elif output.shape[1] > config.audio_mode.channels:
            output = output[:, : config.audio_mode.channels]
        if config.volume.muted:
            return np.zeros_like(output)
        output = np.clip(output * np.float32(config.volume.master), -1.0, 1.0)
        gate = self._gate
        if gate is None or gate.sample_rate != config.audio_mode.sample_rate:
            gate = self._gate = _NoiseGate(config.audio_mode.sample_rate)
        return gate.process(output, np)

    def _load_audio_modules(self) -> tuple[Any, Any]:
        try:
            return importlib.import_module("soundcard"), importlib.import_module("numpy")
        except ImportError as exc:
            raise AudioBackendUnavailable(
                "TwinSync's bundled Windows audio runtime is unavailable. Reinstall TwinSync Audio."
            ) from exc

    def _loopback_source(self, soundcard: Any, source_id: str | None) -> Any:
        if source_id:
            return soundcard.get_microphone(id=source_id, include_loopback=True)
        default_speaker = soundcard.default_speaker()
        return soundcard.get_microphone(id=str(getattr(default_speaker, "name", default_speaker)), include_loopback=True)

    def _capture_endpoint_ids(self, soundcard: Any, source_id: str | None) -> set[str]:
        if source_id:
            return {source_id}
        default_speaker = soundcard.default_speaker()
        return {
            str(getattr(default_speaker, "id", "")),
            str(getattr(default_speaker, "name", default_speaker)),
        }

    def _validate_endpoints(self, soundcard: Any, config: PlaybackConfig, capture_ids: set[str]) -> None:
        available: set[str] = set()
        for speaker in soundcard.all_speakers():
            available.add(str(getattr(speaker, "id", "")))
            available.add(str(getattr(speaker, "name", speaker)))
        for device_id in (config.primary_id, config.secondary_id):
            if device_id not in available:
                raise RuntimeError(f"Selected output disconnected: {device_id}")
        if config.source_id is None:
            current_default = soundcard.default_speaker()
            current_ids = {
                str(getattr(current_default, "id", "")),
                str(getattr(current_default, "name", current_default)),
            }
            if not current_ids.intersection(capture_ids):
                raise RuntimeError("Windows default output changed; rebuilding the routing session.")

    def _speaker_matches(self, speaker: Any, ids: set[str]) -> bool:
        return str(getattr(speaker, "id", "")) in ids or str(getattr(speaker, "name", speaker)) in ids

    def _play_pulse(self, soundcard: Any, np: Any, device_id: str, sample_rate: int, frequency: float) -> None:
        frames = int(sample_rate * 0.35)
        t = np.arange(frames, dtype=np.float32) / sample_rate
        envelope = np.minimum(1.0, np.arange(frames) / max(1, sample_rate * 0.02))
        envelope = np.minimum(envelope, envelope[::-1])
        tone = 0.18 * np.sin(2.0 * math.pi * frequency * t) * envelope
        stereo = np.column_stack([tone, tone]).astype(np.float32)
        self._play_samples(self._speaker_by_id(soundcard, device_id), stereo, sample_rate)

    def _calibration_chirp(self, np: Any, sample_rate: int) -> Any:
        duration = 0.12
        frames = round(sample_rate * duration)
        t = np.arange(frames, dtype=np.float64) / sample_rate
        start_hz, end_hz = 700.0, 6000.0
        phase = 2.0 * math.pi * (start_hz * t + (end_hz - start_hz) * t * t / (2.0 * duration))
        return (0.22 * np.sin(phase) * np.hanning(frames)).astype(np.float32)

    def _record_chirp(self, recorder: Any, speaker: Any, chirp: Any, sample_rate: int, np: Any) -> tuple[float, float, float]:
        errors: list[Exception] = []

        def play() -> None:
            try:
                time.sleep(0.15)
                stereo = np.column_stack([chirp, chirp]).astype(np.float32)
                self._play_samples(speaker, stereo, sample_rate)
            except Exception as exc:  # Propagate playback failures to the calibration caller.
                errors.append(exc)

        thread = threading.Thread(target=play, name="twinsync-calibration-chirp", daemon=True)
        thread.start()
        recorded = np.asarray(recorder.record(numframes=round(sample_rate * 0.75)), dtype=np.float32)
        thread.join(timeout=2.0)
        if thread.is_alive():
            raise RuntimeError("Calibration speaker playback did not finish.")
        if errors:
            raise errors[0]
        arrival_ms, score = self._detect_chirp(recorded, chirp, sample_rate, np)
        level = float(np.sqrt(np.mean(np.square(recorded)))) if recorded.size else 0.0
        return arrival_ms, score, level

    def _detect_chirp(self, recorded: Any, chirp: Any, sample_rate: int, np: Any) -> tuple[float, float]:
        signal = recorded.mean(axis=1) if recorded.ndim > 1 else recorded
        signal = np.asarray(signal, dtype=np.float64)
        reference = np.asarray(chirp, dtype=np.float64)
        signal -= signal.mean() if signal.size else 0.0
        reference -= reference.mean() if reference.size else 0.0
        if len(signal) < len(reference) or not np.any(reference):
            return 0.0, 0.0
        size = 1 << (len(signal) + len(reference) - 2).bit_length()
        correlation = np.fft.irfft(
            np.fft.rfft(signal, size) * np.conj(np.fft.rfft(reference, size)), size
        )
        valid = np.abs(correlation[: len(signal) - len(reference) + 1])
        start = int(np.argmax(valid))
        segment = signal[start : start + len(reference)]
        denominator = float(np.linalg.norm(segment) * np.linalg.norm(reference))
        score = abs(float(np.dot(segment, reference))) / denominator if denominator else 0.0
        return start * 1000.0 / sample_rate, max(0.0, min(1.0, score))

    def _play_samples(self, speaker: Any, samples: Any, sample_rate: int) -> None:
        self._metrics.preview_stream_count += 1
        try:
            with speaker.player(samplerate=sample_rate, channels=samples.shape[1]) as player:
                player.play(samples)
        finally:
            self._metrics.preview_stream_count = max(0, self._metrics.preview_stream_count - 1)

    def _speaker_by_id(self, soundcard: Any, device_id: str) -> Any:
        for speaker in soundcard.all_speakers():
            name = str(getattr(speaker, "name", speaker))
            ident = str(getattr(speaker, "id", name))
            if device_id in (ident, name):
                return speaker
        raise ValueError(f"Speaker is not available: {device_id}")

    def _microphone_by_id(self, soundcard: Any, device_id: str) -> Any:
        try:
            microphones = soundcard.all_microphones(include_loopback=False)
        except TypeError:
            microphones = soundcard.all_microphones()
        for microphone in microphones:
            name = str(getattr(microphone, "name", microphone))
            ident = str(getattr(microphone, "id", name))
            if device_id in (ident, name):
                return microphone
        raise ValueError(f"Measurement microphone is not available: {device_id}")

    @staticmethod
    def _smooth(previous: float, value: float, weight: float = 0.15) -> float:
        return value if previous == 0.0 else previous * (1.0 - weight) + value * weight
