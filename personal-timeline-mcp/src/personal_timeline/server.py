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
from datetime import UTC
from pathlib import Path

from fastmcp import FastMCP

from . import __version__, config, store

mcp = FastMCP(
    name="personal-timeline",
    instructions=(
        "Local activity timeline aggregator. Sources: browser history "
        "(Chrome/Edge/Brave/Firefox/Safari), VS Code workspaces, "
        "git commits, filesystem mtimes, "
        "calendar (.ics). All local — no network. Call `list_sources()` "
        "first to see what's configured. Use `index_sources()` to populate "
        "the index, then `timeline_around()`, `what_changed_today()`, "
        "`find_session()`, `summarize_workday()`, `summarize_week()`, "
        "or `correlate()`."
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


def reset_connection() -> None:
    """Drop the cached SQLite connection. Call this from out-of-band entry
    points (the CLI, tests) when you've changed the DB path after the server
    module was already imported. The next `_get_conn()` call will reopen
    against the current `_db_path()`."""
    import contextlib

    global _conn
    with _conn_lock:
        if _conn is not None:
            with contextlib.suppress(Exception):
                _conn.close()
            _conn = None


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
                    "last_event_ts": None
                    if row["last_event_ts"] is None
                    else int(row["last_event_ts"]),
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

    Sources covered (each only runs if its `enabled = true` in config.toml):
        - `git`        — every repo under `[sources.git].repos`
        - `filesystem` — every dir under `[sources.filesystem].dirs`
        - `chrome` / `firefox` — auto-locate the History/places DB, or use
          `[sources.<name>].profile_dir` (Chromium) / `history_db`/`places_db`
          to point at an explicit path
        - `calendar`   — every path under `[sources.calendar].ics_paths`

    Args:
        force_full: if true, clear `source_state` for each enabled source so
            the next pass walks from the beginning. State for *disabled*
            sources is preserved.

    Returns: {results: {source: <per-source result>}, total_ingested, errors}.
    """
    cfg = config.load()
    conn = _get_conn()
    results: dict = {}
    errors: list[dict] = []
    total_ingested = 0

    enabled = [(name, sc) for name, sc in cfg.sources.items() if sc.enabled]

    if force_full and enabled:
        # Clear watermark state only for the sources we're about to reindex.
        # Source rows are keyed either as bare `<name>` (browser sources) or
        # `<name>:<absolute-path>` (git, filesystem) so match both shapes.
        for name, _sc in enabled:
            conn.execute(
                "DELETE FROM source_state WHERE source = ? OR source LIKE ?",
                (name, f"{name}:%"),
            )
        conn.commit()

    for name, sc in enabled:
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


@mcp.tool()
def timeline_around(
    timestamp: str,
    window: str = "1h",
    sources: list[str] | None = None,
    limit: int = 200,
) -> dict:
    """Return events within ±`window` of `timestamp`, across all sources.

    Args:
        timestamp: ISO-8601 (`2026-05-14T09:30:00Z` or `2026-05-14`) or epoch seconds.
        window: human-readable span — `"30m"`, `"1h"`, `"2h"`, `"1d"`. Default 1h.
        sources: optional source filter (e.g. `["git", "calendar"]`).
        limit: cap on returned events.

    Returns: {center_ts, window_seconds, count, events: [...]}.
    """
    center = _parse_ts(timestamp)
    half = _parse_window(window)
    rows = store.events_in_range(
        _get_conn(),
        start_ts=center - half,
        end_ts=center + half,
        sources=sources,
        limit=limit,
    )
    return {
        "center_ts": center,
        "window_seconds": half * 2,
        "count": len(rows),
        "events": [_row_to_dict(r) for r in rows],
    }


@mcp.tool()
def what_changed_today(path: str | None = None, date: str | None = None) -> dict:
    """Return filesystem + git events for a given day (default: today).

    Args:
        path: optional path prefix — restrict to events whose payload `path`
            (fs) or `files` (git) include this substring.
        date: optional ISO date (`YYYY-MM-DD`); default is the system's
            current UTC date.

    Returns: {date, count, events: [...]} — events ordered chronologically.
    """
    from datetime import datetime, timedelta

    if date is None:
        day = datetime.now(UTC).date()
    else:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    start = int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp())
    end = (
        int(
            (datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)).timestamp()
        )
        - 1
    )

    rows = store.events_in_range(
        _get_conn(),
        start_ts=start,
        end_ts=end,
        sources=["fs", "git"],
        limit=500,
    )
    out: list[dict] = []
    for row in rows:
        if path is not None and not _row_touches_path(row, path):
            continue
        out.append(_row_to_dict(row))
    return {
        "date": str(day),
        "path_filter": path,
        "count": len(out),
        "events": out,
    }


@mcp.tool()
def find_session(query: str, max_results: int = 20) -> dict:
    """FTS5 search across event title + body.

    Returns the highest-scoring events (lower BM25 = better). Useful for
    "find that thing I was working on" queries.

    Args:
        query: FTS5 query string. Plain words work; quote phrases for exact.
        max_results: cap on returned rows.
    """
    rows = store.search_events(_get_conn(), query, max_results=max_results)
    return {
        "query": query,
        "count": len(rows),
        "results": [{**_row_to_dict(r), "score": float(r["score"])} for r in rows],
    }


def _summarize_day(conn, day) -> dict:
    """Aggregate a single calendar day. Pulled out of `summarize_workday` so
    `summarize_week` can call it seven times without duplicating logic."""
    import json
    from collections import Counter
    from datetime import datetime, timedelta

    start = int(datetime.combine(day, datetime.min.time(), tzinfo=UTC).timestamp())
    end = (
        int(
            (datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)).timestamp()
        )
        - 1
    )

    rows = store.events_in_range(conn, start_ts=start, end_ts=end, limit=10_000)

    by_source: Counter = Counter()
    commits: list[dict] = []
    calendar_blocks: list[dict] = []
    file_hits: Counter = Counter()
    first_event_ts: int | None = None
    last_event_ts: int | None = None

    for row in rows:
        by_source[row["source"]] += 1
        ts = int(row["ts"])
        first_event_ts = ts if first_event_ts is None else min(first_event_ts, ts)
        last_event_ts = ts if last_event_ts is None else max(last_event_ts, ts)
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if row["source"] == "git":
            commits.append(
                {
                    "ts": ts,
                    "sha": payload.get("sha"),
                    "subject": row["title"],
                    "files": payload.get("files") or [],
                }
            )
            for f in payload.get("files") or []:
                file_hits[f] += 1
        elif row["source"] == "calendar":
            calendar_blocks.append(
                {
                    "ts": ts,
                    "end_ts": None if row["end_ts"] is None else int(row["end_ts"]),
                    "summary": row["title"],
                    "location": payload.get("location"),
                }
            )
        elif row["source"] == "fs":
            path = payload.get("path")
            if path:
                file_hits[path] += 1

    return {
        "date": str(day),
        "by_source": dict(by_source),
        "total_events": sum(by_source.values()),
        "first_event_ts": first_event_ts,
        "last_event_ts": last_event_ts,
        "active_hours": (
            None
            if first_event_ts is None or last_event_ts is None
            else round((last_event_ts - first_event_ts) / 3600, 1)
        ),
        "git_commits": commits,
        "calendar_blocks": calendar_blocks,
        "top_files": [{"path": p, "hits": n} for p, n in file_hits.most_common(10)],
        "_file_hits": file_hits,  # internal — stripped before client return
    }


def _strip_internal(day_summary: dict) -> dict:
    """Drop fields prefixed with `_` before returning to MCP clients."""
    return {k: v for k, v in day_summary.items() if not k.startswith("_")}


@mcp.tool()
def summarize_workday(date: str | None = None) -> dict:
    """Aggregate report for one day: per-source counts, git commits, calendar
    blocks, top edited files.

    Args:
        date: optional ISO date (`YYYY-MM-DD`); default today (UTC).
    """
    from datetime import datetime

    if date is None:
        day = datetime.now(UTC).date()
    else:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    return _strip_internal(_summarize_day(_get_conn(), day))


@mcp.tool()
def summarize_week(week_start: str | None = None) -> dict:
    """Aggregate a 7-day rollup with per-day breakdown.

    Args:
        week_start: optional ISO date (`YYYY-MM-DD`) of the first day to
            include. Default is the Monday of the current UTC week.

    Returns:
        - `week_start` / `week_end`: ISO dates for the inclusive 7-day window.
        - `days`: 7 per-day summaries (same shape as `summarize_workday`).
        - `by_source`: rolled-up event counts across the week.
        - `total_events`, `total_active_hours`.
        - `top_files`: top 10 across the week.
    """
    from collections import Counter
    from datetime import datetime, timedelta

    if week_start is None:
        today = datetime.now(UTC).date()
        start_day = today - timedelta(days=today.weekday())  # Monday
    else:
        start_day = datetime.strptime(week_start, "%Y-%m-%d").date()

    conn = _get_conn()
    days_summary: list[dict] = []
    by_source: Counter = Counter()
    file_hits: Counter = Counter()
    total_active_hours = 0.0

    for offset in range(7):
        day = start_day + timedelta(days=offset)
        ds = _summarize_day(conn, day)
        for source, count in ds["by_source"].items():
            by_source[source] += count
        file_hits.update(ds["_file_hits"])
        if ds["active_hours"] is not None:
            total_active_hours += ds["active_hours"]
        days_summary.append(_strip_internal(ds))

    week_end = start_day + timedelta(days=6)
    return {
        "week_start": str(start_day),
        "week_end": str(week_end),
        "by_source": dict(by_source),
        "total_events": sum(by_source.values()),
        "total_active_hours": round(total_active_hours, 1),
        "top_files": [{"path": p, "hits": n} for p, n in file_hits.most_common(10)],
        "days": days_summary,
    }


@mcp.tool()
def export_events(
    output_path: str,
    since: str | None = None,
    until: str | None = None,
    sources: list[str] | None = None,
) -> dict:
    """Stream events to a JSONL file for archival or porting to another system.

    One JSON object per line: `{id, source, source_id, ts, end_ts, title,
    body, payload}`. The payload is decoded back to a dict so consumers
    don't have to re-parse `payload_json`.

    Args:
        output_path: destination file path. Parent directories are created.
            An existing file is overwritten.
        since: optional lower bound (inclusive). ISO-8601 or epoch seconds.
        until: optional upper bound (inclusive). Same shape as `since`.
        sources: optional source filter.

    Returns: {output_path, count, since_ts, until_ts, sources}.
    """
    import json as _json

    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    start_ts = _parse_ts(since) if since else 0
    end_ts = _parse_ts(until) if until else 2_147_483_647  # year 2038 sentinel
    if end_ts < start_ts:
        return {
            "error": f"until ({end_ts}) is before since ({start_ts})",
            "count": 0,
        }

    rows = store.events_in_range(
        _get_conn(),
        start_ts=start_ts,
        end_ts=end_ts,
        sources=sources,
        limit=10_000_000,
    )
    count = 0
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            try:
                payload = _json.loads(row["payload_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            fh.write(
                _json.dumps(
                    {
                        "id": int(row["id"]),
                        "source": row["source"],
                        "source_id": row["source_id"],
                        "ts": int(row["ts"]),
                        "end_ts": None if row["end_ts"] is None else int(row["end_ts"]),
                        "title": row["title"],
                        "body": row["body"],
                        "payload": payload,
                    }
                )
            )
            fh.write("\n")
            count += 1
    return {
        "output_path": str(out),
        "count": count,
        "since_ts": start_ts,
        "until_ts": end_ts,
        "sources": sources,
    }


@mcp.tool()
def delete_events_in_range(
    start: str,
    end: str,
    sources: list[str] | None = None,
) -> dict:
    """Remove events whose timestamp falls in [start, end]. Privacy escape hatch.

    Use to scrub a specific window (e.g. "delete the hour I accidentally
    browsed something I don't want indexed"). Inclusive on both ends so a
    single-second cleanup is expressible.

    Args:
        start: ISO-8601 (`2026-05-14T09:30:00Z` / `2026-05-14`) or epoch seconds.
        end:   same format. Must be >= `start`.
        sources: optional source filter — only drop rows from these sources
            within the window.

    Returns: {start_ts, end_ts, sources, deleted_count}.
    """
    start_ts = _parse_ts(start)
    end_ts = _parse_ts(end)
    if end_ts < start_ts:
        return {
            "error": f"end ({end_ts}) is before start ({start_ts})",
            "deleted_count": 0,
        }
    deleted = store.delete_events_in_range(
        _get_conn(), start_ts=start_ts, end_ts=end_ts, sources=sources
    )
    return {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "sources": sources,
        "deleted_count": int(deleted),
    }


@mcp.tool()
def correlate(
    event_id: int,
    sources: list[str] | None = None,
    window: str = "30m",
    limit: int = 50,
) -> dict:
    """Find events from OTHER sources within ±`window` of a given event.

    Use to answer "what meeting prompted this commit?" or "what was I reading
    when I edited this file?" The reference event itself is excluded.

    Args:
        event_id: row id from a prior tool call.
        sources: limit correlated events to these sources (optional).
        window: ±span like `"30m"`, `"1h"`. Default 30 minutes.
        limit: cap.
    """
    conn = _get_conn()
    row = conn.execute("SELECT * FROM events WHERE id = ?", (int(event_id),)).fetchone()
    if row is None:
        return {"error": f"No event with id={event_id}", "results": [], "count": 0}

    half = _parse_window(window)
    center = int(row["ts"])
    ref_source = row["source"]
    candidate_sources = sources if sources else None
    rows = store.events_in_range(
        conn,
        start_ts=center - half,
        end_ts=center + half,
        sources=candidate_sources,
        limit=limit + 1,
    )
    out = []
    for r in rows:
        if int(r["id"]) == int(event_id):
            continue
        if candidate_sources is None and r["source"] == ref_source:
            # Cross-source by default — same-source matches add noise.
            continue
        out.append(
            {
                **_row_to_dict(r),
                "delta_seconds": int(r["ts"]) - center,
            }
        )
        if len(out) >= limit:
            break
    return {
        "reference": _row_to_dict(row),
        "window_seconds": half * 2,
        "count": len(out),
        "results": out,
    }


def _row_touches_path(row, needle: str) -> bool:
    """True if this event's payload mentions `needle` (fs.path or git.files)."""
    import json

    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError):
        return False
    if row["source"] == "fs":
        return needle in (payload.get("path") or "")
    if row["source"] == "git":
        return any(needle in f for f in (payload.get("files") or []))
    return False


def _parse_ts(value: str | int | float) -> int:
    """Accept epoch seconds or ISO-8601 (`%Y-%m-%dT%H:%M:%S`/`Z`/`%Y-%m-%d`)."""
    if isinstance(value, int | float):
        return int(value)
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        pass
    from datetime import datetime

    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=UTC).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {value!r}")


def _parse_window(value: str) -> int:
    """Convert `"30m"` / `"1h"` / `"2h"` / `"1d"` to seconds. Returns half-window."""
    text = str(value).strip().lower()
    if not text:
        return 1800
    unit = text[-1]
    try:
        n = int(text[:-1])
    except ValueError as exc:
        raise ValueError(f"Cannot parse window: {value!r}") from exc
    if unit == "s":
        return n
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    if unit == "d":
        return n * 86400
    raise ValueError(f"Unknown window unit in {value!r}; use s/m/h/d")


def _row_to_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "source": row["source"],
        "source_id": row["source_id"],
        "ts": int(row["ts"]),
        "end_ts": None if row["end_ts"] is None else int(row["end_ts"]),
        "title": row["title"],
        "body": (row["body"] or "")[:300],
    }


def _ingest_one(conn, source: str, opts: dict) -> dict:
    """Dispatch one source's options to its reader/ingestor."""
    from .sources import calendar as calsrc
    from .sources import chrome, discord, firefox, mbox, notion, safari, slack, vscode
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

    if source == "slack":
        export_dirs = opts.get("export_dirs") or []
        state = store.get_source_state(conn, source)
        since = state["last_event_ts"] if state and state.get("last_event_ts") else None
        ingested = 0
        high = since
        for export_dir in export_dirs:
            for event in slack.read_events(export_dir, since_ts=since):
                store.upsert_event(conn, event)
                ingested += 1
                if high is None or event.ts > high:
                    high = event.ts
        if high is not None:
            store.update_source_state(conn, source, last_event_ts=int(high))
        return {"ingested": ingested, "export_dirs": export_dirs}

    if source == "mbox":
        paths = opts.get("paths") or []
        state = store.get_source_state(conn, source)
        since = state["last_event_ts"] if state and state.get("last_event_ts") else None
        ingested = 0
        high = since
        for path in paths:
            for event in mbox.read_events(path, since_ts=since):
                store.upsert_event(conn, event)
                ingested += 1
                if high is None or event.ts > high:
                    high = event.ts
        if high is not None:
            store.update_source_state(conn, source, last_event_ts=int(high))
        return {"ingested": ingested, "paths": paths}

    if source == "discord":
        package_dirs = opts.get("package_dirs") or []
        state = store.get_source_state(conn, source)
        since = state["last_event_ts"] if state and state.get("last_event_ts") else None
        ingested = 0
        high = since
        for package in package_dirs:
            for event in discord.read_events(package, since_ts=since):
                store.upsert_event(conn, event)
                ingested += 1
                if high is None or event.ts > high:
                    high = event.ts
        if high is not None:
            store.update_source_state(conn, source, last_event_ts=int(high))
        return {"ingested": ingested, "package_dirs": package_dirs}

    if source == "notion":
        export_dirs = opts.get("export_dirs") or []
        state = store.get_source_state(conn, source)
        since = state["last_event_ts"] if state and state.get("last_event_ts") else None
        ingested = 0
        high = since
        for export in export_dirs:
            for event in notion.read_events(export, since_ts=since):
                store.upsert_event(conn, event)
                ingested += 1
                if high is None or event.ts > high:
                    high = event.ts
        if high is not None:
            store.update_source_state(conn, source, last_event_ts=int(high))
        return {"ingested": ingested, "export_dirs": export_dirs}

    if source == "vscode":
        flavors = opts.get("flavors") or ["code"]
        state = store.get_source_state(conn, source)
        since = state["last_event_ts"] if state and state.get("last_event_ts") else None
        ingested = 0
        high = since
        dirs_seen: list[str] = []
        for flavor in flavors:
            for storage_dir in vscode.locate_storage_dirs(flavor):
                dirs_seen.append(str(storage_dir))
                for event in vscode.read_events(storage_dir, source_name=source, since_ts=since):
                    store.upsert_event(conn, event)
                    ingested += 1
                    if high is None or event.ts > high:
                        high = event.ts
        if high is not None:
            store.update_source_state(conn, source, last_event_ts=int(high))
        return {"ingested": ingested, "storage_dirs": dirs_seen, "flavors": flavors}

    if source in ("chrome", "firefox", "safari"):
        # Browser indexing needs a concrete History/places.sqlite path — either
        # explicit in config or auto-located.
        explicit = opts.get("history_db") or opts.get("places_db")
        if source == "chrome":
            reader = chrome
        elif source == "firefox":
            reader = firefox
        else:
            reader = safari
        if explicit:
            path = Path(explicit).expanduser()
        else:
            if source == "chrome":
                profile = chrome.locate_profile()
                db_name = "History"
            elif source == "firefox":
                profile = firefox.locate_profile()
                db_name = "places.sqlite"
            else:
                profile = safari.locate_profile()
                db_name = "History.db"
            if profile is None:
                return {
                    "ingested": 0,
                    "note": "profile not located — set [sources.<name>].profile_dir",
                }
            path = profile / db_name
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
