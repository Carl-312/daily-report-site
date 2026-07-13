"""
Sources Registry
Provides centralized access to all news sources
"""

from __future__ import annotations
from datetime import datetime
from time import perf_counter
from typing import Dict, Type, List

from .base import BaseSource, Article
from utils.run_contracts import (
    ArticleSnapshot,
    Diagnostic,
    RunDeadlineExceeded,
    SourceRunResult,
)
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


def fetch_batch(
    enabled_sources: Dict[str, bool],
    max_articles: int = 14,
    syft_url: str = "",
    syft_key: str = "",
    reference_dt: datetime | None = None,
    deadline_at: datetime | None = None,
) -> tuple[List[Article], tuple[SourceRunResult, ...]]:
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
    outcomes: list[SourceRunResult] = []

    for name, enabled in enabled_sources.items():
        if not enabled:
            continue
        if name not in REGISTRY:
            outcomes.append(
                SourceRunResult(
                    source=name,
                    status="failed",
                    attempts=0,
                    duration_ms=0,
                    fetched_count=0,
                    accepted_count=0,
                    error_kind="configuration",
                    error_message="unknown enabled source",
                )
            )
            continue

        started = perf_counter()
        try:
            # Special handling for Syft source
            if name == "syft":
                source = SyftSource(web_app_url=syft_url, secret_key=syft_key)
            else:
                source = REGISTRY[name]()

            articles = source.fetch(
                max_articles=max_articles,
                reference_dt=reference_dt,
                deadline_at=deadline_at,
            )
            all_articles.extend(articles)
            print(f"✅ {name}: fetched {len(articles)} articles")
            outcomes.append(
                SourceRunResult(
                    source=name,
                    status="ok" if articles else "empty",
                    attempts=source.last_attempts or 1,
                    duration_ms=round((perf_counter() - started) * 1000),
                    fetched_count=len(articles),
                    accepted_count=len(articles),
                    articles=tuple(
                        ArticleSnapshot(**article.to_dict()) for article in articles
                    ),
                )
            )

        except RunDeadlineExceeded:
            raise
        except Exception as e:
            print(f"❌ {name}: failed - {e}")
            error_kind = type(e).__name__
            outcomes.append(
                SourceRunResult(
                    source=name,
                    status="failed",
                    attempts=getattr(locals().get("source", None), "last_attempts", 0)
                    or 1,
                    duration_ms=round((perf_counter() - started) * 1000),
                    fetched_count=0,
                    accepted_count=0,
                    error_kind=error_kind,
                    error_message="source execution failed; inspect protected logs",
                    diagnostics=(
                        Diagnostic(
                            code="source_error",
                            message="source execution failed; inspect protected logs",
                        ),
                    ),
                )
            )

    return all_articles, tuple(outcomes)


def fetch_all(
    enabled_sources: Dict[str, bool],
    max_articles: int = 14,
    syft_url: str = "",
    syft_key: str = "",
    reference_dt: datetime | None = None,
    deadline_at: datetime | None = None,
) -> List[Article]:
    """Compatibility wrapper returning only the combined articles list."""
    articles, _ = fetch_batch(
        enabled_sources,
        max_articles=max_articles,
        syft_url=syft_url,
        syft_key=syft_key,
        reference_dt=reference_dt,
        deadline_at=deadline_at,
    )
    return articles


__all__ = [
    "BaseSource",
    "Article",
    "REGISTRY",
    "get_source",
    "fetch_all",
    "fetch_batch",
    "AIBaseSource",
    "TechCrunchSource",
    "TheVergeSource",
    "SyftSource",
]
