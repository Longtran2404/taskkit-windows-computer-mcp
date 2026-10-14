# Owner-run, non-admin installer for Win10 Computer Bridge MCP prototype.
# Changes only user's LocalAppData and home folder; does not patch OpenAI.
[CmdletBinding()]
param([switch]$InstallCodex)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$install = Join-Path $env:LOCALAPPDATA 'Win10ComputerBridgeMCP'
$cfgDir = Join-Path $HOME 'Win10_ComputerBridge'
$cfg = Join-Path $cfgDir 'bridge_config.json'
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $py) { throw 'Install Python 3.11 from python.org and rerun (py.exe launcher missing).' }
& py.exe -3.11 --version
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required for this prototype.' }
New-Item -ItemType Directory -Path $install,$cfgDir -Force | Out-Null
$src = Join-Path $install 'source'
New-Item -ItemType Directory -Path $src -Force | Out-Null
Copy-Item -Path (Join-Path $root 'win10_bridge_mcp') -Destination $src -Recurse -Force
Copy-Item -Path (Join-Path $root 'pyproject.toml') -Destination $src -Force
$venv = Join-Path $install 'venv'
& py.exe -3.11 -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed' }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install $src
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
if (-not (Test-Path -LiteralPath $cfg)) {
    Copy-Item -LiteralPath (Join-Path $root 'bridge_config.example.json') -Destination $cfg
}
Write-Host "Configured (mouse disabled by default). Config: $cfg"
if ($InstallCodex) {
    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $codex) { throw 'Codex CLI command not found in PATH; run Codex installer first.' }
    # Only write to Codex user config when explicitly requested.
    & codex mcp add win10-bridge -- $python -m win10_bridge_mcp
    if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed' }
    Write-Host 'Codex MCP registered. Restart Codex to detect it.'
}
Write-Host "Python: $python"
Write-Host 'Next: Codex -> inspect_windows / capture_window. Screen images may leave machine through AI client.'
