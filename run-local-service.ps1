$ErrorActionPreference = "Stop"
$serviceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $serviceRoot ".venv"

if (-not (Test-Path $venvPath)) {
  python -m venv $venvPath
}

& (Join-Path $venvPath "Scripts\python.exe") -m pip install --quiet -r (Join-Path $serviceRoot "requirements.txt")
$env:HOST = "127.0.0.1"
$env:PORT = "10000"
& (Join-Path $venvPath "Scripts\python.exe") (Join-Path $serviceRoot "app.py")
