# Sample run

This walkthrough shows what every tool returns once the index is populated.
The screenshots referenced below live in `examples/screenshots/` (see the
[README in that folder](screenshots/README.md) for what to drop in there).

## 1. Confirm the server is up

```
> Call: ping()
< {
    "server": "screenshot-search-mcp",
    "version": "0.1.0",
    "python": "3.11.5",
    "platform": "Windows-10-10.0.19045-SP0",
    "now": "2026-05-13T17:42:11Z",
    "status": "ok"
  }
```

## 2. Build the initial index

```
> Call: index_directory(path="~/Pictures/Screenshots", recursive=true)
< {
    "scanned": 312,
    "indexed": 312,
    "skipped_unchanged": 0,
    "skipped_unsupported": 0,
    "errored": 0,
    "last_path": "C:\\Users\\noahs\\Pictures\\Screenshots\\2026-05-12_193401.png",
    "root":     "C:\\Users\\noahs\\Pictures\\Screenshots"
  }
```

Re-running on the same directory should report `skipped_unchanged == scanned`
(mtime/size unchanged).

## 3. Check what's in the index

```
> Call: index_status()
< {
    "db_path": "C:\\Users\\noahs\\.screenshot-search\\index.db",
    "total_images": 312,
    "total_embeddings": 0,
    "last_indexed_path": "C:\\Users\\noahs\\Pictures\\Screenshots\\2026-05-12_193401.png",
    "last_indexed_at": 1715542931.42,
    "last_run": { … same shape as index_directory above }
  }
```

`total_embeddings == 0` is expected — CLIP embeddings aren't populated by the
OCR pass; they're populated on first `search_visual` / `find_similar` call (or
by a future `embed_directory` tool, not yet built).

## 4. Text search (OCR / FTS5)

```
> Call: search_text(query="auth error", max_results=5)
< {
    "count": 2,
    "results": [
      {
        "path":  "C:\\…\\2026-04-22_oauth_failure.png",
        "mtime": 1713815400.0,
        "size":  148290,
        "ocr_text_excerpt": "Authentication error: invalid_grant. Refresh token expired …",
        "score": -3.12
      },
      {
        "path":  "C:\\…\\2026-05-01_login_screen.png",
        "mtime": 1714521600.0,
        "size":  93120,
        "ocr_text_excerpt": "Sign-in error. Please try again or contact support.",
        "score": -2.04
      }
    ]
  }
```

`score` is BM25 — lower is better.

## 5. Visual search (CLIP)

```
> Call: search_visual(query="error dialog with red button", max_results=3)
< {
    "model": "open_clip/ViT-B-32/openai",
    "count": 3,
    "results": [
      { "path": "C:\\…\\2026-04-22_oauth_failure.png", "score": 0.281, … },
      { "path": "C:\\…\\2026-03-09_payment_decline.png", "score": 0.264, … },
      { "path": "C:\\…\\2026-02-14_modal_warning.png",  "score": 0.252, … }
    ]
  }
```

`score` here is cosine similarity — higher is better, capped at 1.0.

## 6. Image-to-image

```
> Call: find_similar(image_path="C:\\…\\2026-04-22_oauth_failure.png", max_results=2)
< {
    "model": "open_clip/ViT-B-32/openai",
    "reference": "C:\\…\\2026-04-22_oauth_failure.png",
    "count": 2,
    "results": [
      { "path": "C:\\…\\2026-03-09_payment_decline.png", "score": 0.74, … },
      { "path": "C:\\…\\2026-02-14_modal_warning.png",   "score": 0.69, … }
    ]
  }
```

The reference image itself is filtered out of results.

## 7. Single-shot OCR (no index)

```
> Call: extract_text(image_path="C:\\Downloads\\one_off_screenshot.png")
< {
    "path":   "C:\\Downloads\\one_off_screenshot.png",
    "text":   "404 Not Found — the requested URL /api/v2 was not found on this server.",
    "length": 75
  }
```

## 8. Metadata + EXIF

```
> Call: get_metadata(image_path="C:\\…\\2026-04-22_oauth_failure.png")
< {
    "path":    "C:\\…\\2026-04-22_oauth_failure.png",
    "size":    148290,
    "mtime":   1713815400.0,
    "ctime":   1713815401.2,
    "width":   1920,
    "height":  1080,
    "format":  "PNG",
    "mode":    "RGBA",
    "indexed": {
      "id": 42,
      "indexed_at": 1715542931.42,
      "ocr_text_length": 312,
      "has_embedding": true
    }
  }
```

Most screenshots have no EXIF, so the `exif` key is usually absent. For
photos taken on a phone you'll see camera/lens/orientation tags.

## End-to-end

Wire everything together: index once, search by text and visually, and use
metadata to confirm a hit:

```
> index_directory("~/Pictures/Screenshots")
> search_text("OAuth grant")        → 1 hit
> search_visual("error dialog")     → 3 hits, overlapping the text search
> get_metadata(<top hit>)           → confirm mtime / dimensions
```

That's the v0.1 surface area — the full README has install + Tesseract setup.
