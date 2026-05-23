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


# -- --check-only CLI flag -----------------------------------------------------


def test_check_only_lists_ecosystems(tmp_path: Path, capsys):
    """`--check-only` prints one ecosystem name per line, sorted, deduped,
    and exits 0."""
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}}), encoding="utf-8"
    )
    (tmp_path / "composer.json").write_text(
        json.dumps({"require": {"monolog/monolog": "^3.0"}}), encoding="utf-8"
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/react": {"version": "18.2.0"}}}),
        encoding="utf-8",
    )

    rc = dm.main([str(tmp_path), "--check-only"])
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    # Alphabetical, deduplicated.
    assert out == ["composer", "npm", "npm-lock"]


def test_check_only_exits_nonzero_when_empty(tmp_path: Path, capsys):
    (tmp_path / "README.md").write_text("nothing", encoding="utf-8")
    rc = dm.main([str(tmp_path), "--check-only"])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_check_only_does_not_emit_json(tmp_path: Path, capsys):
    """Make sure the precheck mode doesn't also dump the JSON manifest list
    — a downstream `gh actions if` would choke on the extra output."""
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}}), encoding="utf-8"
    )
    dm.main([str(tmp_path), "--check-only"])
    out = capsys.readouterr().out
    assert "{" not in out  # no JSON object opener
    assert out.strip() == "npm"


# -- Maven (pom.xml) -----------------------------------------------------------


def test_read_maven_pom_basic(tmp_path: Path):
    (tmp_path / "pom.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>app</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-core</artifactId>
      <version>6.0.0</version>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>4.13.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
""",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "maven"
    assert m["dependencies"] == {
        "org.springframework:spring-core": "6.0.0",
        "junit:junit": "4.13.2",
    }


def test_read_maven_pom_skips_deps_without_version(tmp_path: Path):
    """Dependencies that inherit version from dependencyManagement or a
    parent pom don't carry a <version> here. Skipping them keeps the v1
    surface unambiguous — upgrade-impact would lie about a version we
    don't actually know."""
    (tmp_path / "pom.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>has-version</artifactId>
      <version>1.0.0</version>
    </dependency>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>inherits-from-parent</artifactId>
    </dependency>
  </dependencies>
</project>
""",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert out[0]["dependencies"] == {"org.example:has-version": "1.0.0"}


def test_read_maven_pom_handles_no_namespace(tmp_path: Path):
    """Some hand-written poms omit the namespace declaration. Should still parse."""
    (tmp_path / "pom.xml").write_text(
        "<project>"
        "<dependencies>"
        "<dependency>"
        "<groupId>foo</groupId><artifactId>bar</artifactId><version>2.0</version>"
        "</dependency>"
        "</dependencies>"
        "</project>",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert out[0]["dependencies"] == {"foo:bar": "2.0"}


def test_read_maven_pom_handles_broken_xml(tmp_path: Path):
    (tmp_path / "pom.xml").write_text("<project><unclosed", encoding="utf-8")
    assert dm.detect(tmp_path) == []


# -- requirements.txt ----------------------------------------------------------


def test_read_requirements_txt_basic(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "# top-level comment\n"
        "requests>=2.31\n"
        "click==8.1.7\n"
        "rich  # inline comment, no pin\n"
        "django>=4.0,<5  ; python_version >= '3.10'\n"
        "\n"
        "-r dev-requirements.txt\n"
        "-e .\n"
        "--index-url https://pypi.org/simple\n",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "pypi-requirements"
    assert m["dependencies"] == {
        "requests": ">=2.31",
        "click": "==8.1.7",
        "rich": "",
        "django": ">=4.0,<5",
    }


def test_read_requirements_txt_coexists_with_pyproject(tmp_path: Path):
    """A repo with both pyproject and requirements.txt surfaces both."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["requests>=2.31"]\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    ecosystems = sorted(m["ecosystem"] for m in dm.detect(tmp_path))
    assert ecosystems == ["pypi", "pypi-requirements"]


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


# -- rubygems / Gemfile --------------------------------------------------------


def test_read_gemfile_parses_gem_lines(tmp_path: Path):
    (tmp_path / "Gemfile").write_text(
        "source 'https://rubygems.org'\n"
        "ruby '3.2.0'\n"
        "\n"
        "gem 'rails', '~> 7.0'\n"
        "gem \"pg\", '>= 1.4'\n"
        "gem 'redis'\n"
        "# gem 'commented_out', '1.0'\n"
        "\n"
        "group :development do\n"
        "  gem 'rspec', '~> 3.12'\n"
        "end\n",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "rubygems"
    assert m["dependencies"] == {
        "rails": "~> 7.0",
        "pg": ">= 1.4",
        "redis": "",  # no version specified
        "rspec": "~> 3.12",
    }


def test_read_gemfile_ignores_runtime_directive(tmp_path: Path):
    """The `ruby '3.2.0'` line shouldn't end up as a package."""
    (tmp_path / "Gemfile").write_text(
        "ruby '3.2.0'\ngem 'rails', '~> 7.0'\n",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    deps = out[0]["dependencies"]
    assert "rails" in deps
    assert "ruby" not in deps


# -- go modules ----------------------------------------------------------------


def test_read_gomod_parses_block_and_single(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        "module example.com/foo\n"
        "\n"
        "go 1.21\n"
        "\n"
        "require (\n"
        "    github.com/foo/bar v1.2.3\n"
        "    github.com/baz/qux v0.0.0-20240101120000-abcdef1234567\n"
        ")\n"
        "\n"
        "require github.com/single v0.5.0\n",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    assert len(out) == 1
    m = out[0]
    assert m["ecosystem"] == "gomod"
    assert m["dependencies"] == {
        "github.com/foo/bar": "v1.2.3",
        "github.com/baz/qux": "v0.0.0-20240101120000-abcdef1234567",
        "github.com/single": "v0.5.0",
    }


def test_read_gomod_skips_indirect(tmp_path: Path):
    (tmp_path / "go.mod").write_text(
        "require (\n"
        "    github.com/foo/bar v1.0.0\n"
        "    github.com/transitive/dep v0.1.0 // indirect\n"
        ")\n",
        encoding="utf-8",
    )
    out = dm.detect(tmp_path)
    deps = out[0]["dependencies"]
    assert "github.com/foo/bar" in deps
    assert "github.com/transitive/dep" not in deps


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
