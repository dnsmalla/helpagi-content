"""One-time migration: wrap helpagi-content/articles.json (currently a top-level
array) into the {articles: [...], version, lastUpdated} shape the iOS decoder
expects.

Idempotent: if the file is already wrapped, it leaves it alone.

Usage:
    cd helpagi-content
    python3 scripts/pipeline/bootstrap.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # helpagi-content/
ARTICLES = REPO_ROOT / "articles.json"


def main() -> int:
    if not ARTICLES.exists():
        print(f"ERROR: {ARTICLES} not found", file=sys.stderr)
        return 1

    data = json.loads(ARTICLES.read_text())

    if isinstance(data, dict) and "articles" in data:
        print(f"already wrapped — {len(data['articles'])} articles, no change")
        return 0

    if not isinstance(data, list):
        print(f"ERROR: unexpected top-level type {type(data).__name__}", file=sys.stderr)
        return 1

    today = dt.date.today().isoformat()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    wrapped = {
        "version": today,
        "lastUpdated": now,
        "articles": data,
    }
    ARTICLES.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2) + "\n")
    print(f"wrapped {len(data)} articles → {ARTICLES.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
