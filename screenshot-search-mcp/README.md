# screenshot-search-mcp

An MCP server that indexes a folder of screenshots/images and exposes search by **text
content** (OCR via Tesseract) and **visual content** (CLIP embeddings).

Works with any MCP client — Claude Desktop, Cursor, Cline, Continue, Zed.

> "Find the screenshot from 3 weeks ago with the auth error message."
> "Show me screenshots of error dialogs."
> "Find screenshots similar to this one."

## Status

**v0.1.0** — feature-complete for the v1 surface. All eight tools wired, SQLite
index + FTS5 + CLIP embeddings + watchdog watcher all functional. 23 tests pass
(17 store unit tests + 6 in-memory MCP protocol e2e tests). See
[`examples/sample_run.md`](examples/sample_run.md) for what each tool returns
against a real screenshots folder.

## Tools

| Tool | What it does |
| --- | --- |
| `ping()` | Health check — confirms the server is reachable. |
| `index_directory(path, recursive)` | Scan a folder and OCR-index new/changed images. |
| `index_status()` | Report totals, last-indexed file, last run summary. |
| `search_text(query, since, max_results)` | FTS5 search over OCR'd text. |
| `search_visual(query, since, max_results)` | CLIP text-to-image search. |
| `find_similar(image_path, max_results)` | Image-to-image visual similarity. |
| `extract_text(image_path, lang)` | Single-shot OCR on an arbitrary file. |
| `get_metadata(image_path)` | File stats, EXIF (when present), index status. |

## Install (development)

Requires **Python 3.11+** and `uv` (or `pip`).

```bash
git clone <repo-url>
cd awesome-collections/screenshot-search-mcp

uv venv
# Pick the install footprint that matches what you'll use:
uv pip install -e ".[dev]"           # OCR + text search only  (~50 MB of deps)
uv pip install -e ".[visual,dev]"    # + CLIP visual search    (pulls PyTorch, ~1 GB)
uv pip install -e ".[all]"           # everything

# Or with plain pip (same shape):
python -m venv .venv
source .venv/bin/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**Skip `[visual]` if you don't need `search_visual` / `find_similar`.** The
server starts fine without it — those two tools return a graceful
`{"error": "open_clip_torch is required..."}` payload instead of crashing.

## System dependencies

### Tesseract OCR (required for `index_directory`, `search_text`, `extract_text`)

The OCR pipeline shells out to the Tesseract binary via `pytesseract`. Install:

| OS | Command | Verify |
| --- | --- | --- |
| Windows | `winget install --id UB-Mannheim.TesseractOCR` | `tesseract --version` |
| macOS | `brew install tesseract` | `tesseract --version` |
| Debian/Ubuntu | `sudo apt install tesseract-ocr` | `tesseract --version` |
| Fedora | `sudo dnf install tesseract` | `tesseract --version` |
| Arch | `sudo pacman -S tesseract tesseract-data-eng` | `tesseract --version` |

**Expected version:** 5.0 or later. The output of `tesseract --version` should
show `tesseract 5.x.y` and at least one language under `Available languages` —
typically `eng` for English. Without a language pack, OCR returns empty strings.

**Windows path note:** the UB-Mannheim installer registers Tesseract on `PATH`
automatically. If `pytesseract` can't find it, point at the binary explicitly:

```python
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

You can also set the `TESSERACT_CMD` env var before starting the server, and the
OCR wrapper will pick it up.

### CLIP model files (required for `search_visual`, `find_similar`)

Auto-downloaded by `open-clip-torch` on first use (~150 MB for ViT-B/32 weights).
Cached under `~/.cache/clip/`. The first call to `search_visual` may take
30–60 seconds while the model loads. Subsequent calls are fast.

GPU is **not required**. ViT-B/32 runs on CPU at roughly 30 images/second on a
modern laptop. To enable CUDA, install a CUDA-matched PyTorch build before
installing this package — see the [open_clip docs](https://github.com/mlfoundations/open_clip).

## Run the server (development)

The FastMCP CLI gives you a live inspector at `http://localhost:8000`:

```bash
fastmcp dev src/screenshot_search/server.py
```

Then call the `ping` tool from the inspector to confirm the server is reachable.

For stdio mode (the transport Claude Desktop and most other clients use):

```bash
python -m screenshot_search.server
```

## Configure in Claude Desktop

Edit `claude_desktop_config.json` (paths vary by OS — see the
[Claude Desktop docs](https://modelcontextprotocol.io/quickstart/user)):

```json
{
  "mcpServers": {
    "screenshot-search": {
      "command": "python",
      "args": ["-m", "screenshot_search.server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/screenshot-search-mcp/src"
      }
    }
  }
}
```

After restarting Claude Desktop, you should see `screenshot-search` in the MCP
servers panel and `ping` available as a callable tool.

## Config file (optional)

`~/.screenshot-search/config.toml`:

```toml
db_path           = "~/.screenshot-search/index.db"
watch_dirs        = ["~/Pictures/Screenshots"]
debounce_seconds  = 2.0
recursive         = true
```

Read by `screenshot_search.config.load()`. The watcher (`watch.py`) honors
`watch_dirs` and `debounce_seconds`; `db_path` is also overridable via the
`SCREENSHOT_SEARCH_DB` env var.

## Live watching

```bash
python -m screenshot_search.watch ~/Pictures/Screenshots --debounce 2.0
```

Performs an initial scan, then reindexes the parent directory of any image
that's created or modified — debounced to avoid double-indexing files written
in two passes by screenshot tools.

## Tests

```bash
python -m pytest screenshot-search-mcp/tests/
```

- **`test_store.py`** — 17 cases covering schema, upsert COALESCE, FTS5 trigger
  sync, embedding round-trip, nearest-neighbor cosine ranking, cascade-delete.
- **`test_server_e2e.py`** — 6 cases using FastMCP's in-memory `Client` transport
  to call every tool via the real MCP protocol path (list_tools + call_tool).

CLIP runtime is intentionally not exercised in CI (the ~150 MB model isn't
something to pull on every test run); `test_visual_tools_degrade_gracefully_without_clip`
locks in the contract that visual tools return `{"error": "..."}` instead of
crashing when the model isn't loadable.

## License

MIT (same as the parent repo).
