from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .audio_engine import AudioEngine, PlaybackConfig
from .calibration import CalibrationService
from .database import TwinSyncDatabase, default_profile
from .delay import compute_compensation
from .device_manager import DeviceManager
from .models import AudioDevice, AudioMode, DelaySettings, PlaybackState, SpeakerProfile, SpeakerSelection, VolumeSettings


@dataclass
class AppState:
    selection: SpeakerSelection
    delay: DelaySettings
    volume: VolumeSettings
    audio_mode: AudioMode
    source_id: str | None = None


class TwinSyncService:
    def __init__(
        self,
        db_path: Path | None = None,
        device_manager: DeviceManager | None = None,
        audio_engine: AudioEngine | None = None,
    ) -> None:
        self.db = TwinSyncDatabase(db_path)
        self.devices = device_manager or DeviceManager()
        self.audio = audio_engine or AudioEngine()
        self.calibration = CalibrationService()
        self.state = self._load_state()

    def dispatch(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        handlers = {
            "status": self.status,
            "devices": self.list_devices,
            "select_speakers": self.select_speakers,
            "start": self.start_playback,
            "stop": self.stop_playback,
            "set_delay": self.set_delay,
            "set_volume": self.set_volume,
            "set_mode": self.set_mode,
            "test_sound": self.test_sound,
            "calibrate": self.calibrate,
            "save_profile": self.save_profile,
            "load_profile": self.load_profile,
            "profiles": self.list_profiles,
            "events": self.events,
            "settings": self.settings,
        }
        if method not in handlers:
            raise KeyError(f"Unknown backend method: {method}")
        return handlers[method](**params)

    def status(self) -> dict[str, Any]:
        metrics = self.audio.status()
        return {
            "selection": asdict(self.state.selection),
            "delay": asdict(self.state.delay),
            "volume": asdict(self.state.volume),
            "audio_mode": asdict(self.state.audio_mode),
            "effective_delay": {
                "primary_ms": compute_compensation(self.state.delay)[0],
                "secondary_ms": compute_compensation(self.state.delay)[1],
            },
            "metrics": metrics.to_dict(),
            "events": self.db.recent_events(12),
        }

    def list_devices(self) -> list[dict[str, Any]]:
        return [device.to_dict() for device in self.devices.list_devices()]

    def select_speakers(self, primary_id: str | None = None, secondary_id: str | None = None) -> dict[str, Any]:
        selection = SpeakerSelection(primary_id=primary_id, secondary_id=secondary_id)
        selection.validate()
        if primary_id:
            self.devices.require_output(primary_id)
        if secondary_id:
            self.devices.require_output(secondary_id)
        if self.audio.status().playback_state not in (PlaybackState.STOPPED, PlaybackState.ERROR):
            self.audio.stop()
            self.db.log_event("playback", "Playback stopped before speaker selection changed")
        self.state.selection = selection
        self._persist_state()
        self.db.log_event("device", "Speaker selection changed", asdict(selection))
        return self.status()

    def start_playback(self) -> dict[str, Any]:
        primary, secondary = self._require_selected_pair()
        self._guard_unselected_default_output({primary.id, secondary.id})
        config = PlaybackConfig(
            source_id=self.state.source_id,
            primary_id=primary.id,
            secondary_id=secondary.id,
            delay=self.state.delay,
            volume=self.state.volume,
            audio_mode=self.state.audio_mode,
        )
        self.audio.start(config)
        self.db.log_event("playback", "Playback started", asdict(self.state.selection))
        return self.status()

    def stop_playback(self) -> dict[str, Any]:
        self.audio.stop()
        self.db.log_event("playback", "Playback stopped")
        return self.status()

    def set_delay(
        self,
        primary_manual_ms: float | None = None,
        secondary_manual_ms: float | None = None,
        primary_estimated_ms: float | None = None,
        secondary_estimated_ms: float | None = None,
    ) -> dict[str, Any]:
        if primary_manual_ms is not None:
            self.state.delay.primary_manual_ms = primary_manual_ms
        if secondary_manual_ms is not None:
            self.state.delay.secondary_manual_ms = secondary_manual_ms
        if primary_estimated_ms is not None:
            self.state.delay.primary_estimated_ms = primary_estimated_ms
        if secondary_estimated_ms is not None:
            self.state.delay.secondary_estimated_ms = secondary_estimated_ms
        self.state.delay.clamp()
        self.audio.set_delay(self.state.delay)
        self._persist_state()
        self.db.log_event("sync", "Delay changed", asdict(self.state.delay))
        return self.status()

    def set_volume(
        self,
        master: float | None = None,
        primary: float | None = None,
        secondary: float | None = None,
        muted: bool | None = None,
        balance: float | None = None,
    ) -> dict[str, Any]:
        if master is not None:
            self.state.volume.master = master
        if primary is not None:
            self.state.volume.primary = primary
        if secondary is not None:
            self.state.volume.secondary = secondary
        if muted is not None:
            self.state.volume.muted = bool(muted)
        if balance is not None:
            self.state.volume.balance = balance
        self.state.volume.clamp()
        self.audio.set_volume(self.state.volume)
        self._persist_state()
        self.db.log_event("volume", "Volume changed", asdict(self.state.volume))
        return self.status()

    def set_mode(self, name: str, sample_rate: int, bit_depth: int, channels: int, buffer_ms: int) -> dict[str, Any]:
        mode = AudioMode(name=name, sample_rate=sample_rate, bit_depth=bit_depth, channels=channels, buffer_ms=buffer_ms)
        mode.validate()
        self.state.audio_mode = mode
        self._persist_state()
        self.db.log_event("settings", "Audio mode changed", asdict(mode))
        return self.status()

    def test_sound(self, device_id: str) -> dict[str, Any]:
        self.audio.play_test_sound(device_id, self.state.audio_mode.sample_rate)
        self.db.log_event("device", "Test sound played", {"device_id": device_id})
        return self.status()

    def calibrate(self, measurement_input_id: str | None = None) -> dict[str, Any]:
        self.state.selection.validate()
        if not self.state.selection.primary_id or not self.state.selection.secondary_id:
            raise ValueError("Select primary and secondary speakers before calibration.")
        self.audio.play_calibration_pulses(
            self.state.selection.primary_id,
            self.state.selection.secondary_id,
            self.state.audio_mode.sample_rate,
        )
        result = self.calibration.start(self.state.delay, measurement_input_id)
        self.db.log_event("calibration", result.message, result.to_dict())
        return result.to_dict()

    def save_profile(self, name: str) -> dict[str, Any]:
        primary = self.devices.require_output(self.state.selection.primary_id) if self.state.selection.primary_id else None
        secondary = self.devices.require_output(self.state.selection.secondary_id) if self.state.selection.secondary_id else None
        profile = SpeakerProfile(
            name=name.strip() or "Speaker Pair",
            selection=self.state.selection,
            primary_display_name=primary.name if primary else None,
            secondary_display_name=secondary.name if secondary else None,
            delay=self.state.delay,
            volume=self.state.volume,
            audio_mode=self.state.audio_mode,
        )
        profile_id = self.db.save_profile(profile)
        self.db.log_event("profile", "Profile saved", {"id": profile_id, "name": profile.name})
        return {"id": profile_id, "profiles": self.list_profiles()}

    def load_profile(self, profile_id: int) -> dict[str, Any]:
        profile = self.db.get_profile(profile_id)
        profile.selection.validate()
        if profile.selection.primary_id:
            self.devices.require_output(profile.selection.primary_id)
        if profile.selection.secondary_id:
            self.devices.require_output(profile.selection.secondary_id)
        if self.audio.status().playback_state not in (PlaybackState.STOPPED, PlaybackState.ERROR):
            self.audio.stop()
            self.db.log_event("playback", "Playback stopped before profile load")
        self.state = AppState(
            selection=profile.selection,
            delay=profile.delay,
            volume=profile.volume,
            audio_mode=profile.audio_mode,
        )
        self._persist_state()
        self.audio.set_delay(self.state.delay)
        self.audio.set_volume(self.state.volume)
        self.db.log_event("profile", "Profile loaded", {"id": profile_id, "name": profile.name})
        return self.status()

    def list_profiles(self) -> list[dict[str, Any]]:
        return self.db.list_profiles()

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.recent_events(limit)

    def settings(self) -> dict[str, Any]:
        return {
            "auto_start": self.db.get_setting("auto_start", False),
            "start_minimized": self.db.get_setting("start_minimized", False),
            "automatic_reconnect": self.db.get_setting("automatic_reconnect", True),
            "developer_mode": self.db.get_setting("developer_mode", False),
            "language": self.db.get_setting("language", "en"),
        }

    def _load_state(self) -> AppState:
        payload = self.db.get_setting("state")
        if payload:
            return AppState(
                selection=SpeakerSelection(**payload["selection"]),
                delay=DelaySettings(**payload["delay"]),
                volume=VolumeSettings(**payload["volume"]),
                audio_mode=AudioMode(**payload["audio_mode"]),
                source_id=payload.get("source_id"),
            )
        profile = default_profile()
        return AppState(
            selection=profile.selection,
            delay=profile.delay,
            volume=profile.volume,
            audio_mode=profile.audio_mode,
        )

    def _persist_state(self) -> None:
        self.db.set_setting(
            "state",
            {
                "selection": asdict(self.state.selection),
                "delay": asdict(self.state.delay),
                "volume": asdict(self.state.volume),
                "audio_mode": asdict(self.state.audio_mode),
                "source_id": self.state.source_id,
            },
        )

    def _require_selected_pair(self) -> tuple[AudioDevice, AudioDevice]:
        self.state.selection.validate()
        if not self.state.selection.primary_id or not self.state.selection.secondary_id:
            raise ValueError("Select primary and secondary speakers before starting playback.")
        primary = self.devices.require_output(self.state.selection.primary_id)
        secondary = self.devices.require_output(self.state.selection.secondary_id)
        if primary.id == secondary.id:
            raise ValueError("Primary and secondary speakers must resolve to different output devices.")
        return primary, secondary

    def _guard_unselected_default_output(self, selected_ids: set[str]) -> None:
        if self.state.source_id:
            return
        default_output = self.devices.default_output()
        if default_output and default_output.id not in selected_ids:
            raise ValueError(
                "Windows default output is not one of the selected TwinSync speakers. "
                f"Set Windows default output to Primary or Secondary before starting, or use a virtual routing source. "
                f"Current default: {default_output.name}"
            )
