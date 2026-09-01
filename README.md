# GitHub Copilot Cost Attribution Platform

A working reference implementation for attributing GitHub Copilot AI-credit consumption to repositories and users across an organisation.

## Included

- GitHub Copilot repo-level hooks for Linux/macOS and Windows.
- Central HTTP collector.
- SQLite event store.
- GitHub billing reconciler.
- Repository-aware reconciliation using GitHub's billing usage summary where available.
- Authoritative organization AI-credit import.
- Explicit fallback attribution when repository-scoped billing data is unavailable.
- JSON report API.
- Docker image and Compose file.
- Smoke test.

## Quick start

```bash
export COPILOT_COST_INGEST_KEY='replace-me'
python3 server.py
```

Point the repository hooks at the collector:

```bash
export COPILOT_COST_TELEMETRY_ENDPOINT='https://collector.example.com/v1/copilot/events'
export COPILOT_COST_INGEST_KEY='replace-me'
```

Reconcile a date range:

```bash
export GITHUB_TOKEN='github-token-with-billing-read-access'
python3 copilot_cost.py reconcile --org my-org --from 2026-09-01 --to 2026-09-01 --repo my-org/project-a --repo my-org/project-b
```

Query the report:

```bash
curl 'http://localhost:8080/v1/report?from=2026-09-01&to=2026-09-01'
```

## Billing model

GitHub AI credits are the financial source of truth. The service never estimates credits from prompt characters or tool counts. Hook telemetry exists to provide repository/session attribution context.

## Production notes

This package is dependency-free and is intended as a reference implementation. For production, put the collector behind your standard identity/reverse-proxy layer, move storage to a managed relational database, and run reconciliation as a scheduled job.

## Project mapping

Edit `config/repo-projects.json` to map repositories into your internal project/cost-centre taxonomy. Reports expose the mapped project and use `unmapped` when no mapping exists.

## Scheduled reconciliation

The included `.github/workflows/reconcile.yml` runs daily. Configure `COPILOT_BILLING_TOKEN` as a secret with the GitHub billing permissions required by your organization.
