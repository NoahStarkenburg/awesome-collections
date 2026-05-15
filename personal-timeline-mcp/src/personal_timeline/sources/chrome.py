"""Chromium-family browser history reader.

Reads the `History` SQLite DB from Chrome / Edge / Brave / Arc / Chromium.
Chromium locks the live DB while the browser is running, so we always copy it
to a temp file first.

URL visit timestamps in Chromium are stored as microseconds since 1601-01-01
(the Windows FILETIME epoch). We convert to unix epoch seconds before yielding.

Public:
    locate_profile(browser="chrome") -> Path | None
    read_events(history_db_path, *, since_ts=None) -> Iterator[Event]
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)

# Chromium FILETIME epoch is 1601-01-01 UTC; unix epoch is 1970-01-01.
# Offset in microseconds:
_CHROMIUM_EPOCH_OFFSET_US = 11644473600 * 1_000_000


def chrome_us_to_unix_seconds(value: int) -> int:
    """Convert a Chromium-style microsecond timestamp to unix epoch seconds."""
    return int((value - _CHROMIUM_EPOCH_OFFSET_US) // 1_000_000)


# Default profile paths by platform. Users can override via config.
_PLATFORM_PROFILES: dict[str, dict[str, list[str]]] = {
    "win32": {
        "chrome": [r"%LOCALAPPDATA%\Google\Chrome\User Data\Default"],
        "edge": [r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default"],
        "brave": [r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default"],
    },
    "darwin": {
        "chrome": ["~/Library/Application Support/Google/Chrome/Default"],
        "edge": ["~/Library/Application Support/Microsoft Edge/Default"],
        "brave": ["~/Library/Application Support/BraveSoftware/Brave-Browser/Default"],
    },
    "linux": {
        "chrome": ["~/.config/google-chrome/Default"],
        "edge": ["~/.config/microsoft-edge/Default"],
        "brave": ["~/.config/BraveSoftware/Brave-Browser/Default"],
    },
}


def locate_profile(browser: str = "chrome") -> Path | None:
    """Find the default Chromium profile directory for the running platform."""
    import sys
    table = _PLATFORM_PROFILES.get(sys.platform)
    if not table:
        return None
    for raw in table.get(browser, []):
        expanded = Path(os.path.expandvars(raw)).expanduser()
        if expanded.is_dir():
            return expanded
    return None


def _copy_to_temp(db_path: Path) -> Path:
    """Copy the (potentially locked) DB to a temp file we can safely open."""
    tmp = Path(tempfile.mkstemp(prefix="ptm_chrome_", suffix=".db")[1])
    shutil.copyfile(db_path, tmp)
    return tmp


def read_events(
    history_db_path: str | Path,
    *,
    source_name: str = "chrome",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield `Event` rows from a Chromium History DB.

    `source_name` lets the caller distinguish "chrome", "edge", "brave"
    in the unified index. `since_ts` (unix seconds) filters out older visits
    server-side to keep the working set small on incremental reindexes.
    """
    src = Path(history_db_path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(src)

    tmp = _copy_to_temp(src)
    try:
        conn = sqlite3.connect(str(tmp))
        conn.row_factory = sqlite3.Row
        try:
            sql = (
                "SELECT visits.id AS visit_id, visits.visit_time AS visit_time, "
                "       urls.url AS url, urls.title AS title "
                "FROM visits JOIN urls ON urls.id = visits.url "
            )
            params: list = []
            if since_ts is not None:
                cutoff = (since_ts * 1_000_000) + _CHROMIUM_EPOCH_OFFSET_US
                sql += "WHERE visits.visit_time >= ? "
                params.append(cutoff)
            sql += "ORDER BY visits.visit_time ASC"
            for row in conn.execute(sql, params):
                ts = chrome_us_to_unix_seconds(int(row["visit_time"]))
                yield Event(
                    source=source_name,
                    source_id=f"visit:{row['visit_id']}",
                    ts=ts,
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
