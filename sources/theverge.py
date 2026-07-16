"""
The Verge AI news source.

The public AI page no longer embeds publication dates in article URLs. Its
official Atom feed is the stable machine-readable source for canonical links,
summaries, and timezone-aware publication timestamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
import re
from typing import List
from urllib.parse import urlparse
from xml.etree import ElementTree

from .base import Article, BaseSource


beijing_tz = timezone(timedelta(hours=8))
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
ATOM = f"{{{ATOM_NAMESPACE}}}"


class TheVergeSource(BaseSource):
    """Fetch recent articles from The Verge's official AI Atom feed."""

    name = "theverge"
    BASE_URL = "https://www.theverge.com"
    AI_URL = f"{BASE_URL}/ai-artificial-intelligence"
    FEED_URL = f"{BASE_URL}/rss/ai-artificial-intelligence/index.xml"
    MAX_AGE = timedelta(hours=48)
    FUTURE_TOLERANCE = timedelta(minutes=5)

    def fetch(
        self,
        max_articles: int = 14,
        reference_dt: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> List[Article]:
        """Fetch recent AI articles with authoritative publication timestamps."""
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
        """Parse canonical article metadata from The Verge's Atom feed."""
        root = ElementTree.fromstring(content)
        seen_urls: set[str] = set()
        articles: list[Article] = []

        for entry in root.findall(f"{ATOM}entry"):
            title = self._clean_fragment(entry.findtext(f"{ATOM}title") or "")
            publish_time = (entry.findtext(f"{ATOM}published") or "").strip()
            link = self._entry_link(entry)

            if (
                not title
                or len(title) < 10
                or not publish_time
                or not self._parse_published_datetime(publish_time)
                or not self._is_theverge_article(link)
                or link in seen_urls
            ):
                continue

            seen_urls.add(link)
            description = self._clean_fragment(
                entry.findtext(f"{ATOM}summary") or ""
            )
            articles.append(
                Article(
                    title=title[:200],
                    link=link,
                    description=description,
                    publish_time=publish_time,
                    priority=1,
                    source=self.name,
                )
            )

        return articles

    @staticmethod
    def _entry_link(entry: ElementTree.Element) -> str:
        for link in entry.findall(f"{ATOM}link"):
            if link.get("rel", "alternate") == "alternate":
                return (link.get("href") or "").strip()
        return ""

    @staticmethod
    def _clean_fragment(value: str) -> str:
        """Convert an Atom HTML fragment into compact reader-facing text."""
        from bs4 import BeautifulSoup

        text = BeautifulSoup(unescape(value), "html.parser").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_theverge_article(link: str) -> bool:
        try:
            parsed = urlparse(link)
        except ValueError:
            return False
        return (
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() in {"theverge.com", "www.theverge.com"}
            and parsed.path not in {"", "/"}
        )

    @staticmethod
    def _parse_published_datetime(value: str) -> datetime | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=beijing_tz)
        return parsed

    def _is_recent(
        self, publish_time: str, reference_dt: datetime | None = None
    ) -> bool:
        """Return whether a publication falls inside the rolling 48-hour window."""
        published = self._parse_published_datetime(publish_time)
        if published is None:
            return False

        reference = reference_dt or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=beijing_tz)

        age = reference.astimezone(timezone.utc) - published.astimezone(timezone.utc)
        return -self.FUTURE_TOLERANCE <= age <= self.MAX_AGE

    @staticmethod
    def _extract_date_from_url(url: str) -> str:
        """Retain compatibility with callers that inspect legacy dated URLs."""
        match = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
        if not match:
            return ""
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
