#!/usr/bin/env python3
"""Extract 'Breaking changes' sections from CHANGELOG markdown.

v1: regex-based section detection. Handles the most common heading conventions:
    ## Breaking Changes
    ### BREAKING CHANGES
    ## 💥 Breaking
    ### Breaking

Stdlib only. Symbol extraction (separate concern) lives in a sibling commit.

Usage:
    python extract_breaking.py CHANGELOG.md
    cat CHANGELOG.md | python extract_breaking.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# A heading is considered "breaking" if its text (stripped of decorations) matches.
BREAKING_PATTERNS = [
    re.compile(r"^breaking\s*changes?$", re.I),
    re.compile(r"^breaking$", re.I),
    re.compile(r"^major\s+changes?$", re.I),  # some projects use this synonym
]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def _normalize_heading(title: str) -> str:
    """Strip emoji, brackets, and other decorations from a heading title."""
    # Drop emoji/symbol prefixes by removing leading non-word, non-space chars
    cleaned = re.sub(r"^[^\w]+", "", title).strip()
    # Drop trailing decorations like " ⚠" or ":"
    cleaned = re.sub(r"[^\w\s]+$", "", cleaned).strip()
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def is_breaking_heading(title: str) -> bool:
    norm = _normalize_heading(title)
    return any(p.match(norm) for p in BREAKING_PATTERNS)


def find_breaking_sections(text: str) -> list[dict]:
    """Return all breaking-change sections in `text` (markdown CHANGELOG content).

    Each section: {heading, content, start_line, depth}.
    `content` is the text between this heading and the next heading of any depth.
    """
    headings = list(HEADING_RE.finditer(text))
    out: list[dict] = []
    for i, m in enumerate(headings):
        depth = len(m.group(1))
        title = m.group(2).strip()
        if not is_breaking_heading(title):
            continue
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()
        out.append({
            "heading": title,
            "depth": depth,
            "start_line": text.count("\n", 0, m.start()) + 1,
            "content": content,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extract 'Breaking changes' sections from a CHANGELOG markdown.")
    p.add_argument("path", nargs="?", help="path to CHANGELOG file (omit to read stdin)")
    args = p.parse_args(argv)

    if args.path:
        with open(args.path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    sections = find_breaking_sections(text)
    json.dump(sections, sys.stdout, indent=2)
    print()
    return 0 if sections else 0  # not finding any is not an error


if __name__ == "__main__":
    sys.exit(main())
