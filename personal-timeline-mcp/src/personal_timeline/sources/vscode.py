"""VS Code recently-active workspace reader.

VS Code keeps per-workspace state under `User/workspaceStorage/<hash>/`. Each
such directory has a `workspace.json` pointing at the workspace's folder or
configuration file, plus a `state.vscdb` whose mtime updates whenever the
workspace's state changes. Reading the storage dir gives us a clean
"you were active in workspace X around time T" signal — distinct from the
filesystem source, which sees file changes but doesn't know which IDE
workspace was open.

We DON'T read `state.vscdb` (SQLite) for individual editor tabs — that surface
moves between VS Code versions and isn't worth the brittleness for v1. The
folder-level signal is the high-value one.

Public:
    locate_storage_dirs(flavor="code") -> list[Path]
    read_events(storage_dir, *, source_name="vscode", since_ts=None) -> Iterator[Event]
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..store import Event

log = logging.getLogger(__name__)


# `code` is regular VS Code; `code-insiders` and `vscodium` follow the same
# layout under different parent dirs. Extend the table if a new flavor lands.
_FLAVOR_PARENTS: dict[str, dict[str, str]] = {
    "win32": {
        "code": r"%APPDATA%\Code",
        "code-insiders": r"%APPDATA%\Code - Insiders",
        "vscodium": r"%APPDATA%\VSCodium",
    },
    "darwin": {
        "code": "~/Library/Application Support/Code",
        "code-insiders": "~/Library/Application Support/Code - Insiders",
        "vscodium": "~/Library/Application Support/VSCodium",
    },
    "linux": {
        "code": "~/.config/Code",
        "code-insiders": "~/.config/Code - Insiders",
        "vscodium": "~/.config/VSCodium",
    },
}


def locate_storage_dirs(flavor: str = "code") -> list[Path]:
    """Return any existing `User/workspaceStorage` dirs for the given flavor.

    Empty list if the flavor isn't installed on this platform.
    """
    table = _FLAVOR_PARENTS.get(sys.platform, {})
    raw = table.get(flavor)
    if not raw:
        return []
    expanded = Path(os.path.expandvars(raw)).expanduser()
    storage = expanded / "User" / "workspaceStorage"
    return [storage] if storage.is_dir() else []


def _decode_uri_to_path(uri: str) -> str | None:
    """Best-effort `file:///c%3A/foo/bar` -> `c:/foo/bar`. Returns None for
    non-file URIs (those are remote/SSH workspaces and we don't have a local
    path to attach mtimes to)."""
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    # urlparse leaves the path with a leading `/` even on Windows
    # (file:///c:/foo -> path='/c:/foo'). Strip the leading slash when the
    # next char is a drive letter.
    path = unquote(parsed.path)
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path or None


def _workspace_root(workspace_json: dict) -> str | None:
    """Extract a usable folder/configuration URI from a workspace.json blob."""
    for key in ("folder", "configuration"):
        value = workspace_json.get(key)
        if isinstance(value, str):
            return value
    return None


def read_events(
    storage_dir: str | Path,
    *,
    source_name: str = "vscode",
    since_ts: int | None = None,
) -> Iterator[Event]:
    """Yield one `Event` per VS Code workspace under `storage_dir`.

    Each event's `ts` is the storage dir's mtime (proxy for "last active in
    this workspace"). Empty dirs and ones with no parseable workspace.json
    are skipped silently — VS Code leaves orphaned entries behind regularly.
    """
    root = Path(storage_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(root)

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        ws_json = entry / "workspace.json"
        if not ws_json.is_file():
            continue
        try:
            mtime = int(entry.stat().st_mtime)
        except OSError:
            continue
        if since_ts is not None and mtime < since_ts:
            continue
        try:
            data = json.loads(ws_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.debug("Could not parse %s", ws_json)
            continue
        if not isinstance(data, dict):
            continue
        uri = _workspace_root(data)
        if not uri:
            continue
        local_path = _decode_uri_to_path(uri)
        title = Path(local_path).name if local_path else uri.rsplit("/", 1)[-1] or uri
        yield Event(
            source=source_name,
            source_id=f"workspace:{entry.name}",
            ts=mtime,
            title=title or "vscode workspace",
            body=local_path or uri,
            payload={
                "workspace_hash": entry.name,
                "uri": uri,
                "path": local_path,
                "flavor": source_name,
            },
        )
