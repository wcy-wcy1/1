$ErrorActionPreference = 'Stop'
$python = Join-Path -Path $PSScriptRoot -ChildPath '.venv\Scripts\python.exe'
$requirements = Join-Path -Path $PSScriptRoot -ChildPath 'requirements-deep.txt'

if (-not (Test-Path -LiteralPath $python)) {
  throw '请先运行本地服务一次，以创建本地运行环境。'
}

& $python -m pip install -r $requirements
Write-Host '深度模式组件已安装。重启本地服务后即可选择深度模式。' -ForegroundColor Green
