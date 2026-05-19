"""Tests for fetch_release_notes.

We mock the HTTP functions to keep tests offline and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import fetch_release_notes as frn

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# -- parse_semver / in_range ----------------------------------------------------


@pytest.mark.parametrize(
    "v,expected",
    [
        ("1.2.3", (1, 2, 3, "~")),
        ("v1.2.3", (1, 2, 3, "~")),
        ("1.0.0-alpha", (1, 0, 0, "alpha")),
        ("1.0.0a1", (1, 0, 0, "a1")),
        ("1.0.0rc1", (1, 0, 0, "rc1")),
        ("1.0.0.dev1", (1, 0, 0, "dev1")),
        ("not-a-version", (0, 0, 0, "not-a-version")),
    ],
)
def test_parse_semver(v, expected):
    assert frn.parse_semver(v) == expected


@pytest.mark.parametrize(
    "v,is_stable",
    [
        ("1.2.3", True),
        ("v1.2.3", True),
        ("2.0.0-rc.1", False),
        ("2.0.0a1", False),
        ("2.0.0.dev1", False),
    ],
)
def test_is_stable(v, is_stable):
    assert frn.is_stable(v) is is_stable


def test_in_range_excludes_lo_includes_hi():
    assert frn.in_range("18.3.0", "18.2.0", "19.0.0") is True
    assert frn.in_range("19.0.0", "18.2.0", "19.0.0") is True
    assert frn.in_range("18.2.0", "18.2.0", "19.0.0") is False  # exclusive lo
    assert frn.in_range("19.1.0", "18.2.0", "19.0.0") is False  # past hi


def test_in_range_skips_prereleases():
    assert frn.in_range("19.0.0-rc.0", "18.2.0", "19.0.0") is False
    assert frn.in_range("19.0.0rc1", "18.2.0", "19.0.0") is False


# -- repo URL parsing -----------------------------------------------------------


def test_parse_repo_url_npm_dict():
    meta = _load("npm_react_minimal.json")
    assert frn.parse_repo_url(meta) == "https://github.com/facebook/react"


def test_parse_repo_url_npm_handles_string():
    assert (
        frn.parse_repo_url({"repository": "git+ssh://git@github.com:foo/bar.git"})
        == "https://github.com/foo/bar"
    )


def test_parse_repo_url_npm_missing():
    assert frn.parse_repo_url({}) is None


def test_parse_repo_url_pypi():
    meta = _load("pypi_requests_minimal.json")
    assert frn.parse_repo_url_pypi(meta) == "https://github.com/psf/requests"


def test_repo_slug():
    assert frn.repo_slug("https://github.com/facebook/react") == "facebook/react"
    assert frn.repo_slug("https://gitlab.com/foo/bar") is None


# -- end-to-end fetch (mocked HTTP) --------------------------------------------


@pytest.fixture
def offline(monkeypatch):
    """Stub the network layer so tests don't hit the internet."""
    npm = _load("npm_react_minimal.json")
    pypi = _load("pypi_requests_minimal.json")
    crates = _load("crates_serde_minimal.json")
    changelog = (FIXTURES / "changelog_minimal.md").read_text(encoding="utf-8")

    def fake_json(url, timeout=15):
        if "registry.npmjs.org/react" in url:
            return npm
        if "pypi.org/pypi/requests/json" in url:
            return pypi
        if "crates.io/api/v1/crates/serde" in url:
            return crates
        if "api.github.com" in url and "releases" in url:
            return []
        raise AssertionError(f"unexpected JSON GET: {url}")

    def fake_text(url, timeout=15):
        if "CHANGELOG.md" in url:
            return changelog
        raise FileNotFoundError(url)

    monkeypatch.setattr(frn, "http_get_json", fake_json)
    monkeypatch.setattr(frn, "http_get_text", fake_text)


def test_fetch_release_notes_npm_filters_stable_in_range(offline):
    result = frn.fetch_release_notes("react", "18.2.0", "19.0.0", "npm")
    assert result["repo_url"] == "https://github.com/facebook/react"
    # 19.0.0-rc.0 is prerelease, 18.2.0 is lo-exclusive — both excluded.
    assert result["versions"] == ["18.3.0", "18.3.1", "19.0.0"]
    assert "Breaking Changes" in (result["changelog_raw"] or "")
    assert result["releases"] is None  # CHANGELOG was found → no fallback


def test_fetch_release_notes_pypi(offline):
    result = frn.fetch_release_notes("requests", "2.30.0", "2.32.0", "pypi")
    assert result["repo_url"] == "https://github.com/psf/requests"
    # 2.32.0rc1 prerelease excluded; 2.30.0 lo-exclusive excluded; 2.32.1 past hi excluded.
    assert result["versions"] == ["2.31.0", "2.32.0"]


def test_fetch_release_notes_unsupported_ecosystem():
    with pytest.raises(NotImplementedError):
        frn.fetch_release_notes("anything", "1.0.0", "2.0.0", "composer")


# -- crates.io / Cargo ---------------------------------------------------------


def test_parse_repo_url_crates():
    meta = _load("crates_serde_minimal.json")
    assert frn.parse_repo_url_crates(meta) == "https://github.com/serde-rs/serde"


def test_parse_repo_url_crates_missing():
    assert frn.parse_repo_url_crates({"crate": {}}) is None
    assert frn.parse_repo_url_crates({}) is None


def test_list_crates_versions_filters_yanked():
    meta = _load("crates_serde_minimal.json")
    # 1.0.196 is yanked in the fixture and must not appear.
    versions = frn.list_crates_versions(meta)
    assert "1.0.196" not in versions
    assert "1.0.197" in versions
    assert "2.0.0-rc.1" in versions  # yanked status, not stability — keep prerelease


def test_fetch_release_notes_cargo(offline):
    result = frn.fetch_release_notes("serde", "1.0.193", "1.0.197", "cargo")
    assert result["ecosystem"] == "cargo"
    assert result["repo_url"] == "https://github.com/serde-rs/serde"
    # 1.0.196 is yanked — excluded. 1.0.193 is lo-exclusive. 2.0.0-rc.1 is past hi.
    assert result["versions"] == ["1.0.194", "1.0.195", "1.0.197"]


# -- disk cache -----------------------------------------------------------------


def test_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(frn, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(frn, "_cache_enabled", True)
    monkeypatch.setattr(frn, "_cache_ttl", 3600)
    frn.cache_set("https://example.com/foo", b"hello")
    assert frn.cache_get("https://example.com/foo") == b"hello"
    assert frn.cache_get("https://example.com/missing") is None


def test_cache_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(frn, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(frn, "_cache_enabled", False)
    frn.cache_set("https://example.com/foo", b"hello")
    assert frn.cache_get("https://example.com/foo") is None
