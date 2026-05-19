"""Tests for the FAISS-backed nearest-neighbors fast path.

Confirms:
- `is_available()` does not crash regardless of whether faiss is installed.
- When forced via `use_faiss=True` and faiss IS installed, the path returns
  the same top-1 result as the in-Python cosine path for a small fixture.
- When forced via `use_faiss=True` and faiss is NOT installed, the caller
  gets ImportError (no silent fallback to an unrelated path).
- The auto-dispatch logic picks the right branch based on corpus size +
  availability.
"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from screenshot_search import faiss_search, store


def _pack(vec):
    return struct.pack(f"<{len(vec)}f", *vec)


@pytest.fixture
def seeded_db(tmp_path: Path):
    """Seed a DB with 4 vectors in a 4-dimensional space.

    Vectors are designed so a query (1,0,0,0) clearly ranks them red→blue.
    """
    db = tmp_path / "test.db"
    conn = store.init_db(db)
    rows = [
        ("red.png", [1.0, 0.0, 0.0, 0.0]),
        ("near-red.png", [0.9, 0.1, 0.05, 0.0]),
        ("green.png", [0.0, 1.0, 0.0, 0.0]),
        ("blue.png", [0.0, 0.0, 1.0, 0.0]),
    ]
    for path, vec in rows:
        image_id = store.upsert_image(conn, path=path, mtime=1.0, size=10)
        store.set_embedding(conn, image_id, "test-model", _pack(vec))
    yield conn
    conn.close()


def test_is_available_returns_bool():
    """The result depends on the env, but it must always be a bool, never
    crash on import."""
    assert isinstance(faiss_search.is_available(), bool)


@pytest.mark.skipif(not faiss_search.is_available(), reason="faiss not installed")
def test_faiss_path_matches_in_python_top_result(seeded_db):
    """Both paths should rank `red.png` first for a `(1,0,0,0)` query."""
    q = [1.0, 0.0, 0.0, 0.0]
    py_path = store.nearest_neighbors(seeded_db, q, "test-model", max_results=4, use_faiss=False)
    faiss_path = store.nearest_neighbors(seeded_db, q, "test-model", max_results=4, use_faiss=True)
    assert py_path[0][0]["path"] == "red.png"
    assert faiss_path[0][0]["path"] == "red.png"
    # Top-2 should also match for this clean fixture.
    assert {r[0]["path"] for r in py_path[:2]} == {r[0]["path"] for r in faiss_path[:2]}


@pytest.mark.skipif(not faiss_search.is_available(), reason="faiss not installed")
def test_faiss_path_respects_since_filter(seeded_db):
    """Bump one row's mtime forward; ask for since=that value; only it survives."""
    seeded_db.execute("UPDATE images SET mtime = ? WHERE path = ?", (5000.0, "near-red.png"))
    seeded_db.commit()
    q = [1.0, 0.0, 0.0, 0.0]
    results = store.nearest_neighbors(seeded_db, q, "test-model", since=4000.0, use_faiss=True)
    paths = [r[0]["path"] for r in results]
    assert paths == ["near-red.png"]


def test_use_faiss_true_without_extra_raises(seeded_db, monkeypatch):
    """If a caller insists on FAISS but the extra is missing, give them an
    explicit ImportError — never silently fall back to a different algorithm
    when they explicitly asked for one."""
    monkeypatch.setattr(faiss_search, "is_available", lambda: True)

    def fake_search(*_args, **_kwargs):
        raise ImportError("simulated missing faiss")

    monkeypatch.setattr(faiss_search, "search", fake_search)

    with pytest.raises(ImportError, match="simulated missing faiss"):
        store.nearest_neighbors(seeded_db, [1.0, 0, 0, 0], "test-model", use_faiss=True)


def test_auto_dispatch_uses_in_python_when_corpus_below_threshold(seeded_db):
    """Auto mode: 4 rows are well below the default FAISS_THRESHOLD (1000),
    so the in-Python path should run even when faiss is available. We assert
    that by checking the faiss_search.search is NOT called."""
    with patch.object(faiss_search, "search") as mock_search:
        store.nearest_neighbors(seeded_db, [1.0, 0, 0, 0], "test-model", use_faiss=None)
        mock_search.assert_not_called()


def test_auto_dispatch_uses_faiss_when_corpus_above_threshold(seeded_db):
    """Auto mode: drop the threshold so 4 rows triggers FAISS. Confirm the
    delegation happens (we don't need the call to do real work — just to fire)."""
    with (
        patch.object(faiss_search, "FAISS_THRESHOLD", 2),
        patch.object(faiss_search, "is_available", return_value=True),
        patch.object(faiss_search, "search", return_value=[]) as mock_search,
    ):
        store.nearest_neighbors(seeded_db, [1.0, 0, 0, 0], "test-model", use_faiss=None)
        mock_search.assert_called_once()


def test_auto_dispatch_skips_faiss_when_unavailable(seeded_db):
    """Auto mode with FAISS unavailable: must NOT call faiss_search.search even
    if the corpus would otherwise meet the threshold."""
    with (
        patch.object(faiss_search, "FAISS_THRESHOLD", 1),
        patch.object(faiss_search, "is_available", return_value=False),
        patch.object(faiss_search, "search") as mock_search,
    ):
        store.nearest_neighbors(seeded_db, [1.0, 0, 0, 0], "test-model", use_faiss=None)
        mock_search.assert_not_called()
