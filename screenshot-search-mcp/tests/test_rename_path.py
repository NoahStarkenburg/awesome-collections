"""Tests for `store.rename_path`."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest
from screenshot_search import store


@pytest.fixture
def conn(tmp_path: Path):
    c = store.init_db(tmp_path / "test.db")
    yield c
    c.close()


def test_rename_path_updates_existing_row(conn):
    image_id = store.upsert_image(conn, path="/a/old.png", mtime=1.0, size=1)
    status = store.rename_path(conn, "/a/old.png", "/b/new.png")
    assert status == "renamed"
    # Same id, new path — the row was updated, not re-inserted.
    row = store.get_by_path(conn, "/b/new.png")
    assert row is not None
    assert row["id"] == image_id
    assert store.get_by_path(conn, "/a/old.png") is None


def test_rename_path_preserves_embeddings_and_tags(conn):
    image_id = store.upsert_image(conn, path="/a/old.png", mtime=1.0, size=1)
    store.set_embedding(conn, image_id, "test-model", struct.pack("<4f", 1.0, 0, 0, 0))
    store.set_tags(conn, image_id, ["bug"])

    store.rename_path(conn, "/a/old.png", "/b/new.png")

    # Embedding still attached to the same row id.
    assert store.get_embedding(conn, image_id, "test-model") is not None
    # Tags survive the rename.
    assert store.get_tags(conn, image_id) == ["bug"]


def test_rename_path_returns_missing_when_old_path_unknown(conn):
    status = store.rename_path(conn, "/nope.png", "/somewhere/else.png")
    assert status == "missing"


def test_rename_path_returns_conflict_when_new_path_taken(conn):
    store.upsert_image(conn, path="/a/old.png", mtime=1.0, size=1)
    store.upsert_image(conn, path="/b/taken.png", mtime=2.0, size=2)
    status = store.rename_path(conn, "/a/old.png", "/b/taken.png")
    assert status == "conflict"
    # Both rows survive unchanged.
    assert store.get_by_path(conn, "/a/old.png") is not None
    assert store.get_by_path(conn, "/b/taken.png") is not None


def test_rename_path_to_self_is_a_renamed_noop(conn):
    """Renaming a row to its current path is allowed — the conflict check
    explicitly excludes the same-row case so a re-run is idempotent."""
    store.upsert_image(conn, path="/a/x.png", mtime=1.0, size=1)
    status = store.rename_path(conn, "/a/x.png", "/a/x.png")
    assert status == "renamed"
