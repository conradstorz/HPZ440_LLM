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
Assert-FileContains '.env.example' '^LLM_CONTEXT_SIZE=8192$'
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

Assert-FileContains '.env.example' '^HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data$'
Assert-FileContains '.gitignore' '^jarvis-data/$'

Assert-FileContains 'docs/host-setup.md' 'nvidia-container-toolkit'
Assert-FileContains 'docs/host-setup.md' 'nvidia-ctk runtime configure'

Assert-FileContains 'docs/models.md' 'Qwen2\.5-7B-Instruct'
Assert-FileContains 'docs/models.md' 'Measured'
Assert-FileContains 'docs/operations.md' 'scripts/check-gpu\.ps1'
Assert-FileContains 'docs/operations.md' 'scripts/fetch-model\.ps1'
Assert-FileContains 'docs/operations.md' 'WEBUI_SECRET_KEY'
Assert-FileContains 'README.md' 'scripts/fetch-model\.ps1'
Assert-FileContains 'README.md' 'docs/host-setup\.md'

Assert-FileContains 'compose.yaml' '^  jarvis:$'
Assert-FileContains 'compose.yaml' '\$\{JARVIS_HOST_PORT:-8090\}:8090'
Assert-FileContains 'compose.yaml' '\$\{HOST_JARVIS_DATA_DIR:-/srv/llm/jarvis-data\}:/data'
Assert-FileContains 'compose.yaml' 'JARVIS_LLM_BASE_URL=http://llm-api:8080'
Assert-FileContains '.env.example' '^JARVIS_HOST_PORT=8090$'
Assert-FileContains '.env.example' '^JARVIS_GMAIL_ACCOUNT='
Assert-FileContains '.env.example' '^JARVIS_GMAIL_QUERY=in:inbox newer_than:1d category:primary$'
Assert-FileContains '.env.example' '^JARVIS_MAX_MESSAGES_PER_RUN=50$'
Assert-FileContains '.gitignore' '^token\.json$'
Assert-FileContains '.gitignore' '^credentials\.json$'
Assert-FileContains '.gitignore' '^\*\.sqlite$'
Assert-FileContains '.gitignore' '^\.venv/$'
Assert-FileContains 'docs/jarvis.md' '^# Jarvis'
Assert-FileContains 'README.md' 'scripts/jarvis-auth\.ps1'
Assert-FileContains 'docs/roadmap.md' 'Phase 1 status'

Assert-FileContains 'compose.yaml' 'OPENAI_API_BASE_URLS=http://llm-api:8080/v1;http://jarvis:8090/v1'
Assert-FileContains 'compose.yaml' 'JARVIS_WORKSPACE_AGENT_URL'
Assert-FileContains '.env.example' '^JARVIS_WORKSPACE_AGENT_URL=$'
Assert-FileContains 'docs/jarvis.md' '^## Chat'
Assert-FileContains 'docs/roadmap.md' 'Phase 1.5'
Assert-FileContains 'README.md' 'scripts/jarvis-agent-token\.ps1'
Assert-FileContains 'compose.yaml' 'JARVIS_CONTEXT_TOKENS=\$\{LLM_CONTEXT_SIZE:-4096\}'
Assert-FileContains 'compose.yaml' 'ENABLE_FORWARD_USER_INFO_HEADERS=true'

Assert-FileContains 'compose.yaml' '\$\{LLM_PARALLEL:-1\}'
Assert-FileContains '.env.example' '^LLM_PARALLEL=1$'

Assert-FileContains 'README.md' 'scripts/stress-test\.ps1'
Assert-FileContains 'docs/operations.md' 'scripts/stress-test\.ps1'

Assert-FileContains 'docs/cost-model.md' '^# Cost Model'
Assert-FileContains 'docs/cost-model.md' 'lower bound'
Assert-FileContains 'docs/cost-model.md' 'Break-even'
Assert-FileContains 'docs/models.md' 'Concurrency'

Assert-FileContains 'compose.yaml' '^  obiwan:$'
Assert-FileContains 'compose.yaml' '127\.0\.0\.1:\$\{OBIWAN_HOST_PORT:-8070\}:8070'
Assert-FileContains 'compose.yaml' '\$\{HOST_OBIWAN_DIR:-/srv/obiwan\}/corpus:/sources/corpus:ro'
Assert-FileContains 'compose.yaml' '\$\{HOST_OBIWAN_DIR:-/srv/obiwan\}/inbox:/inbox'
Assert-FileContains 'compose.yaml' '\$\{HOST_OBIWAN_DIR:-/srv/obiwan\}/data:/data'
Assert-FileContains 'compose.yaml' 'OBIWAN_SOURCE_ROOTS=corpus=/sources/corpus'
Assert-FileContains 'compose.yaml' 'OBIWAN_COMMANDER_TOKEN=\$\{OBIWAN_COMMANDER_TOKEN:-\}'
Assert-FileContains 'compose.yaml' 'JARVIS_OBIWAN_URL=http://obiwan:8070'
Assert-FileContains 'compose.yaml' 'JARVIS_OBIWAN_READER_TOKEN=\$\{OBIWAN_READER_TOKEN:-\}'
Assert-FileContains 'compose.yaml' 'JARVIS_OBIWAN_WRITER_TOKEN=\$\{OBIWAN_WRITER_TOKEN:-\}'
Assert-FileContains '.env.example' '^HOST_OBIWAN_DIR=/srv/obiwan$'
Assert-FileContains '.env.example' '^OBIWAN_HOST_PORT=8070$'
Assert-FileContains '.env.example' '^OBIWAN_READER_TOKEN=change-me-reader$'
Assert-FileContains '.env.example' '^OBIWAN_WRITER_TOKEN=change-me-writer$'
Assert-FileContains '.env.example' '^OBIWAN_COMMANDER_TOKEN=change-me-commander$'
Assert-FileContains 'docs/obiwan.md' '^# Obi-Wan'
Assert-FileContains 'docs/obiwan.md' '^## Live demonstration'
Assert-FileContains 'docs/roadmap.md' 'Obi-Wan v0\.1'
Assert-FileContains 'README.md' 'scripts/obiwan-scan\.ps1'
Assert-FileContains 'README.md' 'docs/obiwan\.md'
Assert-FileContains 'CLAUDE.md' 'obiwan'

# D4 / S7: the Admiral never receives the commander credential.
$ComposeLines = Get-Content (Join-Path $Root 'compose.yaml')
if ($ComposeLines | Where-Object { $_ -match 'JARVIS_OBIWAN_COMMANDER' }) { throw 'compose.yaml must never hand the commander token to jarvis' }

$Gitkeep = Join-Path $Root 'models/.gitkeep'
if (-not (Test-Path $Gitkeep)) { throw 'Missing models/.gitkeep placeholder' }

Write-Host 'Project guardrail checks passed.'