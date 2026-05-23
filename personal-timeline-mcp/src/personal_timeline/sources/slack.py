"""Slack workspace-export reader.

Reads a *Slack export* directory — the layout you get from Slack's Settings ->
Workspace Settings -> Export tool. Layout:

    <export-root>/
      users.json                 # workspace-wide user roster
      channels.json              # channel list (optional, not required here)
      <channel-name>/
        2026-05-01.json          # array of messages for that day
        2026-05-02.json
        ...

Each message becomes one `Event`. Non-message records (joins, channel renames,
pinned-message events) are skipped — they aren't useful for "what was I
discussing when I made this commit" correlation.

Public:
    read_events(export_dir, *, source_name="slack", since_ts=None)
        -> Iterator[Event]
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)

# Daily channel files are named `YYYY-MM-DD.json` per Slack's export schema.
_DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def _load_user_map(export_root: Path) -> dict[str, str]:
    """Build a `user_id -> display name` map from `users.json` if present.

    Falls back to using the raw user id when the file is missing or a user
    isn't listed — Slack exports occasionally omit deactivated members.
    """
    users_json = export_root / "users.json"
    if not users_json.is_file():
        return {}
    try:
        data = json.loads(users_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.debug("Could not parse %s", users_json)
        return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, str] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        uid = entry.get("id")
        if not isinstance(uid, str):
            continue
        profile = entry.get("profile") or {}
        # Prefer real_name → display_name → name → id.
        for key in ("real_name", "display_name"):
            value = profile.get(key) if isinstance(profile, dict) else None
            if isinstance(value, str) and value.strip():
                out[uid] = value
                break
        else:
            name = entry.get("name")
            if isinstance(name, str) and name.strip():
                out[uid] = name
    return out


def read_events(
    export_dir: str | Path,
    *,
    source_name: str = "slack",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield `Event` rows from a Slack export tree.

    `since_ts` (unix seconds) filters out older messages — Slack ts strings
    are `"<unix-seconds>.<microseconds>"`, easy to compare numerically.
    """
    root = Path(export_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(root)

    users = _load_user_map(root)

    for channel_dir in sorted(root.iterdir()):
        if not channel_dir.is_dir():
            continue
        channel = channel_dir.name
        for day_file in sorted(channel_dir.iterdir()):
            if not day_file.is_file() or not _DAILY_RE.match(day_file.name):
                continue
            try:
                messages = json.loads(day_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.debug("Could not parse %s", day_file)
                continue
            if not isinstance(messages, list):
                continue
            for msg in messages:
                event = _message_to_event(
                    msg, channel=channel, source_name=source_name, users=users
                )
                if event is None:
                    continue
                if since_ts is not None and event.ts < since_ts:
                    continue
                yield event


def _message_to_event(
    msg: dict,
    *,
    channel: str,
    source_name: str,
    users: dict[str, str],
) -> Event | None:
    if not isinstance(msg, dict):
        return None
    if msg.get("type") != "message":
        return None
    ts_str = msg.get("ts")
    if not isinstance(ts_str, str):
        return None
    try:
        ts = int(float(ts_str))
    except ValueError:
        return None

    user_id = msg.get("user") or msg.get("bot_id") or ""
    user_name = users.get(user_id, user_id) if isinstance(user_id, str) else ""
    text = msg.get("text") or ""
    if not isinstance(text, str):
        text = ""

    title_user = user_name or "unknown"
    title = f"#{channel} · {title_user}"
    return Event(
        source=source_name,
        source_id=f"{channel}:{ts_str}",
        ts=ts,
        title=title,
        body=text[:1000],
        payload={
            "channel": channel,
            "user_id": user_id,
            "user_name": user_name,
            "ts_str": ts_str,
        },
    )
