"""
Syft Email Digest Source
Fetches curated AI news from Syft newsletter via Google Apps Script
"""
from __future__ import annotations
import json
from typing import List
from datetime import datetime, timezone, timedelta

from .base import BaseSource, Article

beijing_tz = timezone(timedelta(hours=8))


class SyftSource(BaseSource):
    """Syft Email Digest Source"""
    
    name = "syft"
    
    def __init__(self, web_app_url: str = "", secret_key: str = ""):
        super().__init__()
        self.web_app_url = web_app_url
        self.secret_key = secret_key
    
    def fetch(self, max_articles: int = 14) -> List[Article]:
        """Fetch news from Syft email digest API"""
        if not self.web_app_url or not self.secret_key:
            return []
        
        try:
            today = datetime.now(beijing_tz).strftime("%Y-%m-%d")
            
            resp = self.session.get(
                self.web_app_url,
                params={
                    "secret": self.secret_key,
                    "date": today,
                },
                headers=self.HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            
            data = resp.json()
            if not data.get("success"):
                return []
            
            articles = []
            for item in data.get("articles", [])[:max_articles]:
                articles.append(Article(
                    title=item.get("title", ""),
                    link=item.get("link", ""),
                    description=item.get("description", ""),
                    publish_time=item.get("date", today),
                    priority=1,
                    source=self.name,
                ))
            
            return articles
            
        except Exception:
            return []
