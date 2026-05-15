"""personal-timeline CLI — administrative subcommands.

Usage:
    personal-timeline init     # bootstrap config + create the DB
    personal-timeline index    # run a one-shot reindex (added later)
    personal-timeline wipe     # remove the index (added later)

The server itself is `personal-timeline-mcp` (in server.py). The CLI is for
out-of-band setup and maintenance.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, store


def cmd_init(args) -> int:
    """Bootstrap config + DB. Idempotent — safe to re-run."""
    cfg_path = Path(args.config).expanduser() if args.config else config.DEFAULT_CONFIG_PATH
    written = config.bootstrap(cfg_path)
    cfg = config.load(written)
    db_path = Path(args.db).expanduser() if args.db else cfg.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = store.init_db(db_path)
    conn.close()
    print(f"Config:   {written}")
    print(f"Database: {db_path}")
    print()
    print("Next steps:")
    print(f"  1. Edit {written} — enable sources and point at your repos/dirs/ics files.")
    print( "  2. Run `personal-timeline index` to populate the timeline.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="personal-timeline",
        description="Local activity timeline — admin CLI for the MCP server.",
    )
    p.add_argument("--config", help="path to config.toml (default: ~/.personal-timeline/config.toml)")
    p.add_argument("--db", help="path to index.db (default: from config or ~/.personal-timeline/index.db)")
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Bootstrap config + database")
    init_p.set_defaults(func=cmd_init)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
