"""FastMCP server entry point.

Run during development with:
    fastmcp dev src/screenshot_search/server.py

Run for clients (Claude Desktop, Cursor, etc.) via stdio:
    python -m screenshot_search.server

The server keeps one SQLite connection alive for the process lifetime. The DB
path defaults to `~/.screenshot-search/index.db` and can be overridden with
the `SCREENSHOT_SEARCH_DB` env var.
"""

from __future__ import annotations

import os
import platform
import sys
import threading
import time
from datetime import UTC
from pathlib import Path

from fastmcp import FastMCP

from . import __version__, clip, colors, config, index, ocr, store

mcp = FastMCP(
    name="screenshot-search",
    instructions=(
        "Index and search screenshots by OCR text (Tesseract) and visual content "
        "(CLIP). Call `index_directory(path)` first to populate the index, then "
        "`search_text(query)` or `search_visual(query)`."
    ),
)


def _db_path() -> Path:
    override = os.environ.get("SCREENSHOT_SEARCH_DB")
    if override:
        return Path(override)
    return Path.home() / ".screenshot-search" / "index.db"


_conn_lock = threading.Lock()
_conn = None
_last_result: dict | None = None


def _get_conn():
    global _conn
    with _conn_lock:
        if _conn is None:
            _conn = store.init_db(_db_path())
        return _conn


@mcp.tool()
def ping() -> dict:
    """Health check. Returns server version, Python version, and current time.

    Use this first when wiring up a new client to confirm the server is reachable.
    """
    return {
        "server": "screenshot-search-mcp",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "ok",
    }


@mcp.tool()
def index_status() -> dict:
    """Report current index state: total rows, embedding count, last index run.

    Use this to confirm what's actually been indexed before running searches.
    """
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    embedded = conn.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"]
    last = conn.execute(
        "SELECT path, indexed_at FROM images ORDER BY indexed_at DESC LIMIT 1"
    ).fetchone()
    return {
        "db_path": str(_db_path()),
        "total_images": int(total),
        "total_embeddings": int(embedded),
        "last_indexed_path": None if last is None else last["path"],
        "last_indexed_at": None if last is None else float(last["indexed_at"]),
        "last_run": _last_result,
    }


@mcp.tool()
def index_directory(
    path: str,
    recursive: bool = True,
    ocr_languages: list[str] | None = None,
) -> dict:
    """Scan a directory for images and OCR-index any new or changed files.

    Args:
        path: directory to scan (absolute or expandable).
        recursive: walk subdirectories. Defaults to true.
        ocr_languages: optional list of ISO 639-2 codes (e.g. ["eng", "spa"]).
            Overrides the value from config.toml's `ocr_languages`. If both
            are absent, defaults to ["eng"]. Each language listed must have a
            matching Tesseract language pack installed.

    Returns a summary dict: scanned, indexed, skipped_unchanged, errored,
    last_path, ocr_lang. Call this before `search_text` / `search_visual`.
    """
    global _last_result
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        return {"error": f"Not a directory: {target}"}

    if ocr_languages:
        ocr_lang = "+".join(ocr_languages)
    else:
        ocr_lang = config.load().tesseract_lang()

    conn = _get_conn()
    result = index.index_directory(conn, target, recursive=recursive, ocr_lang=ocr_lang)
    payload = result.as_dict()
    payload["root"] = str(target)
    payload["ocr_lang"] = ocr_lang
    _last_result = payload
    return payload


@mcp.tool()
def search_text(query: str, since: str | None = None, max_results: int = 10) -> dict:
    """Full-text search the OCR'd text of indexed screenshots.

    Args:
        query: FTS5 query string. Plain words work; quote phrases for exact match.
        since: optional ISO-8601 timestamp or epoch seconds — restrict to files
            modified after this time. Examples: "2026-04-01", "1714521600".
        max_results: cap on returned rows.

    Returns: {results: [{path, mtime, size, ocr_text_excerpt, score}, ...], count}.
    """
    conn = _get_conn()
    since_ts: float | None = None
    if since is not None and since != "":
        since_ts = _parse_since(since)

    rows = store.search_text(conn, query, since=since_ts, max_results=max_results)
    return {
        "count": len(rows),
        "results": [
            {
                "path": r["path"],
                "mtime": float(r["mtime"]),
                "size": int(r["size"]),
                "ocr_text_excerpt": (r["ocr_text"] or "")[:200],
                "score": float(r["score"]),
            }
            for r in rows
        ],
    }


@mcp.tool()
def search_visual(query: str, since: str | None = None, max_results: int = 10) -> dict:
    """Visual search via CLIP text-query embedding + cosine similarity.

    Args:
        query: natural-language description ("error dialog with red button").
        since: optional ISO-8601 timestamp or epoch seconds — same shape as `search_text`.
        max_results: cap on returned rows.

    Returns: {results: [{path, mtime, size, score}, ...], count, model}.

    Requires `open_clip_torch` and ~150 MB of ViT-B/32 weights (downloaded on
    first call). If the CLIP loader fails, returns {"error": "..."} instead of
    raising — Claude/other clients should surface the message to the user.
    """
    conn = _get_conn()
    since_ts: float | None = None
    if since is not None and since != "":
        since_ts = _parse_since(since)

    try:
        query_vec = clip.embed_text(query)
    except (ImportError, ValueError) as exc:
        return {"error": str(exc), "results": [], "count": 0}

    pairs = store.nearest_neighbors(
        conn,
        query_vec,
        clip.model_tag(),
        max_results=max_results,
        since=since_ts,
    )
    return {
        "model": clip.model_tag(),
        "count": len(pairs),
        "results": [
            {
                "path": row["path"],
                "mtime": float(row["mtime"]),
                "size": int(row["size"]),
                "score": float(score),
            }
            for row, score in pairs
        ],
    }


@mcp.tool()
def find_similar(image_path: str, max_results: int = 10) -> dict:
    """Find images in the index visually similar to the given image (image-to-image).

    Args:
        image_path: path to a reference image (does NOT need to be in the index).
        max_results: cap on returned rows. The reference itself is filtered out
            of the results when it happens to be indexed.

    Returns: {results: [{path, mtime, size, score}, ...], count, model, reference}.
    """
    conn = _get_conn()
    ref = Path(image_path).expanduser().resolve()
    if not ref.is_file():
        return {"error": f"Not a file: {ref}", "results": [], "count": 0}

    try:
        blob = clip.embed_image(ref)
    except (ImportError, FileNotFoundError, OSError) as exc:
        return {"error": str(exc), "results": [], "count": 0}

    import struct

    dim = len(blob) // 4
    vector = list(struct.unpack(f"<{dim}f", blob))

    pairs = store.nearest_neighbors(
        conn,
        vector,
        clip.model_tag(),
        max_results=max_results + 1,
    )
    out = []
    for row, score in pairs:
        if row["path"] == str(ref):
            continue
        out.append(
            {
                "path": row["path"],
                "mtime": float(row["mtime"]),
                "size": int(row["size"]),
                "score": float(score),
            }
        )
        if len(out) >= max_results:
            break
    return {
        "model": clip.model_tag(),
        "reference": str(ref),
        "count": len(out),
        "results": out,
    }


@mcp.tool()
def search_by_color(hex_color: str, tolerance: int = 30, max_results: int = 10) -> dict:
    """Find indexed images whose dominant color matches `hex_color`.

    Useful for "find the screenshot with the red error banner" or "show me the
    screenshots from that dark-themed app" — search vectors only let you do this
    via semantic phrases, but color matches the literal pixels.

    Args:
        hex_color: target color as `#RRGGBB` (the `#` is optional).
        tolerance: per-channel slack, 0-255. 30 is a good "same-ish color"
            default; tighten to ~10 for exact matches, widen to ~60 for "any
            shade of blue".
        max_results: cap on returned rows.
    """
    try:
        target = colors.parse_hex(hex_color)
    except ValueError as exc:
        return {"error": str(exc), "results": [], "count": 0}

    tolerance = max(0, min(255, int(tolerance)))
    conn = _get_conn()
    rows = store.search_by_color(conn, target, max_results=max_results, tolerance=tolerance)
    out = []
    for row, dist in rows:
        r, g, b = colors.unpack_rgb(int(row["dominant_rgb"]))
        out.append(
            {
                "path": row["path"],
                "dominant_rgb": f"#{int(row['dominant_rgb']):06X}",
                "rgb": [r, g, b],
                "distance": int(dist),
                "mtime": float(row["mtime"]),
            }
        )
    return {
        "query": hex_color,
        "target_rgb": [colors.unpack_rgb(target)[0], *colors.unpack_rgb(target)[1:]],
        "tolerance": tolerance,
        "count": len(out),
        "results": out,
    }


@mcp.tool()
def compare_images(image_path_a: str, image_path_b: str) -> dict:
    """Compute CLIP cosine similarity between two specific images.

    Neither image needs to be in the index — useful for ad-hoc "are these
    two screenshots the same screen / very similar?" questions where you
    don't want to bring an entire directory into the indexer.

    Returns:
        - `similarity`: cosine sim in [-1, 1]. Both embeddings are already
          L2-normalized so this is just the dot product. 1.0 = identical,
          0.0 = unrelated, -1.0 = opposite direction (rare with CLIP).
        - `distance`: `1 - similarity`, for callers that prefer a 0=match
          distance metric.

    Returns `{error: ...}` (no `similarity`) if CLIP can't be loaded or
    either image is missing/unreadable.
    """
    import struct as _struct

    a = Path(image_path_a).expanduser().resolve()
    b = Path(image_path_b).expanduser().resolve()
    if not a.is_file():
        return {"error": f"Not a file: {a}"}
    if not b.is_file():
        return {"error": f"Not a file: {b}"}

    try:
        blob_a = clip.embed_image(a)
        blob_b = clip.embed_image(b)
    except (ImportError, FileNotFoundError, OSError) as exc:
        return {"error": str(exc)}

    dim = len(blob_a) // 4
    if len(blob_b) != dim * 4:
        return {"error": "Embedding dimensionality mismatch — re-check CLIP install."}
    va = _struct.unpack(f"<{dim}f", blob_a)
    vb = _struct.unpack(f"<{dim}f", blob_b)
    # Both embeddings are L2-normalized by clip.embed_image, so cosine
    # similarity == dot product. No need to renormalize.
    similarity = float(sum(x * y for x, y in zip(va, vb, strict=True)))
    return {
        "image_a": str(a),
        "image_b": str(b),
        "model": clip.model_tag(),
        "similarity": similarity,
        "distance": 1.0 - similarity,
    }


@mcp.tool()
def delete_indexed_directory(path: str) -> dict:
    """Drop every indexed image (and its embeddings + tags) under `path`.

    Privacy escape hatch. Matching is a `path LIKE prefix%` so the
    directory should be passed as an absolute path; SQLite wildcards are
    escaped so a directory containing `%` in its name behaves correctly.

    Returns: {prefix, deleted_count}.
    """
    target = Path(path).expanduser().resolve()
    prefix = str(target)
    conn = _get_conn()
    deleted = store.delete_by_path_prefix(conn, prefix)
    return {"prefix": prefix, "deleted_count": int(deleted)}


@mcp.tool()
def tag_image(image_path: str, tags: list[str], mode: str = "add") -> dict:
    """Attach user-supplied tags to an indexed image.

    Tags are normalized (stripped, lowercased) so callers don't have to
    worry about case sensitivity. `mode="add"` keeps any existing tags;
    `mode="replace"` clears them first.

    The image must already be in the index — call `index_directory` over
    its parent dir first if not. Returns the resulting tag set.
    """
    target = Path(image_path).expanduser().resolve()
    conn = _get_conn()
    row = store.get_by_path(conn, str(target))
    if row is None:
        return {"error": f"Not indexed: {target}", "tags": []}
    if mode not in ("add", "replace"):
        return {"error": f"Unknown mode: {mode!r} (use 'add' or 'replace')", "tags": []}
    resulting = store.set_tags(conn, int(row["id"]), tags, mode=mode)
    return {"path": str(target), "tags": resulting, "mode": mode}


@mcp.tool()
def search_by_tag(tag: str, since: str | None = None, max_results: int = 50) -> dict:
    """Return indexed images carrying `tag` (exact match, case-insensitive).

    Useful when CLIP / OCR don't catch what you want and you'd rather
    explicitly mark images. Pair with `tag_image` to build the tag set.
    """
    since_ts: float | None = None
    if since:
        since_ts = _parse_since(since)
    conn = _get_conn()
    rows = store.find_by_tag(conn, tag, since=since_ts, max_results=max_results)
    return {
        "tag": tag.strip().lower(),
        "count": len(rows),
        "results": [
            {
                "path": r["path"],
                "mtime": float(r["mtime"]),
                "size": int(r["size"]),
                "tags": store.get_tags(conn, int(r["id"])),
            }
            for r in rows
        ],
    }


@mcp.tool()
def extract_text(image_path: str, lang: str = "eng") -> dict:
    """Run OCR on a single image without touching the index.

    Useful for ad-hoc "what's in this screenshot?" questions where the image
    lives outside the indexed directories.

    Returns: {path, text, length}. Empty `text` means Tesseract found nothing
    or the binary isn't installed — call `ping` and check the Tesseract install
    if you expected text.
    """
    target = Path(image_path).expanduser().resolve()
    if not target.is_file():
        return {"error": f"Not a file: {target}", "text": ""}
    text = ocr.extract_text(target, lang=lang)
    return {"path": str(target), "text": text, "length": len(text)}


@mcp.tool()
def get_metadata(image_path: str) -> dict:
    """Return filesystem stats, EXIF tags, and current index status for an image.

    Useful for "when was this screenshot taken?" or "is this in the index yet?"
    questions. EXIF is optional — most screenshots don't carry it.
    """
    target = Path(image_path).expanduser().resolve()
    if not target.is_file():
        return {"error": f"Not a file: {target}"}

    stat = target.stat()
    out: dict = {
        "path": str(target),
        "size": int(stat.st_size),
        "mtime": float(stat.st_mtime),
        "ctime": float(stat.st_ctime),
    }

    try:
        from PIL import ExifTags, Image  # type: ignore[import-not-found]

        with Image.open(target) as img:
            out["width"], out["height"] = img.size
            out["format"] = img.format
            out["mode"] = img.mode
            exif_raw = img.getexif()
            if exif_raw:
                out["exif"] = {
                    ExifTags.TAGS.get(tag, str(tag)): _safe_exif_value(val)
                    for tag, val in exif_raw.items()
                }
    except Exception as exc:  # PIL not installed, unreadable image, etc.
        out["image_info_error"] = str(exc)

    conn = _get_conn()
    row = store.get_by_path(conn, str(target))
    if row is not None:
        out["indexed"] = {
            "id": int(row["id"]),
            "indexed_at": float(row["indexed_at"]),
            "ocr_text_length": len(row["ocr_text"] or ""),
            "has_embedding": _has_embedding(conn, int(row["id"]), clip.model_tag()),
        }
    else:
        out["indexed"] = None
    return out


def _has_embedding(conn, image_id: int, model: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM embeddings WHERE image_id = ? AND model = ? LIMIT 1",
        (image_id, model),
    ).fetchone()
    return row is not None


def _safe_exif_value(val):
    """EXIF values can be IFDRational, bytes, tuples — coerce to JSON-friendly."""
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace")
        except Exception:
            return repr(val)
    if isinstance(val, list | tuple):
        return [_safe_exif_value(v) for v in val]
    if hasattr(val, "numerator") and hasattr(val, "denominator"):
        return float(val) if val.denominator else 0.0
    if isinstance(val, int | float | str | bool) or val is None:
        return val
    return str(val)


def _parse_since(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        pass
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=UTC)
            return dt.timestamp()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse `since`: {value!r}")


def main() -> None:
    """Console-script entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
