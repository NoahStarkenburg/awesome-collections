"""SQLite storage layer for personal-timeline-mcp.

Schema only — the insert / dedupe / range query / FTS API is added in a sibling commit.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    ts           INTEGER NOT NULL,
    end_ts       INTEGER,
    title        TEXT,
    body         TEXT,
    payload_json TEXT NOT NULL,
    indexed_at   INTEGER NOT NULL,
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_source_ts ON events(source, ts);

CREATE TABLE IF NOT EXISTS source_state (
    source         TEXT PRIMARY KEY,
    last_indexed_at INTEGER NOT NULL,
    last_event_ts   INTEGER,
    cursor_json     TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    title,
    body,
    content='events',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, body)
        VALUES('delete', old.id, old.title, old.body);
END;

CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, body)
        VALUES('delete', old.id, old.title, old.body);
    INSERT INTO events_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create or open the database and ensure schema is present."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
