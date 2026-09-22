[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
if ($ModelPath -notmatch '^/models/.+\.gguf$') { throw 'ModelPath must be a container path like /models/name.gguf.' }

$Lines = Get-Content $EnvPath
if ($Lines -match '^LLM_MODEL_PATH=') {
    $Lines = $Lines | ForEach-Object { if ($_ -match '^LLM_MODEL_PATH=') { "LLM_MODEL_PATH=$ModelPath" } else { $_ } }
} else {
    $Lines += "LLM_MODEL_PATH=$ModelPath"
}

Set-Content -Path $EnvPath -Value $Lines
Write-Host "Updated LLM_MODEL_PATH=$ModelPath"