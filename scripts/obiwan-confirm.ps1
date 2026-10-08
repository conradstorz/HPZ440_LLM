[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SubjectId,
    [switch]$Forget,
    [string]$Reason = ''
)

# The Commander's channel (P1, P2, P4). It runs inside the obiwan container, the only place the commander credential
# exists besides your own hands. Jarvis cannot run this: its container never receives OBIWAN_COMMANDER_TOKEN.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
if ($Forget -and [string]::IsNullOrWhiteSpace($Reason)) { throw 'Forgetting needs -Reason: the tombstone records why.' }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }

Push-Location $Root
try {
    if ($Forget) {
        Write-Host "Ordering subject $SubjectId forgotten..."
        docker --context $Context compose --env-file .env exec -T obiwan uv run --no-dev --frozen obiwan forget $SubjectId --reason $Reason
    } else {
        Write-Host "Promoting subject $SubjectId from relayed to direct..."
        docker --context $Context compose --env-file .env exec -T obiwan uv run --no-dev --frozen obiwan confirm $SubjectId
    }
    if ($LASTEXITCODE -ne 0) { throw 'Obi-Wan refused or the stack is not running. The reason is printed above.' }
} finally {
    Pop-Location
}
