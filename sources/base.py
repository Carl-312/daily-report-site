"""
Base class for news sources
All sources should inherit from this class
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
    
    @abstractmethod
    def fetch(self, max_articles: int = 14) -> List[Article]:
        """Fetch articles from source. Must be implemented by subclasses."""
        pass
    
    def _get(self, url: str, timeout: int = 15) -> requests.Response:
        """Make HTTP GET request with standard headers"""
        return self.session.get(
            url,
            headers=self.HEADERS,
            timeout=timeout,
            proxies={}
        )
    
    def _parse_html(self, content: bytes):
        """Parse HTML content using BeautifulSoup"""
        from bs4 import BeautifulSoup
        return BeautifulSoup(content, 'html.parser')
