"""Локальне сховище (SQLite): проекти, історія змін, помилки, запуски, API-запити."""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime

from flask import Flask, current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS projects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    path           TEXT NOT NULL UNIQUE,
    short_desc     TEXT NOT NULL DEFAULT '',
    full_desc      TEXT NOT NULL DEFAULT '',
    usage_notes    TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '',
    run_cmd        TEXT NOT NULL DEFAULT '',
    test_cmd       TEXT NOT NULL DEFAULT '',
    api_base_url   TEXT NOT NULL DEFAULT '',
    prod_mode      TEXT NOT NULL DEFAULT 'git',
    prod_remote    TEXT NOT NULL DEFAULT 'origin',
    prod_branch    TEXT NOT NULL DEFAULT '',
    prod_cmd       TEXT NOT NULL DEFAULT '',
    ingest_key     TEXT NOT NULL,
    favorite       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    last_opened_at TEXT
);

-- Історія змін, зроблених через застосунок (редагування файлів, git-операції, опис...)
CREATE TABLE IF NOT EXISTS changes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    path       TEXT NOT NULL DEFAULT '',
    summary    TEXT NOT NULL DEFAULT '',
    diff       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changes_project ON changes(project_id, id DESC);

-- Падіння та помилки (вручну, з логів або надіслані самим проектом)
CREATE TABLE IF NOT EXISTS incidents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    message      TEXT NOT NULL DEFAULT '',
    traceback    TEXT NOT NULL DEFAULT '',
    level        TEXT NOT NULL DEFAULT 'error',
    source       TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL DEFAULT 'open',
    fingerprint  TEXT NOT NULL DEFAULT '',
    occurrences  INTEGER NOT NULL DEFAULT 1,
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    resolved_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_project ON incidents(project_id, status);

-- Запуски команд: тести, оновлення з проду
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    command    TEXT NOT NULL,
    exit_code  INTEGER,
    timed_out  INTEGER NOT NULL DEFAULT 0,
    output     TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    duration   REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, kind, id DESC);

-- Збережені API-запити проекту
CREATE TABLE IF NOT EXISTS api_requests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    method     TEXT NOT NULL DEFAULT 'GET',
    url        TEXT NOT NULL DEFAULT '',
    headers    TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Поля проекту, які можна змінювати через застосунок.
EDITABLE_PROJECT_FIELDS = (
    "name",
    "short_desc",
    "full_desc",
    "usage_notes",
    "tags",
    "run_cmd",
    "test_cmd",
    "api_base_url",
    "prod_mode",
    "prod_remote",
    "prod_branch",
    "prod_cmd",
    "favorite",
)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app: Flask) -> None:
    conn = connect(app.config["DATABASE"])
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    app.teardown_appcontext(close_db)


# ---------------------------------------------------------------- helpers


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in get_db().execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    return row_to_dict(get_db().execute(sql, params).fetchone())


def execute(sql: str, params: tuple = ()) -> int:
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def get_setting(key: str, default: str = "") -> str:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def new_ingest_key() -> str:
    return secrets.token_urlsafe(18)


def add_project(name: str, path: str, short_desc: str = "") -> int:
    ts = now()
    return execute(
        "INSERT INTO projects(name, path, short_desc, ingest_key, created_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (name, path, short_desc, new_ingest_key(), ts, ts),
    )


def record_change(project_id: int, kind: str, path: str = "", summary: str = "", diff: str = "") -> int:
    # Дуже великі диффи обрізаємо, щоб база не розросталась.
    if len(diff) > 500_000:
        diff = diff[:500_000] + "\n… (дифф обрізано)"
    return execute(
        "INSERT INTO changes(project_id, kind, path, summary, diff, created_at) VALUES(?, ?, ?, ?, ?, ?)",
        (project_id, kind, path, summary, diff, now()),
    )


def record_run(project_id: int, kind: str, command: str, result: dict) -> dict:
    run_id = execute(
        "INSERT INTO runs(project_id, kind, command, exit_code, timed_out, output, started_at, duration) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            kind,
            command,
            result.get("exit_code"),
            1 if result.get("timed_out") else 0,
            result.get("output", ""),
            result.get("started_at") or now(),
            result.get("duration", 0),
        ),
    )
    return query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
