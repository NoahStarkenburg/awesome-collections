"""Directory walker + OCR indexing pipeline.

Public entry: `index_directory(conn, root, recursive=True)` — walks the tree,
dedupes by (path, mtime, size), runs OCR on new/changed images, upserts rows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import ocr, store

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


@dataclass
class IndexResult:
    scanned: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    skipped_unsupported: int = 0
    errored: int = 0
    last_path: str | None = None

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "indexed": self.indexed,
            "skipped_unchanged": self.skipped_unchanged,
            "skipped_unsupported": self.skipped_unsupported,
            "errored": self.errored,
            "last_path": self.last_path,
        }


def iter_image_paths(root: Path, *, recursive: bool = True) -> Iterator[Path]:
    """Yield image paths under `root`, filtered by extension."""
    if recursive:
        walker = root.rglob("*")
    else:
        walker = root.iterdir()
    for path in walker:
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def _is_unchanged(conn, path: str, mtime: float, size: int) -> bool:
    row = store.get_by_path(conn, path)
    if row is None:
        return False
    return float(row["mtime"]) == mtime and int(row["size"]) == size


def index_directory(
    conn,
    root: str | Path,
    *,
    recursive: bool = True,
    skip_ocr: bool = False,
) -> IndexResult:
    """Walk `root`, OCR new/changed images, upsert rows into `conn`.

    Args:
        conn: open SQLite connection from `store.init_db`.
        root: directory to scan.
        recursive: walk subdirectories.
        skip_ocr: useful for tests + bulk metadata refresh — records the file
            without running Tesseract.

    Returns an `IndexResult` summary.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)

    result = IndexResult()
    for path in iter_image_paths(root_path, recursive=recursive):
        result.scanned += 1
        result.last_path = str(path)
        try:
            stat = path.stat()
        except OSError as exc:
            log.debug("Cannot stat %s: %s", path, exc)
            result.errored += 1
            continue

        path_str = str(path)
        if _is_unchanged(conn, path_str, stat.st_mtime, stat.st_size):
            result.skipped_unchanged += 1
            continue

        text = "" if skip_ocr else ocr.extract_text(path)
        try:
            store.upsert_image(
                conn,
                path=path_str,
                mtime=stat.st_mtime,
                size=stat.st_size,
                ocr_text=text,
            )
            result.indexed += 1
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Failed to upsert %s: %s", path, exc)
            result.errored += 1

    return result
