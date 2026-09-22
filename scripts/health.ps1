[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$Values = @{}
Get-Content $EnvPath | Where-Object { $_ -match '^[A-Z0-9_]+=.*$' } | ForEach-Object {
    $Name, $Value = $_ -split '=', 2
    $Values[$Name] = $Value
}

$LlmPort = if ($Values.LLM_HOST_PORT) { $Values.LLM_HOST_PORT } else { '8080' }
$WebPort = if ($Values.WEBUI_HOST_PORT) { $Values.WEBUI_HOST_PORT } else { '3000' }

Invoke-RestMethod -Uri "http://localhost:$LlmPort/v1/models" -Method Get | Out-Null
Invoke-WebRequest -Uri "http://localhost:$WebPort" -UseBasicParsing | Out-Null
Write-Host "LLM API and Open WebUI are reachable on localhost:$LlmPort and localhost:$WebPort."