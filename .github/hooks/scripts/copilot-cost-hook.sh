#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:-unknown}"
INPUT="$(cat || true)"
python3 - "$EVENT_NAME" "$INPUT" <<'PY'
import json, os, subprocess, sys, hashlib, socket, getpass
from datetime import datetime, timezone
from pathlib import Path
EVENT_NAME = sys.argv[1]
RAW = sys.argv[2] or "{}"
try: payload = json.loads(RAW)
except Exception: payload = {}
def run(*args):
    try: return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception: return ""
cwd = payload.get("cwd") or os.getcwd()
repo_root = run("git", "-C", cwd, "rev-parse", "--show-toplevel") or cwd
remote = run("git", "-C", repo_root, "config", "--get", "remote.origin.url")
branch = run("git", "-C", repo_root, "branch", "--show-current")
commit = run("git", "-C", repo_root, "rev-parse", "HEAD")
repo_name = Path(repo_root).name
repo_slug = ""
if remote:
    cleaned = remote.rstrip("/").removesuffix(".git")
    if "github.com/" in cleaned: repo_slug = cleaned.split("github.com/",1)[1]
    elif "github.com:" in remote: repo_slug = remote.split("github.com:",1)[1].removesuffix(".git")
user = os.getenv("GITHUB_ACTOR") or os.getenv("USER") or os.getenv("USERNAME") or getpass.getuser()
record = {
    "schemaVersion": 1,
    "eventId": hashlib.sha256((RAW + EVENT_NAME + datetime.now(timezone.utc).isoformat()).encode()).hexdigest()[:24],
    "event": EVENT_NAME,
    "observedAt": datetime.now(timezone.utc).isoformat(),
    "sessionId": payload.get("sessionId") or payload.get("session_id"),
    "user": user,
    "hostnameHash": hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16],
    "repository": repo_slug or repo_name,
    "branch": branch or None,
    "commit": commit or None,
    "toolName": payload.get("toolName") or payload.get("tool_name"),
    "source": "copilot-hook"
}
if EVENT_NAME == "userPromptSubmitted":
    prompt = payload.get("prompt") or ""
    record["promptChars"] = len(prompt)
    record["promptSha256"] = hashlib.sha256(prompt.encode()).hexdigest() if prompt else None
if EVENT_NAME == "postToolUse":
    result = payload.get("toolResult") or payload.get("tool_result") or {}
    text = result.get("textResultForLlm") or result.get("text_result_for_llm") or ""
    record["toolResultChars"] = len(text)
log_dir = Path(os.getenv("COPILOT_COST_LOG_DIR") or (Path(repo_root) / ".copilot" / "usage"))
log_dir.mkdir(parents=True, exist_ok=True)
with (log_dir / "events.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps(record, separators=(",", ":")) + "\n")
endpoint = os.getenv("COPILOT_COST_TELEMETRY_ENDPOINT")
if endpoint:
    try:
        import urllib.request
        req = urllib.request.Request(endpoint, data=json.dumps(record).encode(), headers={"Content-Type":"application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=int(os.getenv("COPILOT_COST_TELEMETRY_TIMEOUT_SEC","3"))).read()
    except Exception: pass
PY
