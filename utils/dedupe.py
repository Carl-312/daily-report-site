"""
Deduplication utilities
Removes duplicate articles based on title + domain hash
"""
from __future__ import annotations
import re
import hashlib
from urllib.parse import urlparse
from typing import List

from sources.base import Article

_norm_re = re.compile(r"[\s\-—_]+")


def normalize_title(title: str) -> str:
    """Normalize title for comparison"""
    t = (title or '').strip().lower()
    return _norm_re.sub(' ', t)


def get_domain(url: str) -> str:
    """Extract domain from URL"""
    try:
        return urlparse(url).netloc
    except Exception:
        return ''


def article_key(article: Article | dict) -> str:
    """Generate unique key for article"""
    if isinstance(article, Article):
        title = article.title
        link = article.link
    else:
        title = article.get('title', '')
        link = article.get('link', '')
    
    base = f"{normalize_title(title)}|{get_domain(link)}"
    return hashlib.md5(base.encode('utf-8')).hexdigest()


def dedupe(articles: List[Article | dict]) -> List[Article | dict]:
    """
    Remove duplicate articles based on title + domain
    Higher priority articles are kept when duplicates are found
    """
    # Sort by priority (high first)
    def get_priority(a):
        if isinstance(a, Article):
            return a.priority
        return a.get('priority', 0)
    
    sorted_articles = sorted(articles, key=get_priority, reverse=True)
    
    seen = set()
    result = []
    
    for article in sorted_articles:
        key = article_key(article)
        if key in seen:
            continue
        seen.add(key)
        result.append(article)
    
    # Return sorted by priority
    return sorted(result, key=get_priority, reverse=True)
