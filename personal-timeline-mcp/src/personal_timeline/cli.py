"""personal-timeline CLI — administrative subcommands.

Usage:
    personal-timeline init                  # bootstrap config + create the DB
    personal-timeline index                 # run a one-shot reindex
    personal-timeline watch [--interval N]  # loop: reindex every N seconds
    personal-timeline wipe                  # remove the index

The server itself is `personal-timeline-mcp` (in server.py). The CLI is for
out-of-band setup and maintenance.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
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
    print("  2. Run `personal-timeline index` to populate the timeline.")
    return 0


def cmd_wipe(args) -> int:
    """Delete the index database. Privacy escape hatch.

    Config is left untouched. Requires --yes to actually delete; without it,
    prints what *would* be removed and exits 0 so wiring it into a script is
    safe to dry-run.
    """
    cfg_path = Path(args.config).expanduser() if args.config else config.DEFAULT_CONFIG_PATH
    cfg = config.load(cfg_path)
    db_path = Path(args.db).expanduser() if args.db else cfg.db_path

    if not db_path.exists():
        print(f"No index at {db_path} — nothing to wipe.")
        return 0

    if not args.yes:
        print(f"Would delete: {db_path}")
        # SQLite WAL/SHM siblings ride along on a wipe.
        for suffix in ("-wal", "-shm", "-journal"):
            sibling = db_path.with_name(db_path.name + suffix)
            if sibling.exists():
                print(f"Would delete: {sibling}")
        print()
        print("Pass --yes to actually delete.")
        return 0

    db_path.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        sibling = db_path.with_name(db_path.name + suffix)
        if sibling.exists():
            sibling.unlink()
    print(f"Removed: {db_path}")
    return 0


def cmd_index(args) -> int:
    """Run a one-shot reindex over every enabled source.

    Equivalent to calling the server's `index_sources` tool, but invokable
    without launching the MCP server. Useful for cron / first-run setups.
    """
    cfg_path = Path(args.config).expanduser() if args.config else config.DEFAULT_CONFIG_PATH
    cfg = config.load(cfg_path)
    db_path = Path(args.db).expanduser() if args.db else cfg.db_path

    # Reuse the server's dispatcher so the CLI and MCP path stay in lockstep.
    # Set the env var first, then explicitly reset the cached connection in
    # case the server module was already imported by this process (tests).
    os.environ["PERSONAL_TIMELINE_DB"] = str(db_path)
    from . import server as srv

    srv.reset_connection()
    result = srv.index_sources(force_full=bool(args.force_full))
    print(f"Total ingested: {result['total_ingested']}")
    for source, outcome in result["results"].items():
        print(f"  {source:<10s} ingested={outcome.get('ingested', 0)}")
    if result["errors"]:
        print("Errors:")
        for err in result["errors"]:
            print(f"  - {err['source']}: {err['error']}")
        return 1
    return 0


def cmd_watch(args) -> int:
    """Reindex on a loop. Ctrl-C to stop.

    Calls the server's `index_sources` dispatcher on a fixed cadence so the
    timeline stays fresh without running a long-lived MCP session. `--once`
    makes the loop fire exactly one cycle (useful for cron / smoke tests).
    """
    cfg_path = Path(args.config).expanduser() if args.config else config.DEFAULT_CONFIG_PATH
    cfg = config.load(cfg_path)
    db_path = Path(args.db).expanduser() if args.db else cfg.db_path

    os.environ["PERSONAL_TIMELINE_DB"] = str(db_path)
    from . import server as srv

    srv.reset_connection()

    interval = max(1, int(args.interval))
    cycles = 0
    print(f"Watching DB={db_path} every {interval}s (Ctrl-C to stop)")
    try:
        while True:
            t0 = time.time()
            result = srv.index_sources(force_full=False)
            cycles += 1
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            took = time.time() - t0
            print(
                f"[{ts}] cycle={cycles} ingested={result['total_ingested']} "
                f"errors={len(result['errors'])} took={took:.2f}s"
            )
            if args.once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\nStopped after {cycles} cycle(s).")
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="personal-timeline",
        description="Local activity timeline — admin CLI for the MCP server.",
    )
    p.add_argument(
        "--config", help="path to config.toml (default: ~/.personal-timeline/config.toml)"
    )
    p.add_argument(
        "--db", help="path to index.db (default: from config or ~/.personal-timeline/index.db)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Bootstrap config + database")
    init_p.set_defaults(func=cmd_init)

    idx_p = sub.add_parser("index", help="Reindex every enabled source")
    idx_p.add_argument(
        "--force-full",
        action="store_true",
        help="Clear source_state first so every source rewalks from the start",
    )
    idx_p.set_defaults(func=cmd_index)

    watch_p = sub.add_parser("watch", help="Loop: reindex every N seconds")
    watch_p.add_argument(
        "--interval",
        default=300,
        type=int,
        help="Seconds between reindex passes (default: 300)",
    )
    watch_p.add_argument(
        "--once",
        action="store_true",
        help="Run one reindex cycle and exit (useful for cron / smoke tests)",
    )
    watch_p.set_defaults(func=cmd_watch)

    wipe_p = sub.add_parser("wipe", help="Delete the index database (privacy)")
    wipe_p.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete (without this flag, command is a dry-run)",
    )
    wipe_p.set_defaults(func=cmd_wipe)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
