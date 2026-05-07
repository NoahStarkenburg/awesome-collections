#!/usr/bin/env python3
"""Fetch release notes for a package between two versions.

v1: npm support. PyPI and disk caching come in subsequent commits.

Usage:
    python fetch_release_notes.py <package> --from <ver> --to <ver> [--ecosystem npm]

Output: JSON to stdout with keys:
    package, ecosystem, from_version, to_version, repo_url, versions, changelog_raw

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "dep-upgrade-skill/0.1 (+https://github.com/NoahStarkenburg/awesome-collections)"


def parse_semver(v: str) -> tuple[int, int, int, str]:
    """Parse 'x.y.z[-pre]' into a comparable tuple. Best-effort.

    The fourth element is the prerelease tag, or '~' for stable releases.
    '~' sorts AFTER any letter, so stable > prerelease, matching semver.
    """
    v = v.lstrip("v").strip()
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([\w.-]+))?", v)
    if not m:
        return (0, 0, 0, v)
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor), int(patch), pre or "~")


def is_stable(v: str) -> bool:
    return parse_semver(v)[3] == "~"


def in_range(v: str, lo: str, hi: str) -> bool:
    """True if lo < v <= hi. Prereleases are skipped."""
    if not is_stable(v):
        return False
    pv, plo, phi = parse_semver(v), parse_semver(lo), parse_semver(hi)
    return plo < pv <= phi


def http_get_json(url: str, timeout: int = 15) -> Any:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.load(r)


def http_get_text(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_repo_url(pkg_data: dict) -> str | None:
    """Extract canonical github URL from npm package metadata."""
    repo = pkg_data.get("repository")
    if not repo:
        return None
    if isinstance(repo, dict):
        repo = repo.get("url", "")
    if not isinstance(repo, str):
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+)", repo)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}"


def fetch_npm_metadata(package: str) -> dict:
    """Fetch package metadata from the npm registry."""
    return http_get_json(f"https://registry.npmjs.org/{package}")


def find_changelog_text(repo_url: str) -> str | None:
    """Try common CHANGELOG paths on the default branch of a github repo."""
    if "github.com" not in repo_url:
        return None
    parts = repo_url.rstrip("/").split("github.com/", 1)
    if len(parts) != 2:
        return None
    slug = parts[1]
    candidates = [
        f"https://raw.githubusercontent.com/{slug}/HEAD/CHANGELOG.md",
        f"https://raw.githubusercontent.com/{slug}/HEAD/CHANGELOG",
        f"https://raw.githubusercontent.com/{slug}/HEAD/CHANGES.md",
        f"https://raw.githubusercontent.com/{slug}/HEAD/HISTORY.md",
        f"https://raw.githubusercontent.com/{slug}/HEAD/docs/CHANGELOG.md",
    ]
    for candidate in candidates:
        try:
            text = http_get_text(candidate)
            if text.strip():
                return text
        except (HTTPError, URLError):
            continue
    return None


def fetch_release_notes(
    package: str,
    from_version: str,
    to_version: str,
    ecosystem: str = "npm",
) -> dict:
    if ecosystem != "npm":
        raise NotImplementedError(f"ecosystem={ecosystem!r} not yet supported (added in later commits)")

    meta = fetch_npm_metadata(package)
    versions = sorted(
        (v for v in meta.get("versions", {}) if in_range(v, from_version, to_version)),
        key=parse_semver,
    )
    repo_url = parse_repo_url(meta)
    changelog = find_changelog_text(repo_url) if repo_url else None

    return {
        "package": package,
        "ecosystem": ecosystem,
        "from_version": from_version,
        "to_version": to_version,
        "repo_url": repo_url,
        "versions": versions,
        "changelog_raw": changelog,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Fetch release notes for a package between two versions."
    )
    p.add_argument("package", help="package name (e.g. react, express)")
    p.add_argument("--from", dest="from_version", required=True, help="lower bound version (exclusive)")
    p.add_argument("--to", dest="to_version", required=True, help="upper bound version (inclusive)")
    p.add_argument("--ecosystem", default="npm", choices=["npm", "pypi"], help="package registry to query")
    args = p.parse_args(argv)
    try:
        result = fetch_release_notes(
            args.package, args.from_version, args.to_version, args.ecosystem
        )
    except NotImplementedError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except (HTTPError, URLError) as e:
        print(f"Network error: {e}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
