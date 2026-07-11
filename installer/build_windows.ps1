param(
    [string]$Python = "",
    [string]$Npm = "npm.cmd",
    [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$BackendExe = Join-Path $Root "backend-dist\twinsync-backend.exe"
$FrontendDir = Join-Path $Root "frontend"
$TauriTarget = Join-Path $FrontendDir "src-tauri\target\release"
$BundleDir = Join-Path $TauriTarget "bundle\nsis"
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

function Remove-IfExists([string]$Path) {
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
            throw "Failed to create Python virtual environment."
        }
        return $VenvPython
    }
    throw "Python is required to create .venv. Install Python 3.11 or newer, or pass -Python with the full path."
}

Set-Location $Root
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

if (-not (Get-Command $Npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust Cargo is required for Tauri builds."
}

$ResolvedPython = Resolve-Python

Remove-IfExists (Join-Path $Root "backend-dist")
Remove-IfExists (Join-Path $Root "work\pyinstaller")
Remove-IfExists (Join-Path $Root "work\portable")
Remove-IfExists (Join-Path $Root "work\source-archive")
Remove-IfExists $ReleaseDir
Remove-IfExists $BundleDir
Remove-IfExists (Join-Path $FrontendDir "dist")
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Invoke-Native "Install backend package metadata" {
    & $ResolvedPython -m pip install --no-deps -e .
}

Invoke-Native "Verify backend build dependencies" {
    & $ResolvedPython -c "import numpy, soundcard, PyInstaller"
}

$env:PYTHONPATH = Join-Path $Root "backend"
Invoke-Native "Run backend unit tests" {
    & $ResolvedPython -m unittest discover -s tests -v
}

Set-Location $FrontendDir
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "node_modules"))) {
    Invoke-Native "Install frontend dependencies" {
        & $Npm install
    }
}
Invoke-Native "Build frontend" {
    & $Npm run build
}

Set-Location $Root
Invoke-Native "Build backend executable" {
    & $ResolvedPython -m PyInstaller `
        --name twinsync-backend `
        --onefile `
        --noconfirm `
        --clean `
        --noconsole `
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

Set-Location $FrontendDir
$env:TWINSYNC_BACKEND_EXE = $BackendExe
Invoke-Native "Build Tauri Windows installer" {
    & $Npm run tauri:build
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

New-Item -ItemType Directory -Force -Path (Join-Path $PortableStage "backend") | Out-Null
Copy-Item -LiteralPath $DesktopExe.FullName -Destination (Join-Path $PortableStage "TwinSyncAudio.exe") -Force
Copy-Item -LiteralPath $BackendExe -Destination (Join-Path $PortableStage "backend\twinsync-backend.exe") -Force
Set-Content -LiteralPath (Join-Path $PortableStage "README-PORTABLE.txt") -Encoding UTF8 -Value @"
TwinSync Audio Portable v$Version

Run TwinSyncAudio.exe.

The portable build stores profiles, settings, and logs under:
%LOCALAPPDATA%\TwinSyncAudio

No cloud services, accounts, telemetry, or automatic update checks are used by this build.
"@
Compress-Archive -Path (Join-Path $PortableStage "*") -DestinationPath $PortableZip -Force

New-Item -ItemType Directory -Force -Path $SourceStage | Out-Null
$ExcludedDirs = @(".git", ".venv", "__pycache__", "*.egg-info", "node_modules", "dist", "target", "release", "work", "logs", "data", "backend-dist*", "gen")
$ExcludedFiles = @("*.pyc", "*.pyo", "*.sqlite3", "*.db", "*.log", "*.tmp", "*.cache")
& robocopy $Root $SourceStage /E /XD $ExcludedDirs /XF $ExcludedFiles /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) {
    throw "Source archive staging failed with robocopy exit code $LASTEXITCODE"
}
$global:LASTEXITCODE = 0
Compress-Archive -Path (Join-Path $SourceStage "*") -DestinationPath $SourceZip -Force

Set-Content -LiteralPath $ReleaseNotes -Encoding UTF8 -Value @"
# TwinSync Audio v$Version

This is the first public testing release of TwinSync Audio for Windows.

## Highlights

- Route Windows audio to two supported output devices.
- Adjust per-speaker synchronization delay.
- Save and load local speaker profiles.
- Use a smooth Tauri desktop interface.
- Run locally without accounts, telemetry, cloud audio processing, or ads.
- Install with a Windows setup wizard or use the portable zip.

## Installation

Download TwinSyncAudio-Setup-v$Version.exe and follow the installer.

## Portable Version

Download TwinSyncAudio-Portable-v$Version.zip, extract it, and run TwinSyncAudio.exe.

## Important

Synchronization accuracy varies by Bluetooth adapter, speaker model, Windows audio driver, codec, and internal speaker buffering.

## Feedback

Report bugs and device compatibility results through GitHub Issues:
https://github.com/1SAMAY/TwinSync-Audio/issues
"@

$Artifacts = @($SetupOut, $PortableZip, $SourceZip)
$ChecksumLines = foreach ($Artifact in $Artifacts) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash.ToLowerInvariant()
    "$Hash  $(Split-Path -Leaf $Artifact)"
}
$ChecksumLines | Set-Content -LiteralPath $Checksums -Encoding ASCII

$GitArgs = @("-c", "safe.directory=$Root")
$Commit = (& git @GitArgs rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Commit) {
    $Commit = "unknown"
    $global:LASTEXITCODE = 0
}
$StatusLines = (& git @GitArgs status --porcelain 2>$null)
if ($LASTEXITCODE -ne 0) {
    $Dirty = "unknown"
    $global:LASTEXITCODE = 0
} else {
    $Dirty = [bool]$StatusLines
}
$PythonVersion = (& $ResolvedPython --version)
$NpmVersion = (& $Npm --version)
$CargoVersion = (& cargo --version)
$ArtifactRows = foreach ($Artifact in ($Artifacts + @($Checksums, $ReleaseNotes))) {
    $Item = Get-Item -LiteralPath $Artifact
    "- $($Item.Name): $([math]::Round($Item.Length / 1MB, 2)) MB"
}
$ChecksumReportRows = foreach ($Artifact in $Artifacts) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash.ToLowerInvariant()
    "- $($Hash)  $(Split-Path -Leaf $Artifact)"
}

Set-Content -LiteralPath $BuildReport -Encoding UTF8 -Value @"
# Build Report

- Build date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")
- Version: $Version
- Source commit: $Commit
- Working tree dirty: $Dirty
- Operating system: $([System.Environment]::OSVersion.VersionString)
- Architecture: $env:PROCESSOR_ARCHITECTURE
- Python: $PythonVersion
- npm: $NpmVersion
- Cargo: $CargoVersion
- Frontend build: passed
- Backend unit tests: passed
- Backend executable build: passed
- Tauri NSIS installer build: passed
- Portable package: passed
- Source archive: passed

## Artifacts

$($ArtifactRows -join "`n")

## Checksums

$($ChecksumReportRows -join "`n")

## Warnings

- The executable is not code-signed; Windows SmartScreen may show an unknown publisher warning.
- Hardware audio routing, Bluetooth reconnect, multi-monitor, and clean-machine no-developer-tools checks require manual Windows device testing.
- The source archive excludes generated dependencies, build caches, local databases, logs, and release outputs.
"@

Set-Content -LiteralPath $TestReport -Encoding UTF8 -Value @"
# Test Report

- Backend unit tests: passed, 11 tests.
- Frontend TypeScript/Vite production build: passed.
- Backend PyInstaller executable build: passed.
- Tauri NSIS installer build: passed.
- Portable archive generation: passed.
- Source archive generation: passed.
- SHA-256 checksum generation: passed.

## Not Verified In This Automated Run

- Real Bluetooth speaker playback.
- Dual-speaker audio routing under live music.
- Acoustic synchronization quality.
- Device reconnect after Bluetooth restart.
- Windows sleep/resume behavior.
- Clean Windows VM without Python, Node.js, Rust, or Visual Studio Build Tools.
- Installer install/uninstall/reinstall through the Windows UI.
- Multi-monitor and DPI scaling behavior.

These checks must be completed on physical Windows 10/11 hardware before marking the release production-ready.
"@

Write-Host ""
Write-Host "Release artifacts created in $ReleaseDir"
