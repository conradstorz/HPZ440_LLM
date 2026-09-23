[CmdletBinding()]
param(
    [string]$Repo = 'bartowski/Qwen2.5-7B-Instruct-GGUF',
    [string]$File = 'Qwen2.5-7B-Instruct-Q4_K_M.gguf',
    [string]$Context
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }
if ($File -notmatch '^[A-Za-z0-9._-]+\.gguf$') { throw 'File must be a bare GGUF filename such as Qwen2.5-7B-Instruct-Q4_K_M.gguf (no directories).' }
if ($Repo -notmatch '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$') { throw 'Repo must be a Hugging Face repo id such as bartowski/Qwen2.5-7B-Instruct-GGUF.' }

if ([string]::IsNullOrWhiteSpace($Context)) {
    $ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
    if ($ContextMatch) { $Context = $ContextMatch.Matches.Groups[1].Value }
}
if ([string]::IsNullOrWhiteSpace($Context)) { $Context = 'hpz440' }

$HostModelDir = '/srv/llm/models'
$DirMatch = Select-String -Path $EnvPath -Pattern '^HOST_MODEL_DIR=(.+)$'
if ($DirMatch) { $HostModelDir = $DirMatch.Matches.Groups[1].Value }

$ContainerScript = "if [ -f /models/$File ]; then echo 'Already present: /models/$File'; exit 0; fi; pip install --quiet 'huggingface_hub>=0.34,<2' && hf download $Repo $File --local-dir /models"

Write-Host "Downloading $Repo/$File into $HostModelDir on context '$Context'..."
docker --context $Context run --rm -v "${HostModelDir}:/models" python:3.12-slim sh -c $ContainerScript
if ($LASTEXITCODE -ne 0) { throw "Download of $Repo/$File failed on context '$Context'. Gated repositories must be downloaded manually on the host with an authenticated 'hf' CLI and copied into $HostModelDir." }

Write-Host "Model available at $HostModelDir/$File on the host."
Write-Host "Next: pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/$File"
