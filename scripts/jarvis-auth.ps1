[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CredentialsPath
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
if (-not (Test-Path $CredentialsPath)) { throw "credentials.json not found at $CredentialsPath. See docs/jarvis.md for creating the OAuth client." }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
$DataMatch = Select-String -Path $EnvPath -Pattern '^HOST_JARVIS_DATA_DIR=(.+)$'
$DataDir = if ($DataMatch) { $DataMatch.Matches.Groups[1].Value } else { '/srv/llm/jarvis-data' }

$JarvisDir = Join-Path $Root 'jarvis'
$TokenPath = Join-Path $JarvisDir 'token.json'
Push-Location $JarvisDir
try {
    Write-Host 'Opening the Google consent screen in your browser (read-only Gmail scope)...'
    uv run jarvis auth $CredentialsPath --out $TokenPath
    if ($LASTEXITCODE -ne 0) { throw 'jarvis auth failed.' }
} finally {
    Pop-Location
}

Write-Host "Copying token.json to ${DataDir}/secrets on context '$Context'..."
Get-Content -Raw $TokenPath | docker --context $Context run --rm -i -v "${DataDir}:/data" alpine sh -c 'mkdir -p /data/secrets; cat > /data/secrets/token.json; chmod 600 /data/secrets/token.json'
if ($LASTEXITCODE -ne 0) { throw 'Copy to the host failed.' }
Remove-Item $TokenPath
Write-Host 'Done. credentials.json stays on this workstation; only token.json (refresh token, read-only scope) is on the host.'
Write-Host 'Next: pwsh -NoProfile -File scripts/start.ps1  then  pwsh -NoProfile -File scripts/jarvis-run.ps1'
