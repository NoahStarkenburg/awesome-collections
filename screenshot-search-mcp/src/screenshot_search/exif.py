"""EXIF capture-time extraction.

`capture_time(image_path)` returns the photo's `DateTimeOriginal` as unix
epoch seconds, or None if the field is missing / unreadable / not a real
date. Most screenshots don't carry EXIF; real camera images and many
phone screenshots do. When present, this is a far better timeline anchor
than the filesystem mtime (which moves whenever the file is touched).

Pillow only — no piexif or exifread dependency.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

# EXIF tag id for DateTimeOriginal — the "when the shutter clicked" field.
_DATETIME_ORIGINAL = 36867
# DateTime (last-modified) — fallback when Original is missing.
_DATETIME = 306


def _parse_exif_datetime(value: str) -> int | None:
    """EXIF datetimes are `YYYY:MM:DD HH:MM:SS` (yes, colons in the date part).

    We treat the value as UTC — EXIF doesn't specify a tz, and most cameras
    write local time without offset. For "what was I doing when" workflows
    UTC vs local within ~12h doesn't change the answer.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # EXIF uses `0000:00:00 00:00:00` as a sentinel for "unset".
    if text.startswith("0000"):
        return None
    try:
        dt = datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return int(dt.replace(tzinfo=UTC).timestamp())


def capture_time(image_path: str | Path) -> int | None:
    """Return DateTimeOriginal (or DateTime fallback) as unix seconds.

    Returns None for: missing file, no EXIF, unparseable timestamp, or
    when Pillow raises. Never raises — callers can pipe the result
    straight into `upsert_image(..., captured_at=...)`.
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover - Pillow is a hard dep
        return None

    path = Path(image_path)
    if not path.is_file():
        return None

    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except (UnidentifiedImageError, OSError) as exc:
        log.debug("Cannot read EXIF from %s: %s", path, exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("EXIF read failed for %s: %s", path, exc)
        return None

    if not exif:
        return None

    # DateTimeOriginal lives in the Exif sub-IFD (tag 0x8769), not the
    # top-level IFD0. Walk both: prefer DateTimeOriginal from the sub-IFD,
    # then fall back to DateTime (last-modified) in IFD0.
    exif_ifd = {}
    try:
        exif_ifd = exif.get_ifd(0x8769)
    except Exception:  # noqa: BLE001 — Pillow raises odd shapes on partial EXIF
        exif_ifd = {}

    candidates = (
        (exif_ifd, _DATETIME_ORIGINAL),
        (exif, _DATETIME_ORIGINAL),  # some encoders write it at IFD0 anyway
        (exif, _DATETIME),
    )
    for source, tag in candidates:
        value = source.get(tag) if source else None
        if value is None:
            continue
        ts = _parse_exif_datetime(value if isinstance(value, str) else str(value))
        if ts is not None:
            return ts
    return None
