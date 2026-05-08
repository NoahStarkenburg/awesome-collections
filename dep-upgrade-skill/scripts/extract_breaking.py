#!/usr/bin/env python3
"""Extract 'Breaking changes' sections and the symbols they mention from a CHANGELOG.

Pipeline:
  1. Find breaking-change sections (regex on markdown headings).
  2. For each section, extract candidate symbols (backticks, ALL_CAPS, CamelCase,
     snake_case() calls). These are what `grep` will hunt for in the user's repo.

Stdlib only.

Usage:
    python extract_breaking.py CHANGELOG.md
    cat CHANGELOG.md | python extract_breaking.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys

BREAKING_PATTERNS = [
    re.compile(r"^breaking\s*changes?$", re.I),
    re.compile(r"^breaking$", re.I),
    re.compile(r"^major\s+changes?$", re.I),
]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

# Symbol-extraction regexes. Order matters — backticks are most reliable.
BACKTICK_RE = re.compile(r"`([^`\n]{1,80})`")
CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(")
DOTTED_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
CAMEL_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)\b")
ALLCAPS_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")

# Words to drop from CamelCase/ALLCAPS hits — these are English, not symbols.
STOPWORDS = {
    "API", "APIS", "URL", "URLS", "URI", "URIS", "JSON", "YAML", "TOML", "XML",
    "HTTP", "HTTPS", "TLS", "SSL", "DNS", "TCP", "UDP", "IP",
    "CSS", "HTML", "JS", "TS", "DOM",
    "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS",
    "TODO", "FIXME", "NOTE", "WARNING", "ERROR", "INFO", "DEBUG",
    "ID", "IDS", "UUID", "UUIDS",
    "OS", "CPU", "GPU", "RAM", "IO", "FS",
    "AKA", "FAQ", "RFC", "PR", "PRS", "CI", "CD", "PHP", "SDK",
    "BREAKING", "CHANGES", "CHANGE", "MAJOR", "MINOR",
    "NodeJs", "JavaScript", "TypeScript", "GitHub", "GitLab",
}


def _normalize_heading(title: str) -> str:
    cleaned = re.sub(r"^[^\w]+", "", title).strip()
    cleaned = re.sub(r"[^\w\s]+$", "", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned)


def is_breaking_heading(title: str) -> bool:
    return any(p.match(_normalize_heading(title)) for p in BREAKING_PATTERNS)


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
        out.append({
            "heading": title,
            "depth": depth,
            "start_line": text.count("\n", 0, m.start()) + 1,
            "content": text[start:end].strip(),
        })
    return out


def extract_symbols(content: str) -> list[str]:
    """Pull likely symbol names (functions, classes, constants, options) from prose.

    Heuristic-based. Returns a deduped list ordered by extraction weight: backticks
    rank highest, then dotted refs / snake_case() calls, then CamelCase / ALL_CAPS.
    Stopwords cut English noise.
    """
    found: dict[str, int] = {}

    def add(sym: str, weight: int) -> None:
        sym = sym.strip().strip(".,;:()[]{}'\"")
        if not sym or sym.upper() in STOPWORDS or sym in STOPWORDS:
            return
        if len(sym) < 2 or sym.isdigit():
            return
        found[sym] = max(found.get(sym, 0), weight)

    for m in BACKTICK_RE.finditer(content):
        token = m.group(1).strip()
        # Drop multi-word backtick spans unless they contain a call/dot (English in code voice).
        if " " in token and not re.search(r"[(.]", token):
            continue
        add(token, weight=4)

    for m in DOTTED_RE.finditer(content):
        add(m.group(1), weight=3)

    for m in CALL_RE.finditer(content):
        add(m.group(1) + "()", weight=3)

    for m in CAMEL_RE.finditer(content):
        add(m.group(1), weight=2)

    for m in ALLCAPS_RE.finditer(content):
        add(m.group(1), weight=2)

    return [s for s, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Extract 'Breaking changes' sections and symbols from a CHANGELOG.",
    )
    p.add_argument("path", nargs="?", help="path to CHANGELOG file (omit to read stdin)")
    args = p.parse_args(argv)

    if args.path:
        with open(args.path, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    sections = find_breaking_sections(text)
    for s in sections:
        s["symbols"] = extract_symbols(s["content"])
    json.dump({"sections": sections}, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
