"""Tests for the config loader, focused on the new ocr_languages knob."""

from __future__ import annotations

from pathlib import Path

import pytest
from screenshot_search import config


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_use_english_only():
    cfg = config.Config.defaults()
    assert cfg.ocr_languages == ["eng"]
    assert cfg.tesseract_lang() == "eng"


def test_loads_single_language(tmp_path: Path):
    p = _write(tmp_path / "config.toml", 'ocr_languages = ["spa"]\n')
    cfg = config.load(p)
    assert cfg.ocr_languages == ["spa"]
    assert cfg.tesseract_lang() == "spa"


def test_loads_multiple_languages_and_joins_with_plus(tmp_path: Path):
    p = _write(tmp_path / "config.toml", 'ocr_languages = ["eng", "spa", "deu"]\n')
    cfg = config.load(p)
    assert cfg.ocr_languages == ["eng", "spa", "deu"]
    assert cfg.tesseract_lang() == "eng+spa+deu"


def test_strips_whitespace_in_codes(tmp_path: Path):
    p = _write(tmp_path / "config.toml", 'ocr_languages = ["eng", " spa ", ""]\n')
    cfg = config.load(p)
    # Empty strings filtered out; whitespace stripped.
    assert cfg.ocr_languages == ["eng", "spa"]


def test_rejects_non_list(tmp_path: Path):
    p = _write(tmp_path / "config.toml", 'ocr_languages = "eng+spa"\n')
    with pytest.raises(ValueError, match="ocr_languages"):
        config.load(p)


def test_rejects_non_string_entries(tmp_path: Path):
    p = _write(tmp_path / "config.toml", "ocr_languages = [1, 2]\n")
    with pytest.raises(ValueError, match="ocr_languages"):
        config.load(p)


def test_bootstrap_mentions_ocr_languages(tmp_path: Path):
    target = tmp_path / "config.toml"
    config.bootstrap(target)
    body = target.read_text(encoding="utf-8")
    # The starter file should hint at the option even though it's commented out.
    assert "ocr_languages" in body


def test_empty_list_falls_back_to_eng():
    """`tesseract_lang` should never return an empty string — Tesseract would
    refuse the call."""
    cfg = config.Config(ocr_languages=[])
    assert cfg.tesseract_lang() == "eng"
