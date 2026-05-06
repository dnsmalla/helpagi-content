"""Invoke the Claude Code CLI as a single-article writer.

The agent's role has shrunk from "do everything" (orchestration + research +
writing + git) to *just* the creative step: read one prepared article-input
JSON, optionally do web research within budget, return one article JSON.

Tool surface is narrowed to ``WebSearch,WebFetch,Read`` — no Bash, no Write.
The orchestrator captures stdout, extracts the JSON object, and hands it to
the validator.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runlog import RunLog

DEFAULT_TOOLS = "WebSearch,WebFetch,Read"
DEFAULT_TIMEOUT_SECONDS = 600
DROP_SENTINEL = "DROP"


class WriterError(RuntimeError):
    """Raised when the writer agent fails in a way the orchestrator should log + skip."""


def _extract_json_object(stdout: str) -> dict | None:
    """Pull the first balanced ``{...}`` JSON object out of stdout.

    Tolerates leading prose, trailing prose, and Markdown code fences. Returns
    None if no parseable object is found.
    """
    text = stdout.strip()
    if not text:
        return None
    if text == DROP_SENTINEL:
        return None
    # Strip Markdown code fences if present.
    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    # Direct parse first — agent may have done what we asked.
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict):
        return loaded
    # Fall back to balanced-brace extraction (greedy match risks crossing
    # objects, so do a manual depth scan from the first `{`).
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
                    return parsed if isinstance(parsed, dict) else None
    return None


def is_drop_signal(stdout: str) -> bool:
    """True if the agent explicitly signalled DROP (transcript+research too thin)."""
    return stdout.strip() == DROP_SENTINEL


def invoke_writer(
    *,
    prompt_path: Path,
    cwd: Path,
    claude_bin: str = "claude",
    allowed_tools: str = DEFAULT_TOOLS,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    skip_permissions: bool = True,
    log: "RunLog | None" = None,
) -> dict | None:
    """Run the writer prompt; return article dict, None for DROP / parse fail."""
    cmd = [claude_bin, "--print"]
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["--allowedTools", allowed_tools, prompt_path.read_text()])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if log is not None:
            log.record("writer_timeout", timeout=timeout)
        return None
    except FileNotFoundError as e:
        raise WriterError(f"'{claude_bin}' not on PATH") from e

    if result.returncode != 0:
        if log is not None:
            log.record(
                "writer_nonzero_exit",
                returncode=result.returncode,
                stderr=(result.stderr or "").strip()[:500],
            )
        return None

    if is_drop_signal(result.stdout):
        if log is not None:
            log.record("writer_drop")
        return None

    article = _extract_json_object(result.stdout)
    if article is None:
        if log is not None:
            log.record(
                "writer_parse_fail",
                excerpt=result.stdout.strip()[:300],
            )
    return article
