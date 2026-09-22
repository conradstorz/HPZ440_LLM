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

@{
    prompt = $Prompt
    max_tokens = $MaxTokens
    elapsed_ms = $ElapsedMs
    response = $Response
} | ConvertTo-Json -Depth 16 | Set-Content -Path $OutputPath

Write-Host "Benchmark written to $OutputPath"