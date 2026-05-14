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

import platform
import sys
import time

from fastmcp import FastMCP

from . import __version__

mcp = FastMCP(
    name="personal-timeline",
    instructions=(
        "Local activity timeline aggregator (browser history, git commits, "
        "filesystem mtimes, calendar). v0.0.1 — only `ping` is wired up so far. "
        "Real tools (index_sources, timeline_around, summarize_workday, etc.) "
        "land in subsequent commits."
    ),
)


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


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
