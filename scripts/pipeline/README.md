# HelpAGI Content Pipeline

Daily, subscription-powered automation that turns AI/AGI/engineering YouTube uploads into validated articles in `articles.json`. Consumed by the HelpAGI iOS app and (later) the web app.

- **Spec:** `../../docs/superpowers/specs/2026-04-30-auto-content-pipeline-design.md` in the iOS-app repo.
- **Architecture:** Claude Code agent in GitHub Actions, authenticated via the user's Claude Pro/Max OAuth token. No paid API keys.

## Files

| Path | Purpose |
|------|---------|
| `agent-prompt.md` | The instructions Claude Code follows on each daily run. |
| `channels.yaml` | 8 curated AI/AGI/engineering channels with priorities. |
| `style-guide.md` | HelpAGI editorial voice; the agent obeys this. |
| `schema.json` | JSON schema every article must conform to. |
| `config.yaml` | Runtime knobs: `dry_run`, `daily_article_cap`, topic keywords. |
| `.pipeline-state.json` | Already-processed video IDs. Updated by each run. |
| `bootstrap.py` | One-time migration that wraps `articles.json` array into `{articles: [...]}` shape. |
| `tools/validate_article.py` | The hard gate: schema + slop + attribution + topic checks. |
| `tools/tests/` | Pytest tests + fixtures for the validator. |
| `../../.github/workflows/daily-content.yml` | Cron trigger (02:00 UTC daily). |

## First-time setup (user actions)

1. **Generate a Claude Code OAuth token** locally — the token is tied to your Claude Pro/Max subscription. From a terminal where Claude Code is logged in, follow the official instructions to export an OAuth token for non-interactive use (see Anthropic's `claude-code-action` README for the latest command). Treat the token like an API key.
2. **Add the token as a GitHub secret** in the `dnsmalla/helpagi-content` repo:
   - Settings → Secrets and variables → Actions → New repository secret
   - Name: `CLAUDE_CODE_OAUTH_TOKEN`
   - Value: the token from step 1
3. **First-run sanity check:** trigger the workflow manually (Actions tab → Daily Content Pipeline → Run workflow). It runs in dry-run mode (default in `config.yaml`) and writes proposed articles into `_proposed/<date>/`.
4. **Shadow week:** review whatever appears in `_proposed/<date>/` for 7 days. Adjust `agent-prompt.md` or `style-guide.md` as you learn.
5. **Go live:** edit `config.yaml`, set `dry_run: false`, commit and push. Articles will start landing in `articles.json` on the next 02:00-UTC run.

## Running locally

```bash
# One-time
cd helpagi-content/scripts/pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Validator tests
python3 -m pytest tools/tests/ -v

# Validate one article file
python3 -m tools.validate_article tools/tests/fixtures/good_article.json

# Bootstrap (idempotent)
cd ../..
python3 scripts/pipeline/bootstrap.py
```

You cannot run the *agent* locally without a Claude Code session — it's invoked by the GitHub Action. To test the agent's prompt before the cron fires, manually trigger the workflow with `dry_run: true`.

## How the iOS app consumes this

`HelpAGI/Services/ContentManager.swift` fetches `https://dnsmalla.github.io/helpagi-content/articles.json` and decodes a `{articles: [...]}` shape with a 1-hour cache. The bootstrap (Task 11) gives it that shape; daily runs maintain it.

## Subscription budget

5 articles/day stays well within Claude Pro daily limits in normal use. If a run exhausts the subscription budget mid-day, the agent exits gracefully and `.pipeline-state.json` keeps track of what was published; the next day picks up where it left off.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Workflow exits with `oauth_token` error | Secret missing or expired | Re-export token, update GitHub secret |
| 0 candidates discovered | No qualifying uploads in 24h | Normal on slow days; nothing to do |
| All candidates skipped at validation | Style-guide / schema mismatch | Inspect failed articles in workflow logs; tighten the prompt |
| `yt-dlp` errors on every channel | YouTube changed scraping | Workflow already pip-installs latest yt-dlp each run; if persistent, file an issue against yt-dlp |
