#!/usr/bin/env sh
# Preprovision gate for the azd deployment. Fails the deploy if the collector
# does not compile and pass its test suite. Fail closed: any non-zero exits.
set -eu

cd "$(dirname "$0")/../.." || exit 1

echo "== validate-prerequisites: compile =="
python3 -m compileall -q copilot_cost server.py
echo "== validate-prerequisites: unit tests =="
python3 -m unittest discover -s tests -p 'test_*.py'
echo "== validate-prerequisites: OK =="
