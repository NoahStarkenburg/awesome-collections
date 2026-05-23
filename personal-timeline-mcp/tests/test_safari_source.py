"""Tests for the Safari history reader.

Builds a fixture SQLite DB with the schema Safari actually uses, then asserts
the reader yields Event rows with correct CFAbsoluteTime → unix conversion.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from personal_timeline.sources import safari


def _make_safari_db(path: Path, rows: list[tuple[int, str, str, int]]) -> None:
    """rows: (visit_id, url, title, unix_ts_seconds)

    Builds the minimal subset of Safari's schema the reader needs:
        history_items (id, url)
        history_visits (id, history_item, visit_time, title)

    `visit_time` is written as CFAbsoluteTime (seconds since 2001-01-01 UTC).
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE history_items (id INTEGER PRIMARY KEY, url TEXT)")
    cur.execute(
        "CREATE TABLE history_visits ("
        "id INTEGER PRIMARY KEY, history_item INTEGER, "
        "visit_time REAL, title TEXT)"
    )
    for visit_id, url, title, unix_ts in rows:
        cur.execute(
            "INSERT OR IGNORE INTO history_items (id, url) VALUES (?, ?)",
            (visit_id, url),
        )
        cocoa_ts = unix_ts - 978307200
        cur.execute(
            "INSERT INTO history_visits VALUES (?, ?, ?, ?)",
            (visit_id, visit_id, cocoa_ts, title),
        )
    conn.commit()
    conn.close()


def test_cocoa_epoch_conversion_round_trip():
    # 2001-01-01T00:00:00 UTC == unix 978307200; CFAbsoluteTime 0 maps to that.
    assert safari.cocoa_seconds_to_unix_seconds(0) == 978307200
    # And an arbitrary later instant round-trips.
    unix_ts = 1715000000
    cocoa = unix_ts - 978307200
    assert safari.cocoa_seconds_to_unix_seconds(cocoa) == unix_ts


def test_safari_read_events_basic(tmp_path: Path):
    db = tmp_path / "History.db"
    _make_safari_db(
        db,
        [
            (1, "https://apple.com", "Apple", 1715000000),
            (2, "https://developer.apple.com", "Apple Developer", 1715000100),
        ],
    )
    events = list(safari.read_events(db))
    assert len(events) == 2
    assert [e.source for e in events] == ["safari", "safari"]
    assert events[0].ts == 1715000000
    assert events[1].ts == 1715000100
    assert events[0].body == "https://apple.com"
    assert events[0].title == "Apple"
    assert events[0].source_id == "visit:1"


def test_safari_falls_back_to_url_when_title_missing(tmp_path: Path):
    db = tmp_path / "History.db"
    _make_safari_db(db, [(1, "https://example.com", "", 1715000000)])
    events = list(safari.read_events(db))
    # Empty title falls back to url (matches chrome.py behavior).
    assert events[0].title == "https://example.com"


def test_safari_since_filter(tmp_path: Path):
    db = tmp_path / "History.db"
    _make_safari_db(
        db,
        [
            (1, "u1", "t1", 1000),
            (2, "u2", "t2", 2000),
            (3, "u3", "t3", 3000),
        ],
    )
    events = list(safari.read_events(db, since_ts=1500))
    assert [e.ts for e in events] == [2000, 3000]


def test_safari_source_name_override(tmp_path: Path):
    db = tmp_path / "History.db"
    _make_safari_db(db, [(1, "u", "t", 100)])
    events = list(safari.read_events(db, source_name="safari-tp"))
    assert events[0].source == "safari-tp"


def test_safari_read_events_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(safari.read_events(tmp_path / "nope.db"))


def test_locate_profile_does_not_raise():
    # Returns None on non-macOS platforms; a Path or None on macOS.
    result = safari.locate_profile()
    assert result is None or isinstance(result, Path)
