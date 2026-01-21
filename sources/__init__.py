"""
Sources Registry
Provides centralized access to all news sources
"""
from __future__ import annotations
from typing import Dict, Type, List

from .base import BaseSource, Article
from .aibase import AIBaseSource
from .techcrunch import TechCrunchSource
from .theverge import TheVergeSource
from .syft import SyftSource

# Registry of available sources
REGISTRY: Dict[str, Type[BaseSource]] = {
    "aibase": AIBaseSource,
    "techcrunch": TechCrunchSource,
    "theverge": TheVergeSource,
    "syft": SyftSource,
}


def get_source(name: str, **kwargs) -> BaseSource | None:
    """Get source instance by name"""
    source_class = REGISTRY.get(name)
    if source_class:
        return source_class(**kwargs)
    return None


def fetch_all(
    enabled_sources: Dict[str, bool],
    max_articles: int = 14,
    syft_url: str = "",
    syft_key: str = "",
) -> List[Article]:
    """
    Fetch articles from all enabled sources
    
    Args:
        enabled_sources: Dict mapping source name to enabled status
        max_articles: Max articles per source
        syft_url: Syft API URL (for syft source)
        syft_key: Syft API key (for syft source)
    
    Returns:
        Combined list of articles from all sources
    """
    all_articles: List[Article] = []
    
    for name, enabled in enabled_sources.items():
        if not enabled or name not in REGISTRY:
            continue
        
        try:
            # Special handling for Syft source
            if name == "syft":
                source = SyftSource(web_app_url=syft_url, secret_key=syft_key)
            else:
                source = REGISTRY[name]()
            
            articles = source.fetch(max_articles=max_articles)
            all_articles.extend(articles)
            print(f"✅ {name}: fetched {len(articles)} articles")
            
        except Exception as e:
            print(f"❌ {name}: failed - {e}")
    
    return all_articles


__all__ = [
    "BaseSource",
    "Article",
    "REGISTRY",
    "get_source",
    "fetch_all",
    "AIBaseSource",
    "TechCrunchSource",
    "TheVergeSource",
    "SyftSource",
]
