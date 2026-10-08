[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }

Push-Location $Root
try {
    Write-Host 'Scanning every configured root and the inbox, then draining pending work (blocks until done)...'
    docker --context $Context compose --env-file .env exec -T obiwan uv run --no-dev --frozen obiwan scan
    if ($LASTEXITCODE -ne 0) { throw 'Scan failed. Is the stack running (scripts/start.ps1)?' }
} finally {
    Pop-Location
}
