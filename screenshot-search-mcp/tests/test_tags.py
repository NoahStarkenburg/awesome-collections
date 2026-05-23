"""Tests for the user-supplied tag layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from screenshot_search import store


@pytest.fixture
def conn(tmp_path: Path):
    c = store.init_db(tmp_path / "test.db")
    yield c
    c.close()


def _upsert(conn, path: str, mtime: float = 1.0) -> int:
    return store.upsert_image(conn, path=path, mtime=mtime, size=1)


def test_set_tags_normalizes(conn):
    image_id = _upsert(conn, "a.png")
    result = store.set_tags(conn, image_id, ["  Bug  ", "UI", "ui", "", "  "])
    # Whitespace stripped, lowercased, deduped, empties removed.
    assert result == ["bug", "ui"]


def test_set_tags_add_mode_preserves_existing(conn):
    image_id = _upsert(conn, "a.png")
    store.set_tags(conn, image_id, ["bug"])
    store.set_tags(conn, image_id, ["urgent"])
    assert store.get_tags(conn, image_id) == ["bug", "urgent"]


def test_set_tags_replace_mode_clears(conn):
    image_id = _upsert(conn, "a.png")
    store.set_tags(conn, image_id, ["bug", "urgent"])
    store.set_tags(conn, image_id, ["resolved"], mode="replace")
    assert store.get_tags(conn, image_id) == ["resolved"]


def test_find_by_tag_returns_matching_images(conn):
    a = _upsert(conn, "a.png", mtime=10.0)
    b = _upsert(conn, "b.png", mtime=20.0)
    c = _upsert(conn, "c.png", mtime=30.0)
    store.set_tags(conn, a, ["bug"])
    store.set_tags(conn, b, ["feature"])
    store.set_tags(conn, c, ["bug", "urgent"])
    rows = store.find_by_tag(conn, "bug")
    # Newer mtime first, both rows with the bug tag.
    paths = [r["path"] for r in rows]
    assert paths == ["c.png", "a.png"]


def test_find_by_tag_respects_since(conn):
    a = _upsert(conn, "a.png", mtime=100.0)
    b = _upsert(conn, "b.png", mtime=200.0)
    store.set_tags(conn, a, ["bug"])
    store.set_tags(conn, b, ["bug"])
    rows = store.find_by_tag(conn, "bug", since=150.0)
    assert [r["path"] for r in rows] == ["b.png"]


def test_find_by_tag_is_case_insensitive(conn):
    image_id = _upsert(conn, "a.png")
    store.set_tags(conn, image_id, ["Important"])
    rows = store.find_by_tag(conn, "IMPORTANT")
    assert len(rows) == 1


def test_cascading_delete_removes_tags(conn):
    """Deleting an image must wipe its tags via the FK ON DELETE CASCADE."""
    image_id = _upsert(conn, "a.png")
    store.set_tags(conn, image_id, ["bug"])
    conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    conn.commit()
    remaining = conn.execute("SELECT * FROM image_tags WHERE image_id = ?", (image_id,)).fetchall()
    assert remaining == []
