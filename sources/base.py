"""
Base class for news sources
All sources should inherit from this class
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import random
import time
from typing import Any, List
import requests
from requests.utils import get_environ_proxies


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
    provenance: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "publish_time": self.publish_time,
            "content": self.content,
            "priority": self.priority,
            "source": self.source,
            "provenance": dict(self.provenance),
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
        # Source-specific adapters can expose richer, additive run facts.  The
        # registry falls back to the returned Article count for legacy sources.
        self.last_fetched_count: int | None = None
        self.last_accepted_count: int | None = None
        self.last_status: str | None = None
        self.last_diagnostics: tuple[Any, ...] = ()

    @abstractmethod
    def fetch(
        self,
        max_articles: int = 14,
        reference_dt: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> List[Article]:
        """Fetch articles from source. Must be implemented by subclasses."""
        pass

    def _get(
        self,
        url: str,
        timeout: int = 15,
        *,
        max_attempts: int = 3,
        deadline_at: datetime | None = None,
        use_environment_proxy: bool = False,
        sleep=time.sleep,
        random_value=random.random,
    ) -> requests.Response:
        """Make a bounded retryable GET without retrying configuration 4xx errors."""
        from utils.run_contracts import RunDeadlineExceeded

        last_error: requests.RequestException | None = None
        for attempt in range(1, max_attempts + 1):
            self.last_attempts = attempt
            request_timeout = self._bounded_timeout(
                timeout, deadline_at, "source fetch"
            )
            try:
                proxies = (
                    get_environ_proxies(url) if use_environment_proxy else {}
                )
                response = self.session.get(
                    url,
                    headers=self.HEADERS,
                    timeout=request_timeout,
                    proxies=proxies,
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
                delay = (2 ** (attempt - 1)) * 0.1 + random_value() * 0.05
                if deadline_at is not None:
                    remaining = (
                        deadline_at - datetime.now(deadline_at.tzinfo)
                    ).total_seconds()
                    if remaining <= delay:
                        raise RunDeadlineExceeded(
                            "run deadline exceeded during source retry backoff"
                        ) from exc
                sleep(delay)
        raise last_error or RuntimeError("unreachable retry loop")

    @staticmethod
    def _bounded_timeout(
        timeout: float,
        deadline_at: datetime | None,
        stage: str,
    ) -> float:
        from utils.run_contracts import RunDeadlineExceeded

        if deadline_at is None:
            return timeout
        remaining = (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds()
        if remaining <= 0:
            raise RunDeadlineExceeded(f"run deadline exceeded during {stage}")
        return min(float(timeout), remaining)

    def _parse_html(self, content: bytes):
        """Parse HTML content using BeautifulSoup"""
        from bs4 import BeautifulSoup

        return BeautifulSoup(content, "html.parser")
