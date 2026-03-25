# 扩展新闻源教程

学习如何为 Daily Report Site 添加自定义新闻源。

---

## 🎯 学习目标

完成本教程后，你将能够:
- ✅ 理解新闻源接口规范
- ✅ 创建自定义新闻源模块
- ✅ 注册并启用新闻源
- ✅ 测试和调试新闻源

---

## 📋 前置知识

- Python 基础语法
- HTTP 请求 (`requests` 库)
- HTML 解析 (`BeautifulSoup`)

---

## 🚀 快速开始: 添加 Hacker News

### 第一步: 创建模块文件

在 `sources/` 目录创建 `hackernews.py`:

```python
"""
Hacker News Source Scraper
"""
import requests
from typing import List, Dict


def fetch() -> List[Dict[str, str]]:
    """
    从 Hacker News 获取头条新闻
    
    Returns:
        文章列表
    """
    articles = []
    
    # 1. 获取头条 ID 列表
    response = requests.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        timeout=10
    )
    response.raise_for_status()
    story_ids = response.json()[:10]  # 仅取前 10 条
    
    # 2. 获取每条新闻详情
    for story_id in story_ids:
        try:
            story_resp = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=5
            )
            story_resp.raise_for_status()
            story = story_resp.json()
            
            # 3. 格式化为标准格式
            articles.append({
                "title": story.get("title", "Untitled"),
                "link": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                "desc": story.get("text", "No description available")[:200],
            })
        except Exception as e:
            print(f"   ⚠️  Failed to fetch story {story_id}: {e}")
            continue
    
    return articles
```

### 第二步: 注册新闻源

编辑 `sources/__init__.py`，添加注册:

```python
# sources/__init__.py
from .aibase import fetch as fetch_aibase
from .techcrunch import fetch as fetch_techcrunch
from .theverge import fetch as fetch_theverge
from .hackernews import fetch as fetch_hackernews  # 新增

SOURCE_REGISTRY = {
    "aibase": fetch_aibase,
    "techcrunch": fetch_techcrunch,
    "theverge": fetch_theverge,
    "hackernews": fetch_hackernews,  # 新增
}
```

### 第三步: 启用新闻源

编辑 `config.yaml`:

```yaml
sources:
  aibase: true
  techcrunch: true
  theverge: true
  hackernews: true  # 启用
```

### 第四步: 测试

```bash
# 完整测试
python main.py run --offline

# 仅测试抓取
python main.py fetch
```

**查看输出**:
```
📡 Fetching news...
   AIBase: 8 articles
   TechCrunch: 5 articles
   The Verge: 6 articles
   HackerNews: 10 articles  # 新增
```

---

## 📚 进阶示例

### 示例 1: RSS Feed 新闻源 (Ars Technica)

```python
# sources/arstechnica.py
"""
Ars Technica RSS Feed Scraper
"""
import feedparser
from typing import List, Dict


def fetch() -> List[Dict[str, str]]:
    """从 Ars Technica RSS 获取新闻"""
    feed_url = "https://feeds.arstechnica.com/arstechnica/index"
    
    feed = feedparser.parse(feed_url)
    articles = []
    
    for entry in feed.entries[:15]:  # 限制 15 条
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "desc": entry.get("summary", "")[:300],
        })
    
    return articles
```

**依赖**: 需要安装 `feedparser`

```bash
pip install feedparser
# 更新 requirements.txt
pip freeze | grep feedparser >> requirements.txt
```

### 示例 2: 需要认证的 API

```python
# sources/newsapi.py
"""
NewsAPI.org Integration
"""
import os
import requests
from typing import List, Dict


def fetch() -> List[Dict[str, str]]:
    """从 NewsAPI 获取科技新闻"""
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        print("   ⚠️  NEWSAPI_KEY not configured, skipping")
        return []
    
    response = requests.get(
        "https://newsapi.org/v2/top-headlines",
        params={
            "category": "technology",
            "language": "en",
            "apiKey": api_key,
            "pageSize": 20,
        },
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    
    articles = []
    for article in data.get("articles", []):
        articles.append({
            "title": article["title"],
            "link": article["url"],
            "desc": article.get("description", "")[:300],
        })
    
    return articles
```

**配置**:

```bash
# .env
NEWSAPI_KEY=your-newsapi-key
```

### 示例 3: HTML 解析 (使用 BeautifulSoup)

```python
# sources/producthunt.py
"""
Product Hunt Scraper
"""
import requests
from bs4 import BeautifulSoup
from typing import List, Dict


def fetch() -> List[Dict[str, str]]:
    """从 Product Hunt 获取热门产品"""
    url = "https://www.producthunt.com/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    articles = []
    
    # 查找产品卡片 (根据实际 HTML 结构调整)
    products = soup.find_all("div", class_="product-card", limit=10)
    
    for product in products:
        title_elem = product.find("h3")
        link_elem = product.find("a")
        desc_elem = product.find("p", class_="tagline")
        
        if title_elem and link_elem:
            articles.append({
                "title": title_elem.get_text(strip=True),
                "link": "https://www.producthunt.com" + link_elem["href"],
                "desc": desc_elem.get_text(strip=True) if desc_elem else "",
            })
    
    return articles
```

---

## 🔧 接口规范详解

### 必需接口

```python
def fetch() -> List[Dict[str, str]]:
    """
    从新闻源获取文章
    
    Returns:
        文章列表，每个文章为字典，包含:
        - title (str): 文章标题 (必需)
        - link (str): 完整 URL (必需)
        - desc (str): 简短描述 (必需，建议 50-200 字)
    
    Raises:
        requests.RequestException: 网络请求失败
        ValueError: 数据格式错误
    """
```

### 返回格式示例

```python
[
    {
        "title": "OpenAI 发布 GPT-5",
        "link": "https://example.com/article-1",
        "desc": "OpenAI 今日宣布推出 GPT-5 预览版，性能提升 50%..."
    },
    {
        "title": "Startup X 完成 B 轮融资",
        "link": "https://example.com/article-2",
        "desc": "AI 初创公司 Startup X 宣布完成 5000 万美元 B 轮融资..."
    }
]
```

### 错误处理

```python
def fetch() -> List[Dict[str, str]]:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        # ...
    except requests.RequestException as e:
        print(f"   ❌ Failed to fetch from {source_name}: {e}")
        return []  # 返回空列表，不中断整个流程
    except Exception as e:
        print(f"   ⚠️  Unexpected error: {e}")
        return []
```

---

## 🧪 测试和调试

### 单元测试

创建 `tests/test_sources.py`:

```python
import pytest
from sources.hackernews import fetch


def test_hackernews_fetch():
    """测试 Hacker News 抓取"""
    articles = fetch()
    
    # 基本验证
    assert isinstance(articles, list)
    assert len(articles) > 0
    
    # 验证数据结构
    for article in articles:
        assert "title" in article
        assert "link" in article
        assert "desc" in article
        assert article["link"].startswith("http")


def test_hackernews_fetch_with_mock(monkeypatch):
    """使用 Mock 数据测试"""
    class MockResponse:
        @staticmethod
        def json():
            return [1, 2, 3]  # Mock story IDs
        
        @staticmethod
        def raise_for_status():
            pass
    
    def mock_get(*args, **kwargs):
        return MockResponse()
    
    monkeypatch.setattr("requests.get", mock_get)
    
    articles = fetch()
    assert len(articles) == 3
```

**运行测试**:

```bash
pip install -r requirements-dev.txt
pytest -v
```

### 手动测试

创建 `test_single_source.py`:

```python
#!/usr/bin/env python
"""快速测试单个新闻源"""
import sys
from sources.hackernews import fetch


def main():
    print("Testing Hacker News source...")
    articles = fetch()
    
    print(f"\n✅ Fetched {len(articles)} articles\n")
    
    for i, article in enumerate(articles[:5], 1):
        print(f"{i}. {article['title']}")
        print(f"   Link: {article['link']}")
        print(f"   Desc: {article['desc'][:80]}...")
        print()


if __name__ == "__main__":
    main()
```

**运行**:

```bash
python test_single_source.py
```

---

## 🛠️ 常见问题

### Q1: 抓取的数据为空

**可能原因**:
1. 网站结构变化 (HTML 解析失效)
2. API 访问限制
3. 网络问题

**调试方法**:

```python
# 添加详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

response = requests.get(url)
print("Status Code:", response.status_code)
print("Content:", response.text[:500])  # 打印前 500 字符
```

### Q2: 标题或描述过长

**解决**: 在返回前截断

```python
def fetch():
    # ...
    articles.append({
        "title": title[:150],  # 限制 150 字符
        "desc": desc[:300],    # 限制 300 字符
    })
```

### Q3: 特殊字符导致编码错误

**解决**: 确保正确处理编码

```python
response = requests.get(url)
response.encoding = "utf-8"  # 强制 UTF-8
text = response.text
```

### Q4: 请求被封禁 (403/429)

**解决**: 添加 User-Agent 和延迟

```python
headers = {
    "User-Agent": "Mozilla/5.0 (compatible; DailyReport/1.0)"
}
response = requests.get(url, headers=headers, timeout=10)

# 添加延迟 (避免频繁请求)
import time
time.sleep(1)
```

---

## 🎨 最佳实践

### 1. 使用缓存 (可选)

```python
import functools
import time

@functools.lru_cache(maxsize=1)
def fetch_cached():
    """带缓存的抓取 (5 分钟有效)"""
    # 实际抓取逻辑
    return fetch()

def fetch():
    # 检查缓存时间
    current_time = time.time()
    # ... (缓存逻辑)
    return fetch_cached()
```

### 2. 限流器

```python
import time
from threading import Lock

class RateLimiter:
    def __init__(self, calls_per_second=1):
        self.calls_per_second = calls_per_second
        self.lock = Lock()
        self.last_call = 0
    
    def wait(self):
        with self.lock:
            elapsed = time.time() - self.last_call
            wait_time = (1.0 / self.calls_per_second) - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self.last_call = time.time()

limiter = RateLimiter(calls_per_second=2)

def fetch():
    limiter.wait()
    # 实际请求
```

### 3. 结构化日志

```python
import logging

logger = logging.getLogger(__name__)

def fetch():
    logger.info("Starting fetch from Hacker News")
    try:
        # ...
        logger.info(f"Successfully fetched {len(articles)} articles")
        return articles
    except Exception as e:
        logger.error(f"Failed to fetch: {e}", exc_info=True)
        return []
```

---

## 📦 完整示例: Reddit Subreddit

```python
# sources/reddit.py
"""
Reddit Subreddit Scraper (using PRAW library)
"""
import os
import praw
from typing import List, Dict


def fetch() -> List[Dict[str, str]]:
    """从 r/technology 获取热门帖子"""
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("   ⚠️  Reddit credentials not configured")
        return []
    
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="DailyReport/1.0"
    )
    
    subreddit = reddit.subreddit("technology")
    articles = []
    
    for post in subreddit.hot(limit=15):
        if post.is_self:  # 跳过自助贴
            continue
        
        articles.append({
            "title": post.title,
            "link": post.url,
            "desc": post.selftext[:200] if post.selftext else f"{post.score} upvotes",
        })
    
    return articles
```

**安装依赖**:

```bash
pip install praw
```

**配置** (`.env`):

```bash
REDDIT_CLIENT_ID=your-client-id
REDDIT_CLIENT_SECRET=your-client-secret
```

---

## 🔗 相关资源

- [requests 文档](https://docs.python-requests.org/)
- [BeautifulSoup 文档](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
- [feedparser 文档](https://feedparser.readthedocs.io/)
- [API 参考文档](../api/README.md)

---

## 🚀 下一步

- [配置文件详解](configuration.md)
- [故障排查手册](troubleshooting.md)
- [查看 CONTRIBUTING 规范](../../CONTRIBUTING.md)

---

**Last Updated**: 2026-01-21
