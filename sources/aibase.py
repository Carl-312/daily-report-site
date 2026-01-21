"""
AIBase Daily News Source
Fetches AI daily digest from news.aibase.com
"""
from __future__ import annotations
import re
from datetime import datetime
from urllib.parse import urljoin
from typing import List

from .base import BaseSource, Article

# Timezone handling
try:
    import pytz
    beijing_tz = pytz.timezone("Asia/Shanghai")
except ImportError:
    from datetime import timezone, timedelta
    beijing_tz = timezone(timedelta(hours=8))


class AIBaseSource(BaseSource):
    """AIBase Daily News Source"""
    
    name = "aibase"
    BASE_URL = "https://news.aibase.com"
    DAILY_URL = "https://news.aibase.com/zh/daily"
    
    def fetch(self, max_articles: int = 14) -> List[Article]:
        """Fetch today's AI daily digest"""
        today_beijing = datetime.now(beijing_tz).date()
        
        # Get daily page
        resp = self._get(self.DAILY_URL)
        resp.raise_for_status()
        soup = self._parse_html(resp.content)
        
        # Find latest article link
        link = self._find_latest_link(soup)
        if not link:
            return []
        
        # Extract article detail
        article = self._extract_detail(link)
        if not article:
            return []
        
        # Check if article is from today
        is_today = self._is_today(article, today_beijing)
        if not is_today:
            return []
        
        article.priority = 1
        article.source = self.name
        return [article]
    
    def _find_latest_link(self, soup) -> str | None:
        """Find the latest daily article link"""
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith('#'):
                continue
            full_url = urljoin(self.BASE_URL, href)
            if any(p in full_url for p in ["/daily/", "/article/", "/news/", "/post/"]):
                candidates.append({
                    "url": full_url,
                    "text": a.get_text(' ', strip=True)
                })
        
        if not candidates:
            return None
        
        # Score and sort candidates
        def score(c):
            s = 0
            if re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", c["url"]):
                s += 10
            if "/daily/" in c["url"]:
                s += 5
            if 10 <= len(c["text"]) <= 100:
                s += 3
            s += len(c["url"]) / 1000.0
            return s
        
        candidates.sort(key=score, reverse=True)
        return candidates[0]["url"]
    
    def _extract_detail(self, link: str) -> Article | None:
        """Extract article details from page"""
        try:
            resp = self._get(link)
            resp.raise_for_status()
            soup = self._parse_html(resp.content)
            
            title = self._pick_text(soup, [
                "h1", "h1.entry-title", ".post-title",
                ".article-title", ".title", "header h1"
            ]) or "未找到标题"
            
            description = self._extract_summary(soup) or "无描述"
            publish_time = self._extract_time(soup) or "未知时间"
            content = self._extract_full_text(soup)
            
            return Article(
                title=title,
                link=link,
                description=description,
                publish_time=publish_time,
                content=content,
            )
        except Exception:
            return None
    
    def _pick_text(self, soup, selectors: list) -> str:
        """Pick text from first matching selector"""
        for sel in selectors:
            for el in soup.select(sel):
                text = el.get_text(' ', strip=True)
                if text and len(text) > 4:
                    return text
        return soup.title.get_text(' ', strip=True) if soup.title else ''
    
    def _extract_time(self, soup) -> str:
        """Extract publish time from page"""
        selectors = [
            "time[datetime]", "time",
            "meta[property='article:published_time']",
            "meta[name='pubdate']",
            ".post-meta time", ".article-meta time", ".date",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if not el:
                continue
            if el.name == 'time':
                dt = el.get('datetime') or el.get_text(' ', strip=True)
                if dt:
                    return dt.strip()
            if el.name == 'meta':
                c = el.get('content')
                if c:
                    return c.strip()
            text = el.get_text(' ', strip=True)
            if text:
                return text.strip()
        return ''
    
    def _extract_summary(self, soup, max_chars: int = 400) -> str:
        """Extract article summary"""
        areas = []
        for sel in ["article", ".post-content", ".article-content",
                    ".content", "#content", ".entry-content", "main"]:
            el = soup.select_one(sel)
            if el:
                areas.append(el)
        
        if not areas:
            areas = [soup]
        
        texts = []
        for area in areas:
            for p in area.find_all(["p", "li"])[:20]:
                t = p.get_text(' ', strip=True)
                if t and len(t) > 20:
                    texts.append(t)
                if sum(len(x) for x in texts) >= max_chars:
                    break
            if texts:
                break
        
        if not texts:
            return ''
        
        summary = ' '.join(texts)
        return (summary[:max_chars-1] + '…') if len(summary) > max_chars else summary
    
    def _extract_full_text(self, soup) -> str:
        """Extract full article text"""
        area = soup.select_one(
            "article, .post-content, .article-content, .content, "
            "#content, .entry-content, main, #main, [role='main']"
        )
        if area:
            text = area.get_text('\n', strip=True)
        else:
            for tag in soup(["script", "style", "noscript"]):
                tag.extract()
            text = soup.get_text('\n', strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)
    
    def _is_today(self, article: Article, today) -> bool:
        """Check if article is from today (Beijing time)"""
        content = article.content
        
        # Try to find date in content (format: 2025年11月8号)
        date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})号', content)
        if date_match:
            year, month, day = map(int, date_match.groups())
            if datetime(year, month, day).date() == today:
                return True
        
        # Try to parse publish_time
        publish_time = article.publish_time
        if publish_time and publish_time != "未知时间":
            date_str = re.sub(r'\s*\+\d{2}:\d{2}|\s*Z|\s*UTC.*', '', publish_time)
            for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y年%m月%d日']:
                try:
                    if datetime.strptime(date_str[:10], fmt).date() == today:
                        return True
                except ValueError:
                    continue
        
        return False
