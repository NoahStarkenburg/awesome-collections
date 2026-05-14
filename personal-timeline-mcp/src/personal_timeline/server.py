"""FastMCP server entry point for personal-timeline-mcp.

Run during development with:
    fastmcp dev src/personal_timeline/server.py

Run for MCP clients (Claude Desktop, Cursor, etc.) via stdio:
    python -m personal_timeline.server

The server keeps one SQLite connection alive for the process lifetime. The DB
path defaults to `~/.personal-timeline/index.db` and can be overridden with
the `PERSONAL_TIMELINE_DB` env var.
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from pathlib import Path

from fastmcp import FastMCP

from . import __version__, config, store

mcp = FastMCP(
    name="personal-timeline",
    instructions=(
        "Local activity timeline aggregator (browser history, git commits, "
        "filesystem mtimes, calendar). v0.0.1 — only `ping` is wired up so far. "
        "Real tools (index_sources, timeline_around, summarize_workday, etc.) "
        "land in subsequent commits."
    ),
)


def _db_path() -> Path:
    override = os.environ.get("PERSONAL_TIMELINE_DB")
    if override:
        return Path(override)
    return config.load().db_path


_conn_lock = threading.Lock()
_conn = None


def _get_conn():
    global _conn
    with _conn_lock:
        if _conn is None:
            _conn = store.init_db(_db_path())
        return _conn


@mcp.tool()
def ping() -> dict:
    """Health check. Returns server version, Python version, and current time.

    Use this first when wiring up a new client to confirm the server is reachable.
    """
    return {
        "server": "personal-timeline-mcp",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "ok",
    }


@mcp.tool()
def list_sources() -> dict:
    """Report which sources are configured, what's indexed, and last-indexed
    timestamp per source.

    Useful as a first call after `ping` to see what the server can actually
    answer questions about.
    """
    cfg = config.load()
    conn = _get_conn()
    sources_out = []
    for name, sc in cfg.sources.items():
        entry = {
            "source": name,
            "enabled": sc.enabled,
            "options": sc.options,
            "event_count": store.count_events(conn, name),
            "state": None,
        }
        # state is keyed by source-instance (e.g. "git:<absolute path>"). Surface
        # whatever state rows exist that prefix-match this source name.
        states = [
            row
            for row in conn.execute(
                "SELECT * FROM source_state WHERE source LIKE ? ORDER BY last_indexed_at DESC",
                (f"{name}%",),
            )
        ]
        if states:
            entry["state"] = [
                {
                    "key": row["source"],
                    "last_indexed_at": int(row["last_indexed_at"]),
                    "last_event_ts": None if row["last_event_ts"] is None else int(row["last_event_ts"]),
                }
                for row in states
            ]
        sources_out.append(entry)
    return {
        "db_path": str(_db_path()),
        "config_source": str(cfg.source) if cfg.source else None,
        "total_events": store.count_events(conn),
        "sources": sources_out,
    }


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
