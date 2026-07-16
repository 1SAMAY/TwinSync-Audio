from __future__ import annotations

from dataclasses import dataclass

from .models import DelaySettings, clamp_delay_ms


def compute_compensation(delay: DelaySettings) -> tuple[float, float]:
    """Return effective software delays for primary and secondary speakers."""
    primary_auto, secondary_auto = automatic_compensation(delay)
    return delay.primary_manual_ms + primary_auto, delay.secondary_manual_ms + secondary_auto


def automatic_compensation(delay: DelaySettings) -> tuple[float, float]:
    """Delay only the lower-latency endpoint; manual trims remain independent."""
    delay.clamp()
    target = max(delay.primary_estimated_ms, delay.secondary_estimated_ms)
    return target - delay.primary_estimated_ms, target - delay.secondary_estimated_ms


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

