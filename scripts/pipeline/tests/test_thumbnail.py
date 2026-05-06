"""Tests for lib.thumbnail."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from lib import thumbnail
from lib.runlog import RunLog


def _make_curl_factory(*, by_url_kind: dict[str, int | None]):
    """Build a fake `subprocess.run` for curl that writes a file of given size.

    `by_url_kind` maps "maxres" or "hq" to an integer byte count to write,
    or None to simulate a non-zero exit (no file written).
    """

    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        url = cmd[-3]  # ... -o <target> URL? Actually URL is before -o.
        # cmd shape: ["curl", "-fsSL", "--max-time", N, URL, "-o", target]
        # Find the URL by scanning for the first http(s):// arg.
        url = next(arg for arg in cmd if arg.startswith("http"))
        target = cmd[cmd.index("-o") + 1]
        kind = "maxres" if "maxresdefault" in url else "hq"
        size = by_url_kind.get(kind)
        if size is None:
            return subprocess.CompletedProcess(
                args=cmd, returncode=22, stdout=b"", stderr=b"404",
            )
        Path(target).write_bytes(b"x" * size)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b"", stderr=b"",
        )

    return _run


def test_maxres_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={"maxres": 50_000}),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is not None
    assert out.name == "my-slug.jpg"
    assert out.stat().st_size == 50_000
    assert any(e["event"] == "thumbnail_ok" for e in log.entries)


def test_falls_back_to_hqdefault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={"maxres": None, "hq": 30_000}),
    )
    out = thumbnail.fetch_thumbnail("abc12345678", "my-slug", tmp_path)
    assert out is not None
    assert out.stat().st_size == 30_000


def test_too_small_thumbnail_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """YouTube serves a tiny placeholder when no real thumbnail exists."""
    monkeypatch.setattr(
        subprocess, "run",
        _make_curl_factory(by_url_kind={"maxres": 200, "hq": 300}),
    )
    log = RunLog()
    out = thumbnail.fetch_thumbnail(
        "abc12345678", "my-slug", tmp_path, log=log,
    )
    assert out is None
    assert any(e["event"] == "thumbnail_too_small" for e in log.entries)
    assert any(e["event"] == "thumbnail_failed" for e in log.entries)


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
