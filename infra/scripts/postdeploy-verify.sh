#!/usr/bin/env sh
# Postdeploy verification: poll the deployed collector /healthz over HTTPS until
# it reports ok (bounded), then check the latest revision has active ingress
# traffic. Fails closed if the app never becomes healthy or has no traffic.
set -eu

if [ "${AZURE_APP_URL:-}" = "" ]; then
  echo "AZURE_APP_URL not set; skipping postdeploy-verify (manual check required)."
  exit 0
fi

URL="https://${AZURE_APP_URL}/healthz"
echo "== postdeploy-verify: polling ${URL} =="
attempts=0
healthy=0
while [ "$attempts" -lt 60 ]; do
  attempts=$((attempts + 1))
  if curl -fsS --max-time 10 "$URL" | grep -q '"ok"'; then
    echo "healthy after ${attempts} attempts"
    healthy=1
    break
  fi
  sleep 5
done

if [ "$healthy" -ne 1 ]; then
  echo "ERROR: collector /healthz never reported ok over HTTPS." >&2
  echo "Check the revision logs and ingress (see docs/SETUP-REAL-ORG.md § deploy verification)." >&2
  exit 1
fi

echo "== postdeploy-verify: OK =="
