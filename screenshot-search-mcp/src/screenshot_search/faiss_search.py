"""FAISS-backed nearest-neighbor search with a graceful fallback.

The default in-`store.py` `nearest_neighbors` ranks via in-Python cosine. That
works fine into the tens of thousands of vectors, but degrades linearly. This
module wires up FAISS's `IndexFlatIP` (inner-product over L2-normalized
vectors == cosine) when the optional `[faiss]` extra is installed.

Public:
    is_available() -> bool
    search(conn, query_vector, model, *, max_results=10, since=None)
        -> list[(sqlite3.Row, float)]

The caller usually doesn't reach for this module directly — `store.nearest_neighbors`
delegates here automatically when FAISS is present and the corpus exceeds
`FAISS_THRESHOLD`. Tests can also force the path via `use_faiss=True`.
"""

from __future__ import annotations

import logging
import math
import struct
from functools import lru_cache

log = logging.getLogger(__name__)

FAISS_THRESHOLD = 1000


@lru_cache(maxsize=1)
def is_available() -> bool:
    """Return True if `faiss-cpu` (or `faiss-gpu`) is importable."""
    try:
        import faiss  # noqa: F401
    except ImportError:
        return False
    return True


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _bytes_to_floats(blob: bytes, dim: int) -> list[float] | None:
    if len(blob) != dim * 4:
        return None
    return list(struct.unpack(f"<{dim}f", blob))


def search(
    conn,
    query_vector,
    model: str,
    *,
    max_results: int = 10,
    since: float | None = None,
):
    """Run an inner-product cosine search via FAISS. Raises ImportError if the
    optional extra isn't installed — callers should check `is_available()` or
    rely on `store.nearest_neighbors` to make the call.
    """
    try:
        import faiss
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised via is_available()
        raise ImportError("faiss-cpu / numpy not installed; install the [faiss] extra") from exc

    q = _normalize(list(query_vector))
    dim = len(q)

    # Load every (image_id, vec) and normalize. FAISS expects float32 row-major.
    ids: list[int] = []
    rows: list[list[float]] = []
    for row in conn.execute(
        "SELECT image_id, vector FROM embeddings WHERE model = ?",
        (model,),
    ):
        vec = _bytes_to_floats(bytes(row["vector"]), dim)
        if vec is None:
            continue
        ids.append(int(row["image_id"]))
        rows.append(_normalize(vec))

    if not rows:
        return []

    xb = np.array(rows, dtype="float32")
    index = faiss.IndexFlatIP(dim)
    index.add(xb)

    xq = np.array([q], dtype="float32")
    # Search a wider candidate window so the `since` filter has options to
    # discard rows from. 4x is a small overhead; falls back to k if smaller.
    k = min(max(max_results * 4, max_results), len(rows))
    scores, indices = index.search(xq, k)

    out: list[tuple[object, float]] = []
    for rank in range(indices.shape[1]):
        pos = int(indices[0, rank])
        if pos < 0:
            continue
        image_id = ids[pos]
        score = float(scores[0, rank])
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            continue
        if since is not None and float(row["mtime"]) < since:
            continue
        out.append((row, score))
        if len(out) >= max_results:
            break
    return out
