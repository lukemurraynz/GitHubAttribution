# Real-org / Enterprise setup and permissions

This guide is the operational runbook for deploying the GitHub Copilot Cost
Attribution Platform against a **real GitHub organization or enterprise** and
actually importing billing data. It is the practical companion to `README.md`
and `ARCHITECTURE.md`, and it records the permission/plan prerequisites that
must exist *before* the tool can attribute any real spend.

> Status note: every API path, response field, token scope, and permission
> below was verified live against a real GitHub org on 2026-09-01, in addition
> to the official documentation. The one thing that cannot be verified without
> a **paid Copilot plan** is the presence of `usageItems` data itself — steps
> 1–2 make that data exist.

---

## 1. Does the org have a Copilot plan? (the hard prerequisite)

The `ai_credit/usage` and `usage/summary` endpoints return **200 with zero
`usageItems`** (not an error) when the org has no Copilot subscription. A 200
with empty data means **the endpoints work but the org has nothing billed** —
seat assignment is impossible until a plan exists.

You cannot fix this from the tool. An org owner must have a **paid GitHub
Copilot plan** (Business or Enterprise) for the org, with **seat management
enabled**. If Copilot usage is instead tied to a personal/Pro license or a
different org, no amount of configuration on this org will produce data.

**Check state** (run as an org owner/admin token):

```bash
# Seat count and plan state
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  https://api.github.com/orgs/ORG/copilot/billing
#   look for: seat_management_setting and seats_breakdown.total

# Actual AI-credit usage for a day
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "https://api.github.com/organizations/ORG/settings/billing/ai_credit/usage?year=2026&month=8&day=31"
```

Expected healthy output: `seat_management_setting` is not `unconfigured`, and
`usageItems` is non-empty on days Copilot was used.

---

## 2. Plan + seat setup (GitHub UI — owned by the org admin)

These steps are **financial and org-level**. They should be performed by the
org **Owner** in the GitHub UI, not by an automation identity.

1. **Purchase/activate Copilot** for the org:
   GitHub → `ORG` → **Settings → Copilot** → **Copilot Business** (per-seat,
   monthly) or **Copilot Enterprise**. This is the step that makes Copilot
   billing data exist.
2. **Configure seat management**:
   In the same Copilot settings, set seating to **"Assign seats to selected
   members and teams"** (required for API-driven seat assignment; the default
   "auto-assign to all members" is fine only if you want every member covered).
3. **Assign seats**:
   Add the member(s) whose Copilot usage you want to attribute (e.g. a project
   team lead) as assigned seats.
4. **Confirm data flows**:
   Have the assigned user actually use Copilot for a day, then re-run the
   `ai_credit/usage` check — it should now return non-zero `usageItems`.

---

## 3. Create the reconciliation token

The token that runs the `reconcile` command (and the CI workflow) must be for
an identity that is an **Owner** of the org and holds the **Organization
"Read only"** billing/administration permission. Two accepted options:

### Option A — fine-grained personal access token (recommended)
1. GitHub → **Settings → Developer settings → Fine-grained PATs → Generate**.
2. **Repository access**: No repositories required (billing is org-scoped).
3. **Organization permissions** (set **Resource owner** to the org):
   - **Metered usage → Read** (delivers the AI-credit rows)
   - **Administration → Read** (required for the billing endpoints)
4. Generate and store the token in your secret manager, **not** in the repo.

### Option B — classic PAT
Grant **`admin:org`** scope (and optionally `manage_billing:copilot`).
Reserve classic tokens for this narrow use; fine-grained is preferred.

> **Critical gotcha (verified live):** a token whose user is only a
> **Member** or **Billing Manager** gets **HTTP 403** on these endpoints even
> though it can see billing in the UI. Billing Manager is **not** sufficient
> via the REST API. The token must be for an **Owner** with the permissions
> above.

---

## 4. Configure the collector and hooks

### 4a. Collector environment
Copy `.env.example` → `.env` and set at minimum:

```ini
COPILOT_COST_INGEST_KEY=<long-random-secret>   # protect the ingest endpoint
COPILOT_COST_DB=/app/data/copilot-cost.sqlite3
```

Run it:

```bash
docker compose up -d collector          # or
python3 -m copilot_cost.service.server
```

### 4b. Copy the hooks into the consuming repos
Copilot CLI and the Copilot cloud agent auto-load `.github/hooks/*.json` from
the **default branch** of each repo. For **every repo** whose activity you
want to attribute:

1. Copy `.github/hooks/copilot-cost-attribution.json` and
   `.github/hooks/scripts/` from this project into the target repo.
2. Commit them to the **default branch** (required for cloud agents).
3. Set in the developer environment / repo environment:
   ```text
   COPILOT_COST_TELEMETRY_ENDPOINT=http://<collector-host>:8080/v1/copilot/events
   COPILOT_COST_INGEST_KEY=<same shared secret as the collector>
   ```
4. Verify: run one Copilot session in that repo, then check
   `GET /v1/report/repositories?from=...&to=...` — you should see the repo
   from hook events even before billing data arrives.

---

## 5. Point the reconciler at the org

Populate config and run the sync:

```bash
# config/users.txt — one GitHub login per line whose Copilot usage you import
# config/repo-projects.json — map owner/repo -> project + cost centre

export GITHUB_TOKEN=<reconciliation token from step 3>
python3 -m copilot_cost.cli.main reconcile \
  --org ORG \
  --from 2026-09-01 --to 2026-09-01 \
  --project-map config/repo-projects.json \
  --user-file config/users.txt
```

Expected output (with real data present):
```json
{ "days": [ { "date": "...", "aiCreditRows": 1, "...": "...",
              "billingRows": 1, "allocationRows": 1, "allocatedCredits": <qty> } ] }
```

**What "working" looks like:** `imported_credits == allocatedCredits` and
`variance_credits == 0` in `GET /v1/reconciliation`. A non-zero variance
means hook activity was missing for some billed user/day (the tool correctly
leaves the amount unallocated rather than inventing a repo).

---

## 6. Automate daily reconciliation

The bundled `.github/workflows/reconcile.yml` runs daily. Before trusting it:

1. Set the **`COPILOT_BILLING_TOKEN`** secret to the token from step 3.
2. Confirm the workflow's org (`GITHUB_REPOSITORY_OWNER` or a pinned org) is
   the one with the Copilot plan.
3. Confirm the token's user is an **Owner** of that org with the billing
   permissions (a step-3 token is required; a Billing Manager token fails
   with 403).

---

## 7. Verification checklist for a real setup

Use `scripts/verify-billing-api.py` first — it tests both endpoints with your
token and prints PASS/FAIL with an exact permission diagnosis:

```bash
GITHUB_TOKEN=<token> GITHUB_ORG=ORG python scripts/verify-billing-api.py
# VERIFY: PASS (2/2 endpoints)  ->  auth + contract good, org has data access
# VERIFY: FAIL ... 403 ...      ->  token identity lacks Owner + billing perms
```

Then run the live contract tests:

```bash
GITHUB_TOKEN=<token> GITHUB_ORG=ORG \
  python3 -m unittest tests.test_live_github_contract -v
```

| Check | Passes when |
|---|---|
| `verify-billing-api.py` | both endpoints return 200 |
| live contract tests | 4/4 tests pass against the real endpoint |
| `GET /v1/reconciliation` | `variance_credits == 0` for reconciled days |
| `GET /v1/report/projects` | projects/cost centres populated from mapping |

---

## 8. Enterprise accounts

For a **GitHub Enterprise Cloud** account that manages Copilot centrally:

- The org-level endpoints above still work **per org** that has the Copilot
  plan.
- The **enterprise-level** AI-credit endpoint is
  `GET /enterprises/{slug}/settings/billing/ai_credit/usage` (documented under
  the Enterprise Cloud API version). Point the tool's `--org` at each
  org, or extend `GitHubClient.ai_credit_usage` to the enterprise scope if you
  want a single enterprise total. Confirm your token is an **enterprise
  owner/admin** for that endpoint.
- Seat management for enterprise-managed Copilot is governed at the enterprise
  level; verify per-org data separately.

---

## Security notes for a real deployment

- **Rotate any tokens/secrets that have ever been shared in a log or chat**,
  including fine-grained PATs, classic PATs, and GitHub App client secrets.
- Keep the GitHub App private key (`.pem`) out of the repo and off shared
  machines; consider a secret manager.
- The bundled collector is a reference implementation (Bearer secret, no TLS/
  rate limiting). For production, front it with an authenticated reverse proxy
  (or move to a durable store per `ARCHITECTURE.md`), and enable retention
  trimming on the SQLite `events` table per `SECURITY.md`.
- The ingest endpoint is unauthenticated-by-default if
  `COPILOT_COST_INGEST_KEY` is unset — always set it.
