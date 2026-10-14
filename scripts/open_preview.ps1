[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$python = Join-Path $env:LOCALAPPDATA 'Win10ComputerBridgeMCP\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/install_windows.ps1 first.' }
& $python -m win10_bridge_mcp.viewer
if ($LASTEXITCODE -ne 0) { throw 'Preview failed; check that an allowed window is open.' }
