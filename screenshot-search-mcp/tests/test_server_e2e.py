"""End-to-end MCP protocol test.

Uses the FastMCP in-memory `Client` transport — no stdio, no subprocess. This
exercises the real `list_tools` / `call_tool` path that Claude Desktop / Cursor /
Cline / Continue use, so a pass here means every tool is reachable and its JSON
schema is well-formed.

CLIP- and Tesseract-dependent paths are NOT exercised live (the model and binary
aren't guaranteed to exist in this env). Those tools are called only to confirm
they return graceful error payloads instead of raising.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from fastmcp import Client
from PIL import Image


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Fresh server instance per test, pointed at a tmp DB."""
    monkeypatch.setenv("SCREENSHOT_SEARCH_DB", str(tmp_path / "e2e.db"))
    import sys
    for name in list(sys.modules):
        if name.startswith("screenshot_search"):
            del sys.modules[name]
    from screenshot_search.server import mcp
    return mcp


@pytest.fixture
def sample_image(tmp_path):
    p = tmp_path / "screenshot.png"
    Image.new("RGB", (64, 64), color=(50, 100, 200)).save(p)
    return p


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop_policy()._local._loop else asyncio.run(coro)


@pytest.mark.asyncio
async def test_all_tools_are_listed(server):
    async with Client(server) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "ping",
        "index_directory",
        "index_status",
        "search_text",
        "search_visual",
        "find_similar",
        "extract_text",
        "get_metadata",
    }


@pytest.mark.asyncio
async def test_ping_via_protocol(server):
    async with Client(server) as client:
        result = await client.call_tool("ping", {})
    payload = json.loads(result.content[0].text)
    assert payload["server"] == "screenshot-search-mcp"
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_index_then_search_text(server, tmp_path, sample_image):
    """End-to-end: index a folder, then run an FTS query that finds nothing
    (no OCR available) and confirm the response shape is correct.
    """
    async with Client(server) as client:
        idx = await client.call_tool(
            "index_directory",
            {"path": str(sample_image.parent), "recursive": False},
        )
        idx_payload = json.loads(idx.content[0].text)
        assert idx_payload["scanned"] >= 1
        assert idx_payload["indexed"] >= 1

        status = await client.call_tool("index_status", {})
        status_payload = json.loads(status.content[0].text)
        assert status_payload["total_images"] >= 1

        results = await client.call_tool(
            "search_text", {"query": "nonexistent token", "max_results": 5}
        )
        results_payload = json.loads(results.content[0].text)
        assert results_payload["count"] == 0
        assert results_payload["results"] == []


@pytest.mark.asyncio
async def test_get_metadata_via_protocol(server, sample_image):
    async with Client(server) as client:
        result = await client.call_tool(
            "get_metadata", {"image_path": str(sample_image)}
        )
    payload = json.loads(result.content[0].text)
    assert payload["path"] == str(sample_image)
    assert payload["width"] == 64
    assert payload["height"] == 64
    assert payload["format"] == "PNG"


@pytest.mark.asyncio
async def test_extract_text_handles_missing_file(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "extract_text", {"image_path": "/does/not/exist.png"}
        )
    payload = json.loads(result.content[0].text)
    assert "error" in payload
    assert payload["text"] == ""


@pytest.mark.asyncio
async def test_visual_tools_degrade_gracefully_without_clip(server, sample_image):
    """search_visual and find_similar should return {error: ...} rather than 500
    when open_clip isn't usable. (open_clip IS installed via deps, but in CI
    without weights this exercises the same error code path.)
    """
    async with Client(server) as client:
        sv = await client.call_tool("search_visual", {"query": "test"})
        fs = await client.call_tool(
            "find_similar", {"image_path": str(sample_image)}
        )
    sv_payload = json.loads(sv.content[0].text)
    fs_payload = json.loads(fs.content[0].text)
    # Either a real result or a graceful error — never a crash.
    for payload in (sv_payload, fs_payload):
        assert "count" in payload or "error" in payload
