import unittest
import queue
import threading

import numpy as np

from twinsync_backend.audio_engine import (
    AudioEngine,
    PlaybackConfig,
    _AdaptiveResampler,
    _NumpyDelayLine,
)
from twinsync_backend.models import AudioMode, DelaySettings, PlaybackState, VolumeSettings


class FakePlayer:
    def __init__(self, speaker: "FakeSpeaker") -> None:
        self.speaker = speaker

    def __enter__(self):
        self.speaker.open_players += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.speaker.open_players -= 1

    def play(self, block) -> None:
        self.speaker.play_calls += 1


class FakeSpeaker:
    def __init__(self, device_id: str, name: str) -> None:
        self.id = device_id
        self.name = name
        self.open_players = 0
        self.play_calls = 0

    def player(self, samplerate: int, channels: int):
        return FakePlayer(self)


class FakeSoundcard:
    def __init__(self) -> None:
        self.speakers = {"a": FakeSpeaker("a", "Speaker A")}

    def all_speakers(self):
        return list(self.speakers.values())


class AudioEngineTests(unittest.TestCase):
    def config(self) -> PlaybackConfig:
        return PlaybackConfig(
            source_id=None,
            primary_id="a",
            secondary_id="b",
            delay=DelaySettings(),
            volume=VolumeSettings(master=1.0),
            audio_mode=AudioMode(channels=2),
        )

    def test_capture_noise_gate_mutes_static_but_keeps_music(self) -> None:
        engine = AudioEngine()
        quiet = np.full((256, 2), 0.0002, dtype=np.float32)
        music = np.full((256, 2), 0.05, dtype=np.float32)

        self.assertTrue(np.all(engine._prepare_capture_block(quiet, np, self.config()) == 0))
        self.assertGreater(float(np.max(engine._prepare_capture_block(music, np, self.config()))), 0.0)

    def test_capture_block_sanitizes_invalid_samples(self) -> None:
        engine = AudioEngine()
        block = np.array([[np.nan, np.inf], [0.0, -np.inf]], dtype=np.float32)
        cleaned = engine._prepare_capture_block(block, np, self.config())
        self.assertTrue(np.all(np.isfinite(cleaned)))

    def test_test_sound_closes_preview_stream(self) -> None:
        engine = AudioEngine()
        soundcard = FakeSoundcard()
        engine._load_audio_modules = lambda: (soundcard, np)  # type: ignore[method-assign]

        engine.play_test_sound("a", sample_rate=48000)

        speaker = soundcard.speakers["a"]
        self.assertEqual(speaker.play_calls, 1)
        self.assertEqual(speaker.open_players, 0)
        self.assertEqual(engine.status().preview_stream_count, 0)

    def test_live_delay_update_reaches_persistent_processor(self) -> None:
        class Processor:
            calls: list[tuple[int, float]] = []

            def set_delay(self, sample_rate: int, delay_ms: float) -> None:
                self.calls.append((sample_rate, delay_ms))

        engine = AudioEngine()
        engine._config = self.config()
        processor = Processor()
        engine._delay_lines = {"primary": processor}  # type: ignore[assignment]
        engine.set_delay(DelaySettings(primary_manual_ms=31))
        self.assertEqual(processor.calls, [(48000, 31)])
        self.assertEqual(engine.status().current_delay_secondary_ms, 0)

    def test_delay_increase_and_decrease_are_crossfaded(self) -> None:
        delay = _NumpyDelayLine(1000, 1, 0, np)
        signal = np.ones((100, 1), dtype=np.float32)
        self.assertTrue(np.allclose(delay.process(signal), 1.0))
        delay.set_delay(1000, 40)
        increasing = delay.process(signal)
        delay.set_delay(1000, 0)
        decreasing = delay.process(signal)
        self.assertTrue(np.all(np.isfinite(increasing)))
        self.assertTrue(np.all(np.isfinite(decreasing)))
        self.assertLess(float(np.max(np.abs(np.diff(increasing[:, 0])))), 0.1)
        self.assertLess(float(np.max(np.abs(np.diff(decreasing[:, 0])))), 0.1)

    def test_noise_gate_holds_then_releases(self) -> None:
        engine = AudioEngine()
        loud = np.full((480, 2), 0.05, dtype=np.float32)
        quiet = np.zeros((480, 2), dtype=np.float32)
        engine._prepare_capture_block(loud, np, self.config())
        held = engine._prepare_capture_block(quiet, np, self.config())
        for _ in range(30):
            released = engine._prepare_capture_block(quiet, np, self.config())
        self.assertGreater(float(engine._gate.gain), 0.0)  # type: ignore[union-attr]
        self.assertTrue(np.allclose(held, 0.0))
        self.assertLess(float(np.max(np.abs(released))), 1e-5)

    def test_adaptive_resampling_is_small_and_bounded(self) -> None:
        block = np.arange(10000, dtype=np.float32).reshape((-1, 1))
        faster = _AdaptiveResampler.process(block, 1200, np)
        slower = _AdaptiveResampler.process(block, -1200, np)
        self.assertLess(len(faster), len(block))
        self.assertGreater(len(slower), len(block))
        self.assertEqual(_AdaptiveResampler.correction_ppm(99), 1200)

    def test_queue_overflow_recovers_all_outputs_together(self) -> None:
        engine = AudioEngine()
        first = queue.Queue(maxsize=1)
        second = queue.Queue(maxsize=1)
        first.put(np.zeros((4, 2), dtype=np.float32))
        second.put(np.zeros((4, 2), dtype=np.float32))
        engine._queues = {"primary": first, "secondary": second}
        replacement = np.ones((4, 2), dtype=np.float32)
        engine._enqueue_outputs(replacement)
        self.assertTrue(np.array_equal(first.get(), replacement))
        self.assertTrue(np.array_equal(second.get(), replacement))
        self.assertEqual(engine.status().buffer_overruns, 1)

    def test_worker_failure_cancels_sibling_cycle(self) -> None:
        class BrokenPlayer:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def play(self, block) -> None:
                raise RuntimeError("device removed")

        class BrokenSpeaker:
            def player(self, samplerate: int, channels: int):
                return BrokenPlayer()

        engine = AudioEngine()
        engine._config = self.config()
        engine._stop.clear()
        engine._cycle_stop.clear()
        blocks = queue.Queue()
        blocks.put(np.ones((8, 2), dtype=np.float32))
        delay = _NumpyDelayLine(48000, 2, 0, np)
        engine._render_worker(BrokenSpeaker(), blocks, delay, "primary", np)
        self.assertTrue(engine._cycle_stop.is_set())
        self.assertIn("device removed", engine._cycle_error or "")

    def test_disconnect_is_retried_and_session_recovers(self) -> None:
        engine = AudioEngine()
        engine._config = self.config()
        engine._stop.clear()
        calls = 0

        def cycle(config) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Bluetooth disconnected")
            engine._metrics.playback_state = PlaybackState.PLAYING
            engine._stop.set()

        engine._run_cycle = cycle  # type: ignore[method-assign]
        engine._run()
        self.assertEqual(calls, 2)
        self.assertEqual(engine.status().reconnect_attempts, 1)

    def test_capture_failure_without_reconnect_enters_error_state(self) -> None:
        engine = AudioEngine()
        config = self.config()
        config.automatic_reconnect = False
        engine._config = config
        engine._stop.clear()
        engine._run_cycle = lambda unused: (_ for _ in ()).throw(RuntimeError("capture failed"))  # type: ignore[method-assign]
        engine._run()
        self.assertEqual(engine.status().playback_state, PlaybackState.ERROR)
        self.assertIn("capture failed", engine.status().last_error or "")

    def test_repeated_start_stop_leaves_no_workers(self) -> None:
        class IdleEngine(AudioEngine):
            def _run(self) -> None:
                self._metrics.playback_state = PlaybackState.PLAYING
                self._stop.wait()

        engine = IdleEngine()
        for _ in range(5):
            engine.start(self.config())
            engine.stop()
        self.assertEqual(engine._output_threads, [])
        self.assertIsNone(engine._capture_thread)
        self.assertEqual(engine.status().active_playback_worker_count, 0)

    def test_fft_chirp_detection_finds_known_arrival(self) -> None:
        engine = AudioEngine()
        chirp = engine._calibration_chirp(np, 48000)
        recorded = np.zeros((48000, 1), dtype=np.float32)
        start = 7200
        recorded[start : start + len(chirp), 0] = chirp
        arrival, score = engine._detect_chirp(recorded, chirp, 48000, np)
        self.assertAlmostEqual(arrival, 150.0, places=2)
        self.assertGreater(score, 0.99)

    def test_long_running_delay_simulation_keeps_fixed_history(self) -> None:
        delay = _NumpyDelayLine(48000, 2, 120, np)
        block = np.random.default_rng(7).normal(0, 0.02, (480, 2)).astype(np.float32)
        for index in range(500):
            if index % 50 == 0:
                delay.set_delay(48000, float(index % 200))
            output = delay.process(block)
            self.assertEqual(output.shape, block.shape)
        self.assertEqual(len(delay._history), delay._max_frames + 2)


if __name__ == "__main__":
    unittest.main()
