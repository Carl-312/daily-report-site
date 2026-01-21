"""
LLM Summarizer using ModelScope API (GLM-4.7)
Summarizes news articles into daily reports
"""
from __future__ import annotations
import json
from pathlib import Path
from openai import OpenAI
from config import get_config


def create_client() -> OpenAI:
    """Create OpenAI-compatible client for ModelScope API"""
    cfg = get_config()
    if not cfg.api_key:
        raise ValueError("MODELSCOPE_API_KEY not set. Check your .env file.")
    
    return OpenAI(
        base_url=cfg.api_base_url,
        api_key=cfg.api_key,
    )


def load_prompt(path: str = None) -> str:
    """Load system prompt from file"""
    cfg = get_config()
    prompt_path = Path(path or cfg.prompt_path)
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    return "你是一个专业的AI资讯编辑，请将新闻整理成简洁的中文日报。"


def compress_articles(articles: list[dict]) -> list[dict]:
    """Compress articles to reduce token usage"""
    cfg = get_config()
    compressed = []
    for a in articles:
        compressed.append({
            'title': (a.get('title') or '')[:cfg.title_max],
            'link': a.get('link') or '',
            'publish_time': a.get('publish_time') or '',
            'description': (a.get('description') or '')[:cfg.desc_max],
            'priority': a.get('priority', 0),
        })
    return compressed


def summarize(articles: list[dict], stream: bool = True) -> str:
    """
    Summarize articles using LLM
    
    Args:
        articles: List of article dicts
        stream: Whether to stream output (default True)
    
    Returns:
        Summarized markdown content
    """
    if not articles:
        return "暂无新闻"
    
    cfg = get_config()
    client = create_client()
    
    # Compress and prepare input
    compressed = compress_articles(articles)
    user_input = json.dumps({'articles': compressed}, ensure_ascii=False, indent=2)
    system_prompt = load_prompt()
    
    # Build request params
    params = {
        "model": cfg.model,
        "max_tokens": cfg.max_output,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        "stream": stream,
    }
    
    if stream:
        return _summarize_stream(client, params)
    else:
        return _summarize_sync(client, params)


def _summarize_sync(client: OpenAI, params: dict) -> str:
    """Non-streaming summarization"""
    params["stream"] = False
    response = client.chat.completions.create(**params)
    return response.choices[0].message.content or ""


def _summarize_stream(client: OpenAI, params: dict) -> str:
    """Streaming summarization with live output"""
    params["stream"] = True
    response = client.chat.completions.create(**params)
    
    result = []
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            print(content, end="", flush=True)
            result.append(content)
    
    print()  # Newline after streaming
    return "".join(result)


def offline_summary(articles: list[dict], limit: int = 10) -> str:
    """Offline fallback: simple bullet list without LLM"""
    sorted_arts = sorted(articles, key=lambda x: x.get('priority', 0), reverse=True)
    
    lines = []
    for i, a in enumerate(sorted_arts[:limit], 1):
        title = (a.get('title') or '').replace('\n', '').strip()
        marker = "🔥" if a.get('priority', 0) > 0 else ""
        lines.append(f"{i}. {marker}{title[:40]}")
        lines.append("")
    
    lines.append("互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！🤔💬")
    return "\n".join(lines)


def test_connection() -> bool:
    """Test API connection"""
    try:
        client = create_client()
        cfg = get_config()
        response = client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "你好，请用一句话介绍自己。"},
            ],
            stream=False,
        )
        print(f"✅ API 连接成功！")
        print(f"   模型: {cfg.model}")
        print(f"   响应: {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"❌ API 连接失败: {e}")
        return False


if __name__ == "__main__":
    test_connection()
