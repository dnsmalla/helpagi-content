"""Fetch a YouTube thumbnail to ``images/<slug>.jpg`` via curl.

Tries ``maxresdefault.jpg`` first, falls back to ``hqdefault.jpg`` (the
maxres version is missing for older or low-resolution videos). Three
content-quality checks run after the bytes land on disk:

  - **Size > 1 KB.** YouTube serves a tiny gray placeholder when no real
    thumbnail exists; we never want that in the feed.
  - **JPEG dimensions ≥ 320×180.** Catches pathological responses that
    are technically over the size threshold but still unusable (e.g.,
    some live-stream stub thumbnails).
  - **SHA-256 not in known-placeholder set.** Framework only — populate
    ``KNOWN_PLACEHOLDER_HASHES`` as bad images are discovered.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runlog import RunLog

MIN_VALID_BYTES = 1024
MIN_VALID_WIDTH = 320
MIN_VALID_HEIGHT = 180
DEFAULT_TIMEOUT_SECONDS = 30

# Hex-encoded SHA-256 of YouTube placeholder thumbnails seen in the wild.
# Empty by default; append a hash here when a placeholder slips past the
# size + dimension gates and you confirm it's a placeholder.
KNOWN_PLACEHOLDER_HASHES: set[str] = set()


def _read_jpeg_dimensions(path: Path) -> tuple[int, int] | None:
    """Parse a JPEG's first SOF marker and return (width, height).

    Returns None if the file isn't a JPEG or the SOF marker can't be
    located. We only need a few hundred bytes to find SOF in practice;
    the read is bounded by the file size.
    """
    try:
        with path.open("rb") as fh:
            soi = fh.read(2)
            if soi != b"\xff\xd8":
                return None
            while True:
                marker = fh.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                tag = marker[1]
                # SOI/EOI/RSTn carry no payload — stop or skip.
                if tag in (0xD8, 0xD9):
                    return None
                if 0xD0 <= tag <= 0xD7:
                    continue
                length_bytes = fh.read(2)
                if len(length_bytes) < 2:
                    return None
                length = int.from_bytes(length_bytes, "big")
                if tag in (0xC0, 0xC1, 0xC2, 0xC3):
                    # SOF0/1/2/3: precision (1) + height (2) + width (2)
                    payload = fh.read(5)
                    if len(payload) < 5:
                        return None
                    height = int.from_bytes(payload[1:3], "big")
                    width = int.from_bytes(payload[3:5], "big")
                    return (width, height)
                # Skip the segment payload (length includes its own 2 bytes).
                fh.seek(max(0, length - 2), 1)
    except OSError:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        if not _curl_to_file(url, target, timeout=timeout, curl_bin=curl_bin):
            continue
        size = target.stat().st_size
        if size <= MIN_VALID_BYTES:
            if log is not None:
                log.record(
                    "thumbnail_too_small", video_id=video_id, slug=slug,
                    url=url, bytes=size,
                )
            continue
        dims = _read_jpeg_dimensions(target)
        if dims is None:
            if log is not None:
                log.record(
                    "thumbnail_not_jpeg", video_id=video_id, slug=slug,
                    url=url, bytes=size,
                )
            continue
        width, height = dims
        if width < MIN_VALID_WIDTH or height < MIN_VALID_HEIGHT:
            if log is not None:
                log.record(
                    "thumbnail_dims_too_small", video_id=video_id, slug=slug,
                    url=url, width=width, height=height,
                )
            continue
        digest = _sha256(target)
        if digest in KNOWN_PLACEHOLDER_HASHES:
            if log is not None:
                log.record(
                    "thumbnail_known_placeholder", video_id=video_id,
                    slug=slug, url=url, sha256=digest,
                )
            continue
        if log is not None:
            log.record(
                "thumbnail_ok", video_id=video_id, slug=slug,
                url=url, bytes=size, width=width, height=height,
            )
        return target
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
    if log is not None:
        log.record("thumbnail_failed", video_id=video_id, slug=slug)
    return None
