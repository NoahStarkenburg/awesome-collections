"""Tests for PDF page indexing.

Generates a fixture multi-page PDF on the fly via PIL (`Image.save(...,
save_all=True, append_images=[...])`) so the test doesn't depend on a binary
PDF blob checked into the repo. pypdfium2 reads it back the same way it would
read any real-world PDF.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from screenshot_search import index, pdf, store


def _make_fixture_pdf(path: Path, n_pages: int = 3) -> Path:
    """Create a minimal PDF with n_pages, each a solid-color tile.

    Tile sizes/colors vary per page so callers can sanity-check ordering.
    """
    pages = [
        Image.new("RGB", (200, 200), color=(255, 0, 0)),
        Image.new("RGB", (200, 200), color=(0, 255, 0)),
        Image.new("RGB", (200, 200), color=(0, 0, 255)),
        Image.new("RGB", (200, 200), color=(200, 200, 200)),
    ][:n_pages]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:])
    return path


@pytest.fixture(autouse=True)
def _skip_if_no_pypdfium2():
    """Hard-skip the whole module if the [pdf] extra isn't installed."""
    if not pdf.is_available():
        pytest.skip("pypdfium2 not installed — install the [pdf] extra to run these tests.")


def test_render_pages_yields_one_image_per_page(tmp_path: Path):
    pdf_path = _make_fixture_pdf(tmp_path / "fixture.pdf", n_pages=3)
    pages = list(pdf.render_pages(pdf_path))
    assert len(pages) == 3
    indices = [i for i, _ in pages]
    assert indices == [0, 1, 2]
    for _, image in pages:
        # rendered images carry size from the rasterizer; should be non-zero.
        assert image.size[0] > 0
        assert image.size[1] > 0


def test_render_pages_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(pdf.render_pages(tmp_path / "nope.pdf"))


def test_make_page_key_one_based():
    """We render with 0-based indexes but surface 1-based pages to humans."""
    assert pdf.make_page_key("/tmp/doc.pdf", 0).endswith("#page=1")
    assert pdf.make_page_key("/tmp/doc.pdf", 4).endswith("#page=5")


def test_index_directory_indexes_each_pdf_page(tmp_path: Path):
    _make_fixture_pdf(tmp_path / "fixture.pdf", n_pages=3)
    db_path = tmp_path / "test.db"
    conn = store.init_db(db_path)
    try:
        result = index.index_directory(conn, tmp_path, skip_ocr=True)
        # 1 file scanned (the PDF) but 3 rows indexed (one per page).
        assert result.scanned == 1
        assert result.indexed == 3
        rows = store.list_images(conn, limit=10)
        keys = sorted(r["path"] for r in rows)
        assert any(k.endswith("#page=1") for k in keys)
        assert any(k.endswith("#page=2") for k in keys)
        assert any(k.endswith("#page=3") for k in keys)
    finally:
        conn.close()


def test_index_directory_can_opt_out_of_pdfs(tmp_path: Path):
    _make_fixture_pdf(tmp_path / "fixture.pdf")
    db_path = tmp_path / "test.db"
    conn = store.init_db(db_path)
    try:
        result = index.index_directory(conn, tmp_path, skip_ocr=True, include_pdfs=False)
        assert result.scanned == 0
        assert result.indexed == 0
    finally:
        conn.close()


def test_index_directory_mixes_pdfs_and_images(tmp_path: Path):
    """A directory with both raster screenshots and PDFs should index both
    in one pass."""
    _make_fixture_pdf(tmp_path / "doc.pdf", n_pages=2)
    Image.new("RGB", (50, 50), color="red").save(tmp_path / "shot.png")

    db_path = tmp_path / "test.db"
    conn = store.init_db(db_path)
    try:
        result = index.index_directory(conn, tmp_path, skip_ocr=True)
        # 1 PNG + 1 PDF (containing 2 pages) — scanned counts files,
        # indexed counts rows (1 image + 2 PDF pages = 3 rows).
        assert result.scanned == 2
        assert result.indexed == 3
    finally:
        conn.close()
