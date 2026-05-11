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

System dependencies (added piece-by-piece as features land):

- **Tesseract OCR** — required by the OCR pipeline (not yet wired). Install:
  - Windows: `winget install --id UB-Mannheim.TesseractOCR`
  - macOS: `brew install tesseract`
  - Linux (Debian/Ubuntu): `sudo apt install tesseract-ocr`

- **CLIP model files** — auto-downloaded by `open-clip-torch` on first use
  (~150 MB for ViT-B/32). No manual setup.

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
