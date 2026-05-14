"""SQLite storage layer for personal-timeline-mcp.

Schema + minimal API:
    upsert_event, events_in_range, search_events,
    get_source_state, update_source_state, count_events.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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


@dataclass
class Event:
    """Source-agnostic event row. `source_id` must be stable within `source`."""
    source: str
    source_id: str
    ts: int
    title: str = ""
    body: str = ""
    payload: dict[str, Any] | None = None
    end_ts: int | None = None


def upsert_event(conn: sqlite3.Connection, event: Event) -> int:
    """Insert or update an event by (source, source_id). Returns the row id."""
    now = int(time.time())
    cur = conn.execute(
        """
        INSERT INTO events (source, source_id, ts, end_ts, title, body, payload_json, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            ts = excluded.ts,
            end_ts = excluded.end_ts,
            title = excluded.title,
            body = excluded.body,
            payload_json = excluded.payload_json,
            indexed_at = excluded.indexed_at
        RETURNING id
        """,
        (
            event.source,
            event.source_id,
            int(event.ts),
            None if event.end_ts is None else int(event.end_ts),
            event.title,
            event.body,
            json.dumps(event.payload or {}),
            now,
        ),
    )
    row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def upsert_many(conn: sqlite3.Connection, events: Iterable[Event]) -> int:
    """Bulk upsert. Returns the count of rows touched."""
    count = 0
    for ev in events:
        upsert_event(conn, ev)
        count += 1
    return count


def events_in_range(
    conn: sqlite3.Connection,
    *,
    start_ts: int,
    end_ts: int,
    sources: list[str] | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    """Return events with `start_ts <= ts <= end_ts`. Optionally filter by source(s)."""
    sql = "SELECT * FROM events WHERE ts BETWEEN ? AND ? "
    params: list[Any] = [int(start_ts), int(end_ts)]
    if sources:
        placeholders = ",".join("?" for _ in sources)
        sql += f"AND source IN ({placeholders}) "
        params.extend(sources)
    sql += "ORDER BY ts ASC LIMIT ?"
    params.append(int(limit))
    return list(conn.execute(sql, params))


def search_events(
    conn: sqlite3.Connection,
    query: str,
    *,
    max_results: int = 20,
) -> list[sqlite3.Row]:
    """FTS5 search over title + body. Returns rows ordered by BM25."""
    if not query.strip():
        return []
    return list(conn.execute(
        """
        SELECT e.*, bm25(events_fts) AS score
        FROM events_fts
        JOIN events e ON e.id = events_fts.rowid
        WHERE events_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (query, int(max_results)),
    ))


def count_events(conn: sqlite3.Connection, source: str | None = None) -> int:
    if source is None:
        return int(conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"])
    return int(conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE source = ?", (source,)
    ).fetchone()["c"])


def get_source_state(conn: sqlite3.Connection, source: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM source_state WHERE source = ?", (source,)
    ).fetchone()
    if row is None:
        return None
    cursor = row["cursor_json"]
    return {
        "source": row["source"],
        "last_indexed_at": int(row["last_indexed_at"]),
        "last_event_ts": None if row["last_event_ts"] is None else int(row["last_event_ts"]),
        "cursor": json.loads(cursor) if cursor else None,
    }


def update_source_state(
    conn: sqlite3.Connection,
    source: str,
    *,
    last_event_ts: int | None = None,
    cursor: Any = None,
) -> None:
    """Record that a source has been (re)indexed up to the given watermark."""
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO source_state (source, last_indexed_at, last_event_ts, cursor_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_indexed_at = excluded.last_indexed_at,
            last_event_ts = COALESCE(excluded.last_event_ts, source_state.last_event_ts),
            cursor_json = COALESCE(excluded.cursor_json, source_state.cursor_json)
        """,
        (source, now, last_event_ts, json.dumps(cursor) if cursor is not None else None),
    )
    conn.commit()
