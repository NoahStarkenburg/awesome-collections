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
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = "dep-upgrade-skill/0.1 (+https://github.com/NoahStarkenburg/awesome-collections)"

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "dep-upgrade-skill"
DEFAULT_TTL_SECONDS = 3600  # 1 hour
_cache_ttl = DEFAULT_TTL_SECONDS  # mutable for --cache-ttl override
_cache_enabled = True


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / h


def cache_get(url: str) -> bytes | None:
    if not _cache_enabled:
        return None
    p = _cache_path(url)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > _cache_ttl:
        return None
    return p.read_bytes()


def cache_set(url: str, data: bytes) -> None:
    if not _cache_enabled:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(url).write_bytes(data)


def parse_semver(v: str) -> tuple[int, int, int, str]:
    """Parse 'x.y.z[suffix]' into a comparable tuple. Best-effort across semver and PEP 440.

    The fourth element is the prerelease tag, or '~' for stable releases.
    '~' sorts AFTER any letter, so stable > prerelease, matching semver semantics.

    Stable: '1.2.3', 'v1.2.3'
    Prerelease: '1.2.3-alpha', '1.2.3a1', '1.2.3rc1', '1.2.3.dev1', '1.2.3.post1'
    """
    v = v.lstrip("v").strip()
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", v)
    if not m:
        return (0, 0, 0, v)
    major, minor, patch, suffix = m.groups()
    suffix = suffix.lstrip("-+.")
    if re.search(r"[a-zA-Z]", suffix):
        return (int(major), int(minor), int(patch), suffix)
    return (int(major), int(minor), int(patch), "~")


def is_stable(v: str) -> bool:
    return parse_semver(v)[3] == "~"


def in_range(v: str, lo: str, hi: str) -> bool:
    """True if lo < v <= hi. Prereleases are skipped."""
    if not is_stable(v):
        return False
    pv, plo, phi = parse_semver(v), parse_semver(lo), parse_semver(hi)
    return plo < pv <= phi


def _request_headers(url: str, accept: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if "api.github.com" in url:
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def http_get_json(url: str, timeout: int = 15) -> Any:
    cached = cache_get(url)
    if cached is not None:
        return json.loads(cached)
    req = Request(url, headers=_request_headers(url, accept="application/json"))
    with urlopen(req, timeout=timeout) as r:
        body = r.read()
    cache_set(url, body)
    return json.loads(body)


def repo_slug(repo_url: str) -> str | None:
    """Extract 'owner/repo' from a github URL."""
    if "github.com" not in repo_url:
        return None
    parts = repo_url.rstrip("/").split("github.com/", 1)
    if len(parts) != 2:
        return None
    return parts[1]


def fetch_github_releases(repo_url: str, versions: list[str]) -> list[dict] | None:
    """Pull GitHub Releases for `repo_url` and filter to those matching `versions`.

    Used as a fallback when no CHANGELOG file is in the repo. Returns None on network
    failure or non-github repos.
    """
    slug = repo_slug(repo_url)
    if not slug:
        return None
    try:
        data = http_get_json(f"https://api.github.com/repos/{slug}/releases?per_page=100")
    except (HTTPError, URLError):
        return None

    wanted = {v for v in versions}
    out: list[dict] = []
    for r in data:
        tag = (r.get("tag_name") or "").lstrip("v")
        if tag in wanted:
            out.append(
                {
                    "version": tag,
                    "name": r.get("name") or "",
                    "body": r.get("body") or "",
                    "published_at": r.get("published_at") or "",
                    "html_url": r.get("html_url") or "",
                }
            )
    return out


def http_get_text(url: str, timeout: int = 15) -> str:
    cached = cache_get(url)
    if cached is not None:
        return cached.decode("utf-8", errors="replace")
    req = Request(url, headers=_request_headers(url))
    with urlopen(req, timeout=timeout) as r:
        body = r.read()
    cache_set(url, body)
    return body.decode("utf-8", errors="replace")


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


def fetch_pypi_metadata(package: str) -> dict:
    """Fetch package metadata from PyPI."""
    return http_get_json(f"https://pypi.org/pypi/{package}/json")


def fetch_packagist_metadata(package: str) -> dict:
    """Fetch package metadata from Packagist (PHP's registry).

    Packagist expects the canonical `vendor/package` shape — `monolog/monolog`,
    `symfony/console`. The v2 metadata endpoint returns a `packages` map
    keyed by name, with a list of per-version records.
    """
    return http_get_json(f"https://repo.packagist.org/p2/{package}.json")


def parse_repo_url_packagist(pkg_data: dict, package: str) -> str | None:
    """Extract canonical github URL from a Packagist v2 payload.

    The metadata returns a list of per-version entries — they should all
    agree on `source.url`, so we pick the first one.
    """
    packages = pkg_data.get("packages") or {}
    entries = packages.get(package) or []
    for entry in entries:
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, dict):
            continue
        url = source.get("url") or ""
        m = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+)", url)
        if m:
            return f"https://github.com/{m.group(1)}/{m.group(2)}"
    return None


def list_packagist_versions(pkg_data: dict, package: str) -> list[str]:
    """Pull version strings (without the `v` prefix) from a Packagist v2 payload."""
    packages = pkg_data.get("packages") or {}
    entries = packages.get(package) or []
    out: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        version = entry.get("version") or ""
        if isinstance(version, str) and version:
            out.append(version.lstrip("v"))
    return out


def fetch_crates_metadata(package: str) -> dict:
    """Fetch crate metadata from crates.io's v1 API.

    Crates.io requires a meaningful User-Agent and rejects empty ones — the
    project-wide USER_AGENT already passes that bar.
    """
    return http_get_json(f"https://crates.io/api/v1/crates/{package}")


def parse_repo_url_crates(pkg_data: dict) -> str | None:
    """Extract canonical github URL from a crates.io payload.

    crates.io stores the canonical repository URL in `crate.repository`.
    """
    crate = pkg_data.get("crate") or {}
    repo = crate.get("repository")
    if not isinstance(repo, str):
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+)", repo)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}"


def list_crates_versions(pkg_data: dict) -> list[str]:
    """Pull non-yanked version strings out of a crates.io payload."""
    versions = pkg_data.get("versions") or []
    return [
        v["num"]
        for v in versions
        if isinstance(v, dict) and isinstance(v.get("num"), str) and not v.get("yanked")
    ]


def parse_repo_url_pypi(pkg_data: dict) -> str | None:
    """Extract canonical github URL from PyPI package metadata."""
    info = pkg_data.get("info") or {}
    candidates: list[str] = []
    project_urls = info.get("project_urls") or {}
    if isinstance(project_urls, dict):
        candidates.extend(v for v in project_urls.values() if isinstance(v, str))
    for key in ("home_page", "package_url", "project_url"):
        val = info.get(key)
        if isinstance(val, str):
            candidates.append(val)
    for url in candidates:
        m = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+)", url)
        if m:
            return f"https://github.com/{m.group(1)}/{m.group(2)}"
    return None


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
    if ecosystem == "npm":
        meta = fetch_npm_metadata(package)
        all_versions = list((meta.get("versions") or {}).keys())
        repo_url = parse_repo_url(meta)
    elif ecosystem == "pypi":
        meta = fetch_pypi_metadata(package)
        all_versions = list((meta.get("releases") or {}).keys())
        repo_url = parse_repo_url_pypi(meta)
    elif ecosystem == "cargo":
        meta = fetch_crates_metadata(package)
        all_versions = list_crates_versions(meta)
        repo_url = parse_repo_url_crates(meta)
    elif ecosystem == "composer":
        meta = fetch_packagist_metadata(package)
        all_versions = list_packagist_versions(meta, package)
        repo_url = parse_repo_url_packagist(meta, package)
    else:
        raise NotImplementedError(f"ecosystem={ecosystem!r} not supported")

    versions = sorted(
        (v for v in all_versions if in_range(v, from_version, to_version)),
        key=parse_semver,
    )
    changelog = find_changelog_text(repo_url) if repo_url else None
    # Fall back to GitHub Releases when there's no CHANGELOG file.
    releases = fetch_github_releases(repo_url, versions) if (repo_url and not changelog) else None

    return {
        "package": package,
        "ecosystem": ecosystem,
        "from_version": from_version,
        "to_version": to_version,
        "repo_url": repo_url,
        "versions": versions,
        "changelog_raw": changelog,
        "releases": releases,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Fetch release notes for a package between two versions."
    )
    p.add_argument("package", help="package name (e.g. react, express)")
    p.add_argument(
        "--from", dest="from_version", required=True, help="lower bound version (exclusive)"
    )
    p.add_argument("--to", dest="to_version", required=True, help="upper bound version (inclusive)")
    p.add_argument(
        "--ecosystem",
        default="npm",
        choices=["npm", "pypi", "cargo", "composer"],
        help="package registry to query",
    )
    p.add_argument("--no-cache", action="store_true", help="bypass disk cache for this run")
    p.add_argument(
        "--cache-ttl",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help="cache TTL in seconds (default 3600)",
    )
    args = p.parse_args(argv)
    global _cache_enabled, _cache_ttl
    _cache_enabled = not args.no_cache
    _cache_ttl = args.cache_ttl
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
