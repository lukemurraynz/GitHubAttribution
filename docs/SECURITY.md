# Security and privacy

## Hook telemetry

The hook package intentionally does not transmit prompt or tool-result content. It records counts/lengths and, by default, a SHA-256 digest for submitted prompts. Disable prompt hashing with `COPILOT_COST_HASH_PROMPTS=false`.

Hostnames are hashed before transmission.

### Hooks carry NO secrets (design guarantee)

The hook is **secret-free by design**. It does not read, store, or transmit any token, API key, or secret. The two hook scripts (`.sh` and `.ps1`) build a telemetry record, write it to the local `events.jsonl`, and POST it to the collector **with no `Authorization` header and no credential in the body**. The locally-persisted record contains only: `schemaVersion`, `eventId`, `event`, `observedAt`, `sessionId`, `user`, `repository`, `branch`, `commit`, `toolName`, `hostHash`, `source`, and (for prompts/tools) `promptChars`/`promptSha256`/`toolResultChars`.

Because the hook authenticates nothing, the **collector must be protected by its network boundary**, not by a per-hook secret:

- **Safe default (deployed):** the Azure Container Apps collector is **internal-only** (VNet) unless the operator supplies an `allowedIngressIpCidr`. When a CIDR is supplied it is external HTTPS-only with an **IP allow-list**. Never expose a secret-free collector to the public internet.
- **Optional bearer auth:** the collector can still require a shared `COPILOT_COST_INGEST_KEY` bearer header (if you prefer that model), but that requires every hook to hold the shared secret — which this repo deliberately avoids. Default and recommended: network-boundary trust, no hook secret.

## Collector

The collector API (`POST /v1/copilot/events`, `GET /v1/report*`, `GET /healthz`) is a reference HTTP server. For production, run it behind HTTPS with restricted ingress (see `docs/SETUP-REAL-ORG.md`), an `/healthz` readiness probe, and scale-to-zero to limit cost and surface area.

## GitHub token (collector → GitHub)

The **collector→GitHub** reconcile authenticates with a token resolved at runtime from, in order:

1. the `GITHUB_TOKEN` environment variable (local dev), or
2. an **Azure Key Vault secret** (`COPILOT_COST_KEYVAULT_URL` + `COPILOT_COST_KEYVAULT_SECRET`) fetched via the collector's **managed identity** (stdlib-only, through the Azure Instance Metadata Service).

So the GitHub token is **never in the hook**, never committed, and never shipped in the image — it lives in Key Vault and the deployed collector reads it with its own managed identity (granted *Key Vault Secrets User*). Use a GitHub App or fine-grained token with the minimum organisation billing permission required to read the AI-credit endpoint.

## Retention

Define a retention period for event telemetry. Billing records generally need longer retention than raw hook events. In production, separate operational telemetry from financial records so retention can be managed independently.
