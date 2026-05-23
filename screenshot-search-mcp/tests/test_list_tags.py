"""Tests for `list_all_tags` and the matching `list_tags` MCP tool path."""

from __future__ import annotations

from pathlib import Path

import pytest
from screenshot_search import store


@pytest.fixture
def conn(tmp_path: Path):
    c = store.init_db(tmp_path / "test.db")
    yield c
    c.close()


def _seed(conn, fixture: dict[str, list[str]]) -> None:
    """{path: [tags]} -> populated DB."""
    for path, tags in fixture.items():
        image_id = store.upsert_image(conn, path=path, mtime=1.0, size=1)
        store.set_tags(conn, image_id, tags)


def test_list_all_tags_sorted_by_count_desc(conn):
    _seed(
        conn,
        {
            "a.png": ["bug", "ui"],
            "b.png": ["bug"],
            "c.png": ["feature"],
            "d.png": ["bug", "feature"],
        },
    )
    rows = store.list_all_tags(conn)
    # bug appears on 3 images; feature on 2; ui on 1.
    assert rows == [("bug", 3), ("feature", 2), ("ui", 1)]


def test_list_all_tags_min_count_filters_one_offs(conn):
    _seed(conn, {"a.png": ["bug", "typo"], "b.png": ["bug"]})
    rows = store.list_all_tags(conn, min_count=2)
    assert rows == [("bug", 2)]


def test_list_all_tags_limit_caps_result(conn):
    _seed(conn, {f"img{i}.png": [f"tag{i}"] for i in range(10)})
    rows = store.list_all_tags(conn, limit=3)
    assert len(rows) == 3


def test_list_all_tags_empty_db_returns_empty_list(conn):
    assert store.list_all_tags(conn) == []


def test_remove_tags_removes_specific_tags(conn):
    image_id = store.upsert_image(conn, path="a.png", mtime=1.0, size=1)
    store.set_tags(conn, image_id, ["bug", "urgent", "ui"])
    remaining = store.remove_tags(conn, image_id, ["bug", "urgent"])
    assert remaining == ["ui"]


def test_remove_tags_none_clears_all(conn):
    image_id = store.upsert_image(conn, path="a.png", mtime=1.0, size=1)
    store.set_tags(conn, image_id, ["bug", "urgent"])
    remaining = store.remove_tags(conn, image_id, None)
    assert remaining == []


def test_remove_tags_is_case_insensitive(conn):
    image_id = store.upsert_image(conn, path="a.png", mtime=1.0, size=1)
    store.set_tags(conn, image_id, ["Important"])
    # The tag is stored as "important"; remove via mixed case.
    remaining = store.remove_tags(conn, image_id, ["IMPORTANT"])
    assert remaining == []


def test_remove_tags_unknown_is_noop(conn):
    image_id = store.upsert_image(conn, path="a.png", mtime=1.0, size=1)
    store.set_tags(conn, image_id, ["bug"])
    remaining = store.remove_tags(conn, image_id, ["not-a-real-tag"])
    assert remaining == ["bug"]
