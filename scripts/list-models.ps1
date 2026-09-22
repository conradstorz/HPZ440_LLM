[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
$HostModelDir = '/srv/llm/models'

if (Test-Path $EnvPath) {
    $Match = Select-String -Path $EnvPath -Pattern '^HOST_MODEL_DIR=(.+)$'
    if ($Match) { $HostModelDir = $Match.Matches.Groups[1].Value }
}

Write-Host "Remote HOST_MODEL_DIR: $HostModelDir"
Get-ChildItem -Path (Join-Path $Root 'models') -Filter '*.gguf' -File -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Name