#!/usr/bin/env python3
"""Extract 'Breaking changes' sections and the symbols they mention from a CHANGELOG.

Pipeline:
  1. Find breaking-change sections (regex on markdown headings).
  2. For each section, extract candidate symbols (backticks, ALL_CAPS, CamelCase,
     snake_case() calls). These are what `grep` will hunt for in the user's repo.
  3. If no breaking sections were found, set `needs_review` and return the raw
     text so the orchestrator can surface it for human review instead of
     silently dropping the upgrade.

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

# Phrases that suggest the input is a real changelog even without a 'Breaking' heading.
CHANGELOG_HINT_RE = re.compile(
    r"(?:^##\s*\[?\d+\.\d+|^v?\d+\.\d+\.\d+|changelog|release notes|unreleased)",
    re.I | re.M,
)
# Words that often introduce breaking changes inline when there's no dedicated section.
INLINE_BREAKING_RE = re.compile(
    r"\b(removed|deprecated|renamed|replaced|no longer|breaking|drop(?:ped)?\s+support|"
    r"requires?\s+\w+\s+\d|backwards?[ -]incompatible)\b",
    re.I,
)

# Symbol-extraction regexes. Order matters — backticks are most reliable.
BACKTICK_RE = re.compile(r"`([^`\n]{1,80})`")
CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(")
DOTTED_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
CAMEL_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)\b")
ALLCAPS_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")

# Words to drop from CamelCase/ALLCAPS hits — these are English, not symbols.
STOPWORDS = {
    "API",
    "APIS",
    "URL",
    "URLS",
    "URI",
    "URIS",
    "JSON",
    "YAML",
    "TOML",
    "XML",
    "HTTP",
    "HTTPS",
    "TLS",
    "SSL",
    "DNS",
    "TCP",
    "UDP",
    "IP",
    "CSS",
    "HTML",
    "JS",
    "TS",
    "DOM",
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "HEAD",
    "OPTIONS",
    "TODO",
    "FIXME",
    "NOTE",
    "WARNING",
    "ERROR",
    "INFO",
    "DEBUG",
    "ID",
    "IDS",
    "UUID",
    "UUIDS",
    "OS",
    "CPU",
    "GPU",
    "RAM",
    "IO",
    "FS",
    "AKA",
    "FAQ",
    "RFC",
    "PR",
    "PRS",
    "CI",
    "CD",
    "PHP",
    "SDK",
    "BREAKING",
    "CHANGES",
    "CHANGE",
    "MAJOR",
    "MINOR",
    "NodeJs",
    "JavaScript",
    "TypeScript",
    "GitHub",
    "GitLab",
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
        out.append(
            {
                "heading": title,
                "depth": depth,
                "start_line": text.count("\n", 0, m.start()) + 1,
                "content": text[start:end].strip(),
            }
        )
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


def looks_like_changelog(text: str) -> bool:
    """Heuristic: does this text look like release notes at all?"""
    return bool(CHANGELOG_HINT_RE.search(text))


def analyze(text: str) -> dict:
    """Top-level entry. Returns sections, per-section symbols, and a review flag.

    When no breaking sections are detected, sets `needs_review=True` and includes
    the raw text plus a reason. The orchestrator should surface this to the user
    instead of treating "no sections" as "no breaking changes".
    """
    sections = find_breaking_sections(text)
    for s in sections:
        s["symbols"] = extract_symbols(s["content"])

    needs_review = False
    review_reason = None
    if not sections:
        if not text.strip():
            review_reason = "Input was empty."
            needs_review = True
        elif looks_like_changelog(text):
            if INLINE_BREAKING_RE.search(text):
                review_reason = (
                    "Looks like a changelog with inline breaking-change language "
                    "(removed/deprecated/renamed/etc.) but no dedicated 'Breaking' "
                    "heading. Surface raw text for human review."
                )
            else:
                review_reason = (
                    "Looks like a changelog but no 'Breaking' heading was found. "
                    "Author may use a non-standard format — surface raw text."
                )
            needs_review = True
        else:
            review_reason = (
                "Input does not look like a markdown changelog. Surface raw "
                "text for manual review."
            )
            needs_review = True

    return {
        "sections": sections,
        "needs_review": needs_review,
        "review_reason": review_reason,
        "raw_text": text if needs_review else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Extract 'Breaking changes' sections and symbols from a CHANGELOG.",
    )
    p.add_argument("path", nargs="?", help="path to CHANGELOG file (omit to read stdin)")
    p.add_argument(
        "--sections-only",
        action="store_true",
        help="emit only the sections array (skip needs_review/raw_text)",
    )
    args = p.parse_args(argv)

    if args.path:
        with open(args.path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    if args.sections_only:
        sections = find_breaking_sections(text)
        for s in sections:
            s["symbols"] = extract_symbols(s["content"])
        json.dump({"sections": sections}, sys.stdout, indent=2)
    else:
        json.dump(analyze(text), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
