# PRIVACY

`personal-timeline-mcp` reads local data from the sources you configure. Nothing
leaves your machine — there are no network calls in v1.

## What's read

Filled in commit-by-commit as each source lands. Skeleton:

- **Browser history** — Chrome/Edge `History` SQLite DB, Firefox `places.sqlite`.
  Reads URL, title, visit time. Does NOT read cookies, passwords, or form data.
- **Git commits** — only repos you list in config. Reads SHA, author, timestamp,
  commit message, list of changed files. Does NOT read file contents.
- **Filesystem** — only directories you list in config. Reads file path, mtime,
  size. Does NOT read file contents.
- **Calendar** — `.ics` file paths you list in config. Reads event title, start,
  end, location.

## Where it's stored

A single SQLite file at `~/.personal-timeline/index.db` (configurable). FTS5
shadow tables are part of the same DB.

## How to wipe

```sh
personal-timeline wipe
```

Removes the database file. Configuration in `~/.personal-timeline/config.toml`
is left alone.

## Out of scope for v1

- Slack DMs, Gmail, Google Calendar API (require OAuth — deferred)
- Cloud sync
- Multi-machine merging
