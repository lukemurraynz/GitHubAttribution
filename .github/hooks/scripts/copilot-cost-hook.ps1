param(
  [Parameter(Mandatory=$true)] [string]$EventName
)

$ErrorActionPreference = 'Stop'
$raw = [Console]::In.ReadToEnd()
try { $payload = if ($raw) { $raw | ConvertFrom-Json } else { [pscustomobject]@{} } }
catch { $payload = [pscustomobject]@{} }

function Invoke-Git([string[]]$Args) {
  try { return ((& git @Args 2>$null) | Out-String).Trim() } catch { return '' }
}

$cwd = if ($payload.cwd) { [string]$payload.cwd } else { (Get-Location).Path }
$root = Invoke-Git @('-C',$cwd,'rev-parse','--show-toplevel')
if (-not $root) { $root = $cwd }
$remote = Invoke-Git @('-C',$root,'config','--get','remote.origin.url')
$branch = Invoke-Git @('-C',$root,'branch','--show-current')
$commit = Invoke-Git @('-C',$root,'rev-parse','HEAD')

$repo = Split-Path $root -Leaf
if ($remote) {
  $clean = $remote.TrimEnd('/') -replace '\.git$',''
  if ($clean -match '^git@github\.com:(.+)$') { $repo = $Matches[1] }
  elseif ($clean -match 'github\.com/(.+)$') { $repo = $Matches[1] }
}

$user = $env:COPILOT_COST_USER
if (-not $user) { $user = $env:GITHUB_ACTOR }
if (-not $user) { $user = Invoke-Git @('config','--get','user.name') }
if (-not $user) { $user = $env:USERNAME }
if (-not $user) { $user = 'unknown' }

$sessionId = if ($payload.sessionId) { [string]$payload.sessionId } elseif ($payload.session_id) { [string]$payload.session_id } else { $null }
$toolName = if ($payload.toolName) { [string]$payload.toolName } elseif ($payload.tool_name) { [string]$payload.tool_name } else { $null }
$observedAt = [DateTimeOffset]::UtcNow.ToString('o')
$guid = [guid]::NewGuid().ToString('N')
$hasher = [System.Security.Cryptography.SHA256]::Create()
$eventId = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes("$EventName|$observedAt|$guid")))).Replace('-','').ToLowerInvariant()
$hostHash = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($env:COMPUTERNAME)))).Replace('-','').Substring(0,16).ToLowerInvariant()

$record = [ordered]@{
  schemaVersion = 1
  eventId = $eventId
  event = $EventName
  observedAt = $observedAt
  sessionId = $sessionId
  user = $user
  repository = $repo
  branch = if ($branch) { $branch } else { $null }
  commit = if ($commit) { $commit } else { $null }
  toolName = $toolName
  hostHash = $hostHash
  source = 'copilot-hook'
}

if ($EventName -eq 'userPromptSubmitted') {
  $prompt = if ($payload.prompt) { [string]$payload.prompt } else { '' }
  $record.promptChars = $prompt.Length
  if (($env:COPILOT_COST_HASH_PROMPTS -ne 'false') -and $prompt) {
    $record.promptSha256 = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($prompt)))).Replace('-','').ToLowerInvariant()
  }
}

if ($EventName -eq 'postToolUse') {
  $result = if ($payload.toolResult) { $payload.toolResult } elseif ($payload.tool_result) { $payload.tool_result } else { $null }
  $text = if ($result -and $result.textResultForLlm) { [string]$result.textResultForLlm } elseif ($result -and $result.text_result_for_llm) { [string]$result.text_result_for_llm } else { '' }
  $record.toolResultChars = $text.Length
}

$logDir = if ($env:COPILOT_COST_LOG_DIR) { $env:COPILOT_COST_LOG_DIR } else { Join-Path $root '.copilot/usage' }
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$record | ConvertTo-Json -Compress | Add-Content -Encoding UTF8 -Path (Join-Path $logDir 'events.jsonl')

if ($env:COPILOT_COST_TELEMETRY_ENDPOINT) {
  try {
    $headers = @{}
    if ($env:COPILOT_COST_INGEST_KEY) { $headers['Authorization'] = "Bearer $env:COPILOT_COST_INGEST_KEY" }
    Invoke-RestMethod -Uri $env:COPILOT_COST_TELEMETRY_ENDPOINT -Method Post -Headers $headers -ContentType 'application/json' -Body ($record | ConvertTo-Json -Compress) -TimeoutSec ([int]($env:COPILOT_COST_TELEMETRY_TIMEOUT_SEC ?? 3)) | Out-Null
  } catch { }
}
