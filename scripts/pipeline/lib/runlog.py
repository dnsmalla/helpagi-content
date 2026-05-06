"""Structured per-run JSON log.

Today the only debugging trail for a pipeline run is whatever the agent
prints to stdout. RunLog records discrete events (lock acquired, channel
probed, candidate kept/dropped, agent invoked, agent returned) so a future
operator can reconstruct what happened without re-running.

One file per run, written under ``scripts/pipeline/.run/runlog-<id>.json``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class RunLog:
    """Append-only event log written as a single JSON object per run."""

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or _make_run_id()
        self.started_at = _now_iso()
        self.entries: list[dict[str, Any]] = []

    def record(self, event: str, **fields: Any) -> None:
        """Record one event. ``event`` is a short snake_case verb."""
        self.entries.append({"ts": _now_iso(), "event": event, **fields})

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": _now_iso(),
            "entries": list(self.entries),
        }

    def write(self, dir_: Path) -> Path:
        """Write the log to ``<dir_>/runlog-<run_id>.json``. Returns the path."""
        dir_.mkdir(parents=True, exist_ok=True)
        path = dir_ / f"runlog-{self.run_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path
