# Reconciliation

The service uses two GitHub billing surfaces:

1. Organization AI-credit usage: authoritative Copilot credit quantity by day/model/product/user filters.
2. Organization billing usage summary: repository-filterable usage summary used when GitHub returns Copilot credit rows at repository scope.

The repo summary is treated as exact when a returned usage item is clearly a credit record. Otherwise, the organization AI-credit quantity remains authoritative and is allocated using observed hook telemetry.

Allocation confidence:

- `high`: GitHub returned a repository-scoped credit usage row.
- `medium`: one repository observed in the relevant billing window.
- `low`: multiple repositories observed and credits had to be distributed using event share.

Never label the fallback allocation as a GitHub-billed repository amount. It is an internal attribution.
