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

function Assert-FileNotContains {
    param([string]$Path, [string]$Pattern)
    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) { throw "Missing file: $Path" }
    $Lines = Get-Content $FullPath
    if ($Lines | Where-Object { $_ -match $Pattern }) { throw "Expected $Path NOT to contain pattern: $Pattern" }
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

Assert-FileNotContains 'scripts/stop.ps1' 'WEBUI_SECRET_KEY'
Assert-FileContains 'scripts/fetch-model.ps1' '\$Repo -notmatch'
Assert-FileContains 'scripts/fetch-model.ps1' '\$File -notmatch'

Assert-FileContains 'scripts/jarvis-auth.ps1' 'Copy \.env\.example to \.env'
Assert-FileContains 'scripts/jarvis-auth.ps1' 'HOST_JARVIS_DATA_DIR'
Assert-FileContains 'scripts/jarvis-auth.ps1' 'param\(.*\$CredentialsPath'
Assert-FileContains 'scripts/jarvis-auth.ps1' 'jarvis auth'
Assert-FileContains 'scripts/jarvis-auth.ps1' '/data/secrets/token\.json'
Assert-FileContains 'scripts/jarvis-run.ps1' 'JARVIS_HOST_PORT'
Assert-FileContains 'scripts/jarvis-run.ps1' '/run'
Assert-FileContains 'scripts/jarvis-run.ps1' '/health'
Assert-FileContains 'scripts/jarvis-reindex.ps1' 'DOCKER_CONTEXT'
Assert-FileContains 'scripts/jarvis-reindex.ps1' 'jarvis reindex'
Assert-FileContains 'scripts/health.ps1' 'JARVIS_HOST_PORT'
Assert-FileNotContains 'scripts/jarvis-auth.ps1' 'gmail\.modify'
Assert-FileNotContains 'scripts/jarvis-auth.ps1' 'gmail\.send'

Assert-FileContains 'scripts/jarvis-agent-token.ps1' 'Copy \.env\.example to \.env'
Assert-FileContains 'scripts/jarvis-agent-token.ps1' 'HOST_JARVIS_DATA_DIR'
Assert-FileContains 'scripts/jarvis-agent-token.ps1' '/data/secrets/agent_token'
Assert-FileContains 'scripts/jarvis-agent-token.ps1' 'sh -e -c'

Assert-FileContains 'scripts/stress-test.ps1' 'LLM_PARALLEL'
Assert-FileContains 'scripts/stress-test.ps1' 'hpz440:8080'
Assert-FileContains 'scripts/stress-test.ps1' 'finally'
Assert-FileContains 'scripts/stress-test.ps1' 'bench\.load'
Assert-FileContains 'scripts/stress-test.ps1' 'ignore the prefill'
Assert-FileNotContains 'scripts/stress-test.ps1' 'localhost:8080'

Assert-FileContains 'scripts/start.ps1' 'OBIWAN_COMMANDER_TOKEN'
Assert-FileContains 'scripts/start.ps1' 'change-me'
foreach ($Script in 'scripts/obiwan-scan.ps1', 'scripts/obiwan-status.ps1', 'scripts/obiwan-reindex.ps1', 'scripts/obiwan-confirm.ps1') {
    Assert-FileContains $Script 'Copy \.env\.example to \.env'
    Assert-FileContains $Script 'DOCKER_CONTEXT'
    Assert-FileContains $Script 'exec -T obiwan'
}
Assert-FileContains 'scripts/obiwan-scan.ps1' 'obiwan scan'
Assert-FileContains 'scripts/obiwan-status.ps1' 'obiwan status'
Assert-FileContains 'scripts/obiwan-reindex.ps1' 'obiwan reindex'
Assert-FileContains 'scripts/obiwan-confirm.ps1' 'param\(.*\$SubjectId'
Assert-FileContains 'scripts/obiwan-confirm.ps1' 'obiwan confirm'
Assert-FileContains 'scripts/obiwan-confirm.ps1' 'obiwan forget'
Assert-FileContains 'scripts/obiwan-seed-corpus.ps1' 'param\(.*\$SourceDir'
Assert-FileContains 'scripts/obiwan-seed-corpus.ps1' 'HOST_OBIWAN_DIR'
Assert-FileContains 'scripts/obiwan-seed-corpus.ps1' 'docker --context \$Context cp'
Assert-FileNotContains 'scripts/obiwan-seed-corpus.ps1' 'exec -T obiwan'

Assert-FileContains 'scripts/obiwan-call.ps1' 'Copy \.env\.example to \.env'
Assert-FileContains 'scripts/obiwan-call.ps1' 'DOCKER_CONTEXT'
Assert-FileContains 'scripts/obiwan-call.ps1' 'exec -T obiwan'
Assert-FileContains 'scripts/obiwan-call.ps1' 'obiwan call'
Assert-FileContains 'scripts/obiwan-call.ps1' 'param\(.*\$Path'

Write-Host 'Script contract checks passed.'