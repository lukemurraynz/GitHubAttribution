#!/usr/bin/env bash
set -euo pipefail

EVENT_NAME="${1:-unknown}"
INPUT="$(cat || true)"

python3 - "$EVENT_NAME" "$INPUT" <<'PY'
import hashlib, json, os, socket, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

EVENT = sys.argv[1]
RAW = sys.argv[2] or '{}'
try:
    payload = json.loads(RAW)
except json.JSONDecodeError:
    payload = {}

def run(*args):
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return ''

def repo_context(cwd):
    root = run('git', '-C', cwd, 'rev-parse', '--show-toplevel') or cwd
    remote = run('git', '-C', root, 'config', '--get', 'remote.origin.url')
    branch = run('git', '-C', root, 'branch', '--show-current')
    commit = run('git', '-C', root, 'rev-parse', 'HEAD')
    slug = ''
    if remote:
        r = remote.rstrip('/').removesuffix('.git')
        if r.startswith('git@github.com:'):
            slug = r.split(':', 1)[1]
        elif 'github.com/' in r:
            slug = r.split('github.com/', 1)[1]
    return root, slug or Path(root).name, branch or None, commit or None

cwd = payload.get('cwd') or os.getcwd()
root, repository, branch, commit = repo_context(cwd)
user = os.getenv('COPILOT_COST_USER') or os.getenv('GITHUB_ACTOR') or run('git', 'config', '--get', 'user.name') or os.getenv('USER') or os.getenv('USERNAME') or 'unknown'
now = datetime.now(timezone.utc).isoformat()
session_id = payload.get('sessionId') or payload.get('session_id')

record = {
    'schemaVersion': 1,
    'eventId': hashlib.sha256(f'{EVENT}|{now}|{session_id or ""}|{repository}|{os.urandom(8).hex()}'.encode()).hexdigest(),
    'event': EVENT,
    'observedAt': now,
    'sessionId': session_id,
    'user': user,
    'repository': repository,
    'branch': branch,
    'commit': commit,
    'toolName': payload.get('toolName') or payload.get('tool_name'),
    'hostHash': hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16],
    'source': 'copilot-hook'
}

if EVENT == 'userPromptSubmitted':
    prompt = payload.get('prompt') or ''
    record['promptChars'] = len(prompt)
    if os.getenv('COPILOT_COST_HASH_PROMPTS', 'true').lower() == 'true' and prompt:
        record['promptSha256'] = hashlib.sha256(prompt.encode()).hexdigest()

if EVENT == 'postToolUse':
    result = payload.get('toolResult') or payload.get('tool_result') or {}
    text = result.get('textResultForLlm') or result.get('text_result_for_llm') or ''
    record['toolResultChars'] = len(text)

log_dir = Path(os.getenv('COPILOT_COST_LOG_DIR') or (Path(root) / '.copilot' / 'usage'))
log_dir.mkdir(parents=True, exist_ok=True)
with (log_dir / 'events.jsonl').open('a', encoding='utf-8') as fh:
    fh.write(json.dumps(record, separators=(',', ':')) + '\n')

endpoint = os.getenv('COPILOT_COST_TELEMETRY_ENDPOINT')
if endpoint:
    try:
        token = os.getenv('COPILOT_COST_INGEST_KEY', '')
        body = json.dumps(record).encode()
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        req = Request(endpoint, data=body, headers=headers, method='POST')
        with urlopen(req, timeout=float(os.getenv('COPILOT_COST_TELEMETRY_TIMEOUT_SEC', '3'))):
            pass
    except Exception:
        pass
PY
