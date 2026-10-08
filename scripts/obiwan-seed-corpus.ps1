[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceDir
)

# Copies a local directory of documents into HOST_OBIWAN_DIR/corpus on the HPZ440. The corpus is mounted read-only
# into the obiwan container, so this goes through a throwaway container that mounts the host directory writable.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
if (-not (Test-Path $SourceDir -PathType Container)) { throw "SourceDir not found: $SourceDir" }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
$DirMatch = Select-String -Path $EnvPath -Pattern '^HOST_OBIWAN_DIR=(.+)$'
$HostDir = if ($DirMatch) { $DirMatch.Matches.Groups[1].Value } else { '/srv/obiwan' }

Write-Host "Copying $SourceDir into ${HostDir}/corpus on context '$Context'..."
$Id = docker --context $Context create -v "${HostDir}/corpus:/dst" alpine true
if ($LASTEXITCODE -ne 0) { throw 'Could not create the helper container.' }
try {
    docker --context $Context cp "$SourceDir/." "${Id}:/dst/"
    if ($LASTEXITCODE -ne 0) { throw 'Copy failed.' }
} finally {
    docker --context $Context rm -f $Id | Out-Null
}
Write-Host "Done. Next: pwsh -NoProfile -File scripts/obiwan-scan.ps1"
