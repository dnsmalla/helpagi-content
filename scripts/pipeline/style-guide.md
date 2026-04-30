# HelpAGI Editorial Voice

The agent must use this voice for every article it writes.

## Tone

- **Explanatory, not promotional.** No hype words: "revolutionary", "game-changer", "10x", "mind-blowing", "unprecedented".
- **Evidence-led.** Tie every claim back to something the speaker actually said in the video. If the speaker speculates, mark it as speculation.
- **Direct.** Short sentences. Active voice. Drop weasel phrases ("it could be argued", "some say").
- **Curious, not breathless.** The reader is an intelligent engineer who wants to understand, not be sold to.

## Structure

Every article has, in this order:

1. **One-paragraph hook** (also used as `summary`). Tell the reader what the video is about and why an engineer should care, in 2–4 sentences.
2. **2–4 H2 sections** (`## Heading`). Each covers one idea from the video. No empty sections.
3. **What this means for builders / readers** (H2). One paragraph translating the video's content into practical takeaways. Keep it grounded; if the video offers no clear takeaway, say so.
4. **Source** (H2). Always last. Format: ``This article summarizes ["<video title>"](<video URL>) by <channel name> (<channel handle>). Watch the original for the full discussion and citations.``

## Length

- Body content: 1500–3000 words (≈ 5–10 minutes reading).
- Summary field: 1–2 sentences, 40–280 characters.

## What never to do

- **Never invent facts, numbers, names, or quotes.** If the transcript doesn't have it, don't write it.
- **Never paraphrase so closely that it amounts to copying.** Summarize and explain in your own words.
- **Never write listicle-style content** ("5 reasons", "10 things"). Use prose.
- **Never use emojis** in the article body.
- **Never refer to "this article" or "in this post"** — write as if the reader landed cold.

## Tags and metadata

- `tags`: 3–10 specific topical tags. Prefer concrete topics ("transformer scaling") over generic ones ("AI").
- `keywords`: SEO-oriented; include the focus keyword + close variants.
- `category`: pick the single best fit from `AI | AGI | Engineering | Future Tech | Tutorial`.
- `complexity`: be honest. If the video assumes ML coursework, say `advanced`.
- `audience`: one sentence describing who the article is for.
- `focusKeyword`: the single phrase someone might Google to find this article.
