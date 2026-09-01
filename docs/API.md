# API

## Health

`GET /healthz`

```json
{"status":"ok"}
```

## Ingest

`POST /v1/copilot/events`

Headers:

```text
Authorization: Bearer <COPILOT_COST_INGEST_KEY>
Content-Type: application/json
```

Returns `202` and `{ "accepted": true, "duplicate": false }`.

## Repository report

`GET /v1/report/repositories?from=YYYY-MM-DD&to=YYYY-MM-DD&repository=owner/repo&user=alice&project=Project%20Name`

## Project report

`GET /v1/report/projects?from=YYYY-MM-DD&to=YYYY-MM-DD`

## User report

`GET /v1/report/users?from=YYYY-MM-DD&to=YYYY-MM-DD`

## Reconciliation report

`GET /v1/reconciliation?from=YYYY-MM-DD&to=YYYY-MM-DD`
