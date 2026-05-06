"""Tests for lib.discover.find_candidates.

`subprocess.run` is monkeypatched to return canned yt-dlp output so the
filter / sort / dedupe / error paths can be exercised without hitting the
network.
"""
from __future__ import annotations

import subprocess
from typing import Any

import pytest

from lib import discover
from lib.runlog import RunLog


def _ytdlp_row(
    *,
    video_id: str,
    title: str,
    upload_date: str = "20260505",
    duration: int = 720,
    channel: str = "Matt Wolfe",
    url: str | None = None,
) -> str:
    if url is None:
        url = f"https://www.youtube.com/watch?v={video_id}"
    return f"{video_id}\t{title}\t{upload_date}\t{duration}\t{channel}\t{url}"


def _result(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _make_runner(
    by_handle: dict[str, subprocess.CompletedProcess[str]],
):
    """Build a fake `subprocess.run` that dispatches by channel handle in argv."""

    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        url = cmd[-1]
        for handle, result in by_handle.items():
            if handle in url:
                return result
        return _result(returncode=1, stderr=f"unexpected url: {url}")

    return _run


def test_filters_by_topic_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    output = "\n".join([
        _ytdlp_row(video_id="aaaaaaaaaaa", title="GPT-5 launch reactions"),
        _ytdlp_row(video_id="bbbbbbbbbbb", title="My favorite sourdough recipe"),
    ])
    monkeypatch.setattr(
        subprocess, "run",
        _make_runner({"@mreflow": _result(stdout=output)}),
    )
    log = RunLog()
    out = discover.find_candidates(
        channels=[{"priority": 1, "handle": "@mreflow"}],
        topic_keywords=["GPT", "AI"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=5,
        log=log,
    )
    assert [c["id"] for c in out] == ["aaaaaaaaaaa"]


def test_excludes_processed_and_manual_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    output = "\n".join([
        _ytdlp_row(video_id="aaaaaaaaaaa", title="GPT-5 launch reactions"),
        _ytdlp_row(video_id="bbbbbbbbbbb", title="LLM scaling laws explained"),
        _ytdlp_row(video_id="ccccccccccc", title="Transformer internals"),
    ])
    monkeypatch.setattr(
        subprocess, "run",
        _make_runner({"@mreflow": _result(stdout=output)}),
    )
    out = discover.find_candidates(
        channels=[{"priority": 1, "handle": "@mreflow"}],
        topic_keywords=["GPT", "LLM", "transformer"],
        duration_min=300,
        duration_max=5400,
        processed_ids={"aaaaaaaaaaa"},
        skip_ids={"bbbbbbbbbbb"},
        cap=5,
    )
    assert [c["id"] for c in out] == ["ccccccccccc"]


def test_sort_by_priority_then_duration_desc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_runner({
            "@mreflow": _result(stdout=_ytdlp_row(
                video_id="prio1aaaaaa", title="AI roundup", duration=400,
            )),
            "@AIDailyBrief": _result(stdout="\n".join([
                _ytdlp_row(video_id="prio2longer", title="AGI signals", duration=900),
                _ytdlp_row(video_id="prio2shortr", title="LLM news", duration=500),
            ])),
        }),
    )
    out = discover.find_candidates(
        channels=[
            {"priority": 2, "handle": "@AIDailyBrief"},
            {"priority": 1, "handle": "@mreflow"},
        ],
        topic_keywords=["AI", "AGI", "LLM"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=5,
    )
    # Priority 1 first, then within priority 2 the longer duration wins.
    assert [c["id"] for c in out] == [
        "prio1aaaaaa",
        "prio2longer",
        "prio2shortr",
    ]


def test_cap_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    output = "\n".join(
        _ytdlp_row(video_id=f"vid{i:08d}xx"[:11], title="AI thing")
        for i in range(10)
    )
    monkeypatch.setattr(
        subprocess, "run",
        _make_runner({"@mreflow": _result(stdout=output)}),
    )
    out = discover.find_candidates(
        channels=[{"priority": 1, "handle": "@mreflow"}],
        topic_keywords=["AI"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=3,
    )
    assert len(out) == 3


def test_channel_error_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_runner({
            "@mreflow": _result(returncode=1, stderr="HTTP 429 rate limited"),
            "@AIDailyBrief": _result(stdout=_ytdlp_row(
                video_id="ok000000000", title="AGI update",
            )),
        }),
    )
    log = RunLog()
    out = discover.find_candidates(
        channels=[
            {"priority": 1, "handle": "@mreflow"},
            {"priority": 2, "handle": "@AIDailyBrief"},
        ],
        topic_keywords=["AGI", "AI"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=5,
        log=log,
    )
    assert [c["id"] for c in out] == ["ok000000000"]
    events = [e["event"] for e in log.entries]
    assert "channel_error" in events


def test_invalid_handle_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _make_runner({}))
    log = RunLog()
    out = discover.find_candidates(
        channels=[{"priority": 1, "handle": "no-at-prefix"}],
        topic_keywords=["AI"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=5,
        log=log,
    )
    assert out == []
    assert any(e["event"] == "channel_skipped" for e in log.entries)


def test_published_at_iso_formatted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_runner({"@mreflow": _result(stdout=_ytdlp_row(
            video_id="aaaaaaaaaaa", title="AI thing", upload_date="20260429",
        ))}),
    )
    out = discover.find_candidates(
        channels=[{"priority": 1, "handle": "@mreflow"}],
        topic_keywords=["AI"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=5,
    )
    assert out[0]["publishedAt"].startswith("2026-04-29T00:00:00")


def test_ytdlp_missing_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("yt-dlp not on PATH")

    monkeypatch.setattr(subprocess, "run", _raise)
    log = RunLog()
    out = discover.find_candidates(
        channels=[{"priority": 1, "handle": "@mreflow"}],
        topic_keywords=["AI"],
        duration_min=300,
        duration_max=5400,
        processed_ids=set(),
        skip_ids=set(),
        cap=5,
        log=log,
    )
    assert out == []
    assert any(e["event"] == "ytdlp_missing" for e in log.entries)
