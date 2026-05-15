"""Table-driven tests for extract_breaking against real-shape CHANGELOG snippets."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import extract_breaking as eb

FIXTURES = Path(__file__).parent / "fixtures"


# -- heading detection ---------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Breaking Changes", True),
        ("BREAKING CHANGES", True),
        ("breaking changes", True),
        ("Breaking change", True),
        ("Breaking", True),
        ("Major changes", True),
        ("Major Changes in v5", False),
        ("New Features", False),
        ("Bug Fixes", False),
    ],
)
def test_is_breaking_heading(title, expected):
    assert eb.is_breaking_heading(title) is expected


def test_normalize_strips_emoji_and_punctuation():
    assert eb._normalize_heading("💥 Breaking Changes ⚠") == "Breaking Changes"
    assert eb._normalize_heading("**Breaking**") == "Breaking"
    assert eb._normalize_heading("  Breaking   Changes  ") == "Breaking Changes"


# -- section extraction (table-driven over fixtures) ---------------------------

SECTION_CASES = [
    # (fixture filename, expected section count, expected first symbol substring)
    ("snippet_react_style.md", 1, "ReactDOM.render"),
    ("snippet_uppercase.md", 1, "parseQuery"),
    ("snippet_emoji.md", 1, "Logger.warn"),
    ("snippet_major_changes.md", 1, "NewClass"),
    ("snippet_h4_breaking.md", 1, "serialize_options"),
]


@pytest.mark.parametrize("filename,n_sections,sample_symbol", SECTION_CASES)
def test_section_extraction_from_fixture(filename, n_sections, sample_symbol):
    text = (FIXTURES / filename).read_text(encoding="utf-8")
    result = eb.analyze(text)
    assert result["needs_review"] is False
    assert len(result["sections"]) == n_sections
    flat_symbols = {s for sec in result["sections"] for s in sec["symbols"]}
    assert any(
        sample_symbol in s for s in flat_symbols
    ), f"Expected a symbol containing {sample_symbol!r}; got {flat_symbols!r}"


# -- needs_review fallback ------------------------------------------------------


def test_inline_breaking_without_heading_flags_review():
    text = (FIXTURES / "snippet_inline_only.md").read_text(encoding="utf-8")
    result = eb.analyze(text)
    assert result["needs_review"] is True
    assert "inline breaking-change language" in result["review_reason"]
    assert result["raw_text"] == text


def test_empty_input_flags_review():
    result = eb.analyze("")
    assert result["needs_review"] is True
    assert result["review_reason"] == "Input was empty."


def test_non_changelog_text_flags_review():
    result = eb.analyze("Hello world, this is unrelated prose with no relevant markers.")
    assert result["needs_review"] is True
    assert "does not look like a markdown changelog" in result["review_reason"]


def test_clean_changelog_with_breaking_skips_review():
    text = (FIXTURES / "snippet_react_style.md").read_text(encoding="utf-8")
    result = eb.analyze(text)
    assert result["needs_review"] is False
    assert result["raw_text"] is None


# -- symbol extractor ----------------------------------------------------------


def test_extract_symbols_prefers_backticks():
    syms = eb.extract_symbols("Removed `oldMethod()` and renamed `MyClass`.")
    # Both should appear; backtick-stripping removes trailing () from `oldMethod()`.
    assert "MyClass" in syms
    assert "oldMethod" in syms
    # And both should outrank anything from lower-weight passes.
    assert syms.index("MyClass") < 2
    assert syms.index("oldMethod") < 2


def test_extract_symbols_drops_stopwords():
    syms = eb.extract_symbols("The API now returns JSON instead of XML.")
    for stop in ("API", "JSON", "XML"):
        assert stop not in syms


def test_extract_symbols_finds_dotted_refs():
    syms = eb.extract_symbols("Use `foo.bar.baz` instead of the old form.")
    assert "foo.bar.baz" in syms


def test_extract_symbols_finds_all_caps_constants():
    syms = eb.extract_symbols("The `DEFAULT_TIMEOUT` constant was removed.")
    assert "DEFAULT_TIMEOUT" in syms


def test_extract_symbols_drops_short_and_numeric():
    syms = eb.extract_symbols("Bumped to 19 and 2.")
    # Bare numbers and 1-char tokens are filtered.
    assert "19" not in syms
    assert "2" not in syms


def test_extract_symbols_drops_multi_word_backtick_prose():
    # Backtick spans containing only English words (no `(` or `.`) should be ignored.
    syms = eb.extract_symbols("This change is `important to know` for users.")
    assert "important to know" not in syms
