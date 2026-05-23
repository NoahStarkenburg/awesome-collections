"""Tests for the mbox email reader.

Builds a fixture .mbox file in tmp_path with a couple of RFC-822 messages,
then asserts the reader yields well-shaped Event rows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from personal_timeline.sources import mbox


def _make_mbox(path: Path, messages: list[str]) -> Path:
    """Write a minimal `.mbox`. Each `messages` entry is a full RFC-822 blob
    (headers + blank line + body). mboxo separator is a `From ` line at the
    start of each message."""
    chunks = []
    for i, body in enumerate(messages):
        chunks.append(f"From sender@example.com Mon Jan  1 00:00:0{i} 2026\n")
        chunks.append(body)
        if not body.endswith("\n"):
            chunks.append("\n")
        chunks.append("\n")
    path.write_text("".join(chunks), encoding="utf-8")
    return path


def test_read_events_basic(tmp_path: Path):
    path = _make_mbox(
        tmp_path / "test.mbox",
        [
            "From: alice@example.com\n"
            "To: bob@example.com\n"
            "Subject: Hello\n"
            "Date: Fri, 15 May 2026 12:00:00 +0000\n"
            "Message-ID: <msg1@example.com>\n"
            "\n"
            "First message body.",
            "From: bob@example.com\n"
            "To: alice@example.com\n"
            "Subject: Re: Hello\n"
            "Date: Fri, 15 May 2026 12:30:00 +0000\n"
            "Message-ID: <msg2@example.com>\n"
            "\n"
            "Reply body.",
        ],
    )
    events = list(mbox.read_events(path))
    assert len(events) == 2
    assert events[0].source == "mbox"
    assert events[0].title == "Hello"
    assert "First message body" in events[0].body
    assert events[0].payload["from"] == "alice@example.com"
    assert events[0].source_id == "<msg1@example.com>"
    # 2026-05-15 12:00:00 UTC.
    assert events[0].ts == 1778846400


def test_skips_messages_without_date(tmp_path: Path):
    path = _make_mbox(
        tmp_path / "test.mbox",
        [
            "From: a@x.com\nSubject: dated\nDate: Fri, 15 May 2026 12:00:00 +0000\n\nbody",
            "From: b@x.com\nSubject: undated\n\nbody",
        ],
    )
    events = list(mbox.read_events(path))
    # Only the dated message survives.
    assert len(events) == 1
    assert events[0].title == "dated"


def test_since_filter(tmp_path: Path):
    path = _make_mbox(
        tmp_path / "test.mbox",
        [
            "From: a@x.com\nSubject: old\nDate: Mon, 01 Jan 2024 00:00:00 +0000\n\nold",
            "From: a@x.com\nSubject: new\nDate: Mon, 01 Jan 2026 00:00:00 +0000\n\nnew",
        ],
    )
    # since_ts between Jan 2024 and Jan 2026 — drops "old", keeps "new".
    events = list(mbox.read_events(path, since_ts=1750000000))
    assert [e.title for e in events] == ["new"]


def test_fallback_subject_and_sender(tmp_path: Path):
    path = _make_mbox(
        tmp_path / "test.mbox",
        [
            "Date: Fri, 15 May 2026 12:00:00 +0000\n\nbody only",
        ],
    )
    events = list(mbox.read_events(path))
    assert events[0].title == "(no subject)"
    assert events[0].payload["from"] == "(unknown sender)"


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(mbox.read_events(tmp_path / "nope.mbox"))


def test_source_name_override(tmp_path: Path):
    path = _make_mbox(
        tmp_path / "test.mbox",
        ["From: x@x.com\nSubject: t\nDate: Fri, 15 May 2026 12:00:00 +0000\n\nb"],
    )
    events = list(mbox.read_events(path, source_name="gmail-takeout"))
    assert events[0].source == "gmail-takeout"
