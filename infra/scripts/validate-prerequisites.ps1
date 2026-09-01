# Preprovision gate (Windows/azd local twin). Fails the deploy if the collector
# does not compile and pass its tests. Mirrors validate-prerequisites.sh for the
# Linux/CI path (GitHub Actions ubuntu).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\..')

Write-Host '== validate-prerequisites: compile =='
python -m compileall -q copilot_cost server.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '== validate-prerequisites: unit tests =='
python -m unittest discover -s tests -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '== validate-prerequisites: OK =='
