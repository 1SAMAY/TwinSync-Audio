from __future__ import annotations

from dataclasses import dataclass

from .models import CalibrationMode, DelaySettings


@dataclass(frozen=True)
class CalibrationResult:
    mode: CalibrationMode
    status: str
    message: str
    applied_delay: DelaySettings

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "status": self.status,
            "message": self.message,
            "applied_delay": {
                "primary_manual_ms": self.applied_delay.primary_manual_ms,
                "secondary_manual_ms": self.applied_delay.secondary_manual_ms,
                "primary_estimated_ms": self.applied_delay.primary_estimated_ms,
                "secondary_estimated_ms": self.applied_delay.secondary_estimated_ms,
            },
        }


class CalibrationService:
    def start(self, delay: DelaySettings, measurement_input_id: str | None = None) -> CalibrationResult:
        if not measurement_input_id:
            # The Windows render path can tell us when samples were submitted to each endpoint,
            # but not when Bluetooth speakers physically emit sound. Acoustic latency requires
            # a microphone or hardware loopback, so the safe fallback is guided calibration.
            return CalibrationResult(
                mode=CalibrationMode.GUIDED,
                status="guided_required",
                message="Calibration pulses were played on both speakers. No measurement input was selected, so adjust the delay sliders until the final pulse sounds centered, then save the profile.",
                applied_delay=delay,
            )
        return CalibrationResult(
            mode=CalibrationMode.AUTOMATIC,
            status="measurement_input_required_by_runtime",
            message="Measurement input was provided. Use the calibration pulses to estimate acoustic offset and apply the measured delay.",
            applied_delay=delay,
        )
