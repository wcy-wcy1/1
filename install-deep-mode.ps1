$ErrorActionPreference = "Stop"
$serviceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $serviceRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "请先运行 run-local-service.ps1 一次，以创建本地运行环境。"
}

& $python -m pip install -r (Join-Path $serviceRoot "requirements-deep.txt")
Write-Host "深度模式组件已安装。重启本地服务后即可选择深度模式。" -ForegroundColor Green
