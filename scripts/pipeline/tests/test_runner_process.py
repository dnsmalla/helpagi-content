"""End-to-end style tests for runner._process_candidate.

The orchestrator's per-candidate loop is the integration point between
discovery → transcribe → writer → validate → thumbnail. Each dependency
is monkeypatched so the test runs offline; the focus is the glue:

  - article-input.json gets written with the right shape.
  - skip reasons land on the run log with the right `reason` field.
  - the writer's article is returned only if every gate passes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import runner
from lib.runlog import RunLog
from tools.validate_article import ValidationError


SAMPLE_CANDIDATE = {
    "id": "abc12345678",
    "title": "AI thing",
    "channel": "Matt Wolfe",
    "channelHandle": "@mreflow",
    "url": "https://www.youtube.com/watch?v=abc12345678",
    "publishedAt": "2026-04-29T00:00:00+00:00",
    "durationSeconds": 720,
    "channelPriority": 1,
}

SAMPLE_TRANSCRIPT = {
    "video_id": "abc12345678",
    "language": "en",
    "text": "Hello and welcome — today we discuss large language models.",
}

SAMPLE_ARTICLE = {
    "slug": "ai-thing-explainer",
    "title": "AI Thing Explainer",
    "summary": "Test article summary.",
    "content": "## Body\n\nSome content here.\n\n## Source\n\n…",
    "sourceVideo": SAMPLE_CANDIDATE,
}


def _setup_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    transcripts = tmp_path / "transcripts"
    images = tmp_path / "images"
    transcripts.mkdir()
    images.mkdir()
    article_input = tmp_path / "article-input.json"
    monkeypatch.setattr(runner, "TRANSCRIPT_DIR", transcripts)
    monkeypatch.setattr(runner, "ARTICLE_INPUT_PATH", article_input)
    monkeypatch.setattr(runner, "IMAGES_DIR", images)
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "WRITER_PROMPT_PATH", tmp_path / "prompt.md")
    return {
        "transcripts": transcripts,
        "images": images,
        "article_input": article_input,
    }


def _stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    transcript: dict | None = SAMPLE_TRANSCRIPT,
    article: dict | None = SAMPLE_ARTICLE,
    validate: Exception | None = None,
    thumb: Path | None | object = ...,
) -> None:
    monkeypatch.setattr(
        runner.transcribe, "fetch_transcript",
        lambda *a, **k: transcript,
    )
    monkeypatch.setattr(
        runner, "invoke_writer",
        lambda **k: article,
    )
    if validate is None:
        monkeypatch.setattr(
            runner, "validate_article",
            lambda art, existing=None: None,
        )
    else:
        def _raise(art: dict, existing: Any = None) -> None:
            raise validate

        monkeypatch.setattr(runner, "validate_article", _raise)
    if thumb is ...:
        thumb = Path("/tmp/dummy.jpg")
    monkeypatch.setattr(
        runner.thumbnail, "fetch_thumbnail",
        lambda *a, **k: thumb,
    )


def test_happy_path_returns_article(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _setup_paths(monkeypatch, tmp_path)
    _stub(monkeypatch, thumb=paths["images"] / "ai-thing-explainer.jpg")
    log = RunLog()
    out = runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=4,
        existing_articles=[],
        log=log,
    )
    assert out == SAMPLE_ARTICLE
    accepted = [e for e in log.entries if e["event"] == "candidate_accepted"]
    assert len(accepted) == 1
    assert accepted[0]["slug"] == "ai-thing-explainer"


def test_writes_article_input_with_expected_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _setup_paths(monkeypatch, tmp_path)
    _stub(monkeypatch)
    runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=7,
        existing_articles=[],
        log=RunLog(),
    )
    payload = json.loads(paths["article_input"].read_text())
    assert payload["candidate"]["id"] == SAMPLE_CANDIDATE["id"]
    assert payload["transcript"]["language"] == "en"
    assert payload["research_budget"] == 7
    assert "today" in payload


def test_skip_when_no_captions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup_paths(monkeypatch, tmp_path)
    _stub(monkeypatch, transcript=None)
    log = RunLog()
    out = runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=4,
        existing_articles=[],
        log=log,
    )
    assert out is None
    skips = [e for e in log.entries if e["event"] == "candidate_skipped"]
    assert any(e.get("reason") == "no_captions" for e in skips)


def test_skip_when_writer_drops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup_paths(monkeypatch, tmp_path)
    _stub(monkeypatch, article=None)
    log = RunLog()
    out = runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=4,
        existing_articles=[],
        log=log,
    )
    assert out is None
    skips = [e for e in log.entries if e["event"] == "candidate_skipped"]
    assert any(e.get("reason") == "writer_drop_or_parse_fail" for e in skips)


def test_skip_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup_paths(monkeypatch, tmp_path)
    _stub(
        monkeypatch,
        validate=ValidationError("content too short (1200 < 1500 words)"),
    )
    log = RunLog()
    out = runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=4,
        existing_articles=[],
        log=log,
    )
    assert out is None
    skips = [e for e in log.entries if e["event"] == "candidate_skipped"]
    val = next((e for e in skips if e.get("reason") == "validation"), None)
    assert val is not None
    assert "1200" in val["error"]


def test_skip_when_thumbnail_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup_paths(monkeypatch, tmp_path)
    _stub(monkeypatch, thumb=None)
    log = RunLog()
    out = runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=4,
        existing_articles=[],
        log=log,
    )
    assert out is None
    skips = [e for e in log.entries if e["event"] == "candidate_skipped"]
    assert any(e.get("reason") == "thumbnail_failed" for e in skips)


def test_date_filled_when_writer_omits_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _setup_paths(monkeypatch, tmp_path)
    article_no_date = {k: v for k, v in SAMPLE_ARTICLE.items() if k != "date"}
    _stub(
        monkeypatch,
        article=article_no_date,
        thumb=paths["images"] / "ai-thing-explainer.jpg",
    )
    out = runner._process_candidate(
        candidate=SAMPLE_CANDIDATE,
        research_budget=4,
        existing_articles=[],
        log=RunLog(),
    )
    assert out is not None
    assert "date" in out
    assert out["date"].endswith("+00:00")
