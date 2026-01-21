"""
The Verge AI News Source
Fetches AI news from theverge.com/ai-artificial-intelligence
"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from typing import List

from .base import BaseSource, Article

beijing_tz = timezone(timedelta(hours=8))


class TheVergeSource(BaseSource):
    """The Verge AI News Source"""
    
    name = "theverge"
    BASE_URL = "https://www.theverge.com"
    AI_URL = "https://www.theverge.com/ai-artificial-intelligence"
    
    def fetch(self, max_articles: int = 14) -> List[Article]:
        """Fetch AI news from The Verge"""
        resp = self._get(self.AI_URL)
        resp.raise_for_status()
        soup = self._parse_html(resp.content)
        
        articles = self._parse_articles(soup)
        filtered = [a for a in articles if self._is_recent(a.publish_time)]
        
        return filtered[:max_articles]
    
    def _parse_articles(self, soup) -> List[Article]:
        """Parse article links from AI section"""
        selectors = [
            'h2 a', 'h3 a',
            '.duet--content-cards--content-card a',
            'a[href*="/2025/"]', 'a[href*="/2026/"]',
        ]
        
        all_links = []
        for selector in selectors:
            try:
                elements = soup.select(selector)
                all_links.extend(elements)
            except Exception:
                continue
        
        seen_urls = set()
        articles = []
        
        for element in all_links:
            if element.name != 'a':
                continue
            
            title = element.get_text(strip=True)
            link = element.get('href', '')
            
            if link and not link.startswith('http'):
                link = self.BASE_URL + link if link.startswith('/') else f"{self.BASE_URL}/{link}"
            
            if (link in seen_urls or
                not title or len(title) < 10 or
                'theverge.com' not in link):
                continue
            
            seen_urls.add(link)
            publish_time = self._extract_date_from_url(link)
            
            articles.append(Article(
                title=title[:150],
                link=link,
                description="",
                publish_time=publish_time,
                priority=1 if self._is_recent(publish_time) else 0,
                source=self.name,
            ))
        
        return articles
    
    def _extract_date_from_url(self, url: str) -> str:
        """Extract date from The Verge URL format"""
        match = re.search(r'/(\d{4})/(\d{1,2})/(\d{1,2})/', url)
        if match:
            year, month, day = match.groups()
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        return ""
    
    def _is_recent(self, publish_time: str) -> bool:
        """Check if article is within last 48 hours"""
        if not publish_time:
            return False
        try:
            pub_date = datetime.strptime(publish_time, "%Y-%m-%d")
            now = datetime.now(beijing_tz).replace(tzinfo=None)
            return (now - pub_date).days <= 1
        except Exception:
            return False
