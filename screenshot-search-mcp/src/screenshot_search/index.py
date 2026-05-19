"""Directory walker + OCR indexing pipeline.

Public entry: `index_directory(conn, root, recursive=True)` — walks the tree,
dedupes by (path, mtime, size), runs OCR on new/changed images and on PDF
pages (one row per page), upserts rows.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import colors, ocr, pdf, store

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}


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


def iter_pdf_paths(root: Path, *, recursive: bool = True) -> Iterator[Path]:
    """Yield PDF paths under `root`."""
    if recursive:
        walker = root.rglob("*")
    else:
        walker = root.iterdir()
    for path in walker:
        if path.is_file() and path.suffix.lower() in PDF_EXTENSIONS:
            yield path


def _index_pdf(conn, pdf_path: Path, *, skip_ocr: bool = False) -> tuple[int, int]:
    """Rasterize a PDF's pages and upsert one row per page.

    Each page is written to a temp PNG, OCR'd, then upserted with path
    `<pdf>#page=<n>` so the rest of the index treats it like any image.
    Returns (pages_indexed, pages_errored).
    """
    if not pdf.is_available():
        log.info("Skipping %s: pypdfium2 not installed", pdf_path)
        return (0, 0)

    try:
        stat = pdf_path.stat()
    except OSError:
        return (0, 1)

    indexed = 0
    errored = 0
    try:
        for page_idx, pil_image in pdf.render_pages(pdf_path):
            page_key = pdf.make_page_key(pdf_path, page_idx)
            # OCR runs against a real file path (pytesseract opens PIL via PNG
            # round-trip anyway), so write to temp.
            with tempfile.NamedTemporaryFile(
                prefix="sscan_pdfpage_", suffix=".png", delete=False
            ) as f:
                tmp_path = Path(f.name)
            try:
                pil_image.save(tmp_path, "PNG")
                text = "" if skip_ocr else ocr.extract_text(tmp_path)
                page_rgb = colors.dominant_rgb(tmp_path)
            finally:
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
            try:
                store.upsert_image(
                    conn,
                    path=page_key,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    ocr_text=text,
                    dominant_rgb=page_rgb,
                )
                indexed += 1
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Failed to upsert PDF page %s: %s", page_key, exc)
                errored += 1
    except Exception as exc:
        log.warning("Failed to render PDF %s: %s", pdf_path, exc)
        errored += 1
    return (indexed, errored)


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
    include_pdfs: bool = True,
) -> IndexResult:
    """Walk `root`, OCR new/changed images + PDF pages, upsert rows into `conn`.

    Args:
        conn: open SQLite connection from `store.init_db`.
        root: directory to scan.
        recursive: walk subdirectories.
        skip_ocr: useful for tests + bulk metadata refresh — records the file
            without running Tesseract.
        include_pdfs: rasterize and index each page of any PDFs found. Requires
            the `[pdf]` extra (pypdfium2). Silently no-op if it isn't installed.

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
        rgb = colors.dominant_rgb(path)
        try:
            store.upsert_image(
                conn,
                path=path_str,
                mtime=stat.st_mtime,
                size=stat.st_size,
                ocr_text=text,
                dominant_rgb=rgb,
            )
            result.indexed += 1
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Failed to upsert %s: %s", path, exc)
            result.errored += 1

    if include_pdfs:
        for path in iter_pdf_paths(root_path, recursive=recursive):
            result.scanned += 1
            result.last_path = str(path)
            indexed, errored = _index_pdf(conn, path, skip_ocr=skip_ocr)
            result.indexed += indexed
            result.errored += errored

    return result
