"""Tests for the Discord data-package reader.

Builds a fixture package tree in tmp_path with the same layout Discord
hands you, then asserts the reader yields well-shaped Event rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from personal_timeline.sources import discord


def _make_package(root: Path, channels: dict[str, dict]) -> Path:
    """`channels`: {channel_id: {"meta": {...}, "messages": [...]}}"""
    msgs_root = root / "messages"
    msgs_root.mkdir(parents=True, exist_ok=True)
    for channel_id, payload in channels.items():
        chan_dir = msgs_root / f"c{channel_id}"
        chan_dir.mkdir()
        (chan_dir / "channel.json").write_text(
            json.dumps(payload.get("meta") or {}), encoding="utf-8"
        )
        (chan_dir / "messages.json").write_text(
            json.dumps(payload.get("messages") or []), encoding="utf-8"
        )
    return root


def test_read_events_basic(tmp_path: Path):
    pkg = tmp_path / "discord-pkg"
    _make_package(
        pkg,
        {
            "111111": {
                "meta": {"id": "111111", "name": "general"},
                "messages": [
                    {
                        "ID": "msg-1",
                        "Timestamp": "2026-05-15T12:00:00+00:00",
                        "Contents": "hello",
                        "Attachments": "",
                    },
                    {
                        "ID": "msg-2",
                        "Timestamp": "2026-05-15T12:01:00+00:00",
                        "Contents": "world",
                        "Attachments": "",
                    },
                ],
            },
        },
    )
    events = list(discord.read_events(pkg))
    assert len(events) == 2
    assert events[0].source == "discord"
    assert events[0].title == "#general"
    assert events[0].body == "hello"
    assert events[0].source_id == "111111:msg-1"
    # 2026-05-15T12:00:00 UTC == 1778846400
    assert events[0].ts == 1778846400


def test_skips_empty_messages(tmp_path: Path):
    """Pure-join/leave noise (no Contents, no Attachments) is dropped."""
    pkg = _make_package(
        tmp_path / "pkg",
        {
            "200": {
                "meta": {"id": "200", "name": "noise"},
                "messages": [
                    {
                        "ID": "a",
                        "Timestamp": "2026-05-15T12:00:00Z",
                        "Contents": "real msg",
                        "Attachments": "",
                    },
                    {
                        "ID": "b",
                        "Timestamp": "2026-05-15T12:01:00Z",
                        "Contents": "",
                        "Attachments": "",
                    },
                ],
            },
        },
    )
    events = list(discord.read_events(pkg))
    assert [e.body for e in events] == ["real msg"]


def test_keeps_attachment_only_messages(tmp_path: Path):
    """Empty Contents + non-empty Attachments is still a real message."""
    pkg = _make_package(
        tmp_path / "pkg",
        {
            "300": {
                "meta": {"id": "300", "name": "media"},
                "messages": [
                    {
                        "ID": "x",
                        "Timestamp": "2026-05-15T12:00:00Z",
                        "Contents": "",
                        "Attachments": "https://cdn.example/img.png",
                    }
                ],
            },
        },
    )
    events = list(discord.read_events(pkg))
    assert len(events) == 1
    assert events[0].payload["attachments"].startswith("https://cdn")


def test_since_ts_filters_older(tmp_path: Path):
    pkg = _make_package(
        tmp_path / "pkg",
        {
            "1": {
                "meta": {"id": "1", "name": "g"},
                "messages": [
                    {"ID": "a", "Timestamp": "2024-01-01T00:00:00Z", "Contents": "old"},
                    {"ID": "b", "Timestamp": "2026-01-01T00:00:00Z", "Contents": "newer"},
                ],
            },
        },
    )
    events = list(discord.read_events(pkg, since_ts=1750000000))
    assert [e.body for e in events] == ["newer"]


def test_dm_channel_falls_back_to_recipients_label(tmp_path: Path):
    """DM channels (type 1) have no `name` — label uses recipients."""
    pkg = _make_package(
        tmp_path / "pkg",
        {
            "777": {
                "meta": {"id": "777", "type": 1, "recipients": ["alice", "bob"]},
                "messages": [
                    {
                        "ID": "m",
                        "Timestamp": "2026-05-15T12:00:00Z",
                        "Contents": "hey",
                    }
                ],
            },
        },
    )
    events = list(discord.read_events(pkg))
    assert events[0].title == "#dm:alice+bob"


def test_skips_messages_with_unparseable_timestamp(tmp_path: Path):
    pkg = _make_package(
        tmp_path / "pkg",
        {
            "1": {
                "meta": {"id": "1", "name": "g"},
                "messages": [
                    {"ID": "a", "Timestamp": "not-a-date", "Contents": "skip me"},
                    {"ID": "b", "Timestamp": "2026-05-15T12:00:00Z", "Contents": "keep"},
                ],
            },
        },
    )
    events = list(discord.read_events(pkg))
    assert [e.body for e in events] == ["keep"]


def test_missing_messages_dir_yields_nothing(tmp_path: Path):
    """A directory that exists but isn't a Discord package surfaces no events
    rather than crashing — useful when probing arbitrary paths."""
    (tmp_path / "random.txt").write_text("hi", encoding="utf-8")
    events = list(discord.read_events(tmp_path))
    assert events == []


def test_missing_root_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(discord.read_events(tmp_path / "nope"))
