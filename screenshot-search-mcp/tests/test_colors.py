"""Tests for the dominant-color helper and search_by_color store function."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from screenshot_search import colors, store


def test_parse_hex_accepts_with_and_without_hash():
    assert colors.parse_hex("#ff0000") == 0xFF0000
    assert colors.parse_hex("FF0000") == 0xFF0000
    assert colors.parse_hex("  #00FF00  ") == 0x00FF00


def test_parse_hex_rejects_bad_input():
    with pytest.raises(ValueError):
        colors.parse_hex("red")
    with pytest.raises(ValueError):
        colors.parse_hex("#FFF")  # short form not supported in v1


def test_pack_unpack_round_trip():
    packed = colors.pack_rgb(10, 20, 30)
    assert colors.unpack_rgb(packed) == (10, 20, 30)


def test_rgb_distance_zero_for_identical():
    assert colors.rgb_distance(0xFF0000, 0xFF0000) == 0


def test_rgb_distance_grows_with_difference():
    near = colors.rgb_distance(0xFF0000, 0xF00000)
    far = colors.rgb_distance(0xFF0000, 0x00FF00)
    assert near < far


def test_dominant_rgb_solid_color(tmp_path: Path):
    img_path = tmp_path / "red.png"
    Image.new("RGB", (50, 50), color=(255, 0, 0)).save(img_path)
    rgb = colors.dominant_rgb(img_path)
    # Quantization may shift the value slightly but it should be in the red ball.
    assert rgb is not None
    r, g, b = colors.unpack_rgb(rgb)
    assert r > 200 and g < 50 and b < 50


def test_dominant_rgb_returns_none_for_missing_file(tmp_path: Path):
    assert colors.dominant_rgb(tmp_path / "nope.png") is None


def test_dominant_rgb_returns_none_for_corrupt_file(tmp_path: Path):
    corrupt = tmp_path / "broken.png"
    corrupt.write_bytes(b"not actually a png")
    assert colors.dominant_rgb(corrupt) is None


def test_search_by_color_finds_close_matches(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = store.init_db(db)
    try:
        # Three rows: pure red, near-red, pure blue.
        store.upsert_image(conn, path="a.png", mtime=1.0, size=1, dominant_rgb=0xFF0000)
        store.upsert_image(conn, path="b.png", mtime=2.0, size=2, dominant_rgb=0xF00010)
        store.upsert_image(conn, path="c.png", mtime=3.0, size=3, dominant_rgb=0x0000FF)

        # tolerance=30 (per-channel) — should catch red + near-red, exclude blue.
        rows = store.search_by_color(conn, 0xFF0000, tolerance=30)
        paths = [r[0]["path"] for r in rows]
        assert "a.png" in paths
        assert "b.png" in paths
        assert "c.png" not in paths
        # Result ordering: exact match first.
        assert paths[0] == "a.png"
    finally:
        conn.close()


def test_search_by_color_ignores_rows_with_no_color(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = store.init_db(db)
    try:
        store.upsert_image(conn, path="a.png", mtime=1.0, size=1, dominant_rgb=None)
        store.upsert_image(conn, path="b.png", mtime=2.0, size=2, dominant_rgb=0xFF0000)
        rows = store.search_by_color(conn, 0xFF0000, tolerance=30)
        assert [r[0]["path"] for r in rows] == ["b.png"]
    finally:
        conn.close()


def test_search_by_color_max_results_caps_output(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = store.init_db(db)
    try:
        for i in range(5):
            store.upsert_image(
                conn,
                path=f"shot{i}.png",
                mtime=float(i),
                size=i + 1,
                dominant_rgb=0xFF0000,
            )
        rows = store.search_by_color(conn, 0xFF0000, tolerance=30, max_results=3)
        assert len(rows) == 3
    finally:
        conn.close()


def test_init_db_idempotent_migration(tmp_path: Path):
    """Opening an existing DB twice must not error even though the schema's
    `_ensure_columns` runs each time."""
    db = tmp_path / "test.db"
    conn1 = store.init_db(db)
    conn1.close()
    # Reopen — _ensure_columns finds dominant_rgb already present, must no-op.
    conn2 = store.init_db(db)
    conn2.close()
