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


@mcp.tool()
def index_sources(force_full: bool = False) -> dict:
    """Drive every enabled source through its ingest pipeline.

    Sources covered:
        - `git`        — every repo under `[sources.git].repos`
        - `filesystem` — every dir under `[sources.filesystem].dirs`
        - `chrome` / `firefox` — placeholders for now (need profile_dir from config)
        - `calendar`   — every path under `[sources.calendar].ics_paths`

    Args:
        force_full: if true, clear `source_state` for each enabled source so
            the next pass walks from the beginning.

    Returns: {results: {source: <per-source result>}, total_ingested, errors}.
    """
    cfg = config.load()
    conn = _get_conn()
    results: dict = {}
    errors: list[dict] = []
    total_ingested = 0

    if force_full:
        conn.execute("DELETE FROM source_state")
        conn.commit()

    for name, sc in cfg.sources.items():
        if not sc.enabled:
            continue
        try:
            outcome = _ingest_one(conn, name, sc.options)
        except Exception as exc:  # surface per-source failure, don't kill the run
            errors.append({"source": name, "error": str(exc)})
            continue
        results[name] = outcome
        total_ingested += outcome.get("ingested", 0)

    return {
        "total_ingested": total_ingested,
        "results": results,
        "errors": errors,
        "force_full": bool(force_full),
    }


def _ingest_one(conn, source: str, opts: dict) -> dict:
    """Dispatch one source's options to its reader/ingestor."""
    from .sources import calendar as calsrc
    from .sources import chrome, firefox
    from .sources import filesystem as fssrc
    from .sources import git as gitsrc

    if source == "git":
        repos = opts.get("repos") or []
        author = opts.get("author_email")
        per_repo = [gitsrc.ingest_repo(conn, r, author_email=author) for r in repos]
        return {"ingested": sum(r["ingested"] for r in per_repo), "repos": per_repo}

    if source == "filesystem":
        dirs = opts.get("dirs") or []
        ignore = set(opts.get("ignore") or fssrc.DEFAULT_IGNORE)
        per_dir = [fssrc.ingest_directory(conn, d, ignore=ignore) for d in dirs]
        return {"ingested": sum(r["ingested"] for r in per_dir), "dirs": per_dir}

    if source == "calendar":
        ics_paths = opts.get("ics_paths") or []
        ingested = 0
        for path in ics_paths:
            for event in calsrc.read_events(path):
                store.upsert_event(conn, event)
                ingested += 1
        return {"ingested": ingested, "ics_paths": ics_paths}

    if source in ("chrome", "firefox"):
        # Browser indexing needs a concrete History/places.sqlite path — either
        # explicit in config or auto-located.
        explicit = opts.get("history_db") or opts.get("places_db")
        reader = chrome if source == "chrome" else firefox
        if explicit:
            path = Path(explicit).expanduser()
        else:
            profile = chrome.locate_profile() if source == "chrome" else firefox.locate_profile()
            if profile is None:
                return {"ingested": 0, "note": "profile not located — set [sources.<name>].profile_dir"}
            path = profile / ("History" if source == "chrome" else "places.sqlite")
        if not path.is_file():
            return {"ingested": 0, "note": f"DB not found at {path}"}
        state = store.get_source_state(conn, source)
        since = state["last_event_ts"] if state and state.get("last_event_ts") else None
        ingested = 0
        high = since
        for event in reader.read_events(path, source_name=source, since_ts=since):
            store.upsert_event(conn, event)
            ingested += 1
            if high is None or event.ts > high:
                high = event.ts
        if high is not None:
            store.update_source_state(conn, source, last_event_ts=int(high))
        return {"ingested": ingested, "db_path": str(path)}

    return {"ingested": 0, "note": f"unknown source: {source}"}


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
