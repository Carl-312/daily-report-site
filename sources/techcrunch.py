"""
TechCrunch News Source
Fetches AI/tech news from techcrunch.com
"""
from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from typing import List

from .base import BaseSource, Article

# Beijing timezone
beijing_tz = timezone(timedelta(hours=8))


class TechCrunchSource(BaseSource):
    """TechCrunch News Source"""
    
    name = "techcrunch"
    BASE_URL = "https://techcrunch.com"
    
    def fetch(self, max_articles: int = 14) -> List[Article]:
        """Fetch recent tech news"""
        resp = self._get(self.BASE_URL)
        resp.raise_for_status()
        soup = self._parse_html(resp.content)
        
        articles = self._parse_articles(soup)
        
        # Filter to last 24-48 hours
        filtered = [a for a in articles if self._is_recent(a.publish_time)]
        
        return filtered[:max_articles]
    
    def _parse_articles(self, soup) -> List[Article]:
        """Parse article links from homepage"""
        selectors = [
            'h2 a', 'h3 a', 'h1 a',
            'article h2 a', 'article h3 a',
            '.post-block a', '.river-block a',
            'a[href*="/2025/"]', 'a[href*="/2026/"]',
        ]
        
        all_links = []
        for selector in selectors:
            try:
                elements = soup.select(selector)
                all_links.extend(elements)
            except Exception:
                continue
        
        # Deduplicate by URL
        seen_urls = set()
        articles = []
        
        for element in all_links:
            if element.name != 'a':
                continue
            
            title = element.get_text(strip=True)
            link = element.get('href', '')
            
            # Normalize link
            if link and not link.startswith('http'):
                link = self.BASE_URL + link if link.startswith('/') else f"{self.BASE_URL}/{link}"
            
            # Validate
            if (link in seen_urls or
                not title or len(title) < 10 or
                'techcrunch.com' not in link or
                not any(f'/{year}/' in link for year in ['2024', '2025', '2026'])):
                continue
            
            seen_urls.add(link)
            
            # Extract date from URL
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
        """Extract date from TechCrunch URL format"""
        match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
        if match:
            year, month, day = match.groups()
            return f"{year}-{month}-{day}"
        return ""
    
    def _is_recent(self, publish_time: str) -> bool:
        """Check if article is within last 48 hours"""
        if not publish_time or len(publish_time) != 10:
            return False
        
        try:
            pub_date = datetime.strptime(publish_time, "%Y-%m-%d")
            now = datetime.now(beijing_tz).replace(tzinfo=None)
            diff = now - pub_date
            return diff.days <= 1
        except Exception:
            return False
