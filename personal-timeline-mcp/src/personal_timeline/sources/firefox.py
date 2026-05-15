"""Firefox places.sqlite history reader.

Firefox stores visit timestamps in `moz_historyvisits.visit_date` as
**microseconds since 1970-01-01** (PRTime µs) — a different epoch from
Chromium's FILETIME. Same locking gotcha though: copy the DB to temp first.

Public:
    locate_profile() -> Path | None
    read_events(places_db_path, *, since_ts=None) -> Iterator[Event]
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)


def firefox_us_to_unix_seconds(value: int) -> int:
    """Convert a Firefox PRTime µs timestamp to unix epoch seconds."""
    return int(value // 1_000_000)


_PROFILES_INI_BY_PLATFORM = {
    "win32": [r"%APPDATA%\Mozilla\Firefox\profiles.ini"],
    "darwin": ["~/Library/Application Support/Firefox/profiles.ini"],
    "linux": ["~/.mozilla/firefox/profiles.ini"],
}


def locate_profile() -> Path | None:
    """Best-effort find of the default Firefox profile directory."""
    candidates = _PROFILES_INI_BY_PLATFORM.get(sys.platform, [])
    for raw in candidates:
        ini = Path(os.path.expandvars(raw)).expanduser()
        if not ini.is_file():
            continue
        # parse profiles.ini just enough to find the default
        import configparser

        parser = configparser.ConfigParser()
        parser.read(ini)
        # The default profile is the section with Default=1, or fall back to
        # whichever Profile section has the most recent atime — too fiddly for v1.
        for section in parser.sections():
            if parser[section].get("Default") == "1":
                rel = parser[section].get("Path", "")
                is_relative = parser[section].get("IsRelative", "1") != "0"
                base = ini.parent if is_relative else Path("/")
                profile = (base / rel).resolve()
                if profile.is_dir():
                    return profile
    return None


def _copy_to_temp(db_path: Path) -> Path:
    tmp = Path(tempfile.mkstemp(prefix="ptm_firefox_", suffix=".sqlite")[1])
    shutil.copyfile(db_path, tmp)
    return tmp


def read_events(
    places_db_path: str | Path,
    *,
    source_name: str = "firefox",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield `Event` rows from a Firefox `places.sqlite`."""
    src = Path(places_db_path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(src)

    tmp = _copy_to_temp(src)
    try:
        conn = sqlite3.connect(str(tmp))
        conn.row_factory = sqlite3.Row
        try:
            sql = (
                "SELECT v.id AS visit_id, v.visit_date AS visit_date, "
                "       p.url AS url, p.title AS title "
                "FROM moz_historyvisits v JOIN moz_places p ON p.id = v.place_id "
            )
            params: list = []
            if since_ts is not None:
                sql += "WHERE v.visit_date >= ? "
                params.append(since_ts * 1_000_000)
            sql += "ORDER BY v.visit_date ASC"
            for row in conn.execute(sql, params):
                yield Event(
                    source=source_name,
                    source_id=f"visit:{row['visit_id']}",
                    ts=firefox_us_to_unix_seconds(int(row["visit_date"])),
                    title=row["title"] or row["url"],
                    body=row["url"],
                    payload={"url": row["url"], "title": row["title"]},
                )
        finally:
            conn.close()
    finally:
        try:
            tmp.unlink()
        except OSError:
            log.debug("Could not remove temp DB %s", tmp)
