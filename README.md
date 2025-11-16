# HelpAGI Content

This repository contains the unified blog content for HelpAGI, served via GitHub Pages.

## Structure

- `articles.json` - All blog posts as a single JSON array (used by web + iOS)
- `images/` - Blog post images (optional)

## GitHub Pages Setup

1. Push this repository to GitHub
2. Go to Settings → Pages
3. Source: Deploy from branch
4. Branch: `main` / root
5. Save

Your content will be available at:
`https://yourusername.github.io/helpagi-content/articles.json`

## Updating Content

1. Update `posts.json` locally
2. Commit and push to GitHub
3. Wait 30-60 seconds for GitHub Pages to deploy
4. Apps will detect the update automatically

## Content Format

Each post in `articles.json` follows this structure:

```json
{
  "slug": "post-slug",
  "title": "Post Title",
  "date": "2025-11-16",
  "summary": "Brief summary",
  "content": "Full markdown content...",
  "author": "Author Name",
  "category": { "slug": "ai", "name": "AI" },
  "tags": [{ "slug": "tag", "name": "Tag" }],
  "readingMinutes": 5
}
```

## Auto-Sync Script

To sync from the main blog repository:

```bash
cd web_blog
node tools/sync-to-github-pages.mjs ../helpagi-content
cd ../helpagi-content
git add .
git commit -m "Update blog content"
git push
```
