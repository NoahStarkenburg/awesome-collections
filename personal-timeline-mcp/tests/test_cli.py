"""Smoke tests for personal-timeline CLI subcommands.

Each test points the CLI at a tmp_path-scoped config + DB so it never touches
the user's real index. The `watch --once` test asserts the loop body fires
exactly one cycle and exits 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from personal_timeline import cli


@pytest.fixture(autouse=True)
def _reset_server_module():
    """Each CLI subcommand mutates the env var + reimports the server. Drop
    the cached modules between tests so state doesn't bleed."""
    for name in list(sys.modules):
        if name.startswith("personal_timeline"):
            del sys.modules[name]
    yield
    for name in list(sys.modules):
        if name.startswith("personal_timeline"):
            del sys.modules[name]


def _tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "config.toml", tmp_path / "index.db"


def test_init_creates_config_and_db(tmp_path: Path):
    cfg_path, db_path = _tmp_paths(tmp_path)
    rc = cli.main(["--config", str(cfg_path), "--db", str(db_path), "init"])
    assert rc == 0
    assert cfg_path.is_file()
    assert db_path.is_file()


def test_watch_once_runs_a_single_cycle(tmp_path: Path, capsys):
    cfg_path, db_path = _tmp_paths(tmp_path)
    cli.main(["--config", str(cfg_path), "--db", str(db_path), "init"])
    capsys.readouterr()  # drain init output

    rc = cli.main(
        [
            "--config",
            str(cfg_path),
            "--db",
            str(db_path),
            "watch",
            "--once",
            "--interval",
            "5",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "cycle=1" in out
    # Nothing's enabled in the fresh config so ingested must be 0 with no errors.
    assert "ingested=0" in out
    assert "errors=0" in out


def test_watch_handles_keyboard_interrupt(tmp_path: Path, monkeypatch, capsys):
    cfg_path, db_path = _tmp_paths(tmp_path)
    cli.main(["--config", str(cfg_path), "--db", str(db_path), "init"])
    capsys.readouterr()

    # Inject a KeyboardInterrupt on the first sleep — proves the loop exits
    # cleanly with rc=0 instead of propagating the exception.
    def fake_sleep(_seconds):
        raise KeyboardInterrupt()

    monkeypatch.setattr("personal_timeline.cli.time.sleep", fake_sleep)

    rc = cli.main(
        [
            "--config",
            str(cfg_path),
            "--db",
            str(db_path),
            "watch",
            "--interval",
            "1",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Stopped after 1 cycle" in out


def test_watch_subcommand_is_registered():
    """Argparse help should mention the watch subcommand. Catches a parser
    regression if someone deletes the registration."""
    parser = cli.build_parser()
    # subparsers are stored in the _subparsers_action's choices dict
    subparsers_action = next(
        a for a in parser._actions if isinstance(a, type(parser._subparsers._group_actions[0]))
    )
    assert "watch" in subparsers_action.choices
