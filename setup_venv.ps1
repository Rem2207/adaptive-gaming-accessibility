$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "Python Launcher was not found. Install Python 3.11 and try again."
}

py -3.11 --version
py -3.11 -m venv .venv

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip setuptools wheel
& $python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Environment ready. Run the app with:" -ForegroundColor Green
Write-Host ".\run_app.ps1"
