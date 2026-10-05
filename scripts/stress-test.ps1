<#
Concurrency sweep for the llama.cpp server on the HPZ440.

For each slot count it rewrites .env, restarts llm-api, samples GPU power in a
throwaway container, runs bench/load.py against http://hpz440:8080, and merges
the results. .env is restored byte-for-byte in the finally block, including on
Ctrl+C -- LLM_CONTEXT_SIZE also feeds JARVIS_CONTEXT_TOKENS, so leaving it
raised would silently change Jarvis's budget.

Jarvis is unavailable while this runs. The sweep takes several minutes.
#>
[CmdletBinding()]
param(
    [int[]]$Slots = @(1, 2, 4, 8),
    [int]$CtxPerSlot = 2048,
    [int]$RequestsPerClient = 5,
    [int]$PromptTokens = 1000,
    [int]$MaxTokens = 300,
    [int]$IdleSampleSeconds = 20
)

$ErrorActionPreference = 'Stop'
# docker/compose failures must surface through $LASTEXITCODE, not a thrown
# terminating error, or the oom/unhealthy/error branches below never run.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root '.env'
if (-not (Test-Path $EnvPath)) { throw 'Missing .env. Copy .env.example to .env first.' }

$ContextMatch = Select-String -Path $EnvPath -Pattern '^DOCKER_CONTEXT=(.+)$'
$Context = if ($ContextMatch) { $ContextMatch.Matches.Groups[1].Value } else { 'hpz440' }
$ModelMatch = Select-String -Path $EnvPath -Pattern '^LLM_MODEL_PATH=(.+)$'
if (-not $ModelMatch) { throw 'LLM_MODEL_PATH missing from .env.' }
$Model = $ModelMatch.Matches.Groups[1].Value

$BaseUrl = 'http://hpz440:8080'
$CudaImage = 'nvidia/cuda:12.4.1-base-ubuntu22.04'
$SmiQuery = 'power.draw,utilization.gpu,memory.used'
# A literal comma-separated bareword passed straight into a Start-Job scriptblock
# gets re-tokenized as a PowerShell array and lands in argv as three separate
# tokens ("--format=csv", "noheader", "nounits"), which nvidia-smi then rejects
# ("Option noheader is not recognized"). Routing it through a variable, exactly
# like $SmiQuery above, keeps it one opaque token. Verified against the live
# server: the literal form reproduces the error every time; this form does not.
$SmiFormat = 'csv,noheader,nounits'

# Byte-for-byte backup so the restore cannot reformat the operator's file.
$OriginalEnv = [System.IO.File]::ReadAllBytes($EnvPath)

function Set-EnvKey {
    param([string]$Name, [string]$Value)
    $Lines = Get-Content $EnvPath
    if ($Lines | Where-Object { $_ -match "^$Name=" }) {
        $Lines = $Lines | ForEach-Object { if ($_ -match "^$Name=") { "$Name=$Value" } else { $_ } }
    } else {
        $Lines += "$Name=$Value"
    }
    # Set-Content writes CRLF by default on Windows PowerShell, which would turn
    # every other line in the file -- including LLM_MODEL_PATH -- into CRLF too.
    # A trailing \r riding along in a value docker compose passes into the
    # container command array breaks llama.cpp's --model argument. Write LF
    # explicitly so a mid-sweep rewrite cannot corrupt the file docker compose
    # is about to read, independent of the final byte-for-byte restore below.
    $Text = ($Lines -join "`n") + "`n"
    [System.IO.File]::WriteAllText($EnvPath, $Text)
}

# The sampler runs unbounded and is killed explicitly, so it always outlives the load. A
# guessed timeout would expire mid-load at high slot counts and report watts from a partial
# window.
$SamplerName = 'hpz440-bench-smi'

function Start-GpuSampler {
    docker --context $Context rm -f $SamplerName 2>$null | Out-Null
    Start-Job -ScriptBlock {
        param($Ctx, $Image, $Query, $Format, $Name)
        docker --context $Ctx run --rm --name $Name --gpus all $Image `
            nvidia-smi --query-gpu=$Query --format=$Format -l 1
    } -ArgumentList $Context, $CudaImage, $SmiQuery, $SmiFormat, $SamplerName
}

function Stop-GpuSampler {
    param($Job)
    # Killing the container ends the piped process, which completes the job.
    docker --context $Context kill $SamplerName 2>$null | Out-Null
    $Lines = Receive-Job -Job $Job -Wait -AutoRemoveJob 2>$null
    $Watts = @(); $Vram = @()
    foreach ($Line in $Lines) {
        $Parts = ($Line -split ',') | ForEach-Object { $_.Trim() }
        if ($Parts.Count -ge 3 -and $Parts[0] -match '^[\d.]+$') {
            $Watts += [double]$Parts[0]
            $Vram += [double]$Parts[2]
        }
    }
    if ($Watts.Count -eq 0) { return $null }
    [pscustomobject]@{
        mean = [math]::Round(($Watts | Measure-Object -Average).Average, 2)
        max  = [math]::Round(($Watts | Measure-Object -Maximum).Maximum, 2)
        vram = [math]::Round(($Vram | Measure-Object -Maximum).Maximum, 0)
        n    = $Watts.Count
    }
}

function Wait-ForModel {
    param([int]$TimeoutSeconds = 180)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $Deadline) {
        try {
            Invoke-RestMethod -Uri "$BaseUrl/v1/models" -Method Get -TimeoutSec 5 | Out-Null
            return $true
        } catch { Start-Sleep -Seconds 3 }
    }
    return $false
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutputDir = Join-Path $Root 'benchmarks'
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputPath = Join-Path $OutputDir "stress-$Stamp.json"
$Points = @()

# Baseline draw with the model resident in VRAM and no requests in flight. This is NOT a
# cold-idle GPU -- llama.cpp holds the weights, and that is the state the box actually sits in
# 24/7, which is the right number for the cost model. docs/cost-model.md labels it so.
Write-Host "Sampling baseline GPU power (model resident, no load) for $IdleSampleSeconds s..."
$IdleSampler = Start-GpuSampler
Start-Sleep -Seconds $IdleSampleSeconds
$IdleStats = Stop-GpuSampler $IdleSampler
if ($null -eq $IdleStats) {
    Write-Warning 'GPU telemetry unavailable. Throughput will still be measured; docs/cost-model.md cannot be regenerated without watts.'
}

# docker compose resolves compose.yaml and --env-file .env relative to the current
# directory, as every other script in this repo (start.ps1, stop.ps1, jarvis-reindex.ps1)
# accounts for by running from $Root.
Push-Location $Root
try {
    foreach ($N in $Slots) {
        $TotalCtx = $N * $CtxPerSlot
        Write-Host ""
        Write-Host "=== $N slot(s), $CtxPerSlot ctx each (total $TotalCtx) ==="
        Set-EnvKey -Name 'LLM_PARALLEL' -Value "$N"
        Set-EnvKey -Name 'LLM_CONTEXT_SIZE' -Value "$TotalCtx"

        docker --context $Context compose --env-file .env up -d llm-api
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "llm-api failed to start at $N slots (likely out of VRAM). Recording oom and continuing."
            $Points += [pscustomobject]@{ slots = $N; ctx_per_slot = $CtxPerSlot; status = 'oom' }
            continue
        }
        if (-not (Wait-ForModel)) {
            Write-Warning "llm-api did not answer /v1/models at $N slots. Recording unhealthy and stopping the sweep."
            $Points += [pscustomobject]@{ slots = $N; ctx_per_slot = $CtxPerSlot; status = 'unhealthy' }
            break
        }

        $Sampler = Start-GpuSampler
        $Json = & uv --directory (Join-Path $Root 'bench') run python -m bench.load `
            --base-url $BaseUrl --model $Model --slots $N --ctx-per-slot $CtxPerSlot `
            --requests-per-client $RequestsPerClient --prompt-tokens $PromptTokens `
            --max-tokens $MaxTokens
        $LoadExit = $LASTEXITCODE
        $LoadStats = Stop-GpuSampler $Sampler

        if ($LoadExit -ne 0) {
            Write-Warning "Load generator failed at $N slots (exit $LoadExit). Recording error and continuing."
            $Points += [pscustomobject]@{ slots = $N; ctx_per_slot = $CtxPerSlot; status = 'error' }
            continue
        }

        $Point = $Json | ConvertFrom-Json
        $Point | Add-Member -NotePropertyName status -NotePropertyValue 'ok'
        $Point | Add-Member -NotePropertyName gpu_watts_idle -NotePropertyValue $(if ($IdleStats) { $IdleStats.mean } else { $null })
        $Point | Add-Member -NotePropertyName gpu_watts_mean -NotePropertyValue $(if ($LoadStats) { $LoadStats.mean } else { $null })
        $Point | Add-Member -NotePropertyName gpu_watts_max -NotePropertyValue $(if ($LoadStats) { $LoadStats.max } else { $null })
        $Point | Add-Member -NotePropertyName vram_mb_max -NotePropertyValue $(if ($LoadStats) { $LoadStats.vram } else { $null })
        $Points += $Point

        Write-Host ("  aggregate {0:N1} tok/s, per-client {1:N1} tok/s, TTFT p95 {2:N0} ms, {3} W mean" -f `
            $Point.aggregate_output_tps, $Point.per_client_output_tps, $Point.ttft_ms_p95, $Point.gpu_watts_mean)
        if (-not $Point.prefill_valid) {
            Write-Warning "  Prefix cache served $($Point.cached_tokens_total) prompt tokens at $N slots -- ignore the prefill rate for this point."
        }
    }
}
finally {
    Write-Host ""
    Write-Host 'Restoring .env and restarting llm-api at production settings...'
    [System.IO.File]::WriteAllBytes($EnvPath, $OriginalEnv)
    docker --context $Context rm -f $SamplerName 2>$null | Out-Null
    docker --context $Context compose --env-file .env up -d llm-api
    if ($LASTEXITCODE -ne 0) { Write-Warning 'llm-api did not restart cleanly. Run scripts/start.ps1.' }
    Pop-Location
}

@{
    started       = $Stamp
    model         = $Model
    ctx_per_slot  = $CtxPerSlot
    prompt_tokens = $PromptTokens
    max_tokens    = $MaxTokens
    capex_usd     = 300.0
    price_per_kwh = 0.17
    gpu_watts_idle = $(if ($IdleStats) { $IdleStats.mean } else { $null })
    points        = $Points
} | ConvertTo-Json -Depth 12 | Set-Content -Path $OutputPath

Write-Host "Sweep written to $OutputPath"
Write-Host "Next: uv --directory bench run python -m bench.report --sweep $OutputPath"
