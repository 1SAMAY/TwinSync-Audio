# TwinSync Audio Developer Guide

## Architecture

TwinSync is split into three local layers:

- `backend/twinsync_backend`: Python service for audio devices, playback, sync state, profiles, SQLite, diagnostics, and JSON-lines IPC.
- `frontend`: React UI.
- `frontend/src-tauri`: Tauri desktop shell and Rust IPC bridge that starts the Python backend over stdin/stdout.

No network service is required for the backend.

## Backend Entry Point

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m twinsync_backend.ipc_server
```

IPC request:

```json
{"id":1,"method":"status","params":{}}
```

IPC response:

```json
{"id":1,"ok":true,"result":{}}
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

The included tests avoid physical audio hardware. Hardware verification should be run on Windows with two real output devices connected.

## Windows Audio

The audio engine uses `soundcard` and `numpy` only inside runtime audio paths. Device/profile/settings tests run without those packages so state logic stays easy to verify.

The render path uses a capture worker and independent render workers for the two speakers. Delay is applied per output before playback. Drift metrics are based on local capture/render timing because Windows does not expose all Bluetooth packet timing or acoustic latency data through a stable user-mode API.

