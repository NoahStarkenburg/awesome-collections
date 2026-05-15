# Security Policy

This repo contains three software projects, two of which are MCP servers that
read local user data. Treat security issues — anything that could leak data,
escalate privilege, or run arbitrary code — as **high priority**.

## Reporting

**Do not** open a public issue for security problems. Instead, email
**noahstarkenburg@gmail.com** with:

- A short description of the issue
- The project affected (`dep-upgrade-skill`, `screenshot-search-mcp`,
  `personal-timeline-mcp`, or repo-wide)
- A minimal repro (commands, sample input, or a stripped-down PoC)
- The commit SHA you tested against

You should hear back within **72 hours**. If you don't, please follow up —
the address is not perfectly monitored.

## What counts as a security issue

Per-project specifics:

### `dep-upgrade-skill`

- Anything that lets an attacker control which files the skill writes or which
  shell commands it runs when invoked from a benign-looking dependency name.
- Cache poisoning via the disk cache at `~/.cache/dep-upgrade-skill/`.
- Issues with how `GITHUB_TOKEN` is read or transmitted.

### `screenshot-search-mcp`

- Path-traversal or arbitrary-file-read via the `index_directory`,
  `extract_text`, `find_similar`, `get_metadata` tools.
- SQL injection via `search_text` (FTS5 queries are user input).
- Leaks of OCR'd text or image content outside the local SQLite DB.

### `personal-timeline-mcp`

- **Any** path the server reads that isn't in `config.toml`'s explicit allow
  lists.
- Browser DB reads that include cookies, passwords, or other sensitive tables
  (the readers should only touch `urls`/`visits` for Chromium and
  `moz_places`/`moz_historyvisits` for Firefox).
- Network calls from any source module. The v1 promise is "nothing leaves
  your machine" — a regression there is a security issue.
- Read access to file contents (only paths + mtime/size are supposed to be
  recorded for the `fs` source).

### Repo-wide

- Anything in CI that could leak secrets or be used to run arbitrary code
  with repo write permissions.
- Dependency-supply-chain issues (typosquats, hijacked packages).

## What's not a security issue

- Performance regressions
- Crashes on bad input that don't escalate privilege or leak data
- Aesthetic problems
- Disagreement with a design decision (open a regular issue or PR)

## Disclosure

We follow coordinated disclosure: once a fix is available, the original
reporter is credited in the release notes unless they prefer otherwise.
There's no bug bounty in v1.

## Out of scope

- Vulnerabilities in third-party dependencies (FastMCP, Pillow,
  pytesseract, open-clip-torch, etc.) — report those upstream. We track
  advisories and bump dependencies promptly.
- Vulnerabilities that require an attacker to already control the user's
  machine. The threat model is "untrusted input to MCP tools / dep names",
  not "attacker has shell access".
