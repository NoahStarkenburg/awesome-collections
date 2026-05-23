"""Notion workspace-export reader.

Reads a *Notion HTML export* — the export you get from Settings & members ->
Export content. Layout (one page per directory):

    <export-root>/
      Page Name abcdef0123456789abcdef0123456789/
        Page Name abcdef0123456789abcdef0123456789.html
        Sub Page deadbeefcafef00ddeadbeefcafef00d/
          Sub Page deadbeefcafef00ddeadbeefcafef00d.html
        Embedded database deadbeef.../
          ...
      ...

Each `.html` file becomes one Event. The 32-char hex hash trailing the
title in Notion's filenames is stripped for a human-readable title; the
hash is preserved in the payload so callers can correlate.

The page's mtime is used as the event timestamp — Notion doesn't reliably
embed last-edited times in the exported HTML, but the file mtime is set
to the page's last-edit time by the exporter.

Public:
    read_events(export_dir, *, source_name="notion", since_ts=None)
        -> Iterator[Event]
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)

# Notion filename hashes are 32 hex chars at the end, separated by a space.
_NOTION_HASH_RE = re.compile(r"^(.*?)[\s_-]([0-9a-fA-F]{32})$")


class _TextExtractor(HTMLParser):
    """Pulls visible text from a Notion-exported HTML page.

    We skip <script>/<style> entirely. The output is whitespace-collapsed
    so an FTS query like `"my project"` lines up with what a human would see.
    """

    SKIP_TAGS = {"script", "style", "head", "title", "meta"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        return " ".join(self._chunks)


def _strip_hash(stem: str) -> tuple[str, str | None]:
    """Split `Page Name abcdef...` into (title, hash). Hash is None when the
    stem doesn't match Notion's `<title>[ _-]<32hex>` convention."""
    m = _NOTION_HASH_RE.match(stem)
    if not m:
        return (stem.strip() or stem, None)
    title = m.group(1).strip()
    return (title or stem, m.group(2).lower())


def _extract_text(html_path: Path) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - html.parser raises odd shapes
        log.debug("HTMLParser failed on %s: %s", html_path, exc)
        return ""
    return parser.text()


def read_events(
    export_dir: str | Path,
    *,
    source_name: str = "notion",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield one `Event` per HTML page in a Notion export."""
    root = Path(export_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(root)

    for html_path in sorted(root.rglob("*.html")):
        try:
            mtime = int(html_path.stat().st_mtime)
        except OSError:
            continue
        if since_ts is not None and mtime < since_ts:
            continue
        title, page_hash = _strip_hash(html_path.stem)
        body = _extract_text(html_path)[:2000]
        relative = html_path.relative_to(root)
        # Source ID prefers the Notion hash for stability across re-exports;
        # falls back to the relative path so re-runs are still idempotent.
        source_id = f"notion:{page_hash}" if page_hash else f"path:{relative.as_posix()}"
        yield Event(
            source=source_name,
            source_id=source_id,
            ts=mtime,
            title=title or "Untitled",
            body=body,
            payload={
                "path": str(html_path),
                "relative_path": relative.as_posix(),
                "page_hash": page_hash,
            },
        )
