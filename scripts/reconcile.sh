#!/usr/bin/env bash
set -euo pipefail
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
: "${GITHUB_ORG:?GITHUB_ORG is required}"
: "${FROM:?FROM is required, e.g. 2026-09-01}"
: "${TO:?TO is required, e.g. 2026-09-01}"
python3 -m copilot_cost.cli.main reconcile --org "$GITHUB_ORG" --from "$FROM" --to "$TO" --project-map config/repo-projects.json --repo-file config/repos.txt
