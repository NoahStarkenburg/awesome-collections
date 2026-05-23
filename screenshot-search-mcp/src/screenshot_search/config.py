"""TOML config loader for screenshot-search-mcp.

Default location: ~/.screenshot-search/config.toml

Shape:
    db_path = "/path/to/index.db"      # optional; default ~/.screenshot-search/index.db
    watch_dirs = ["~/Pictures/Screenshots", "/data/screenshots"]
    debounce_seconds = 2.0             # optional
    recursive = true                   # optional

When the file is missing, `load()` returns Config.defaults() — no error. Use
`bootstrap()` to write a starter config on first run.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".screenshot-search" / "config.toml"
DEFAULT_DB_PATH = Path.home() / ".screenshot-search" / "index.db"


@dataclass
class Config:
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    watch_dirs: list[Path] = field(default_factory=list)
    debounce_seconds: float = 2.0
    recursive: bool = True
    ocr_languages: list[str] = field(default_factory=lambda: ["eng"])
    source: Path | None = None

    @classmethod
    def defaults(cls) -> Config:
        return cls()

    def tesseract_lang(self) -> str:
        """Return the `eng+spa+deu`-style joined string Tesseract expects."""
        return "+".join(self.ocr_languages) if self.ocr_languages else "eng"


def _expand(value) -> Path:
    return Path(value).expanduser()


def load(path: str | Path | None = None) -> Config:
    """Load config from `path`, the default location, or return defaults."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        return Config.defaults()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    cfg = Config(source=config_path)
    if "db_path" in data:
        cfg.db_path = _expand(data["db_path"])
    if "watch_dirs" in data:
        raw = data["watch_dirs"]
        if not isinstance(raw, list):
            raise ValueError("watch_dirs must be a list of strings")
        cfg.watch_dirs = [_expand(p) for p in raw]
    if "debounce_seconds" in data:
        cfg.debounce_seconds = float(data["debounce_seconds"])
    if "recursive" in data:
        cfg.recursive = bool(data["recursive"])
    if "ocr_languages" in data:
        raw = data["ocr_languages"]
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ValueError("ocr_languages must be a list of strings, e.g. ['eng', 'spa']")
        cfg.ocr_languages = [s.strip() for s in raw if s.strip()]
    return cfg


def bootstrap(path: str | Path | None = None) -> Path:
    """Write a starter config to `path` (default location). Returns the path written.

    Idempotent: never overwrites an existing file. Returns the existing path if
    it's already there.
    """
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# screenshot-search-mcp config\n"
        "# Uncomment and edit to suit your setup.\n"
        "\n"
        '# db_path = "~/.screenshot-search/index.db"\n'
        '# watch_dirs = ["~/Pictures/Screenshots"]\n'
        "# debounce_seconds = 2.0\n"
        "# recursive = true\n"
        "\n"
        "# OCR languages (ISO 639-2 codes). Each entry must have a matching\n"
        "# Tesseract language pack installed. Multiple = Tesseract tries all\n"
        '# of them at once: e.g. ["eng", "spa", "deu"].\n'
        '# ocr_languages = ["eng"]\n',
        encoding="utf-8",
    )
    return target
