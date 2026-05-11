"""Tests for the SQLite store. Uses tmp_path so each test gets a fresh DB."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from screenshot_search import store


@pytest.fixture
def conn(tmp_path: Path):
    db = tmp_path / "test.db"
    c = store.init_db(db)
    yield c
    c.close()


def _pack(*floats: float) -> bytes:
    return struct.pack(f"<{len(floats)}f", *floats)


# -- schema + connection -------------------------------------------------------

def test_init_db_creates_expected_tables(tmp_path: Path):
    db = tmp_path / "fresh.db"
    c = store.init_db(db)
    names = {
        r[0]
        for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    # FTS5 creates several shadow tables (images_fts, images_fts_data, etc.)
    assert {"images", "embeddings", "images_fts"} <= names
    c.close()


def test_foreign_keys_enabled(conn):
    cur = conn.execute("PRAGMA foreign_keys").fetchone()
    assert cur[0] == 1


# -- upsert / fetch ------------------------------------------------------------

def test_upsert_image_returns_id(conn):
    row_id = store.upsert_image(
        conn, path="/img/a.png", mtime=1.0, size=10, ocr_text="hello"
    )
    assert row_id == 1


def test_upsert_image_updates_existing(conn):
    a = store.upsert_image(conn, path="/img/a.png", mtime=1.0, size=10, ocr_text="v1")
    b = store.upsert_image(conn, path="/img/a.png", mtime=2.0, size=11, ocr_text="v2")
    assert a == b
    row = store.get_by_path(conn, "/img/a.png")
    assert row["mtime"] == 2.0
    assert row["size"] == 11
    assert row["ocr_text"] == "v2"


def test_upsert_image_preserves_unprovided_fields(conn):
    """COALESCE on update: if sha256 was set once, a later upsert without sha256 keeps it."""
    store.upsert_image(conn, path="/p.png", mtime=1.0, size=1, sha256="abc", ocr_text="t")
    store.upsert_image(conn, path="/p.png", mtime=2.0, size=2)  # no sha256
    row = store.get_by_path(conn, "/p.png")
    assert row["sha256"] == "abc"
    assert row["ocr_text"] == "t"


def test_get_by_path_missing_returns_none(conn):
    assert store.get_by_path(conn, "/does/not/exist.png") is None


def test_list_images_orders_by_mtime_desc(conn):
    store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="x")
    store.upsert_image(conn, path="/b.png", mtime=3.0, size=1, ocr_text="x")
    store.upsert_image(conn, path="/c.png", mtime=2.0, size=1, ocr_text="x")
    paths = [r["path"] for r in store.list_images(conn)]
    assert paths == ["/b.png", "/c.png", "/a.png"]


def test_list_images_since_filter(conn):
    store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="x")
    store.upsert_image(conn, path="/b.png", mtime=3.0, size=1, ocr_text="x")
    paths = [r["path"] for r in store.list_images(conn, since=2.0)]
    assert paths == ["/b.png"]


# -- FTS5 search ---------------------------------------------------------------

def test_search_text_returns_matching_rows(conn):
    store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="auth error dialog")
    store.upsert_image(conn, path="/b.png", mtime=1.0, size=1, ocr_text="rainbow kittens")
    results = store.search_text(conn, "auth")
    assert len(results) == 1
    assert results[0]["path"] == "/a.png"


def test_search_text_empty_query_returns_empty(conn):
    store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="text")
    assert store.search_text(conn, "   ") == []


def test_search_text_respects_since(conn):
    store.upsert_image(conn, path="/old.png", mtime=1.0, size=1, ocr_text="error here")
    store.upsert_image(conn, path="/new.png", mtime=5.0, size=1, ocr_text="error here")
    results = store.search_text(conn, "error", since=3.0)
    assert [r["path"] for r in results] == ["/new.png"]


def test_search_text_updates_index_on_upsert(conn):
    store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="cats")
    store.upsert_image(conn, path="/a.png", mtime=2.0, size=1, ocr_text="dogs")
    # "cats" should no longer match
    assert store.search_text(conn, "cats") == []
    assert len(store.search_text(conn, "dogs")) == 1


# -- embeddings ----------------------------------------------------------------

def test_embedding_round_trip(conn):
    img_id = store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="x")
    blob = _pack(0.1, 0.2, 0.3, 0.4)
    store.set_embedding(conn, img_id, "clip-vitb32", blob)
    assert store.get_embedding(conn, img_id, "clip-vitb32") == blob


def test_embedding_upsert_replaces(conn):
    img_id = store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="x")
    store.set_embedding(conn, img_id, "m", _pack(1.0, 0.0))
    store.set_embedding(conn, img_id, "m", _pack(0.0, 1.0))
    assert store.get_embedding(conn, img_id, "m") == _pack(0.0, 1.0)


def test_nearest_neighbors_ranks_identical_vector_first(conn):
    id_a = store.upsert_image(conn, path="/a.png", mtime=1.0, size=1, ocr_text="x")
    id_b = store.upsert_image(conn, path="/b.png", mtime=1.0, size=1, ocr_text="x")
    store.set_embedding(conn, id_a, "clip", _pack(1.0, 0.0, 0.0, 0.0))
    store.set_embedding(conn, id_b, "clip", _pack(0.0, 1.0, 0.0, 0.0))
    results = store.nearest_neighbors(conn, [1.0, 0.0, 0.0, 0.0], "clip", max_results=2)
    assert results[0][0]["path"] == "/a.png"
    assert results[0][1] == pytest.approx(1.0)


def test_nearest_neighbors_since_filter(conn):
    id_old = store.upsert_image(conn, path="/old.png", mtime=1.0, size=1, ocr_text="x")
    id_new = store.upsert_image(conn, path="/new.png", mtime=10.0, size=1, ocr_text="x")
    store.set_embedding(conn, id_old, "clip", _pack(1.0, 0.0))
    store.set_embedding(conn, id_new, "clip", _pack(0.95, 0.31))
    results = store.nearest_neighbors(
        conn, [1.0, 0.0], "clip", max_results=10, since=5.0
    )
    assert [r["path"] for r, _ in results] == ["/new.png"]


def test_cascade_delete_clears_embeddings(conn):
    img_id = store.upsert_image(conn, path="/gone.png", mtime=1.0, size=1, ocr_text="x")
    store.set_embedding(conn, img_id, "m", _pack(1.0))
    conn.execute("DELETE FROM images WHERE id = ?", (img_id,))
    conn.commit()
    assert store.get_embedding(conn, img_id, "m") is None
