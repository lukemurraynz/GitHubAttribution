#!/usr/bin/env bash
# Copilot cost-attribution hook wrapper (bash).
#
# Contract: never fail, never write to stdout, never put the hook payload on
# the command line. The payload is piped to copilot_cost_hook.py on stdin so
# prompt text stays out of the process list and large payloads are not bounded
# by the per-argument execve limit (128 KiB on Linux).
set -euo pipefail

EVENT_NAME="${1:-unknown}"
INPUT="$(cat || true)"

# Prefer python3, fall back to python (Windows Git Bash often only has the
# latter). With neither, exit quietly: a missing interpreter must not turn
# every hook event into a host-visible error.
PYBIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYBIN" ]; then
  exit 0
fi

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Swallow stderr and non-zero exits: telemetry must stay silent even when the
# interpreter is a broken stub (e.g. the Windows Store python3 alias).
printf '%s' "$INPUT" | "$PYBIN" "$HOOK_DIR/copilot_cost_hook.py" "$EVENT_NAME" 2>/dev/null || true
