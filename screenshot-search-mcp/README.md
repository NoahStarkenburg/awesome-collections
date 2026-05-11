# screenshot-search-mcp

An MCP server that indexes a folder of screenshots/images and exposes search by **text
content** (OCR via Tesseract) and **visual content** (CLIP embeddings).

Works with any MCP client — Claude Desktop, Cursor, Cline, Continue, Zed.

> "Find the screenshot from 3 weeks ago with the auth error message."
> "Show me screenshots of error dialogs."
> "Find screenshots similar to this one."

## Status

Early scaffolding. Only the `ping` tool is wired up so far — index/search tools land
in subsequent commits. See `.local/plans/screenshot-search-mcp.md` for the full build
plan.

## Install (development)

Requires **Python 3.11+** and `uv` (or `pip`).

```bash
# 1. Clone and enter the project:
git clone <repo-url>
cd awesome-collections/screenshot-search-mcp

# 2. Create a venv and install in editable mode with dev extras:
uv venv
uv pip install -e ".[dev]"
# or with plain pip:
python -m venv .venv
source .venv/bin/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

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

## License

MIT (same as the parent repo).
