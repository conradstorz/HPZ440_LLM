$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Assert-FileContains {
    param([string]$Path, [string]$Pattern)
    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) { throw "Missing file: $Path" }
    $Content = Get-Content -Raw $FullPath
    $Lines = Get-Content $FullPath
    if (($Content -notmatch $Pattern) -and (-not ($Lines | Where-Object { $_ -match $Pattern }))) { throw "Expected $Path to contain pattern: $Pattern" }
}

Assert-FileContains '.gitignore' '^\.env$'
Assert-FileContains '.gitignore' '\*\.gguf$'
Assert-FileContains '.gitignore' '^benchmarks/$'
Assert-FileContains '.env.example' '^DOCKER_CONTEXT=hpz440$'
Assert-FileContains '.env.example' '^LLM_CONTEXT_SIZE=4096$'
Assert-FileContains '.env.example' '^LLM_GPU_LAYERS=999$'
Assert-FileContains '.env.example' '^LLM_HOST_PORT=8080$'
Assert-FileContains '.env.example' '^WEBUI_HOST_PORT=3000$'
Assert-FileContains 'compose.yaml' 'llm-api:'
Assert-FileContains 'compose.yaml' 'open-webui:'
Assert-FileContains 'compose.yaml' '\$\{LLM_HOST_PORT:-8080\}:8080'
Assert-FileContains 'compose.yaml' '\$\{WEBUI_HOST_PORT:-3000\}:8080'
Assert-FileContains 'compose.yaml' 'NVIDIA_VISIBLE_DEVICES=all'
Assert-FileContains 'compose.yaml' '--model'
Assert-FileContains 'compose.yaml' '\$\{LLM_MODEL_PATH:-/models/model\.gguf\}'
Assert-FileContains 'compose.yaml' 'OPENAI_API_BASE_URL=http://llm-api:8080/v1'
Assert-FileContains 'README.md' 'OpenAI-compatible API'
Assert-FileContains 'README.md' 'scripts/start\.ps1'
Assert-FileContains 'README.md' 'Open WebUI'
Assert-FileContains 'docs/models.md' 'Q4_K_M'
Assert-FileContains 'docs/models.md' 'Q5_K_M'
Assert-FileContains 'docs/models.md' '/srv/llm/models'
Assert-FileContains 'docs/operations.md' 'scripts/check-context\.ps1'
Assert-FileContains 'docs/operations.md' 'scripts/switch-model\.ps1'
Assert-FileContains 'docs/operations.md' 'scripts/benchmark\.ps1'
Assert-FileContains 'docs/operations.md' 'Public internet exposure is out of scope'

$Gitkeep = Join-Path $Root 'models/.gitkeep'
if (-not (Test-Path $Gitkeep)) { throw 'Missing models/.gitkeep placeholder' }

Write-Host 'Project guardrail checks passed.'