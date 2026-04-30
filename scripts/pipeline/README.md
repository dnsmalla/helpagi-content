# HelpAGI Content Pipeline

Daily, subscription-powered automation that turns AI/AGI/engineering YouTube uploads into validated articles in `articles.json`. Consumed by the HelpAGI iOS app and (later) the web app.

- **Spec:** `../../docs/superpowers/specs/2026-04-30-auto-content-pipeline-design.md` in the iOS-app repo.
- **Architecture:** Claude Code agent runs **locally** on your machine via the `claude` CLI you're already logged into. No OAuth token, no API key, nothing in the repo. Auth is whatever your local `claude` is using — typically your Claude Pro/Max subscription session.

## Files

| Path | Purpose |
|------|---------|
| `run.sh` | Entry point. Runs the pipeline via the local `claude` CLI. |
| `agent-prompt.md` | The instructions Claude Code follows on each run. |
| `channels.yaml` | 8 curated AI/AGI/engineering channels with priorities. |
| `style-guide.md` | HelpAGI editorial voice; the agent obeys this. |
| `schema.json` | JSON schema every article must conform to. |
| `config.yaml` | Runtime knobs: `dry_run`, `daily_article_cap`, topic keywords. |
| `.pipeline-state.json` | Already-processed video IDs. Updated by each run. |
| `bootstrap.py` | One-time migration that wraps `articles.json` array into `{articles: [...]}` shape. |
| `tools/validate_article.py` | The hard gate: schema + slop + attribution + topic checks. |
| `tools/tests/` | Pytest tests + fixtures for the validator. |

## Prerequisites (one-time)

1. **Claude Code CLI** installed and logged in:
   ```bash
   claude --version           # confirm it's installed
   claude /login              # only needed if you've never logged in
   ```
2. **Python 3.11+** with `pipx` or `pip3` (for installing `yt-dlp`).
3. **Validator deps** (only if you want to run the tests / validator manually):
   ```bash
   cd helpagi-content/scripts/pipeline
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Running the pipeline

```bash
cd /path/to/helpagi-content
bash scripts/pipeline/run.sh
```

The script will:

1. Refresh `yt-dlp` (YouTube changes its scraper-defeats often).
2. Hand the agent prompt to `claude --print`, scoped to `Bash,Read,Write,Edit` tools.
3. The agent discovers new videos, transcribes captions, writes ≤ 5 articles, validates them, saves thumbnails, commits — all within this repo.
4. Print final `git status` + last commit so you can see what changed.

`config.yaml`'s `dry_run: true` (default) sends proposed articles to `_proposed/<date>/<slug>.json` instead of appending to `articles.json`. Flip to `false` once you trust the output.

## Scheduling daily runs

### macOS (launchd)

Save this as `~/Library/LaunchAgents/blog.helpagi.pipeline.plist` and adjust paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>blog.helpagi.pipeline</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/YOU/path/to/helpagi-content/scripts/pipeline/run.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>9</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/tmp/helpagi-pipeline.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/helpagi-pipeline.err</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/YOU/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/blog.helpagi.pipeline.plist
launchctl start blog.helpagi.pipeline    # run once now to test
tail -f /tmp/helpagi-pipeline.log         # watch output
```

### Linux (cron)

```bash
crontab -e
# Add:
0 9 * * * /bin/bash /home/YOU/path/to/helpagi-content/scripts/pipeline/run.sh \
  >> /tmp/helpagi-pipeline.log 2>&1
```

> **Important for cron:** cron runs with a minimal `PATH`. Make sure the path in your crontab includes the directory where `claude` lives (`which claude` shows you). The launchd plist above already does this via `EnvironmentVariables`.

> **Computer must be awake** at the scheduled time. macOS users on laptops: consider `caffeinate -s` or just run on a desktop / always-on Mac mini.

## Manual sub-commands (for testing)

```bash
# Validator unit tests
cd helpagi-content/scripts/pipeline
source .venv/bin/activate
python3 -m pytest tools/tests/ -v

# Validate one article file
python3 -m tools.validate_article tools/tests/fixtures/good_article.json

# Bootstrap (idempotent — safe to re-run)
cd ../..
python3 scripts/pipeline/bootstrap.py
```

## How the iOS app consumes this

`HelpAGI/Services/ContentManager.swift` fetches `https://dnsmalla.github.io/helpagi-content/articles.json` and decodes a `{articles: [...]}` shape with a 1-hour cache. The bootstrap script (run once) gives it that shape; the daily pipeline keeps it that shape.

After your local run pushes new articles to `dnsmalla/helpagi-content`, GitHub Pages auto-deploys and the iOS app sees fresh content within ~1 hour.

## Subscription budget

5 articles/day stays well within Claude Pro daily limits in normal use. If a run hits the subscription ceiling mid-job, the script exits and `.pipeline-state.json` records what was already published; tomorrow's run picks up the rest. There is **zero per-token cost** — your Pro/Max plan covers everything.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `claude: command not found` in cron/launchd | `PATH` doesn't include the directory `claude` is in | Set `PATH` explicitly in the launchd plist or crontab (see scheduling section) |
| `WARN: yt-dlp still not on PATH` | Neither pipx nor pip3 succeeded | Install yt-dlp manually: `pip3 install --user --upgrade yt-dlp` |
| 0 candidates discovered | No qualifying uploads in 24h | Normal on slow days; nothing to do |
| All candidates skipped at validation | Style-guide / schema mismatch | Inspect failed articles in `_proposed/<date>/`; tighten the prompt |
| `yt-dlp` errors on every channel | YouTube changed scraping | run.sh already pip-upgrades yt-dlp; if persistent, check yt-dlp's GitHub for a fresh release |
| Pipeline got partway then stopped | Subscription rate limit hit | Re-run in a few hours; `.pipeline-state.json` deduplicates already-published videos |
| Want to approve each step interactively | `--dangerously-skip-permissions` flag in run.sh | Edit run.sh and remove that line; the run will prompt before every Edit/Bash |
