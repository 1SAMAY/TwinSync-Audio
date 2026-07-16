param(
    [string]$Python = "",
    [string]$Npm = "npm.cmd",
    [string]$Version = "0.2.0"
)

$ErrorActionPreference = "Stop"
$TargetTriple = "x86_64-pc-windows-msvc"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$BackendExe = Join-Path $Root "backend-dist\twinsync-backend.exe"
$FrontendDir = Join-Path $Root "frontend"
$CargoTargetRoot = if ($env:CARGO_TARGET_DIR) { [IO.Path]::GetFullPath($env:CARGO_TARGET_DIR) } else { Join-Path $FrontendDir "src-tauri\target" }
$TauriTarget = Join-Path $CargoTargetRoot "$TargetTriple\release"
$BundleDir = Join-Path $TauriTarget "bundle\nsis"
$WebViewRuntimeName = "Microsoft.WebView2.FixedVersionRuntime.150.0.4078.65.x64"
$WebViewRuntime = Join-Path $FrontendDir "src-tauri\$WebViewRuntimeName"
$ReleaseDir = Join-Path $Root "release\v$Version"
$PortableStage = Join-Path $Root "work\portable\TwinSyncAudio"
$SourceStage = Join-Path $Root "work\source-archive\TwinSync-Audio-v$Version"

$SetupOut = Join-Path $ReleaseDir "TwinSyncAudio-Setup-v$Version.exe"
$PortableZip = Join-Path $ReleaseDir "TwinSyncAudio-Portable-v$Version.zip"
$SourceZip = Join-Path $ReleaseDir "TwinSyncAudio-Source-v$Version.zip"
$Checksums = Join-Path $ReleaseDir "SHA256SUMS.txt"
$ReleaseNotes = Join-Path $ReleaseDir "RELEASE_NOTES.md"
$BuildReport = Join-Path $ReleaseDir "BUILD_REPORT.md"
$TestReport = Join-Path $ReleaseDir "TEST_REPORT.md"

function Assert-ChildPath([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $inSource = $absolute.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    $inCargoTarget = $absolute.StartsWith($CargoTargetRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
    if (-not ($inSource -or $inCargoTarget)) {
        throw "Refusing to modify a path outside the source or Cargo target root: $absolute"
    }
}

function Remove-IfExists([string]$Path) {
    Assert-ChildPath $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Invoke-Native([string]$Name, [scriptblock]$Command) {
    Write-Host ""
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Resolve-Python {
    if (Test-Path -LiteralPath $VenvPython) {
        return $VenvPython
    }
    if ($Python -and (Get-Command $Python -ErrorAction SilentlyContinue)) {
        & $Python -m venv (Join-Path $Root ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the Python virtual environment."
        }
        return $VenvPython
    }
    throw "Python 3.11 or newer is required to build. Pass -Python with the full x64 python.exe path."
}

function Get-PeMachine([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $reader = [IO.BinaryReader]::new($stream)
    try {
        $stream.Position = 0x3c
        $peOffset = $reader.ReadInt32()
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            throw "$Path is not a valid PE executable."
        }
        return $reader.ReadUInt16()
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

if (-not $IsWindows -and $PSVersionTable.PSEdition -eq "Core") {
    throw "TwinSync Audio Windows releases must be built on Windows."
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "TwinSync Audio v$Version supports only Windows 10/11 x64."
}
$WindowsVersion = [Environment]::OSVersion.Version
if ($WindowsVersion.Major -lt 10) {
    throw "TwinSync Audio v$Version requires Windows 10 or Windows 11."
}
if (-not [Environment]::Is64BitProcess) {
    throw "Run this build from a 64-bit PowerShell process."
}
if (-not (Get-Command $Npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required to build."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust Cargo is required to build."
}

$ResolvedPython = Resolve-Python
$PythonArchitecture = (& $ResolvedPython -c "import platform; print(platform.machine())").Trim()
if ($PythonArchitecture -notin @("AMD64", "x86_64")) {
    throw "The backend must be built with x64 Python; detected $PythonArchitecture."
}
$RustHost = (& rustc -vV | Select-String '^host:' | ForEach-Object { $_.Line.Split(':', 2)[1].Trim() })
if ($RustHost -ne $TargetTriple) {
    throw "Rust host must be $TargetTriple; detected $RustHost."
}

$VersionFiles = @(
    "pyproject.toml",
    "frontend\package.json",
    "frontend\src-tauri\Cargo.toml",
    "frontend\src-tauri\tauri.conf.json"
)
foreach ($VersionFile in $VersionFiles) {
    $content = Get-Content -Raw -LiteralPath (Join-Path $Root $VersionFile)
    if ($content -notmatch [regex]::Escape($Version)) {
        throw "$VersionFile does not contain release version $Version."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $WebViewRuntime "msedgewebview2.exe"))) {
    throw "Extract the official x64 $WebViewRuntimeName beside tauri.conf.json before building."
}

Set-Location $Root
Remove-IfExists (Join-Path $Root "backend-dist")
Remove-IfExists (Join-Path $Root "work\pyinstaller")
Remove-IfExists (Join-Path $Root "work\portable")
Remove-IfExists (Join-Path $Root "work\source-archive")
Remove-IfExists $ReleaseDir
Remove-IfExists $BundleDir
Remove-IfExists (Join-Path $FrontendDir "dist")
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Invoke-Native "Install pinned backend build/runtime dependencies" {
    & $ResolvedPython -m pip install --disable-pip-version-check -r requirements.txt
}
Invoke-Native "Install backend package metadata" {
    & $ResolvedPython -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e .
}

$env:PYTHONPATH = Join-Path $Root "backend"
Invoke-Native "Compile backend source" {
    & $ResolvedPython -m compileall -q backend tests
}
Invoke-Native "Run backend unit and integration simulations" {
    & $ResolvedPython -m unittest discover -s tests -v
}
$TestCount = (& $ResolvedPython -c "import unittest; print(unittest.defaultTestLoader.discover('tests').countTestCases())").Trim()

Set-Location $FrontendDir
Invoke-Native "Install locked frontend dependencies" {
    & $Npm ci
}
Invoke-Native "Build production frontend" {
    & $Npm run build
}

Set-Location $Root
Invoke-Native "Build x64 backend executable" {
    & $ResolvedPython -m PyInstaller `
        --name twinsync-backend `
        --onefile `
        --noconfirm `
        --clean `
        --paths backend `
        --hidden-import soundcard `
        --hidden-import numpy `
        --distpath backend-dist `
        --workpath work\pyinstaller `
        --specpath work\pyinstaller `
        backend\run_backend.py
}
if (-not (Test-Path -LiteralPath $BackendExe)) {
    throw "Backend executable was not produced at $BackendExe"
}
if ((Get-PeMachine $BackendExe) -ne 0x8664) {
    throw "The backend executable is not x86_64."
}

Set-Location $FrontendDir
$env:TWINSYNC_BACKEND_EXE = $BackendExe
Invoke-Native "Build x86_64 Tauri app and NSIS installer" {
    & $Npm run tauri:build -- --target $TargetTriple
}

$BuiltSetup = Get-ChildItem -LiteralPath $BundleDir -Filter "*.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $BuiltSetup) {
    throw "NSIS setup executable was not produced in $BundleDir"
}
Copy-Item -LiteralPath $BuiltSetup.FullName -Destination $SetupOut -Force

$DesktopExe = Get-ChildItem -LiteralPath $TauriTarget -Filter "*.exe" -File |
    Where-Object { $_.Name -notmatch "setup|installer|uninstall" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $DesktopExe) {
    throw "Desktop executable was not produced in $TauriTarget"
}
if ((Get-PeMachine $DesktopExe.FullName) -ne 0x8664) {
    throw "The desktop executable is not x86_64."
}

New-Item -ItemType Directory -Force -Path (Join-Path $PortableStage "backend") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PortableStage "data") | Out-Null
Copy-Item -LiteralPath $DesktopExe.FullName -Destination (Join-Path $PortableStage "TwinSyncAudio.exe") -Force
Copy-Item -LiteralPath $BackendExe -Destination (Join-Path $PortableStage "backend\twinsync-backend.exe") -Force
$PortableWebView = Join-Path $PortableStage $WebViewRuntimeName
& robocopy $WebViewRuntime $PortableWebView /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) {
    throw "Fixed WebView2 runtime staging failed with robocopy exit code $LASTEXITCODE"
}
$global:LASTEXITCODE = 0
Set-Content -LiteralPath (Join-Path $PortableStage "portable.flag") -Encoding ASCII -Value "TwinSync Audio portable data marker"
Set-Content -LiteralPath (Join-Path $PortableStage "data\README.txt") -Encoding UTF8 -Value "Profiles, settings, diagnostics, and logs are stored in this folder."
Set-Content -LiteralPath (Join-Path $PortableStage "README-PORTABLE.txt") -Encoding UTF8 -Value @"
TwinSync Audio Portable v$Version — Windows 10/11 x64

Extract the complete archive, then run TwinSyncAudio.exe.

Profiles, settings, diagnostics, and logs stay under the adjacent data folder. The portable build does not install services, drivers, or system files. It includes the x64 Microsoft Edge WebView2 Fixed Version Runtime used by the interface and never downloads a runtime silently. On first launch, TwinSync grants the two Windows app-container identities read/execute access to that bundled runtime folder; no system folder is changed.

The app does not require Python, Node.js, npm, Rust, Cargo, Visual Studio, or an internet connection.
"@
Compress-Archive -Path (Join-Path $PortableStage "*") -DestinationPath $PortableZip -Force

New-Item -ItemType Directory -Force -Path $SourceStage | Out-Null
$ExcludedDirs = @(".git", ".venv", "__pycache__", "*.egg-info", "node_modules", "dist", "target", "release", "work", "logs", "data", "backend-dist*", "gen", "Microsoft.WebView2.FixedVersionRuntime.*")
$ExcludedFiles = @("*.pyc", "*.pyo", "*.sqlite3", "*.db", "*.log", "*.tmp", "*.cache")
& robocopy $Root $SourceStage /E /XD $ExcludedDirs /XF $ExcludedFiles /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) {
    throw "Source archive staging failed with robocopy exit code $LASTEXITCODE"
}
$global:LASTEXITCODE = 0
Compress-Archive -Path (Join-Path $SourceStage "*") -DestinationPath $SourceZip -Force

$GitArgs = @("-c", "safe.directory=$Root", "-c", "core.autocrlf=false")
$OldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$Commit = (& git @GitArgs rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Commit) {
    $Commit = "unknown"
    $global:LASTEXITCODE = 0
}
$UntrackedLines = (& git @GitArgs ls-files --others --exclude-standard 2>$null)
& git @GitArgs diff --quiet 2>$null
$HasTrackedDiff = $LASTEXITCODE -ne 0
& git @GitArgs diff --cached --quiet 2>$null
$HasStagedDiff = $LASTEXITCODE -ne 0
$Dirty = $HasTrackedDiff -or $HasStagedDiff -or [bool]$UntrackedLines
$global:LASTEXITCODE = 0
$ErrorActionPreference = $OldErrorActionPreference

Set-Content -LiteralPath $ReleaseNotes -Encoding UTF8 -Value @"
# TwinSync Audio v$Version

TwinSync Audio v$Version is the Windows x64 synchronization and reliability release.

## Highlights

- Correctly separates measured hardware latency, automatic compensation, and independent manual trim.
- Applies live delay changes through persistent, crossfaded delay processors.
- Adds smooth noise-gate attack, hold, release, and gain ramping.
- Coordinates capture/render worker failure and automatically rebuilds routing sessions with controlled backoff.
- Monitors endpoint positions, relative clock error, queue latency, underruns, overruns, workers, streams, and reconnect state.
- Uses small adaptive resampling corrections for normal drift control; block removal is reserved for coordinated overflow recovery.
- Adds real microphone chirp measurement, repeated cross-correlation, outlier rejection, confidence scoring, and confidence-gated application.
- Adds a native-CSS cinematic interface, persistent playback HUD, quality modes, Reduced Motion, and simple/developer diagnostics.
- Serializes frontend IPC, prevents overlapping refreshes, and debounces live sliders.
- Stores portable settings beside the executable and preserves installed profiles under Local AppData.
- Bundles the x64 WebView2 Fixed Version Runtime for installer and portable use; dependencies are never downloaded silently.

## Platform

- Windows 10/11 x64
- Intel or AMD x86_64 processors
- English interface and installer

## Important

The binaries are unsigned, so Windows SmartScreen may identify the publisher as unknown. Real acoustic accuracy still depends on the Bluetooth adapter, driver, codec, speaker firmware, room, and microphone placement.
"@

$PythonVersion = (& $ResolvedPython --version)
$NpmVersion = (& $Npm --version)
$CargoVersion = (& cargo --version)
$ArtifactRows = foreach ($Artifact in @($SetupOut, $PortableZip, $SourceZip, $ReleaseNotes)) {
    $Item = Get-Item -LiteralPath $Artifact
    "- $($Item.Name): $([math]::Round($Item.Length / 1MB, 2)) MB"
}
Set-Content -LiteralPath $BuildReport -Encoding UTF8 -Value @"
# Build Report — TwinSync Audio v$Version

- Build date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
- Source commit: $Commit
- Working tree dirty: $Dirty
- Target OS: Windows 10/11
- Target architecture: x86_64 ($TargetTriple)
- Release mode: Production
- Interface language: English
- Build host: $([Environment]::OSVersion.VersionString)
- Build process: 64-bit $([Environment]::Is64BitProcess)
- Python: $PythonVersion ($PythonArchitecture)
- npm: $NpmVersion
- Cargo: $CargoVersion
- Frontend production build: passed
- Backend executable build: passed, PE machine 0x8664
- Tauri desktop build: passed, PE machine 0x8664
- NSIS current-user installer: passed
- Fixed WebView2 runtime: $WebViewRuntimeName
- Portable package: passed
- Source archive: passed

## Artifacts

$($ArtifactRows -join "`n")

## Packaging behavior

- Installer uses current-user mode to avoid administrator permission for TwinSync itself.
- Installer and portable packages include the x64 fixed WebView2 runtime beside the app executable.
- Installed profiles remain under `%LOCALAPPDATA%\TwinSyncAudio` across uninstall/reinstall.
- Portable profiles remain under the extracted `data` folder.
- No ARM or 32-bit application binaries were built.
- No developer-machine path is used at runtime.

## Publication warning

- The executable is not code-signed.
- Hardware and clean-machine results are reported separately in TEST_REPORT.md and must not be inferred from compilation.
"@

Set-Content -LiteralPath $TestReport -Encoding UTF8 -Value @"
# Test Report — TwinSync Audio v$Version

## Passed in this automated build

- Python backend suite: $TestCount tests passed.
- Independent manual delay and hardware compensation math.
- Live delay processor updates and smooth increase/decrease transitions.
- Noise-gate attack, hold, release, and gain ramp behavior.
- Capture/render failure propagation and shared cycle cancellation.
- Disconnect/reconnect supervisor simulation with bounded retry.
- Queue overflow recovery and adaptive drift-resampling simulation.
- Acoustic chirp detection, outlier rejection, confidence scoring, and low-confidence rejection.
- Repeated start/stop and fixed-size long-running delay-buffer simulation.
- SQLite settings, profiles, events, and private-safe diagnostics export.
- Frontend TypeScript check and Vite production build.
- x86_64 PE validation for the backend and desktop executable.
- NSIS installer, portable archive, source archive, and checksum generation.

## Not verified by the build script

- Real dual-speaker audio routing or acoustic alignment.
- Bluetooth disconnect/reconnect on physical hardware.
- Windows Audio service restart, sleep/resume, shutdown, or restart.
- 100%, 125%, 150%, and 200% DPI on physical displays.
- Multiple-monitor movement and mixed-DPI behavior.
- Installer install/uninstall/reinstall through the Windows UI.
- Clean Windows 10/11 VM with no development tools.
- Program Files execution (the default installer intentionally uses current-user mode).
- Offline startup on a clean machine.

Do not mark the release production-verified until the hardware checklist in `docs/HARDWARE_TEST_CHECKLIST.md` is completed on a clean Windows 10 or Windows 11 x64 system.
"@

$HashArtifacts = @($SetupOut, $PortableZip, $SourceZip, $BuildReport, $TestReport, $ReleaseNotes)
$ChecksumLines = foreach ($Artifact in $HashArtifacts) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash.ToLowerInvariant()
    "$Hash  $(Split-Path -Leaf $Artifact)"
}
$ChecksumLines | Set-Content -LiteralPath $Checksums -Encoding ASCII

Write-Host ""
Write-Host "Release artifacts created in $ReleaseDir"
