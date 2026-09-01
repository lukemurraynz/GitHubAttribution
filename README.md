# GitHub Copilot Cost Attribution Platform

A reference implementation for attributing GitHub Copilot AI-credit spend to repositories and projects across multiple users.

## What it does

1. Repository-level Copilot hooks emit privacy-conscious session/activity telemetry.
2. A central collector stores the telemetry with idempotency.
3. A scheduled reconciler imports GitHub's organisation AI-credit usage report, which is the billing source of truth.
4. The attribution engine allocates each user's/model's daily AI-credit total across repositories using observed activity for that user/day.
5. Repository-to-project mappings roll repo costs into project and cost-centre views.
6. The API exposes operational health, repo/project/user reports, and raw reconciliation totals.

**Important:** GitHub's AI-credit report is the authoritative cost record. Repository/project figures are an internal allocation unless GitHub itself supplies a repository-scoped AI-credit record in the future. The service labels the allocation method and confidence explicitly.

## Quick start

### 1. Start the collector

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m copilot_cost.service.server
```

Default: `http://localhost:8080`.

### 2. Configure hooks in a consuming repo

Copy `.github/hooks/copilot-cost-attribution.json` and `.github/hooks/scripts/` into the target repository. The hook paths are relative to the repository root.

Set:

```text
COPILOT_COST_TELEMETRY_ENDPOINT=http://collector:8080/v1/copilot/events
COPILOT_COST_INGEST_KEY=<shared-secret>
```

### 3. Configure repository → project mapping

Edit `config/repo-projects.json`:

```json
{
  "acme/platform-api": {
    "project": "Customer Platform",
    "costCenter": "Digital"
  }
}
```

### 4. Configure Copilot users

For organisation-managed Copilot, populate `config/users.txt` with the GitHub logins whose Copilot usage should be reconciled. The organisation AI-credit endpoint supports a user filter; using the user list produces materially better attribution than importing only an organisation-wide total.

### 5. Reconcile GitHub billing

```bash
export GITHUB_TOKEN=...
python3 -m copilot_cost.cli.main reconcile \
  --org acme \
  --from 2026-09-01 \
  --to 2026-09-01 \
  --project-map config/repo-projects.json \
  --user-file config/users.txt
```

For organisation-managed Copilot, the token needs organisation Administration read access for the AI-credit endpoint.

## Reporting

```text
GET /healthz
GET /v1/report?from=2026-09-01&to=2026-09-01
GET /v1/report/repositories?from=...&to=...
GET /v1/report/projects?from=...&to=...
GET /v1/report/users?from=...&to=...
GET /v1/reconciliation?from=...&to=...
```

Example:

```bash
curl http://localhost:8080/v1/report/projects?from=2026-09-01\&to=2026-09-01
```

## Attribution algorithm

For each organisation AI-credit row, the service groups hook events by user and UTC date. Repository share is calculated from weighted activity:

`score = session_seconds + (prompt_count * PROMPT_WEIGHT) + (tool_event_count * TOOL_WEIGHT)`

Default weights are defined in `.env.example` and can be changed. Allocation is proportional to score and preserves the exact imported AI-credit quantity at the daily user/model row level.

If a billing row is user-specific, only that user's observed repositories are eligible. If the billing row is organisation-wide, the service can use all active users for that day; this is marked lower confidence because the bill itself does not identify the user.

## Privacy

Hooks do not store prompt contents or tool result contents. A prompt length and SHA-256 digest may be recorded only when the prompt hook is enabled. Hostnames are hashed. The collector stores the original hook envelope for reconciliation/debugging; configure retention in your database deployment.

## Production shape

The bundled SQLite collector is intentionally simple and self-contained. A production deployment can place an Azure Container App / App Service / Function in front of a durable store (PostgreSQL, Azure SQL, Fabric Eventhouse, ADX, etc.) while keeping the same event schema and reconciliation contract.

See `docs/ARCHITECTURE.md`, `docs/RECONCILIATION.md`, and `docs/SECURITY.md`.
