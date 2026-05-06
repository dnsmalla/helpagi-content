"""Tests for lib.thumbnail."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lib import thumbnail
from lib.runlog import RunLog


def _make_jpeg(width: int, height: int, *, target_bytes: int = 0) -> bytes:
    """Build a minimal but parseable JPEG with given SOF dimensions."""
    out = bytearray(b"\xff\xd8")          # SOI
    out += b"\xff\xc0"                    # SOF0
    out += b"\x00\x11"                    # segment length 17
    out += b"\x08"                        # precision
    out += height.to_bytes(2, "big")
    out += width.to_bytes(2, "big")
    out += b"\x03"                        # 3 components
    out += b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    out += b"\xff\xd9"                    # EOI
    if target_bytes > len(out):
        out += b"\x00" * (target_bytes - len(out))
    return bytes(out)


def _make_curl_factory(*, by_url_kind: dict[str, bytes | None]):
    """Fake `subprocess.run` for curl: writes the given bytes for each url kind."""

    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        url = next(arg for arg in cmd if arg.startswith("http"))
        target = cmd[cmd.index("-o") + 1]
        kind = "maxres" if "maxresdefault" in url else "hq"
        payload = by_url_kind.get(kind)
        if payload is None:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=b"", stderr=b"404",
            )
        Path(target).write_bytes(payload)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b"", stderr=b"",
        )

    return _run


# ---- _read_jpeg_dimensions unit tests --------------------------------------


def test_jpeg_dim_parser_extracts_dims(tmp_path: Path) -> None:
    p = tmp_path / "img.jpg"
    p.write_bytes(_make_jpeg(1280, 720))
    assert thumbnail._read_jpeg_dimensions(p) == (1280, 720)


def test_jpeg_dim_parser_handles_padding(tmp_path: Path) -> None:
    p = tmp_path / "img.jpg"
    p.write_bytes(_make_jpeg(640, 360, target_bytes=8192))
    assert thumbnail._read_jpeg_dimensions(p) == (640, 360)


def test_jpeg_dim_parser_rejects_non_jpeg(tmp_path: Path) -> None:
    p = tmp_path / "not.jpg"
    p.write_bytes(b"PNG nope " * 200)
    assert thumbnail._read_jpeg_dimensions(p) is None


# ---- fetch_thumbnail integration tests --------------------------------------


def test_maxres_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={
            "maxres": _make_jpeg(1280, 720, target_bytes=50_000),
        }),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is not None
    assert out.name == "my-slug.jpg"
    ok_events = [e for e in log.entries if e["event"] == "thumbnail_ok"]
    assert ok_events
    assert ok_events[0]["width"] == 1280
    assert ok_events[0]["height"] == 720


def test_falls_back_to_hqdefault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={
            "maxres": None,
            "hq": _make_jpeg(480, 360, target_bytes=30_000),
        }),
    )
    out = thumbnail.fetch_thumbnail("abc12345678", "my-slug", tmp_path)
    assert out is not None
    assert out.stat().st_size == 30_000


def test_too_small_thumbnail_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sub-1KB response (YouTube placeholder)."""
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={
            "maxres": b"x" * 200,
            "hq": b"x" * 300,
        }),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is None
    assert any(e["event"] == "thumbnail_too_small" for e in log.entries)
    assert any(e["event"] == "thumbnail_failed" for e in log.entries)


def test_dimensions_too_small_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Over-1KB but JPEG dims below the floor → rejected on both URLs."""
    tiny_jpeg = _make_jpeg(120, 90, target_bytes=4096)
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={"maxres": tiny_jpeg, "hq": tiny_jpeg}),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is None
    dim_events = [e for e in log.entries if e["event"] == "thumbnail_dims_too_small"]
    assert len(dim_events) == 2
    assert dim_events[0]["width"] == 120


def test_non_jpeg_payload_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={
            "maxres": b"<html>404 not jpeg</html>" + b"\x00" * 4096,
            "hq": b"<html>nope</html>" + b"\x00" * 4096,
        }),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is None
    assert any(e["event"] == "thumbnail_not_jpeg" for e in log.entries)


def test_known_placeholder_hash_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bit-for-bit known placeholder must be rejected even if dims pass."""
    placeholder = _make_jpeg(1280, 720, target_bytes=4096)
    import hashlib
    digest = hashlib.sha256(placeholder).hexdigest()
    monkeypatch.setattr(
        thumbnail, "KNOWN_PLACEHOLDER_HASHES", {digest},
    )
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={
            "maxres": placeholder,
            "hq": placeholder,
        }),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is None
    assert any(e["event"] == "thumbnail_known_placeholder" for e in log.entries)


def test_both_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={"maxres": None, "hq": None}),
    )
    out = thumbnail.fetch_thumbnail("abc12345678", "my-slug", tmp_path)
    assert out is None
    assert not (tmp_path / "my-slug.jpg").exists()


def test_curl_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("curl not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    out = thumbnail.fetch_thumbnail("abc12345678", "my-slug", tmp_path)
    assert out is None
