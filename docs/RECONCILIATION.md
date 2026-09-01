# Reconciliation

## Daily process

1. Import the organisation's Copilot AI-credit report for the UTC day.
2. Preserve each billing row by model/product/quantity and the GitHub source endpoint.
3. Query hook events for the same UTC day.
4. Group events by user and repository.
5. Score observed activity:
   - session duration seconds
   - prompt count × `COPILOT_COST_PROMPT_WEIGHT`
   - tool events × `COPILOT_COST_TOOL_WEIGHT`
6. Allocate each billing row proportionally to those scores.
7. Preserve the exact imported credit total across allocations.
8. Surface allocation method and confidence in reports.

## Reconciliation invariant

For a given billing row:

```text
sum(repository allocations) == imported GitHub AI-credit quantity
```

A variance should only occur when there are no observable repository events, in which case the service leaves the amount unallocated instead of inventing a repository.

## Confidence

- `high`: a billing row maps to exactly one observed repository.
- `medium`: multiple repositories are observed for the identified user/day.
- `low`: the billing row is organisation-level and user/repository activity has to be inferred.

## Repository mapping

`config/repo-projects.json` is intentionally external to billing data. This lets teams change project/cost-centre ownership without rewriting the billing ledger.
