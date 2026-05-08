# Example: Express 4.18 → 5.0 upgrade impact

This walkthrough demonstrates the **fallback path** of `upgrade-impact`: what happens
when the project doesn't keep a `CHANGELOG.md` and the GitHub Release body uses
non-standard headings.

The release notes shown below were retrieved by `scripts/fetch_release_notes.py
express --from 4.18.0 --to 5.0.0` and analyzed by `scripts/extract_breaking.py`. The
sample-repo file paths are illustrative.

## Invocation

```
> /upgrade-impact express 4.18.0 5.0.0
```

## Progress lines

```
1. Detected manifest: package.json (npm), express ^4.18.0 → 5.0.0
2. Fetched release notes: 13 versions (no CHANGELOG.md, used GitHub Releases instead)
3. Extracted breaking changes: 0 dedicated sections — needs_review flagged
4. Surfacing raw release body…
5. Report:
```

## Why the fallback fires

Express formats its v5 release body as `### Major Changes in v5` — the trailing "in
v5" defeats the `^major\s+changes?$` heading detector by design (we don't want to
match arbitrary headings that happen to start with "Major Changes"). Combined with
the absence of a `CHANGELOG.md` file in the repo, no structured breaking-change
section is produced. The orchestrator switches to the manual-review path instead of
silently returning "no breaking changes".

## Report

````markdown
# Upgrade impact: express 4.18.0 → 5.0.0

## Manual review required

No structured breaking-change section was detected. Reason: Looks like a changelog
with inline breaking-change language (removed/deprecated/renamed/etc.) but no
dedicated 'Breaking' heading. Surface raw text for human review.

Raw release notes are pasted below — read them and let me know what to grep for.

---

# Express v5.0.0

🎉 **Express v5 is finally here!** 🎉

…

### Major Changes in v5

- **Node.js version support**: Dropped support for Node.js versions before v18.
- **Routing changes**: Updated to `path-to-regexp@8.x`, removing sub-expression
  regex patterns for security reasons (ReDoS mitigation).
- **Promise support**: Middleware can now return rejected promises, caught by the
  router as errors.
- **`body-parser` changes**: Several improvements including the ability to
  customize `urlencoded` body depth and defaulting `extended` to `false`.
- **Deprecated API methods removed**: Removed old, deprecated API method signatures
  from Express v3/v4.

For a complete list of breaking changes and API deprecations, see the
[migration guide](https://expressjs.com/en/guide/migrating-5.html).

…

---

Total: manual review pending — re-run with `--symbols path-to-regexp,urlencoded,extended` to grep for specific names.
````

## What this told the user

- The skill **didn't fail**: it correctly detected that the heuristics couldn't
  produce a clean structured report and handed back the raw text.
- The user can read the bullet list and pick the symbols they care about
  (`path-to-regexp`, `urlencoded`, `extended`, `body-parser`) and run `Grep` directly,
  or feed those symbols back into the skill.

## Hand-driven follow-up

```sh
# After reading the raw notes, the user (or Claude) re-runs the grep step manually:
grep -rn "path-to-regexp\|urlencoded\|body-parser" src/
grep -rn "extended:\s*true" src/
```

A real follow-up against a sample Express 4 repo turns up:

```
src/server.js:14  app.use(bodyParser.urlencoded({ extended: true }));
src/server.js:8   const bodyParser = require('body-parser');
src/middleware/parser.js:4  module.exports = bodyParser.urlencoded({ extended: true });
```

Two files use the v4 default `extended: true` for `urlencoded`. Under v5, the
default flips to `false`, so explicit `extended: true` is now required — a real,
silent breaking change that the manual grep caught. The user makes the change, and
the upgrade is unblocked.

## Takeaway for the skill design

The Express case shows why **never fabricate findings** is in `SKILL.md`: a
strict-pattern fallback that surfaces raw text is more useful than a confident-but-
wrong "no breaking changes detected" message would have been.
