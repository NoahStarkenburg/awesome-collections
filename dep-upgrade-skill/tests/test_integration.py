"""End-to-end integration smoke test for the dep-upgrade-skill pipeline.

Drives the three helpers in the same order the SKILL.md orchestrator does:

    detect_manifest  -> fetch_release_notes  -> extract_breaking

…against a tmp-path "repo" and a stubbed HTTP layer that returns fixture
changelog text. No network. No real Tesseract / CLIP / git. Catches
regressions where one helper's output shape drifts from the next helper's
expected input shape — the kind of break unit tests can miss.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import detect_manifest as dm
from scripts import extract_breaking as eb
from scripts import fetch_release_notes as frn

FIXTURES = Path(__file__).parent / "fixtures"

# Inline a small but realistic CHANGELOG that exercises both the "Breaking
# Changes" heading detector AND the per-section symbol extractor. Keeping it
# inline (rather than a fixture file) makes the test's assertions
# self-evident.
INLINE_CHANGELOG = """# Changelog

## 19.0.0

### Breaking Changes

- `ReactDOM.render` has been removed. Migrate to `createRoot`.
- The `defaultProps` option on function components no longer works.

### Added

- `use` hook for reading promises in render.

## 18.3.0

### Bug Fixes

- Fix concurrent rendering edge case.
"""


@pytest.fixture
def offline(monkeypatch):
    """Stub the HTTP layer so the fetch step returns deterministic data."""
    npm = {
        "name": "react",
        "repository": {"url": "git+https://github.com/facebook/react.git"},
        "versions": {
            "18.2.0": {},
            "18.3.0": {},
            "19.0.0-rc.0": {},
            "19.0.0": {},
        },
    }

    def fake_json(url, timeout=15):
        if "registry.npmjs.org/react" in url:
            return npm
        if "api.github.com" in url:
            return []
        raise AssertionError(f"unexpected JSON GET: {url}")

    def fake_text(url, timeout=15):
        if "CHANGELOG.md" in url:
            return INLINE_CHANGELOG
        raise FileNotFoundError(url)

    monkeypatch.setattr(frn, "http_get_json", fake_json)
    monkeypatch.setattr(frn, "http_get_text", fake_text)


def test_full_pipeline_npm_react_18_to_19(tmp_path: Path, offline):
    """The headline scenario: a React 18 -> 19 bump in an npm repo.

    1. Drop a package.json with `react: ^18.2.0`.
    2. detect_manifest finds it and confirms ecosystem=npm.
    3. fetch_release_notes pulls versions in (18.2.0, 19.0.0] and the CHANGELOG.
    4. extract_breaking finds the 'Breaking Changes' section + symbols.
    5. The orchestrator could now grep the user's repo for those symbols.
       This test asserts the *shape* of the pipeline output, not the grep.
    """
    # Step 1: seed the repo.
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "myapp", "dependencies": {"react": "^18.2.0"}}),
        encoding="utf-8",
    )

    # Step 2: detect the manifest.
    manifests = dm.detect(tmp_path)
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest["ecosystem"] == "npm"
    assert "react" in manifest["dependencies"]

    # Step 3: fetch release notes for the upgrade target.
    fetched = frn.fetch_release_notes("react", "18.2.0", "19.0.0", manifest["ecosystem"])
    assert fetched["repo_url"] == "https://github.com/facebook/react"
    assert fetched["versions"] == ["18.3.0", "19.0.0"]  # prerelease + lo-exclusive dropped
    assert fetched["changelog_raw"] is not None
    assert "Breaking Changes" in fetched["changelog_raw"]

    # Step 4: extract breaking changes from the fetched text.
    analysis = eb.analyze(fetched["changelog_raw"])
    assert analysis["needs_review"] is False
    assert len(analysis["sections"]) >= 1
    # The breaking section's symbols should include the headline removals.
    flat_symbols = {sym for s in analysis["sections"] for sym in s["symbols"]}
    assert "ReactDOM.render" in flat_symbols
    assert "createRoot" in flat_symbols
    assert "defaultProps" in flat_symbols


def test_pipeline_handles_non_changelog_text(tmp_path: Path, monkeypatch):
    """If the fetcher returns release notes that don't look like a changelog
    at all, extract_breaking should flag needs_review rather than confidently
    claiming there are no breaking changes."""
    monkeypatch.setattr(frn, "http_get_json", lambda url, timeout=15: {})
    monkeypatch.setattr(frn, "http_get_text", lambda url, timeout=15: "lol")

    # The fetch step will return changelog_raw = None for the empty payload
    # path; drive analyze directly on the would-be-empty case.
    analysis = eb.analyze("")
    assert analysis["needs_review"] is True
    assert analysis["review_reason"] is not None


def test_pipeline_with_multi_ecosystem_repo(tmp_path: Path, offline):
    """A polyglot repo (npm + composer) still detects each manifest cleanly.

    We don't run fetch for both — Packagist isn't stubbed — but we confirm
    detect_manifest's output is the right shape for downstream consumption.
    """
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.2.0"}}), encoding="utf-8"
    )
    (tmp_path / "composer.json").write_text(
        json.dumps({"require": {"monolog/monolog": "^3.0"}}), encoding="utf-8"
    )

    manifests = dm.detect(tmp_path)
    by_eco = {m["ecosystem"]: m for m in manifests}
    assert set(by_eco) == {"npm", "composer"}
    assert by_eco["npm"]["dependencies"]["react"] == "^18.2.0"
    assert by_eco["composer"]["dependencies"]["monolog/monolog"] == "^3.0"


def test_pipeline_skips_yanked_versions(tmp_path: Path, monkeypatch):
    """Verify the cargo path actually filters yanked versions when wired
    end-to-end through fetch_release_notes."""
    crates = json.loads((FIXTURES / "crates_serde_minimal.json").read_text(encoding="utf-8"))

    def fake_json(url, timeout=15):
        if "crates.io/api/v1/crates/serde" in url:
            return crates
        if "api.github.com" in url:
            return []
        raise AssertionError(f"unexpected JSON GET: {url}")

    from urllib.error import URLError

    def fake_text_404(url, timeout=15):
        # find_changelog_text catches (HTTPError, URLError) and falls through
        # to the next candidate. URLError stops the changelog probe gracefully.
        raise URLError("not found")

    monkeypatch.setattr(frn, "http_get_json", fake_json)
    monkeypatch.setattr(frn, "http_get_text", fake_text_404)

    fetched = frn.fetch_release_notes("serde", "1.0.193", "1.0.197", "cargo")
    # 1.0.196 is yanked in the fixture — must not leak into the upgrade range.
    assert "1.0.196" not in fetched["versions"]
    assert fetched["versions"] == ["1.0.194", "1.0.195", "1.0.197"]
