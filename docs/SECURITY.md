# Security and privacy

## Hook telemetry

The hook package intentionally does not transmit prompt or tool-result content. It records counts/lengths and, by default, a SHA-256 digest for submitted prompts. Disable prompt hashing with `COPILOT_COST_HASH_PROMPTS=false`.

Hostnames are hashed before transmission.

### Hook secret handling (storage guarantee)

The hook **never stores** the ingest key or any token/API key. The `COPILOT_COST_INGEST_KEY` is read from the environment **only at POST time** and placed in the `Authorization` header of the single network request. It is **not** part of the telemetry record and is **never written** to the local `events.jsonl` file or any other log. The locally-persisted record contains only: `schemaVersion`, `eventId`, `event`, `observedAt`, `sessionId`, `user`, `repository`, `branch`, `commit`, `toolName`, `hostHash`, `source`, and (for prompts/tools) `promptChars`/`promptSha256`/`toolResultChars`.

Because the key still travels over the network to the collector, **the collector endpoint must use HTTPS** (e.g. the Azure Container Apps deployment in `docs/SETUP-REAL-ORG.md`), never plain HTTP across an untrusted network. The key itself is a shared ingest secret for the collector, not a GitHub token; keep it out of committed `.env` files regardless.

## Collector

Set `COPILOT_COST_INGEST_KEY` and require an `Authorization: Bearer ...` header. The included server is a reference implementation, not an internet-facing hardened service. Put TLS, authentication, rate limiting and network restrictions in front of it for production.

For a hardened deployment, use the **Azure Container Apps** path (see `docs/SETUP-REAL-ORG.md` § collector deployment): the collector runs behind **HTTPS-only external ingress**, with the ingest key supplied as an **Azure Key Vault secret reference** wired via a **managed identity** (never a plaintext env var), an `/healthz` readiness probe, and scale-to-zero to limit cost and surface area.

## GitHub token

Use a GitHub App or fine-grained token with the minimum organisation billing permission required to read the AI-credit endpoint. Do not place a token in source control.

## Retention

Define a retention period for event telemetry. Billing records generally need longer retention than raw hook events. In production, separate operational telemetry from financial records so retention can be managed independently.
