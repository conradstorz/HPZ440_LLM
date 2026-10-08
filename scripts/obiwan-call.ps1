[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Path,
    [string]$Method = 'GET',
    [ValidateSet('reader','writer','commander')][string]$Role = 'reader',
    [string]$Body = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }

Push-Location $Root
try {
    Write-Host "Obi-Wan call: $Method $Path (role $Role)..."
    if ($Body) {
        docker --context $Context compose --env-file .env exec -T obiwan uv run --no-dev --frozen obiwan call $Method $Path --role $Role --json $Body
    } else {
        docker --context $Context compose --env-file .env exec -T obiwan uv run --no-dev --frozen obiwan call $Method $Path --role $Role
    }
    if ($LASTEXITCODE -ne 0) { throw 'Call failed. Is the stack running (scripts/start.ps1)?' }
} finally {
    Pop-Location
}
