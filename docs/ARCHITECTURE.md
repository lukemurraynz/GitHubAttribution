# Architecture

```text
Developer / Copilot CLI
        |
        | hook events
        v
+----------------------+       +---------------------------+
| Repository hooks     | ----> | Central collector        |
| session / prompt /   |       | authenticated HTTP        |
| tool / error events  |       +------------+--------------+
+----------------------+                    |
                                           v
                                  +-------------------+
                                  | Durable event DB  |
                                  +-------------------+
                                           ^
                                           |
                         +-----------------+------------------+
                         | GitHub billing reconciliation   |
                         | organisation AI-credit report  |
                         +-----------------+------------------+
                                           |
                                           v
                                  +-------------------+
                                  | Attribution engine |
                                  | user + day + repo |
                                  +---------+---------+
                                            |
                                            v
                              +---------------------------+
                              | repo -> project mapping |
                              +-------------+-------------+
                                            |
                                            v
                                  API / BI / FinOps views
```

## Source-of-truth boundary

- **GitHub AI-credit usage endpoint**: authoritative quantity and model-level billing record.
- **Copilot hooks**: contextual telemetry that establishes which repository was active and how much activity occurred.
- **Attribution engine**: an internal accounting calculation that allocates a user/day/model credit total across observed repositories.

The service never calls its inferred repository amount a direct GitHub invoice charge.

## Why session telemetry matters

The organisation AI-credit endpoint can be filtered by date, user, model and product, but its response is not documented as a repository-scoped Copilot AI-credit ledger. That means repository/project allocation requires an additional context signal. Hooks provide that signal at the point where the developer is actually operating on a repository.

## Production deployment

For an enterprise, keep the hook/event contract and replace the bundled SQLite collector with an Azure Container App or Function behind API Management, fronted by Entra ID or workload authentication, with Event Hubs + ADX/Fabric/SQL for durable analytics.
