import tempfile
import unittest
from pathlib import Path

from twinsync_backend.device_manager import DeviceManager
from twinsync_backend.models import AudioDevice, ConnectionType
from twinsync_backend.service import TwinSyncService


class FakeProvider:
    def list_devices(self) -> list[AudioDevice]:
        return [
            AudioDevice(id="a", name="Bluetooth Speaker A", is_output=True, is_input=False, connection_type=ConnectionType.BLUETOOTH),
            AudioDevice(id="b", name="USB Speaker B", is_output=True, is_input=False, connection_type=ConnectionType.USB),
        ]


class FakeAudioEngine:
    def __init__(self) -> None:
        self.calibration_calls: list[tuple[str, str, int]] = []

    def status(self):
        from twinsync_backend.models import SyncMetrics

        return SyncMetrics()

    def set_delay(self, delay) -> None:
        pass

    def set_volume(self, volume) -> None:
        pass

    def play_calibration_pulses(self, primary_id: str, secondary_id: str, sample_rate: int) -> None:
        self.calibration_calls.append((primary_id, secondary_id, sample_rate))


class ServiceTests(unittest.TestCase):
    def test_selecting_same_speaker_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider()),
            )
            with self.assertRaises(ValueError):
                service.select_speakers("a", "a")

    def test_selection_and_profile_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider()),
            )
            status = service.select_speakers("a", "b")
            self.assertEqual(status["selection"]["primary_id"], "a")
            service.set_delay(primary_manual_ms=23, secondary_manual_ms=0)
            saved = service.save_profile("Desk Pair")
            self.assertEqual(saved["profiles"][0]["name"], "Desk Pair")

    def test_partial_selection_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "twinsync.sqlite3"
            service = TwinSyncService(
                db_path=path,
                device_manager=DeviceManager(FakeProvider()),
            )
            status = service.select_speakers("a", None)
            self.assertEqual(status["selection"]["primary_id"], "a")
            self.assertIsNone(status["selection"]["secondary_id"])

            reloaded = TwinSyncService(
                db_path=path,
                device_manager=DeviceManager(FakeProvider()),
            )
            self.assertEqual(reloaded.status()["selection"]["primary_id"], "a")
            self.assertIsNone(reloaded.status()["selection"]["secondary_id"])

    def test_calibration_plays_both_selected_speakers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider()),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            result = service.calibrate()
            self.assertEqual(result["status"], "guided_required")
            self.assertEqual(audio.calibration_calls, [("a", "b", 48000)])


if __name__ == "__main__":
    unittest.main()
