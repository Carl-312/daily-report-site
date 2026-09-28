"""TechCrunch artificial-intelligence RSS source."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from typing import List
from urllib.parse import urlparse
from xml.etree import ElementTree

from .base import Article, BaseSource


class TechCrunchSource(BaseSource):
    """Fetch publishable stories from TechCrunch's official AI RSS feed."""

    name = "techcrunch"
    BASE_URL = "https://techcrunch.com"
    FEED_URL = f"{BASE_URL}/category/artificial-intelligence/feed/"
    MAX_AGE = timedelta(hours=48)
    FUTURE_TOLERANCE = timedelta(minutes=5)

    def fetch(
        self,
        max_articles: int = 14,
        reference_dt: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> List[Article]:
        """Fetch recent AI stories with direct evidence text and publication time."""

        response = self._get(
            self.FEED_URL,
            deadline_at=deadline_at,
            use_environment_proxy=True,
        )
        response.raise_for_status()

        candidates = self._parse_feed(response.content)
        self.last_fetched_count = len(candidates)
        accepted = [
            article
            for article in candidates
            if self._is_recent(article.publish_time, reference_dt=reference_dt)
        ][: max(0, max_articles)]
        self.last_accepted_count = len(accepted)
        self.last_status = "ok" if accepted else "empty"
        return accepted

    def _parse_feed(self, content: bytes) -> List[Article]:
        root = ElementTree.fromstring(content)
        seen_urls: set[str] = set()
        articles: list[Article] = []

        for item in root.findall("./channel/item"):
            title = self._clean_fragment(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()
            publish_time = (item.findtext("pubDate") or "").strip()
            description = self._clean_fragment(item.findtext("description") or "")
            if (
                len(title) < 10
                or not description
                or not self._is_techcrunch_article(link)
                or self._parse_published_datetime(publish_time) is None
                or link in seen_urls
            ):
                continue

            seen_urls.add(link)
            articles.append(
                Article(
                    title=title[:200],
                    link=link,
                    description=description[:1200],
                    publish_time=publish_time,
                    content=description[:2400],
                    priority=1,
                    source=self.name,
                    provenance={
                        "input_kind": "story",
                        "retrieval": "official_ai_rss",
                        "publish_time_semantics": "source_published_at",
                    },
                )
            )

        return articles

    @staticmethod
    def _clean_fragment(value: str) -> str:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(unescape(value), "html.parser").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_techcrunch_article(link: str) -> bool:
        try:
            parsed = urlparse(link)
        except ValueError:
            return False
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() in {"techcrunch.com", "www.techcrunch.com"}
            and parsed.path not in {"", "/"}
        )

    @staticmethod
    def _parse_published_datetime(value: str) -> datetime | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _is_recent(
        self,
        publish_time: str,
        reference_dt: datetime | None = None,
    ) -> bool:
        published = self._parse_published_datetime(publish_time)
        if published is None:
            return False
        reference = reference_dt or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age = reference.astimezone(timezone.utc) - published.astimezone(timezone.utc)
        return -self.FUTURE_TOLERANCE <= age <= self.MAX_AGE
