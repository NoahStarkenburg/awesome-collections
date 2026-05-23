"""Tests for the max_bytes index filter."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from screenshot_search import config, index, store


def _make_image(path: Path, color, size=(20, 20)) -> int:
    """Write a tiny PNG and return its on-disk size in bytes."""
    Image.new("RGB", size, color=color).save(path)
    return path.stat().st_size


def test_max_bytes_zero_means_no_limit(tmp_path: Path):
    """The 0 sentinel disables the size filter."""
    db = tmp_path / "test.db"
    conn = store.init_db(db)
    try:
        _make_image(tmp_path / "small.png", (255, 0, 0))
        result = index.index_directory(conn, tmp_path, skip_ocr=True, max_bytes=0)
        assert result.indexed == 1
        assert result.skipped_too_large == 0
    finally:
        conn.close()


def test_max_bytes_filters_oversize(tmp_path: Path):
    """Files larger than max_bytes are skipped, with `skipped_too_large` bumped."""
    db = tmp_path / "test.db"
    conn = store.init_db(db)
    try:
        # Two PNGs; "small" stays under, "big" goes over a tight threshold.
        size_small = _make_image(tmp_path / "small.png", (255, 0, 0), size=(10, 10))
        size_big = _make_image(tmp_path / "big.png", (0, 255, 0), size=(800, 800))
        threshold = (size_small + size_big) // 2
        result = index.index_directory(conn, tmp_path, skip_ocr=True, max_bytes=threshold)
        assert result.indexed == 1
        assert result.skipped_too_large == 1
        # And the small one made it into the store.
        rows = store.list_images(conn, limit=10)
        assert [Path(r["path"]).name for r in rows] == ["small.png"]
    finally:
        conn.close()


def test_config_default_max_index_bytes_is_50_mb():
    cfg = config.Config.defaults()
    assert cfg.max_index_bytes == 50 * 1024 * 1024


def test_config_loads_custom_max_index_bytes(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("max_index_bytes = 1024\n", encoding="utf-8")
    cfg = config.load(cfg_file)
    assert cfg.max_index_bytes == 1024


def test_config_rejects_negative_max_index_bytes(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("max_index_bytes = -1\n", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="non-negative"):
        config.load(cfg_file)
