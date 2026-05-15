"""Tesseract OCR wrapper.

Wraps `pytesseract` so callers don't have to handle:
  - the missing-binary case (returns empty string + logs a warning)
  - the empty-result case (returns empty string instead of erroring)
  - the unsupported-format case (Pillow raises; we catch and return empty)
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _configure_tesseract() -> bool:
    """Apply TESSERACT_CMD env var if set. Returns True if Tesseract is reachable."""
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - dependency declared in pyproject
        log.warning("pytesseract not installed; OCR disabled.")
        return False

    cmd = os.environ.get("TESSERACT_CMD")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception as exc:  # pytesseract.TesseractNotFoundError + friends
        log.warning("Tesseract binary not found: %s. OCR will return empty strings.", exc)
        return False


def extract_text(image_path: str | Path, *, lang: str = "eng") -> str:
    """Run OCR on `image_path` and return the recognized text. Never raises."""
    path = Path(image_path)
    if not path.is_file():
        return ""

    if not _configure_tesseract():
        return ""

    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image, UnidentifiedImageError  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        return ""

    try:
        with Image.open(path) as img:
            text = pytesseract.image_to_string(img, lang=lang)
    except (UnidentifiedImageError, OSError) as exc:
        log.debug("Cannot read image %s: %s", path, exc)
        return ""
    except Exception as exc:  # pytesseract.TesseractError, etc.
        log.warning("OCR failed for %s: %s", path, exc)
        return ""

    return text.strip()
