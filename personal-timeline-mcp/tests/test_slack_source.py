"""Tests for the Slack export reader.

Builds a fixture export tree in tmp_path with the same layout Slack actually
hands you, then asserts the reader yields well-shaped Event rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from personal_timeline.sources import slack


def _make_export(root: Path, *, users: list[dict], channels: dict[str, dict]) -> Path:
    """`channels`: {channel_name: {YYYY-MM-DD: [message, ...]}}"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "users.json").write_text(json.dumps(users), encoding="utf-8")
    for name, days in channels.items():
        chan_dir = root / name
        chan_dir.mkdir()
        for day, messages in days.items():
            (chan_dir / f"{day}.json").write_text(json.dumps(messages), encoding="utf-8")
    return root


def test_read_events_basic(tmp_path: Path):
    export = tmp_path / "export"
    _make_export(
        export,
        users=[
            {"id": "U001", "name": "noah", "profile": {"real_name": "Noah Starkenburg"}},
            {"id": "U002", "name": "alex", "profile": {"display_name": "Alex"}},
        ],
        channels={
            "engineering": {
                "2026-05-15": [
                    {"type": "message", "ts": "1747310400.000100", "user": "U001", "text": "hi"},
                    {"type": "message", "ts": "1747310500.000200", "user": "U002", "text": "hey"},
                ],
            },
        },
    )
    events = list(slack.read_events(export))
    assert len(events) == 2
    assert events[0].source == "slack"
    assert events[0].title == "#engineering · Noah Starkenburg"
    assert events[0].body == "hi"
    assert events[0].ts == 1747310400
    assert events[0].source_id == "engineering:1747310400.000100"
    assert events[0].payload["user_id"] == "U001"
    assert events[0].payload["user_name"] == "Noah Starkenburg"
    assert events[1].title == "#engineering · Alex"


def test_skips_non_message_types(tmp_path: Path):
    export = tmp_path / "export"
    _make_export(
        export,
        users=[{"id": "U001", "name": "noah"}],
        channels={
            "general": {
                "2026-05-15": [
                    {"type": "message", "ts": "1747310400.000100", "user": "U001", "text": "hi"},
                    {"type": "channel_join", "ts": "1747310500.000200", "user": "U001"},
                    {"type": "channel_purpose", "ts": "1747310600.000300"},
                    {"type": "message", "ts": "1747310700.000400", "user": "U001", "text": "ok"},
                ],
            },
        },
    )
    events = list(slack.read_events(export))
    bodies = [e.body for e in events]
    assert bodies == ["hi", "ok"]


def test_since_ts_filters_older_messages(tmp_path: Path):
    export = tmp_path / "export"
    _make_export(
        export,
        users=[{"id": "U001", "name": "noah"}],
        channels={
            "general": {
                "2026-05-15": [
                    {"type": "message", "ts": "1000.0", "user": "U001", "text": "old"},
                    {"type": "message", "ts": "2000.0", "user": "U001", "text": "newer"},
                    {"type": "message", "ts": "3000.0", "user": "U001", "text": "newest"},
                ],
            },
        },
    )
    events = list(slack.read_events(export, since_ts=1500))
    assert [e.body for e in events] == ["newer", "newest"]


def test_falls_back_to_user_id_when_users_json_missing(tmp_path: Path):
    export = tmp_path / "export"
    export.mkdir()
    # No users.json — the reader has to surface the raw user id.
    (export / "general").mkdir()
    (export / "general" / "2026-05-15.json").write_text(
        json.dumps([{"type": "message", "ts": "100.0", "user": "U999", "text": "hi"}]),
        encoding="utf-8",
    )
    events = list(slack.read_events(export))
    assert events[0].title == "#general · U999"


def test_skips_malformed_daily_files(tmp_path: Path):
    export = tmp_path / "export"
    _make_export(
        export,
        users=[{"id": "U001", "name": "noah"}],
        channels={
            "general": {
                "2026-05-15": [
                    {"type": "message", "ts": "100.0", "user": "U001", "text": "valid"},
                ],
            },
        },
    )
    # Drop a malformed file in the same channel — must not crash.
    (export / "general" / "2026-05-16.json").write_text("{not json", encoding="utf-8")
    events = list(slack.read_events(export))
    assert [e.body for e in events] == ["valid"]


def test_ignores_non_daily_filenames(tmp_path: Path):
    """The export tool can drop README.md, canvas exports, etc. into channel
    dirs. We only consume YYYY-MM-DD.json — everything else is left alone."""
    export = tmp_path / "export"
    _make_export(
        export,
        users=[{"id": "U001", "name": "noah"}],
        channels={
            "general": {
                "2026-05-15": [{"type": "message", "ts": "100.0", "user": "U001", "text": "ok"}],
            },
        },
    )
    (export / "general" / "README.md").write_text("# channel info", encoding="utf-8")
    (export / "general" / "canvas.json").write_text("[]", encoding="utf-8")
    events = list(slack.read_events(export))
    assert len(events) == 1


def test_missing_export_dir_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(slack.read_events(tmp_path / "nope"))
