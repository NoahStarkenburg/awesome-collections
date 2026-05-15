# Contributing

This monorepo houses three independent projects + a curation list. Each
sub-project has its own `pyproject.toml`, README, and test suite. Pick the
one you want to change and work locally inside its directory.

## Layout

| Path | What it is |
| --- | --- |
| `dep-upgrade-skill/` | A Claude Code skill (Python helpers + `SKILL.md`). |
| `screenshot-search-mcp/` | A FastMCP server for OCR + CLIP image search. |
| `personal-timeline-mcp/` | A FastMCP server aggregating local activity. |
| `awesome-mcp-clients/` | A curated awesome-list (Markdown + a fetch helper). |

## Branching + PRs

- `main` is always shippable. Tests pass; READMEs reflect current behavior.
- Open work goes on topic branches off `main`. Naming:
  - `feat/<project>-<short-slug>` for new features
  - `fix/<project>-<short-slug>` for bug fixes
  - `chore/<short-slug>` for tooling, CI, or repo-wide maintenance
  - `docs/<short-slug>` for doc-only changes
- One concern per PR. Several small PRs are better than one giant one.
- PRs target `main`. The CI workflow (`.github/workflows/ci.yml`) runs tests
  for every project on Linux + Windows with Python 3.11 and 3.12, plus a ruff
  lint + format check.

## Development setup

Each Python project under this repo declares its own dev extras:

```bash
cd <project>
python -m venv .venv
source .venv/bin/activate    # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Run tests for that project only:

```bash
python -m pytest tests/
```

Or for everything from the repo root:

```bash
python -m pytest dep-upgrade-skill/tests/
python -m pytest screenshot-search-mcp/tests/
python -m pytest personal-timeline-mcp/tests/
```

## Coding standards

- **Python 3.11+** across the board. Use new-syntax type hints (`list[str]`,
  `str | None`) and `from __future__ import annotations` at the top of each
  file.
- Lint + format with **ruff** (config in the root `pyproject.toml`):
  ```bash
  ruff check .
  ruff format .
  ```
- Stdlib-first. A new third-party dependency needs a one-line justification
  in the PR description.
- No emojis in source files unless the user asks for them.
- Comments explain *why*, never *what*. Don't restate the code in English.
- Tests live next to the project they cover, not in a shared root `tests/`.

## Commit messages

- Imperative present-tense subject under 70 chars: `Add foo`, `Fix bar`, not
  `Added foo` or `Fixes bar`.
- One logical change per commit. If you find yourself writing `and` in the
  subject, split the commit.
- Body (optional) explains the *why*. Wrap at ~72 chars.

## Curation entries (awesome-mcp-clients)

- Use `awesome-mcp-clients/pipeline/fetch.py <github-url>` to generate the
  metadata line. Never hand-write fields the script can produce.
- Insert in alphabetical order within the category.
- Each entry is its own commit so the README diff stays reviewable.

## Cutting a release

Each project releases independently via a per-project git tag. The CD
workflow ([`.github/workflows/release.yml`](./.github/workflows/release.yml))
fires on every tag of the form `<project>-v<X.Y.Z>` and does:

1. Parse the tag → `(project, version)`
2. Verify the project directory exists
3. For projects with a `pyproject.toml`: assert `version` in pyproject matches
   the tag, build wheel + sdist with `python -m build`, install the wheel
   into a fresh venv, and import the package as a smoke test
4. For skill-style projects (`dep-upgrade-skill`): pack the directory as
   `<project>-<version>.tar.gz`
5. Create a GitHub Release with auto-generated notes and attach the artifacts

### To cut a release

1. Open a PR that bumps the version in `<project>/pyproject.toml` and
   `<project>/src/<package>/__init__.py` (where applicable). Verify the
   matching `# Status` block in the README is accurate.
2. After it merges, on `main`:
   ```bash
   git pull origin main
   git tag <project>-v<X.Y.Z>
   git push origin <project>-v<X.Y.Z>
   ```
3. Watch the **Release** workflow run. On success the GitHub Release shows
   up at `https://github.com/<owner>/awesome-collections/releases`.

If the tag/pyproject versions don't match, the workflow fails before
publishing anything — fix the mismatch and re-tag (delete the bad tag
first: `git tag -d <tag> && git push --delete origin <tag>`).

### Manual re-release

You can also re-run the release workflow against an existing tag from the
Actions tab → Release → Run workflow → enter the tag name. Useful if the
first run failed on transient network issues.

## When in doubt

Open a draft PR early and ask. Better than 30 commits down a wrong path.
