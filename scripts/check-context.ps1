[CmdletBinding()]
param(
    [string]$Context = $env:DOCKER_CONTEXT
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Context)) { $Context = 'hpz440' }

docker context inspect $Context *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker context '$Context' is not available. Create or select the remote hpz440 context first." }

docker --context $Context info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker context '$Context' is not reachable. Check LAN, SSH, and the Docker daemon on HPZ440." }

Write-Host "Docker context '$Context' is reachable."