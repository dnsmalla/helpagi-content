#!/usr/bin/env bash
# Local runner for the HelpAGI content pipeline.
#
# This script runs the pipeline on YOUR machine using the Claude Code CLI
# you're already logged into. No OAuth token, no API key, nothing committed
# to the repo. Auth is whatever `claude` is using locally — typically your
# Claude Pro/Max subscription session.
#
# Usage:
#     bash scripts/pipeline/run.sh
#
# Schedule it daily with launchd (macOS) or cron — see the plist example in
# scripts/pipeline/README.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# --- Sanity checks -----------------------------------------------------------

if [ ! -f articles.json ]; then
    echo "ERROR: articles.json missing — wrong directory?" >&2
    echo "Expected: $REPO_ROOT/articles.json" >&2
    exit 1
fi

if [ ! -f scripts/pipeline/agent-prompt.md ]; then
    echo "ERROR: scripts/pipeline/agent-prompt.md missing." >&2
    exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: 'claude' CLI not on PATH." >&2
    echo "Install Claude Code: https://claude.com/claude-code" >&2
    exit 1
fi

# --- Bootstrap the validator's venv if missing -------------------------------
# The agent calls scripts/pipeline/.venv/bin/python3 -m tools.validate_article.
# Without the venv, the validator can't import jsonschema and every article
# would be dropped.
VENV_DIR="scripts/pipeline/.venv"
if [ ! -x "$VENV_DIR/bin/python3" ]; then
    echo "→ Creating validator venv at $VENV_DIR…"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
    "$VENV_DIR/bin/pip" install -r scripts/pipeline/requirements.txt >/dev/null
fi

# --- Refresh yt-dlp ----------------------------------------------------------
# YouTube ships scraper-defeating changes every few weeks. Always run latest.
echo "→ Updating yt-dlp…"
if command -v pipx >/dev/null 2>&1; then
    pipx upgrade yt-dlp >/dev/null 2>&1 \
        || pipx install yt-dlp >/dev/null 2>&1 \
        || true
elif command -v pip3 >/dev/null 2>&1; then
    pip3 install --user --upgrade yt-dlp >/dev/null 2>&1 || true
fi

if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "WARN: yt-dlp still not on PATH. Agent may fail at the discovery step." >&2
fi

# --- Run the agent -----------------------------------------------------------
# Tool surface is restricted to Bash/Read/Write/Edit and the repo root.
# --dangerously-skip-permissions is needed for an unattended (cron/launchd)
# run — without it, every Bash + Edit prompts for confirmation. Safe in this
# context: the agent can only operate inside this repo and push to its own
# `origin`. If you'd rather approve each step interactively, drop that flag.
echo "→ Running pipeline agent…"
claude \
    --print \
    --dangerously-skip-permissions \
    --allowedTools "Bash,Read,Write,Edit" \
    "$(cat scripts/pipeline/agent-prompt.md)"

# --- Final state -------------------------------------------------------------
echo
echo "→ Final state:"
git status --short || true
git log -1 --oneline
