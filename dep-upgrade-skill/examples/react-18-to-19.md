# Example: React 18.2 → 19.0 upgrade impact

This is an illustrative walkthrough of the `upgrade-impact` skill running against a small
fictional React 18 codebase. The release notes and symbols are pulled from the **real**
React `CHANGELOG.md` (verified by re-running `scripts/fetch_release_notes.py react --from
18.2.0 --to 19.0.0`); the file paths and line numbers below are from a sample repo created
to demonstrate output shape — yours will look different.

## Invocation

```
> /upgrade-impact react 18.2.0 19.0.0
```

## Progress lines

```
1. Detected manifest: package.json (npm), react ^18.2.0 → 19.0.0
2. Fetched release notes: 3 versions (18.3.0, 18.3.1, 19.0.0), CHANGELOG.md found
3. Extracted breaking changes: 1 dedicated v19 section, 11 candidate symbols
4. Searching repo for symbol usage…
5. Report:
```

## Report

````markdown
# Upgrade impact: react 18.2.0 → 19.0.0

Found **1** breaking change(s) that affect this repo across **3** file(s).
Versions covered: 18.3.0, 18.3.1, 19.0.0
Source: CHANGELOG.md (facebook/react)

---

## Breaking Changes (v19.0.0)

> Removed: `propTypes` and `defaultProps` for functions. PropTypes were deprecated in
> April 2017 (React 15.5.0). Removed: Legacy Context using contextTypes and
> getChildContext. Removed: string refs and `React.createFactory`. Removed:
> `ReactDOM.render`, `ReactDOM.hydrate` and `ReactDOM.unmountComponentAtNode`.

Affected symbols and call sites:

- `ReactDOM.render` — 2 hit(s)
  - `src/index.js:7` — `ReactDOM.render(<App />, document.getElementById('root'));`
  - `src/legacy-mount.js:14` — `ReactDOM.render(node, container);`
- `ReactDOM.hydrate` — 1 hit(s)
  - `src/ssr-entry.js:22` — `ReactDOM.hydrate(<App />, document.getElementById('root'));`
- `defaultProps` — 1 hit(s)
  - `src/components/Avatar.jsx:18` — `Avatar.defaultProps = { size: 'md' };`

## Symbols with no hits in this repo

These breaking changes do not appear to affect this repo, but verify manually for
indirect usage (re-exports, dynamic dispatch, string-keyed access):

`ReactDOM.unmountComponentAtNode`, `ReactDOM.unstable_batchedUpdates`,
`ReactDOM.unstable_renderIntoContainer`, `React.createFactory`,
`componentWillUnmount`, `componentWillMount`, `prevContext`

---

Total: 3 file(s) need review across 1 change(s).
````

## What this told the user

- **Three files need to change** before bumping to React 19. Two `ReactDOM.render` call
  sites switch to `createRoot(...).render(...)`. The SSR entry switches to `hydrateRoot`.
- **One `defaultProps` usage** on a function component — needs to move to JS default
  parameters.
- The "no hits" list confirms several other breaking changes don't apply to this repo, so
  the reviewer can focus their attention.

## Reproducing on your own repo

```sh
cd my-react-app
python /path/to/dep-upgrade-skill/scripts/detect_manifest.py . --package react
python /path/to/dep-upgrade-skill/scripts/fetch_release_notes.py react \
    --from 18.2.0 --to 19.0.0 --ecosystem npm > /tmp/react.json
python -c "
import json
from scripts.extract_breaking import analyze
data = json.load(open('/tmp/react.json'))
result = analyze(data['changelog_raw'])
for s in result['sections']:
    print(s['heading'], '→', s['symbols'][:10])
"
```

Then have Claude Code grep each symbol against the repo and apply the report template
from `SKILL.md` step 5.
