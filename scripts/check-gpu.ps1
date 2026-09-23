[CmdletBinding()]
param(
    [string]$Context
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'

if ([string]::IsNullOrWhiteSpace($Context) -and (Test-Path $EnvPath)) {
    $ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
    if ($ContextMatch) { $Context = $ContextMatch.Matches.Groups[1].Value }
}
if ([string]::IsNullOrWhiteSpace($Context)) { $Context = 'hpz440' }

$Image = 'nvidia/cuda:12.4.1-base-ubuntu22.04'
Write-Host "Running nvidia-smi in $Image on context '$Context'..."
docker --context $Context run --rm --gpus all $Image nvidia-smi
if ($LASTEXITCODE -ne 0) {
    throw "GPU is not visible to containers on context '$Context'. Usual causes: the NVIDIA Container Toolkit is not installed, or Docker was not restarted after 'nvidia-ctk runtime configure'. See docs/host-setup.md."
}
Write-Host "GPU check passed on context '$Context'."
