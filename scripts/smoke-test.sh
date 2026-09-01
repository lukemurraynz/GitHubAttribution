#!/usr/bin/env bash
set -euo pipefail
TMP=$(mktemp -d)
trap 'kill ${PID:-} 2>/dev/null || true; rm -rf "$TMP"' EXIT
export COPILOT_COST_DB="$TMP/test.sqlite3"
export COPILOT_COST_INGEST_KEY=test-key
export COPILOT_COST_PORT=18080
export PYTHONPATH="$(pwd)"
python3 server.py >/tmp/copilot-cost-test.log 2>&1 & PID=$!
sleep 1
curl -fsS http://127.0.0.1:18080/healthz
curl -fsS -X POST http://127.0.0.1:18080/v1/copilot/events \
  -H 'Authorization: Bearer test-key' -H 'Content-Type: application/json' \
  --data '{"schemaVersion":1,"eventId":"smoke-1","event":"sessionStart","observedAt":"2026-09-01T00:00:00Z","sessionId":"s1","user":"alice","repository":"acme/project-a","source":"copilot-hook"}'
curl -fsS 'http://127.0.0.1:18080/v1/report'
echo
