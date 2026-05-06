"""HelpAGI pipeline orchestrator.

Phase 1 of de-LLM-ifying the pipeline. This entry point:
  1. Acquires a non-blocking file lock (prevents concurrent runs).
  2. Runs the deterministic Python discovery step (`lib.discover`) and
     persists the candidate list to `.run/candidates.json` for the agent.
  3. Invokes the Claude Code CLI agent against `agent-prompt.md`. The agent
     still does transcribe / write / validate / publish — but it now reads
     the prepared candidates instead of running yt-dlp itself.
  4. Writes a structured per-run JSON log under `.run/`.

Phase 2 (next batch) will pull transcribe + publish out of the agent and
narrow its tool surface to {WebSearch, WebFetch, Read}.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from lib.discover import find_candidates
from lib.locking import FileLock, LockHeld
from lib.runlog import RunLog

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_DIR.parent.parent
RUN_DIR = PIPELINE_DIR / ".run"
LOCK_PATH = RUN_DIR / "lock"
CANDIDATES_PATH = RUN_DIR / "candidates.json"
CONFIG_PATH = PIPELINE_DIR / "config.yaml"
CHANNELS_PATH = PIPELINE_DIR / "channels.yaml"
STATE_PATH = PIPELINE_DIR / ".pipeline-state.json"
AGENT_PROMPT_PATH = PIPELINE_DIR / "agent-prompt.md"

AGENT_TOOLS = "Bash,Read,Write,Edit,WebSearch,WebFetch"


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"schema_version": 1, "last_run": None, "processed_video_ids": []}
    return json.loads(STATE_PATH.read_text())


def _invoke_agent(log: RunLog) -> int:
    prompt = AGENT_PROMPT_PATH.read_text()
    cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--allowedTools", AGENT_TOOLS,
        prompt,
    ]
    log.record("agent_invoke", tools=AGENT_TOOLS)
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    except FileNotFoundError:
        log.record("agent_missing")
        print("ERROR: 'claude' CLI not on PATH", file=sys.stderr)
        return 127
    log.record("agent_return", returncode=result.returncode)
    return result.returncode


def _run(log: RunLog) -> int:
    cfg = _load_yaml(CONFIG_PATH) or {}
    channels_doc = _load_yaml(CHANNELS_PATH) or {}
    channels = channels_doc.get("channels", [])
    state = _load_state()

    log.record(
        "config_loaded",
        dry_run=bool(cfg.get("dry_run")),
        cap=int(cfg.get("daily_article_cap", 5)),
        research_budget=int(cfg.get("research_budget", 4)),
    )

    candidates = find_candidates(
        channels=channels,
        topic_keywords=cfg.get("topic_keywords", []),
        duration_min=int(cfg.get("video_duration_min_sec", 300)),
        duration_max=int(cfg.get("video_duration_max_sec", 5400)),
        processed_ids=set(state.get("processed_video_ids", []) or []),
        skip_ids=set(cfg.get("manual_skip_video_ids", []) or []),
        cap=int(cfg.get("daily_article_cap", 5)),
        log=log,
    )
    log.record("discovery_complete", count=len(candidates))

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(candidates, indent=2) + "\n")
    log.record("candidates_written", path=str(CANDIDATES_PATH))

    if not candidates:
        print("→ 0 candidates discovered; skipping agent invocation.")
        log.record("agent_skipped", reason="no_candidates")
        return 0

    return _invoke_agent(log)


def main() -> int:
    log = RunLog()
    rc = 1
    try:
        with FileLock(LOCK_PATH):
            log.record("lock_acquired", path=str(LOCK_PATH))
            rc = _run(log)
    except LockHeld as e:
        log.record("lock_held", error=str(e))
        print(f"ERROR: {e}", file=sys.stderr)
        rc = 1
    finally:
        log.record("run_end", returncode=rc)
        path = log.write(RUN_DIR)
        # Best-effort console pointer; runs are headless and stdout may be tee'd.
        if os.environ.get("HELPAGI_QUIET") != "1":
            print(f"→ run log: {path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
