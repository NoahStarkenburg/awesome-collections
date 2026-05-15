"""Calendar .ics file parser.

A minimal RFC 5545 reader that handles the fields we actually use: SUMMARY,
DESCRIPTION, LOCATION, DTSTART, DTEND, UID. Stdlib-only.

Supports:
    - line unfolding (continuation lines start with space/tab)
    - DTSTART/DTEND with TZID parameter or 'Z' suffix
    - DATE values (no time) treated as midnight UTC
    - multiple VEVENT blocks in one file

Public:
    read_events(ics_path) -> Iterator[Event]
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)


def _unfold(text: str) -> list[str]:
    """Apply RFC 5545 line unfolding (a line starting with space/tab continues
    the prior line)."""
    out: list[str] = []
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _parse_dt(value: str) -> int:
    """Convert an iCal date/datetime string to a unix epoch second.

    Accepts:
        20260513T140000Z          (UTC datetime)
        20260513T140000           (floating local — treated as UTC for v1)
        20260513                  (date — midnight UTC)
    Caller strips any parameters before the colon.
    """
    value = value.strip()
    fmts = ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d")
    for fmt in fmts:
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=UTC)
            return int(dt.timestamp())
        except ValueError:
            continue
    raise ValueError(f"Cannot parse iCal datetime: {value!r}")


def _split_field(line: str) -> tuple[str, str]:
    """Split 'KEY[;PARAM=val]:VALUE' into (KEY_UPPER, VALUE)."""
    key_part, _, value = line.partition(":")
    key = key_part.split(";", 1)[0].upper()
    return key, value


def _unescape(value: str) -> str:
    """Reverse RFC 5545 text escaping (\\n, \\,, \\;, \\\\ )."""
    return (
        value.replace("\\n", "\n")
             .replace("\\N", "\n")
             .replace("\\,", ",")
             .replace("\\;", ";")
             .replace("\\\\", "\\")
    )


def parse_events(text: str) -> list[dict]:
    """Return a list of {uid, summary, description, location, start_ts, end_ts}
    dicts for every VEVENT block in `text`."""
    out: list[dict] = []
    in_event = False
    current: dict = {}
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
            continue
        if line == "END:VEVENT":
            if "start_ts" in current:
                out.append(current)
            in_event = False
            continue
        if not in_event or ":" not in line:
            continue
        key, value = _split_field(line)
        if key == "SUMMARY":
            current["summary"] = _unescape(value)
        elif key == "DESCRIPTION":
            current["description"] = _unescape(value)
        elif key == "LOCATION":
            current["location"] = _unescape(value)
        elif key == "UID":
            current["uid"] = value.strip()
        elif key == "DTSTART":
            try:
                current["start_ts"] = _parse_dt(value)
            except ValueError as exc:
                log.debug("Skipping VEVENT with bad DTSTART: %s", exc)
        elif key == "DTEND":
            try:
                current["end_ts"] = _parse_dt(value)
            except ValueError:
                pass
    return out


def read_events(ics_path: str | Path) -> Iterator[Event]:
    """Yield `Event` rows for every VEVENT in an .ics file."""
    path = Path(ics_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    for entry in parse_events(text):
        uid = entry.get("uid") or f"{path.name}:{entry['start_ts']}:{entry.get('summary','')}"
        body_parts = [entry.get("location", ""), entry.get("description", "")]
        body = " — ".join(p for p in body_parts if p)
        yield Event(
            source="calendar",
            source_id=uid,
            ts=entry["start_ts"],
            end_ts=entry.get("end_ts"),
            title=entry.get("summary", ""),
            body=body,
            payload={
                "uid": uid,
                "summary": entry.get("summary"),
                "description": entry.get("description"),
                "location": entry.get("location"),
                "start_ts": entry["start_ts"],
                "end_ts": entry.get("end_ts"),
                "ics_path": str(path),
            },
        )
