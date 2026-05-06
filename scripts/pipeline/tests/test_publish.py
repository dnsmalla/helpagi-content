"""Tests for lib.publish."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lib import publish
from lib.runlog import RunLog


def _seed_feed(path: Path, articles: list[dict] | None = None) -> None:
    path.write_text(json.dumps({
        "version": "2026-04-29",
        "lastUpdated": "2026-04-29T00:00:00+00:00",
        "articles": articles or [],
    }, indent=2))


def test_write_proposed(tmp_path: Path) -> None:
    proposed = tmp_path / "_proposed"
    arts = [
        {"slug": "alpha", "title": "Alpha"},
        {"slug": "beta", "title": "Beta"},
    ]
    paths = publish.write_proposed(proposed, arts, today="2026-05-06")
    assert {p.name for p in paths} == {"alpha.json", "beta.json"}
    body = json.loads(paths[0].read_text())
    assert body["slug"] == "alpha"
    assert paths[0].parent.name == "2026-05-06"


def test_merge_into_feed_appends_and_bumps(tmp_path: Path) -> None:
    feed = tmp_path / "articles.json"
    _seed_feed(feed, articles=[{"slug": "old", "title": "Old"}])
    publish.merge_into_feed(
        feed,
        [{"slug": "new", "title": "New"}],
        today="2026-05-06",
    )
    data = json.loads(feed.read_text())
    assert [a["slug"] for a in data["articles"]] == ["old", "new"]
    assert data["version"] == "2026-05-06"
    assert data["lastUpdated"].startswith("2026-")


def test_merge_into_unwrapped_feed_raises(tmp_path: Path) -> None:
    feed = tmp_path / "articles.json"
    feed.write_text(json.dumps([{"slug": "x"}]))  # legacy array form
    with pytest.raises(ValueError, match="not a wrapped feed"):
        publish.merge_into_feed(feed, [{"slug": "y"}])


def test_update_state_dedups(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "schema_version": 1,
        "last_run": None,
        "processed_video_ids": ["aaaaaaaaaaa"],
    }))
    publish.update_state(
        state_path, ["aaaaaaaaaaa", "bbbbbbbbbbb"],
        now_iso="2026-05-06T12:00:00+00:00",
    )
    state = json.loads(state_path.read_text())
    assert state["processed_video_ids"] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert state["last_run"] == "2026-05-06T12:00:00+00:00"


def test_update_state_creates_missing(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    publish.update_state(state_path, ["xxx"])
    state = json.loads(state_path.read_text())
    assert state["processed_video_ids"] == ["xxx"]


def _git_runner(scripted: list[tuple[list[str], int, str]]):
    """Build a fake `subprocess.run` that returns scripted (args, rc, stderr) tuples in order."""
    calls: list[list[str]] = []

    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if not scripted:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="unscripted")
        match_args, rc, stderr = scripted.pop(0)
        # Sanity-check the call shape — we record git subcommands.
        return subprocess.CompletedProcess(
            args=cmd, returncode=rc, stdout="", stderr=stderr,
        )

    _run.calls = calls  # type: ignore[attr-defined]
    return _run


def test_commit_and_push_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "articles.json"
    target.write_text("{}")
    monkeypatch.setattr(
        subprocess, "run",
        _git_runner([
            (["add"], 0, ""),
            (["commit"], 0, ""),
            (["push"], 0, ""),
        ]),
    )
    log = RunLog()
    ok = publish.commit_and_push(
        repo_root=tmp_path,
        paths=[target],
        message="auto: 1 article",
        push=True,
        log=log,
    )
    assert ok is True
    assert any(e["event"] == "git_pushed" for e in log.entries)


def test_commit_and_push_retries_on_race(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "articles.json"
    target.write_text("{}")
    monkeypatch.setattr(
        subprocess, "run",
        _git_runner([
            (["add"], 0, ""),
            (["commit"], 0, ""),
            (["push"], 1, "rejected: non-fast-forward"),
            (["pull"], 0, ""),
            (["push"], 0, ""),
        ]),
    )
    log = RunLog()
    ok = publish.commit_and_push(
        repo_root=tmp_path,
        paths=[target],
        message="auto: 1 article",
        push=True,
        log=log,
        push_retries=1,
    )
    assert ok is True


def test_commit_and_push_aborts_on_rebase_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "articles.json"
    target.write_text("{}")
    monkeypatch.setattr(
        subprocess, "run",
        _git_runner([
            (["add"], 0, ""),
            (["commit"], 0, ""),
            (["push"], 1, "rejected: non-fast-forward"),
            (["pull"], 1, "CONFLICT: articles.json"),
            (["rebase"], 0, ""),
        ]),
    )
    log = RunLog()
    ok = publish.commit_and_push(
        repo_root=tmp_path,
        paths=[target],
        message="auto",
        push=True,
        log=log,
        push_retries=1,
    )
    assert ok is False
    assert any(e["event"] == "git_rebase_failed" for e in log.entries)


def test_commit_skipped_push_returns_true(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "articles.json"
    target.write_text("{}")
    monkeypatch.setattr(
        subprocess, "run",
        _git_runner([
            (["add"], 0, ""),
            (["commit"], 0, ""),
        ]),
    )
    log = RunLog()
    ok = publish.commit_and_push(
        repo_root=tmp_path,
        paths=[target],
        message="auto",
        push=False,
        log=log,
    )
    assert ok is True
    assert any(e["event"] == "git_push_skipped" for e in log.entries)
