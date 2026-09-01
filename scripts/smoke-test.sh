#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m py_compile $(find copilot_cost -name '*.py' -print)
python3 -m json.tool .github/hooks/copilot-cost-attribution.json >/dev/null
python3 -m json.tool schemas/event.schema.json >/dev/null
printf '\nSmoke test passed.\n'
