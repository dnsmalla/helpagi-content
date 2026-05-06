# HelpAGI Editorial Voice

The agent must use this voice for every article it writes.

## What HelpAGI articles actually are

A HelpAGI article is **not** a YouTube transcript summary. It is a research-augmented blog post anchored on a specific video. The video is the *origin* — the reason this piece exists today and the primary attribution. Web research provides the corroborating context, primary sources, and background that a working engineer needs to actually use the information.

If the transcript alone can carry a substantive 2000-word piece, that's fine. More often you'll need 2–4 web sources to back up specific claims, fill in background, or verify a number the speaker cited.

## Tone

- **Explanatory, not promotional.** No hype words: "revolutionary", "game-changer", "10x", "mind-blowing", "unprecedented", "groundbreaking", "insane".
- **Evidence-led.** Every claim traces to the transcript or to a cited URL in `references[]`. If the speaker speculates, mark it as speculation. If a research source disagrees with the speaker, surface the disagreement.
- **Direct.** Short sentences. Active voice. Drop weasel phrases ("it could be argued", "some say").
- **Curious, not breathless.** The reader is a working engineer who wants to understand, not be sold to.

## Structure

Every article has, in this order:

1. **One-paragraph hook** (also used as `summary`). 2–4 sentences explaining what the video covers and why a working engineer should care.
2. **4–6 H2 sections.** Each covers one idea, anchored on the transcript and supplemented with cited research. No empty sections. No section that exists only to pad word count.
3. **What this means for builders / readers** (H2). One paragraph translating the video + research into practical takeaways. If there is no clear takeaway, say that — do not invent one.
4. **`## Source`** (H2). Always penultimate. Format: ``This article summarizes ["<video title>"](<video URL>) by <channel name> (<channel handle>) and the research below. Watch the original for the full discussion.``
5. **`## References`** (H2). Always last. One bullet per cited source: `- [Title](URL) (accessed YYYY-MM-DD)`. Required when `references[]` is non-empty; omit the heading entirely when no web research was used.

## Citation contract

- Every fact, number, proper noun, quote, or specific claim traces to **either** the transcript **or** a URL in `references[]`.
- Research-backed claims are **inline-cited** with Markdown links: `[the model's MMLU score is 86.4](https://example.com/post)`. Do not use footnote-style references with no inline anchor.
- Do not cite a URL you have not actually fetched. Do not cite a page that doesn't contain the claim. If a source disappears or paywalls between research and write, drop the citation and either rewrite the claim from the transcript or drop the claim.
- Do not cite other AI-generated summary sites. Do not cite content farms. Do not cite marketing pages.

## Length

- Body content: **2000–2800 words target**. Floor 1500. Ceiling 3000. The validator enforces the floor and ceiling; the target is what the agent should *aim* for.
- Summary field: 1–2 sentences, 40–280 characters.
- If, after research, you cannot reach 1500 substantive words for this video, **drop the candidate**. Do not pad.

## What never to do

- **Never invent facts, numbers, names, or quotes.** If the transcript doesn't have it and you can't find a research source for it, drop the claim.
- **Never pad.** No filler sections. No paragraph that restates the previous paragraph. No "It is worth noting that…" preambles.
- **Never paraphrase so closely it amounts to copying.** Summarize and explain in your own words.
- **Never write listicle-style content** ("5 reasons", "10 things", "Top 10"). Use prose.
- **Never use emojis** in title or body.
- **Never refer to "this article" or "in this post"** — write as if the reader landed cold.
- **Never cite a URL you didn't actually fetch.**

## Tags and metadata

- `tags`: 3–10 specific topical tags. Prefer concrete topics ("transformer scaling") over generic ones ("AI").
- `keywords`: SEO-oriented; include the focus keyword + close variants.
- `category`: pick the single best fit from `AI | AGI | Engineering | Future Tech | Tutorial`.
- `complexity`: be honest. If the video assumes ML coursework, say `advanced`.
- `audience`: one sentence describing who the article is for.
- `focusKeyword`: the single phrase someone might Google to find this article.
