"""Fetch + clean YouTube auto-caption tracks via yt-dlp.

Replaces the agent's Bash-driven transcription step. Try English language
variants in order (`en`, `en-US`, `en-GB`, `en-orig`); the first one that
yt-dlp can fetch wins. If none work, the candidate has no captions and
the orchestrator must skip it (Whisper fallback is out of scope).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runlog import RunLog

LANGUAGES = ("en", "en-US", "en-GB", "en-orig")
TIMEOUT_SECONDS = 180

_TIMESTAMP_TAG = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>")
_CSTYLE_TAG = re.compile(r"</?c[^>]*>")


def _clean_vtt(text: str) -> str:
    """Strip VTT headers, timestamps, styling tags; de-dup consecutive lines."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        if line.isdigit():
            continue
        line = _TIMESTAMP_TAG.sub("", line)
        line = _CSTYLE_TAG.sub("", line)
        line = line.strip()
        if not line:
            continue
        if out and out[-1] == line:
            continue
        out.append(line)
    return "\n".join(out)


def fetch_transcript(
    video_url: str,
    video_id: str,
    *,
    out_dir: Path,
    ytdlp_bin: str = "yt-dlp",
    log: "RunLog | None" = None,
) -> dict | None:
    """Return ``{video_id, language, text}`` if any English variant works, else None."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for lang in LANGUAGES:
        cmd = [
            ytdlp_bin,
            "--write-auto-sub",
            "--sub-lang", lang,
            "--skip-download",
            "--sub-format", "vtt",
            "-o", str(out_dir / "%(id)s.%(ext)s"),
            "--no-warnings",
            "--quiet",
            video_url,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            if log is not None:
                log.record("transcript_timeout", video_id=video_id, lang=lang)
            continue
        except FileNotFoundError:
            if log is not None:
                log.record("ytdlp_missing", video_id=video_id, bin=ytdlp_bin)
            return None
        if result.returncode != 0:
            if log is not None:
                log.record(
                    "transcript_lang_failed",
                    video_id=video_id, lang=lang,
                    stderr=(result.stderr or "").strip()[:200],
                )
            continue
        vtt_path = out_dir / f"{video_id}.{lang}.vtt"
        if not vtt_path.exists():
            if log is not None:
                log.record(
                    "transcript_no_file", video_id=video_id, lang=lang,
                )
            continue
        cleaned = _clean_vtt(vtt_path.read_text(encoding="utf-8", errors="replace"))
        if not cleaned:
            continue
        if log is not None:
            log.record(
                "transcript_ok", video_id=video_id, lang=lang,
                chars=len(cleaned),
            )
        return {"video_id": video_id, "language": lang, "text": cleaned}
    return None
