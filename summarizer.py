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
    SUMMARY_MAX_VISIBLE_CHARS,
    SUMMARY_MIN_VISIBLE_CHARS,
    SUMMARY_TARGET_MIN_VISIBLE_CHARS,
    SUMMARY_TARGET_MAX_VISIBLE_CHARS,
    SummaryAttempt,
    SummaryDraft,
    SummaryItem,
    SummaryResult,
    fingerprint_summary_input,
    impact_summary_issues,
    reader_summary_issues,
    render_summary_markdown,
    summary_visible_character_count,
    validate_summary_result,
)
from utils.summary_selection import (
    SUMMARY_SELECTION_POLICY,
    article_reference_id,
    article_reference_map,
    article_source_label,
    select_summary_candidates_with_diagnostics,
)


class SummaryQualityError(ValueError):
    """Raised when an LLM response is not a usable Chinese daily summary."""


def modelscope_request_options(model: str) -> dict[str, Any]:
    """Return verified ModelScope-specific generation controls for a model."""
    if model == "ZhipuAI/GLM-5.2":
        return {"extra_body": {"enable_thinking": False}}
    if model == "Qwen/Qwen3.5-35B-A3B":
        return {
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": False},
            }
        }
    return {}


def _summary_limit(cfg=None) -> int:
    """Return the independent daily-news limit, not a source-candidate limit."""
    cfg = cfg or get_config()
    return max(1, int(getattr(cfg, "max_summary_items", 10)))


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
    for index, a in enumerate(articles, 1):
        item = {
            "article_id": article_reference_id(a, index),
            "title": (a.get("title") or "")[: cfg.title_max],
            "description": (a.get("description") or "")[: cfg.desc_max],
        }
        trend_signal = _trend_editorial_signal(a)
        if trend_signal is not None:
            item["trend_signal"] = trend_signal
        compressed.append(item)
    return compressed


def _trend_editorial_signal(article: dict) -> dict[str, int | float | str] | None:
    """Expose validated Trending rank/heat to the editor without source URLs."""

    if str(article.get("source") or "") != "agihunt_trending":
        return None
    provenance = article.get("provenance")
    if not isinstance(provenance, dict):
        return None
    try:
        rank = int(provenance.get("trend_rank", ""))
        heat = float(provenance.get("trend_heat", ""))
    except (TypeError, ValueError):
        return None
    if rank < 1 or heat < 0:
        return None

    signal: dict[str, int | float | str] = {"rank": rank, "heat": heat}
    state = str(provenance.get("trend_state") or "")
    if state in {"up", "down", "new", "steady"}:
        signal["state"] = state
    try:
        delta = int(provenance.get("trend_delta", ""))
    except (TypeError, ValueError):
        delta = -1
    if delta >= 0:
        signal["delta"] = delta
    return signal


def _count_cjk(text: str) -> int:
    """Count CJK characters as a practical proxy for Chinese summary quality."""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _numbered_items(content: str) -> list[str]:
    """Extract numbered daily-report items from Markdown-ish text."""
    items = []
    for line in content.splitlines():
        match = re.match(r"^\s*\d+[.、]\s+(.+?)\s*$", line)
        if not match:
            match = re.match(r"^\s*#{1,6}\s+\d+[.、]\s+(.+?)\s*$", line)
        if match:
            items.append(match.group(1))
    return items


_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_PUBLIC_LINK = re.compile(r"(?:https?://|www\.)|\[[^\]]+\]\([^)]*\)", re.IGNORECASE)
_PUBLIC_ARTICLE_ID = re.compile(r"\[a\d+\]", re.IGNORECASE)
_SOURCE_SENTENCE = re.compile(r"[^。！？]+[。！？]")
_TITLE_SEPARATOR = re.compile(r"[:：]")
_COMPACT_HEADLINE_REWRITES = (
    ("能力飞跃", "能力显著跃迁"),
    ("引争议", "引发业界争议"),
)


def _strip_json_fence(content: str) -> str:
    """Accept a fenced JSON response while keeping the model contract strict."""

    stripped = content.strip()
    match = _JSON_FENCE.fullmatch(stripped)
    return match.group(1).strip() if match else stripped


def _contains_public_link(value: str) -> bool:
    return bool(_PUBLIC_LINK.search(value))


def _contains_public_article_id(value: str) -> bool:
    return bool(_PUBLIC_ARTICLE_ID.search(value))


def _normalize_reader_text(value: object) -> str:
    """Collapse whitespace before applying the reader-visible character budget."""
    return " ".join(str(value or "").split())


def _complete_reader_sentence(value: object) -> str:
    """Normalize a title-shaped fact into one displayable sentence."""

    normalized = _normalize_reader_text(value)
    if not normalized:
        return ""
    if normalized[-1] in "。！？":
        return normalized
    return f"{normalized.rstrip(' ，、；:：')}。"


def _title_reader_sentence(title: str, description: str) -> str:
    """Turn a source headline into a sentence without a title/summary colon."""

    normalized_title = _normalize_reader_text(title)
    separator = _TITLE_SEPARATOR.search(normalized_title)
    if separator:
        subject = normalized_title[: separator.start()].strip()
        predicate = normalized_title[separator.end() :].strip()
        if subject and predicate:
            # When the source description explicitly attributes a statement to
            # the headline subject, preserve that relationship. Otherwise the
            # headline's colon is an apposition and reads naturally with "是".
            attribution = re.search(
                rf"{re.escape(subject)}\s*(?:说|称|表示|指出|认为|透露|宣布)",
                description,
            )
            connector = "称" if attribution else "是"
            normalized_title = f"{subject}{connector}{predicate}"
    # Source headlines often omit grammatical glue to stay short. Expand only
    # stable, meaning-preserving patterns so the reader still gets one clear
    # sentence without falling back to a much longer source description.
    for source, replacement in _COMPACT_HEADLINE_REWRITES:
        normalized_title = normalized_title.replace(source, replacement)
    normalized_title = _TITLE_SEPARATOR.sub("，", normalized_title)
    return _complete_reader_sentence(normalized_title)


def _source_sentence_candidates(value: str) -> list[str]:
    """Return complete, source-faithful description sentences without clipping."""

    normalized = _normalize_reader_text(value)
    candidates = [
        match.group(0).strip() for match in _SOURCE_SENTENCE.finditer(normalized)
    ]
    if not candidates and normalized:
        candidates.append(_complete_reader_sentence(normalized))
    return [_TITLE_SEPARATOR.sub("，", candidate) for candidate in candidates]


def _offline_candidate_rank(source: str, text: str) -> tuple[int, int, int]:
    """Prefer a normal-length digest without sacrificing a full source fact."""

    length = summary_visible_character_count(text)
    # A description sentence normally carries the fact's useful qualifier,
    # while a title in the same range remains a sound fallback.
    source_rank = 0 if source == "description" else 1
    target_midpoint = (
        SUMMARY_TARGET_MIN_VISIBLE_CHARS + SUMMARY_TARGET_MAX_VISIBLE_CHARS
    ) // 2
    if SUMMARY_TARGET_MIN_VISIBLE_CHARS <= length <= SUMMARY_TARGET_MAX_VISIBLE_CHARS:
        return (0, abs(length - target_midpoint), source_rank)
    if length > SUMMARY_TARGET_MAX_VISIBLE_CHARS:
        # A complete, source-faithful 66–95-character sentence is preferable
        # to reverting to a bare headline when no normal-length source fact
        # exists.
        return (1, length - SUMMARY_TARGET_MAX_VISIBLE_CHARS, source_rank)
    return (2, SUMMARY_TARGET_MIN_VISIBLE_CHARS - length, source_rank)


def _offline_summary_text(article: dict) -> str:
    """Choose a factual, complete fallback when an LLM is intentionally absent."""

    title = _normalize_reader_text(article.get("title"))
    description = _normalize_reader_text(article.get("description"))
    candidates: list[tuple[str, str]] = []
    title_sentence = _title_reader_sentence(title, description)
    if not reader_summary_issues(title_sentence):
        candidates.append(("title", title_sentence))
    for sentence in _source_sentence_candidates(description):
        if not reader_summary_issues(sentence):
            candidates.append(("description", sentence))
    if not candidates:
        raise ValueError(
            "offline summary cannot preserve one complete "
            f"{SUMMARY_MIN_VISIBLE_CHARS}–"
            f"{SUMMARY_MAX_VISIBLE_CHARS}-character source sentence without "
            "truncation"
        )
    return min(candidates, key=lambda candidate: _offline_candidate_rank(*candidate))[1]


def _parse_summary_draft(content: str) -> SummaryDraft:
    try:
        return SummaryDraft.model_validate_json(_strip_json_fence(content))
    except ValueError as exc:
        raise SummaryQualityError(
            "summary is not valid JSON matching the contract"
        ) from exc


def validate_summary_quality(
    content: str,
    expected_items: int = 10,
    expected_article_ids: set[str] | tuple[str, ...] | None = None,
    *,
    require_impact: bool = False,
) -> SummaryDraft:
    """Validate the compact JSON output before joining private source metadata."""
    draft = _parse_summary_draft(content)

    max_items = max(0, expected_items)
    if max_items == 0:
        raise SummaryQualityError("cannot publish a summary without source articles")

    if not draft.items:
        raise SummaryQualityError(
            "summary must contain at least one item when source articles exist"
        )
    if len(draft.items) > max_items:
        raise SummaryQualityError(
            f"summary has {len(draft.items)} items, maximum allowed is {max_items}"
        )

    discussion_topic = draft.discussion_topic.strip()
    if not discussion_topic:
        raise SummaryQualityError("summary is missing the interaction topic")
    if _contains_public_link(discussion_topic):
        raise SummaryQualityError("interaction topic contains a link")
    if _contains_public_article_id(discussion_topic):
        raise SummaryQualityError("interaction topic exposes an article_id")

    visible_text = "\n".join(item.summary for item in draft.items)
    searchable_chars = re.findall(r"[\u4e00-\u9fffA-Za-z]", visible_text)
    chinese_ratio = _count_cjk(visible_text) / max(1, len(searchable_chars))
    if chinese_ratio < 0.45:
        raise SummaryQualityError(
            f"summary is not predominantly Chinese (ratio={chinese_ratio:.2f})"
        )

    for index, item in enumerate(draft.items, 1):
        article_id = item.article_id.strip()
        title = item.title.strip()
        summary = item.summary.strip()
        impact = item.why_it_matters.strip()
        if expected_article_ids is not None:
            if article_id not in expected_article_ids:
                raise SummaryQualityError(
                    f"item {index} references unknown article_id {article_id}"
                )
        if not summary:
            raise SummaryQualityError(f"item {index} is missing a summary")
        if _count_cjk(summary) < 8:
            raise SummaryQualityError(
                f"item {index} does not contain enough Chinese content"
            )
        if _contains_public_link(summary):
            raise SummaryQualityError(f"item {index} contains a link")
        if _contains_public_article_id(summary):
            raise SummaryQualityError(f"item {index} exposes an article_id")
        if title and _contains_public_link(title):
            raise SummaryQualityError(f"item {index} contains a link")
        if title and _contains_public_article_id(title):
            raise SummaryQualityError(f"item {index} exposes an article_id")
        if issues := reader_summary_issues(summary):
            raise SummaryQualityError(f"item {index} summary " + "; ".join(issues))
        if require_impact and not impact:
            raise SummaryQualityError(f"item {index} is missing why_it_matters")
        if impact and _contains_public_link(impact):
            raise SummaryQualityError(f"item {index} impact contains a link")
        if impact and _contains_public_article_id(impact):
            raise SummaryQualityError(f"item {index} impact exposes an article_id")
        if impact and (issues := impact_summary_issues(impact)):
            raise SummaryQualityError(f"item {index} impact " + "; ".join(issues))
    if isinstance(expected_article_ids, tuple):
        output_ids = tuple(item.article_id.strip() for item in draft.items)
        if output_ids != expected_article_ids:
            raise SummaryQualityError(
                "summary must cover every selected candidate exactly once and in order"
            )
    return draft


def _validate_summary_with_one_repair(
    client: OpenAI,
    params: dict[str, Any],
    content: str,
    *,
    expected_items: int,
    expected_article_ids: tuple[str, ...],
) -> SummaryDraft:
    """Retry one non-empty response only when its reader summary is invalid."""

    try:
        return validate_summary_quality(
            content,
            expected_items=expected_items,
            expected_article_ids=expected_article_ids,
            require_impact=True,
        )
    except SummaryQualityError as exc:
        # Do not spend another request on empty output, schema drift, or unknown
        # IDs. A focused repair is useful for a complete JSON draft that either
        # missed one selected ID or missed the reader sentence contract.
        repairable = re.search(
            r"\bitem \d+ (?:summary|impact|is missing why_it_matters)\b", str(exc)
        ) or ("cover every selected candidate" in str(exc))
        if not content.strip() or not repairable:
            raise

        repair_instruction = (
            f"上一版 JSON 未通过本地检查：{exc}。重新输出完整 JSON；逐条保留输入 "
            "article_id 和顺序，每条 summary 以 45–65 个可见字符为目标，硬性保持在 "
            f"{SUMMARY_MIN_VISIBLE_CHARS}–{SUMMARY_MAX_VISIBLE_CHARS} 个可见字符；"
            "写成完整中文单句；why_it_matters 用 15–70 个可见字符说明影响，"
            "不要解释 JSON 之外的内容。"
        )
        repair_params = dict(params)
        repair_params["messages"] = [
            *params["messages"],
            {"role": "assistant", "content": content},
            {"role": "user", "content": repair_instruction},
        ]
        print("\n   ↻ Provider output missed the summary contract; repairing once")
        repaired_content = _summarize_sync(client, repair_params)
        return validate_summary_quality(
            repaired_content,
            expected_items=expected_items,
            expected_article_ids=expected_article_ids,
            require_impact=True,
        )


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

    result = summarize_result(articles, stream=stream, deadline_at=deadline_at)
    return render_summary_markdown(result)


def _parse_summary_result(
    draft: SummaryDraft,
    articles: list[dict],
    *,
    policy: str,
    provider: str,
    model: str,
    input_fingerprint: str,
    prompt_fingerprint: str,
    attempts: tuple[SummaryAttempt, ...],
    selection_diagnostics: dict[str, Any],
) -> SummaryResult:
    """Join validated model output to private source provenance."""

    items: list[SummaryItem] = []
    articles_by_id = article_reference_map(articles)
    for item in draft.items:
        article_id = item.article_id.strip()
        article = articles_by_id.get(article_id)
        if article is None:
            raise SummaryQualityError(
                f"summary references unknown article_id {article_id}"
            )
        url = str(article.get("link") or "")
        items.append(
            SummaryItem(
                article_id=article_id,
                title=str(article.get("title") or "").replace("\n", " ").strip(),
                summary=item.summary.replace("\n", " ").strip(),
                url=url.strip(),
                why_it_matters=item.why_it_matters.replace("\n", " ").strip(),
                source_label=article_source_label(article),
                published_at=str(article.get("publish_time") or "").strip(),
                confidence=str(article.get("confidence") or "reported").strip(),
            )
        )

    return SummaryResult(
        policy=policy,
        items=tuple(items),
        discussion_topic=draft.discussion_topic.strip(),
        provider=provider,
        model=model,
        input_fingerprint=input_fingerprint,
        prompt_fingerprint=prompt_fingerprint,
        attempts=attempts,
        selection_policy=SUMMARY_SELECTION_POLICY,
        candidate_article_ids=tuple(
            article_reference_id(article, index)
            for index, article in enumerate(articles, 1)
        ),
        selection_diagnostics=selection_diagnostics,
        presentation="fact_impact_v1",
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
            presentation="fact_impact_v1",
        )

    cfg = get_config()
    providers = _provider_candidates()
    if not providers:
        raise ValueError(
            "No LLM provider API key found. Set MODELSCOPE_API_KEY or SILICONFLOW_API_KEY."
        )
    selection = select_summary_candidates_with_diagnostics(
        articles, _summary_limit(cfg)
    )
    selected_articles = list(selection.articles)
    compressed = compress_articles(selected_articles)
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
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
                # A JSON response must be complete before strict local parsing;
                # do not expose internal article IDs in streamed console output.
                "stream": False,
            }
            if provider["name"].startswith("ModelScope"):
                params.update(modelscope_request_options(provider["model"]))
            content = _summarize_sync(client, params)
            draft = _validate_summary_with_one_repair(
                client,
                params,
                content,
                expected_items=_summary_limit(cfg),
                expected_article_ids=tuple(
                    article["article_id"] for article in compressed
                ),
            )
            attempts.append(
                SummaryAttempt(
                    provider=provider["name"],
                    model=provider["model"],
                    status="ok",
                )
            )
            result = _parse_summary_result(
                draft,
                selected_articles,
                policy="required_ai",
                provider=provider["name"],
                model=provider["model"],
                input_fingerprint=input_fingerprint,
                prompt_fingerprint=prompt_fingerprint,
                attempts=tuple(attempts),
                selection_diagnostics=selection.diagnostics,
            )
            validate_summary_result(result, articles, max_items=_summary_limit(cfg))
            print(
                f"\n   ✅ {provider['name']} succeeded: "
                f"model={provider['model']} items={len(result.items)}"
            )
            return result
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
    if not response.choices:
        raise SummaryQualityError("provider returned an empty choices list")
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise SummaryQualityError("provider returned empty message content")
    return content


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
    """Offline fallback rendered with the same private-provenance policy."""
    if not articles:
        return "暂无新闻"
    return render_summary_markdown(offline_summary_result(articles, limit=limit))


def offline_summary_result(articles: list[dict], limit: int = 10):
    """Create a structured deterministic offline summary for replayable runs."""
    from utils.summary_contracts import (
        SummaryAttempt,
        SummaryItem,
        SummaryResult,
        fingerprint_summary_input,
    )

    selection = select_summary_candidates_with_diagnostics(articles, max(0, limit))
    selected = list(selection.articles)
    limit = len(selected)
    input_fingerprint, prompt_fingerprint = fingerprint_summary_input(
        selected, "offline"
    )
    items = tuple(
        SummaryItem(
            article_id=article_reference_id(article, index),
            title=(article.get("title") or "").replace("\n", "").strip(),
            summary=_offline_summary_text(article),
            url=article.get("link") or "",
            source_label=article_source_label(article),
            published_at=str(article.get("publish_time") or "").strip(),
            confidence=str(article.get("confidence") or "reported").strip(),
        )
        for index, article in enumerate(selected, 1)
    )
    result = SummaryResult(
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
        selection_policy=SUMMARY_SELECTION_POLICY,
        candidate_article_ids=tuple(
            article_reference_id(article, index)
            for index, article in enumerate(selected, 1)
        ),
        selection_diagnostics=selection.diagnostics,
    )
    validate_summary_result(result, articles, max_items=max(1, limit))
    return result


def test_connection() -> bool:
    """Test API connection (primary first, then fallback)."""
    providers = _provider_candidates()

    if not providers:
        print("❌ 未找到可用 API Key（MODELSCOPE_API_KEY / SILICONFLOW_API_KEY）")
        return False

    for provider in providers:
        try:
            client = create_client(provider["base_url"], provider["api_key"])
            params: dict[str, Any] = {
                "model": provider["model"],
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "你好，请用一句话介绍自己。"},
                ],
                "max_tokens": 64,
                "temperature": 0.2,
                "stream": False,
            }
            if provider["name"].startswith("ModelScope"):
                params.update(modelscope_request_options(provider["model"]))
            content = _summarize_sync(client, params)
            print("✅ API 连接成功！")
            print(f"   供应商: {provider['name']}")
            print(f"   模型: {provider['model']}")
            print(f"   非空正文长度: {len(content)}")
            return True
        except Exception as exc:
            message = str(exc)
            if provider["api_key"]:
                message = message.replace(provider["api_key"], "***")
            print(f"⚠️  {provider['name']} 连接失败: {message}")

    print("❌ 所有供应商连接失败")
    return False


if __name__ == "__main__":
    test_connection()
