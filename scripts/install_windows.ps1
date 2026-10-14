# Owner-run, non-admin installer for Win10 Computer Bridge MCP prototype.
# Changes only user's LocalAppData and home folder; does not patch OpenAI.
[CmdletBinding()]
param(
    [switch]$InstallCodex,
    [switch]$OwnerOnboarding,
    [ValidateSet('3.11','3.12','3.13')][string]$PythonVersion = '3.11'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$install = Join-Path $env:LOCALAPPDATA 'Win10ComputerBridgeMCP'
$cfgDir = Join-Path $HOME 'Win10_ComputerBridge'
$cfg = Join-Path $cfgDir 'bridge_config.json'
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $py) { throw 'Install Python with Tkinter and py.exe launcher from python.org, then rerun.' }
& py.exe "-$PythonVersion" --version
if ($LASTEXITCODE -ne 0) { throw "Python $PythonVersion is not installed; select -PythonVersion 3.11, 3.12 or 3.13." }
New-Item -ItemType Directory -Path $install,$cfgDir -Force | Out-Null
$src = Join-Path $install 'source'
New-Item -ItemType Directory -Path $src -Force | Out-Null
Copy-Item -Path (Join-Path $root 'win10_bridge_mcp') -Destination $src -Recurse -Force
Copy-Item -Path (Join-Path $root 'pyproject.toml') -Destination $src -Force
foreach ($document in @('LICENSE','NOTICE','README.md')) {
    Copy-Item -LiteralPath (Join-Path $root $document) -Destination $src -Force
}
Copy-Item -LiteralPath (Join-Path $root 'docs') -Destination $install -Recurse -Force
$venv = Join-Path $install 'venv'
& py.exe "-$PythonVersion" -m venv $venv
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
if ($OwnerOnboarding) {
    # Only the owner-running installer can request this local UI. It does not
    # turn on persistent mode or register credentials with any AI host.
    & $python -m win10_bridge_mcp --permissions
    if ($LASTEXITCODE -ne 0) { throw 'Owner permissions UI failed; access was not enabled automatically.' }
}
Write-Host 'Next: Codex -> inspect_windows / capture_window. Screen images may leave machine through AI client.'
