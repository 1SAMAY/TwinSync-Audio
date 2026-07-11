import unittest

import numpy as np

from twinsync_backend.audio_engine import AudioEngine, PlaybackConfig
from twinsync_backend.models import AudioMode, DelaySettings, VolumeSettings


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


if __name__ == "__main__":
    unittest.main()
