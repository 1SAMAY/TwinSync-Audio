# UI Performance Report

## Scope

Only the React UI rendering layer was changed.

Changed files:

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- `frontend/src/useDisplayPerformance.ts`
- `frontend/src/vite-env.d.ts`

Unchanged areas:

- Python audio engine
- Bluetooth and Windows device discovery
- Synchronization and delay math
- Calibration backend behavior
- SQLite database schema
- IPC command names and payload shapes
- Tauri Rust bridge

## Confirmed Bottlenecks

- The UI had no monitor refresh-rate estimator, so it had no way to adapt visual diagnostics to 60 Hz, 75 Hz, 120 Hz, 144 Hz, 165 Hz, or 240 Hz displays.
- The status refresh loop stayed active while the webview was hidden.
- Each refresh could write React state for devices, status, profiles, and errors even when payloads had not changed.
- Repeated rows and controls were recreated inside the main `App` render path.
- Scroll containers had no layout or paint containment.
- No custom scroll listeners were present, so there were no listener leaks to remove.

## Optimizations Applied

- Added `requestAnimationFrame`-based display refresh-rate estimation.
- Added common refresh-rate rounding with safe 60 Hz fallback.
- Rechecks refresh rate on focus, resize, orientation change, and visibility restore.
- Added development-only frame diagnostics at `window.__twinsyncUiPerformance`.
- Suppressed unchanged device/status/profile state writes during polling.
- Paused UI polling while the window/webview is hidden and refreshed immediately when visible again.
- Memoized repeated presentational components.
- Stabilized UI action callbacks with `useCallback`.
- Added scroll container containment, stable scrollbar gutter, and native scroll behavior.
- Converted hover movement to GPU-friendly `translate3d`.
- Preserved the existing colors, spacing, layout, wording, controls, and theme.

## Measurement Summary

Baseline from code inspection:

- Refresh-rate detection: none
- Hidden-window UI polling: active
- Unchanged polling payload writes: up to devices + status + profiles + error per poll
- Scroll containment: none
- Full Tauri/webview frame measurements: unavailable in this sandbox

Final from code and validation:

- Refresh-rate detection: `requestAnimationFrame` sample of 80 frames, first 8 ignored, abnormal intervals filtered, nearest common rate selected
- Hidden-window UI polling: paused
- Unchanged polling payload writes: suppressed
- Scroll containment: enabled for device/profile/event scroll containers
- Production build: passed
- Backend tests: 11 passed
- Python compile: passed
- npm audit: 0 vulnerabilities

## Refresh Rates

The estimator supports and rounds near these common rates:

- 60 Hz
- 75 Hz
- 90 Hz
- 120 Hz
- 144 Hz
- 165 Hz
- 240 Hz

Runtime testing across physical monitors still requires the app running on the target Windows machine because this sandbox cannot move the Tauri window between real displays.

## Remaining Hardware / OS Limits

- Actual desktop webview frame timing must be verified on the user's Windows machine.
- High-refresh behavior must be verified on real 120 Hz, 144 Hz, 165 Hz, or 240 Hz monitors.
- Audio stability under UI load must be verified with the real two-speaker setup.

