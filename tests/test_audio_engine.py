import unittest

import numpy as np

from twinsync_backend.audio_engine import AudioEngine, PlaybackConfig
from twinsync_backend.models import AudioMode, DelaySettings, VolumeSettings


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


if __name__ == "__main__":
    unittest.main()

