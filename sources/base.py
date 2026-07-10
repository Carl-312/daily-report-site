"""
Base class for news sources
All sources should inherit from this class
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import random
import time
from typing import List
import requests


@dataclass
class Article:
    """Standard article structure"""

    title: str
    link: str
    description: str = ""
    publish_time: str = ""
    content: str = ""
    priority: int = 0
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "publish_time": self.publish_time,
            "content": self.content,
            "priority": self.priority,
            "source": self.source,
        }


class BaseSource(ABC):
    """Base class for all news sources"""

    name: str = "base"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.last_attempts = 0

    @abstractmethod
    def fetch(
        self, max_articles: int = 14, reference_dt: datetime | None = None
    ) -> List[Article]:
        """Fetch articles from source. Must be implemented by subclasses."""
        pass

    def _get(
        self,
        url: str,
        timeout: int = 15,
        *,
        max_attempts: int = 3,
        sleep=time.sleep,
        random_value=random.random,
    ) -> requests.Response:
        """Make a bounded retryable GET without retrying configuration 4xx errors."""
        last_error: requests.RequestException | None = None
        for attempt in range(1, max_attempts + 1):
            self.last_attempts = attempt
            try:
                response = self.session.get(
                    url, headers=self.HEADERS, timeout=timeout, proxies={}
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                retryable = status is None or status == 429 or status >= 500
                if not retryable or attempt == max_attempts:
                    raise
                sleep((2 ** (attempt - 1)) * 0.1 + random_value() * 0.05)
        raise last_error or RuntimeError("unreachable retry loop")

    def _parse_html(self, content: bytes):
        """Parse HTML content using BeautifulSoup"""
        from bs4 import BeautifulSoup

        return BeautifulSoup(content, "html.parser")
