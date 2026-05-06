"""Tests for lib.transcribe."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lib import transcribe
from lib.runlog import RunLog


SAMPLE_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.500
Welcome to the show, today we're talking about

00:00:02.500 --> 00:00:05.000
<00:00:02.500><c>large language models</c> and how they work.

00:00:05.000 --> 00:00:07.000
large language models and how they work.

00:00:07.000 --> 00:00:10.000
The first thing to understand is the architecture.
"""


def test_clean_vtt_strips_headers_and_timestamps() -> None:
    cleaned = transcribe._clean_vtt(SAMPLE_VTT)
    assert "WEBVTT" not in cleaned
    assert "Kind:" not in cleaned
    assert "-->" not in cleaned
    assert "<c>" not in cleaned
    assert "<00:00:02.500>" not in cleaned


def test_clean_vtt_dedups_consecutive_lines() -> None:
    cleaned = transcribe._clean_vtt(SAMPLE_VTT)
    lines = cleaned.splitlines()
    # The repeated "large language models and how they work." line should
    # appear only once, not twice.
    assert lines.count("large language models and how they work.") == 1


def _make_subprocess_factory(
    *,
    on_call: list[str],
    create_files: dict[str, str] | None = None,
):
    """Return a fake `subprocess.run` that records langs requested + creates files."""
    create_files = create_files or {}

    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        # Find the lang argument
        lang = None
        for i, arg in enumerate(cmd):
            if arg == "--sub-lang" and i + 1 < len(cmd):
                lang = cmd[i + 1]
                break
        assert lang is not None
        on_call.append(lang)
        # If this lang is in create_files, write the file the caller expects.
        if lang in create_files:
            # Find the -o output template, infer the file path.
            for i, arg in enumerate(cmd):
                if arg == "-o" and i + 1 < len(cmd):
                    template = cmd[i + 1]
                    break
            else:
                template = "%(id)s.%(ext)s"
            video_url = cmd[-1]
            video_id = video_url.rsplit("=", 1)[-1]
            target = template.replace("%(id)s", video_id).replace(
                "%(ext)s", f"{lang}.vtt"
            )
            Path(target).write_text(create_files[lang])
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr="",
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="no captions in language",
        )

    return _run


def test_first_language_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subprocess, "run",
        _make_subprocess_factory(on_call=calls, create_files={"en": SAMPLE_VTT}),
    )
    result = transcribe.fetch_transcript(
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "aaaaaaaaaaa",
        out_dir=tmp_path,
    )
    assert result is not None
    assert result["language"] == "en"
    assert result["video_id"] == "aaaaaaaaaaa"
    assert "language models" in result["text"]
    assert calls == ["en"]


def test_falls_back_through_languages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subprocess, "run",
        _make_subprocess_factory(on_call=calls, create_files={"en-GB": SAMPLE_VTT}),
    )
    result = transcribe.fetch_transcript(
        "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        "bbbbbbbbbbb",
        out_dir=tmp_path,
    )
    assert result is not None
    assert result["language"] == "en-GB"
    # Should have tried en, en-US, then en-GB before succeeding.
    assert calls == ["en", "en-US", "en-GB"]


def test_no_captions_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subprocess, "run",
        _make_subprocess_factory(on_call=calls, create_files={}),
    )
    log = RunLog()
    result = transcribe.fetch_transcript(
        "https://www.youtube.com/watch?v=ccccccccccc",
        "ccccccccccc",
        out_dir=tmp_path,
        log=log,
    )
    assert result is None
    # All four language variants should have been attempted.
    assert calls == ["en", "en-US", "en-GB", "en-orig"]


def test_ytdlp_missing_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("yt-dlp not on PATH")

    monkeypatch.setattr(subprocess, "run", _raise)
    log = RunLog()
    result = transcribe.fetch_transcript(
        "https://www.youtube.com/watch?v=ddddddddddd",
        "ddddddddddd",
        out_dir=tmp_path,
        log=log,
    )
    assert result is None
    assert any(e["event"] == "ytdlp_missing" for e in log.entries)
