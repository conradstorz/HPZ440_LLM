[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$PortMatch = Select-String -Path $EnvPath -Pattern '^JARVIS_HOST_PORT=(.+)$'
$Port = if ($PortMatch) { $PortMatch.Matches.Groups[1].Value } else { '8090' }
$Base = "http://localhost:$Port"

Write-Host "Triggering a Jarvis run at $Base/run (this blocks until the pass finishes)..."
$Resp = Invoke-WebRequest -Uri "$Base/run" -Method Post -SkipHttpErrorCheck -UseBasicParsing
if ($Resp.StatusCode -eq 409) { throw 'A run is already in progress.' }
if ($Resp.StatusCode -ge 400) { throw "Run failed (HTTP $($Resp.StatusCode)): $($Resp.Content)" }
$Health = Invoke-RestMethod -Uri "$Base/health" -Method Get
Write-Host "Messages archived: $($Health.messages). Last run: $($Health.last_run). LLM reachable: $($Health.llm)."
Write-Host "Open $Base/ for the briefing."
