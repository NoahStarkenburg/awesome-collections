"""End-to-end MCP protocol test for personal-timeline-mcp.

Uses the FastMCP in-memory `Client` transport so every tool is exercised
through the real list_tools + call_tool code path. Re-runnable in CI without
launching a real MCP client process.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import Client


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Fresh server module per test, pointed at a tmp DB."""
    monkeypatch.setenv("PERSONAL_TIMELINE_DB", str(tmp_path / "e2e.db"))
    import sys
    for name in list(sys.modules):
        if name.startswith("personal_timeline"):
            del sys.modules[name]
    from personal_timeline.server import mcp
    return mcp


@pytest.mark.asyncio
async def test_all_tools_are_listed(server):
    async with Client(server) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "ping",
        "list_sources",
        "index_sources",
        "timeline_around",
        "what_changed_today",
        "find_session",
        "summarize_workday",
        "correlate",
    }


@pytest.mark.asyncio
async def test_ping_via_protocol(server):
    async with Client(server) as client:
        result = await client.call_tool("ping", {})
    payload = json.loads(result.content[0].text)
    assert payload["server"] == "personal-timeline-mcp"
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_list_sources_via_protocol(server):
    async with Client(server) as client:
        result = await client.call_tool("list_sources", {})
    payload = json.loads(result.content[0].text)
    assert payload["total_events"] == 0
    names = [s["source"] for s in payload["sources"]]
    assert {"chrome", "firefox", "git", "filesystem", "calendar"} <= set(names)


@pytest.mark.asyncio
async def test_index_sources_with_nothing_enabled(server):
    async with Client(server) as client:
        result = await client.call_tool("index_sources", {})
    payload = json.loads(result.content[0].text)
    assert payload["total_ingested"] == 0
    assert payload["errors"] == []


@pytest.mark.asyncio
async def test_find_session_returns_empty_on_fresh_db(server):
    async with Client(server) as client:
        result = await client.call_tool("find_session", {"query": "anything", "max_results": 5})
    payload = json.loads(result.content[0].text)
    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_timeline_around_accepts_iso_and_epoch(server):
    async with Client(server) as client:
        r1 = await client.call_tool("timeline_around", {"timestamp": "2026-05-15T12:00:00Z", "window": "30m"})
        r2 = await client.call_tool("timeline_around", {"timestamp": "1747310400", "window": "30m"})
    p1 = json.loads(r1.content[0].text)
    p2 = json.loads(r2.content[0].text)
    assert p1["count"] == 0
    assert p2["count"] == 0
    assert p1["window_seconds"] == 3600
    assert p2["window_seconds"] == 3600


@pytest.mark.asyncio
async def test_summarize_workday_handles_empty_db(server):
    async with Client(server) as client:
        result = await client.call_tool("summarize_workday", {"date": "2026-05-15"})
    payload = json.loads(result.content[0].text)
    assert payload["total_events"] == 0
    assert payload["git_commits"] == []
    assert payload["calendar_blocks"] == []
    assert payload["top_files"] == []


@pytest.mark.asyncio
async def test_correlate_missing_event(server):
    async with Client(server) as client:
        result = await client.call_tool("correlate", {"event_id": 99999})
    payload = json.loads(result.content[0].text)
    assert "error" in payload
    assert payload["count"] == 0


@pytest.mark.asyncio
async def test_what_changed_today_via_protocol(server):
    async with Client(server) as client:
        result = await client.call_tool("what_changed_today", {"date": "2026-05-15"})
    payload = json.loads(result.content[0].text)
    assert payload["date"] == "2026-05-15"
    assert payload["count"] == 0
