import { useEffect } from "react";

const COMMON_REFRESH_RATES = [60, 75, 90, 120, 144, 165, 240] as const;
const FALLBACK_REFRESH_RATE = 60;
const SAMPLE_COUNT = 80;
const WARMUP_FRAMES = 8;
const MIN_FRAME_MS = 3;
const MAX_FRAME_MS = 60;

type UiPerformanceSnapshot = {
  estimatedRefreshRate: number;
  estimatedFrameMs: number;
  renderedFps: number;
  averageFrameMs: number;
  p95FrameMs: number;
  longFrames: number;
  sampleCount: number;
  lastUpdatedAt: number;
};

declare global {
  interface Window {
    __twinsyncUiPerformance?: UiPerformanceSnapshot;
  }
}

function percentile(sortedValues: number[], ratio: number): number {
  if (sortedValues.length === 0) return 0;
  const index = Math.min(sortedValues.length - 1, Math.floor((sortedValues.length - 1) * ratio));
  return sortedValues[index];
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function nearestCommonRefreshRate(rate: number): number {
  let nearest = FALLBACK_REFRESH_RATE;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const candidate of COMMON_REFRESH_RATES) {
    const distance = Math.abs(candidate - rate);
    if (distance < nearestDistance) {
      nearest = candidate;
      nearestDistance = distance;
    }
  }
  return nearestDistance <= nearest * 0.08 ? nearest : Math.round(rate);
}

function stableIntervals(timestamps: number[]): number[] {
  const intervals = timestamps
    .slice(WARMUP_FRAMES + 1)
    .map((timestamp, index) => timestamp - timestamps[index + WARMUP_FRAMES])
    .filter((interval) => interval >= MIN_FRAME_MS && interval <= MAX_FRAME_MS)
    .sort((a, b) => a - b);

  if (intervals.length < 8) return intervals;
  const trim = Math.max(1, Math.floor(intervals.length * 0.1));
  return intervals.slice(trim, intervals.length - trim);
}

function publishSnapshot(snapshot: UiPerformanceSnapshot) {
  window.__twinsyncUiPerformance = snapshot;
  document.documentElement.style.setProperty("--twinsync-refresh-rate", String(snapshot.estimatedRefreshRate));
  document.documentElement.style.setProperty("--twinsync-frame-ms", `${snapshot.estimatedFrameMs.toFixed(2)}ms`);
}

export function useDisplayPerformance() {
  useEffect(() => {
    let cancelled = false;
    let detectionFrame = 0;
    let monitorFrame = 0;
    let lastDetectionStartedAt = 0;
    const timestamps: number[] = [];

    const fallbackSnapshot: UiPerformanceSnapshot = {
      estimatedRefreshRate: FALLBACK_REFRESH_RATE,
      estimatedFrameMs: 1000 / FALLBACK_REFRESH_RATE,
      renderedFps: 0,
      averageFrameMs: 0,
      p95FrameMs: 0,
      longFrames: 0,
      sampleCount: 0,
      lastUpdatedAt: performance.now()
    };
    publishSnapshot(fallbackSnapshot);

    const startDetection = () => {
      if (cancelled || document.visibilityState === "hidden") return;
      const now = performance.now();
      if (now - lastDetectionStartedAt < 1200) return;
      lastDetectionStartedAt = now;
      timestamps.length = 0;
      cancelAnimationFrame(detectionFrame);

      const collect = (timestamp: number) => {
        if (cancelled || document.visibilityState === "hidden") return;
        timestamps.push(timestamp);
        if (timestamps.length < SAMPLE_COUNT) {
          detectionFrame = requestAnimationFrame(collect);
          return;
        }

        const intervals = stableIntervals(timestamps);
        const frameMs = intervals.length ? percentile(intervals, 0.5) : fallbackSnapshot.estimatedFrameMs;
        const refreshRate = nearestCommonRefreshRate(1000 / frameMs);
        publishSnapshot({
          ...window.__twinsyncUiPerformance,
          estimatedRefreshRate: refreshRate,
          estimatedFrameMs: 1000 / refreshRate,
          renderedFps: window.__twinsyncUiPerformance?.renderedFps ?? 0,
          averageFrameMs: window.__twinsyncUiPerformance?.averageFrameMs ?? 0,
          p95FrameMs: window.__twinsyncUiPerformance?.p95FrameMs ?? 0,
          longFrames: window.__twinsyncUiPerformance?.longFrames ?? 0,
          sampleCount: intervals.length,
          lastUpdatedAt: performance.now()
        });
      };

      detectionFrame = requestAnimationFrame(collect);
    };

    const monitorFrames = () => {
      if (!import.meta.env.DEV || cancelled) return;
      const frameTimes: number[] = [];
      let previous = performance.now();
      let lastPublished = previous;

      const tick = (timestamp: number) => {
        if (cancelled) return;
        if (document.visibilityState === "hidden") {
          monitorFrame = requestAnimationFrame(tick);
          previous = timestamp;
          return;
        }

        const frameMs = timestamp - previous;
        previous = timestamp;
        if (frameMs >= MIN_FRAME_MS && frameMs <= 250) {
          frameTimes.push(frameMs);
          if (frameTimes.length > 180) frameTimes.shift();
        }

        if (timestamp - lastPublished > 750 && frameTimes.length > 8) {
          const sorted = [...frameTimes].sort((a, b) => a - b);
          const avg = average(frameTimes);
          const p95 = percentile(sorted, 0.95);
          const longFrameLimit = Math.max(24, (window.__twinsyncUiPerformance?.estimatedFrameMs ?? 16.67) * 1.5);
          publishSnapshot({
            estimatedRefreshRate: window.__twinsyncUiPerformance?.estimatedRefreshRate ?? FALLBACK_REFRESH_RATE,
            estimatedFrameMs: window.__twinsyncUiPerformance?.estimatedFrameMs ?? 1000 / FALLBACK_REFRESH_RATE,
            renderedFps: Math.round(1000 / avg),
            averageFrameMs: avg,
            p95FrameMs: p95,
            longFrames: frameTimes.filter((value) => value > longFrameLimit).length,
            sampleCount: frameTimes.length,
            lastUpdatedAt: timestamp
          });
          lastPublished = timestamp;
        }

        monitorFrame = requestAnimationFrame(tick);
      };

      monitorFrame = requestAnimationFrame(tick);
    };

    const onVisibleOrChanged = () => {
      if (document.visibilityState !== "hidden") startDetection();
    };

    startDetection();
    monitorFrames();

    window.addEventListener("focus", startDetection, { passive: true });
    window.addEventListener("resize", startDetection, { passive: true });
    document.addEventListener("visibilitychange", onVisibleOrChanged, { passive: true });
    window.screen.orientation?.addEventListener?.("change", startDetection);

    return () => {
      cancelled = true;
      cancelAnimationFrame(detectionFrame);
      cancelAnimationFrame(monitorFrame);
      window.removeEventListener("focus", startDetection);
      window.removeEventListener("resize", startDetection);
      document.removeEventListener("visibilitychange", onVisibleOrChanged);
      window.screen.orientation?.removeEventListener?.("change", startDetection);
    };
  }, []);
}

