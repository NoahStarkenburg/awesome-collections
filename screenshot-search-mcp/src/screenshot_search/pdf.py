"""PDF rasterization for the screenshot index.

Treats each PDF page as a "screenshot" — renders to a PIL image so the
existing OCR + CLIP pipeline can process it without knowing it's a PDF.

Optional dependency: install with `pip install screenshot-search-mcp[pdf]`
to pull in pypdfium2. If the extra isn't installed, `is_available()` returns
False and `render_pages` raises ImportError. Callers should guard accordingly
so a user without PDF support gets a graceful skip, not a crash.

Public:
    is_available() -> bool
    render_pages(pdf_path, *, dpi=150) -> Iterator[(page_index_0based, PIL.Image)]
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def is_available() -> bool:
    """Return True if pypdfium2 is installed and importable."""
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        return False
    return True


def render_pages(pdf_path: str | Path, *, dpi: int = 150) -> Iterator[tuple[int, object]]:
    """Yield (page_index, PIL.Image) tuples for every page in `pdf_path`.

    `page_index` is 0-based to match other internal counters; callers should
    add 1 when surfacing to humans. `dpi` controls the rasterization density
    — 150 is a good OCR/CLIP balance; bump to 300 for fine text.

    Raises ImportError if pypdfium2 isn't installed, FileNotFoundError if
    the file doesn't exist.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ImportError(
            "pypdfium2 not installed. Install the [pdf] extra: "
            "`pip install screenshot-search-mcp[pdf]`"
        ) from exc

    scale = dpi / 72.0
    pdf = pdfium.PdfDocument(str(path))
    try:
        for idx in range(len(pdf)):
            page = pdf[idx]
            try:
                pil_image = page.render(scale=scale).to_pil()
            finally:
                page.close()
            yield idx, pil_image
    finally:
        pdf.close()


def make_page_key(pdf_path: str | Path, page_index: int) -> str:
    """Build the storage key for a PDF page row.

    We reuse the `images.path` column for PDF pages by appending `#page=N` (one-
    based). This keeps the existing schema intact and makes the page-of-pdf
    relationship discoverable to anyone reading raw rows.
    """
    return f"{Path(pdf_path).as_posix()}#page={page_index + 1}"
