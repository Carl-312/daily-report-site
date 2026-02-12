# API 参考文档

本文档描述 Daily Report Site 各模块的接口定义和使用方法。

---

## 📡 新闻源接口 (sources/)

### 通用接口规范

所有新闻源模块必须实现以下接口:

```python
def fetch() -> List[Dict[str, str]]:
    """
    从新闻源获取文章列表
    
    Returns:
        文章列表，每个文章包含以下字段:
        [
            {
                "title": str,   # 文章标题 (必需)
                "link": str,    # 完整 URL (必需)
                "desc": str     # 简短描述，50-200 字 (必需)
            },
            ...
        ]
    
    Raises:
        requests.RequestException: 网络请求失败
        ValueError: 数据格式错误
    """
```

### 当前实现的源

#### AIBase (`sources/aibase.py`)

**描述**: 中文 AI 资讯聚合平台

**端点**: `https://www.aibase.com`

**特点**:
- 返回中文标题和描述
- 自动过滤广告内容
- 默认获取最新 20 篇文章

**示例输出**:
```python
[
    {
        "title": "OpenAI 发布 GPT-5 预览版",
        "link": "https://www.aibase.com/zh/news/12345",
        "desc": "OpenAI 今日宣布推出 GPT-5 预览版，性能提升 50%..."
    }
]
```

#### TechCrunch (`sources/techcrunch.py`)

**描述**: 国际科技新闻媒体

**端点**: `https://techcrunch.com`

**特点**:
- 英文内容
- 包含创投、AI、硬件等多个类别
- RSS Feed 抓取

**示例输出**:
```python
[
    {
        "title": "Startup X raises $50M Series B",
        "link": "https://techcrunch.com/2026/01/21/startup-x-...",
        "desc": "Startup X, a leading AI platform, announced today..."
    }
]
```

#### The Verge (`sources/theverge.py`)

**描述**: 科技与文化新闻

**端点**: `https://www.theverge.com`

**特点**:
- 英文内容
- 科技、游戏、文化等主题
- HTML 解析

---

## 🤖 摘要生成接口 (summarizer.py)

### summarize()

```python
def summarize(
    articles: List[Dict[str, str]], 
    stream: bool = False
) -> str:
    """
    使用 LLM API 生成智能摘要
    
    Args:
        articles: 文章列表 (来自 sources)
        stream: 是否启用流式输出 (实时打印)
    
    Returns:
        Markdown 格式的摘要内容
    
    Raises:
        ConnectionError: API 连接失败
        AuthenticationError: API Key 无效
        
    Environment:
        MODELSCOPE_API_KEY: ModelScope API 密钥 (必需)
        MODELSCOPE_MODEL: 模型名称 (可选，默认 ZhipuAI/GLM-5)
    """
```

**调用示例**:
```python
from summarizer import summarize

articles = [
    {"title": "...", "link": "...", "desc": "..."},
    # ...
]

content = summarize(articles, stream=True)
print(content)
```

**API 请求格式**:
```json
{
  "model": "ZhipuAI/GLM-5",
  "messages": [
    {
      "role": "system",
      "content": "<prompts/daily.md 的内容>"
    },
    {
      "role": "user",
      "content": "[{\"title\": \"...\", \"link\": \"...\"}, ...]"
    }
  ],
  "stream": true,
  "temperature": 0.7
}
```

**API 响应格式** (stream=true):
```
data: {"choices": [{"delta": {"content": "## 今日要闻\n\n"}}]}
data: {"choices": [{"delta": {"content": "### OpenAI 发布..."}}]}
...
data: [DONE]
```

### offline_summary()

```python
def offline_summary(articles: List[Dict[str, str]]) -> str:
    """
    本地摘要算法 (无需 API)
    
    Args:
        articles: 文章列表
    
    Returns:
        Markdown 格式的简单列表
    
    Note:
        此方法仅格式化原始内容，不进行智能摘要
    """
```

**输出示例**:
```markdown
## 📰 今日资讯

### [OpenAI 发布 GPT-5](https://...)
OpenAI 今日宣布推出 GPT-5 预览版...

### [Startup X 融资 5000 万美元](https://...)
Startup X, a leading AI platform...
```

### test_connection()

```python
def test_connection() -> bool:
    """
    测试 ModelScope API 连接
    
    Returns:
        True: 连接成功
        False: 连接失败
    
    Prints:
        详细的诊断信息
    """
```

**使用场景**:
```bash
# CLI
python main.py test

# 代码
from summarizer import test_connection
if test_connection():
    print("API 配置正确")
```

---

## 🔧 工具函数 (utils/)

### dedupe()

```python
from utils import dedupe

def dedupe(articles: List[Article]) -> List[Article]:
    """
    基于 URL 和标题的去重
    
    Args:
        articles: Article 对象列表
    
    Returns:
        去重后的列表
    
    Algorithm:
        1. URL 精确匹配
        2. 标题 Levenshtein 距离 < 5 视为重复
        3. 保留最早出现的文章
    """
```

### today_ymd() / today_cn()

```python
from utils import today_ymd, today_cn

today_ymd()  # "2026-01-21"
today_cn()   # "1月21日"
```

### save_json() / load_json()

```python
from utils import save_json, load_json

# 保存
path = save_json(
    directory="data",
    filename="2026-01-21",
    data={"articles": [...]},
)
# 生成: data/2026-01-21.json

# 加载
data = load_json("data", "2026-01-21")
```

### save_markdown()

```python
from utils import save_markdown

path = save_markdown(
    directory="content",
    filename="2026-01-21",
    content="# Title\n\nContent...",
)
# 生成: content/2026-01-21.md
```

---

## 🏗️ 静态站点构建 (build.py)

### build_site()

```python
from build import build_site

def build_site() -> None:
    """
    构建完整的静态站点
    
    Process:
        1. 扫描 content/*.md
        2. 为每篇文章生成独立 HTML
        3. 生成首页 index.html
        4. 生成归档页 archive.html
        5. 复制静态资源 (CSS)
    
    Output:
        docs/
        ├── index.html
        ├── archive.html
        ├── 2026-01-21.html
        ├── 2026-01-20.html
        └── style.css
    """
```

### parse_frontmatter()

```python
def parse_frontmatter(content: str) -> Tuple[Dict, str]:
    """
    解析 Markdown Frontmatter (可选功能)
    
    Args:
        content: Markdown 文件内容
    
    Returns:
        (metadata, body)
    
    Example:
        Input:
            ---
            title: Custom Title
            ---
            # Content
        
        Output:
            ({"title": "Custom Title"}, "# Content")
    """
```

---

## 📝 配置管理 (config.py)

### get_config()

```python
from config import get_config

cfg = get_config()

# 访问配置
print(cfg.api_key)       # 从 .env 读取
print(cfg.sources)       # 从 config.yaml 读取
print(cfg.max_articles)  # 14
```

### Config 数据类

```python
@dataclass
class Config:
    # API 配置
    api_key: str
    model: str
    
    # 新闻源配置
    sources: Dict[str, bool]
    max_articles: int
    
    # Syft 配置 (可选)
    syft_web_app_url: Optional[str]
    syft_secret_key: Optional[str]
    
    # 路径配置
    data_dir: Path
    content_dir: Path
    docs_dir: Path
    
    # 摘要配置
    prompt_path: Path
    prefer_chinese: bool
    title_max: int
    desc_max: int
```

---

## 🔌 扩展示例

### 添加自定义新闻源

```python
# sources/hacker_news.py
import requests
from typing import List, Dict

def fetch() -> List[Dict[str, str]]:
    """从 Hacker News 获取头条"""
    response = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()[:10]
    
    articles = []
    for story_id in story_ids:
        story_resp = requests.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_resp.json()
        
        articles.append({
            "title": story["title"],
            "link": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
            "desc": story.get("text", "No description available")[:200],
        })
    
    return articles
```

**注册**:
```python
# sources/__init__.py
from .hacker_news import fetch as fetch_hackernews

SOURCE_REGISTRY = {
    # ...
    "hackernews": fetch_hackernews,
}
```

**启用**:
```yaml
# config.yaml
sources:
  hackernews: true
```

---

**Last Updated**: 2026-01-21  
**Version**: 1.0.0
