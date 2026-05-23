"""SQLite storage layer for screenshot-search-mcp.

Provides schema management plus a minimal API:
    upsert_image, get_by_path, list_images, search_text, nearest_neighbors,
    set_embedding, get_embedding, set_tags, get_tags, find_by_tag.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT NOT NULL UNIQUE,
    mtime         REAL NOT NULL,
    size          INTEGER NOT NULL,
    sha256        TEXT,
    ocr_text      TEXT,
    dominant_rgb  INTEGER,
    indexed_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime);
CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);

CREATE TABLE IF NOT EXISTS embeddings (
    image_id  INTEGER NOT NULL,
    model     TEXT NOT NULL,
    vector    BLOB NOT NULL,
    PRIMARY KEY (image_id, model),
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS images_fts USING fts5(
    ocr_text,
    content='images',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS images_ai AFTER INSERT ON images BEGIN
    INSERT INTO images_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS images_ad AFTER DELETE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, ocr_text) VALUES('delete', old.id, old.ocr_text);
END;

CREATE TRIGGER IF NOT EXISTS images_au AFTER UPDATE ON images BEGIN
    INSERT INTO images_fts(images_fts, rowid, ocr_text) VALUES('delete', old.id, old.ocr_text);
    INSERT INTO images_fts(rowid, ocr_text) VALUES (new.id, new.ocr_text);
END;

CREATE TABLE IF NOT EXISTS image_tags (
    image_id  INTEGER NOT NULL,
    tag       TEXT NOT NULL,
    PRIMARY KEY (image_id, tag),
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags(tag);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults for this project."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create or open the database and ensure schema is present."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    conn.executescript(SCHEMA_SQL)
    _ensure_columns(conn)
    conn.commit()
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migrations for columns added after v0.1.

    SQLite has no `ALTER TABLE ADD COLUMN IF NOT EXISTS`, so check PRAGMA
    table_info and add what's missing. Old DBs upgrade in place.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(images)")}
    if "dominant_rgb" not in cols:
        conn.execute("ALTER TABLE images ADD COLUMN dominant_rgb INTEGER")


# -- image rows ----------------------------------------------------------------


def upsert_image(
    conn: sqlite3.Connection,
    *,
    path: str,
    mtime: float,
    size: int,
    sha256: str | None = None,
    ocr_text: str | None = None,
    dominant_rgb: int | None = None,
) -> int:
    """Insert or update an image row. Returns the row id."""
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO images (path, mtime, size, sha256, ocr_text, dominant_rgb, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            mtime = excluded.mtime,
            size = excluded.size,
            sha256 = COALESCE(excluded.sha256, images.sha256),
            ocr_text = COALESCE(excluded.ocr_text, images.ocr_text),
            dominant_rgb = COALESCE(excluded.dominant_rgb, images.dominant_rgb),
            indexed_at = excluded.indexed_at
        RETURNING id
        """,
        (path, mtime, size, sha256, ocr_text, dominant_rgb, now),
    )
    row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def set_tags(
    conn: sqlite3.Connection,
    image_id: int,
    tags: Iterable[str],
    *,
    mode: str = "add",
) -> list[str]:
    """Attach `tags` to an image.

    `mode="add"` (default): append, preserving any existing tags.
    `mode="replace"`: drop all existing tags first.

    Tags are normalized (stripped, lowercased). Returns the resulting tag set
    for the image, sorted.
    """
    normalized = sorted({t.strip().lower() for t in tags if t and t.strip()})
    if mode == "replace":
        conn.execute("DELETE FROM image_tags WHERE image_id = ?", (int(image_id),))
    for tag in normalized:
        conn.execute(
            "INSERT OR IGNORE INTO image_tags (image_id, tag) VALUES (?, ?)",
            (int(image_id), tag),
        )
    conn.commit()
    return get_tags(conn, image_id)


def get_tags(conn: sqlite3.Connection, image_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT tag FROM image_tags WHERE image_id = ? ORDER BY tag",
        (int(image_id),),
    ).fetchall()
    return [row["tag"] for row in rows]


def find_by_tag(
    conn: sqlite3.Connection,
    tag: str,
    *,
    since: float | None = None,
    max_results: int = 50,
) -> list[sqlite3.Row]:
    """Return images carrying `tag`. Tag match is exact, case-insensitive."""
    sql = "SELECT i.* FROM images i " "JOIN image_tags t ON t.image_id = i.id " "WHERE t.tag = ? "
    params: list = [tag.strip().lower()]
    if since is not None:
        sql += "AND i.mtime >= ? "
        params.append(since)
    sql += "ORDER BY i.mtime DESC LIMIT ?"
    params.append(int(max_results))
    return conn.execute(sql, params).fetchall()


def search_by_color(
    conn: sqlite3.Connection,
    target_rgb: int,
    *,
    max_results: int = 10,
    tolerance: int = 30,
) -> list[tuple[sqlite3.Row, int]]:
    """Return images whose dominant color is within `tolerance` of `target_rgb`.

    Distance is squared Euclidean in RGB. `tolerance` is the *channel* tolerance
    a human would think in (0-255); we square it for the SQL comparison so the
    user can say e.g. `tolerance=30` and get all colors within ~30 per channel.

    Returns [(row, distance), ...] sorted by closest match.
    """
    from .colors import unpack_rgb

    tr, tg, tb = unpack_rgb(target_rgb)
    # Squared-channel threshold for early filter; final ordering uses the real
    # squared Euclidean distance below.
    sq_threshold = (tolerance * tolerance) * 3
    rows = conn.execute("SELECT * FROM images WHERE dominant_rgb IS NOT NULL").fetchall()
    candidates: list[tuple[sqlite3.Row, int]] = []
    for row in rows:
        rgb = int(row["dominant_rgb"])
        r = (rgb >> 16) & 0xFF
        g = (rgb >> 8) & 0xFF
        b = rgb & 0xFF
        d = (r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2
        if d <= sq_threshold:
            candidates.append((row, d))
    candidates.sort(key=lambda kv: kv[1])
    return candidates[:max_results]


def get_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM images WHERE path = ?", (path,)).fetchone()


def list_images(
    conn: sqlite3.Connection,
    *,
    since: float | None = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    if since is None:
        return conn.execute("SELECT * FROM images ORDER BY mtime DESC LIMIT ?", (limit,)).fetchall()
    return conn.execute(
        "SELECT * FROM images WHERE mtime >= ? ORDER BY mtime DESC LIMIT ?",
        (since, limit),
    ).fetchall()


# -- text search via FTS5 ------------------------------------------------------


def search_text(
    conn: sqlite3.Connection,
    query: str,
    *,
    since: float | None = None,
    max_results: int = 10,
) -> list[sqlite3.Row]:
    """Run an FTS5 query against ocr_text. Falls back to nothing for empty query."""
    if not query.strip():
        return []
    sql = (
        "SELECT i.*, bm25(images_fts) AS score "
        "FROM images_fts "
        "JOIN images i ON i.id = images_fts.rowid "
        "WHERE images_fts MATCH ? "
    )
    params: list = [query]
    if since is not None:
        sql += "AND i.mtime >= ? "
        params.append(since)
    sql += "ORDER BY score LIMIT ?"
    params.append(max_results)
    return conn.execute(sql, params).fetchall()


# -- embeddings ----------------------------------------------------------------


def set_embedding(
    conn: sqlite3.Connection,
    image_id: int,
    model: str,
    vector: bytes,
) -> None:
    conn.execute(
        """
        INSERT INTO embeddings (image_id, model, vector) VALUES (?, ?, ?)
        ON CONFLICT(image_id, model) DO UPDATE SET vector = excluded.vector
        """,
        (image_id, model, vector),
    )
    conn.commit()


def get_embedding(conn: sqlite3.Connection, image_id: int, model: str) -> bytes | None:
    row = conn.execute(
        "SELECT vector FROM embeddings WHERE image_id = ? AND model = ?",
        (image_id, model),
    ).fetchone()
    return None if row is None else bytes(row["vector"])


def iter_embeddings(conn: sqlite3.Connection, model: str) -> Iterable[tuple[int, bytes]]:
    """Yield (image_id, vector_bytes) for every image with an embedding for `model`."""
    for row in conn.execute("SELECT image_id, vector FROM embeddings WHERE model = ?", (model,)):
        yield int(row["image_id"]), bytes(row["vector"])


def nearest_neighbors(
    conn: sqlite3.Connection,
    query_vector: Sequence[float],
    model: str,
    *,
    max_results: int = 10,
    since: float | None = None,
    use_faiss: bool | None = None,
) -> list[tuple[sqlite3.Row, float]]:
    """Cosine-similarity ranking with an optional FAISS fast path.

    `use_faiss`:
      - `None` (default): pick automatically — FAISS when the optional extra
        is installed AND the corpus passes `faiss_search.FAISS_THRESHOLD`.
      - `True`: force FAISS. Raises ImportError if the extra isn't installed.
      - `False`: force the in-Python cosine path. Useful for tests / debugging.

    Both paths return results in identical (row, score) shape.
    """
    from . import faiss_search

    if use_faiss is None:
        if faiss_search.is_available():
            corpus_size = conn.execute(
                "SELECT COUNT(*) AS c FROM embeddings WHERE model = ?",
                (model,),
            ).fetchone()["c"]
            use_faiss = corpus_size >= faiss_search.FAISS_THRESHOLD
        else:
            use_faiss = False

    if use_faiss:
        return faiss_search.search(conn, query_vector, model, max_results=max_results, since=since)

    import math

    q = list(query_vector)
    q_norm = math.sqrt(sum(x * x for x in q)) or 1.0
    q_unit = [x / q_norm for x in q]
    dim = len(q_unit)

    candidates: list[tuple[int, float]] = []
    for image_id, blob in iter_embeddings(conn, model):
        vec = _bytes_to_floats(blob, dim)
        if vec is None:
            continue
        v_norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        score = sum(a * (b / v_norm) for a, b in zip(q_unit, vec, strict=False))
        candidates.append((image_id, score))

    candidates.sort(key=lambda kv: -kv[1])
    out: list[tuple[sqlite3.Row, float]] = []
    for image_id, score in candidates:
        if len(out) >= max_results:
            break
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            continue
        if since is not None and row["mtime"] < since:
            continue
        out.append((row, score))
    return out


def _bytes_to_floats(blob: bytes, dim: int) -> list[float] | None:
    """Decode a float32-packed BLOB. Stdlib-only so tests don't need numpy."""
    import struct

    expected = dim * 4
    if len(blob) != expected:
        return None
    return list(struct.unpack(f"<{dim}f", blob))
