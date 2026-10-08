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

$SecretMatch = Select-String -Path $EnvPath -CaseSensitive -Pattern '^WEBUI_SECRET_KEY=(.*)$'
$Secret = if ($SecretMatch) { $SecretMatch.Matches.Groups[1].Value } else { '' }
if ([string]::IsNullOrWhiteSpace($Secret) -or $Secret -eq 'change-me-before-use') {
    throw "WEBUI_SECRET_KEY in .env is missing or still the default 'change-me-before-use'. Set a random value, for example: [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))"
}

$Tokens = @{}
foreach ($Name in 'OBIWAN_READER_TOKEN', 'OBIWAN_WRITER_TOKEN', 'OBIWAN_COMMANDER_TOKEN') {
    $TokenMatch = Select-String -Path $EnvPath -CaseSensitive -Pattern "^$Name=(.*)$"
    $Token = if ($TokenMatch) { $TokenMatch.Matches.Groups[1].Value } else { '' }
    if ([string]::IsNullOrWhiteSpace($Token) -or $Token.StartsWith('change-me')) {
        throw "$Name in .env is missing or still a 'change-me' placeholder. Set a random value, for example: [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))"
    }
    $Tokens[$Name] = $Token
}
if (($Tokens.Values | Select-Object -Unique | Measure-Object).Count -ne 3) {
    throw 'OBIWAN_READER_TOKEN, OBIWAN_WRITER_TOKEN and OBIWAN_COMMANDER_TOKEN must be three different values; a shared token collapses the three roles into one.'
}

$CheckContextScript = Join-Path $Root 'scripts/check-context.ps1'
& $CheckContextScript -Context $Context
Push-Location $Root
try {
    docker --context $Context compose --env-file .env up -d --build
} finally {
    Pop-Location
}
