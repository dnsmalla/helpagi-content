"""HelpAGI content pipeline orchestrator (Phase 2).

The Python orchestrator now owns the full pipeline mechanics:

  1. Acquire a non-blocking file lock at ``.run/lock``.
  2. Run ``lib.discover.find_candidates`` (yt-dlp wrapper).
  3. For each candidate, in priority order:
       a. ``lib.transcribe.fetch_transcript`` — yt-dlp captions, English
          variant fallback, VTT cleaning.
       b. Write ``article-input.json`` for the writer agent.
       c. ``lib.writer_agent.invoke_writer`` — single-article Claude Code
          invocation. Tool surface narrowed to {WebSearch, WebFetch, Read}.
       d. ``tools.validate_article.validate_article`` — 12 hard gates,
          including dedupe against the live feed.
       e. ``lib.thumbnail.fetch_thumbnail`` — image fetch.
  4. After all candidates are processed, ``lib.publish.{write_proposed |
     merge_into_feed + commit_and_push}`` depending on ``dry_run``.
  5. Write a structured per-run JSON log under ``.run/runlog-<id>.json``.

The agent's role has shrunk from "do everything via Bash + Edit + Write +
WebSearch + WebFetch" to **just the writing step**: read the prepared
inputs, do bounded research, return one JSON object on stdout.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from lib.discover import find_candidates
from lib.locking import FileLock, LockHeld
from lib import publish, thumbnail, transcribe
from lib.runlog import RunLog
from lib.writer_agent import WriterError, invoke_writer
from tools.validate_article import ValidationError, validate_article

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_DIR.parent.parent
RUN_DIR = PIPELINE_DIR / ".run"
LOCK_PATH = RUN_DIR / "lock"
CANDIDATES_PATH = RUN_DIR / "candidates.json"
ARTICLE_INPUT_PATH = RUN_DIR / "article-input.json"
TRANSCRIPT_DIR = RUN_DIR / "transcripts"

CONFIG_PATH = PIPELINE_DIR / "config.yaml"
CHANNELS_PATH = PIPELINE_DIR / "channels.yaml"
STATE_PATH = PIPELINE_DIR / ".pipeline-state.json"
WRITER_PROMPT_PATH = PIPELINE_DIR / "agent-prompt-write.md"
SCHEMA_PATH = PIPELINE_DIR / "schema.json"
STYLE_GUIDE_PATH = PIPELINE_DIR / "style-guide.md"

FEED_PATH = REPO_ROOT / "articles.json"
IMAGES_DIR = REPO_ROOT / "images"
PROPOSED_DIR = REPO_ROOT / "_proposed"


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"schema_version": 1, "last_run": None, "processed_video_ids": []}
    return json.loads(STATE_PATH.read_text())


def _load_existing_articles() -> list[dict]:
    if not FEED_PATH.exists():
        return []
    feed = json.loads(FEED_PATH.read_text())
    if isinstance(feed, dict):
        return list(feed.get("articles", []))
    return list(feed) if isinstance(feed, list) else []


def _today_utc_iso_midnight() -> str:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    return datetime(
        today.year, today.month, today.day, tzinfo=timezone.utc
    ).isoformat()


def _today_utc_date() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _process_candidate(
    *,
    candidate: dict,
    research_budget: int,
    existing_articles: list[dict],
    log: RunLog,
) -> dict | None:
    """Returns a validated article dict or None (skipped — reason in log)."""
    video_id = candidate["id"]
    transcript = transcribe.fetch_transcript(
        candidate["url"], video_id, out_dir=TRANSCRIPT_DIR, log=log,
    )
    if transcript is None:
        log.record("candidate_skipped", video_id=video_id, reason="no_captions")
        return None

    ARTICLE_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTICLE_INPUT_PATH.write_text(json.dumps({
        "candidate": candidate,
        "transcript": transcript,
        "research_budget": research_budget,
        "today": _today_utc_date(),
    }, indent=2))

    article = invoke_writer(
        prompt_path=WRITER_PROMPT_PATH,
        cwd=REPO_ROOT,
        log=log,
    )
    if article is None:
        log.record(
            "candidate_skipped",
            video_id=video_id,
            reason="writer_drop_or_parse_fail",
        )
        return None

    # The writer is responsible for ``date``; if it omitted it, fill in today's.
    article.setdefault("date", _today_utc_iso_midnight())

    try:
        validate_article(article, existing=existing_articles)
    except ValidationError as e:
        log.record(
            "candidate_skipped",
            video_id=video_id,
            reason="validation",
            error=str(e),
        )
        return None

    slug = article["slug"]
    img = thumbnail.fetch_thumbnail(video_id, slug, IMAGES_DIR, log=log)
    if img is None:
        log.record(
            "candidate_skipped",
            video_id=video_id,
            reason="thumbnail_failed",
        )
        return None

    log.record("candidate_accepted", video_id=video_id, slug=slug)
    return article


def _run(log: RunLog) -> int:
    cfg = _load_yaml(CONFIG_PATH) or {}
    channels_doc = _load_yaml(CHANNELS_PATH) or {}
    channels = channels_doc.get("channels", [])
    state = _load_state()
    existing_articles = _load_existing_articles()
    dry_run = bool(cfg.get("dry_run", True))
    cap = int(cfg.get("daily_article_cap", 5))
    research_budget = int(cfg.get("research_budget", 4))

    log.record(
        "config_loaded",
        dry_run=dry_run,
        cap=cap,
        research_budget=research_budget,
        existing_articles=len(existing_articles),
    )

    candidates = find_candidates(
        channels=channels,
        topic_keywords=cfg.get("topic_keywords", []),
        duration_min=int(cfg.get("video_duration_min_sec", 300)),
        duration_max=int(cfg.get("video_duration_max_sec", 5400)),
        processed_ids=set(state.get("processed_video_ids", []) or []),
        skip_ids=set(cfg.get("manual_skip_video_ids", []) or []),
        cap=cap,
        log=log,
    )
    log.record("discovery_complete", count=len(candidates))

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(candidates, indent=2) + "\n")

    if not candidates:
        print("→ 0 candidates discovered. Nothing to do.")
        return 0

    accepted: list[dict] = []
    accepted_paths: list[Path] = []
    accepted_video_ids: list[str] = []

    # Build a running "existing" set so within-run dedupe also fires (two
    # candidates this run can't both produce articles with similar titles).
    seen_for_dedupe = list(existing_articles)

    try:
        for candidate in candidates:
            article = _process_candidate(
                candidate=candidate,
                research_budget=research_budget,
                existing_articles=seen_for_dedupe,
                log=log,
            )
            if article is None:
                continue
            accepted.append(article)
            seen_for_dedupe.append(article)
            accepted_video_ids.append(candidate["id"])
            slug = article["slug"]
            accepted_paths.append(IMAGES_DIR / f"{slug}.jpg")
    except WriterError as e:
        log.record("writer_fatal", error=str(e))
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    log.record(
        "processing_complete",
        accepted=len(accepted),
        skipped=len(candidates) - len(accepted),
    )

    if not accepted:
        print("→ 0 articles accepted this run.")
        return 0

    if dry_run:
        proposed_paths = publish.write_proposed(PROPOSED_DIR, accepted)
        log.record(
            "dry_run_written",
            count=len(proposed_paths),
            dir=str(proposed_paths[0].parent) if proposed_paths else "",
        )
        all_paths = proposed_paths + accepted_paths + [STATE_PATH]
        publish.update_state(STATE_PATH, accepted_video_ids)
        ok = publish.commit_and_push(
            repo_root=REPO_ROOT,
            paths=all_paths,
            message=(
                f"auto: {len(accepted)} proposed article(s) for review (dry run)"
            ),
            push=False,
            log=log,
        )
        if not ok:
            print("ERROR: dry-run commit failed; see runlog.", file=sys.stderr)
            return 1
        return 0

    publish.merge_into_feed(FEED_PATH, accepted)
    publish.update_state(STATE_PATH, accepted_video_ids)
    log.record("feed_merged", count=len(accepted))
    ok = publish.commit_and_push(
        repo_root=REPO_ROOT,
        paths=[FEED_PATH, STATE_PATH, *accepted_paths],
        message=f"auto: {len(accepted)} new article(s) from {_today_utc_date()}",
        push=True,
        log=log,
    )
    if not ok:
        print("ERROR: live publish failed; see runlog.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    log = RunLog()
    rc = 1
    try:
        with FileLock(LOCK_PATH):
            log.record("lock_acquired", path=str(LOCK_PATH))
            rc = _run(log)
    except LockHeld as e:
        log.record("lock_held", error=str(e))
        print(f"ERROR: {e}", file=sys.stderr)
        rc = 1
    finally:
        log.record("run_end", returncode=rc)
        path = log.write(RUN_DIR)
        if os.environ.get("HELPAGI_QUIET") != "1":
            print(f"→ run log: {path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
