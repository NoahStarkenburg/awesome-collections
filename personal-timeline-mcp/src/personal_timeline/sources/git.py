"""Git commit reader.

Walks one or more local git repositories and yields commit Events. Uses the
`git` CLI via subprocess — no pygit2 dependency, no libgit2 install.

Public:
    list_commits(repo_path, *, since_ts=None, author_email=None, max_count=None)
    read_events(repo_path, *, since_ts=None, author_email=None)
    ingest_repo(conn, repo_path, *, author_email=None) — incremental, uses
        source_state to remember the last commit ts ingested per repo.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterator
from pathlib import Path

from ..store import Event

log = logging.getLogger(__name__)

# Use a delimiter unlikely to appear in commit messages. NUL bytes work nicely.
_GIT_FORMAT = "%H%x1f%an%x1f%ae%x1f%at%x1f%s"


def _run_git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo)] + args,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout


def list_commits(
    repo_path: str | Path,
    *,
    since_ts: int | None = None,
    author_email: str | None = None,
    max_count: int | None = None,
) -> list[dict]:
    """Return commit records as plain dicts. Pure function — easy to test.

    Each record: {sha, author_name, author_email, ts, subject, files}.
    """
    repo = Path(repo_path).expanduser().resolve()
    if not (repo / ".git").exists() and not repo.is_dir():
        raise FileNotFoundError(f"Not a git repo: {repo}")

    args = ["log", f"--pretty=format:{_GIT_FORMAT}", "--name-only", "-z"]
    if since_ts is not None:
        args += [f"--since=@{since_ts}"]
    if author_email is not None:
        args += [f"--author={author_email}"]
    if max_count is not None:
        args += ["-n", str(max_count)]
    out = _run_git(repo, args)
    return list(_parse_z_log(out))


def _parse_z_log(text: str) -> Iterator[dict]:
    """Parse `git log -z --name-only --pretty=format:...` output.

    Layout per commit:
        <sha>\\x1f<name>\\x1f<email>\\x1f<ts>\\x1f<subject>\\n<file1>\\n<file2>...
    Commits are NUL-separated, with a second NUL between records.
    """
    if not text:
        return
    for record in text.split("\x00"):
        if not record.strip():
            continue
        head, _, rest = record.partition("\n")
        try:
            sha, name, email, ts, subject = head.split("\x1f")
        except ValueError:
            continue
        files = [line for line in rest.split("\n") if line]
        yield {
            "sha": sha,
            "author_name": name,
            "author_email": email,
            "ts": int(ts),
            "subject": subject,
            "files": files,
        }


def read_events(
    repo_path: str | Path,
    *,
    since_ts: int | None = None,
    author_email: str | None = None,
) -> Iterator[Event]:
    """Yield commit Events from `repo_path`."""
    repo = Path(repo_path).expanduser().resolve()
    repo_label = repo.name
    for c in list_commits(repo, since_ts=since_ts, author_email=author_email):
        yield Event(
            source="git",
            source_id=f"{repo_label}:{c['sha']}",
            ts=c["ts"],
            title=c["subject"],
            body=" ".join(c["files"]),
            payload={
                "sha": c["sha"],
                "repo": str(repo),
                "author_name": c["author_name"],
                "author_email": c["author_email"],
                "files": c["files"],
            },
        )


def _source_key(repo_path: Path) -> str:
    """source_state key for a given repo. Uses absolute path so two `proj/`
    folders in different parents don't collide."""
    return f"git:{repo_path.resolve()}"


def ingest_repo(
    conn,
    repo_path: str | Path,
    *,
    author_email: str | None = None,
) -> dict:
    """Incrementally ingest a repo into the events table.

    Uses `source_state` to remember the last commit ts processed per repo. On
    subsequent runs only commits with ts > watermark are re-walked.

    Returns: {repo, ingested, last_event_ts}.
    """
    from .. import store

    repo = Path(repo_path).expanduser().resolve()
    key = _source_key(repo)
    state = store.get_source_state(conn, key)
    since_ts: int | None = None
    if state is not None and state.get("last_event_ts") is not None:
        since_ts = int(state["last_event_ts"])

    ingested = 0
    last_ts = since_ts
    for event in read_events(repo, since_ts=since_ts, author_email=author_email):
        # The `--since=@<ts>` filter is exclusive on git's side but the cutoff
        # itself is included occasionally; skip rows we've already stored.
        if since_ts is not None and event.ts <= since_ts:
            continue
        store.upsert_event(conn, event)
        ingested += 1
        if last_ts is None or event.ts > last_ts:
            last_ts = event.ts

    store.update_source_state(conn, key, last_event_ts=last_ts)
    return {"repo": str(repo), "ingested": ingested, "last_event_ts": last_ts}
