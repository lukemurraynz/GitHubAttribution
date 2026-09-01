from __future__ import annotations
import sqlite3
from typing import Any


def _filters(start: str | None, end: str | None, extra: list[tuple[str, Any]]) -> tuple[str, list[Any]]:
    where = []
    params: list[Any] = []
    if start:
        where.append('a.usage_date >= ?'); params.append(start)
    if end:
        where.append('a.usage_date <= ?'); params.append(end)
    for clause, value in extra:
        if value:
            where.append(clause); params.append(value)
    return (' WHERE ' + ' AND '.join(where)) if where else '', params


def report_repositories(con: sqlite3.Connection, start: str | None, end: str | None, repo: str | None, user: str | None, project: str | None) -> list[dict[str, Any]]:
    where, params = _filters(start, end, [
        ('a.repository = ?', repo), ('a.user_name = ?', user), ('COALESCE(p.project, \'Unmapped\') = ?', project)
    ])
    rows = con.execute(
        f"""SELECT a.usage_date, a.repository, COALESCE(p.project,'Unmapped') project,
           COALESCE(p.cost_center,'Unmapped') cost_center, a.user_name,
           SUM(a.allocated_credits) credits, SUM(a.allocated_usd) usd,
           GROUP_CONCAT(DISTINCT a.model) models, GROUP_CONCAT(DISTINCT a.confidence) confidence,
           GROUP_CONCAT(DISTINCT a.allocation_method) allocation_methods
           FROM allocations a LEFT JOIN repository_projects p ON p.repository=a.repository{where}
           GROUP BY a.usage_date,a.repository,p.project,p.cost_center,a.user_name
           ORDER BY a.usage_date,a.repository,a.user_name""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def report_projects(con: sqlite3.Connection, start: str | None, end: str | None, project: str | None) -> list[dict[str, Any]]:
    where, params = _filters(start, end, [('COALESCE(p.project, \'Unmapped\') = ?', project)])
    rows = con.execute(
        f"""SELECT a.usage_date, COALESCE(p.project,'Unmapped') project,
           COALESCE(p.cost_center,'Unmapped') cost_center,
           COUNT(DISTINCT a.repository) repositories, COUNT(DISTINCT a.user_name) users,
           SUM(a.allocated_credits) credits, SUM(a.allocated_usd) usd,
           GROUP_CONCAT(DISTINCT a.confidence) confidence
           FROM allocations a LEFT JOIN repository_projects p ON p.repository=a.repository{where}
           GROUP BY a.usage_date,p.project,p.cost_center ORDER BY a.usage_date,p.project""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def report_users(con: sqlite3.Connection, start: str | None, end: str | None, user: str | None, repo: str | None) -> list[dict[str, Any]]:
    where, params = _filters(start, end, [('a.user_name = ?', user), ('a.repository = ?', repo)])
    rows = con.execute(
        f"""SELECT a.usage_date, a.user_name, COUNT(DISTINCT a.repository) repositories,
           SUM(a.allocated_credits) credits, SUM(a.allocated_usd) usd,
           GROUP_CONCAT(DISTINCT a.model) models
           FROM allocations a{where}
           GROUP BY a.usage_date,a.user_name ORDER BY a.usage_date,a.user_name""", params
    ).fetchall()
    return [dict(r) for r in rows]


def reconciliation_report(con: sqlite3.Connection, start: str | None, end: str | None) -> list[dict[str, Any]]:
    where, params = _filters(start, end, [])
    billing_where = []
    billing_params = []
    if start:
        billing_where.append('usage_date >= ?'); billing_params.append(start)
    if end:
        billing_where.append('usage_date <= ?'); billing_params.append(end)
    clause = ' AND ' + ' AND '.join(billing_where) if billing_where else ''
    billing = con.execute(
        f"""SELECT usage_date, COUNT(*) billing_rows, SUM(quantity) imported_credits, SUM(net_amount) imported_net_amount
        FROM billing_usage WHERE scope='ai_credit'{clause} GROUP BY usage_date ORDER BY usage_date""", billing_params
    ).fetchall()
    rows = []
    for r in billing:
        alloc = con.execute('SELECT COALESCE(SUM(allocated_credits),0) x FROM allocations WHERE usage_date=?', (r['usage_date'],)).fetchone()['x']
        rows.append({**dict(r), 'allocated_credits': alloc, 'variance_credits': float(r['imported_credits'] or 0) - float(alloc or 0)})
    return rows
