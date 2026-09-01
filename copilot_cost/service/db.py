from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL,
  event TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  session_id TEXT,
  user_name TEXT,
  repository TEXT,
  branch TEXT,
  commit_sha TEXT,
  tool_name TEXT,
  prompt_chars INTEGER,
  prompt_sha256 TEXT,
  tool_result_chars INTEGER,
  raw_json TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_events_user_time ON events(user_name, observed_at);
CREATE INDEX IF NOT EXISTS ix_events_repo_time ON events(repository, observed_at);
CREATE INDEX IF NOT EXISTS ix_events_session ON events(session_id);

CREATE TABLE IF NOT EXISTS billing_usage (
  usage_id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  organisation TEXT NOT NULL,
  user_name TEXT,
  usage_date TEXT NOT NULL,
  model TEXT,
  product TEXT,
  sku TEXT,
  unit_type TEXT,
  quantity REAL NOT NULL,
  price_per_unit REAL,
  gross_amount REAL,
  discount_quantity REAL,
  discount_amount REAL,
  net_amount REAL,
  source_endpoint TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  imported_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(scope, organisation, user_name, usage_date, model, product, sku, quantity, source_endpoint)
);
CREATE INDEX IF NOT EXISTS ix_billing_user_date ON billing_usage(user_name, usage_date);

CREATE TABLE IF NOT EXISTS repository_projects (
  repository TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  cost_center TEXT,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS allocations (
  allocation_id TEXT PRIMARY KEY,
  usage_id TEXT NOT NULL,
  repository TEXT NOT NULL,
  user_name TEXT,
  usage_date TEXT NOT NULL,
  model TEXT,
  allocated_credits REAL NOT NULL,
  allocated_usd REAL NOT NULL,
  allocation_method TEXT NOT NULL,
  confidence TEXT NOT NULL,
  activity_score REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(usage_id, repository)
);
CREATE INDEX IF NOT EXISTS ix_alloc_repo_date ON allocations(repository, usage_date);
CREATE INDEX IF NOT EXISTS ix_alloc_user_date ON allocations(user_name, usage_date);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    db_path = path or os.getenv('COPILOT_COST_DB', './data/copilot-cost.sqlite3')
    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript(SCHEMA)
    return con


def ingest_event(con: sqlite3.Connection, record: dict[str, Any]) -> bool:
    cur = con.execute(
        """INSERT OR IGNORE INTO events
        (event_id,schema_version,event,observed_at,session_id,user_name,repository,branch,commit_sha,
         tool_name,prompt_chars,prompt_sha256,tool_result_chars,raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record.get('eventId'), record.get('schemaVersion', 1), record.get('event'), record.get('observedAt'),
            record.get('sessionId'), record.get('user'), record.get('repository'), record.get('branch'),
            record.get('commit'), record.get('toolName'), record.get('promptChars'), record.get('promptSha256'),
            record.get('toolResultChars'), json.dumps(record, separators=(',', ':')),
        ),
    )
    con.commit()
    return cur.rowcount == 1


def upsert_project(con: sqlite3.Connection, repository: str, project: str, cost_center: str | None) -> None:
    con.execute(
        "INSERT INTO repository_projects(repository,project,cost_center) VALUES(?,?,?) "
        "ON CONFLICT(repository) DO UPDATE SET project=excluded.project,cost_center=excluded.cost_center,active=1",
        (repository, project, cost_center),
    )
    con.commit()
