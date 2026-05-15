"""Tests for the git commit reader.

Each test creates a throw-away git repo in tmp_path and asserts the reader +
ingestor return the right shape. The test repo is configured with a fixed
identity so commits are deterministic across machines.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from personal_timeline import store
from personal_timeline.sources import git as gitsrc


def _run(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    out = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        check=True, capture_output=True, text=True, env=env,
    )
    return out.stdout


def _make_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "tester@example.com")
    _run(repo, "config", "user.name", "Tester")
    _run(repo, "config", "commit.gpgsign", "false")


def _commit(
    repo: Path,
    filename: str,
    content: str,
    message: str,
    *,
    author: str | None = None,
    when: int | None = None,
) -> str:
    """Stage + commit. `when` (unix ts) is required for deterministic ordering
    — tests that rely on ts comparisons must pass distinct values."""
    (repo / filename).write_text(content, encoding="utf-8")
    _run(repo, "add", filename)
    extra: dict[str, str] = {}
    if author is not None:
        name, _, email = author.partition("<")
        extra["GIT_AUTHOR_NAME"] = name.strip() or "Other"
        extra["GIT_AUTHOR_EMAIL"] = email.rstrip(">").strip() or "other@example.com"
        extra["GIT_COMMITTER_NAME"] = extra["GIT_AUTHOR_NAME"]
        extra["GIT_COMMITTER_EMAIL"] = extra["GIT_AUTHOR_EMAIL"]
    if when is not None:
        iso = f"@{when} +0000"
        extra.setdefault("GIT_AUTHOR_DATE", iso)
        extra.setdefault("GIT_COMMITTER_DATE", iso)
    _run(repo, "commit", "-q", "-m", message, env_extra=extra)
    return _run(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo"
    _make_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "Initial commit", when=1715000000)
    _commit(repo, "b.py", "y = 2\n", "Add b.py", when=1715000100)
    _commit(repo, "a.py", "x = 99\n", "Tweak a.py", when=1715000200)
    return repo


# -- list_commits / read_events -----------------------------------------------

def test_list_commits_returns_all(fixture_repo: Path):
    commits = gitsrc.list_commits(fixture_repo)
    assert len(commits) == 3
    # most-recent first
    assert commits[0]["subject"] == "Tweak a.py"
    assert "a.py" in commits[0]["files"]


def test_list_commits_since_filter(fixture_repo: Path):
    all_commits = gitsrc.list_commits(fixture_repo)
    # `git log --since=@<ts>` is inclusive — bump by 1s to exclude the oldest.
    oldest_ts = all_commits[-1]["ts"]
    later = gitsrc.list_commits(fixture_repo, since_ts=oldest_ts + 1)
    assert len(later) == 2


def test_list_commits_author_filter(fixture_repo: Path):
    _commit(fixture_repo, "c.py", "z = 3\n", "From other person",
            author="Other Person <other@example.com>", when=1715000250)
    mine = gitsrc.list_commits(fixture_repo, author_email="tester@example.com")
    assert len(mine) == 3
    assert all(c["author_email"] == "tester@example.com" for c in mine)


def test_read_events_shape(fixture_repo: Path):
    events = list(gitsrc.read_events(fixture_repo))
    assert events[0].source == "git"
    assert events[0].source_id.endswith(events[0].payload["sha"])
    assert isinstance(events[0].payload["files"], list)
    assert events[0].title == "Tweak a.py"


# -- incremental ingest -------------------------------------------------------

def test_ingest_repo_is_incremental(fixture_repo: Path, tmp_path: Path):
    db = tmp_path / "ingest.db"
    conn = store.init_db(db)
    try:
        r1 = gitsrc.ingest_repo(conn, fixture_repo)
        assert r1["ingested"] == 3
        assert store.count_events(conn, "git") == 3

        # No new commits — second pass ingests nothing.
        r2 = gitsrc.ingest_repo(conn, fixture_repo)
        assert r2["ingested"] == 0
        assert store.count_events(conn, "git") == 3

        # Add a commit with a later ts; only that one is ingested.
        _commit(fixture_repo, "d.py", "w = 4\n", "Add d.py", when=1715000300)
        r3 = gitsrc.ingest_repo(conn, fixture_repo)
        assert r3["ingested"] == 1
        assert store.count_events(conn, "git") == 4
    finally:
        conn.close()


def test_ingest_repo_records_watermark(fixture_repo: Path, tmp_path: Path):
    db = tmp_path / "wm.db"
    conn = store.init_db(db)
    try:
        gitsrc.ingest_repo(conn, fixture_repo)
        key = gitsrc._source_key(fixture_repo)
        state = store.get_source_state(conn, key)
        assert state is not None
        assert state["last_event_ts"] is not None
    finally:
        conn.close()
