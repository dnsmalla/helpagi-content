"""Tests for tools.validate_article.

The validator is the *only* hard gate between agent output and the published
articles.json. Every check that drops an article must be tested here so a
regression in the validator can't silently let bad content through.
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from tools.validate_article import ValidationError, validate_article

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_good_article_passes():
    validate_article(load("good_article.json"))


def test_short_content_rejected():
    with pytest.raises(ValidationError, match="content too short"):
        validate_article(load("bad_article_short.json"))


def test_long_content_rejected():
    article = load("good_article.json")
    article["content"] = article["content"] + ("\n\nfiller paragraph. " * 800)
    with pytest.raises(ValidationError, match="content too long"):
        validate_article(article)


def test_missing_attribution_rejected():
    with pytest.raises(ValidationError, match="attribution missing"):
        validate_article(load("bad_article_no_attribution.json"))


def test_url_without_source_heading_rejected():
    """A URL pasted inline must not satisfy the attribution gate — the
    `## Source` heading is required."""
    article = load("good_article.json")
    article["content"] = article["content"].replace("\n\n## Source\n\n", "\n\n")
    with pytest.raises(ValidationError, match="attribution missing"):
        validate_article(article)


def test_repeated_paragraphs_rejected():
    with pytest.raises(ValidationError, match="duplicate paragraphs"):
        validate_article(load("bad_article_repeated.json"))


def test_schema_violation_rejected():
    bad = load("good_article.json")
    bad["category"] = "Cooking"
    with pytest.raises(ValidationError, match="schema"):
        validate_article(bad)


def test_off_topic_rejected():
    bad = load("good_article.json")
    bad["title"] = "How to bake sourdough at home"
    bad["content"] = bad["content"].replace("AGI", "sourdough").replace("AI ", "yeast ")
    with pytest.raises(ValidationError, match="off-topic"):
        validate_article(bad)


def test_empty_heading_rejected():
    with pytest.raises(ValidationError, match="empty heading"):
        validate_article(load("bad_article_empty_heading.json"))


def test_slop_word_rejected():
    with pytest.raises(ValidationError, match="slop word"):
        validate_article(load("bad_article_slop.json"))


def test_slop_word_in_title_rejected():
    article = load("good_article.json")
    article["title"] = "What AGI Means: A Game-Changer for Engineers"
    with pytest.raises(ValidationError, match="slop word"):
        validate_article(article)


def test_emoji_in_body_rejected():
    with pytest.raises(ValidationError, match="emoji detected"):
        validate_article(load("bad_article_emoji.json"))


def test_emoji_in_title_rejected():
    article = load("good_article.json")
    article["title"] = "What AGI Means in 2026 \U0001F680"
    with pytest.raises(ValidationError, match="emoji detected"):
        validate_article(article)


def test_listicle_title_rejected():
    with pytest.raises(ValidationError, match="listicle-style title"):
        validate_article(load("bad_article_listicle.json"))


def test_top_n_listicle_title_rejected():
    article = load("good_article.json")
    article["title"] = "Top 10 Tools Every AI Engineer Should Know"
    with pytest.raises(ValidationError, match="listicle-style title"):
        validate_article(article)


def test_reading_time_far_off_rejected():
    with pytest.raises(ValidationError, match="readingMinutes"):
        validate_article(load("bad_article_reading_time.json"))


def test_reading_time_within_tolerance_passes():
    article = load("good_article.json")
    article["readingMinutes"] = 9  # within ±3 of expected 8
    validate_article(article)


def test_dedupe_same_video_id_rejected():
    article = load("good_article.json")
    existing = [deepcopy(article)]
    article["slug"] = "different-slug-same-video"
    article["title"] = "What AGI Means: An Updated Take"
    with pytest.raises(ValidationError, match="already published"):
        validate_article(article, existing=existing)


def test_dedupe_similar_title_rejected():
    article = load("good_article.json")
    existing = [deepcopy(article)]
    article["slug"] = "different-slug-different-video"
    article["sourceVideo"]["id"] = "abcdefghijk"
    article["sourceVideo"]["url"] = "https://www.youtube.com/watch?v=abcdefghijk"
    article["content"] = article["content"].replace(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=abcdefghijk",
    )
    with pytest.raises(ValidationError, match="title too similar"):
        validate_article(article, existing=existing)


def test_dedupe_no_existing_passes():
    """Without an `existing` list, dedupe is a no-op — the validator should
    not reject an article just because it cannot check."""
    validate_article(load("good_article.json"), existing=None)


def test_dedupe_distinct_passes():
    article = load("good_article.json")
    existing = [{
        "title": "A completely unrelated article on database indexing",
        "sourceVideo": {"id": "zzzzzzzzzzz"},
    }]
    validate_article(article, existing=existing)


def test_orphan_reference_url_rejected():
    """A `references[]` entry whose URL doesn't appear in the body must fail.
    Stops the agent from stuffing references in metadata without citing them."""
    with pytest.raises(ValidationError, match="not cited in body"):
        validate_article(load("bad_article_orphan_reference.json"))


def test_missing_references_heading_rejected():
    """When `references[]` is non-empty, a `## References` H2 must exist."""
    with pytest.raises(ValidationError, match="no '## References' heading"):
        validate_article(load("bad_article_missing_references_heading.json"))


def test_transcript_only_article_passes():
    """An article with no `references` field (or empty list) must still pass —
    research is augmentation, not a hard requirement."""
    article = load("good_article.json")
    article["content"] = article["content"].replace(
        "\n\n## References\n\n- [OpenAI Charter](https://openai.com/charter) "
        "(accessed 2026-05-06)\n- [ARC-AGI Prize](https://arcprize.org/arc) "
        "(accessed 2026-05-06)",
        "",
    )
    article.pop("references", None)
    validate_article(article)


def test_empty_references_list_passes():
    article = load("good_article.json")
    article["content"] = article["content"].replace(
        "\n\n## References\n\n- [OpenAI Charter](https://openai.com/charter) "
        "(accessed 2026-05-06)\n- [ARC-AGI Prize](https://arcprize.org/arc) "
        "(accessed 2026-05-06)",
        "",
    )
    article["references"] = []
    validate_article(article)
