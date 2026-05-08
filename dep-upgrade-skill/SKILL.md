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

## Step 2 — Fetch release notes

Run `scripts/fetch_release_notes.py <package> --from <from> --to <to> --ecosystem <npm|pypi>`.
The script returns JSON with `versions`, `repo_url`, `changelog_raw`, and (when no CHANGELOG
file is found) a `releases` array filled from GitHub Releases. Pipe the output through `jq`
or load it directly when chaining the next step.

If `versions` is empty, tell the user there are no stable releases between `from` and `to`
and stop. (Prereleases are skipped on purpose — the user is asking about a real bump.)

If both `changelog_raw` and `releases` are null, surface this as "no public release notes
found" and stop. The skill's value-add is cross-referencing notes; without notes there's
nothing to cross-reference.

## Step 3 — Extract breaking changes

Pipe the changelog text into `scripts/extract_breaking.py`:

```sh
echo "$changelog_raw" | python scripts/extract_breaking.py
```

You'll get either:
- `sections: [...]` — one or more breaking-change sections, each with `heading`, `content`,
  `start_line`, `depth`, and a `symbols` list (the names to grep for).
- `needs_review: true` — no dedicated breaking section was detected. Show the user the
  raw text + `review_reason` and let them decide what's worth checking. Don't fabricate.

When `releases` is populated instead of `changelog_raw`, run each release's `body` through
`extract_breaking` independently and merge the results.

## Step 4 — Grep the user's repo

For each unique symbol across all sections, search the repo using the `Grep` tool (NOT
`scripts/`-side — let the harness do this):

- Pattern: the symbol itself for backticks, dotted refs, ALL_CAPS, CamelCase. For
  `name()` entries, drop the `()` and search for the bare name (Grep will hit declarations
  and call sites both).
- Scope: the repo path the user provided. Skip `node_modules/`, `.venv/`, `dist/`,
  `build/`, `vendor/` — these are not the user's code.
- Output mode: `content` with `-n` so each hit comes back as `file:line:context`.

For each symbol that matches **at least one breaking section** AND **at least one file**,
record the file paths + line numbers. A symbol with zero hits in the user's repo is
nothing to report — that breaking change doesn't apply.

## Step 5 — Report (template added in next commit)

The reporter takes the (section × symbol × hits) cross-product and renders the markdown
report. Format and example output are wired up in the next commit.

## Activation prompt

When triggered, do not preview the steps to the user. Run them, then output the report.
Print one short progress line per step so the user knows what's happening:

```
1. Detected manifest: package.json (npm), react ^18.2.0 → 19.0.0
2. Fetched release notes: 3 versions, CHANGELOG.md found
3. Extracted breaking changes: 5 sections, 24 candidate symbols
4. Searching repo for symbol usage…
5. Report:
```

If any step yields zero output, say so plainly and stop. Don't fabricate findings.
