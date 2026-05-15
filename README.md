# awesome-collections

A monorepo of small, useful AI / developer-tooling projects: three independent
software projects plus a curated list. Each subdirectory is self-contained
(own `pyproject.toml` where relevant, own `README.md`, own tests) so you can
clone the parent and use any of them in isolation.

## Projects

| Project | What it is | Status |
| --- | --- | --- |
| [`dep-upgrade-skill`](./dep-upgrade-skill) | Claude Code skill that flags which lines in your repo break when you bump a dependency. Fetches release notes, extracts breaking-change symbols, greps the repo. | v0.1 ready_for_review |
| [`screenshot-search-mcp`](./screenshot-search-mcp) | FastMCP server that indexes a screenshot folder by OCR text (Tesseract) and visual content (CLIP). Exposes 8 tools to MCP clients. | v0.1 ready_for_review |
| [`personal-timeline-mcp`](./personal-timeline-mcp) | FastMCP server aggregating local activity (browser history, git commits, filesystem mtimes, calendar) into one queryable timeline. All sources local-only — see PRIVACY.md. | v0.1 ready_for_review |
| [`awesome-mcp-clients`](./awesome-mcp-clients) | Curated list of clients that speak the [Model Context Protocol](https://modelcontextprotocol.io). | active |

## Quick start

```bash
git clone https://github.com/NoahStarkenburg/awesome-collections.git
cd awesome-collections

# Pick the project you want and follow its README:
cd screenshot-search-mcp        # → ./screenshot-search-mcp/README.md
```

The MCP servers (`screenshot-search-mcp`, `personal-timeline-mcp`) declare
their own dependencies in their `pyproject.toml`. The Python helpers in
`dep-upgrade-skill` are stdlib-only.

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) for branching conventions, dev
setup, coding standards, commit-message rules, and the curation-entry
workflow.

For security issues, see [`SECURITY.md`](./SECURITY.md).

## CI

Every push and PR runs:
- pytest for each project on Linux + Windows × Python 3.11 and 3.12
- `ruff check .` and `ruff format --check .` against the whole tree

See [`.github/workflows/ci.yml`](./.github/workflows/ci.yml).

## Repo layout

```
awesome-collections/
├── .github/
│   ├── workflows/ci.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── dep-upgrade-skill/        # Claude Code skill + Python helpers
├── screenshot-search-mcp/    # FastMCP server
├── personal-timeline-mcp/    # FastMCP server
├── awesome-mcp-clients/      # Curated list + pipeline/fetch.py
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── pyproject.toml            # shared ruff config
```

## License

[MIT](./LICENSE) for code; [CC0](https://creativecommons.org/publicdomain/zero/1.0/)
for the curated `awesome-mcp-clients` content.
