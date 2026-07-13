"""
Deduplication utilities
Removes duplicate articles based on canonical URL and obvious story-title rewrites.
"""

from __future__ import annotations
from difflib import SequenceMatcher
import hashlib
from urllib.parse import urlparse
from typing import List

from article_identity import canonical_url, normalize_title
from sources.base import Article


def get_domain(url: str) -> str:
    """Extract domain from URL"""
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def article_key(article: Article | dict) -> str:
    """Generate unique key for article"""
    if isinstance(article, Article):
        title = article.title
        link = article.link
    else:
        title = article.get("title", "")
        link = article.get("link", "")

    normalized_url = canonical_url(link)
    base = normalized_url or normalize_title(title)
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def _same_story(left_title: str, right_title: str) -> bool:
    """Catch only obvious cross-source title rewrites."""
    left = normalize_title(left_title)
    right = normalize_title(right_title)
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) < 18:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.9


def dedupe(articles: List[Article | dict]) -> List[Article | dict]:
    """
    Remove duplicate articles based on canonical URL and obvious title rewrites.
    Higher priority articles are kept when duplicates are found
    """

    # Sort by priority (high first)
    def get_priority(a):
        if isinstance(a, Article):
            return a.priority
        return a.get("priority", 0)

    sorted_articles = sorted(articles, key=get_priority, reverse=True)

    seen = set()
    seen_titles: list[str] = []
    result = []

    for article in sorted_articles:
        key = article_key(article)
        if key in seen:
            continue
        title = (
            article.title if isinstance(article, Article) else article.get("title", "")
        )
        if any(_same_story(title, seen_title) for seen_title in seen_titles):
            continue
        seen.add(key)
        seen_titles.append(title)
        result.append(article)

    # Return sorted by priority
    return sorted(result, key=get_priority, reverse=True)
