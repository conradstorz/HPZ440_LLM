[CmdletBinding()]
param(
    [string]$TokenFile = (Join-Path $env:USERPROFILE '.jarvis\agent_token')
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
if (-not (Test-Path $TokenFile)) { throw "agent_token not found at $TokenFile. Paste the GTE workspace agent's bearer token into that file (one line, no quotes). See docs/jarvis.md." }
if ((Get-Item $TokenFile).Length -eq 0) { throw "agent_token at $TokenFile is empty. Paste the GTE workspace agent's bearer token into that file." }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
$DataMatch = Select-String -Path $EnvPath -Pattern '^HOST_JARVIS_DATA_DIR=(.+)$'
$DataDir = if ($DataMatch) { $DataMatch.Matches.Groups[1].Value } else { '/srv/llm/jarvis-data' }
$UrlMatch = Select-String -Path $EnvPath -Pattern '^JARVIS_WORKSPACE_AGENT_URL=(.+)$'
if (-not $UrlMatch) { Write-Host 'Note: JARVIS_WORKSPACE_AGENT_URL is empty in .env, so the document tools stay disabled until you set it.' }

Write-Host "Copying the agent token to ${DataDir}/secrets on context '$Context'..."
Get-Content -Raw $TokenFile | docker --context $Context run --rm -i -v "${DataDir}:/data" alpine sh -e -c 'mkdir -p /data/secrets; cat > /data/secrets/agent_token.tmp; test -s /data/secrets/agent_token.tmp; mv /data/secrets/agent_token.tmp /data/secrets/agent_token; chmod 600 /data/secrets/agent_token'
if ($LASTEXITCODE -ne 0) { throw 'Copy to the host failed.' }
Write-Host "Done. The token is at ${DataDir}/secrets/agent_token on the host, mode 600. It was never printed here."
Write-Host 'Next: pwsh -NoProfile -File scripts/start.ps1  then ask Jarvis in Open WebUI to list your documents.'
