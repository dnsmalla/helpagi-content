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

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.json"
_raw_schema = json.loads(SCHEMA_PATH.read_text())
# Remove schema-level content minLength so the validator's own word-count gate
# is the sole content-length enforcement (avoids double-gating with different
# units: schema uses chars, validator uses words).
SCHEMA = {
    **_raw_schema,
    "properties": {
        **_raw_schema["properties"],
        "content": {k: v for k, v in _raw_schema["properties"]["content"].items()
                    if k != "minLength"},
    },
}

MIN_WORDS = 100
MAX_WORDS = 4000
DUPLICATE_PARAGRAPH_THRESHOLD = 0.7

# Topic relevance — must hit at least one keyword (whole-word match) in title
# or first ~200 words.  "model" and "system" are omitted: too generic to be
# reliable signals (a sourdough article can have "model" or "system").
TOPIC_KEYWORDS = [
    "ai", "agi", "artificial intelligence", "machine learning", "neural",
    "llm", "gpt", "transformer", "deep learning",
    "engineering", "software", "devops", "compiler",
    "agent", "robotics",
]


class ValidationError(Exception):
    """Raised when an article fails any hard gate."""


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _has_attribution(article: dict) -> bool:
    content = article.get("content", "")
    sv = article.get("sourceVideo", {})
    if "youtube.com/watch?v=" not in content:
        return False
    channel = sv.get("channel", "")
    return bool(channel) and channel in content


def _on_topic(article: dict) -> bool:
    title = article.get("title", "").lower()
    body = article.get("content", "").lower()
    head = body[:1200]  # first ~200 words
    haystack = title + " " + head
    return any(
        re.search(r"\b" + re.escape(kw) + r"\b", haystack)
        for kw in TOPIC_KEYWORDS
    )


def _has_duplicate_paragraphs(text: str) -> bool:
    paragraphs = _paragraphs(text)
    for i in range(len(paragraphs)):
        for j in range(i + 1, len(paragraphs)):
            ratio = difflib.SequenceMatcher(None, paragraphs[i], paragraphs[j]).ratio()
            if ratio >= DUPLICATE_PARAGRAPH_THRESHOLD:
                return True
    return False


def validate_article(article: dict) -> None:
    """Raise ValidationError if `article` fails any gate; return None on pass."""
    # 1. Word count (checked before schema so the error message is always
    #    "content too short" rather than a raw jsonschema char-length message).
    words = _word_count(article.get("content", ""))
    if words < MIN_WORDS:
        raise ValidationError(f"content too short ({words} < {MIN_WORDS} words)")
    if words > MAX_WORDS:
        raise ValidationError(f"content too long ({words} > {MAX_WORDS} words)")

    # 2. Schema (also catches enums / patterns).
    try:
        jsonschema.validate(article, SCHEMA)
    except jsonschema.ValidationError as e:
        raise ValidationError(f"schema: {e.message}") from e

    # 3. Attribution.
    if not _has_attribution(article):
        raise ValidationError("attribution missing (no youtube link or channel name in content)")

    # 4. Duplicate paragraphs.
    if _has_duplicate_paragraphs(article.get("content", "")):
        raise ValidationError("duplicate paragraphs detected (likely AI repetition)")

    # 5. Topic relevance.
    if not _on_topic(article):
        raise ValidationError("off-topic (no AI/AGI/engineering keyword in title or opening)")


def main() -> int:
    """CLI: `python -m tools.validate_article path/to/article.json`."""
    import sys
    if len(sys.argv) != 2:
        print("usage: validate_article.py <path>", file=sys.stderr)
        return 2
    article = json.loads(Path(sys.argv[1]).read_text())
    try:
        validate_article(article)
    except ValidationError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
