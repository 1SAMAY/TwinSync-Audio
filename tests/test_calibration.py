import unittest

from twinsync_backend.calibration import CalibrationService
from twinsync_backend.models import DelaySettings


class CalibrationTests(unittest.TestCase):
    def test_consistent_measurements_apply_relative_hardware_latency(self) -> None:
        result = CalibrationService().finish(
            DelaySettings(primary_manual_ms=7),
            [150.0, 151.0, 149.5, 300.0],
            [182.0, 183.2, 181.4, 90.0],
            [0.94, 0.92, 0.95, 0.2],
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.accepted_measurements, 3)
        self.assertAlmostEqual(result.applied_delay.secondary_estimated_ms, 32.0, places=1)
        self.assertEqual(result.applied_delay.primary_manual_ms, 7)

    def test_low_confidence_does_not_change_delay(self) -> None:
        original = DelaySettings(primary_estimated_ms=12, secondary_estimated_ms=30)
        result = CalibrationService().finish(
            original,
            [100.0, 100.0, 100.0],
            [120.0, 132.0, 109.0],
            [0.3, 0.25, 0.2],
        )
        self.assertFalse(result.applied)
        self.assertEqual(result.applied_delay, original)


if __name__ == "__main__":
    unittest.main()
