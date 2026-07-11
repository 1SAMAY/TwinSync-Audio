from __future__ import annotations

import importlib
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from .delay import DriftEstimator, chunk_frames, compute_compensation
from .models import AudioMode, DelaySettings, PlaybackState, SyncMetrics, VolumeSettings

LOGGER = logging.getLogger(__name__)
SILENCE_RMS_THRESHOLD = 0.0015


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


class _NumpyDelayLine:
    def __init__(self, sample_rate: int, channels: int, delay_ms: float, numpy_module: Any) -> None:
        self._np = numpy_module
        self._channels = channels
        self._lock = threading.Lock()
        self._pending = self._np.zeros((0, channels), dtype=self._np.float32)
        self.set_delay(sample_rate, delay_ms)

    def set_delay(self, sample_rate: int, delay_ms: float) -> None:
        with self._lock:
            frames = round(sample_rate * max(0.0, delay_ms) / 1000.0)
            current = len(self._pending)
            if frames > current:
                extra = self._np.zeros((frames - current, self._channels), dtype=self._np.float32)
                self._pending = self._np.concatenate([extra, self._pending], axis=0)
            elif frames < current:
                self._pending = self._pending[current - frames :]

    def process(self, block: Any) -> Any:
        with self._lock:
            if len(self._pending) == 0:
                return block
            joined = self._np.concatenate([self._pending, block], axis=0)
            output = joined[: len(block)]
            self._pending = joined[len(block) :]
            return output


class AudioEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._output_threads: list[threading.Thread] = []
        self._queues: list[queue.Queue[Any]] = []
        self._config: PlaybackConfig | None = None
        self._metrics = SyncMetrics()

    def start(self, config: PlaybackConfig) -> None:
        config.audio_mode.validate()
        config.delay.clamp()
        config.volume.clamp()
        if config.primary_id == config.secondary_id:
            raise ValueError("Primary and secondary speakers must be different devices.")
        with self._lock:
            self.stop()
            self._config = config
            self._stop.clear()
            self._metrics = SyncMetrics(
                playback_state=PlaybackState.STARTING,
                buffer_size_ms=config.audio_mode.buffer_ms,
                sample_rate=config.audio_mode.sample_rate,
                bit_depth=config.audio_mode.bit_depth,
                connection_health="starting",
            )
            self._capture_thread = threading.Thread(target=self._run, name="twinsync-capture", daemon=True)
            self._capture_thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in [self._capture_thread, *self._output_threads]:
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
        self._capture_thread = None
        self._output_threads = []
        self._queues = []
        self._metrics.playback_state = PlaybackState.STOPPED
        self._metrics.connection_health = "idle"

    def set_delay(self, delay: DelaySettings) -> None:
        delay.clamp()
        if self._config:
            self._config.delay = delay
        primary_ms, secondary_ms = compute_compensation(delay)
        self._metrics.current_delay_primary_ms = primary_ms
        self._metrics.current_delay_secondary_ms = secondary_ms

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
        primary = threading.Thread(target=self._play_pulse, args=(soundcard, np, primary_id, sample_rate, 760.0), daemon=True)
        secondary = threading.Thread(target=self._play_pulse, args=(soundcard, np, secondary_id, sample_rate, 760.0), daemon=True)
        primary.start()
        secondary.start()
        primary.join()
        secondary.join()

    def _run(self) -> None:
        config = self._config
        if config is None:
            return
        try:
            soundcard, np = self._load_audio_modules()
            sample_rate = config.audio_mode.sample_rate
            channels = config.audio_mode.channels
            frames_per_chunk = chunk_frames(sample_rate, config.audio_mode.buffer_ms)
            primary_delay_ms, secondary_delay_ms = compute_compensation(config.delay)
            self._metrics.current_delay_primary_ms = primary_delay_ms
            self._metrics.current_delay_secondary_ms = secondary_delay_ms

            source = self._loopback_source(soundcard, config.source_id)
            capture_ids = self._capture_endpoint_ids(soundcard, config.source_id)
            primary = self._speaker_by_id(soundcard, config.primary_id)
            secondary = self._speaker_by_id(soundcard, config.secondary_id)
            queue_count = max(3, round(250 / max(10, config.audio_mode.buffer_ms)))
            primary_queue = None if self._speaker_matches(primary, capture_ids) else queue.Queue(maxsize=queue_count)
            secondary_queue = None if self._speaker_matches(secondary, capture_ids) else queue.Queue(maxsize=queue_count)
            # If the selected speaker is also the loopback capture endpoint, Windows is already
            # playing system audio there. Rendering into it again can self-feed through loopback
            # and produce static, so TwinSync only renders the non-capture side in that case.
            self._queues = [target for target in (primary_queue, secondary_queue) if target is not None]
            primary_delay = _NumpyDelayLine(sample_rate, channels, primary_delay_ms, np)
            secondary_delay = _NumpyDelayLine(sample_rate, channels, secondary_delay_ms, np)
            self._output_threads = []
            if primary_queue is not None:
                self._output_threads.append(threading.Thread(
                    target=self._render_worker,
                    name="twinsync-primary-render",
                    args=(primary, primary_queue, primary_delay, "primary"),
                    daemon=True,
                ))
            if secondary_queue is not None:
                self._output_threads.append(threading.Thread(
                    target=self._render_worker,
                    name="twinsync-secondary-render",
                    args=(secondary, secondary_queue, secondary_delay, "secondary"),
                    daemon=True,
                ))
            for thread in self._output_threads:
                thread.start()

            drift = DriftEstimator(sample_rate=sample_rate)
            self._metrics.playback_state = PlaybackState.PLAYING
            self._metrics.connection_health = "feedback guard active" if len(self._output_threads) < 2 else "healthy"
            with source.recorder(samplerate=sample_rate, channels=channels, blocksize=frames_per_chunk) as recorder:
                while not self._stop.is_set():
                    started = time.perf_counter()
                    block = self._prepare_capture_block(recorder.record(numframes=frames_per_chunk), np, config)
                    if primary_queue is not None:
                        self._enqueue(primary_queue, block.copy())
                    if secondary_queue is not None:
                        self._enqueue(secondary_queue, block.copy())
                    self._metrics.estimated_drift_ms = drift.observe(frames_per_chunk, time.perf_counter() - started)
        except Exception as exc:  # Audio callback errors must reach the UI instead of killing silently.
            LOGGER.exception("Audio engine failed")
            self._metrics.playback_state = PlaybackState.ERROR
            self._metrics.connection_health = "error"
            self._metrics.last_error = str(exc)

    def _render_worker(self, speaker: Any, blocks: queue.Queue[Any], delay: _NumpyDelayLine, label: str) -> None:
        config = self._config
        if config is None:
            return
        sample_rate = config.audio_mode.sample_rate
        channels = config.audio_mode.channels
        volume_getter = (lambda: config.volume.primary) if label == "primary" else (lambda: config.volume.secondary)
        try:
            with speaker.player(samplerate=sample_rate, channels=channels) as player:
                while not self._stop.is_set():
                    try:
                        block = blocks.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    output = delay.process(block) * volume_getter()
                    player.play(output)
        except Exception as exc:
            LOGGER.exception("%s render worker failed", label)
            self._metrics.playback_state = PlaybackState.ERROR
            self._metrics.connection_health = "error"
            self._metrics.last_error = str(exc)

    def _enqueue(self, target: queue.Queue[Any], block: Any) -> None:
        try:
            target.put_nowait(block)
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            target.put_nowait(block)
            self._metrics.dropped_frames += len(block)
            self._metrics.connection_health = "degraded"

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
        rms = float(np.sqrt(np.mean(np.square(output)))) if output.size else 0.0
        if rms < SILENCE_RMS_THRESHOLD:
            return np.zeros_like(output)
        return output

    def _load_audio_modules(self) -> tuple[Any, Any]:
        try:
            return importlib.import_module("soundcard"), importlib.import_module("numpy")
        except ImportError as exc:
            raise AudioBackendUnavailable(
                "Install TwinSync Windows audio dependencies with `python -m pip install -e .[windows]`."
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
        return {str(getattr(default_speaker, "id", "")), str(getattr(default_speaker, "name", default_speaker))}

    def _speaker_matches(self, speaker: Any, ids: set[str]) -> bool:
        return str(getattr(speaker, "id", "")) in ids or str(getattr(speaker, "name", speaker)) in ids

    def _play_pulse(self, soundcard: Any, np: Any, device_id: str, sample_rate: int, frequency: float) -> None:
        speaker = self._speaker_by_id(soundcard, device_id)
        duration_seconds = 0.35
        frames = int(sample_rate * duration_seconds)
        t = np.arange(frames, dtype=np.float32) / sample_rate
        envelope = np.minimum(1.0, np.arange(frames) / max(1, sample_rate * 0.02))
        envelope = np.minimum(envelope, envelope[::-1])
        tone = 0.18 * np.sin(2.0 * math.pi * frequency * t) * envelope
        stereo = np.column_stack([tone, tone]).astype(np.float32)
        with speaker.player(samplerate=sample_rate, channels=2) as player:
            player.play(stereo)

    def _speaker_by_id(self, soundcard: Any, device_id: str) -> Any:
        for speaker in soundcard.all_speakers():
            name = str(getattr(speaker, "name", speaker))
            ident = str(getattr(speaker, "id", name))
            if device_id in (ident, name):
                return speaker
        raise ValueError(f"Speaker is not available: {device_id}")
