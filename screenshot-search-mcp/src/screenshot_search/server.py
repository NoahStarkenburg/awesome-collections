"""FastMCP server entry point.

Run during development with:
    fastmcp dev src/screenshot_search/server.py

Run for clients (Claude Desktop, Cursor, etc.) via stdio:
    python -m screenshot_search.server

The server keeps one SQLite connection alive for the process lifetime. The DB
path defaults to `~/.screenshot-search/index.db` and can be overridden with
the `SCREENSHOT_SEARCH_DB` env var.
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from pathlib import Path

from fastmcp import FastMCP

from . import __version__, index, store

mcp = FastMCP(
    name="screenshot-search",
    instructions=(
        "Index and search screenshots by OCR text (Tesseract) and visual content "
        "(CLIP). Call `index_directory(path)` first to populate the index, then "
        "`search_text(query)` or `search_visual(query)`."
    ),
)


def _db_path() -> Path:
    override = os.environ.get("SCREENSHOT_SEARCH_DB")
    if override:
        return Path(override)
    return Path.home() / ".screenshot-search" / "index.db"


_conn_lock = threading.Lock()
_conn = None
_last_result: dict | None = None


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
        "server": "screenshot-search-mcp",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "ok",
    }


@mcp.tool()
def index_status() -> dict:
    """Report current index state: total rows, embedding count, last index run.

    Use this to confirm what's actually been indexed before running searches.
    """
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    embedded = conn.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"]
    last = conn.execute(
        "SELECT path, indexed_at FROM images ORDER BY indexed_at DESC LIMIT 1"
    ).fetchone()
    return {
        "db_path": str(_db_path()),
        "total_images": int(total),
        "total_embeddings": int(embedded),
        "last_indexed_path": None if last is None else last["path"],
        "last_indexed_at": None if last is None else float(last["indexed_at"]),
        "last_run": _last_result,
    }


@mcp.tool()
def index_directory(path: str, recursive: bool = True) -> dict:
    """Scan a directory for images and OCR-index any new or changed files.

    Args:
        path: directory to scan (absolute or expandable).
        recursive: walk subdirectories. Defaults to true.

    Returns a summary dict: scanned, indexed, skipped_unchanged, errored,
    last_path. Call this before `search_text` / `search_visual`.
    """
    global _last_result
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        return {"error": f"Not a directory: {target}"}

    conn = _get_conn()
    result = index.index_directory(conn, target, recursive=recursive)
    payload = result.as_dict()
    payload["root"] = str(target)
    _last_result = payload
    return payload


@mcp.tool()
def search_text(query: str, since: str | None = None, max_results: int = 10) -> dict:
    """Full-text search the OCR'd text of indexed screenshots.

    Args:
        query: FTS5 query string. Plain words work; quote phrases for exact match.
        since: optional ISO-8601 timestamp or epoch seconds — restrict to files
            modified after this time. Examples: "2026-04-01", "1714521600".
        max_results: cap on returned rows.

    Returns: {results: [{path, mtime, size, ocr_text_excerpt, score}, ...], count}.
    """
    conn = _get_conn()
    since_ts: float | None = None
    if since is not None and since != "":
        since_ts = _parse_since(since)

    rows = store.search_text(conn, query, since=since_ts, max_results=max_results)
    return {
        "count": len(rows),
        "results": [
            {
                "path": r["path"],
                "mtime": float(r["mtime"]),
                "size": int(r["size"]),
                "ocr_text_excerpt": (r["ocr_text"] or "")[:200],
                "score": float(r["score"]),
            }
            for r in rows
        ],
    }


def _parse_since(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        pass
    from datetime import datetime, timezone

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse `since`: {value!r}")


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
