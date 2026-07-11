from __future__ import annotations

from dataclasses import dataclass

from .models import DelaySettings, clamp_delay_ms


def compute_compensation(delay: DelaySettings) -> tuple[float, float]:
    """Return effective software delays for primary and secondary speakers."""
    delay.clamp()
    primary_total = delay.primary_estimated_ms + delay.primary_manual_ms
    secondary_total = delay.secondary_estimated_ms + delay.secondary_manual_ms
    target = max(primary_total, secondary_total)
    primary_auto = max(0.0, target - primary_total)
    secondary_auto = max(0.0, target - secondary_total)
    return delay.primary_manual_ms + primary_auto, delay.secondary_manual_ms + secondary_auto


def chunk_frames(sample_rate: int, buffer_ms: float) -> int:
    return max(1, round(sample_rate * buffer_ms / 1000.0))


@dataclass
class DriftEstimator:
    sample_rate: int
    smoothing: float = 0.08
    drift_ms: float = 0.0

    def observe(self, frame_count: int, elapsed_seconds: float) -> float:
        expected_seconds = frame_count / float(self.sample_rate)
        instant_ms = (elapsed_seconds - expected_seconds) * 1000.0
        self.drift_ms = (1.0 - self.smoothing) * self.drift_ms + self.smoothing * instant_ms
        return self.drift_ms


def delay_is_valid(value: float) -> bool:
    return clamp_delay_ms(value) == float(value)

