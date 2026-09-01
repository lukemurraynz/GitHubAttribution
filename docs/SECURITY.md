# Security and privacy

## Hook telemetry

The hook package intentionally does not transmit prompt or tool-result content. It records counts/lengths and, by default, a SHA-256 digest for submitted prompts. Disable prompt hashing with `COPILOT_COST_HASH_PROMPTS=false`.

Hostnames are hashed before transmission.

## Collector

Set `COPILOT_COST_INGEST_KEY` and require an `Authorization: Bearer ...` header. The included server is a reference implementation, not an internet-facing hardened service. Put TLS, authentication, rate limiting and network restrictions in front of it for production.

## GitHub token

Use a GitHub App or fine-grained token with the minimum organisation billing permission required to read the AI-credit endpoint. Do not place a token in source control.

## Retention

Define a retention period for event telemetry. Billing records generally need longer retention than raw hook events. In production, separate operational telemetry from financial records so retention can be managed independently.
