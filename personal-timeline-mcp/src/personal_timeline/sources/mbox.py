"""mbox (Unix mail archive) reader.

Reads any `.mbox` file via the stdlib `mailbox` module and emits one Event
per message. Useful for indexing personal email exports — Gmail Takeout,
Apple Mail export, mutt archives, etc. all hand you .mbox files.

We don't attempt to decode attachments or HTML bodies — the v1 use case is
"what was I emailing when I made this commit?", and subject+from+text is
enough for FTS matching.

Public:
    read_events(mbox_path, *, source_name="mbox", since_ts=None)
        -> Iterator[Event]
"""

from __future__ import annotations

import logging
import mailbox
from collections.abc import Iterator
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)


def _header(message: mailbox.mboxMessage, name: str) -> str:
    value = message.get(name)
    if value is None:
        return ""
    return str(value).strip()


def _date_to_ts(date_header: str) -> int | None:
    """RFC 2822 Date header -> unix epoch seconds. Returns None on parse fail."""
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return int(dt.timestamp())


def _plain_text_body(message: mailbox.mboxMessage) -> str:
    """Pull the first text/plain part — never decode HTML.

    Multi-part messages are common; only the leaf parts have payloads. We
    walk and pick the first `text/plain` we see. If there isn't one, we
    fall back to `get_payload(decode=True)` for single-part messages and
    return whatever string we can recover.
    """
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True) or b""
                except Exception:  # noqa: BLE001 - email package raises odd shapes
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    return payload.decode("utf-8", errors="replace")
        return ""
    try:
        payload = message.get_payload(decode=True)
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        return payload
    return ""


def read_events(
    mbox_path: str | Path,
    *,
    source_name: str = "mbox",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield `Event` rows from a `.mbox` file.

    `since_ts` (unix seconds) drops older messages. Messages without a
    parseable Date header are skipped — without a timestamp they have no
    place on the timeline.
    """
    path = Path(mbox_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)

    box = mailbox.mbox(str(path))
    try:
        for key, message in box.iteritems():
            ts = _date_to_ts(_header(message, "Date"))
            if ts is None:
                continue
            if since_ts is not None and ts < since_ts:
                continue
            subject = _header(message, "Subject") or "(no subject)"
            sender = _header(message, "From") or "(unknown sender)"
            message_id = _header(message, "Message-ID") or f"mbox:{key}"
            body = _plain_text_body(message)[:2000]
            yield Event(
                source=source_name,
                source_id=message_id,
                ts=ts,
                title=subject,
                body=body,
                payload={
                    "from": sender,
                    "to": _header(message, "To"),
                    "cc": _header(message, "Cc"),
                    "subject": subject,
                    "message_id": message_id,
                },
            )
    finally:
        box.close()
