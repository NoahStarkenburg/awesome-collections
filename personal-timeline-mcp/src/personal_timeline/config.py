"""TOML config loader for personal-timeline-mcp.

Default location: ~/.personal-timeline/config.toml

Shape:
    db_path = "~/.personal-timeline/index.db"

    [sources.chrome]
    enabled = true
    # profile_dir = "~/AppData/Local/Google/Chrome/User Data/Default"  # optional override

    [sources.firefox]
    enabled = true
    # profile_dir = "..."

    [sources.git]
    enabled = true
    repos = ["~/code/projectA", "~/code/projectB"]
    author_email = "you@example.com"   # only your commits

    [sources.filesystem]
    enabled = true
    dirs = ["~/Documents/notes", "~/code"]
    ignore = [".git", "node_modules", "__pycache__", ".venv"]

    [sources.calendar]
    enabled = true
    ics_paths = ["~/.calendar/personal.ics"]

When the file is missing, `load()` returns Config.defaults() — no error. Use
`bootstrap()` to write a starter on first run.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".personal-timeline" / "config.toml"
DEFAULT_DB_PATH = Path.home() / ".personal-timeline" / "index.db"
DEFAULT_IGNORE = [".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"]


@dataclass
class SourceConfig:
    enabled: bool = False
    options: dict = field(default_factory=dict)


@dataclass
class Config:
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    source: Path | None = None  # path the config was loaded from

    @classmethod
    def defaults(cls) -> Config:
        return cls(
            sources={
                "chrome": SourceConfig(enabled=False),
                "firefox": SourceConfig(enabled=False),
                "safari": SourceConfig(enabled=False),
                "git": SourceConfig(enabled=False, options={"repos": [], "author_email": None}),
                "filesystem": SourceConfig(
                    enabled=False, options={"dirs": [], "ignore": list(DEFAULT_IGNORE)}
                ),
                "calendar": SourceConfig(enabled=False, options={"ics_paths": []}),
            }
        )

    def enabled_sources(self) -> list[str]:
        return [name for name, sc in self.sources.items() if sc.enabled]


def _expand(value) -> Path:
    return Path(value).expanduser()


def load(path: str | Path | None = None) -> Config:
    """Load config from `path`, the default location, or return defaults."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        return Config.defaults()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    cfg = Config.defaults()
    cfg.source = config_path
    if "db_path" in data:
        cfg.db_path = _expand(data["db_path"])

    src_block = data.get("sources") or {}
    for name, raw in src_block.items():
        if not isinstance(raw, dict):
            continue
        enabled = bool(raw.get("enabled", False))
        opts = {k: v for k, v in raw.items() if k != "enabled"}
        # Expand any path-like fields so downstream readers don't have to.
        if "repos" in opts and isinstance(opts["repos"], list):
            opts["repos"] = [str(_expand(p)) for p in opts["repos"]]
        if "dirs" in opts and isinstance(opts["dirs"], list):
            opts["dirs"] = [str(_expand(p)) for p in opts["dirs"]]
        if "ics_paths" in opts and isinstance(opts["ics_paths"], list):
            opts["ics_paths"] = [str(_expand(p)) for p in opts["ics_paths"]]
        if "profile_dir" in opts:
            opts["profile_dir"] = str(_expand(opts["profile_dir"]))
        cfg.sources[name] = SourceConfig(enabled=enabled, options=opts)
    return cfg


STARTER_TOML = """# personal-timeline-mcp config
# Uncomment and edit the sources you want to index. All paths can use ~.

# db_path = "~/.personal-timeline/index.db"

[sources.chrome]
enabled = false
# profile_dir = "~/AppData/Local/Google/Chrome/User Data/Default"

[sources.firefox]
enabled = false

[sources.safari]
enabled = false
# macOS only. Auto-locates ~/Library/Safari/History.db.
# history_db = "~/Library/Safari/History.db"  # optional override

[sources.git]
enabled = false
repos = []
# author_email = "you@example.com"

[sources.filesystem]
enabled = false
dirs = []
ignore = [".git", "node_modules", "__pycache__", ".venv"]

[sources.calendar]
enabled = false
ics_paths = []
"""


def bootstrap(path: str | Path | None = None) -> Path:
    """Write a starter config. Idempotent — won't overwrite an existing file."""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(STARTER_TOML, encoding="utf-8")
    return target
