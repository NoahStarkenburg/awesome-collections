"""FastMCP server entry point.

Run during development with:
    fastmcp dev src/screenshot_search/server.py

Run for clients (Claude Desktop, Cursor, etc.) via stdio:
    python -m screenshot_search.server
"""
from __future__ import annotations

import platform
import sys
import time

from fastmcp import FastMCP

from . import __version__

mcp = FastMCP(
    name="screenshot-search",
    instructions=(
        "Index and search screenshots by OCR text (Tesseract) and visual content "
        "(CLIP). v0.0.1 — only `ping` is wired up so far."
    ),
)


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


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
