"""Tests for tools.validate_article.

The validator is the *only* hard gate between agent output and the published
articles.json. Every check that drops an article must be tested here so a
regression in the validator can't silently let bad content through.
"""
import json
from pathlib import Path

import pytest

from tools.validate_article import ValidationError, validate_article

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_good_article_passes():
    validate_article(load("good_article.json"))  # raises if invalid


def test_short_content_rejected():
    with pytest.raises(ValidationError, match="content too short"):
        validate_article(load("bad_article_short.json"))


def test_missing_attribution_rejected():
    with pytest.raises(ValidationError, match="attribution missing"):
        validate_article(load("bad_article_no_attribution.json"))


def test_repeated_paragraphs_rejected():
    with pytest.raises(ValidationError, match="duplicate paragraphs"):
        validate_article(load("bad_article_repeated.json"))


def test_schema_violation_rejected():
    bad = load("good_article.json")
    bad["category"] = "Cooking"  # not in enum
    with pytest.raises(ValidationError, match="schema"):
        validate_article(bad)


def test_off_topic_rejected():
    bad = load("good_article.json")
    bad["title"] = "How to bake sourdough at home"
    bad["content"] = bad["content"].replace("AGI", "sourdough").replace("AI", "yeast")
    with pytest.raises(ValidationError, match="off-topic"):
        validate_article(bad)
