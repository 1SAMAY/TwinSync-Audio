# Build Windows

## Prerequisites

- Windows 10 or Windows 11, 64-bit
- Python 3.11 or newer
- Node.js 20 or newer
- Rust stable
- Visual Studio 2022 Build Tools with C++ workload

## Build

```powershell
.\installer\build_windows.ps1
```

The script:

- runs backend unit tests
- builds the React frontend
- builds `backend-dist\twinsync-backend.exe`
- bundles the Tauri NSIS installer
- creates the portable zip
- creates the source zip
- writes checksums, release notes, build report, and test report

## Output

Release files are written to:

```text
release\v0.1.1
```

## Notes

The v0.1.1 executable is unsigned unless a real code-signing certificate is configured outside the repository.
