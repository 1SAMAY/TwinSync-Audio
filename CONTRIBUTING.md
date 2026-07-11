# Contributing

Thanks for helping improve TwinSync Audio.

## Development Requirements

- Windows 10 or Windows 11, 64-bit
- Python 3.11 or newer
- Node.js 20 or newer
- Rust stable through rustup
- Visual Studio 2022 Build Tools with the C++ workload

## Setup

```powershell
git clone https://github.com/1SAMAY/TwinSync-Audio.git
cd TwinSync-Audio
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[windows]
cd frontend
npm.cmd install
```

## Run

```powershell
cd frontend
$env:TWINSYNC_PYTHON = "..\.venv\Scripts\python.exe"
npm.cmd run tauri:dev
```

## Test

```powershell
cd ..
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm.cmd run build
```

## Build Windows Release

```powershell
.\installer\build_windows.ps1
```

## Pull Requests

- Keep audio behavior backward compatible unless the change explicitly fixes a bug.
- Confirm backend tests pass.
- Confirm `npm.cmd run build` passes.
- Include screenshots for UI changes.
- Document any manual audio hardware tests performed.
