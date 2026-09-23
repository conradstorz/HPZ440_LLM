[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'

if (-not (Test-Path $EnvPath)) {
    throw 'Missing .env. Copy .env.example to .env and set LLM_MODEL_PATH before starting.'
}

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
if ([string]::IsNullOrWhiteSpace($Context)) { $Context = 'hpz440' }

$SecretMatch = Select-String -Path $EnvPath -Pattern '^WEBUI_SECRET_KEY=(.*)$'
$Secret = if ($SecretMatch) { $SecretMatch.Matches.Groups[1].Value } else { '' }
if ([string]::IsNullOrWhiteSpace($Secret) -or $Secret -eq 'change-me-before-use') {
    throw "WEBUI_SECRET_KEY in .env is missing or still the default 'change-me-before-use'. Set a random value, for example: [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))"
}

$CheckContextScript = Join-Path $Root 'scripts/check-context.ps1'
& $CheckContextScript -Context $Context
Push-Location $Root
try {
    docker --context $Context compose --env-file .env up -d
} finally {
    Pop-Location
}
