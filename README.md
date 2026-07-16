# TwinSync Audio

TwinSync Audio v0.2.0 is a local Windows desktop application for routing one system-audio source to two selected playback endpoints, applying independent delay and volume, measuring acoustic offset with a microphone, monitoring endpoint timing, and correcting small long-term drift.

Target release:

```text
Target OS: Windows 10/11
Architecture: x86_64
Release mode: Production
Interface language: English
```

TwinSync does not use accounts, telemetry, cloud audio processing, ads, or automatic update checks.

## Changes from v0.1.1 to v0.2.0

- Independent manual trim: changing one speaker never silently changes the other speaker's manual delay.
- Separate measured hardware latency, automatic compensation, manual trim, endpoint drift, and queue latency.
- Live delay changes through persistent delay processors with short crossfades.
- Smooth noise gate with attack, hold, release, and gain ramping.
- Shared cancellation: a failed render worker stops its sibling and rebuilds the routing session.
- Automatic recovery for endpoint removal, default-output changes, and audio-session failure using controlled backoff.
- Endpoint position, relative clock error, queue depth, queue latency, correction rate, underrun/overrun, worker, stream, and reconnect diagnostics.
- Adaptive resampling for normal drift correction. Coordinated block removal is reserved for exceptional queue overflow recovery.
- Real microphone calibration with repeated chirps, FFT cross-correlation, outlier rejection, confidence scoring, and confidence-gated application.
- Cinematic CSS 3D interface with a permanent playback HUD and Cinematic, Balanced, Performance, and Reduced Motion modes.
- Serialized frontend IPC, one active refresh at a time, debounced sliders, hidden-window polling pause, and no per-frame React state.
- Installer and portable packages that embed the Python/audio backend; users need no developer tools.

## Architecture

TwinSync has three local processes/layers:

1. React renders controls and diagnostics in the Windows WebView2 component.
2. The Tauri Rust shell serializes JSON-line IPC and owns the backend child process.
3. A bundled Python sidecar performs device discovery, SQLite storage, calibration analysis, and audio routing. SoundCard calls the native Windows WASAPI interfaces through CFFI; NumPy performs delay, gating, correlation, and small resampling operations.

The backend is isolated from the UI process, so interface rendering cannot run on the audio workers. See [Architecture](docs/ARCHITECTURE.md) for routing modes and failure behavior.

## Routing modes

### Windows default plus controlled output

When TwinSync captures the Windows default speaker through WASAPI loopback, Windows already renders that endpoint. TwinSync controls the other selected output and clearly names the selected Windows-default speaker that is not controlled by TwinSync. This feedback guard prevents playing captured loopback back into the same endpoint.

### Dual controlled outputs

When a dedicated loopback/virtual source is configured, TwinSync renders and controls both selected outputs independently.

TwinSync blocks startup if an unselected third Windows-default speaker would remain audible.

## Delay model

For each speaker:

```text
effective software delay = automatic compensation + that speaker's manual trim
```

Automatic compensation is calculated only from measured hardware latency. Manual trim is not part of the automatic comparison, so a manual change to Primary does not add delay to Secondary.

## Microphone calibration

1. Select Primary and Secondary outputs.
2. Select a measurement microphone.
3. Keep the room quiet and place the microphone where timing should converge.
4. Start calibration.
5. TwinSync checks background level, plays a known chirp through each speaker separately, repeats the measurement, correlates each recording, removes outliers, and calculates relative arrival time.
6. The result is applied only at acceptable confidence. Manual trim remains available afterward.

Leaving the microphone blank runs guided listening calibration instead.

## Local data

Installed mode stores profiles, settings, logs, and diagnostics under:

```text
%LOCALAPPDATA%\TwinSyncAudio
```

Portable mode stores them under the extracted `data` folder beside `TwinSyncAudio.exe`. Uninstalling the installed app preserves the Local AppData profile database.

## Release files

- `TwinSyncAudio-Setup-v0.2.0.exe`
- `TwinSyncAudio-Portable-v0.2.0.zip`
- `TwinSyncAudio-Source-v0.2.0.zip`
- `SHA256SUMS.txt`
- `BUILD_REPORT.md`
- `TEST_REPORT.md`
- `RELEASE_NOTES.md`

The setup is current-user by default and does not require administrator permission for TwinSync itself. It creates a Start Menu shortcut and asks whether to create a desktop shortcut. The setup bundles Microsoft Edge WebView2 Fixed Version Runtime 150.0.4078.65 x64 and never downloads a component silently.

The portable package modifies no system files and installs no service or driver. It includes the same fixed x64 WebView2 runtime beside the executable. First launch grants Windows app-container read/execute access only on that bundled folder; a native startup message explains if the package is incomplete or damaged.

## Use

1. Connect both playback devices in Windows.
2. Set one selected device as the Windows default output, or configure a dedicated virtual loopback source.
3. Start TwinSync Audio.
4. Select Primary and Secondary.
5. Use Test Primary and Test Secondary.
6. Start the routing session.
7. Adjust independent manual trim or run microphone calibration.
8. Save the pair as a profile.

The permanent HUD always exposes Start, Stop, Primary, Secondary, connection/sync health, master volume, Emergency Stop, and Settings.

## Development

Build requirements are needed only by contributors:

- Windows 10/11 x64
- Python 3.11+
- Node.js 20+
- Rust stable targeting `x86_64-pc-windows-msvc`
- Visual Studio 2022 Build Tools with the C++ workload

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[windows]
cd frontend
npm.cmd ci
npm.cmd run build
```

Backend tests:

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Production Windows release:

```powershell
.\installer\build_windows.ps1
```

The release script fails if the host, Python, Rust target, backend executable, or desktop executable is not x86_64.

## Diagnostics export

Developer mode shows endpoint clocks, relative error, queue depth, correction rate, capture/render timing, acoustic offset, buffer errors, worker/stream counts, reconnect attempts, and the last local audio error. Export omits device IDs, device names, usernames, audio, event messages, and full error text.

## Verification policy

Compilation is not treated as proof of audio behavior. Automated checks cover audio math and simulated failure/recovery. The clean-machine and physical-device matrix is tracked in [Hardware Test Checklist](docs/HARDWARE_TEST_CHECKLIST.md). Unchecked items remain unverified and must be reported as such.

## Known limitations

See [Known Limitations](KNOWN_LIMITATIONS.md). The most important are hardware-dependent Bluetooth latency, the uncontrolled Windows-default endpoint in guarded loopback mode, unsigned binaries, and clean-machine/hardware checks that cannot be inferred from automated tests.

## License

Copyright (c) 2026 SAMAY DUDHREJIYA. All rights reserved. See [LICENSE](LICENSE).
