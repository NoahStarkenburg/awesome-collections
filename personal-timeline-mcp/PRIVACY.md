# PRIVACY

`personal-timeline-mcp` reads local data from the sources you opt into via
`~/.personal-timeline/config.toml`. **Nothing leaves your machine** in v1 —
there are no network calls anywhere in the codebase.

If you ever want to confirm that for yourself:

```bash
rg -n "urlopen|requests|httpx|urllib|socket\." personal-timeline-mcp/src
```

The only matches you should see are inside the FastMCP framework itself
(which speaks stdio JSON-RPC to the client — no outbound HTTP).

## What's read

Every source is disabled by default. Enabling a source in `config.toml`
is the only way it reads anything.

### `[sources.chrome]` / `[sources.edge]` / `[sources.brave]`

- **Path:** the browser's `History` SQLite file (auto-located per OS, or
  override with `profile_dir`).
- **What:** `urls.url`, `urls.title`, `visits.visit_time` from the
  Chromium History DB.
- **Never:** cookies, passwords, autofill, form data, downloads, bookmarks,
  open tabs, extensions, sync state, profile pictures.
- **Lock handling:** the live DB is copied to a temp file before reading so
  the browser can keep running.

### `[sources.firefox]`

- **Path:** the profile's `places.sqlite` (auto-located via `profiles.ini`,
  or override).
- **What:** `moz_places.url`, `moz_places.title`, `moz_historyvisits.visit_date`.
- **Never:** cookies, passwords (those live in separate DBs), bookmarks, form data.

### `[sources.git]`

- **Repos:** only paths listed in `repos = [...]`.
- **What:** for each commit — SHA, author name/email, timestamp, commit
  subject, list of changed file paths.
- **Never:** file *contents*, diffs, blob data, refs other than commits.
- **Author filter:** `author_email = "you@example.com"` restricts to your
  own commits when you walk shared repos.

### `[sources.filesystem]`

- **Dirs:** only paths listed in `dirs = [...]`.
- **What:** file path, mtime, size.
- **Never:** file contents.
- **Ignore list:** `.git`, `node_modules`, `__pycache__`, `.venv` (and any
  others you add) are skipped at the directory level.

### `[sources.calendar]`

- **Files:** only `.ics` paths listed in `ics_paths = [...]`.
- **What:** event UID, summary, description, location, start, end.
- **Never:** anything outside the .ics files you pointed at.

## Where it's stored

A single SQLite file. Default location:

- Windows: `C:\Users\<you>\.personal-timeline\index.db`
- macOS:   `~/.personal-timeline/index.db`
- Linux:   `~/.personal-timeline/index.db`

The directory is created on first run with the user's normal umask. FTS5
shadow tables live in the same file.

Override with `db_path` in `config.toml` or the `PERSONAL_TIMELINE_DB`
environment variable.

## How to wipe

```sh
personal-timeline wipe          # dry-run: shows what would be deleted
personal-timeline wipe --yes    # actually deletes the index + WAL/SHM siblings
```

Configuration in `~/.personal-timeline/config.toml` is left intact. To wipe
that too:

```sh
rm ~/.personal-timeline/config.toml
```

## What's never read

Even with every source enabled, the server never reads:

- File contents (just paths + mtime/size for filesystem; just commit metadata
  for git).
- Browser cookies, passwords, autofill, downloads, bookmarks, extensions.
- Anything from your email, chat, Slack, Discord, or cloud services. v1 has
  no OAuth — those sources are deferred to v0.2 and will be off-by-default.
- Anything outside the explicit paths you put in `config.toml`.

## What's logged

The server uses Python's `logging` module at WARNING level by default. Errors
include file paths but no contents. Set `LOG_LEVEL=DEBUG` if you need verbose
diagnostics — that's printed to stderr only and never written to disk.

## Out of scope for v1

- OAuth sources (Slack DMs, Gmail, Google Calendar API) — deferred to v0.2.
- Cloud sync of the index.
- Multi-machine merging.
- Encryption at rest of the index file. (SQLite encryption extensions exist
  but aren't part of v1.) Treat `index.db` like you'd treat your shell
  history file — protect it via OS file permissions.

## Questions

If something in this doc is wrong or you notice the server reading something
it shouldn't, file an issue immediately and don't deploy the change.
