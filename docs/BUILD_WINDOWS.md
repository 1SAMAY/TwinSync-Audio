# Build Windows x64

## Prerequisites

- Windows 10 or Windows 11 x64
- x64 Python 3.11+
- Node.js 20+
- Rust stable with host `x86_64-pc-windows-msvc`
- Visual Studio 2022 Build Tools with the C++ workload
- Microsoft WebView2 Fixed Version Runtime 150.0.4078.65 x64, downloaded directly from Microsoft and extracted as `frontend\src-tauri\Microsoft.WebView2.FixedVersionRuntime.150.0.4078.65.x64`

## Production build

```powershell
.\installer\build_windows.ps1 -Python "C:\path\to\python.exe"
```

The script validates the host/toolchain architecture, compiles/tests the backend, performs a locked frontend production build, creates the PyInstaller sidecar, builds Tauri explicitly for `x86_64-pc-windows-msvc`, validates the PE application headers as `0x8664`, bundles the fixed x64 WebView2 runtime, and writes all required files to `release\v0.2.0`. Set `CARGO_TARGET_DIR` when the Rust build cache should live on another drive.

No ARM or 32-bit application artifact is produced. Binaries are unsigned unless a real owner-controlled certificate is configured outside the repository.
