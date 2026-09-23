# Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing llama.cpp + Open WebUI stack runnable and measurable on the HPZ440's RTX 3060, and add the config surface Phase 1 needs.

**Architecture:** Everything stays operations-only: PowerShell scripts on the Windows workstation drive the remote Docker context `hpz440`, Markdown docs describe manual host steps, and two literal-content PowerShell test scripts assert that files contain what the docs promise. New scripts follow the existing `.env` `Select-String` single-key pattern.

**Tech Stack:** PowerShell 7 (`pwsh`), Docker CLI with remote context `hpz440`, `nvidia/cuda:12.4.1-base-ubuntu22.04` (GPU check), `python:3.12-slim` + `huggingface_hub` (model download), llama.cpp server `timings` response fields.

**Spec:** `docs/superpowers/specs/2026-09-23-phase-0-foundation-design.md`

## Global Constraints

- Host: HPZ440, Ubuntu 24.04.4 LTS, Docker Engine 28.3.3, Compose v5.3.0, context `hpz440`. Nothing runs locally.
- Never chain shell commands with `&&` in tool calls; use separate calls.
- `compose.yaml` is not modified in this phase.
- Default model: `bartowski/Qwen2.5-7B-Instruct-GGUF`, file `Qwen2.5-7B-Instruct-Q4_K_M.gguf`.
- Default `HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data`.
- `WEBUI_SECRET_KEY` default sentinel: `change-me-before-use`. `start.ps1` must refuse it; `stop.ps1` must not check it.
- Tests are `tests/assert-project-shape.ps1` and `tests/assert-script-contracts.ps1`, run with `pwsh -NoProfile -File <path>`. Both must pass at the end of every task.
- `.env` parsing: single keys via `Select-String -Pattern '^KEY=(.+)$'` (lifecycle scripts) or the `Get-Content | Where-Object { $_ -match '^[A-Z0-9_]+=.*$' }` block (health/benchmark). Do not introduce a third style.
- The exact sentence `Public internet exposure is out of scope` must remain in `docs/operations.md`.
- Existing docs headings and script names are asserted by tests; do not rename anything.
- Work on branch `phase-0-foundation`, created from `main`. Commit after each task.

---

## File Structure

- Create `scripts/check-gpu.ps1`: runs `nvidia-smi` in a throwaway CUDA container on the remote host; exit non-zero with guidance if the GPU runtime is missing.
- Create `scripts/fetch-model.ps1`: one-shot container download of one GGUF into `HOST_MODEL_DIR` on the remote host.
- Create `docs/host-setup.md`: manual Ubuntu 24.04 steps for driver, NVIDIA Container Toolkit, and host directories.
- Modify `scripts/start.ps1`: refuse default/missing `WEBUI_SECRET_KEY`.
- Modify `scripts/benchmark.ps1`: add throughput fields from llama.cpp `timings` and `usage`, plus the model path.
- Modify `.env.example`, `.gitignore`: reserve `HOST_JARVIS_DATA_DIR`, ignore `jarvis-data/`.
- Modify `docs/models.md`, `docs/operations.md`, `README.md`, `CLAUDE.md`: document the new scripts, the secret guard, and the measured-throughput table.
- Modify `tests/assert-project-shape.ps1`, `tests/assert-script-contracts.ps1`: assertions for all of the above.

---

### Task 0: Branch

**Files:** none

- [ ] **Step 1: Create the working branch from main**

Run: `git checkout main`
Run: `git pull`
Run: `git checkout -b phase-0-foundation`
Expected: `Switched to a new branch 'phase-0-foundation'`

---

### Task 1: Config reservation and WebUI secret guard

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `scripts/start.ps1`
- Test: `tests/assert-project-shape.ps1`, `tests/assert-script-contracts.ps1`

**Interfaces:**
- Produces: `.env` key `HOST_JARVIS_DATA_DIR` (used by Phase 1, documented in Task 5). `start.ps1` throws when `WEBUI_SECRET_KEY` is missing or equals `change-me-before-use`.

- [ ] **Step 1: Add failing assertions**

Append to `tests/assert-project-shape.ps1`, immediately before the line `$Gitkeep = Join-Path $Root 'models/.gitkeep'`:

```powershell
Assert-FileContains '.env.example' '^HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data$'
Assert-FileContains '.gitignore' '^jarvis-data/$'
```

Append to `tests/assert-script-contracts.ps1`, immediately before the line `Write-Host 'Script contract checks passed.'`:

```powershell
Assert-FileContains 'scripts/start.ps1' 'WEBUI_SECRET_KEY'
Assert-FileContains 'scripts/start.ps1' 'change-me-before-use'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: throws `Expected .env.example to contain pattern: ^HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data$`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: throws `Expected scripts/start.ps1 to contain pattern: WEBUI_SECRET_KEY`

- [ ] **Step 3: Update `.env.example`**

Replace the whole file with:

```text
DOCKER_CONTEXT=hpz440
COMPOSE_PROJECT_NAME=hpz440-llm

HOST_MODEL_DIR=/srv/llm/models
LLM_MODEL_PATH=/models/model.gguf
LLM_CONTEXT_SIZE=4096
LLM_GPU_LAYERS=999
LLM_HOST_PORT=8080

WEBUI_HOST_PORT=3000
WEBUI_SECRET_KEY=change-me-before-use

# Reserved for Phase 1 (Jarvis archive and journal). Not mounted by compose.yaml yet.
HOST_JARVIS_DATA_DIR=/srv/llm/jarvis-data
```

- [ ] **Step 4: Update `.gitignore`**

In the `# Runtime data` block, add `jarvis-data/` after `open-webui/`, so the block reads:

```text
# Runtime data
data/
open-webui/
jarvis-data/
benchmarks/
logs/
*.log
```

- [ ] **Step 5: Add the secret guard to `scripts/start.ps1`**

Replace the whole file with:

```powershell
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'

if (-not (Test-Path $EnvPath)) {
    throw 'Missing .env. Copy .env.example to .env and set LLM_MODEL_PATH before starting.'
}

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
if ([string]::IsNullOrWhiteSpace($Context)) { $Context = 'hpz440' }

$SecretMatch = Select-String -Path $EnvPath -CaseSensitive -Pattern '^WEBUI_SECRET_KEY=(.*)$'
$Secret = if ($SecretMatch) { $SecretMatch.Matches.Groups[1].Value } else { '' }
if ([string]::IsNullOrWhiteSpace($Secret) -or $Secret -eq 'change-me-before-use') {
    throw "WEBUI_SECRET_KEY in .env is missing or still the default 'change-me-before-use'. Set a random value, for example: [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))"
}

$CheckContextScript = Join-Path $Root 'scripts/check-context.ps1'
& $CheckContextScript -Context $Context
Push-Location $Root
try {
    docker --context $Context compose --env-file .env up -d
} finally {
    Pop-Location
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: `Project guardrail checks passed.`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: `Script contract checks passed.`

- [ ] **Step 7: Verify the guard behaves against a real `.env`**

If `.env` does not exist, create it: `Copy-Item .env.example .env`.

Run: `pwsh -NoProfile -File scripts/start.ps1`
Expected (with the default secret): the throw message beginning `WEBUI_SECRET_KEY in .env is missing or still the default`. Nothing is started.

Then set a real value in `.env` (edit the `WEBUI_SECRET_KEY=` line to any random string) and run again:
Run: `pwsh -NoProfile -File scripts/start.ps1`
Expected: proceeds past the guard into `check-context.ps1`. It will then fail at `compose up` today because the host has no NVIDIA runtime; that is expected and not a defect of this task. Stop reading at the first Docker error.

- [ ] **Step 8: Commit**

```bash
git add .env.example .gitignore scripts/start.ps1 tests/assert-project-shape.ps1 tests/assert-script-contracts.ps1
git commit -m "Reserve HOST_JARVIS_DATA_DIR and refuse default WEBUI_SECRET_KEY"
```

---

### Task 2: GPU check script and host setup doc

**Files:**
- Create: `scripts/check-gpu.ps1`
- Create: `docs/host-setup.md`
- Test: `tests/assert-project-shape.ps1`, `tests/assert-script-contracts.ps1`

**Interfaces:**
- Produces: `scripts/check-gpu.ps1 [-Context <name>]`, exit 0 with `nvidia-smi` output when the GPU is container-visible, otherwise throws a message that names `docs/host-setup.md`.

- [ ] **Step 1: Add failing assertions**

Append to `tests/assert-project-shape.ps1`, immediately before `$Gitkeep = Join-Path $Root 'models/.gitkeep'`:

```powershell
Assert-FileContains 'docs/host-setup.md' 'nvidia-container-toolkit'
Assert-FileContains 'docs/host-setup.md' 'nvidia-ctk runtime configure'
```

Append to `tests/assert-script-contracts.ps1`, immediately before `Write-Host 'Script contract checks passed.'`:

```powershell
Assert-FileContains 'scripts/check-gpu.ps1' '--gpus all'
Assert-FileContains 'scripts/check-gpu.ps1' 'nvidia-smi'
Assert-FileContains 'scripts/check-gpu.ps1' 'docs/host-setup\.md'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: throws `Missing file: docs/host-setup.md`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: throws `Missing file: scripts/check-gpu.ps1`

- [ ] **Step 3: Create `scripts/check-gpu.ps1`**

```powershell
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
```

- [ ] **Step 4: Create `docs/host-setup.md`**

```markdown
# HPZ440 Host Setup

One-time steps on the HPZ440 itself (Ubuntu 24.04 LTS), run over SSH as a user with sudo. These are manual because they need sudo, a reboot, and a judgement call on driver versions. After this, everything else is driven from the workstation through the `hpz440` Docker context.

## 1. Physical install

Seat the RTX 3060, connect its PCIe power lead, and boot. Confirm the OS sees it:

```bash
lspci | grep -i nvidia
```

Expected: one line naming an NVIDIA device. If nothing appears, check seating and power before continuing.

## 2. NVIDIA driver

```bash
sudo ubuntu-drivers install
sudo reboot
```

After the reboot:

```bash
nvidia-smi
```

Expected: a table showing the RTX 3060 and a driver version of 550 or newer.

## 3. NVIDIA Container Toolkit

Commands from NVIDIA's installation guide for apt-based distributions:
<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>. Check that page if any step below fails; the repository URL or key location may have changed.

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Confirm Docker now lists the runtime:

```bash
docker info --format '{{range $k,$v := .Runtimes}}{{$k}} {{end}}'
```

Expected: the output includes `nvidia`.

## 4. Verify from the workstation

```powershell
pwsh -NoProfile -File scripts/check-gpu.ps1
```

Expected: `nvidia-smi` output from inside a container, then `GPU check passed on context 'hpz440'.`

## 5. Host directories

Create the directories that `compose.yaml` and the scripts bind-mount, owned by the SSH user so `scripts/fetch-model.ps1` can write there:

```bash
sudo mkdir -p /srv/llm/models /srv/llm/jarvis-data
sudo chown -R "$USER":"$USER" /srv/llm
```

If `.env` overrides `HOST_MODEL_DIR` or `HOST_JARVIS_DATA_DIR`, create those paths instead.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: `Project guardrail checks passed.`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: `Script contract checks passed.`

- [ ] **Step 6: Run the script against the real host (expected failure today)**

Run: `pwsh -NoProfile -File scripts/check-gpu.ps1`
Expected: Docker prints an error such as `could not select device driver "" with capabilities: [[gpu]]`, followed by the script's own throw beginning `GPU is not visible to containers on context 'hpz440'`. The message must mention `docs/host-setup.md`. If instead the script prints `GPU check passed`, the toolkit is already installed and that is also fine.

- [ ] **Step 7: Commit**

```bash
git add scripts/check-gpu.ps1 docs/host-setup.md tests/assert-project-shape.ps1 tests/assert-script-contracts.ps1
git commit -m "Add GPU preflight script and host setup guide"
```

---

### Task 3: Model fetch script

**Files:**
- Create: `scripts/fetch-model.ps1`
- Test: `tests/assert-script-contracts.ps1`

**Interfaces:**
- Consumes: `.env` keys `DOCKER_CONTEXT`, `HOST_MODEL_DIR`.
- Produces: `scripts/fetch-model.ps1 [-Repo <hf repo>] [-File <gguf name>] [-Context <name>]`; on success the file exists at `<HOST_MODEL_DIR>/<File>` on the host and the script prints the `switch-model.ps1` command to run next.

- [ ] **Step 1: Add failing assertions**

Append to `tests/assert-script-contracts.ps1`, immediately before `Write-Host 'Script contract checks passed.'`:

```powershell
Assert-FileContains 'scripts/fetch-model.ps1' 'HOST_MODEL_DIR'
Assert-FileContains 'scripts/fetch-model.ps1' 'huggingface_hub'
Assert-FileContains 'scripts/fetch-model.ps1' 'param\(.*\$Repo'
Assert-FileContains 'scripts/fetch-model.ps1' 'switch-model\.ps1'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: throws `Missing file: scripts/fetch-model.ps1`

- [ ] **Step 3: Create `scripts/fetch-model.ps1`**

```powershell
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
```

Note: the `&&` inside `$ContainerScript` is shell syntax executed inside the container, not a workstation command chain; it is allowed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: `Script contract checks passed.`

- [ ] **Step 5: Exercise against the real host**

This downloads roughly 4.7 GB onto the HPZ440. `HOST_MODEL_DIR` must exist and be writable on the host (see `docs/host-setup.md` section 5). If the directory does not exist yet, create it over SSH first:

Run: `ssh gte@hpz440 "sudo mkdir -p /srv/llm/models"`
Run: `ssh gte@hpz440 "sudo chown -R gte:gte /srv/llm"`

Then:

Run: `pwsh -NoProfile -File scripts/fetch-model.ps1`
Expected: pip and `hf download` progress, then `Model available at /srv/llm/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf on the host.` and the `Next:` line.

Run it a second time:
Run: `pwsh -NoProfile -File scripts/fetch-model.ps1`
Expected: `Already present: /models/Qwen2.5-7B-Instruct-Q4_K_M.gguf` and no pip install.

Confirm on the host:
Run: `ssh gte@hpz440 "ls -la /srv/llm/models"`
Expected: the `.gguf` file, size about 4.7 GB.

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch-model.ps1 tests/assert-script-contracts.ps1
git commit -m "Add fetch-model script for host-side GGUF downloads"
```

---

### Task 4: Benchmark throughput fields

**Files:**
- Modify: `scripts/benchmark.ps1`
- Test: `tests/assert-script-contracts.ps1`

**Interfaces:**
- Consumes: llama.cpp chat completion response fields `timings.prompt_n`, `timings.prompt_per_second`, `timings.predicted_n`, `timings.predicted_per_second`, `usage`.
- Produces: benchmark JSON with new top-level keys `model`, `prompt_tokens`, `prompt_tokens_per_second`, `generated_tokens`, `generated_tokens_per_second`, `usage`, alongside the existing `prompt`, `max_tokens`, `elapsed_ms`, `response`.

- [ ] **Step 1: Add failing assertions**

Append to `tests/assert-script-contracts.ps1`, immediately before `Write-Host 'Script contract checks passed.'`:

```powershell
Assert-FileContains 'scripts/benchmark.ps1' 'predicted_per_second'
Assert-FileContains 'scripts/benchmark.ps1' 'generated_tokens_per_second'
Assert-FileContains 'scripts/benchmark.ps1' 'LLM_MODEL_PATH'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: throws `Expected scripts/benchmark.ps1 to contain pattern: predicted_per_second`

- [ ] **Step 3: Replace `scripts/benchmark.ps1`**

```powershell
[CmdletBinding()]
param(
    [string]$Prompt = 'Write one concise sentence about local LLM operations.',
    [int]$MaxTokens = 64
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$Values = @{}
Get-Content $EnvPath | Where-Object { $_ -match '^[A-Z0-9_]+=.*$' } | ForEach-Object {
    $Name, $Value = $_ -split '=', 2
    $Values[$Name] = $Value
}

$Port = if ($Values.LLM_HOST_PORT) { $Values.LLM_HOST_PORT } else { '8080' }
$Model = if ($Values.LLM_MODEL_PATH) { $Values.LLM_MODEL_PATH } else { $null }
$OutputDir = Join-Path $Root 'benchmarks'
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutputPath = Join-Path $OutputDir "benchmark-$Stamp.json"

$Body = @{
    model = 'local'
    messages = @(@{ role = 'user'; content = $Prompt })
    max_tokens = $MaxTokens
} | ConvertTo-Json -Depth 8

$Started = Get-Date
$Response = Invoke-RestMethod -Uri "http://localhost:$Port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $Body
$ElapsedMs = [int]((Get-Date) - $Started).TotalMilliseconds

# llama.cpp server adds a non-standard "timings" object to OpenAI-compatible responses.
$Timings = $Response.timings
$PromptTokens = if ($Timings) { $Timings.prompt_n } else { $null }
$PromptTps = if ($Timings) { $Timings.prompt_per_second } else { $null }
$GeneratedTokens = if ($Timings) { $Timings.predicted_n } else { $null }
$GeneratedTps = if ($Timings) { $Timings.predicted_per_second } else { $null }

@{
    model = $Model
    prompt = $Prompt
    max_tokens = $MaxTokens
    elapsed_ms = $ElapsedMs
    prompt_tokens = $PromptTokens
    prompt_tokens_per_second = $PromptTps
    generated_tokens = $GeneratedTokens
    generated_tokens_per_second = $GeneratedTps
    usage = $Response.usage
    response = $Response
} | ConvertTo-Json -Depth 16 | Set-Content -Path $OutputPath

if ($null -ne $GeneratedTps) {
    Write-Host ("Benchmark written to {0} ({1:N1} generated tok/s)" -f $OutputPath, [double]$GeneratedTps)
} else {
    Write-Host "Benchmark written to $OutputPath (no timings in response)"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: `Script contract checks passed.`

- [ ] **Step 5: Static sanity check**

The stack cannot run without the GPU, so verify the script parses:

Run: `pwsh -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile('scripts/benchmark.ps1', [ref]$null, [ref]$errs) | Out-Null; if ($errs) { $errs; exit 1 } else { 'parse ok' }"`
Expected: `parse ok`

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark.ps1 tests/assert-script-contracts.ps1
git commit -m "Record llama.cpp throughput fields in benchmark output"
```

---

### Task 5: Documentation and CLAUDE.md

**Files:**
- Modify: `docs/models.md`
- Modify: `docs/operations.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Test: `tests/assert-project-shape.ps1`

**Interfaces:**
- Consumes: script names and behaviors from Tasks 1 to 4.

- [ ] **Step 1: Add failing assertions**

Append to `tests/assert-project-shape.ps1`, immediately before `$Gitkeep = Join-Path $Root 'models/.gitkeep'`:

```powershell
Assert-FileContains 'docs/models.md' 'Qwen2\.5-7B-Instruct'
Assert-FileContains 'docs/models.md' 'Measured'
Assert-FileContains 'docs/operations.md' 'scripts/check-gpu\.ps1'
Assert-FileContains 'docs/operations.md' 'scripts/fetch-model\.ps1'
Assert-FileContains 'docs/operations.md' 'WEBUI_SECRET_KEY'
Assert-FileContains 'README.md' 'scripts/fetch-model\.ps1'
Assert-FileContains 'README.md' 'docs/host-setup\.md'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: throws `Expected docs/models.md to contain pattern: Qwen2\.5-7B-Instruct`

- [ ] **Step 3: Replace `docs/models.md`**

```markdown
# Models

Use 7B instruct GGUF models for the default RTX 3060 12GB profile.

Recommended starting quantizations:

- `Q4_K_M`: best first choice for fitting comfortably in 12GB VRAM.
- `Q5_K_M`: higher quality, still plausible for 7B models depending on context size.

Place model files on the HPZ440 host under `/srv/llm/models` unless `.env` sets a different `HOST_MODEL_DIR`.

Inside the container, models are mounted at `/models`, so `LLM_MODEL_PATH` should look like `/models/name.gguf`.

Do not commit model files. The repository ignores `*.gguf`, `*.safetensors`, checkpoints, and generated model artifacts.

## Fetching a model

`pwsh -NoProfile -File scripts/fetch-model.ps1` downloads one GGUF from Hugging Face straight into `HOST_MODEL_DIR` on the host, using a one-shot container. The default is `bartowski/Qwen2.5-7B-Instruct-GGUF` / `Qwen2.5-7B-Instruct-Q4_K_M.gguf`. Override with `-Repo` and `-File`.

Prefer single-file GGUF builds. Qwen's official `Qwen/Qwen2.5-7B-Instruct-GGUF` repository splits `q4_k_m` into two files (`-00001-of-00002.gguf`), which llama.cpp can load but which the scripts and `LLM_MODEL_PATH` do not handle. Gated repositories (Llama, Gemma) need an authenticated `hf` CLI on the host and a manual copy into `HOST_MODEL_DIR`.

## Measured

Filled in from `scripts/benchmark.ps1` output (`generated_tokens_per_second`) on the real hardware. One row per model and context size tried.

| Model | Quantization | Context | Generated tok/s | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| Qwen2.5-7B-Instruct | Q4_K_M | 4096 | pending hardware | pending hardware | First Phase 0 target. |

Triage target for Phase 1: one email classified in under 10 seconds. If measured throughput allows, raise `LLM_CONTEXT_SIZE` to 8192 in `.env` and add a row here.
```

- [ ] **Step 4: Replace `docs/operations.md`**

```markdown
# Operations

## Host Setup

Before anything else, follow `docs/host-setup.md` once on the HPZ440: GPU install, NVIDIA driver, NVIDIA Container Toolkit, and host directories.

## GPU Check

Run `pwsh -NoProfile -File scripts/check-gpu.ps1` to confirm the GPU is visible to containers on the remote host. It runs `nvidia-smi` inside a throwaway CUDA container and points to `docs/host-setup.md` on failure.

## Fetch a Model

Run `pwsh -NoProfile -File scripts/fetch-model.ps1` to download the default Qwen2.5-7B-Instruct Q4_K_M GGUF into `HOST_MODEL_DIR` on the host. Use `-Repo` and `-File` for a different single-file GGUF. See `docs/models.md`.

Then run `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/<file>.gguf` to point `.env` at it.

## WebUI Secret

`scripts/start.ps1` refuses to start while `WEBUI_SECRET_KEY` in `.env` is missing or still `change-me-before-use`. Set it to a random string once; Open WebUI uses it to sign sessions. One way to generate a value in PowerShell:

```powershell
[Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

`scripts/stop.ps1` never checks the secret, so a stack can always be stopped.

## Start

Run `pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440` before starting.

Run `pwsh -NoProfile -File scripts/start.ps1` to start the stack.

## Stop

Run `pwsh -NoProfile -File scripts/stop.ps1`.

## Health

Run `pwsh -NoProfile -File scripts/health.ps1` to check `/v1/models` and Open WebUI.

## Switch Models

Run `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/name.gguf`.

Restart the stack after switching models.

## Benchmark

Run `pwsh -NoProfile -File scripts/benchmark.ps1` after the API is healthy.

Benchmark JSON is written under `benchmarks/`, which is ignored by git. It includes `generated_tokens_per_second` and `prompt_tokens_per_second` from llama.cpp's `timings` block; record the generated figure in the Measured table in `docs/models.md`.

## Exposure

Public internet exposure is out of scope. Keep this service on the LAN unless a later hardening project adds authentication, TLS, and network controls.
```

- [ ] **Step 5: Update the README quickstart**

Replace the `## Quickstart` section of `README.md` (keep everything else) with:

```markdown
## Quickstart

1. On the HPZ440, follow `docs/host-setup.md` once (GPU, driver, NVIDIA Container Toolkit, host directories).
2. Run `pwsh -NoProfile -File scripts/check-context.ps1 -Context hpz440`.
3. Run `pwsh -NoProfile -File scripts/check-gpu.ps1`.
4. Copy `.env.example` to `.env` and set `WEBUI_SECRET_KEY` to a random value.
5. Run `pwsh -NoProfile -File scripts/fetch-model.ps1` to download the default model to the host.
6. Run `pwsh -NoProfile -File scripts/switch-model.ps1 -ModelPath /models/Qwen2.5-7B-Instruct-Q4_K_M.gguf`.
7. Run `pwsh -NoProfile -File scripts/start.ps1`.
8. Run `pwsh -NoProfile -File scripts/health.ps1`.
9. Run `pwsh -NoProfile -File scripts/benchmark.ps1` and record the result in `docs/models.md`.
```

- [ ] **Step 6: Update `CLAUDE.md`**

In the `## Commands` PowerShell block, add after the `list-models.ps1` line:

```powershell
pwsh -NoProfile -File scripts/check-gpu.ps1                        # nvidia-smi in a throwaway container on hpz440
pwsh -NoProfile -File scripts/fetch-model.ps1 [-Repo r] [-File f]  # one-shot container downloads a GGUF into HOST_MODEL_DIR on the host
```

In `## Architecture`, replace the bullet beginning `Every tunable flows through` with:

```markdown
- Every tunable flows through `.env` (untracked, copied from `.env.example`). The compose file has defaults for each, but `start.ps1`/`stop.ps1` hard-require `.env` to exist, and `start.ps1` refuses to run while `WEBUI_SECRET_KEY` is missing or still `change-me-before-use`. `HOST_JARVIS_DATA_DIR` is reserved in `.env.example` for Phase 1 and not yet mounted.
```

In `## Conventions That Matter Here`, replace the bullet beginning **`.env` parsing is duplicated** with:

```markdown
- **`.env` parsing is duplicated** in `health.ps1` and `benchmark.ps1` (identical `Get-Content | -match '^[A-Z0-9_]+=.*$'` block); `start.ps1`, `stop.ps1`, `list-models.ps1`, `check-gpu.ps1`, and `fetch-model.ps1` use `Select-String` on single keys instead. Keep any parsing change consistent across all seven.
```

- [ ] **Step 7: Run both tests**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: `Project guardrail checks passed.`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: `Script contract checks passed.`

- [ ] **Step 8: Commit**

```bash
git add docs/models.md docs/operations.md README.md CLAUDE.md tests/assert-project-shape.ps1
git commit -m "Document GPU check, model fetch, secret guard, and measured throughput"
```

---

### Task 6: Final validation and pull request

**Files:** none new.

- [ ] **Step 1: Full test run**

Run: `pwsh -NoProfile -File tests/assert-project-shape.ps1`
Expected: `Project guardrail checks passed.`

Run: `pwsh -NoProfile -File tests/assert-script-contracts.ps1`
Expected: `Script contract checks passed.`

- [ ] **Step 2: Ignore rules**

Run: `git check-ignore -v jarvis-data/x benchmarks/x .env models/x.gguf`
Expected: four lines, each naming a `.gitignore` rule. `git status --short` shows no untracked runtime files.

- [ ] **Step 3: Confirm spec exit criteria for the implementation layer**

- `check-gpu.ps1` run today ends with the documented throw naming `docs/host-setup.md` (Task 2 step 6).
- The GGUF exists at `/srv/llm/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf` on the host (Task 3 step 5).
- `start.ps1` refused the default secret and accepted a set one (Task 1 step 7).

Record any that could not be exercised, and why, in the task report.

- [ ] **Step 4: Push and open the PR**

Run: `git push -u origin phase-0-foundation`
Run: `gh pr create --title "Phase 0: GPU preflight, model fetch, benchmark throughput" --body-file -` with body:

```markdown
## Summary
- `scripts/check-gpu.ps1`: nvidia-smi in a throwaway container on hpz440; points to the new `docs/host-setup.md` on failure.
- `scripts/fetch-model.ps1`: one-shot container downloads a single-file GGUF into `HOST_MODEL_DIR` on the host (default Qwen2.5-7B-Instruct Q4_K_M).
- `scripts/benchmark.ps1`: records llama.cpp `timings` throughput and `usage`.
- `start.ps1` refuses the default `WEBUI_SECRET_KEY`; `.env.example` reserves `HOST_JARVIS_DATA_DIR` for Phase 1.
- Docs and CLAUDE.md updated; both literal-content tests extended.

Spec: `docs/superpowers/specs/2026-09-23-phase-0-foundation-design.md`. Hardware validation (GPU install, health, measured tok/s row in `docs/models.md`) is an operator step after the card arrives.

## Test plan
- [ ] `tests/assert-project-shape.ps1` passes
- [ ] `tests/assert-script-contracts.ps1` passes
- [ ] `check-gpu.ps1` fails with the documented message on the current host
- [ ] `fetch-model.ps1` placed the GGUF on the host and is idempotent on re-run

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Expected: a PR URL.

---

## Operator follow-up after hardware arrives (not part of this plan's tasks)

1. `docs/host-setup.md` sections 1 to 3 on the HPZ440.
2. `scripts/check-gpu.ps1` passes.
3. `scripts/start.ps1`, then `scripts/health.ps1` passes.
4. `scripts/benchmark.ps1`; replace the "pending hardware" row in `docs/models.md` with the measured value and date; commit. Phase 0 is then complete per the spec.
