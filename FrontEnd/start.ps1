$ErrorActionPreference = 'Stop'
$launcher = Join-Path (Split-Path -Parent $PSScriptRoot) 'start.ps1'
& $launcher
exit $LASTEXITCODE
