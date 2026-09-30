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
$JarvisPort = if ($Values.JARVIS_HOST_PORT) { $Values.JARVIS_HOST_PORT } else { '8090' }

Invoke-RestMethod -Uri "http://localhost:$LlmPort/v1/models" -Method Get | Out-Null
Invoke-WebRequest -Uri "http://localhost:$WebPort" -UseBasicParsing | Out-Null
$Jarvis = Invoke-RestMethod -Uri "http://localhost:$JarvisPort/health" -Method Get
Write-Host "LLM API, Open WebUI, and Jarvis are reachable on localhost:$LlmPort, localhost:$WebPort, and localhost:$JarvisPort (jarvis: $($Jarvis.messages) messages, llm reachable from container: $($Jarvis.llm))."