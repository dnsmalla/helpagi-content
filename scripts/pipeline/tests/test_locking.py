"""Tests for lib.locking.FileLock."""
from __future__ import annotations

from pathlib import Path

import pytest

from lib.locking import FileLock, LockHeld


def test_acquire_and_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    with FileLock(lock_path):
        assert lock_path.exists()
    # After release, the file persists but the lock is free; we should be
    # able to acquire it again immediately.
    with FileLock(lock_path):
        pass


def test_concurrent_acquire_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock"
    with FileLock(lock_path):
        with pytest.raises(LockHeld):
            with FileLock(lock_path):
                pass


def test_creates_parent_directory(tmp_path: Path) -> None:
    lock_path = tmp_path / "nested" / "deep" / "lock"
    with FileLock(lock_path):
        assert lock_path.exists()
