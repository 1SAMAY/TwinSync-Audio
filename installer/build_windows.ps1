param(
    [string]$Python = "python",
    [string]$Npm = "npm.cmd"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$BackendExe = Join-Path $Root "backend-dist\twinsync-backend.exe"

Set-Location $Root

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python is required. Install Python 3.11 or newer, or pass -Python with the full path."
}
if (-not (Get-Command $Npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust Cargo is required for Tauri builds."
}

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv .venv
}
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e .[windows]

if (Test-Path (Join-Path $Root "backend-dist")) {
    Remove-Item -LiteralPath (Join-Path $Root "backend-dist") -Recurse -Force
}
& $VenvPython -m PyInstaller `
    --name twinsync-backend `
    --onefile `
    --paths backend `
    --hidden-import soundcard `
    --hidden-import numpy `
    --distpath backend-dist `
    --workpath work\pyinstaller `
    --specpath work\pyinstaller `
    backend\run_backend.py

if (-not (Test-Path $BackendExe)) {
    throw "Backend executable was not produced."
}

Set-Location (Join-Path $Root "frontend")
& $Npm install
$env:TWINSYNC_BACKEND_EXE = $BackendExe
& $Npm run tauri:build
