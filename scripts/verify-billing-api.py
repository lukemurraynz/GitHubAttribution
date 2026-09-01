#!/usr/bin/env python3
"""Verify that the GitHub billing API endpoints used by the cost-attribution
tool are reachable and that the provided token has sufficient permissions.

Reads configuration from environment variables (never echoes the token).

Usage:
    GITHUB_TOKEN=ghp_... GITHUB_ORG=my-org python scripts/verify-billing-api.py

Environment variables:
    GITHUB_TOKEN       (required) GitHub PAT or fine-grained token.
    GITHUB_ORG         (required) GitHub organization login name.
    GITHUB_API_URL     Base API URL.           Default: https://api.github.com
    GITHUB_API_VERSION API version header.     Default: 2026-03-10
    YEAR               Billing query year.     Default: yesterday (UTC)
    MONTH              Billing query month.    Default: yesterday (UTC)
    DAY                Billing query day.      Default: yesterday (UTC)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

# Make stdout safe for non-ASCII banner characters (box-drawing) on Windows
# consoles that default to the cp1252 codec. Not all encoding attrs exist on
# every stream; guard so redirection (bytes) still works.
_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure is not None:
    try:
        _reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# ── constants ────────────────────────────────────────────────────────────────

_TIMEOUT_S = 30
_USER_AGENT = "verify-billing-api/1.0 (github-copilot-cost-attribution)"

_ENV_NAMES = [
    "GITHUB_TOKEN",
    "GITHUB_ORG",
    "GITHUB_API_URL",
    "GITHUB_API_VERSION",
    "YEAR",
    "MONTH",
    "DAY",
]

# ── helpers ──────────────────────────────────────────────────────────────────


def _yesterday_utc() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)


def _diagnose(status: int) -> str:
    """Return a human-oriented diagnosis for common HTTP error codes."""
    if status == 401:
        return (
            "401 Unauthorized – token is invalid, expired, or revoked.\n"
            "  For classic PATs ensure the 'admin:org' scope is granted.\n"
            "  For fine-grained tokens ensure Organization 'Administration: read' permission."
        )
    if status == 403:
        return (
            "403 Forbidden – insufficient permission.\n"
            "  The AI-credit / usage-summary billing endpoints require Organization\n"
            "  'Administration read' (fine-grained) or 'admin:org' (classic PAT).\n"
            "  NOTE: Billing Manager role alone is NOT sufficient via the REST API.\n"
            "  Use an org owner/admin token, or add 'manage_billing:copilot' to a\n"
            "  classic PAT that already has 'admin:org'."
        )
    if status == 404:
        return (
            "404 Not Found – the organization was not found, or this billing\n"
            "  endpoint is not available for your account type / plan tier."
        )
    if status == 429:
        return "429 Rate Limited – back off and retry later."
    if 500 <= status < 600:
        return f"{status} Server Error – transient failure on GitHub's side; retry in a moment."
    return f"{status} – unexpected HTTP status."


def _summarise_body(body: bytes) -> str:
    """Parse the response and return a concise, safe summary string."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        preview = body[:200].decode("utf-8", errors="replace")
        return f"  (non-JSON response, first 200 chars): {preview}"

    lines: list[str] = []

    if isinstance(data, dict):
        lines.append(f"  top-level keys: {sorted(data.keys())}")
        items = data.get("usageItems") or data.get("usage_items")
        if isinstance(items, list):
            lines.append(f"  usageItems count: {len(items)}")
            if items:
                first = items[0]
                if isinstance(first, dict):
                    lines.append(f"  example usageItem keys: {sorted(first.keys())}")
            total_qty = sum(
                float(i.get("netQuantity") or i.get("net_quantity") or 0)
                for i in items
                if isinstance(i, dict)
            )
            lines.append(f"  netQuantity total: {total_qty}")
    elif isinstance(data, list):
        lines.append(f"  response is a JSON array with {len(data)} element(s)")
        if data and isinstance(data[0], dict):
            lines.append(f"  first element keys: {sorted(data[0].keys())}")
    else:
        lines.append(f"  response is a JSON scalar: {type(data).__name__}")

    return "\n".join(lines) if lines else "  (empty or unrecognised structure)"


def _call(url: str, token: str, api_version: str) -> tuple[bool, str]:
    """Perform a single GET and return (success, human_message)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": api_version,
        "User-Agent": _USER_AGENT,
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        msg = _diagnose(status)
        return False, f"HTTP {status}\n{msg}"
    except urllib.error.URLError as exc:
        return False, f"Connection error: {exc.reason}"
    except OSError as exc:
        return False, f"Network error: {exc}"

    summary = _summarise_body(body)
    return True, f"HTTP {status} OK\n{summary}"


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify GitHub billing API endpoints used by the Copilot "
            "cost-attribution tool.  Reads configuration from environment "
            "variables listed below."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # No positional/flag args — everything comes from env vars.
    parser.parse_args()

    # ── read config ──────────────────────────────────────────────────────
    token = os.environ.get("GITHUB_TOKEN", "")
    org = os.environ.get("GITHUB_ORG", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    api_version = os.environ.get("GITHUB_API_VERSION", "2026-03-10")

    yesterday = _yesterday_utc()
    year = os.environ.get("YEAR", str(yesterday.year))
    month = os.environ.get("MONTH", str(yesterday.month))
    day = os.environ.get("DAY", str(yesterday.day))

    # ── echo config (names only, never the token value) ──────────────────
    print("=" * 64)
    print("verify-billing-api  —  GitHub Copilot cost-attribution checker")
    print("=" * 64)
    env_display = {
        "GITHUB_TOKEN": "(set, value hidden)" if token else "(NOT SET)",
        "GITHUB_ORG": org or "(NOT SET)",
        "GITHUB_API_URL": api_url,
        "GITHUB_API_VERSION": api_version,
        "YEAR": year,
        "MONTH": month,
        "DAY": day,
    }
    for name in _ENV_NAMES:
        print(f"  {name:24s} = {env_display[name]}")
    print()

    # ── validate required vars ───────────────────────────────────────────
    if not token:
        print("ERROR: GITHUB_TOKEN is required but not set.", file=sys.stderr)
        print("  Export a PAT with admin:org (classic) or Organization", file=sys.stderr)
        print("  Administration:read (fine-grained) and re-run.", file=sys.stderr)
        return 1
    if not org:
        print("ERROR: GITHUB_ORG is required but not set.", file=sys.stderr)
        return 1

    # ── define the two endpoints ─────────────────────────────────────────
    endpoints: list[tuple[str, str]] = [
        (
            "AI-credit usage",
            f"{api_url}/organizations/{org}/settings/billing/ai_credit/usage"
            f"?year={year}&month={month}&day={day}",
        ),
        (
            "Usage summary",
            f"{api_url}/organizations/{org}/settings/billing/usage/summary"
            f"?year={year}&month={month}&day={day}&product=Copilot",
        ),
    ]

    # ── run checks ───────────────────────────────────────────────────────
    passed = 0
    total = len(endpoints)

    for label, url in endpoints:
        print(f"── {label} ──")
        # show URL with org visible but never the token
        print(f"  GET {url}")
        ok, msg = _call(url, token, api_version)
        status_tag = "PASS" if ok else "FAIL"
        print(f"  [{status_tag}] {msg}")
        print()
        if ok:
            passed += 1

    # ── summary ──────────────────────────────────────────────────────────
    if passed == total:
        print(f"VERIFY: PASS ({passed}/{total} endpoints)")
        return 0

    print(f"VERIFY: FAIL ({passed}/{total} endpoints)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
