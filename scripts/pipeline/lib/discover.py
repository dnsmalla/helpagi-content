"""Discover candidate videos via yt-dlp.

Replaces the agent's Bash-driven yt-dlp call with a deterministic Python
wrapper. For each channel (in priority order) we shell out once, parse
the tab-separated output, drop already-processed / manually-skipped IDs,
filter by topic keyword in the title, and return up to ``cap`` candidates
sorted by channel priority then duration.

Per-channel failures (timeout, non-zero exit, rate limit) are recorded on
the supplied ``RunLog`` and do not stop the overall run — skip-don't-block.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runlog import RunLog

YTDLP_PRINT_FORMAT = (
    "%(id)s\t%(title)s\t%(upload_date)s\t%(duration)s\t%(channel)s\t%(webpage_url)s"
)
YTDLP_TIMEOUT_SECONDS = 180


def _format_published_at(upload_date: str) -> str:
    """yt-dlp's `upload_date` is `YYYYMMDD`. Map to ISO 8601 UTC midnight."""
    try:
        return (
            datetime.strptime(upload_date, "%Y%m%d")
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
    except ValueError:
        return upload_date


def find_candidates(
    *,
    channels: list[dict],
    topic_keywords: list[str],
    duration_min: int,
    duration_max: int,
    processed_ids: set[str],
    skip_ids: set[str],
    cap: int,
    log: "RunLog | None" = None,
    ytdlp_bin: str = "yt-dlp",
) -> list[dict]:
    """Return up to ``cap`` candidate videos ready for transcription.

    Each candidate dict matches the shape consumed by the agent / validator's
    ``sourceVideo`` field plus orchestration-only ``channelPriority``.
    """
    keywords_lower = [str(k).lower() for k in topic_keywords]
    accepted: list[dict] = []

    for channel in sorted(channels, key=lambda c: c.get("priority", 999)):
        handle = str(channel.get("handle", ""))
        if not handle.startswith("@"):
            if log is not None:
                log.record("channel_skipped", reason="invalid_handle", handle=handle)
            continue

        url = f"https://www.youtube.com/{handle}/videos"
        cmd = [
            ytdlp_bin,
            "--print", YTDLP_PRINT_FORMAT,
            "--dateafter", "now-1day",
            "--match-filter",
            f"duration > {duration_min} & duration < {duration_max}",
            "--no-warnings",
            "--skip-download",
            "--quiet",
            url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=YTDLP_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            if log is not None:
                log.record("channel_timeout", handle=handle)
            continue
        except FileNotFoundError:
            if log is not None:
                log.record("ytdlp_missing", handle=handle, bin=ytdlp_bin)
            return []

        if result.returncode != 0:
            stderr_excerpt = (result.stderr or "").strip()[:500]
            if log is not None:
                log.record(
                    "channel_error",
                    handle=handle,
                    returncode=result.returncode,
                    stderr=stderr_excerpt,
                )
            continue

        rows = [
            line for line in (result.stdout or "").splitlines() if line.strip()
        ]
        kept: list[dict] = []
        for row in rows:
            parts = row.split("\t")
            if len(parts) < 6:
                continue
            video_id, title, upload_date, duration, channel_name, webpage_url = (
                parts[:6]
            )
            if video_id in processed_ids or video_id in skip_ids:
                continue
            title_lower = title.lower()
            if not any(kw in title_lower for kw in keywords_lower):
                continue
            try:
                dur = int(duration)
            except (TypeError, ValueError):
                continue
            kept.append({
                "id": video_id,
                "title": title,
                "channel": channel_name,
                "channelHandle": handle,
                "url": webpage_url,
                "publishedAt": _format_published_at(upload_date),
                "durationSeconds": dur,
                "channelPriority": int(channel.get("priority", 999)),
            })

        if log is not None:
            log.record(
                "channel_probed", handle=handle, raw=len(rows), kept=len(kept)
            )
        accepted.extend(kept)

    accepted.sort(
        key=lambda c: (c["channelPriority"], -c["durationSeconds"])
    )
    return accepted[:cap]
