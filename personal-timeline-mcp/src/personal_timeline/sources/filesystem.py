"""Filesystem mtime walker.

Walks one or more directories and yields Events for every file inside, capturing
path + mtime + size. Honors an ignore list so we don't drown in `node_modules`.

Public:
    walk(root, *, ignore=None) -> Iterator[FileMeta]
    read_events(root, *, ignore=None) -> Iterator[Event]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..store import Event

log = logging.getLogger(__name__)

DEFAULT_IGNORE = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
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

    for current, dirs, files in _walk(root_path, skip):
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
) -> Iterator[Event]:
    """Yield filesystem Events. `source_id` is the file path so subsequent
    walks dedupe naturally."""
    for meta in walk(root, ignore=ignore):
        yield Event(
            source="fs",
            source_id=meta.path,
            ts=int(meta.mtime),
            title=Path(meta.path).name,
            body=meta.path,
            payload={"path": meta.path, "size": meta.size, "mtime": meta.mtime},
        )
