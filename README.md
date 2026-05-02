# HelpAGI Content

Single source of truth for HelpAGI's article feed. Served via GitHub Pages and consumed by the iOS app and (later) the web site at helpagi.blog.

- **Live URL:** `https://dnsmalla.github.io/helpagi-content/articles.json`
- **Pipeline:** [`scripts/pipeline/`](scripts/pipeline/) — on-demand auto-publishing from YouTube via the Claude Code agent (run manually from Terminal; no daemon)

## Files

| Path | Purpose |
|---|---|
| `articles.json` | The feed. Wrapped shape: `{ "version": "...", "lastUpdated": "...", "articles": [ ... ] }` |
| `images/` | Per-article hero images (`<slug>.jpg` matched against `imageUrl` in the JSON) |
| `scripts/pipeline/` | The auto-publishing pipeline (see its [README](scripts/pipeline/README.md)) |
| `_proposed/<YYYY-MM-DD>/` | Dry-run output: agent-generated articles staged for human review before publishing |

## Article schema

Every article in `articles[]` matches [`scripts/pipeline/schema.json`](scripts/pipeline/schema.json). Required fields:

```json
{
  "slug": "kebab-case-slug",
  "title": "Headline ≤ 120 chars",
  "date": "2026-05-01T00:00:00Z",
  "summary": "1–2 sentences, 40–320 chars.",
  "content": "Markdown body, ≥ 800 words, ending with a `## Source` section.",
  "author": "HelpAGI Editorial Team",
  "category": "AI",
  "tags": ["...", "..."],
  "readingMinutes": 7,
  "focusKeyword": "...",
  "keywords": ["..."],
  "contentType": "explainer",
  "mainTopic": "...",
  "complexity": "intermediate",
  "audience": "...",
  "optimizedForScoring": true,
  "scoringVersion": "2.0",
  "sourceVideo": {
    "id": "11-char-id",
    "title": "...",
    "channel": "...",
    "channelHandle": "@handle",
    "url": "https://www.youtube.com/watch?v=...",
    "publishedAt": "2026-04-29T18:30:00Z",
    "durationSeconds": 720
  },
  "imageUrl": "https://dnsmalla.github.io/helpagi-content/images/<slug>.jpg"
}
```

Run [`scripts/pipeline/tools/validate_article.py`](scripts/pipeline/tools/validate_article.py) on any candidate article to confirm it matches the contract.

## How content lands here

There are two paths:

### 1. On-demand auto-pipeline (default)

Run [`scripts/pipeline/run.sh`](scripts/pipeline/run.sh) from a Terminal whenever you want fresh content:

```bash
bash scripts/pipeline/run.sh
```

The script invokes the local Claude Code CLI (your subscription, no API key) which:

1. Pulls the last 24 h of uploads from 8 curated AI/AGI/engineering YouTube channels via `yt-dlp`.
2. Transcribes their auto-captions.
3. Writes ≤ 5 articles in HelpAGI editorial voice.
4. Validates each (schema + slop + attribution + topic gates).
5. Saves thumbnails to `images/`.
6. Appends to `articles.json` and `git push`es.

GitHub Pages auto-deploys; iOS sees the update within ~1 hour (`cacheExpirationSeconds: 3600` in `ContentManager`).

Default mode is **dry-run** (proposed articles land in `_proposed/<date>/`, nothing pushed). Edit [`scripts/pipeline/config.yaml`](scripts/pipeline/config.yaml) and set `dry_run: false` once you trust the output. There is intentionally no cron / launchd daemon — see [`scripts/pipeline/README.md`](scripts/pipeline/README.md) for why and how to add one back if you really want it.

### 2. Manual edits

For corrections or hand-curated posts, edit `articles.json` directly:

```bash
git pull
$EDITOR articles.json          # add/edit one entry in articles[]
git add articles.json
git commit -m "edit: <slug>"
git push
```

GitHub Pages picks up the push within 30–60 s.

## Setting up GitHub Pages (one-time)

1. Push this repo to GitHub.
2. Settings → Pages → Source: **Deploy from branch** → Branch: `main` / root.
3. Save. The feed becomes live at `https://<user>.github.io/<repo>/articles.json`.

## Pipeline-related links

- Daily-run script: [`scripts/pipeline/run.sh`](scripts/pipeline/run.sh)
- Agent prompt: [`scripts/pipeline/agent-prompt.md`](scripts/pipeline/agent-prompt.md)
- Editorial voice: [`scripts/pipeline/style-guide.md`](scripts/pipeline/style-guide.md)
- Validator + tests: [`scripts/pipeline/tools/`](scripts/pipeline/tools/)
