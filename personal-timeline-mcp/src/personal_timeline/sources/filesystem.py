"""Filesystem mtime walker.

Walks one or more directories and yields Events for every file inside, capturing
path + mtime + size. Honors an ignore list so we don't drown in `node_modules`.

Public:
    walk(root, *, ignore=None) -> Iterator[FileMeta]
    read_events(root, *, ignore=None) -> Iterator[Event]
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)

DEFAULT_IGNORE = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
}


@dataclass
class FileMeta:
    path: str
    mtime: float
    size: int


def walk(
    root: str | Path,
    *,
    ignore: set[str] | None = None,
) -> Iterator[FileMeta]:
    """Yield FileMeta for every file under `root`. Directory names matching
    `ignore` (any segment) are skipped wholesale."""
    skip = set(ignore) if ignore is not None else set(DEFAULT_IGNORE)
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    for current, _dirs, files in _walk(root_path, skip):
        for name in files:
            try:
                p = current / name
                stat = p.stat()
            except OSError as exc:
                log.debug("Cannot stat %s: %s", p, exc)
                continue
            yield FileMeta(path=str(p), mtime=float(stat.st_mtime), size=int(stat.st_size))


def _walk(root: Path, skip: set[str]):
    """Iterate directories filtering out ignored names. Uses os.scandir for speed."""
    import os

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                dirs: list[str] = []
                files: list[str] = []
                for entry in it:
                    name = entry.name
                    if name in skip:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs.append(name)
                            stack.append(current / name)
                        else:
                            files.append(name)
                    except OSError:
                        continue
                yield current, dirs, files
        except OSError as exc:
            log.debug("Cannot scan %s: %s", current, exc)


def read_events(
    root: str | Path,
    *,
    ignore: set[str] | None = None,
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield filesystem Events. `source_id` is the file path so subsequent
    walks dedupe naturally. `since_ts` (unix seconds) filters to files whose
    integer mtime is > the watermark — matches how we serialize event.ts."""
    for meta in walk(root, ignore=ignore):
        ts_int = int(meta.mtime)
        if since_ts is not None and ts_int <= since_ts:
            continue
        yield Event(
            source="fs",
            source_id=meta.path,
            ts=ts_int,
            title=Path(meta.path).name,
            body=meta.path,
            payload={"path": meta.path, "size": meta.size, "mtime": meta.mtime},
        )


def _source_key(root: Path) -> str:
    return f"fs:{root.resolve()}"


def ingest_directory(
    conn,
    root: str | Path,
    *,
    ignore: set[str] | None = None,
) -> dict:
    """Incrementally ingest filesystem state into the events table.

    Uses source_state to remember the highest mtime processed for `root`. Files
    whose mtime is <= the watermark are skipped.

    Returns: {root, ingested, last_event_ts}.
    """
    from .. import store

    root_path = Path(root).expanduser().resolve()
    key = _source_key(root_path)
    state = store.get_source_state(conn, key)
    since: int | None = None
    if state is not None and state.get("last_event_ts") is not None:
        since = int(state["last_event_ts"])

    ingested = 0
    high_water = since
    for event in read_events(root_path, ignore=ignore, since_ts=since):
        store.upsert_event(conn, event)
        ingested += 1
        if high_water is None or event.ts > high_water:
            high_water = event.ts

    if high_water is not None:
        store.update_source_state(conn, key, last_event_ts=int(high_water))
    return {"root": str(root_path), "ingested": ingested, "last_event_ts": high_water}
