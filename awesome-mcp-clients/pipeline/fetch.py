#!/usr/bin/env python3
"""Fetch GitHub repo metadata and print a formatted markdown entry.

Usage:
    python fetch.py https://github.com/cline/cline
    python fetch.py cline/cline

Output (single line):
    - **[name](url)** — description. ⭐ stars · language · license · updated when

No third-party dependencies. Stdlib only.
Set GITHUB_TOKEN in env to lift rate limits.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_RE = re.compile(r"(?:https?://github\.com/)?([^/\s]+/[^/\s]+?)(?:\.git|/|$)")


def parse_repo(arg: str) -> str:
    m = REPO_RE.search(arg.strip())
    if not m:
        raise ValueError(f"Couldn't parse a github repo from: {arg!r}")
    return m.group(1)


def fetch(repo: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "awesome-collections-fetch/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"https://api.github.com/repos/{repo}", headers=headers)
    with urlopen(req, timeout=15) as r:
        return json.load(r)


def humanize_stars(n: int) -> str:
    if n >= 1_000:
        v = n / 1000
        s = f"{v:.1f}".rstrip("0").rstrip(".")
        return f"{s}k"
    return str(n)


def humanize_pushed(iso: str | None) -> str:
    if not iso:
        return "unknown"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (datetime.now(UTC) - dt).days
    if days <= 0:
        return "today"
    if days < 7:
        return f"{days}d ago"
    if days < 60:
        return f"{days // 7}w ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def format_entry(data: dict) -> str:
    name = data["name"]
    url = data["html_url"]
    desc = (data.get("description") or "No description").strip().rstrip(".")
    stars = humanize_stars(data.get("stargazers_count", 0))
    lic = (data.get("license") or {}).get("spdx_id") or "no-license"
    lang = data.get("language") or "—"
    pushed = humanize_pushed(data.get("pushed_at"))
    return f"- **[{name}]({url})** — {desc}. ⭐ {stars} · {lang} · {lic} · updated {pushed}"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python fetch.py <github-url-or-owner/repo>", file=sys.stderr)
        return 2
    try:
        repo = parse_repo(sys.argv[1])
        data = fetch(repo)
        print(format_entry(data))
        return 0
    except HTTPError as e:
        print(f"GitHub API error {e.code}: {e.reason}", file=sys.stderr)
        return 1
    except URLError as e:
        print(f"Network error: {e.reason}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
