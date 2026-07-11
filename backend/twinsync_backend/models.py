from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

MAX_MANUAL_DELAY_MS = 500
SUPPORTED_SAMPLE_RATES = (44100, 48000, 96000)
SUPPORTED_BIT_DEPTHS = (16, 24)


class ConnectionType(str, Enum):
    BLUETOOTH = "Bluetooth"
    USB = "USB"
    HDMI = "HDMI"
    BUILT_IN = "Built-in"
    VIRTUAL = "Virtual"
    UNKNOWN = "Unknown"


class DeviceStatus(str, Enum):
    AVAILABLE = "available"
    SELECTED = "selected"
    UNAVAILABLE = "unavailable"


class PlaybackState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    PLAYING = "playing"
    ERROR = "error"


class CalibrationMode(str, Enum):
    AUTOMATIC = "automatic"
    GUIDED = "guided"


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    is_output: bool
    is_input: bool
    connection_type: ConnectionType
    is_default: bool = False
    channels: int | None = None
    sample_rates: tuple[int, ...] = field(default_factory=lambda: SUPPORTED_SAMPLE_RATES)
    codec: str | None = None
    battery_percent: int | None = None
    current_latency_ms: float | None = None
    signal_strength_percent: int | None = None
    status: DeviceStatus = DeviceStatus.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["connection_type"] = self.connection_type.value
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class SpeakerSelection:
    primary_id: str | None = None
    secondary_id: str | None = None

    def validate(self) -> None:
        if self.primary_id and self.secondary_id and self.primary_id == self.secondary_id:
            raise ValueError("Primary and secondary speakers must be different devices.")


@dataclass
class DelaySettings:
    primary_manual_ms: float = 0.0
    secondary_manual_ms: float = 0.0
    primary_estimated_ms: float = 0.0
    secondary_estimated_ms: float = 0.0

    def clamp(self) -> None:
        self.primary_manual_ms = clamp_delay_ms(self.primary_manual_ms)
        self.secondary_manual_ms = clamp_delay_ms(self.secondary_manual_ms)


@dataclass
class VolumeSettings:
    master: float = 1.0
    primary: float = 1.0
    secondary: float = 1.0
    muted: bool = False
    balance: float = 0.0

    def clamp(self) -> None:
        self.master = clamp_unit(self.master)
        self.primary = clamp_unit(self.primary)
        self.secondary = clamp_unit(self.secondary)
        self.balance = max(-1.0, min(1.0, float(self.balance)))


@dataclass
class AudioMode:
    name: str = "Balanced"
    sample_rate: int = 48000
    bit_depth: int = 24
    channels: int = 2
    buffer_ms: int = 60

    def validate(self) -> None:
        if self.sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"Unsupported sample rate: {self.sample_rate}")
        if self.bit_depth not in SUPPORTED_BIT_DEPTHS:
            raise ValueError(f"Unsupported bit depth: {self.bit_depth}")
        if self.channels not in (1, 2):
            raise ValueError("TwinSync supports mono or stereo output.")
        if not 10 <= self.buffer_ms <= 250:
            raise ValueError("Buffer size must be between 10 and 250 ms.")


@dataclass
class SpeakerProfile:
    name: str
    selection: SpeakerSelection
    delay: DelaySettings
    volume: VolumeSettings
    audio_mode: AudioMode
    primary_display_name: str | None = None
    secondary_display_name: str | None = None
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "selection": asdict(self.selection),
            "primary_display_name": self.primary_display_name,
            "secondary_display_name": self.secondary_display_name,
            "delay": asdict(self.delay),
            "volume": asdict(self.volume),
            "audio_mode": asdict(self.audio_mode),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpeakerProfile":
        return cls(
            id=data.get("id"),
            name=str(data["name"]),
            selection=SpeakerSelection(**data["selection"]),
            primary_display_name=data.get("primary_display_name"),
            secondary_display_name=data.get("secondary_display_name"),
            delay=DelaySettings(**data["delay"]),
            volume=VolumeSettings(**data["volume"]),
            audio_mode=AudioMode(**data["audio_mode"]),
        )


@dataclass
class SyncMetrics:
    playback_state: PlaybackState = PlaybackState.STOPPED
    current_delay_primary_ms: float = 0.0
    current_delay_secondary_ms: float = 0.0
    estimated_drift_ms: float = 0.0
    buffer_size_ms: float = 0.0
    dropped_frames: int = 0
    sample_rate: int = 48000
    bit_depth: int = 24
    cpu_usage_percent: float | None = None
    connection_health: str = "idle"
    last_error: str | None = None
    selected_output_count: int = 0
    active_output_stream_count: int = 0
    active_playback_worker_count: int = 0
    preview_stream_count: int = 0
    routing_session_count: int = 0
    queue_depths: dict[str, int] = field(default_factory=dict)
    routing_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["playback_state"] = self.playback_state.value
        return data


def clamp_delay_ms(value: float) -> float:
    return max(0.0, min(float(value), float(MAX_MANUAL_DELAY_MS)))


def clamp_unit(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
