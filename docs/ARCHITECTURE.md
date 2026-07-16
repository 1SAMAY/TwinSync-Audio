# TwinSync Audio v0.2.0 Architecture

## Process boundary

```text
React/WebView2 UI
       |
       | serialized Tauri invoke calls
       v
Rust Tauri shell
       |
       | JSON lines over child stdin/stdout
       v
Bundled backend sidecar
  |-- service and state
  |-- SQLite profiles/events
  |-- SoundCard -> native Windows WASAPI
  `-- NumPy delay/gate/resampling/calibration
```

The UI and backend are separate processes. UI animation and React work cannot run on the capture or render workers. The Rust shell owns the sidecar lifetime and terminates it when the desktop process closes.

## Routing cycle

One supervisor owns a routing session. Each cycle resolves the source and both selected endpoints again, creates bounded queues and persistent delay processors, then starts one render worker for every output TwinSync can safely control.

In default-loopback mode, Windows controls the selected default endpoint and TwinSync controls the other selected endpoint. Re-rendering captured loopback into its source endpoint would create feedback, so the UI names the uncontrolled selected endpoint. With a dedicated virtual/loopback source, TwinSync creates two controlled render workers.

The service refuses to start when the Windows default endpoint is an unselected third output.

## Delay and drift

Measured hardware latency is an endpoint observation. Automatic compensation delays only the faster measured endpoint. Manual trim is then added independently to its named endpoint.

Persistent delay lines retain history across audio blocks. A live target change crossfades between old and new delay taps over 80 ms, avoiding an abrupt block drop or duplicated discontinuity.

Each controlled render worker reports submitted endpoint frames, software clock position, queue depth, queue latency, render duration, and its small correction rate. Queue pressure selects an adaptive linear-resampling correction limited to ±1200 ppm. Exceptional queue overflow removes one old block from all controlled queues together; independent block dropping is not used as normal drift correction.

## Noise gate

The capture gate uses separate open/close thresholds, 8 ms attack, 80 ms hold, and 120 ms release. Its gain changes as a ramp across each processed block.

## Failure and reconnect

Capture and render workers share cycle cancellation. The first output failure records one error and sets the cycle event; its sibling exits instead of playing indefinitely. The supervisor closes all streams and queues, re-resolves devices, and retries after 0.5, 1, 2, 4, then 8 seconds. User Stop sets the session event and bypasses reconnect.

Selected endpoint presence and Windows-default identity are checked during playback. Endpoint removal, default changes, capture failure, render failure, and Windows Audio session loss all rebuild the complete cycle.

## Acoustic calibration

The selected microphone records background noise and repeated speaker-specific chirps. FFT cross-correlation finds arrival time. Median absolute deviation removes inconsistent relative offsets. Confidence combines correlation quality, repeatability, and accepted repeat count. Only results at or above the confidence threshold update measured hardware latency.

## Storage

Installed mode uses `%LOCALAPPDATA%\TwinSyncAudio`. Portable mode is selected by `portable.flag`; the Rust shell then passes adjacent `data` and `data\logs` paths to the backend. SQLite uses WAL mode and opens a short connection per operation.

## Packaging

PyInstaller embeds Python, NumPy, SoundCard, CFFI, and the backend with standard handles enabled for IPC. The Rust shell launches it with Windows `CREATE_NO_WINDOW`, so no console appears. Tauri bundles the frontend, Rust shell, backend resource, NSIS uninstaller, and Microsoft WebView2 Fixed Version Runtime 150.0.4078.65 x64. The fixed runtime sits beside the desktop executable in installed and portable layouts. Both application executables are validated as PE machine `0x8664` during the release build.
