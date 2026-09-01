#!/usr/bin/env bash
set -euo pipefail
: "${GITHUB_TOKEN:?Set GITHUB_TOKEN}"
python3 -m copilot_cost.cli.main reconcile --org "${1:?org}" --from "${2:?from YYYY-MM-DD}" --to "${3:?to YYYY-MM-DD}"
