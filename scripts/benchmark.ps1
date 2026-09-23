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
