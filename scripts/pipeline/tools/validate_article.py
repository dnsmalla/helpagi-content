"""Article validator. The single hard gate between agent output and articles.json.

A `ValidationError` from any check causes the agent to drop the article and
move on. Never block the run — log and skip.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import jsonschema
import yaml

PIPELINE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PIPELINE_DIR / "schema.json"
CONFIG_PATH = PIPELINE_DIR / "config.yaml"

SCHEMA = json.loads(SCHEMA_PATH.read_text())
_CFG = yaml.safe_load(CONFIG_PATH.read_text())
TOPIC_KEYWORDS = [str(kw).lower() for kw in _CFG.get("topic_keywords", [])]

MIN_WORDS = 1500
MAX_WORDS = 3000
DUPLICATE_PARAGRAPH_THRESHOLD = 0.7
DUPLICATE_PARAGRAPH_SCAN_LIMIT = 60
TITLE_SIMILARITY_THRESHOLD = 0.85
WORDS_PER_MINUTE = 200
READING_MINUTES_TOLERANCE_PCT = 0.4

# Hype/marketing language banned by style-guide.md. Matched whole-word /
# whole-phrase, case-insensitive, against title + summary + content.
SLOP_WORDS = [
    "revolutionary",
    "game-changer",
    "game changer",
    "10x",
    "mind-blowing",
    "mind blowing",
    "blow your mind",
    "unprecedented",
    "groundbreaking",
    "paradigm shift",
    "world-changing",
    "jaw-dropping",
    "earth-shattering",
    "insane",
    "breathtaking",
]

# Listicle title patterns banned by style-guide.md ("Never write listicle-style
# content"). Matched against the article title.
_LISTICLE_PATTERNS = [
    re.compile(
        r"^\s*\d+\s+(reasons|things|ways|tips|hacks|tricks|secrets|steps|"
        r"signs|facts|rules|lessons|mistakes|examples|tools)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*top\s+\d+\b", re.IGNORECASE),
]

# Unicode ranges where emoji live. Skips math/symbol blocks that legitimately
# appear in technical writing (∑, ≤, ±, etc.).
_EMOJI_RANGES = (
    (0x1F300, 0x1F5FF),
    (0x1F600, 0x1F64F),
    (0x1F680, 0x1F6FF),
    (0x1F700, 0x1F77F),
    (0x1F780, 0x1F7FF),
    (0x1F800, 0x1F8FF),
    (0x1F900, 0x1F9FF),
    (0x1FA00, 0x1FA6F),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
)


class ValidationError(Exception):
    """Raised when an article fails any hard gate."""


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _has_attribution(article: dict) -> bool:
    """Require an explicit `## Source` heading whose body contains the URL + channel."""
    content = article.get("content", "")
    sv = article.get("sourceVideo", {})
    url = sv.get("url", "")
    channel = sv.get("channel", "")
    if not url or not channel:
        return False
    match = re.search(r"^##\s+Source\s*$", content, flags=re.MULTILINE)
    if not match:
        return False
    tail = content[match.end():]
    return url in tail and channel in tail


def _has_empty_headings(text: str) -> bool:
    """Return True if any Markdown heading has no content before the next heading."""
    lines = text.splitlines()
    heading_pattern = re.compile(r"^#{1,6} ")
    i = 0
    while i < len(lines):
        if heading_pattern.match(lines[i]):
            j = i + 1
            found_content = False
            while j < len(lines):
                stripped = lines[j].strip()
                if heading_pattern.match(lines[j]):
                    break
                if stripped:
                    found_content = True
                    break
                j += 1
            if not found_content:
                return True
        i += 1
    return False


def _on_topic(article: dict) -> bool:
    title = article.get("title", "").lower()
    body = article.get("content", "").lower()
    head = body[:1200]
    haystack = title + " " + head
    return any(
        re.search(r"\b" + re.escape(kw) + r"\b", haystack)
        for kw in TOPIC_KEYWORDS
    )


def _has_duplicate_paragraphs(text: str) -> bool:
    paragraphs = _paragraphs(text)[:DUPLICATE_PARAGRAPH_SCAN_LIMIT]
    for i in range(len(paragraphs)):
        for j in range(i + 1, len(paragraphs)):
            ratio = difflib.SequenceMatcher(None, paragraphs[i], paragraphs[j]).ratio()
            if ratio >= DUPLICATE_PARAGRAPH_THRESHOLD:
                return True
    return False


def _find_slop(text: str) -> str | None:
    haystack = text.lower()
    for word in SLOP_WORDS:
        if re.search(r"\b" + re.escape(word.lower()) + r"\b", haystack):
            return word
    return None


def _contains_emoji(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        for lo, hi in _EMOJI_RANGES:
            if lo <= cp <= hi:
                return True
    return False


def _is_listicle_title(title: str) -> bool:
    return any(p.search(title) for p in _LISTICLE_PATTERNS)


def _reading_time_off(article: dict) -> str | None:
    minutes = article.get("readingMinutes")
    if not isinstance(minutes, int):
        return None
    words = _word_count(article.get("content", ""))
    expected = max(1, round(words / WORDS_PER_MINUTE))
    tolerance = max(2, round(expected * READING_MINUTES_TOLERANCE_PCT))
    if abs(minutes - expected) > tolerance:
        return (
            f"readingMinutes={minutes} disagrees with {words} words "
            f"(expected ≈{expected}±{tolerance} min)"
        )
    return None


def _references_problem(article: dict) -> str | None:
    """Return reason string if `references[]` is malformed in context, else None.

    Schema covers shape; this enforces the editorial contract:
      - When non-empty, body must contain a `## References` heading.
      - Every reference URL must appear in the body (so we know it's
        actually cited, not stuffed in metadata).
    """
    refs = article.get("references")
    if not refs:
        return None
    content = article.get("content", "")
    heading = re.search(r"^##\s+References\s*$", content, flags=re.MULTILINE)
    if not heading:
        return "references[] is non-empty but no '## References' heading found in content"
    for ref in refs:
        url = ref.get("url", "")
        if url and url not in content:
            return f"references[] entry url not cited in body: {url}"
    return None


def _duplicates_existing(
    article: dict, existing: list[dict] | None
) -> str | None:
    if not existing:
        return None
    new_title = article.get("title", "").strip().lower()
    new_video_id = (article.get("sourceVideo") or {}).get("id", "")
    for prev in existing:
        prev_video_id = (prev.get("sourceVideo") or {}).get("id", "")
        if new_video_id and prev_video_id and new_video_id == prev_video_id:
            return f"sourceVideo.id={new_video_id} already published"
        prev_title = prev.get("title", "").strip().lower()
        if not prev_title or not new_title:
            continue
        ratio = difflib.SequenceMatcher(None, new_title, prev_title).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD:
            return (
                f"title too similar to existing '{prev.get('title')}' "
                f"(ratio={ratio:.2f})"
            )
    return None


def validate_article(
    article: dict,
    *,
    existing: list[dict] | None = None,
) -> None:
    """Raise ValidationError if `article` fails any gate; return None on pass.

    `existing`, when supplied, is the list of already-published articles
    (typically `articles.json`'s `articles[]`). Used for the dedupe check.
    """
    words = _word_count(article.get("content", ""))
    if words < MIN_WORDS:
        raise ValidationError(f"content too short ({words} < {MIN_WORDS} words)")
    if words > MAX_WORDS:
        raise ValidationError(f"content too long ({words} > {MAX_WORDS} words)")

    try:
        jsonschema.validate(article, SCHEMA)
    except jsonschema.ValidationError as e:
        raise ValidationError(f"schema: {e.message}") from e

    if not _has_attribution(article):
        raise ValidationError(
            "attribution missing (no '## Source' section linking the video and channel)"
        )

    if _has_duplicate_paragraphs(article.get("content", "")):
        raise ValidationError("duplicate paragraphs detected (likely AI repetition)")

    if _has_empty_headings(article.get("content", "")):
        raise ValidationError("empty heading detected")

    if not _on_topic(article):
        raise ValidationError(
            "off-topic (no AI/AGI/engineering keyword in title or opening)"
        )

    haystack = " ".join([
        article.get("title", ""),
        article.get("summary", ""),
        article.get("content", ""),
    ])
    slop = _find_slop(haystack)
    if slop is not None:
        raise ValidationError(f"slop word detected: '{slop}'")

    if _contains_emoji(article.get("content", "")) or _contains_emoji(article.get("title", "")):
        raise ValidationError("emoji detected (banned by style guide)")

    if _is_listicle_title(article.get("title", "")):
        raise ValidationError("listicle-style title (banned by style guide)")

    reason = _reading_time_off(article)
    if reason is not None:
        raise ValidationError(reason)

    reason = _references_problem(article)
    if reason is not None:
        raise ValidationError(reason)

    reason = _duplicates_existing(article, existing)
    if reason is not None:
        raise ValidationError(f"duplicate of existing article: {reason}")


def main() -> int:
    """CLI: `python -m tools.validate_article <path> [--against=articles.json]`."""
    import sys

    args = sys.argv[1:]
    against_path: Path | None = None
    positional: list[str] = []
    for a in args:
        if a.startswith("--against="):
            against_path = Path(a.split("=", 1)[1])
        else:
            positional.append(a)
    if len(positional) != 1:
        print(
            "usage: validate_article.py <path> [--against=articles.json]",
            file=sys.stderr,
        )
        return 2

    article = json.loads(Path(positional[0]).read_text())
    existing: list[dict] | None = None
    if against_path is not None:
        feed = json.loads(against_path.read_text())
        existing = feed.get("articles", []) if isinstance(feed, dict) else feed

    try:
        validate_article(article, existing=existing)
    except ValidationError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
