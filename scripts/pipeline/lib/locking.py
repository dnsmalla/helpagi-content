"""Non-blocking exclusive file lock for pipeline runs.

Two concurrent `run.sh` invocations would race on `.pipeline-state.json`,
`articles.json`, and `git push`. `FileLock` is acquired by the orchestrator
on entry and released on exit; a second invocation while the first is in
flight raises `LockHeld` immediately rather than blocking.
"""
from __future__ import annotations

import errno
import fcntl
from pathlib import Path
from types import TracebackType
from typing import IO


class LockHeld(RuntimeError):
    """Raised when another process already holds the lock."""


class FileLock:
    """Context manager wrapping ``fcntl.flock`` with non-blocking acquire."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: IO[str] | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self._fh.close()
            self._fh = None
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise LockHeld(
                    f"another pipeline run holds the lock at {self.path}"
                ) from e
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
