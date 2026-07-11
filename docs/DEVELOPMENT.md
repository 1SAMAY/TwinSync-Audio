# Development

TwinSync Audio uses a Tauri desktop shell, React frontend, and local Python backend.

## Architecture

- `frontend/src`: React UI.
- `frontend/src-tauri`: Rust desktop shell and IPC bridge.
- `backend/twinsync_backend`: audio engine, device manager, SQLite profiles, logging, and command service.
- `tests`: backend regression tests.
- `installer/build_windows.ps1`: Windows release build.

The Tauri shell starts the backend locally and communicates over JSON lines through stdin/stdout. No HTTP service is required.

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[windows]
cd frontend
npm.cmd install
$env:TWINSYNC_PYTHON = "..\.venv\Scripts\python.exe"
npm.cmd run tauri:dev
```

## Tests

```powershell
cd ..
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm.cmd run build
```

## Local Data

Default Windows data path: `%LOCALAPPDATA%\TwinSyncAudio`.

Developers can override paths with `TWINSYNC_DATA_DIR` and `TWINSYNC_LOG_DIR`.
