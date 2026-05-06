"""Articles-feed merge + git publish.

Replaces the agent's Bash-driven git steps. Two modes:

  - ``write_proposed`` for dry runs: each accepted article goes to
    ``_proposed/<YYYY-MM-DD>/<slug>.json``.
  - ``publish_live`` for live runs: articles are merged into
    ``articles.json`` (preserving existing order, appending new), the
    feed's ``version`` and ``lastUpdated`` are bumped, state is updated,
    then a git commit + push happens with one ``pull --rebase`` retry on
    push race.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runlog import RunLog

DEFAULT_PUSH_RETRIES = 1


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_proposed(
    proposed_root: Path, articles: list[dict], *, today: str | None = None
) -> list[Path]:
    """Write each accepted article to ``proposed_root/<today>/<slug>.json``."""
    today = today or _today_utc()
    out_dir = proposed_root / today
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for art in articles:
        slug = str(art.get("slug") or "untitled")
        path = out_dir / f"{slug}.json"
        path.write_text(
            json.dumps(art, ensure_ascii=False, indent=2) + "\n"
        )
        paths.append(path)
    return paths


def merge_into_feed(
    feed_path: Path, articles: list[dict], *, today: str | None = None
) -> None:
    """Append `articles` to ``feed['articles']``; bump version + lastUpdated."""
    today = today or _today_utc()
    data = json.loads(feed_path.read_text())
    if not isinstance(data, dict) or "articles" not in data:
        raise ValueError(
            f"{feed_path} is not a wrapped feed; run bootstrap.py first"
        )
    data["articles"].extend(articles)
    data["version"] = today
    data["lastUpdated"] = _now_utc_iso()
    feed_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )


def update_state(
    state_path: Path, video_ids: list[str], *, now_iso: str | None = None
) -> None:
    """Append video_ids to processed_video_ids; bump last_run."""
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {"schema_version": 1, "last_run": None, "processed_video_ids": []}
    processed = list(state.get("processed_video_ids", []) or [])
    seen = set(processed)
    for vid in video_ids:
        if vid not in seen:
            processed.append(vid)
            seen.add(vid)
    state["processed_video_ids"] = processed
    state["last_run"] = now_iso or _now_utc_iso()
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def commit_and_push(
    *,
    repo_root: Path,
    paths: list[Path],
    message: str,
    push: bool,
    log: "RunLog | None" = None,
    push_retries: int = DEFAULT_PUSH_RETRIES,
    git_bin: str = "git",
) -> bool:
    """git add the listed paths, commit, and (optionally) push.

    Returns True if everything succeeded. On push race, runs
    ``git pull --rebase origin main`` once and retries the push.
    """
    rel = [str(p.relative_to(repo_root)) for p in paths]
    try:
        subprocess.run(
            [git_bin, "-C", str(repo_root), "add", *rel],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [git_bin, "-C", str(repo_root), "commit", "-m", message],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        if log is not None:
            log.record(
                "git_commit_failed",
                stderr=(e.stderr or "").strip()[:500],
            )
        return False

    if not push:
        if log is not None:
            log.record("git_push_skipped")
        return True

    for attempt in range(push_retries + 1):
        result = subprocess.run(
            [git_bin, "-C", str(repo_root), "push", "origin", "main"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            if log is not None:
                log.record("git_pushed", attempt=attempt)
            return True
        if log is not None:
            log.record(
                "git_push_failed",
                attempt=attempt,
                stderr=(result.stderr or "").strip()[:500],
            )
        if attempt >= push_retries:
            break
        rebase = subprocess.run(
            [git_bin, "-C", str(repo_root),
             "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True, check=False,
        )
        if rebase.returncode != 0:
            if log is not None:
                log.record(
                    "git_rebase_failed",
                    stderr=(rebase.stderr or "").strip()[:500],
                )
            subprocess.run(
                [git_bin, "-C", str(repo_root), "rebase", "--abort"],
                capture_output=True, text=True, check=False,
            )
            return False
    return False
