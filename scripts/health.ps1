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

$Failed = @()

try {
    Invoke-RestMethod -Uri "http://localhost:$LlmPort/v1/models" -Method Get | Out-Null
    Write-Host "LLM API (localhost:$LlmPort/v1/models): OK"
} catch {
    $Failed += 'LLM API'
    Write-Host "LLM API (localhost:$LlmPort/v1/models): FAIL $($_.Exception.Message)"
}

try {
    Invoke-WebRequest -Uri "http://localhost:$WebPort" -UseBasicParsing | Out-Null
    Write-Host "Open WebUI (localhost:$WebPort): OK"
} catch {
    $Failed += 'Open WebUI'
    Write-Host "Open WebUI (localhost:$WebPort): FAIL $($_.Exception.Message)"
}

try {
    $Jarvis = Invoke-RestMethod -Uri "http://localhost:$JarvisPort/health" -Method Get
    Write-Host "Jarvis (localhost:$JarvisPort/health): OK ($($Jarvis.messages) messages, llm reachable from container: $($Jarvis.llm))"
} catch {
    $Failed += 'Jarvis'
    Write-Host "Jarvis (localhost:$JarvisPort/health): FAIL $($_.Exception.Message)"
}

if ($Failed.Count -gt 0) { throw "Unreachable: $($Failed -join ', ')." }
Write-Host "All three services are reachable."