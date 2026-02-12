"""
LLM Summarizer using ModelScope API with SiliconFlow fallback.
Summarizes news articles into daily reports.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from openai import OpenAI
from config import get_config


def create_client(base_url: str, api_key: str) -> OpenAI:
    """Create OpenAI-compatible client."""
    return OpenAI(base_url=base_url, api_key=api_key)


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


def _provider_candidates() -> list[dict[str, str]]:
    """Build provider candidates in priority order."""
    cfg = get_config()
    providers: list[dict[str, str]] = []

    if cfg.api_key:
        providers.append({
            "name": "ModelScope",
            "base_url": cfg.api_base_url,
            "api_key": cfg.api_key,
            "model": cfg.model,
        })

    if cfg.fallback_api_key:
        providers.append({
            "name": "SiliconFlow",
            "base_url": cfg.fallback_api_base_url,
            "api_key": cfg.fallback_api_key,
            "model": cfg.fallback_model,
        })

    return providers


def summarize(articles: list[dict], stream: bool = True) -> str:
    """
    Summarize articles using LLM with provider fallback.

    Args:
        articles: List of article dicts
        stream: Whether to stream output (default True)

    Returns:
        Summarized markdown content
    """
    if not articles:
        return "暂无新闻"

    cfg = get_config()
    providers = _provider_candidates()
    if not providers:
        raise ValueError(
            "No LLM provider API key found. Set MODELSCOPE_API_KEY or SILICONFLOW_API_KEY."
        )

    compressed = compress_articles(articles)
    user_input = json.dumps({'articles': compressed}, ensure_ascii=False, indent=2)
    system_prompt = load_prompt()

    errors: list[str] = []
    for idx, provider in enumerate(providers):
        client = create_client(provider["base_url"], provider["api_key"])
        params: dict[str, Any] = {
            "model": provider["model"],
            "max_tokens": cfg.max_output,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "stream": stream,
        }

        try:
            if idx > 0:
                print(f"\n   🔁 Trying fallback provider: {provider['name']} ({provider['model']})")

            if stream:
                return _summarize_stream(client, params)
            return _summarize_sync(client, params)
        except Exception as e:
            errors.append(f"{provider['name']}[{provider['model']}]: {e}")
            print(f"\n   ⚠️  {provider['name']} failed: {e}")

    raise RuntimeError("All LLM providers failed. " + " | ".join(errors))


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
    """Test API connection (primary first, then fallback)."""
    cfg = get_config()
    providers = _provider_candidates()

    if not providers:
        print("❌ 未找到可用 API Key（MODELSCOPE_API_KEY / SILICONFLOW_API_KEY）")
        return False

    for provider in providers:
        try:
            client = create_client(provider["base_url"], provider["api_key"])
            response = client.chat.completions.create(
                model=provider["model"],
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "你好，请用一句话介绍自己。"},
                ],
                stream=False,
            )
            print("✅ API 连接成功！")
            print(f"   供应商: {provider['name']}")
            print(f"   模型: {provider['model']}")
            print(f"   响应: {response.choices[0].message.content}")
            return True
        except Exception as e:
            print(f"⚠️  {provider['name']} 连接失败: {e}")

    print("❌ 所有供应商连接失败")
    return False


if __name__ == "__main__":
    test_connection()
