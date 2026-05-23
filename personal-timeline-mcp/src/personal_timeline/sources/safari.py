"""Safari history reader (macOS).

Reads `~/Library/Safari/History.db` (SQLite). Safari, like Chromium, locks the
live DB while the browser is running, so we always copy to a temp file first.

Safari visit timestamps are stored as **CFAbsoluteTime** — seconds since
2001-01-01 00:00:00 UTC, the Cocoa/Mac reference date. We convert to unix
epoch seconds before yielding.

Public:
    locate_profile() -> Path | None
    read_events(history_db_path, *, source_name="safari", since_ts=None) -> Iterator[Event]
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

# CFAbsoluteTime epoch is 2001-01-01 UTC; unix epoch is 1970-01-01.
# Offset in seconds: 31 years incl. 8 leap days.
_COCOA_EPOCH_OFFSET_S = 978307200


def cocoa_seconds_to_unix_seconds(value: float | int) -> int:
    """Convert a Safari CFAbsoluteTime value (seconds since 2001-01-01) to
    unix epoch seconds."""
    return int(float(value) + _COCOA_EPOCH_OFFSET_S)


def locate_profile() -> Path | None:
    """Return Safari's history directory if it exists. macOS only — other
    platforms always return None."""
    if sys.platform != "darwin":
        return None
    expanded = Path(os.path.expanduser("~/Library/Safari"))
    return expanded if expanded.is_dir() else None


def _copy_to_temp(db_path: Path) -> Path:
    """Copy the (potentially locked) DB to a temp file. Close the mkstemp fd
    immediately so we don't leak one per call."""
    fd, name = tempfile.mkstemp(prefix="ptm_safari_", suffix=".db")
    os.close(fd)
    tmp = Path(name)
    shutil.copyfile(db_path, tmp)
    return tmp


def read_events(
    history_db_path: str | Path,
    *,
    source_name: str = "safari",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield `Event` rows from a Safari `History.db`.

    `since_ts` (unix seconds) filters older visits server-side. `source_name`
    is configurable so a caller could route Safari Technology Preview entries
    to a different key.
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
                "SELECT v.id AS visit_id, v.visit_time AS visit_time, "
                "       v.title AS title, i.url AS url "
                "FROM history_visits v JOIN history_items i ON i.id = v.history_item "
            )
            params: list = []
            if since_ts is not None:
                # Safari stores visit_time as a REAL (CFAbsoluteTime). Subtract
                # the offset to convert the unix-seconds filter back to Cocoa.
                params.append(since_ts - _COCOA_EPOCH_OFFSET_S)
                sql += "WHERE v.visit_time >= ? "
            sql += "ORDER BY v.visit_time ASC"
            for row in conn.execute(sql, params):
                ts = cocoa_seconds_to_unix_seconds(row["visit_time"])
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
