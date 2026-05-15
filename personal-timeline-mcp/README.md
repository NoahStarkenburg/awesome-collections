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

**v0.1.0** — all 4 sources read, all 8 MCP tools wired, 24 tests passing.
Real-world Claude Desktop verification still recommended before tagging.

## Tools

| Tool | What it does |
| --- | --- |
| `ping()` | Health check — confirms the server is reachable. |
| `list_sources()` | Report which sources are configured + per-source state. |
| `index_sources(force_full)` | Drive every enabled source through its ingestor. |
| `timeline_around(timestamp, window, sources)` | Events near a moment. |
| `what_changed_today(path, date)` | fs + git events for a day, optionally path-scoped. |
| `find_session(query)` | FTS5 search over event titles + bodies. |
| `summarize_workday(date)` | Per-source counts, commits, calendar, top files. |
| `correlate(event_id, sources, window)` | Cross-source events near a reference. |

## Sample workday report

What `summarize_workday("2026-05-15")` returns against a real personal-timeline
index, condensed for readability:

```json
{
  "date": "2026-05-15",
  "by_source": {"git": 8, "calendar": 2, "fs": 14, "chrome": 47},
  "total_events": 71,
  "first_event_ts": 1747293812,
  "last_event_ts":  1747327489,
  "active_hours":   9.4,

  "git_commits": [
    {"sha": "8a29081…", "subject": "Add index subcommand to personal-timeline CLI", "files": ["personal-timeline-mcp/src/personal_timeline/cli.py"]},
    {"sha": "fad33e9…", "subject": "Add personal-timeline CLI with init subcommand", "files": ["personal-timeline-mcp/src/personal_timeline/cli.py"]},
    {"sha": "5b3b51b…", "subject": "Add correlate MCP tool finding cross-source events", "files": ["personal-timeline-mcp/src/personal_timeline/server.py"]}
  ],

  "calendar_blocks": [
    {"summary": "Standup",    "ts": 1747299600, "end_ts": 1747301400, "location": "Zoom"},
    {"summary": "Design sync","ts": 1747315200, "end_ts": 1747320600, "location": "Office"}
  ],

  "top_files": [
    {"path": "personal-timeline-mcp/src/personal_timeline/server.py", "hits": 6},
    {"path": "personal-timeline-mcp/src/personal_timeline/cli.py",    "hits": 4},
    {"path": ".local/QUEUE.md",                                       "hits": 3}
  ]
}
```

Pair with `correlate(event_id=<one of the commits>)` to find the calendar
block / browser tabs around that commit — that's the "what meeting prompted
this commit?" workflow.

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
