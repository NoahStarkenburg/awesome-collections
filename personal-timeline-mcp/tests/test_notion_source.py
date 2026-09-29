"""Tests for the Notion export reader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from personal_timeline.sources import notion


def _make_page(root: Path, dir_name: str, html: str, mtime: int) -> Path:
    """Build a fixture Notion page: <root>/<dir_name>/<dir_name>.html with
    given content + mtime."""
    page_dir = root / dir_name
    page_dir.mkdir(parents=True, exist_ok=True)
    html_path = page_dir / f"{dir_name}.html"
    html_path.write_text(html, encoding="utf-8")
    os.utime(html_path, (mtime, mtime))
    return html_path


def test_strip_hash_removes_notion_trailing_hash():
    assert notion._strip_hash("My Page 0123456789abcdef0123456789abcdef") == (
        "My Page",
        "0123456789abcdef0123456789abcdef",
    )


def test_strip_hash_without_match_returns_original():
    assert notion._strip_hash("plain-name") == ("plain-name", None)


def test_read_events_basic(tmp_path: Path):
    _make_page(
        tmp_path,
        "Roadmap 0123456789abcdef0123456789abcdef",
        "<html><body><h1>Roadmap</h1><p>Ship Q1</p></body></html>",
        1715000000,
    )
    events = list(notion.read_events(tmp_path))
    assert len(events) == 1
    e = events[0]
    assert e.source == "notion"
    assert e.title == "Roadmap"
    assert "Ship Q1" in e.body
    assert e.ts == 1715000000
    assert e.source_id == "notion:0123456789abcdef0123456789abcdef"
    assert e.payload["page_hash"] == "0123456789abcdef0123456789abcdef"


def test_extracts_text_skipping_script_and_style(tmp_path: Path):
    _make_page(
        tmp_path,
        "Notes 0123456789abcdef0123456789abcdef",
        "<html><head><style>.a{}</style></head><body>"
        "<script>alert('hi')</script>"
        "<p>Visible content here.</p></body></html>",
        1715000000,
    )
    events = list(notion.read_events(tmp_path))
    body = events[0].body
    assert "Visible content here" in body
    assert "alert" not in body
    assert ".a{}" not in body


def test_recurses_into_subpages(tmp_path: Path):
    _make_page(
        tmp_path,
        "Top 0123456789abcdef0123456789abcdef",
        "<html><body>top</body></html>",
        1715000000,
    )
    sub_dir = tmp_path / "Top 0123456789abcdef0123456789abcdef"
    _make_page(
        sub_dir,
        "Child deadbeefcafef00ddeadbeefcafef00d",
        "<html><body>child</body></html>",
        1715000100,
    )
    events = list(notion.read_events(tmp_path))
    titles = sorted(e.title for e in events)
    assert titles == ["Child", "Top"]


def test_since_filter(tmp_path: Path):
    _make_page(tmp_path, "Old 11111111111111111111111111111111", "<p>old</p>", 1000)
    _make_page(tmp_path, "New 22222222222222222222222222222222", "<p>new</p>", 2000)
    events = list(notion.read_events(tmp_path, since_ts=1500))
    assert [e.title for e in events] == ["New"]


def test_fallback_source_id_when_no_hash(tmp_path: Path):
    """Pages without the standard 32-hex suffix still get indexed; source_id
    falls back to the relative path so re-runs stay idempotent."""
    _make_page(tmp_path, "plain", "<p>x</p>", 1715000000)
    events = list(notion.read_events(tmp_path))
    assert events[0].source_id == "path:plain/plain.html"
    assert events[0].payload["page_hash"] is None


def test_handles_malformed_html(tmp_path: Path):
    _make_page(
        tmp_path,
        "Broken 33333333333333333333333333333333",
        "<html><body><p>unclosed paragraph<div>still text",
        1715000000,
    )
    events = list(notion.read_events(tmp_path))
    # Parser should still surface readable text, not crash.
    assert "still text" in events[0].body


def test_missing_root_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(notion.read_events(tmp_path / "nope"))
