"""Watchdog-based incremental file watcher.

Calls `index.index_directory` on the parent of any image that's created or
modified. Debounces rapid bursts (screenshot tools often write a temp file and
then rename) by waiting `debounce_seconds` after the last event before kicking
the indexer.

Run standalone:
    python -m screenshot_search.watch /path/to/screenshots
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path

from . import index, store

log = logging.getLogger(__name__)


class _DebouncedHandler:
    """Watchdog event handler that batches events per directory."""

    def __init__(self, conn, debounce_seconds: float):
        self.conn = conn
        self.debounce = debounce_seconds
        self._pending: dict[Path, float] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    # FileSystemEventHandler protocol -----------------------------------------

    def dispatch(self, event) -> None:
        if getattr(event, "is_directory", False):
            return
        path = Path(getattr(event, "src_path", "") or getattr(event, "dest_path", ""))
        if not path.suffix or path.suffix.lower() not in index.IMAGE_EXTENSIONS:
            return
        with self._lock:
            self._pending[path.parent] = time.time()
            self._reset_timer_locked()

    # internals ---------------------------------------------------------------

    def _reset_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            dirs = list(self._pending.keys())
            self._pending.clear()
        for directory in dirs:
            try:
                result = index.index_directory(self.conn, directory, recursive=False)
                log.info(
                    "reindexed %s: indexed=%d skipped=%d",
                    directory, result.indexed, result.skipped_unchanged,
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Reindex failed for %s: %s", directory, exc)


def watch(
    root: str | Path,
    db_path: str | Path,
    *,
    recursive: bool = True,
    debounce_seconds: float = 2.0,
):
    """Start watching `root` and reindex on file events. Blocks until interrupted.

    Returns the watchdog Observer so callers can stop it programmatically.
    """
    try:
        from watchdog.observers import Observer  # type: ignore[import-not-found]
        from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "watchdog is required for live watching. Install with: pip install watchdog"
        ) from exc

    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    conn = store.init_db(db_path)
    log.info("Priming index with initial scan of %s …", root_path)
    initial = index.index_directory(conn, root_path, recursive=recursive)
    log.info("Initial scan: %s", initial.as_dict())

    handler_impl = _DebouncedHandler(conn, debounce_seconds)

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            handler_impl.dispatch(event)

    observer = Observer()
    observer.schedule(_Handler(), str(root_path), recursive=recursive)
    observer.start()
    log.info("Watching %s (recursive=%s, debounce=%.1fs) …", root_path, recursive, debounce_seconds)
    return observer


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Watch a directory and reindex on changes.")
    p.add_argument("root", help="directory to watch")
    p.add_argument("--db", default=None, help="SQLite index path (default: ~/.screenshot-search/index.db)")
    p.add_argument("--no-recursive", action="store_true", help="watch root only, no subdirs")
    p.add_argument("--debounce", type=float, default=2.0, help="debounce window in seconds")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    db_path = args.db or str(Path.home() / ".screenshot-search" / "index.db")
    observer = watch(
        args.root, db_path,
        recursive=not args.no_recursive,
        debounce_seconds=args.debounce,
    )
    try:
        while observer.is_alive():
            observer.join(timeout=1.0)
    except KeyboardInterrupt:
        log.info("Stopping watcher …")
        observer.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
