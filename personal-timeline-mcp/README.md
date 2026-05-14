# personal-timeline-mcp

An MCP server that aggregates your local activity into a single queryable timeline:

- Browser history (Chrome, Edge, Firefox)
- Git commits across configured repos
- Filesystem mtimes for configured directories
- Calendar events (`.ics` files)

All sources are **local-only** in v1 — no OAuth, no cloud upload. See
[`PRIVACY.md`](PRIVACY.md) for exactly what's read and how to wipe the index.

> "What was I doing last Tuesday at 3pm?"
> "What changed in the auth code today and what meeting prompted it?"
> "Summarize my workday on May 5."

## Status

Early. Server scaffolding + `ping` is wired up; the source readers and tools
land commit-by-commit. See `.local/plans/personal-timeline-mcp.md` for the full
build plan.

## Install (development)

Requires **Python 3.11+** and `uv` (or `pip`).

```bash
git clone <repo-url>
cd awesome-collections/personal-timeline-mcp
uv venv
uv pip install -e ".[dev]"

# or with plain pip:
python -m venv .venv
source .venv/bin/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## First-run setup

Once the source readers land you'll bootstrap a config with:

```bash
personal-timeline init
```

That creates `~/.personal-timeline/config.toml` and `~/.personal-timeline/index.db`.

Edit the config to point at your repos / screenshot folders / `.ics` paths,
then:

```bash
personal-timeline index
```

…to run the first full pass. After that, the server's `index_sources` tool
handles incremental updates.

## Configure in Claude Desktop

```json
{
  "mcpServers": {
    "personal-timeline": {
      "command": "python",
      "args": ["-m", "personal_timeline.server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/personal-timeline-mcp/src"
      }
    }
  }
}
```

Restart Claude Desktop. `personal-timeline` should appear in the MCP servers
panel and `ping` should be callable to confirm.

## Tests

```bash
python -m pytest personal-timeline-mcp/tests/
```

Tests for each source land alongside the source itself. None of the tests hit
the user's real browser/git/filesystem state — they use fixture SQLite DBs,
fixture git repos, and fixture `.ics` files under `tests/fixtures/`.

## License

MIT (same as the parent repo).
