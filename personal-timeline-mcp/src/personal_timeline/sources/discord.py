"""Discord Data Package reader.

Reads a *Discord Data Package* — the export you can request from Discord's
Privacy & Safety settings. Layout:

    <package-root>/
      messages/
        c<channel-id>/
          channel.json   # { id, type, name?, guild? }
          messages.csv   # legacy format (we ignore — superseded by .json)
          messages.json  # array of { ID, Timestamp, Contents, Attachments }
        ...
      servers/
        <guild-id>/...   # we don't read this — channel.json already has guild

Each message becomes one `Event`. Empty-content messages (joins, leaves,
embed-only forwards) are skipped — they aren't useful for "what was I
discussing" correlation.

Public:
    read_events(package_root, *, source_name="discord", since_ts=None)
        -> Iterator[Event]
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)

_CHANNEL_DIR_RE = re.compile(r"^c?\d+$")


def _parse_timestamp(value: str) -> int | None:
    """Discord message timestamps are ISO-8601 like `2026-05-15T12:34:56.789+00:00`.

    Some older exports use `2026-05-15T12:34:56` without timezone — treat
    those as UTC. Returns None on parse failure so the caller can skip the
    message rather than crash.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    # `Z` suffix → +00:00 for datetime.fromisoformat
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        from datetime import UTC

        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def _channel_label(channel_meta: dict, fallback: str) -> str:
    """Best-effort human label for a channel.

    Direct messages (`type == 1`) carry no `name` field; we fall back to the
    `recipients` list there.
    """
    name = channel_meta.get("name")
    if isinstance(name, str) and name.strip():
        return name
    recipients = channel_meta.get("recipients") or []
    if isinstance(recipients, list) and recipients:
        return f"dm:{'+'.join(str(r) for r in recipients[:3])}"
    return fallback


def read_events(
    package_root: str | Path,
    *,
    source_name: str = "discord",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield `Event` rows from a Discord data package."""
    root = Path(package_root).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(root)

    messages_dir = root / "messages"
    if not messages_dir.is_dir():
        # Not a Discord package — surface as no events rather than raise.
        log.debug("No messages/ under %s — skipping", root)
        return

    for channel_dir in sorted(messages_dir.iterdir()):
        if not channel_dir.is_dir() or not _CHANNEL_DIR_RE.match(channel_dir.name):
            continue
        meta_path = channel_dir / "channel.json"
        msgs_path = channel_dir / "messages.json"
        if not msgs_path.is_file():
            continue
        try:
            channel_meta = (
                json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            )
        except (OSError, ValueError):
            channel_meta = {}
        channel_label = _channel_label(channel_meta, channel_dir.name)
        channel_id = channel_meta.get("id") or channel_dir.name.lstrip("c")
        try:
            messages = json.loads(msgs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.debug("Could not parse %s", msgs_path)
            continue
        if not isinstance(messages, list):
            continue

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            ts = _parse_timestamp(msg.get("Timestamp") or "")
            if ts is None:
                continue
            if since_ts is not None and ts < since_ts:
                continue
            contents = msg.get("Contents") or ""
            if not isinstance(contents, str):
                contents = ""
            attachments = msg.get("Attachments") or ""
            # Drop pure-join/leave noise (no contents and no attachments).
            if not contents.strip() and not (isinstance(attachments, str) and attachments.strip()):
                continue
            msg_id = msg.get("ID") or msg.get("id")
            if not isinstance(msg_id, str):
                continue
            yield Event(
                source=source_name,
                source_id=f"{channel_id}:{msg_id}",
                ts=ts,
                title=f"#{channel_label}",
                body=contents[:1000],
                payload={
                    "channel_id": channel_id,
                    "channel_label": channel_label,
                    "message_id": msg_id,
                    "attachments": attachments if isinstance(attachments, str) else "",
                },
            )
