"""Dominant-color computation for images.

`dominant_rgb(image_path)` returns the most common color (downsampled +
quantized) as a packed 0xRRGGBB int — small enough to store in a SQLite
INTEGER column without any new types. The packed-int form also makes
in-SQL distance math easy.

Stdlib + Pillow only; no numpy.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# How aggressively to shrink images before quantizing. 128 is plenty for
# dominant-color analysis and keeps the per-image cost in single-digit ms.
_RESIZE_TO = 128

# Number of palette colors to ask Pillow for. 4 buckets the image into 4
# coarse colors; we pick the most-used bucket as the dominant color.
_PALETTE_SIZE = 4


def parse_hex(hex_color: str) -> int:
    """Parse `#RRGGBB` (or `RRGGBB`) into a packed 0xRRGGBB int.

    Raises ValueError on bad input — callers should treat this as a 4xx-style
    user error, not a 5xx.
    """
    s = hex_color.strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Expected 6 hex digits, got {hex_color!r}")
    return int(s, 16)


def pack_rgb(r: int, g: int, b: int) -> int:
    return ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def unpack_rgb(packed: int) -> tuple[int, int, int]:
    return ((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)


def rgb_distance(a: int, b: int) -> int:
    """Squared Euclidean distance between two packed RGB ints.

    Squared rather than sqrt'd because we only ever compare against a
    threshold — saves a sqrt per row in the hot path.
    """
    ar, ag, ab = unpack_rgb(a)
    br, bg, bb = unpack_rgb(b)
    return (ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2


def dominant_rgb(image_path: str | Path) -> int | None:
    """Return the dominant color of `image_path` as a packed 0xRRGGBB int.

    Returns None if the file can't be opened (corrupt image, missing file,
    unsupported format). Never raises — callers can safely call this in
    bulk during indexing.
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover - Pillow is a hard dep
        return None

    path = Path(image_path)
    if not path.is_file():
        return None

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((_RESIZE_TO, _RESIZE_TO))
            quantized = img.quantize(colors=_PALETTE_SIZE)
            palette = quantized.getpalette() or []
            # `getcolors` returns [(count, palette_index), ...] sorted by count desc.
            counts = quantized.getcolors() or []
            if not counts:
                return None
            counts.sort(key=lambda kv: -kv[0])
            _, palette_index = counts[0]
            base = palette_index * 3
            if len(palette) < base + 3:
                return None
            return pack_rgb(palette[base], palette[base + 1], palette[base + 2])
    except (UnidentifiedImageError, OSError) as exc:
        log.debug("Cannot read image %s: %s", path, exc)
        return None
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Dominant-color failed for %s: %s", path, exc)
        return None
