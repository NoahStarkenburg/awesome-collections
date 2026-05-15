"""Tests for the Chromium and Firefox history readers.

Each test builds a fixture SQLite DB in `tmp_path` with the same schema the
real browsers use, then asserts the reader yields properly-shaped Event rows
with correctly-converted timestamps.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from personal_timeline.sources import chrome, firefox

# -- Chromium / FILETIME -------------------------------------------------------

def _make_chrome_db(path: Path, rows: list[tuple[int, str, str, int]]) -> None:
    """rows: (visit_id, url, title, unix_ts_seconds)"""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    cur.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
    for visit_id, url, title, unix_ts in rows:
        cur.execute(
            "INSERT OR IGNORE INTO urls (id, url, title) VALUES (?, ?, ?)",
            (visit_id, url, title),
        )
        chrome_us = (unix_ts + 11644473600) * 1_000_000
        cur.execute("INSERT INTO visits VALUES (?, ?, ?)", (visit_id, visit_id, chrome_us))
    conn.commit()
    conn.close()


def test_chrome_filetime_conversion_round_trip():
    unix_ts = 1715000000
    chrome_us = (unix_ts + 11644473600) * 1_000_000
    assert chrome.chrome_us_to_unix_seconds(chrome_us) == unix_ts


def test_chrome_read_events_basic(tmp_path: Path):
    db = tmp_path / "History"
    _make_chrome_db(db, [
        (1, "https://stackoverflow.com/q/jwt", "Stack Overflow", 1715000000),
        (2, "https://github.com", "GitHub", 1715000100),
    ])
    events = list(chrome.read_events(db))
    assert len(events) == 2
    assert [e.source for e in events] == ["chrome", "chrome"]
    assert events[0].ts == 1715000000
    assert events[1].ts == 1715000100
    assert events[0].body == "https://stackoverflow.com/q/jwt"
    assert events[0].source_id == "visit:1"


def test_chrome_since_filter(tmp_path: Path):
    db = tmp_path / "History"
    _make_chrome_db(db, [
        (1, "u1", "t1", 1000),
        (2, "u2", "t2", 2000),
        (3, "u3", "t3", 3000),
    ])
    events = list(chrome.read_events(db, since_ts=1500))
    assert [e.ts for e in events] == [2000, 3000]


def test_chrome_source_name_override(tmp_path: Path):
    db = tmp_path / "History"
    _make_chrome_db(db, [(1, "u", "t", 100)])
    events = list(chrome.read_events(db, source_name="edge"))
    assert events[0].source == "edge"


def test_chrome_read_events_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(chrome.read_events(tmp_path / "nope.db"))


# -- Firefox / PRTime ----------------------------------------------------------

def _make_firefox_db(path: Path, rows: list[tuple[int, str, str, int]]) -> None:
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    cur.execute("CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)")
    for visit_id, url, title, unix_ts in rows:
        cur.execute(
            "INSERT OR IGNORE INTO moz_places (id, url, title) VALUES (?, ?, ?)",
            (visit_id, url, title),
        )
        cur.execute(
            "INSERT INTO moz_historyvisits VALUES (?, ?, ?)",
            (visit_id, visit_id, unix_ts * 1_000_000),
        )
    conn.commit()
    conn.close()


def test_firefox_prtime_conversion_round_trip():
    assert firefox.firefox_us_to_unix_seconds(1715000000 * 1_000_000) == 1715000000


def test_firefox_read_events_basic(tmp_path: Path):
    db = tmp_path / "places.sqlite"
    _make_firefox_db(db, [
        (1, "https://news.ycombinator.com", "Hacker News", 1715000000),
        (2, "https://wikipedia.org", "Wikipedia", 1715000100),
    ])
    events = list(firefox.read_events(db))
    assert len(events) == 2
    assert events[0].source == "firefox"
    assert events[0].ts == 1715000000
    assert events[0].title == "Hacker News"


def test_firefox_since_filter(tmp_path: Path):
    db = tmp_path / "places.sqlite"
    _make_firefox_db(db, [
        (1, "u1", "t1", 1000),
        (2, "u2", "t2", 2000),
    ])
    events = list(firefox.read_events(db, since_ts=1500))
    assert [e.ts for e in events] == [2000]


def test_firefox_read_events_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(firefox.read_events(tmp_path / "nope.sqlite"))


# -- locate_profile (smoke; must not raise on platforms where path missing) ---

def test_locate_profile_does_not_raise():
    # Real result depends on the test runner's machine — just confirm no crash.
    assert chrome.locate_profile() is None or isinstance(chrome.locate_profile(), Path)
    assert firefox.locate_profile() is None or isinstance(firefox.locate_profile(), Path)
