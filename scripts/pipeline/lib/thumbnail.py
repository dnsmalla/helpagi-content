"""Fetch a YouTube thumbnail to ``images/<slug>.jpg`` via curl.

Tries ``maxresdefault.jpg`` first, falls back to ``hqdefault.jpg`` (the
maxres version is missing for older or low-resolution videos). Returns
True only if the resulting file is > 1 KB — YouTube serves a tiny
placeholder when no real thumbnail exists, and we treat that as failure.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runlog import RunLog

MIN_VALID_BYTES = 1024
DEFAULT_TIMEOUT_SECONDS = 30


def _curl_to_file(
    url: str, target: Path, *, timeout: int, curl_bin: str
) -> bool:
    cmd = [
        curl_bin, "-fsSL", "--max-time", str(timeout),
        url, "-o", str(target),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout + 5, check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        return False
    return result.returncode == 0 and target.exists()


def fetch_thumbnail(
    video_id: str,
    slug: str,
    images_dir: Path,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    curl_bin: str = "curl",
    log: "RunLog | None" = None,
) -> Path | None:
    """Download a thumbnail. Returns the local path on success, else None."""
    images_dir.mkdir(parents=True, exist_ok=True)
    target = images_dir / f"{slug}.jpg"
    urls = (
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    )
    for url in urls:
        if _curl_to_file(url, target, timeout=timeout, curl_bin=curl_bin):
            size = target.stat().st_size
            if size > MIN_VALID_BYTES:
                if log is not None:
                    log.record(
                        "thumbnail_ok", video_id=video_id, slug=slug,
                        url=url, bytes=size,
                    )
                return target
            if log is not None:
                log.record(
                    "thumbnail_too_small", video_id=video_id, slug=slug,
                    url=url, bytes=size,
                )
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
    if log is not None:
        log.record("thumbnail_failed", video_id=video_id, slug=slug)
    return None
