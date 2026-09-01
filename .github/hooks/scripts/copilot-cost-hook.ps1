param([string]$EventName = "unknown")
$ErrorActionPreference = "Stop"
$inputText = [Console]::In.ReadToEnd(); if ([string]::IsNullOrWhiteSpace($inputText)) { $inputText = "{}" }
try { $payload = $inputText | ConvertFrom-Json -Depth 20 } catch { $payload = [pscustomobject]@{} }
function Invoke-Git([string[]]$Args) { try { $o=& git @Args 2>$null; if($LASTEXITCODE -eq 0){return (($o|Out-String).Trim())} } catch {}; return "" }
function Sha256([string]$Text){$sha=[Security.Cryptography.SHA256]::Create();try{return ([Convert]::ToHexString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).ToLowerInvariant()}finally{$sha.Dispose()}}
$cwd=if($payload.cwd){[string]$payload.cwd}else{(Get-Location).Path}
$repoRoot=Invoke-Git @("-C",$cwd,"rev-parse","--show-toplevel");if(-not $repoRoot){$repoRoot=$cwd}
$remote=Invoke-Git @("-C",$repoRoot,"config","--get","remote.origin.url");$branch=Invoke-Git @("-C",$repoRoot,"branch","--show-current");$commit=Invoke-Git @("-C",$repoRoot,"rev-parse","HEAD")
$repoSlug="";if($remote){$clean=$remote.TrimEnd('/') -replace '\.git$','';if($clean -match 'github\.com[:/](.+)$'){$repoSlug=$Matches[1]}};if(-not $repoSlug){$repoSlug=Split-Path $repoRoot -Leaf}
$user=$env:GITHUB_ACTOR;if(-not $user){$user=$env:USERNAME};if(-not $user){$user=[Environment]::UserName}
$sessionId=if($payload.sessionId){$payload.sessionId}else{$payload.session_id};$toolName=if($payload.toolName){$payload.toolName}else{$payload.tool_name}
$record=[ordered]@{schemaVersion=1;eventId=(Sha256 ($inputText+$EventName+[DateTime]::UtcNow.ToString('o'))).Substring(0,24);event=$EventName;observedAt=[DateTime]::UtcNow.ToString('o');sessionId=$sessionId;user=$user;hostnameHash=(Sha256 $env:COMPUTERNAME).Substring(0,16);repository=$repoSlug;branch=if($branch){$branch}else{$null};commit=if($commit){$commit}else{$null};toolName=$toolName;source='copilot-hook'}
if($EventName -eq 'userPromptSubmitted'){$prompt=if($payload.prompt){[string]$payload.prompt}else{""};$record.promptChars=$prompt.Length;$record.promptSha256=if($prompt){Sha256 $prompt}else{$null}}
if($EventName -eq 'postToolUse'){$result=if($payload.toolResult){$payload.toolResult}else{$payload.tool_result};$text=if($result.textResultForLlm){[string]$result.textResultForLlm}elseif($result.text_result_for_llm){[string]$result.text_result_for_llm}else{""};$record.toolResultChars=$text.Length}
$logDir=if($env:COPILOT_COST_LOG_DIR){$env:COPILOT_COST_LOG_DIR}else{Join-Path $repoRoot '.copilot/usage'};New-Item -ItemType Directory -Path $logDir -Force|Out-Null;($record|ConvertTo-Json -Compress -Depth 20)|Add-Content -Path (Join-Path $logDir 'events.jsonl') -Encoding utf8
if($env:COPILOT_COST_TELEMETRY_ENDPOINT){try{$body=$record|ConvertTo-Json -Compress -Depth 20;$timeout=3;if($env:COPILOT_COST_TELEMETRY_TIMEOUT_SEC){$timeout=[int]$env:COPILOT_COST_TELEMETRY_TIMEOUT_SEC};$headers=@{};if($env:COPILOT_COST_INGEST_KEY){$headers['Authorization']='Bearer '+$env:COPILOT_COST_INGEST_KEY};Invoke-RestMethod -Uri $env:COPILOT_COST_TELEMETRY_ENDPOINT -Method Post -ContentType 'application/json' -Headers $headers -Body $body -TimeoutSec $timeout|Out-Null}catch{}}
