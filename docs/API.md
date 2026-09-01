# API

## Health
`GET /healthz`

## Ingest
`POST /v1/copilot/events`

Headers:
`Authorization: Bearer <COPILOT_COST_INGEST_KEY>`
`Content-Type: application/json`

Body: the hook event schema in `schemas/event.schema.json`.

The endpoint is idempotent on `eventId`.

## Report
`GET /v1/report?from=2026-09-01&to=2026-09-01&repository=org/repo&user=alice`

Returns allocated AI credits and USD by repository/user/day.
