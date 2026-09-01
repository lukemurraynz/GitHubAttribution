from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .github import GitHubClient


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce a billing quantity/amount to float, tolerating None and ''.

    GitHub billing payloads occasionally carry null or empty-string numeric
    fields. Failing cleanly here (skipping the malformed row) is safer than
    letting a raw ValueError abort the entire reconcile mid-loop.
    """
    if value is None or value == '':
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _usage_id(scope: str, org: str, user: str | None, d: date, item: dict[str, Any]) -> str:
    stable = [scope, org, user, d.isoformat(), item.get('model'), item.get('product'), item.get('sku'), item.get('quantity'), item.get('netQuantity'), item.get('grossQuantity')]
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def import_ai_credit_day(con: sqlite3.Connection, gh: GitHubClient, org: str, d: date, user: str | None = None) -> int:
    payload = gh.ai_credit_usage(org, d.year, d.month, d.day, user=user)
    count = 0
    for item in payload.get('usageItems') or []:
        if not isinstance(item, dict):
            continue
        if str(item.get('unitType', '')).lower() != 'credits':
            continue
        quantity = _as_float(item.get('netQuantity', item.get('grossQuantity', 0)))
        if quantity <= 0:
            # Nothing billable for this row; do not fabricate a zero-cost record.
            continue
        usage_id = _usage_id('ai_credit', org, user, d, item)
        con.execute(
            """INSERT OR IGNORE INTO billing_usage
            (usage_id,scope,organisation,user_name,usage_date,model,product,sku,unit_type,quantity,price_per_unit,
             gross_amount,discount_quantity,discount_amount,net_amount,source_endpoint,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                usage_id, 'ai_credit', org, user, d.isoformat(), item.get('model'), item.get('product'), item.get('sku'),
                item.get('unitType'), quantity, _as_float(item.get('pricePerUnit')), _as_float(item.get('grossAmount')),
                _as_float(item.get('discountQuantity')), _as_float(item.get('discountAmount')), _as_float(item.get('netAmount')),
                '/organizations/{org}/settings/billing/ai_credit/usage', json.dumps(item, separators=(',', ':')),
            ),
        )
        count += 1
    con.commit()
    return count


def import_repo_usage_summary(con: sqlite3.Connection, gh: GitHubClient, org: str, d: date, repository: str) -> int:
    """Import repo billing summary for contextual reporting only.

    This is deliberately not used as authoritative Copilot AI-credit allocation because GitHub's
    public summary endpoint is a general billing summary and is documented as preview.
    """
    payload = gh.usage_summary(org, d.year, d.month, d.day, repository=repository, product='Copilot')
    imported = 0
    for item in payload.get('usageItems') or []:
        if not isinstance(item, dict):
            continue
        usage_id = _usage_id('usage_summary_repo', org, repository, d, item)
        con.execute(
            """INSERT OR IGNORE INTO billing_usage
            (usage_id,scope,organisation,user_name,usage_date,model,product,sku,unit_type,quantity,price_per_unit,
             gross_amount,discount_quantity,discount_amount,net_amount,source_endpoint,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                usage_id, 'usage_summary_repo', org, None, d.isoformat(), item.get('model'), item.get('product'), item.get('sku'),
                item.get('unitType'), _as_float(item.get('netQuantity', item.get('grossQuantity', 0))), _as_float(item.get('pricePerUnit')),
                _as_float(item.get('grossAmount')), _as_float(item.get('discountQuantity')), _as_float(item.get('discountAmount')), _as_float(item.get('netAmount')),
                '/organizations/{org}/settings/billing/usage/summary', json.dumps(item, separators=(',', ':')),
            ),
        )
        imported += 1
    con.commit()
    return imported


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _scores_by_repo(con: sqlite3.Connection, d: str, user: str | None) -> dict[str, float]:
    rows = con.execute(
        "SELECT event, observed_at, repository, session_id FROM events WHERE substr(observed_at,1,10)=? AND repository IS NOT NULL AND (? IS NULL OR user_name=?) ORDER BY observed_at",
        (d, user, user),
    ).fetchall()
    if not rows:
        return {}
    prompt_weight = float(os.getenv('COPILOT_COST_PROMPT_WEIGHT', '0.25'))
    tool_weight = float(os.getenv('COPILOT_COST_TOOL_WEIGHT', '0.10'))
    scores = defaultdict(float)
    per_session: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        per_session[(row['repository'], row['session_id'] or row['observed_at'])].append(row)
    for (repo, _), events in per_session.items():
        first = _parse_time(events[0]['observed_at'])
        last = _parse_time(events[-1]['observed_at'])
        duration = max(0.0, (last - first).total_seconds())
        prompts = sum(1 for e in events if e['event'] == 'userPromptSubmitted')
        tools = sum(1 for e in events if e['event'] in {'preToolUse', 'postToolUse', 'postToolUseFailure'})
        scores[repo] += duration + prompts * prompt_weight + tools * tool_weight
    return dict(scores)


def allocate_day(con: sqlite3.Connection, d: date) -> dict[str, Any]:
    day = d.isoformat()
    rows = con.execute("SELECT * FROM billing_usage WHERE usage_date=? AND scope='ai_credit'", (day,)).fetchall()
    summary = {'billingRows': len(rows), 'allocationRows': 0, 'allocatedCredits': 0.0}
    for usage in rows:
        scores = _scores_by_repo(con, day, usage['user_name'])
        if not scores:
            continue
        total_score = sum(scores.values())
        con.execute('DELETE FROM allocations WHERE usage_id=?', (usage['usage_id'],))
        for repo, score in sorted(scores.items()):
            allocated = float(usage['quantity']) * (score / total_score)
            method = 'observed-session-activity'
            confidence = 'high' if len(scores) == 1 else 'medium'
            if usage['user_name'] is None:
                confidence = 'low'
                method = 'organisation-total-observed-user-and-repo-share'
            allocation_id = hashlib.sha256(f"{usage['usage_id']}|{repo}".encode()).hexdigest()
            con.execute(
                """INSERT INTO allocations
                (allocation_id,usage_id,repository,user_name,usage_date,model,allocated_credits,allocated_usd,allocation_method,confidence,activity_score)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    allocation_id, usage['usage_id'], repo, usage['user_name'], day, usage['model'], allocated,
                    allocated * (usage['price_per_unit'] or 0.01), method, confidence, score,
                ),
            )
            summary['allocationRows'] += 1
            summary['allocatedCredits'] += allocated
    con.commit()
    return summary


def load_projects(con: sqlite3.Connection, path: str) -> int:
    with open(path, encoding='utf-8') as handle:
        mapping = json.load(handle)
    count = 0
    for repo, metadata in mapping.items():
        if isinstance(metadata, str):
            project, cost_center = metadata, None
        else:
            project, cost_center = metadata.get('project', 'Unmapped'), metadata.get('costCenter')
        con.execute(
            "INSERT INTO repository_projects(repository,project,cost_center) VALUES(?,?,?) "
            "ON CONFLICT(repository) DO UPDATE SET project=excluded.project,cost_center=excluded.cost_center,active=1",
            (repo, project, cost_center),
        )
        count += 1
    con.commit()
    return count


def reconcile_range(con: sqlite3.Connection, gh: GitHubClient, org: str, start: date, end: date, project_map: str | None = None, repo_context: list[str] | None = None, users: list[str] | None = None) -> dict[str, Any]:
    if project_map:
        load_projects(con, project_map)
    current = start
    result: dict[str, Any] = {'days': [], 'from': start.isoformat(), 'to': end.isoformat()}
    while current <= end:
        imported = 0
        for user in users or [None]:
            imported += import_ai_credit_day(con, gh, org, current, user=user)
        context_imported = 0
        for repo in repo_context or []:
            context_imported += import_repo_usage_summary(con, gh, org, current, repo)
        allocated = allocate_day(con, current)
        result['days'].append({'date': current.isoformat(), 'aiCreditRows': imported, 'repoContextRows': context_imported, **allocated})
        current += timedelta(days=1)
    return result
