# dep-upgrade-skill

A Claude Code skill that tells you **which lines in your repo break** when you bump a dependency.

Most upgrade tools just summarize release notes. This one cross-references the breaking changes against your actual code so you know what to fix and where.

## What it does

Given a package name and a version range:

1. Detects your ecosystem from your manifest (`package.json`, `pyproject.toml`, `Cargo.toml`).
2. Fetches release notes / CHANGELOG entries between the two versions (npm registry → PyPI → GitHub Releases as fallbacks).
3. Extracts breaking-change symbols (renamed APIs, removed options, changed signatures).
4. Greps your repo for usage of those symbols.
5. Reports affected files with line numbers, grouped by breaking change.

## Example invocation

In Claude Code, just ask:

> /upgrade-impact react 18 19

Or in plain English:

> "I'm bumping React from 18 to 19. What breaks in this repo?"

Claude routes to this skill, runs the pipeline, and returns a markdown report.

## Example output

```markdown
## React 18 → 19 — 3 breaking changes affect this repo

### `propTypes` removed from function components
- `src/components/Button.tsx:14`
- `src/components/Modal.tsx:32`

### `defaultProps` removed from function components
- `src/components/Card.tsx:8`

### `forwardRef` no longer needs to wrap components for `ref` access
- `src/components/Input.tsx:22` (informational, no fix required)
```

## Install

The skill lives in this repo. To use it from your own Claude Code session:

```bash
# 1. Clone or vendor this dir into your project's .claude/skills/
cp -r dep-upgrade-skill ~/.claude/skills/

# 2. Make the helper scripts executable
chmod +x dep-upgrade-skill/scripts/*.py
```

The scripts are stdlib-only (Python 3.11+), so no `pip install` needed.

## How it works under the hood

- `scripts/fetch_release_notes.py` — pulls release notes from package registries (npm, PyPI) with GitHub Releases as fallback. Caches responses to disk.
- `scripts/extract_breaking.py` — parses changelog markdown to find breaking-change sections and the symbols they mention.
- `SKILL.md` — the orchestration prompt Claude reads when the skill is triggered. Glues the scripts together via Read/Bash/Grep.

## Status

Under active development. See `.local/plans/dep-upgrade-skill.md` for the full build plan and `.local/QUEUE.md` for what's next.

## License

MIT (same as the parent repo).
