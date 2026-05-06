"""Tests for lib.writer_agent."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lib import writer_agent
from lib.runlog import RunLog


SAMPLE_ARTICLE = {
    "slug": "what-is-agi",
    "title": "What is AGI",
    "content": "...",
}


def _claude_runner(*, stdout: str = "", stderr: str = "", returncode: int = 0):
    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout=stdout, stderr=stderr,
        )
    return _run


def _write_prompt(tmp_path: Path) -> Path:
    p = tmp_path / "prompt.md"
    p.write_text("be a writer")
    return p


def test_extract_direct_json() -> None:
    out = writer_agent._extract_json_object(json.dumps(SAMPLE_ARTICLE))
    assert out == SAMPLE_ARTICLE


def test_extract_with_markdown_fence() -> None:
    fenced = "```json\n" + json.dumps(SAMPLE_ARTICLE) + "\n```"
    out = writer_agent._extract_json_object(fenced)
    assert out == SAMPLE_ARTICLE


def test_extract_with_leading_prose() -> None:
    text = "Here is the article:\n\n" + json.dumps(SAMPLE_ARTICLE) + "\n"
    out = writer_agent._extract_json_object(text)
    assert out == SAMPLE_ARTICLE


def test_extract_drop_returns_none() -> None:
    out = writer_agent._extract_json_object("DROP")
    assert out is None


def test_extract_garbage_returns_none() -> None:
    out = writer_agent._extract_json_object("nothing parseable here")
    assert out is None


def test_invoke_writer_returns_article(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _claude_runner(stdout=json.dumps(SAMPLE_ARTICLE)),
    )
    article = writer_agent.invoke_writer(
        prompt_path=_write_prompt(tmp_path),
        cwd=tmp_path,
    )
    assert article == SAMPLE_ARTICLE


def test_invoke_writer_drop_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "run", _claude_runner(stdout="DROP\n"))
    log = RunLog()
    article = writer_agent.invoke_writer(
        prompt_path=_write_prompt(tmp_path),
        cwd=tmp_path,
        log=log,
    )
    assert article is None
    assert any(e["event"] == "writer_drop" for e in log.entries)


def test_invoke_writer_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _claude_runner(returncode=1, stderr="rate-limited"),
    )
    log = RunLog()
    article = writer_agent.invoke_writer(
        prompt_path=_write_prompt(tmp_path),
        cwd=tmp_path,
        log=log,
    )
    assert article is None
    assert any(e["event"] == "writer_nonzero_exit" for e in log.entries)


def test_invoke_writer_parse_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _claude_runner(stdout="this is not JSON at all"),
    )
    log = RunLog()
    article = writer_agent.invoke_writer(
        prompt_path=_write_prompt(tmp_path),
        cwd=tmp_path,
        log=log,
    )
    assert article is None
    assert any(e["event"] == "writer_parse_fail" for e in log.entries)


def test_invoke_writer_missing_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("claude not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(writer_agent.WriterError):
        writer_agent.invoke_writer(
            prompt_path=_write_prompt(tmp_path),
            cwd=tmp_path,
        )
