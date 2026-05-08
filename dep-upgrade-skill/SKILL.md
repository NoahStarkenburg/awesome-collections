---
name: upgrade-impact
description: |
  Tells the user which lines in THEIR repo break when bumping a dependency. Cross-references
  release-note breaking changes against actual call sites in the codebase.

  TRIGGER when: user asks about upgrading a specific package (e.g. "what breaks if I bump React
  to 19?", "I want to upgrade express to 5", "/upgrade-impact <pkg> <from> <to>"); user is reading
  a CHANGELOG and wants to know if it affects them; package.json/pyproject.toml/Cargo.toml has
  outdated entries and user asks about consequences of upgrading.

  SKIP when: user just wants to bump versions without knowing what changes (use the package
  manager directly); user asks about general changelog viewing without their own repo as context;
  the package isn't on npm or PyPI (registry fetchers don't cover private/internal packages).
---

# upgrade-impact

When this skill activates, the user wants to know **which lines in their repo break** for a
specific dependency upgrade. Don't summarize release notes generically — cross-reference them
against the user's code.

## Inputs to extract from the user's request

1. **Package name** (e.g. `react`, `express`, `requests`)
2. **From version** — current version. If user didn't say, run manifest detection (below)
   and read it from there.
3. **To version** — target version. If user said "latest" or didn't specify, fetch the latest
   from the registry.
4. **Repo path** — defaults to the current working directory.

If any of these are ambiguous, ask the user once before proceeding.

## Step 1 — Manifest detection

Run `scripts/detect_manifest.py <repo-path> --package <name>`. The script scans for
`package.json` (npm), `pyproject.toml` (pypi), and `Cargo.toml` (cargo) at the repo root
and emits JSON like:

```json
{"manifests": [
  {"path": "package.json", "ecosystem": "npm",
   "dependencies": {"react": "^18.2.0"}}
]}
```

Use this output to:
- **Pick the ecosystem** for `fetch_release_notes.py --ecosystem <npm|pypi>` (cargo is not
  yet supported by the fetcher — fall back to "manual review" if Cargo is the only manifest).
- **Resolve `--from`** when the user didn't say. Strip semver-range prefixes (`^`, `~`, `>=`)
  to get a concrete version to pass to the fetcher.
- **Disambiguate** when more than one manifest matches the package — ask the user which one.

If `detect_manifest.py` exits 1 (no manifests found), tell the user the skill needs at least
one of `package.json`, `pyproject.toml`, or `Cargo.toml` at the repo root, then stop.

## Pipeline (orchestration)

Remaining steps (fetch → extract → grep → report) are added in subsequent commits.

## Activation behavior (current stub)

When triggered, respond with:

```
upgrade-impact skill activated.
Package: <pkg>
From:    <from>
To:      <to>
Repo:    <path>

(Pipeline not yet implemented — coming in next commits.)
```

Real orchestration is wired up once `fetch_release_notes.py` and `extract_breaking.py` are
ready.
