import unittest

from twinsync_backend.delay import DriftEstimator, chunk_frames, compute_compensation, delay_is_valid
from twinsync_backend.models import DelaySettings


class DelayTests(unittest.TestCase):
    def test_compensation_delays_faster_speaker(self) -> None:
        delay = DelaySettings(primary_estimated_ms=170, secondary_estimated_ms=245)
        primary, secondary = compute_compensation(delay)
        self.assertEqual(primary, 75)
        self.assertEqual(secondary, 0)

    def test_manual_delay_is_clamped(self) -> None:
        delay = DelaySettings(primary_manual_ms=-4, secondary_manual_ms=999)
        compute_compensation(delay)
        self.assertEqual(delay.primary_manual_ms, 0)
        self.assertEqual(delay.secondary_manual_ms, 500)

    def test_manual_trim_never_delays_the_other_speaker(self) -> None:
        primary, secondary = compute_compensation(DelaySettings(primary_manual_ms=37))
        self.assertEqual((primary, secondary), (37, 0))

        primary, secondary = compute_compensation(DelaySettings(secondary_manual_ms=42))
        self.assertEqual((primary, secondary), (0, 42))

    def test_chunk_frames(self) -> None:
        self.assertEqual(chunk_frames(48000, 10), 480)
        self.assertEqual(chunk_frames(44100, 60), 2646)

    def test_drift_estimator_smooths_timing(self) -> None:
        drift = DriftEstimator(sample_rate=48000)
        value = drift.observe(480, 0.012)
        self.assertGreater(value, 0)
        self.assertTrue(delay_is_valid(250))
        self.assertFalse(delay_is_valid(501))


if __name__ == "__main__":
    unittest.main()

