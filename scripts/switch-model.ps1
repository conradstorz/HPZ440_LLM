[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
$ConfigPath = Join-Path $Root 'llama-swap/config.yaml'
if (-not (Test-Path $ConfigPath)) { throw 'Missing llama-swap/config.yaml.' }
# llama-swap rejects any model id it does not know, so only accept an id or alias the config declares.
$Known = Get-Content $ConfigPath | Where-Object { $_ -match '^  "([^"]+)":' -or $_ -match 'aliases:\s*\[(.+)\]' } | ForEach-Object { [regex]::Matches($_, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value } }
if ($Known -notcontains $ModelPath) { throw "ModelPath '$ModelPath' is not a model id or alias in llama-swap/config.yaml. Known: $($Known -join ', ')" }

$Lines = Get-Content $EnvPath
if ($Lines -match '^LLM_MODEL_PATH=') {
    $Lines = $Lines | ForEach-Object { if ($_ -match '^LLM_MODEL_PATH=') { "LLM_MODEL_PATH=$ModelPath" } else { $_ } }
} else {
    $Lines += "LLM_MODEL_PATH=$ModelPath"
}

Set-Content -Path $EnvPath -Value $Lines
Write-Host "Updated LLM_MODEL_PATH=$ModelPath"
Write-Host "This is the model id Jarvis and benchmark.ps1 request. It does not load anything: llama-swap loads models on demand. Re-run scripts/start.ps1 to apply to Jarvis."