"""Tests for detect_manifest.

Covers npm / pyproject / cargo / composer manifest readers. Each test seeds
tmp_path with a manifest fixture and asserts the reader pulls out the right
dependency map without hitting any actual package registry.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import detect_manifest as dm

# -- npm -----------------------------------------------------------------------


def test_read_npm_collects_all_dependency_groups(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "myapp",
                "dependencies": {"react": "18.2.0", "lodash": "^4.17.0"},
                "devDependencies": {"jest": "29.0.0"},
                "peerDependencies": {"typescript": "^5.0.0"},
            }
        ),
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "npm"
    assert m["dependencies"] == {
        "react": "18.2.0",
        "lodash": "^4.17.0",
        "jest": "29.0.0",
        "typescript": "^5.0.0",
    }


def test_read_npm_handles_broken_json(tmp_path: Path):
    (tmp_path / "package.json").write_text("{not-json", encoding="utf-8")
    # Broken manifests are silently dropped — detect_manifest is best-effort.
    assert dm.detect(tmp_path) == []


# -- composer ------------------------------------------------------------------


def test_read_composer_filters_php_and_ext(tmp_path: Path):
    (tmp_path / "composer.json").write_text(
        json.dumps(
            {
                "name": "vendor/app",
                "require": {
                    "php": "^8.1",
                    "ext-mbstring": "*",
                    "lib-libxml": "*",
                    "monolog/monolog": "^3.0",
                    "symfony/console": "5.4.*",
                },
                "require-dev": {
                    "phpunit/phpunit": "^10.0",
                },
            }
        ),
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "composer"
    # php / ext-* / lib-* are platform constraints, not packages — must be dropped.
    assert "php" not in m["dependencies"]
    assert "ext-mbstring" not in m["dependencies"]
    assert "lib-libxml" not in m["dependencies"]
    assert m["dependencies"] == {
        "monolog/monolog": "^3.0",
        "symfony/console": "5.4.*",
        "phpunit/phpunit": "^10.0",
    }


def test_read_composer_handles_broken_json(tmp_path: Path):
    (tmp_path / "composer.json").write_text("{ broken", encoding="utf-8")
    assert dm.detect(tmp_path) == []


# -- npm package-lock.json -----------------------------------------------------


def test_read_package_lock_top_level(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "myapp",
                "lockfileVersion": 3,
                "packages": {
                    "": {"version": "1.0.0"},  # root package, has no name segment
                    "node_modules/react": {"version": "18.2.0"},
                    "node_modules/lodash": {"version": "4.17.21"},
                },
            }
        ),
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    # The root project ("" key) is filtered since it has no name segment.
    lock = next(m for m in out if m["ecosystem"] == "npm-lock")
    assert lock["dependencies"] == {
        "react": "18.2.0",
        "lodash": "4.17.21",
    }


def test_read_package_lock_handles_nested_deps(tmp_path: Path):
    """Nested deps use the last `node_modules/<name>` segment as the
    package name. If a package appears at multiple depths, the last
    occurrence wins (matches Node runtime resolution)."""
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/lodash": {"version": "4.17.20"},
                    "node_modules/some-pkg/node_modules/lodash": {"version": "4.17.21"},
                }
            }
        ),
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    lock = next(m for m in out if m["ecosystem"] == "npm-lock")
    # Last occurrence ("nested") wins.
    assert lock["dependencies"]["lodash"] == "4.17.21"


def test_read_package_lock_handles_broken_json(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text("{not json", encoding="utf-8")
    assert dm.detect(tmp_path) == []


def test_read_package_lock_coexists_with_package_json(tmp_path: Path):
    """A typical npm repo has both files; detect_manifest should surface both."""
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/react": {"version": "18.2.0"},
                }
            }
        ),
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    ecosystems = sorted(m["ecosystem"] for m in out)
    assert ecosystems == ["npm", "npm-lock"]
    npm = next(m for m in out if m["ecosystem"] == "npm")
    npm_lock = next(m for m in out if m["ecosystem"] == "npm-lock")
    # package.json reports the semver range; lockfile reports the resolved version.
    assert npm["dependencies"]["react"] == "^18.0.0"
    assert npm_lock["dependencies"]["react"] == "18.2.0"


# -- multi-manifest scan -------------------------------------------------------


def test_detect_returns_multiple_manifests(tmp_path: Path):
    """A polyglot repo with both package.json and composer.json should surface
    both manifests in one pass."""
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "18.0.0"}}), encoding="utf-8"
    )
    (tmp_path / "composer.json").write_text(
        json.dumps({"require": {"monolog/monolog": "^3.0"}}), encoding="utf-8"
    )
    out = dm.detect(tmp_path)
    ecosystems = sorted(m["ecosystem"] for m in out)
    assert ecosystems == ["composer", "npm"]


def test_detect_returns_empty_on_unrelated_dir(tmp_path: Path):
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    assert dm.detect(tmp_path) == []


# -- pyproject -----------------------------------------------------------------


def test_read_pyproject_pep621(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["requests>=2.31", "click>=8.0"]\n',
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    assert out[0]["ecosystem"] == "pypi"
    assert out[0]["dependencies"]["requests"] == ">=2.31"
    assert out[0]["dependencies"]["click"] == ">=8.0"


# -- cargo ---------------------------------------------------------------------


def test_read_cargo_inline_and_table_versions(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "x"\n'
        "[dependencies]\n"
        'serde = "1.0"\n'
        'tokio = { version = "1.35", features = ["full"] }\n'
        "[dev-dependencies]\n"
        'criterion = "0.5"\n',
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "cargo"
    assert m["dependencies"] == {
        "serde": "1.0",
        "tokio": "1.35",
        "criterion": "0.5",
    }
