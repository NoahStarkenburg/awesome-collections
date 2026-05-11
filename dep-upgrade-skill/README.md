# dep-upgrade-skill

A Claude Code skill that tells you **which lines in your repo break** when you bump a
dependency.

Most upgrade tools just summarize release notes. This one cross-references the breaking
changes against your actual code so you know what to fix and where — grouped by breaking
change, with `file_path:line_number` refs.

## What it does

Given a package name and a version range:

1. **Detects your ecosystem** from `package.json` / `pyproject.toml` / `Cargo.toml`
2. **Fetches release notes** between the two versions (npm registry, PyPI, with GitHub
   Releases as fallback). Responses are cached on disk for 1 hour.
3. **Extracts breaking-change symbols** — renamed APIs, removed options, changed
   signatures. Backticks, dotted refs, ALL_CAPS, CamelCase, and `snake_case()` calls
   are all picked up.
4. **Greps your repo** for usage of those symbols.
5. **Reports affected files** with line numbers, grouped by breaking change. Symbols
   with zero hits are listed separately so you can verify nothing dynamic was missed.

If the release notes don't have a structured "Breaking changes" section, the skill
flags the raw text for manual review instead of falsely reporting "nothing to fix".

## Example invocation

In Claude Code:

> /upgrade-impact react 18 19

Or in plain English:

> "I'm bumping React from 18 to 19. What breaks in this repo?"

Claude routes to this skill, runs the pipeline, and returns a markdown report.

## Example run output

```
1. Detected manifest: package.json (npm), react ^18.2.0 → 19.0.0
2. Fetched release notes: 3 versions (18.3.0, 18.3.1, 19.0.0), CHANGELOG.md found
3. Extracted breaking changes: 1 dedicated v19 section, 11 candidate symbols
4. Searching repo for symbol usage…
5. Report:

# Upgrade impact: react 18.2.0 → 19.0.0

Found 1 breaking change(s) that affect this repo across 3 file(s).

## Breaking Changes (v19.0.0)

- `ReactDOM.render` — 2 hit(s)
  - src/index.js:7 — ReactDOM.render(<App />, document.getElementById('root'));
  - src/legacy-mount.js:14 — ReactDOM.render(node, container);
- `ReactDOM.hydrate` — 1 hit(s)
  - src/ssr-entry.js:22 — ReactDOM.hydrate(<App />, document.getElementById('root'));
- `defaultProps` — 1 hit(s)
  - src/components/Avatar.jsx:18 — Avatar.defaultProps = { size: 'md' };

Total: 3 file(s) need review across 1 change(s).
```

See [`examples/react-18-to-19.md`](examples/react-18-to-19.md) for the full report
template and [`examples/express-4-to-5.md`](examples/express-4-to-5.md) for the
manual-review fallback path.

## Install

The skill lives in this repo. To use it from your own Claude Code session:

```bash
# Vendor the skill into Claude Code's skills directory:
cp -r dep-upgrade-skill ~/.claude/skills/upgrade-impact

# (Windows PowerShell:)
Copy-Item -Recurse dep-upgrade-skill "$env:USERPROFILE\.claude\skills\upgrade-impact"
```

Requires **Python 3.11+**. The helper scripts are stdlib-only — no `pip install`.

For an unauthenticated GitHub Releases fallback you'll hit rate limits after ~60
requests/hour. Set `GITHUB_TOKEN` (any token with `public_repo` read scope) to bump
this to 5000/hour:

```bash
export GITHUB_TOKEN=ghp_…
```

## Run the helpers directly

If you'd rather skip the skill wrapper and use the Python tools directly:

```bash
python dep-upgrade-skill/scripts/detect_manifest.py /path/to/my-repo --package react
python dep-upgrade-skill/scripts/fetch_release_notes.py react \
    --from 18.2.0 --to 19.0.0 --ecosystem npm > /tmp/react.json
cat /tmp/react.json | jq -r .changelog_raw |
    python dep-upgrade-skill/scripts/extract_breaking.py
```

Each script emits JSON to stdout. Pipe them together to build your own report.

## How it works under the hood

- [`scripts/detect_manifest.py`](scripts/detect_manifest.py) — scans the repo root
  for `package.json`, `pyproject.toml`, or `Cargo.toml` and reports the
  ecosystem + locked-or-declared versions. Stdlib only.
- [`scripts/fetch_release_notes.py`](scripts/fetch_release_notes.py) — pulls release
  notes from npm / PyPI with GitHub Releases as fallback. SHA256-keyed disk cache
  at `~/.cache/dep-upgrade-skill/` (1 hour TTL).
- [`scripts/extract_breaking.py`](scripts/extract_breaking.py) — regex-based parser
  for "Breaking changes" sections + heuristic symbol extractor (weighted regex
  passes with a stopword set).
- [`SKILL.md`](SKILL.md) — the orchestration prompt Claude reads when the skill
  triggers. Glues the scripts together via Read/Bash/Grep.

## Tests

```bash
python -m pytest dep-upgrade-skill/tests/
```

49 tests cover semver/PEP-440 parsing, version-range filtering, repo-URL extraction,
mocked HTTP round-trips, disk caching, heading detection, symbol extraction, and the
`needs_review` fallback against six real-shape CHANGELOG snippets.

## Status

Feature-complete for v1. Real-world tested against React 18→19 and Express 4→5. See
[`examples/`](examples/) for sample runs and [`SKILL.md`](SKILL.md) for the
orchestration template.

## License

MIT (same as the parent repo).
