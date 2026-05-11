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


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
