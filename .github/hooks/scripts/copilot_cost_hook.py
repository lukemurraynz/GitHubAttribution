#!/usr/bin/env python3
"""Copilot cost-attribution hook payload processor.

Usage: copilot_cost_hook.py <event-name>   (hook payload JSON on stdin)

The host's shell wrapper (copilot-cost-hook.sh) pipes the hook payload in on
stdin rather than passing it as a command-line argument, so prompt text never
appears in the process list and large payloads are not bounded by the
per-argument execve limit (128 KiB on Linux).

Writes a telemetry record to the local JSONL spool and, when
COPILOT_COST_TELEMETRY_ENDPOINT is set, POSTs it to the collector. This
script never raises: telemetry must not surface as a hook failure in the
host agent.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

EVENT = sys.argv[1] if len(sys.argv) > 1 else 'unknown'

try:
    raw = sys.stdin.buffer.read().decode('utf-8', 'replace') or '{}'
except Exception:
    raw = '{}'

try:
    payload = json.loads(raw)
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


def main():
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
        # No secrets here: the hook sends the telemetry with no auth header.
        # The collector is trusted via its network boundary (IP-restricted
        # ingress / private network), not a bearer token. Nothing that could
        # be a credential is read, stored, or transmitted.
        body = json.dumps(record).encode()
        headers = {'Content-Type': 'application/json'}
        req = Request(endpoint, data=body, headers=headers, method='POST')
        with urlopen(req, timeout=float(os.getenv('COPILOT_COST_TELEMETRY_TIMEOUT_SEC', '3'))):
            pass


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Telemetry must never break the host agent's hook pipeline.
        pass
