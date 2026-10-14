# Owner-run, non-admin installer for TaskKit.vn Windows Computer Bridge MCP.
# Changes only user's LocalAppData and home folder; does not patch OpenAI.
[CmdletBinding()]
param(
    [switch]$InstallCodex,
    [string]$PythonVersion = '3',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Win10ComputerBridgeMCP'),
    [string]$ConfigDir = (Join-Path $env:USERPROFILE 'Win10_ComputerBridge')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$install = [System.IO.Path]::GetFullPath($InstallDir)
$cfgDir = [System.IO.Path]::GetFullPath($ConfigDir)
$cfg = Join-Path $cfgDir 'bridge_config.json'
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $py) { throw 'Install Python 3.11 or later from python.org (py.exe launcher missing).' }
$selector = "-$PythonVersion"
& $py.Source $selector -c "import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'A selected Python version of 3.11 or later is required.' }
New-Item -ItemType Directory -Path $install,$cfgDir -Force | Out-Null
$src = Join-Path $install 'source'
if (Test-Path -LiteralPath $src) {
    $backup = Join-Path $install ('source-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-ffff'))
    Copy-Item -LiteralPath $src -Destination $backup -Recurse -Force
}
New-Item -ItemType Directory -Path $src -Force | Out-Null
Copy-Item -Path (Join-Path $root 'win10_bridge_mcp') -Destination $src -Recurse -Force
Copy-Item -Path (Join-Path $root 'pyproject.toml') -Destination $src -Force
Copy-Item -LiteralPath (Join-Path $root 'LICENSE'),(Join-Path $root 'NOTICE') -Destination $src -Force
$venv = Join-Path $install 'venv'
& $py.Source $selector -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed' }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install $src
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
if (-not (Test-Path -LiteralPath $cfg)) {
    Copy-Item -LiteralPath (Join-Path $root 'bridge_config.example.json') -Destination $cfg
}
Write-Host "TaskKit.vn MCP installed. Existing config preserved; new config defaults to disabled. Config: $cfg"
if ($InstallCodex) {
    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $codex) { throw 'Codex CLI command not found in PATH; run Codex installer first.' }
    # Only write to Codex user config when explicitly requested.
    & codex mcp add win10-bridge -- $python -m win10_bridge_mcp
    if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed' }
    Write-Host 'Codex MCP registered. Restart Codex to detect it.'
}
Write-Host "Python: $python"
Write-Host "For this config path, set WIN10_BRIDGE_CONFIG to: $cfg"
Write-Host 'Next: Codex -> inspect_windows / capture_window. Screen images may leave machine through AI client.'
