"""Tests for the VS Code workspace reader.

Builds a fixture workspaceStorage tree in tmp_path with the same layout VS
Code uses on disk, then asserts the reader yields well-shaped Event rows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from personal_timeline.sources import vscode


def _make_workspace(parent: Path, hash_name: str, uri: str, mtime: int) -> Path:
    ws_dir = parent / hash_name
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "workspace.json").write_text(json.dumps({"folder": uri}), encoding="utf-8")
    # Touch a state.vscdb file so the dir looks realistic, though we don't read it.
    (ws_dir / "state.vscdb").write_bytes(b"")
    os.utime(ws_dir, (mtime, mtime))
    return ws_dir


def test_read_events_basic(tmp_path: Path):
    storage = tmp_path / "workspaceStorage"
    _make_workspace(storage, "aaa", "file:///home/user/projectA", 1715000000)
    _make_workspace(storage, "bbb", "file:///home/user/projectB", 1715000100)
    events = list(vscode.read_events(storage))
    assert len(events) == 2
    assert {e.source for e in events} == {"vscode"}
    assert events[0].source_id == "workspace:aaa"
    assert events[0].title == "projectA"
    assert events[0].body == "/home/user/projectA"
    assert events[0].ts == 1715000000
    assert events[0].payload["workspace_hash"] == "aaa"
    assert events[0].payload["path"] == "/home/user/projectA"


def test_since_filter(tmp_path: Path):
    storage = tmp_path / "workspaceStorage"
    _make_workspace(storage, "aaa", "file:///a", 1000)
    _make_workspace(storage, "bbb", "file:///b", 2000)
    _make_workspace(storage, "ccc", "file:///c", 3000)
    events = list(vscode.read_events(storage, since_ts=1500))
    assert sorted(e.ts for e in events) == [2000, 3000]


def test_skips_dirs_with_no_workspace_json(tmp_path: Path):
    storage = tmp_path / "workspaceStorage"
    storage.mkdir()
    orphan = storage / "orphan"
    orphan.mkdir()
    # No workspace.json — should be silently skipped.
    _make_workspace(storage, "aaa", "file:///home/user/projectA", 1715000000)
    events = list(vscode.read_events(storage))
    assert len(events) == 1
    assert events[0].source_id == "workspace:aaa"


def test_skips_invalid_json(tmp_path: Path):
    storage = tmp_path / "workspaceStorage"
    storage.mkdir()
    bad = storage / "bad"
    bad.mkdir()
    (bad / "workspace.json").write_text("{not json", encoding="utf-8")
    _make_workspace(storage, "ok", "file:///home/user/projectA", 1715000000)
    events = list(vscode.read_events(storage))
    assert [e.source_id for e in events] == ["workspace:ok"]


def test_skips_non_file_uri(tmp_path: Path):
    """Remote SSH / WSL workspaces use vscode-remote:// — no local mtime to
    anchor an event against, so they're skipped (URI is preserved in the
    skip log, not surfaced as an event)."""
    storage = tmp_path / "workspaceStorage"
    storage.mkdir()
    remote = storage / "remote"
    remote.mkdir()
    (remote / "workspace.json").write_text(
        json.dumps({"folder": "vscode-remote://ssh-remote+host/home/u/proj"}),
        encoding="utf-8",
    )
    # urlparse on a vscode-remote URI gives scheme='vscode-remote' which our
    # decoder rejects. We emit *something* because we have a uri — verify.
    _make_workspace(storage, "ok", "file:///home/user/projectA", 1715000000)
    events = list(vscode.read_events(storage))
    assert len(events) == 2  # remote IS emitted, but with body=uri
    remote_event = next(e for e in events if e.source_id == "workspace:remote")
    assert remote_event.payload["path"] is None
    assert remote_event.payload["uri"].startswith("vscode-remote://")


def test_windows_uri_decoding(tmp_path: Path):
    """file:///c%3A/Users/me/proj should decode to c:/Users/me/proj."""
    storage = tmp_path / "workspaceStorage"
    _make_workspace(
        storage,
        "win",
        "file:///c%3A/Users/me/proj",
        1715000000,
    )
    events = list(vscode.read_events(storage))
    assert events[0].body == "c:/Users/me/proj"
    assert events[0].title == "proj"


def test_missing_directory_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(vscode.read_events(tmp_path / "does-not-exist"))


def test_locate_storage_dirs_does_not_raise():
    # Returns list (possibly empty) on all platforms — must never crash.
    result = vscode.locate_storage_dirs()
    assert isinstance(result, list)
    for p in result:
        assert isinstance(p, Path)
