from __future__ import annotations

import importlib
import logging
from typing import Protocol

from .models import AudioDevice, ConnectionType

LOGGER = logging.getLogger(__name__)


class DeviceProvider(Protocol):
    def list_devices(self) -> list[AudioDevice]:
        ...


def infer_connection_type(name: str) -> ConnectionType:
    lowered = name.lower()
    if "bluetooth" in lowered or "bt-" in lowered or "buds" in lowered or "airpods" in lowered:
        return ConnectionType.BLUETOOTH
    if "usb" in lowered:
        return ConnectionType.USB
    if "hdmi" in lowered or "display audio" in lowered:
        return ConnectionType.HDMI
    if "realtek" in lowered or "speakers" in lowered or "built-in" in lowered:
        return ConnectionType.BUILT_IN
    if "virtual" in lowered or "vb-audio" in lowered or "voicemeeter" in lowered:
        return ConnectionType.VIRTUAL
    return ConnectionType.UNKNOWN


class SoundcardDeviceProvider:
    def list_devices(self) -> list[AudioDevice]:
        try:
            soundcard = importlib.import_module("soundcard")
        except ImportError as exc:
            raise RuntimeError(
                "The Windows audio backend is not installed. Run `python -m pip install -e .[windows]`."
            ) from exc

        devices: list[AudioDevice] = []
        default_speaker = soundcard.default_speaker()
        default_speaker_name = str(getattr(default_speaker, "name", ""))
        default_speaker_id = str(getattr(default_speaker, "id", ""))
        for speaker in soundcard.all_speakers():
            name = str(getattr(speaker, "name", speaker))
            device_id = str(getattr(speaker, "id", name))
            is_default = device_id == default_speaker_id if default_speaker_id else name == default_speaker_name
            devices.append(
                AudioDevice(
                    id=device_id,
                    name=name,
                    is_output=True,
                    is_input=False,
                    connection_type=infer_connection_type(name),
                    is_default=is_default,
                    channels=getattr(speaker, "channels", None),
                    # Windows does not expose Bluetooth codec, battery, and RF signal strength
                    # through this local audio API for every device. Leaving these as None keeps
                    # diagnostics truthful instead of fabricating unavailable telemetry.
                    codec=None,
                    battery_percent=None,
                    signal_strength_percent=None,
                )
            )

        try:
            microphones = soundcard.all_microphones(include_loopback=True)
        except TypeError:
            microphones = soundcard.all_microphones()

        for microphone in microphones:
            name = str(getattr(microphone, "name", microphone))
            device_id = str(getattr(microphone, "id", name))
            devices.append(
                AudioDevice(
                    id=device_id,
                    name=name,
                    is_output=False,
                    is_input=True,
                    connection_type=infer_connection_type(name),
                    channels=getattr(microphone, "channels", None),
                )
            )

        return devices


class DeviceManager:
    def __init__(self, provider: DeviceProvider | None = None) -> None:
        self.provider = provider or SoundcardDeviceProvider()

    def list_devices(self) -> list[AudioDevice]:
        devices = self.provider.list_devices()
        LOGGER.info("Detected %s audio devices", len(devices))
        return devices

    def output_devices(self) -> list[AudioDevice]:
        return [device for device in self.list_devices() if device.is_output]

    def default_output(self) -> AudioDevice | None:
        for device in self.output_devices():
            if device.is_default:
                return device
        return None

    def require_output(self, device_id: str) -> AudioDevice:
        for device in self.output_devices():
            if device.id == device_id:
                return device
        raise ValueError(f"Output device is not available: {device_id}")
