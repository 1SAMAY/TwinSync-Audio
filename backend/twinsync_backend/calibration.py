from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import median

from .models import CalibrationMode, DelaySettings


@dataclass(frozen=True)
class CalibrationResult:
    mode: CalibrationMode
    status: str
    message: str
    applied_delay: DelaySettings
    confidence: float | None = None
    relative_delay_ms: float | None = None
    accepted_measurements: int = 0
    applied: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "status": self.status,
            "message": self.message,
            "confidence": self.confidence,
            "relative_delay_ms": self.relative_delay_ms,
            "accepted_measurements": self.accepted_measurements,
            "applied": self.applied,
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
                applied_delay=replace(delay),
            )
        raise ValueError("Automatic calibration measurements must be supplied by the audio runtime.")

    def finish(
        self,
        delay: DelaySettings,
        primary_arrivals_ms: list[float],
        secondary_arrivals_ms: list[float],
        correlations: list[float],
        minimum_confidence: float = 0.65,
    ) -> CalibrationResult:
        if len(primary_arrivals_ms) != len(secondary_arrivals_ms) or len(correlations) != len(primary_arrivals_ms):
            raise ValueError("Calibration measurement sets must have the same length.")
        if len(primary_arrivals_ms) < 3:
            raise ValueError("Automatic calibration requires at least three measurements per speaker.")

        offsets = [secondary - primary for primary, secondary in zip(primary_arrivals_ms, secondary_arrivals_ms)]
        centre = median(offsets)
        deviations = [abs(value - centre) for value in offsets]
        mad = median(deviations)
        limit = max(1.5, 3.0 * mad)
        accepted = [index for index, value in enumerate(offsets) if abs(value - centre) <= limit]
        filtered = [offsets[index] for index in accepted]
        relative_delay_ms = median(filtered)
        repeatability = max(0.0, 1.0 - (max(filtered) - min(filtered)) / 12.0)
        signal_confidence = median([max(0.0, min(1.0, correlations[index])) for index in accepted])
        sample_confidence = min(1.0, len(accepted) / 3.0)
        confidence = round(signal_confidence * repeatability * sample_confidence, 3)
        applied = replace(delay)

        if confidence >= minimum_confidence:
            applied.primary_estimated_ms = max(0.0, -relative_delay_ms)
            applied.secondary_estimated_ms = max(0.0, relative_delay_ms)
            applied.clamp()
            return CalibrationResult(
                mode=CalibrationMode.AUTOMATIC,
                status="calibrated",
                message=f"Acoustic calibration measured {relative_delay_ms:+.2f} ms with {confidence:.0%} confidence.",
                applied_delay=applied,
                confidence=confidence,
                relative_delay_ms=relative_delay_ms,
                accepted_measurements=len(accepted),
                applied=True,
            )

        return CalibrationResult(
            mode=CalibrationMode.AUTOMATIC,
            status="low_confidence",
            message=f"Calibration confidence was {confidence:.0%}; no delay was changed. Reduce background noise and retry.",
            applied_delay=applied,
            confidence=confidence,
            relative_delay_ms=relative_delay_ms,
            accepted_measurements=len(accepted),
            applied=False,
        )
