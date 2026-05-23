"""End-to-end MCP protocol test for personal-timeline-mcp.

Uses the FastMCP in-memory `Client` transport so every tool is exercised
through the real list_tools + call_tool code path. Re-runnable in CI without
launching a real MCP client process.
"""

from __future__ import annotations

import json

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
        "summarize_week",
        "event_stats",
        "delete_events_in_range",
        "export_events",
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
        r1 = await client.call_tool(
            "timeline_around", {"timestamp": "2026-05-15T12:00:00Z", "window": "30m"}
        )
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


@pytest.mark.asyncio
async def test_summarize_week_handles_empty_db(server):
    async with Client(server) as client:
        result = await client.call_tool("summarize_week", {"week_start": "2026-05-11"})
    payload = json.loads(result.content[0].text)
    assert payload["week_start"] == "2026-05-11"
    assert payload["week_end"] == "2026-05-17"
    assert payload["total_events"] == 0
    assert len(payload["days"]) == 7
    assert payload["days"][0]["date"] == "2026-05-11"
    assert payload["days"][6]["date"] == "2026-05-17"
    # Each day's per-source dict + active_hours present even with no events.
    for day in payload["days"]:
        assert day["by_source"] == {}
        assert day["active_hours"] is None
        # Internal `_file_hits` must be stripped — clients should only see the
        # summarized `top_files` list.
        assert "_file_hits" not in day


@pytest.mark.asyncio
async def test_summarize_week_aggregates_across_days(server, tmp_path):
    """Seeds the DB out-of-band (own connection in the test thread), then
    asks summarize_week to roll it up via the MCP protocol."""
    import os

    from personal_timeline.store import Event, init_db, upsert_event

    seed_conn = init_db(os.environ["PERSONAL_TIMELINE_DB"])
    try:
        # Two git commits on 2026-05-11 (Mon), one on 2026-05-13 (Wed). Each
        # commit touches "src/server.py" so it appears in top_files.
        base_mon = 1778457600  # 2026-05-11T00:00:00Z (Monday)
        upsert_event(
            seed_conn,
            Event(
                source="git",
                source_id="sha:aaa",
                ts=base_mon + 3600,
                title="Wire foo",
                body="",
                payload={"sha": "aaa", "files": ["src/server.py"]},
            ),
        )
        upsert_event(
            seed_conn,
            Event(
                source="git",
                source_id="sha:bbb",
                ts=base_mon + 7200,
                title="Wire bar",
                body="",
                payload={"sha": "bbb", "files": ["src/server.py", "src/cli.py"]},
            ),
        )
        upsert_event(
            seed_conn,
            Event(
                source="git",
                source_id="sha:ccc",
                ts=base_mon + (86400 * 2) + 3600,  # Wed
                title="Wire baz",
                body="",
                payload={"sha": "ccc", "files": ["src/cli.py"]},
            ),
        )
    finally:
        seed_conn.close()

    async with Client(server) as client:
        result = await client.call_tool("summarize_week", {"week_start": "2026-05-11"})
    payload = json.loads(result.content[0].text)
    assert payload["total_events"] == 3
    assert payload["by_source"] == {"git": 3}
    # File hits: server.py twice, cli.py twice across the week.
    top = {f["path"]: f["hits"] for f in payload["top_files"]}
    assert top == {"src/server.py": 2, "src/cli.py": 2}
    # Per-day breakdown: Monday has 2 commits, Wednesday has 1, rest empty.
    counts_by_day = {d["date"]: d["total_events"] for d in payload["days"]}
    assert counts_by_day["2026-05-11"] == 2
    assert counts_by_day["2026-05-13"] == 1
    assert counts_by_day["2026-05-17"] == 0
    del tmp_path  # silence unused-arg lint


@pytest.mark.asyncio
async def test_event_stats_empty_db(server):
    async with Client(server) as client:
        result = await client.call_tool("event_stats", {})
    payload = json.loads(result.content[0].text)
    assert payload["total_events"] == 0
    assert payload["by_source"] == {}
    assert payload["oldest_ts"] is None
    assert payload["newest_ts"] is None
    assert payload["oldest_iso"] is None
    assert payload["newest_iso"] is None
    assert payload["db_size_bytes"] >= 0


@pytest.mark.asyncio
async def test_event_stats_populated(server, tmp_path):
    """Seed events from two sources; confirm counts, bounds, and ISO formatting."""
    import os

    from personal_timeline.store import Event, init_db, upsert_event

    seed_conn = init_db(os.environ["PERSONAL_TIMELINE_DB"])
    try:
        upsert_event(
            seed_conn,
            Event(source="git", source_id="a", ts=1000, title="t", body="", payload={}),
        )
        upsert_event(
            seed_conn,
            Event(source="git", source_id="b", ts=2000, title="t", body="", payload={}),
        )
        upsert_event(
            seed_conn,
            Event(source="chrome", source_id="c", ts=3000, title="t", body="", payload={}),
        )
    finally:
        seed_conn.close()

    async with Client(server) as client:
        result = await client.call_tool("event_stats", {})
    payload = json.loads(result.content[0].text)
    assert payload["total_events"] == 3
    assert payload["by_source"] == {"git": 2, "chrome": 1}
    assert payload["oldest_ts"] == 1000
    assert payload["newest_ts"] == 3000
    # ISO formatting sanity — ts=1000 is 1970-01-01T00:16:40Z.
    assert payload["oldest_iso"].startswith("1970-01-01")
    assert payload["db_size_bytes"] > 0
    del tmp_path


@pytest.mark.asyncio
async def test_delete_events_in_range_via_protocol(server, tmp_path):
    """Seed a few events, delete the middle hour, confirm only those rows go."""
    import os

    from personal_timeline.store import Event, init_db, upsert_event

    seed_conn = init_db(os.environ["PERSONAL_TIMELINE_DB"])
    try:
        for i, ts in enumerate([1000, 2000, 3000, 4000, 5000]):
            upsert_event(
                seed_conn,
                Event(
                    source="git" if i % 2 == 0 else "chrome",
                    source_id=f"id:{i}",
                    ts=ts,
                    title=f"event {i}",
                    body="",
                    payload={},
                ),
            )
    finally:
        seed_conn.close()

    async with Client(server) as client:
        result = await client.call_tool("delete_events_in_range", {"start": "2000", "end": "4000"})
    payload = json.loads(result.content[0].text)
    # Three rows fall in [2000, 4000] inclusive.
    assert payload["deleted_count"] == 3
    assert payload["start_ts"] == 2000
    assert payload["end_ts"] == 4000
    del tmp_path  # silence unused-arg lint


@pytest.mark.asyncio
async def test_delete_events_in_range_rejects_inverted(server):
    async with Client(server) as client:
        result = await client.call_tool("delete_events_in_range", {"start": "5000", "end": "1000"})
    payload = json.loads(result.content[0].text)
    assert "error" in payload
    assert payload["deleted_count"] == 0


@pytest.mark.asyncio
async def test_delete_events_in_range_source_filter(server, tmp_path):
    """Source filter scopes the wipe — git events vanish, chrome stays."""
    import os

    from personal_timeline.store import Event, init_db, upsert_event

    seed_conn = init_db(os.environ["PERSONAL_TIMELINE_DB"])
    try:
        upsert_event(
            seed_conn,
            Event(source="git", source_id="g1", ts=1000, title="g", body="", payload={}),
        )
        upsert_event(
            seed_conn,
            Event(source="chrome", source_id="c1", ts=1000, title="c", body="", payload={}),
        )
    finally:
        seed_conn.close()

    async with Client(server) as client:
        result = await client.call_tool(
            "delete_events_in_range",
            {"start": "0", "end": "2000", "sources": ["git"]},
        )
    payload = json.loads(result.content[0].text)
    assert payload["deleted_count"] == 1  # only git row dropped
    del tmp_path  # silence unused-arg lint


@pytest.mark.asyncio
async def test_export_events_jsonl_round_trip(server, tmp_path):
    """Seed events, export to JSONL, parse back, confirm shape + ordering."""
    import os

    from personal_timeline.store import Event, init_db, upsert_event

    seed_conn = init_db(os.environ["PERSONAL_TIMELINE_DB"])
    try:
        upsert_event(
            seed_conn,
            Event(
                source="git",
                source_id="sha:1",
                ts=1000,
                title="first",
                body="",
                payload={"sha": "abc", "files": ["a.py"]},
            ),
        )
        upsert_event(
            seed_conn,
            Event(
                source="chrome",
                source_id="visit:1",
                ts=2000,
                title="hn",
                body="https://news.ycombinator.com",
                payload={"url": "https://news.ycombinator.com"},
            ),
        )
    finally:
        seed_conn.close()

    out_path = tmp_path / "export.jsonl"
    async with Client(server) as client:
        result = await client.call_tool("export_events", {"output_path": str(out_path)})
    payload = json.loads(result.content[0].text)
    assert payload["count"] == 2
    assert payload["output_path"] == str(out_path)
    # Parse the JSONL back. Each line is a valid JSON dict with payload decoded.
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert rows[0]["source"] == "git"
    assert rows[0]["payload"] == {"sha": "abc", "files": ["a.py"]}
    assert rows[1]["source"] == "chrome"
    assert rows[1]["payload"] == {"url": "https://news.ycombinator.com"}


@pytest.mark.asyncio
async def test_export_events_respects_filters(server, tmp_path):
    """since/until/sources should restrict what lands in the export."""
    import os

    from personal_timeline.store import Event, init_db, upsert_event

    seed_conn = init_db(os.environ["PERSONAL_TIMELINE_DB"])
    try:
        for ts, source in [(100, "git"), (500, "chrome"), (1000, "git")]:
            upsert_event(
                seed_conn,
                Event(
                    source=source,
                    source_id=f"{source}:{ts}",
                    ts=ts,
                    title="x",
                    body="",
                    payload={},
                ),
            )
    finally:
        seed_conn.close()

    out_path = tmp_path / "filtered.jsonl"
    async with Client(server) as client:
        result = await client.call_tool(
            "export_events",
            {
                "output_path": str(out_path),
                "since": "200",
                "until": "1500",
                "sources": ["git"],
            },
        )
    payload = json.loads(result.content[0].text)
    # Only ts=1000 git event matches all three filters.
    assert payload["count"] == 1
    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["source"] == "git"
    assert rows[0]["ts"] == 1000
