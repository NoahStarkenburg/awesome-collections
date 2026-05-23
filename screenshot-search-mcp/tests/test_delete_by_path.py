"""Tests for `delete_by_path_prefix` — the privacy escape hatch."""

from __future__ import annotations

from pathlib import Path

import pytest
from screenshot_search import store


@pytest.fixture
def conn(tmp_path: Path):
    c = store.init_db(tmp_path / "test.db")
    yield c
    c.close()


def _seed(conn, paths: list[str]) -> dict[str, int]:
    """Insert one row per path. Returns {path: image_id}."""
    out = {}
    for i, p in enumerate(paths):
        out[p] = store.upsert_image(conn, path=p, mtime=float(i), size=1)
    return out


def test_delete_by_prefix_drops_matching_rows(conn):
    ids = _seed(
        conn,
        [
            "/home/u/screens/a.png",
            "/home/u/screens/b.png",
            "/home/u/other/c.png",
        ],
    )
    deleted = store.delete_by_path_prefix(conn, "/home/u/screens/")
    assert deleted == 2
    # The /other path survives.
    rows = conn.execute("SELECT path FROM images").fetchall()
    assert [r["path"] for r in rows] == ["/home/u/other/c.png"]
    del ids  # silence unused-var lint


def test_delete_cascades_to_embeddings_and_tags(conn):
    ids = _seed(conn, ["/home/u/a.png"])
    image_id = ids["/home/u/a.png"]
    store.set_embedding(conn, image_id, "test-model", b"\x00" * 16)
    store.set_tags(conn, image_id, ["foo", "bar"])
    store.delete_by_path_prefix(conn, "/home/u/")
    # Embeddings table empty.
    assert conn.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"] == 0
    # Tags table empty.
    assert conn.execute("SELECT COUNT(*) AS c FROM image_tags").fetchone()["c"] == 0


def test_delete_escapes_sql_wildcards(conn):
    """A user path containing `%` should match literally, not as a wildcard."""
    _seed(conn, ["/data/100%/a.png", "/data/foo/b.png"])
    deleted = store.delete_by_path_prefix(conn, "/data/100%/")
    assert deleted == 1
    rows = [r["path"] for r in conn.execute("SELECT path FROM images")]
    assert rows == ["/data/foo/b.png"]


def test_delete_returns_zero_on_no_match(conn):
    _seed(conn, ["/home/u/a.png"])
    deleted = store.delete_by_path_prefix(conn, "/does/not/exist/")
    assert deleted == 0
    # Existing row still present.
    assert conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"] == 1
