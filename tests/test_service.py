import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

from twinsync_backend.device_manager import DeviceManager
from twinsync_backend.models import AudioDevice, ConnectionType, PlaybackState, SyncMetrics
from twinsync_backend.service import TwinSyncService


class FakeProvider:
    def __init__(self, device_ids: tuple[str, ...] = ("a", "b"), default_id: str = "a") -> None:
        self.device_ids = device_ids
        self.default_id = default_id

    def list_devices(self) -> list[AudioDevice]:
        names = {"a": "Bluetooth Speaker A", "b": "USB Speaker B", "c": "Bluetooth Speaker C"}
        return [
            AudioDevice(
                id=device_id,
                name=names.get(device_id, device_id),
                is_output=True,
                is_input=False,
                connection_type=ConnectionType.BLUETOOTH if device_id in ("a", "c") else ConnectionType.USB,
                is_default=device_id == self.default_id,
            )
            for device_id in self.device_ids
        ]


class FakeAudioEngine:
    def __init__(self) -> None:
        self.calibration_calls: list[tuple[str, str, int]] = []
        self.start_calls = []
        self.stop_calls = 0
        self.metrics = SyncMetrics()

    def status(self):
        return self.metrics

    def start(self, config) -> None:
        self.start_calls.append(config)
        self.metrics.playback_state = PlaybackState.PLAYING

    def stop(self) -> None:
        self.stop_calls += 1
        self.metrics.playback_state = PlaybackState.STOPPED

    def set_delay(self, delay) -> None:
        pass

    def set_volume(self, volume) -> None:
        pass

    def play_calibration_pulses(self, primary_id: str, secondary_id: str, sample_rate: int) -> None:
        self.calibration_calls.append((primary_id, secondary_id, sample_rate))

    def measure_acoustic_latency(self, primary_id: str, secondary_id: str, measurement_input_id: str, sample_rate: int):
        return {
            "primary_arrivals_ms": [150.0, 150.4, 149.8],
            "secondary_arrivals_ms": [177.0, 177.5, 176.9],
            "correlations": [0.94, 0.93, 0.95],
            "background_noise_rms": 0.004,
            "microphone_level_rms": 0.08,
        }


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
            self.assertEqual(saved["profiles"][0]["primary_display_name"], "Bluetooth Speaker A")
            self.assertEqual(saved["profiles"][0]["secondary_display_name"], "USB Speaker B")

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

    def test_unselected_windows_default_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider(("a", "b", "c"), default_id="c")),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            with self.assertRaisesRegex(ValueError, "Windows default output"):
                service.start_playback()
            self.assertEqual(audio.start_calls, [])

    def test_selected_windows_default_output_can_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider(("a", "b", "c"), default_id="a")),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            service.start_playback()
            self.assertEqual((audio.start_calls[0].primary_id, audio.start_calls[0].secondary_id), ("a", "b"))

    def test_selection_change_stops_active_playback_and_keeps_only_new_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider(("a", "b", "c"), default_id="a")),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            service.start_playback()
            service.select_speakers("a", "c")
            self.assertEqual(audio.stop_calls, 1)
            self.assertEqual(service.status()["selection"], {"primary_id": "a", "secondary_id": "c"})

    def test_profile_load_rejects_missing_saved_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "twinsync.sqlite3"
            service = TwinSyncService(
                db_path=path,
                device_manager=DeviceManager(FakeProvider(("a", "b"), default_id="a")),
            )
            service.select_speakers("a", "b")
            profile_id = service.save_profile("Desk Pair")["id"]

            reloaded = TwinSyncService(
                db_path=path,
                device_manager=DeviceManager(FakeProvider(("a", "c"), default_id="a")),
            )
            with self.assertRaisesRegex(ValueError, "b"):
                reloaded.load_profile(profile_id)

    def test_custom_source_can_start_when_windows_default_is_unselected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider(("a", "b", "c"), default_id="c")),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            service.state.source_id = "virtual-loopback"
            service.start_playback()
            self.assertEqual(len(audio.start_calls), 1)

    def test_microphone_calibration_applies_only_confident_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider()),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            result = service.calibrate("measurement-mic")
            self.assertTrue(result["applied"])
            self.assertGreater(result["confidence"], 0.9)
            self.assertAlmostEqual(service.state.delay.secondary_estimated_ms, 27.1, places=1)
            self.assertEqual(result["background_noise_rms"], 0.004)

    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = TwinSyncService(db_path=Path(temp) / "twinsync.sqlite3")
            settings = service.set_settings(automatic_reconnect=False, developer_mode=True)
            self.assertFalse(settings["automatic_reconnect"])
            self.assertTrue(settings["developer_mode"])

    def test_diagnostics_export_omits_device_ids_and_error_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio = FakeAudioEngine()
            audio.metrics.last_error = "private-device-id failed"
            service = TwinSyncService(
                db_path=Path(temp) / "twinsync.sqlite3",
                device_manager=DeviceManager(FakeProvider()),
                audio_engine=audio,
            )
            service.select_speakers("a", "b")
            with patch.dict(os.environ, {"TWINSYNC_DATA_DIR": temp}):
                path = Path(service.export_diagnostics()["path"])
            payload = path.read_text(encoding="utf-8")
            self.assertNotIn("private-device-id", payload)
            self.assertNotIn('"primary_id"', payload)
            self.assertTrue(json.loads(payload)["metrics"]["last_error_present"])


if __name__ == "__main__":
    unittest.main()
