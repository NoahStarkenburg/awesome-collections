"""Tests for `exif.capture_time` and end-to-end captured_at ingestion.

`piexif` is the cleanest way to write EXIF metadata into fixture JPEGs;
it's a [dev]-extras dep, not a production dep. CI runs install only the
production deps, so importorskip here keeps the suite collectible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from screenshot_search import exif, index, store

piexif = pytest.importorskip("piexif")


def _make_image_with_exif(path: Path, datetime_original: str | None = None) -> Path:
    """Save a tiny JPEG. If `datetime_original` is provided, embed it as the
    EXIF DateTimeOriginal field."""
    img = Image.new("RGB", (16, 16), color=(255, 0, 0))
    if datetime_original is not None:
        exif_dict = {"Exif": {piexif.ExifIFD.DateTimeOriginal: datetime_original.encode("ascii")}}
        img.save(path, "JPEG", exif=piexif.dump(exif_dict))
    else:
        img.save(path, "JPEG")
    return path


def test_parse_exif_datetime_round_trip():
    """`2026:05:15 12:34:56` (EXIF) → unix epoch (UTC)."""
    # 2026-05-15T12:34:56 UTC == 1778848496
    assert exif._parse_exif_datetime("2026:05:15 12:34:56") == 1778848496


def test_parse_exif_datetime_rejects_zero_sentinel():
    """EXIF uses `0000:00:00 00:00:00` as 'unset' — must return None."""
    assert exif._parse_exif_datetime("0000:00:00 00:00:00") is None


def test_parse_exif_datetime_rejects_garbage():
    assert exif._parse_exif_datetime("not-a-date") is None
    assert exif._parse_exif_datetime("") is None


def test_capture_time_reads_datetime_original(tmp_path: Path):
    pytest.importorskip("piexif")
    path = _make_image_with_exif(tmp_path / "shot.jpg", "2026:05:15 12:34:56")
    assert exif.capture_time(path) == 1778848496


def test_capture_time_returns_none_when_missing(tmp_path: Path):
    path = _make_image_with_exif(tmp_path / "no_exif.jpg", datetime_original=None)
    assert exif.capture_time(path) is None


def test_capture_time_returns_none_for_missing_file(tmp_path: Path):
    assert exif.capture_time(tmp_path / "nope.jpg") is None


def test_capture_time_handles_corrupt_image(tmp_path: Path):
    corrupt = tmp_path / "broken.jpg"
    corrupt.write_bytes(b"not actually a jpeg")
    assert exif.capture_time(corrupt) is None


def test_index_directory_stores_captured_at(tmp_path: Path):
    pytest.importorskip("piexif")
    _make_image_with_exif(tmp_path / "with_exif.jpg", "2026:05:15 12:34:56")
    _make_image_with_exif(tmp_path / "no_exif.jpg", datetime_original=None)

    conn = store.init_db(tmp_path / "test.db")
    try:
        index.index_directory(conn, tmp_path, skip_ocr=True)
        with_exif = store.get_by_path(conn, str(tmp_path / "with_exif.jpg"))
        no_exif = store.get_by_path(conn, str(tmp_path / "no_exif.jpg"))
        assert with_exif["captured_at"] == 1778848496.0
        # No EXIF → captured_at left null so callers can fall back to mtime.
        assert no_exif["captured_at"] is None
    finally:
        conn.close()


def test_init_db_idempotent_with_captured_at_column(tmp_path: Path):
    """Opening twice must not error — the captured_at migration is idempotent."""
    db = tmp_path / "test.db"
    store.init_db(db).close()
    store.init_db(db).close()
