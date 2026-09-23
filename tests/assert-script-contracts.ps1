$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Assert-FileContains {
    param([string]$Path, [string]$Pattern)
    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) { throw "Missing file: $Path" }
    $Content = Get-Content -Raw $FullPath
    $NormalizedContent = $Content -replace "`r?`n", "`n"
    $Lines = Get-Content $FullPath
    if (($Content -notmatch $Pattern) -and ($NormalizedContent -notmatch "(?s)$Pattern") -and (-not ($Lines | Where-Object { $_ -match $Pattern }))) { throw "Expected $Path to contain pattern: $Pattern" }
}

Assert-FileContains 'scripts/check-context.ps1' 'docker context inspect'
Assert-FileContains 'scripts/check-context.ps1' 'DOCKER_CONTEXT'
Assert-FileContains 'scripts/check-context.ps1' 'hpz440'
Assert-FileContains 'scripts/start.ps1' 'Copy \.env\.example to \.env'
Assert-FileContains 'scripts/start.ps1' 'compose --env-file \.env up -d'
Assert-FileContains 'scripts/stop.ps1' 'compose --env-file \.env down'
Assert-FileContains 'scripts/start.ps1' 'scripts/check-context\.ps1'
Assert-FileContains 'scripts/health.ps1' '/v1/models'
Assert-FileContains 'scripts/health.ps1' 'WEBUI_HOST_PORT'
Assert-FileContains 'scripts/list-models.ps1' 'HOST_MODEL_DIR'
Assert-FileContains 'scripts/list-models.ps1' '\*\.gguf'
Assert-FileContains 'scripts/switch-model.ps1' 'param\(.*\$ModelPath'
Assert-FileContains 'scripts/switch-model.ps1' 'LLM_MODEL_PATH='
Assert-FileContains 'scripts/benchmark.ps1' '/v1/chat/completions'
Assert-FileContains 'scripts/benchmark.ps1' 'benchmarks'
Assert-FileContains 'scripts/start.ps1' 'WEBUI_SECRET_KEY'
Assert-FileContains 'scripts/start.ps1' 'change-me-before-use'

Assert-FileContains 'scripts/check-gpu.ps1' '--gpus all'
Assert-FileContains 'scripts/check-gpu.ps1' 'nvidia-smi'
Assert-FileContains 'scripts/check-gpu.ps1' 'docs/host-setup\.md'

Assert-FileContains 'scripts/fetch-model.ps1' 'HOST_MODEL_DIR'
Assert-FileContains 'scripts/fetch-model.ps1' 'huggingface_hub'
Assert-FileContains 'scripts/fetch-model.ps1' 'param\(.*\$Repo'
Assert-FileContains 'scripts/fetch-model.ps1' 'switch-model\.ps1'

Assert-FileContains 'scripts/benchmark.ps1' 'predicted_per_second'
Assert-FileContains 'scripts/benchmark.ps1' 'generated_tokens_per_second'
Assert-FileContains 'scripts/benchmark.ps1' 'LLM_MODEL_PATH'

Write-Host 'Script contract checks passed.'