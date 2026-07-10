"""
LLM Summarizer using ModelScope API with secondary ModelScope and SiliconFlow fallback.
Summarizes news articles into daily reports.
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any
from openai import OpenAI
from config import get_config
from utils.run_contracts import RunDeadlineExceeded
from utils.summary_contracts import (
    SummaryAttempt,
    SummaryItem,
    SummaryResult,
    fingerprint_summary_input,
)


class SummaryQualityError(ValueError):
    """Raised when an LLM response is not a usable Chinese daily summary."""


def create_client(
    base_url: str,
    api_key: str,
    *,
    timeout: float | None = None,
) -> OpenAI:
    """Create OpenAI-compatible client."""
    options = {"base_url": base_url, "api_key": api_key, "max_retries": 0}
    if timeout is not None:
        options["timeout"] = timeout
    return OpenAI(**options)


def load_prompt(path: str = None) -> str:
    """Load system prompt from file"""
    cfg = get_config()
    prompt_path = Path(path or cfg.prompt_path)
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return "你是一个专业的AI资讯编辑，请将新闻整理成简洁的中文日报。"


def compress_articles(articles: list[dict]) -> list[dict]:
    """Compress articles to reduce token usage"""
    cfg = get_config()
    compressed = []
    for a in articles:
        compressed.append(
            {
                "title": (a.get("title") or "")[: cfg.title_max],
                "link": a.get("link") or "",
                "publish_time": a.get("publish_time") or "",
                "description": (a.get("description") or "")[: cfg.desc_max],
                "priority": a.get("priority", 0),
            }
        )
    return compressed


def _count_cjk(text: str) -> int:
    """Count CJK characters as a practical proxy for Chinese summary quality."""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _numbered_items(content: str) -> list[str]:
    """Extract numbered daily-report items from Markdown-ish text."""
    items = []
    for line in content.splitlines():
        match = re.match(r"^\s*\d+[.、]\s+(.+?)\s*$", line)
        if match:
            items.append(match.group(1))
    return items


def validate_summary_quality(content: str, expected_items: int = 10) -> None:
    """Validate that generated content is a complete Simplified Chinese digest."""
    stripped = content.strip()
    if not stripped:
        raise SummaryQualityError("summary is empty")

    items = _numbered_items(stripped)
    min_items = max(1, min(10, expected_items))
    if len(items) < min_items:
        raise SummaryQualityError(
            f"summary has {len(items)} numbered items, expected at least {min_items}"
        )

    if "互动话题" not in stripped:
        raise SummaryQualityError("summary is missing the interaction footer")

    searchable_chars = re.findall(r"[\u4e00-\u9fffA-Za-z]", stripped)
    chinese_ratio = _count_cjk(stripped) / max(1, len(searchable_chars))
    if chinese_ratio < 0.45:
        raise SummaryQualityError(
            f"summary is not predominantly Chinese (ratio={chinese_ratio:.2f})"
        )

    for index, item in enumerate(items[:min_items], 1):
        if _count_cjk(item) < 8:
            raise SummaryQualityError(
                f"item {index} does not contain enough Chinese content"
            )
        if "http://" in item or "https://" in item:
            raise SummaryQualityError(f"item {index} contains a raw link")


def _provider_candidates() -> list[dict[str, str]]:
    """Build provider candidates in priority order."""
    cfg = get_config()
    providers: list[dict[str, str]] = []

    def append_provider(name: str, base_url: str, api_key: str, model: str) -> None:
        if not api_key or not model:
            return
        candidate = {
            "name": name,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
        }
        if any(
            provider["base_url"] == base_url and provider["model"] == model
            for provider in providers
        ):
            return
        providers.append(candidate)

    if cfg.api_key:
        append_provider(
            "ModelScope",
            cfg.api_base_url,
            cfg.api_key,
            cfg.model,
        )
        append_provider(
            "ModelScope secondary",
            cfg.api_base_url,
            cfg.api_key,
            cfg.modelscope_secondary_model,
        )

    if cfg.fallback_api_key:
        append_provider(
            "SiliconFlow",
            cfg.fallback_api_base_url,
            cfg.fallback_api_key,
            cfg.fallback_model,
        )

    return providers


def summarize(
    articles: list[dict],
    stream: bool = True,
    deadline_at=None,
) -> str:
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
    user_input = json.dumps({"articles": compressed}, ensure_ascii=False, indent=2)
    system_prompt = load_prompt()

    errors: list[str] = []
    for idx, provider in enumerate(providers):
        if deadline_at is not None:
            remaining = (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds()
            if remaining <= 0:
                raise RunDeadlineExceeded("run deadline exceeded before summary")
        else:
            remaining = None
        if remaining is None:
            client = create_client(provider["base_url"], provider["api_key"])
        else:
            client = create_client(
                provider["base_url"], provider["api_key"], timeout=remaining
            )
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
                print(
                    f"\n   🔁 Trying fallback provider: {provider['name']} ({provider['model']})"
                )

            if stream:
                content = _summarize_stream(client, params)
            else:
                content = _summarize_sync(client, params)
            validate_summary_quality(
                content,
                expected_items=min(10, len(compressed)),
            )
            return content
        except Exception as e:
            errors.append(f"{provider['name']}[{provider['model']}]: {e}")
            print(f"\n   ⚠️  {provider['name']} failed: {e}")

    raise RuntimeError("All LLM providers failed. " + " | ".join(errors))


def _parse_summary_result(
    content: str,
    articles: list[dict],
    *,
    policy: str,
    provider: str,
    model: str,
    input_fingerprint: str,
    prompt_fingerprint: str,
    attempts: tuple[SummaryAttempt, ...],
) -> SummaryResult:
    """Convert validated model text into a provenance-preserving contract."""
    items: list[SummaryItem] = []
    for index, line in enumerate(content.splitlines()):
        match = re.match(r"^\s*\d+[.、]\s+(.+?)\s*$", line)
        if not match:
            continue
        text = match.group(1).strip()
        link_match = re.match(r"^\[(.+?)\]\((https?://[^)]+)\)[:：]\s*(.+)$", text)
        input_urls = {
            str(article.get("link"))
            for article in articles
            if str(article.get("link") or "").startswith(("http://", "https://"))
        }
        if link_match and link_match.group(2) in input_urls:
            title, url, summary = link_match.groups()
        else:
            article = articles[len(items)] if len(items) < len(articles) else {}
            title = article.get("title") or text
            url = article.get("link") or ""
            summary = text
        article_id = url or f"article-{index + 1}"
        items.append(
            SummaryItem(
                article_id=article_id,
                title=title.strip(),
                summary=summary.strip(),
                url=url.strip(),
            )
        )

    discussion_topic = ""
    for line in content.splitlines():
        if "互动话题" in line:
            discussion_topic = re.sub(r"^.*?互动话题[：:]\s*", "", line).strip()
            break
    if not discussion_topic:
        discussion_topic = "欢迎分享你最关注的新闻。"
    return SummaryResult(
        policy=policy,
        items=tuple(items),
        discussion_topic=discussion_topic,
        provider=provider,
        model=model,
        input_fingerprint=input_fingerprint,
        prompt_fingerprint=prompt_fingerprint,
        attempts=attempts,
    )


def summarize_result(
    articles: list[dict],
    *,
    stream: bool = True,
    deadline_at=None,
) -> SummaryResult:
    """Generate a structured AI summary with provider-attempt provenance."""
    if not articles:
        input_fingerprint, prompt_fingerprint = fingerprint_summary_input([], "")
        return SummaryResult(
            policy="required_ai",
            items=(),
            discussion_topic="暂无新闻。",
            provider="none",
            model="none",
            input_fingerprint=input_fingerprint,
            prompt_fingerprint=prompt_fingerprint,
            attempts=(),
        )

    cfg = get_config()
    providers = _provider_candidates()
    if not providers:
        raise ValueError(
            "No LLM provider API key found. Set MODELSCOPE_API_KEY or SILICONFLOW_API_KEY."
        )
    compressed = compress_articles(articles)
    system_prompt = load_prompt()
    input_fingerprint, prompt_fingerprint = fingerprint_summary_input(
        compressed, system_prompt
    )
    user_input = json.dumps({"articles": compressed}, ensure_ascii=False, indent=2)
    attempts: list[SummaryAttempt] = []
    errors: list[str] = []

    for idx, provider in enumerate(providers):
        remaining = None
        if deadline_at is not None:
            remaining = (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds()
            if remaining <= 0:
                raise RunDeadlineExceeded("run deadline exceeded before summary")
        try:
            client = (
                create_client(provider["base_url"], provider["api_key"])
                if remaining is None
                else create_client(
                    provider["base_url"], provider["api_key"], timeout=remaining
                )
            )
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
            content = (
                _summarize_stream(client, params)
                if stream
                else _summarize_sync(client, params)
            )
            validate_summary_quality(content, expected_items=min(10, len(compressed)))
            attempts.append(
                SummaryAttempt(
                    provider=provider["name"],
                    model=provider["model"],
                    status="ok",
                )
            )
            return _parse_summary_result(
                content,
                articles,
                policy="required_ai",
                provider=provider["name"],
                model=provider["model"],
                input_fingerprint=input_fingerprint,
                prompt_fingerprint=prompt_fingerprint,
                attempts=tuple(attempts),
            )
        except RunDeadlineExceeded:
            raise
        except Exception as exc:
            errors.append(f"{provider['name']}[{provider['model']}]: {exc}")
            attempts.append(
                SummaryAttempt(
                    provider=provider["name"],
                    model=provider["model"],
                    status="failed",
                    error_kind=type(exc).__name__,
                )
            )
            if idx + 1 < len(providers):
                print(f"\n   ⚠️  {provider['name']} failed: {exc}")

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
    sorted_arts = sorted(articles, key=lambda x: x.get("priority", 0), reverse=True)

    lines = []
    for i, a in enumerate(sorted_arts[:limit], 1):
        title = (a.get("title") or "").replace("\n", "").strip()
        link = (a.get("link") or "").strip()
        marker = "🔥" if a.get("priority", 0) > 0 else ""
        headline = f"{marker}{title}"
        if link:
            headline = f"[{headline}]({link})"
        lines.append(f"{i}. {headline}")
        lines.append("")

    lines.append("互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！🤔💬")
    return "\n".join(lines)


def offline_summary_result(articles: list[dict], limit: int = 10):
    """Create a structured deterministic offline summary for replayable runs."""
    from utils.summary_contracts import (
        SummaryAttempt,
        SummaryItem,
        SummaryResult,
        fingerprint_summary_input,
    )

    selected = sorted(articles, key=lambda x: x.get("priority", 0), reverse=True)[
        :limit
    ]
    input_fingerprint, prompt_fingerprint = fingerprint_summary_input(
        selected, "offline"
    )
    items = tuple(
        SummaryItem(
            article_id=article.get("link") or f"offline-{index}",
            title=(article.get("title") or "").replace("\n", "").strip(),
            summary=article.get("description") or "离线模式：仅提供原始新闻标题。",
            url=article.get("link") or "",
        )
        for index, article in enumerate(selected, 1)
    )
    return SummaryResult(
        policy="offline",
        items=items,
        discussion_topic="你最关注哪条AI新闻？欢迎留言分享你的看法！🤔💬",
        provider="local",
        model="deterministic",
        input_fingerprint=input_fingerprint,
        prompt_fingerprint=prompt_fingerprint,
        attempts=(
            SummaryAttempt(provider="local", model="deterministic", status="ok"),
        ),
    )


def test_connection() -> bool:
    """Test API connection (primary first, then fallback)."""
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
