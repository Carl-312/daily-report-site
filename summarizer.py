"""
LLM Summarizer using ModelScope API with secondary ModelScope and SiliconFlow fallback.
Summarizes news articles into daily reports.
"""

from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from time import monotonic, sleep
from typing import Any
from openai import OpenAI
from config import LLMExecutionPolicy, LLMModelCapability, LLMSettings, get_config
from utils.llm_compat import (
    CompletionResult,
    CompletionTelemetry,
    LLMCompatibilityError,
    classify_exception,
    endpoint_label,
    extract_single_json_object,
    request_chat_completion,
    request_streaming_chat_completion,
)
from utils.llm_execution import (
    ExecutionBudgetExceeded,
    bounded_attempt_timeout,
    bounded_provider_deadline,
    effective_execution_policy,
    evaluate_retry,
)
from utils.run_contracts import RunDeadlineExceeded
from utils.summary_contracts import (
    SUMMARY_MAX_VISIBLE_CHARS,
    SUMMARY_MIN_VISIBLE_CHARS,
    SUMMARY_TARGET_MIN_VISIBLE_CHARS,
    SUMMARY_TARGET_MAX_VISIBLE_CHARS,
    SummaryAttempt,
    SummaryAttemptsArtifact,
    SummaryDraft,
    SummaryDraftItem,
    SummaryItem,
    SummaryResult,
    SummaryValidationIssue,
    article_id_for_index,
    fingerprint_summary_input,
    reader_summary_issues,
    render_summary_markdown,
    summary_visible_character_count,
    validate_summary_result,
)


class SummaryContractError(LLMCompatibilityError):
    """Raised when final text cannot satisfy the model-facing JSON contract."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "contract_shape",
        issues: tuple[SummaryValidationIssue, ...] = (),
    ) -> None:
        super().__init__(message, stage="contract", code=code)
        self.issues = issues


class SummaryProvenanceError(LLMCompatibilityError):
    """Raised when model output cannot be joined to local source provenance."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "unknown_article_id",
        issues: tuple[SummaryValidationIssue, ...] = (),
    ) -> None:
        super().__init__(message, stage="provenance", code=code)
        self.issues = issues


class SummaryQualityError(LLMCompatibilityError):
    """Raised when an LLM response is not a usable Chinese daily summary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "quality_invalid",
        issues: tuple[SummaryValidationIssue, ...] = (),
    ) -> None:
        super().__init__(message, stage="quality", code=code)
        self.issues = issues


class AllProvidersFailed(RuntimeError):
    """Raised with structured attempts after every configured provider failed."""

    def __init__(self, attempts: tuple[SummaryAttempt, ...]) -> None:
        self.attempts = attempts
        summary = " | ".join(
            f"{attempt.provider}[{attempt.model}]={attempt.failure_code}"
            for attempt in attempts
        )
        if not summary:
            summary = "no executable provider candidates"
        super().__init__(f"All LLM providers failed. {summary}")


@dataclass(frozen=True, slots=True)
class ValidatedSummaryDraft:
    draft: SummaryDraft
    diagnostics: tuple[str, ...] = ()


def resolve_model_capability(
    cfg: Any, provider: str, base_url: str, model: str
) -> LLMModelCapability:
    """Resolve endpoint-scoped capability data without consulting model names."""

    llm_settings = getattr(cfg, "llm", None)
    if not isinstance(llm_settings, LLMSettings):
        llm_settings = LLMSettings()
    return llm_settings.capability_for(provider, base_url, model)


def model_request_options(capability: LLMModelCapability) -> dict[str, Any]:
    """Build only request features explicitly verified for this capability."""

    options: dict[str, Any] = {}
    if capability.thinking_control_parameter:
        options["extra_body"] = {
            capability.thinking_control_parameter: capability.thinking_control_value
        }
    if capability.request_mode == "json_object":
        options["response_format"] = {"type": "json_object"}
    elif capability.request_mode == "json_schema":
        options["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "daily_summary",
                "strict": True,
                "schema": _SUMMARY_RESPONSE_SCHEMA,
            },
        }
    return options


def modelscope_request_options(
    model: str, capability: LLMModelCapability | None = None
) -> dict[str, Any]:
    """Compatibility wrapper; model names alone no longer enable features."""

    del model
    return model_request_options(capability) if capability is not None else {}


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
        compressed.append(
            {
                "article_id": article_id_for_index(index),
                "title": (a.get("title") or "")[: cfg.title_max],
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


_PUBLIC_LINK = re.compile(r"(?:https?://|www\.)|\[[^\]]+\]\([^)]*\)", re.IGNORECASE)
_PUBLIC_ARTICLE_ID = re.compile(r"\[a\d+\]", re.IGNORECASE)
_SOURCE_SENTENCE = re.compile(r"[^。！？]+[。！？]")
_TITLE_SEPARATOR = re.compile(r"[:：]")
_COMPACT_HEADLINE_REWRITES = (
    ("能力飞跃", "能力显著跃迁"),
    ("引争议", "引发业界争议"),
)
_DEFAULT_DISCUSSION_TOPIC = "你最关注哪条AI新闻？"
_SUMMARY_ROOT_FIELDS = frozenset({"items", "discussion_topic"})
_SUMMARY_ITEM_FIELDS = frozenset({"article_id", "title", "summary"})
_COMPLETE_JSON_FENCE = re.compile(
    r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE
)
_SUMMARY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["article_id", "summary"],
                "additionalProperties": False,
            },
        },
        "discussion_topic": {"type": "string"},
    },
    "required": ["items", "discussion_topic"],
    "additionalProperties": False,
}


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
        # A complete, source-faithful 51–80-character sentence is preferable
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


def _parse_summary_draft_with_diagnostics(
    content: str, *, compatible_contract: bool = True
) -> ValidatedSummaryDraft:
    """Allowlist model fields while retaining non-sensitive drift diagnostics."""

    payload = _extract_summary_object(content, compatible_contract=compatible_contract)

    issues: list[SummaryValidationIssue] = []
    diagnostics: list[str] = []
    for field_name in sorted(set(payload) - _SUMMARY_ROOT_FIELDS):
        if compatible_contract:
            diagnostics.append(f"ignored_field:{field_name}")
        else:
            issues.append(
                SummaryValidationIssue(
                    stage="contract",
                    code="contract_shape",
                    message=f"unknown root field {field_name}",
                )
            )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        issues.append(
            SummaryValidationIssue(
                stage="contract",
                code="contract_shape",
                message="items must be an array",
            )
        )
        raw_items = []

    items: list[SummaryDraftItem] = []
    for index, raw_item in enumerate(raw_items, 1):
        if not isinstance(raw_item, dict):
            issues.append(
                SummaryValidationIssue(
                    stage="contract",
                    code="contract_shape",
                    message="item must be an object",
                    item_index=index,
                )
            )
            continue
        for field_name in sorted(set(raw_item) - _SUMMARY_ITEM_FIELDS):
            if compatible_contract:
                diagnostics.append(f"ignored_field:items[{index}].{field_name}")
            else:
                issues.append(
                    SummaryValidationIssue(
                        stage="contract",
                        code="contract_shape",
                        message=f"unknown item field {field_name}",
                        item_index=index,
                    )
                )
        article_id = raw_item.get("article_id")
        summary = raw_item.get("summary")
        title = raw_item.get("title", "")
        if not isinstance(article_id, str) or not article_id.strip():
            issues.append(
                SummaryValidationIssue(
                    stage="contract",
                    code="contract_shape",
                    message="article_id must be a non-empty string",
                    item_index=index,
                )
            )
        if not isinstance(summary, str) or not summary.strip():
            issues.append(
                SummaryValidationIssue(
                    stage="contract",
                    code="contract_shape",
                    message="summary must be a non-empty string",
                    item_index=index,
                )
            )
        if not isinstance(title, str):
            title = ""
            if compatible_contract:
                diagnostics.append(f"ignored_non_string_title:items[{index}]")
        if not compatible_contract and not title.strip():
            issues.append(
                SummaryValidationIssue(
                    stage="contract",
                    code="contract_shape",
                    message="title must be a non-empty string in legacy mode",
                    item_index=index,
                )
            )
        if (
            isinstance(article_id, str)
            and article_id.strip()
            and isinstance(summary, str)
            and summary.strip()
        ):
            items.append(
                SummaryDraftItem(
                    article_id=article_id.strip(),
                    title=title.strip(),
                    summary=summary.strip(),
                )
            )

    discussion_topic = payload.get("discussion_topic")
    if discussion_topic is None or (
        isinstance(discussion_topic, str) and not discussion_topic.strip()
    ):
        if compatible_contract:
            discussion_topic = _DEFAULT_DISCUSSION_TOPIC
            diagnostics.append("discussion_topic_defaulted")
        else:
            discussion_topic = ""
            issues.append(
                SummaryValidationIssue(
                    stage="contract",
                    code="contract_shape",
                    message="discussion_topic must be a non-empty string",
                )
            )
    elif not isinstance(discussion_topic, str):
        issues.append(
            SummaryValidationIssue(
                stage="contract",
                code="contract_shape",
                message="discussion_topic must be a string",
            )
        )

    if issues:
        raise SummaryContractError(
            "; ".join(issue.message for issue in issues),
            code=issues[0].code,
            issues=tuple(issues),
        )
    return ValidatedSummaryDraft(
        draft=SummaryDraft(
            items=tuple(items), discussion_topic=str(discussion_topic).strip()
        ),
        diagnostics=tuple(diagnostics),
    )


def _extract_summary_object(
    content: str, *, compatible_contract: bool
) -> dict[str, Any]:
    try:
        if compatible_contract:
            return extract_single_json_object(content)
        stripped = content.strip()
        fence = _COMPLETE_JSON_FENCE.fullmatch(stripped)
        payload = json.loads(fence.group(1).strip() if fence else stripped)
        if not isinstance(payload, dict):
            raise LLMCompatibilityError(
                "summary JSON root must be an object",
                stage="contract",
                code="contract_shape",
            )
        return payload
    except (json.JSONDecodeError, LLMCompatibilityError) as exc:
        code = getattr(exc, "code", "contract_invalid_json")
        raise SummaryContractError(
            "summary is not valid JSON matching the contract", code=code
        ) from exc


def _parse_summary_draft(
    content: str, *, compatible_contract: bool = True
) -> SummaryDraft:
    return _parse_summary_draft_with_diagnostics(
        content, compatible_contract=compatible_contract
    ).draft


def validate_summary_provenance(
    draft: SummaryDraft, expected_article_ids: set[str] | None
) -> None:
    """Validate model IDs independently from JSON and editorial quality."""

    if expected_article_ids is None:
        return
    issues = tuple(
        SummaryValidationIssue(
            stage="provenance",
            code="unknown_article_id",
            message=f"item references unknown article_id {item.article_id}",
            item_index=index,
        )
        for index, item in enumerate(draft.items, 1)
        if item.article_id not in expected_article_ids
    )
    if issues:
        raise SummaryProvenanceError(
            "; ".join(issue.message for issue in issues),
            code="unknown_article_id",
            issues=issues,
        )


def evaluate_editorial_quality(
    draft: SummaryDraft,
    *,
    expected_items: int,
    source_count: int | None = None,
    compatible_contract: bool = True,
) -> tuple[SummaryValidationIssue, ...]:
    """Return all current-gate and shadow editorial issues for one draft."""

    issues: list[SummaryValidationIssue] = []
    max_items = max(0, expected_items)
    if max_items == 0:
        issues.append(
            SummaryValidationIssue(
                stage="contract",
                code="contract_shape",
                message="cannot publish a summary without source articles",
            )
        )
    if not draft.items:
        issues.append(
            SummaryValidationIssue(
                stage="contract",
                code="contract_shape",
                message="summary must contain at least one item when sources exist",
            )
        )
    if len(draft.items) > max_items:
        issues.append(
            SummaryValidationIssue(
                stage="contract",
                code="contract_shape",
                message=(
                    f"summary has {len(draft.items)} items, maximum allowed is "
                    f"{max_items}"
                ),
            )
        )

    discussion_topic = draft.discussion_topic.strip()
    if _contains_public_link(discussion_topic):
        issues.append(
            SummaryValidationIssue(
                stage="quality",
                code="quality_public_safety",
                message="interaction topic contains a link",
            )
        )
    if _contains_public_article_id(discussion_topic):
        issues.append(
            SummaryValidationIssue(
                stage="quality",
                code="quality_public_safety",
                message="interaction topic exposes an article_id",
            )
        )

    visible_text = "\n".join(
        item.summary if compatible_contract else f"{item.title} {item.summary}"
        for item in draft.items
    )
    searchable_chars = re.findall(r"[\u4e00-\u9fffA-Za-z]", visible_text)
    chinese_ratio = _count_cjk(visible_text) / max(1, len(searchable_chars))
    if chinese_ratio < 0.45:
        issues.append(
            SummaryValidationIssue(
                stage="quality",
                code="quality_chinese",
                message=(
                    "reader-visible summaries are not predominantly Chinese "
                    f"(ratio={chinese_ratio:.2f})"
                ),
            )
        )

    normalized_summaries: list[str] = []
    for index, item in enumerate(draft.items, 1):
        summary = item.summary.strip()
        chinese_text = summary if compatible_contract else f"{item.title}{summary}"
        if _count_cjk(chinese_text) < 8:
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_chinese",
                    message="item does not contain enough Chinese content",
                    item_index=index,
                )
            )
        if _contains_public_link(summary):
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_public_safety",
                    message="item contains a link",
                    item_index=index,
                )
            )
        if _contains_public_article_id(summary):
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_public_safety",
                    message="item exposes an article_id",
                    item_index=index,
                )
            )
        if not compatible_contract and _contains_public_link(item.title):
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_public_safety",
                    message="item title contains a link",
                    item_index=index,
                )
            )
        if not compatible_contract and _contains_public_article_id(item.title):
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_public_safety",
                    message="item title exposes an article_id",
                    item_index=index,
                )
            )
        for message in reader_summary_issues(summary):
            code = (
                "quality_length"
                if "visible characters" in message
                else "quality_sentence"
            )
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code=code,
                    message=f"item summary {message}",
                    item_index=index,
                )
            )
        normalized_summaries.append(
            re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", summary).lower()
        )

    for index, normalized in enumerate(normalized_summaries):
        if not normalized:
            continue
        if normalized in normalized_summaries[:index]:
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_duplicate",
                    message="item exactly duplicates an earlier summary",
                    item_index=index + 1,
                    blocking=False,
                )
            )
            continue
        if any(
            SequenceMatcher(None, normalized, earlier).ratio() >= 0.92
            for earlier in normalized_summaries[:index]
            if earlier
        ):
            issues.append(
                SummaryValidationIssue(
                    stage="quality",
                    code="quality_near_duplicate",
                    message="item closely resembles an earlier summary",
                    item_index=index + 1,
                    blocking=False,
                )
            )

    if (source_count or 0) >= 10 and max_items >= 7 and len(draft.items) < 7:
        issues.append(
            SummaryValidationIssue(
                stage="quality",
                code="quality_item_coverage",
                message="fewer than seven items were returned for a large candidate set",
                blocking=False,
            )
        )
    return tuple(issues)


def _validate_summary_payload(
    content: str,
    *,
    expected_items: int,
    expected_article_ids: set[str] | None,
    compatible_contract: bool = True,
) -> ValidatedSummaryDraft:
    parsed = _parse_summary_draft_with_diagnostics(
        content, compatible_contract=compatible_contract
    )
    issues = evaluate_editorial_quality(
        parsed.draft,
        expected_items=expected_items,
        source_count=len(expected_article_ids)
        if expected_article_ids is not None
        else None,
        compatible_contract=compatible_contract,
    )
    contract_issues = tuple(
        issue for issue in issues if issue.stage == "contract" and issue.blocking
    )
    if contract_issues:
        raise SummaryContractError(
            "; ".join(issue.message for issue in contract_issues),
            code=contract_issues[0].code,
            issues=contract_issues,
        )
    validate_summary_provenance(parsed.draft, expected_article_ids)
    quality_issues = tuple(
        issue for issue in issues if issue.stage == "quality" and issue.blocking
    )
    if quality_issues:
        raise SummaryQualityError(
            "; ".join(issue.message for issue in quality_issues),
            code=quality_issues[0].code,
            issues=quality_issues,
        )
    shadow_diagnostics = tuple(
        _issue_diagnostic(issue) for issue in issues if not issue.blocking
    )
    return ValidatedSummaryDraft(
        draft=parsed.draft,
        diagnostics=parsed.diagnostics + shadow_diagnostics,
    )


def _issue_diagnostic(issue: SummaryValidationIssue) -> str:
    """Render issue metadata without copying model response text."""

    diagnostic = f"{issue.code}:item={issue.item_index or 0}"
    if issue.code == "quality_length":
        match = re.search(r"has (\d+) visible characters", issue.message)
        if match:
            diagnostic += f":visible={match.group(1)}"
    elif issue.code == "quality_chinese":
        match = re.search(r"ratio=([0-9.]+)", issue.message)
        if match:
            diagnostic += f":ratio={match.group(1)}"
    return diagnostic


def validate_summary_quality(
    content: str,
    expected_items: int = 10,
    expected_article_ids: set[str] | None = None,
    *,
    compatible_contract: bool = True,
) -> SummaryDraft:
    """Apply contract, provenance, and current publication gates in order."""

    return _validate_summary_payload(
        content,
        expected_items=expected_items,
        expected_article_ids=expected_article_ids,
        compatible_contract=compatible_contract,
    ).draft


def _provider_candidates() -> list[dict[str, Any]]:
    """Build provider candidates in priority order."""
    cfg = get_config()
    providers: list[dict[str, Any]] = []

    def append_provider(
        provider_id: str, name: str, base_url: str, api_key: str, model: str
    ) -> None:
        if not api_key or not model:
            return
        candidate = {
            "provider_id": provider_id,
            "name": name,
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "capability": resolve_model_capability(cfg, provider_id, base_url, model),
        }
        if any(
            provider["base_url"] == base_url and provider["model"] == model
            for provider in providers
        ):
            return
        providers.append(candidate)

    if cfg.api_key:
        append_provider(
            "modelscope",
            "ModelScope",
            cfg.api_base_url,
            cfg.api_key,
            cfg.model,
        )
        append_provider(
            "modelscope",
            "ModelScope secondary",
            cfg.api_base_url,
            cfg.api_key,
            cfg.modelscope_secondary_model,
        )

    if cfg.fallback_api_key:
        append_provider(
            "siliconflow",
            "SiliconFlow",
            cfg.fallback_api_base_url,
            cfg.fallback_api_key,
            cfg.fallback_model,
        )

    return providers


def summarize(
    articles: list[dict],
    deadline_at=None,
) -> str:
    """
    Summarize articles using LLM with provider fallback.

    Args:
        articles: List of article dicts

    Returns:
        Summarized markdown content
    """
    if not articles:
        return "暂无新闻"

    result = summarize_result(articles, deadline_at=deadline_at)
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
) -> SummaryResult:
    """Join validated model output to private source provenance."""

    items: list[SummaryItem] = []
    articles_by_id = {
        article_id_for_index(index): article
        for index, article in enumerate(articles, 1)
    }
    for item in draft.items:
        article_id = item.article_id.strip()
        article = articles_by_id.get(article_id)
        if article is None:
            raise SummaryProvenanceError(
                f"summary references unknown article_id {article_id}",
                code="unknown_article_id",
            )
        url = str(article.get("link") or "")
        items.append(
            SummaryItem(
                article_id=article_id,
                # The model-facing title is diagnostic only.  Bind private
                # source metadata locally so an English or omitted model title
                # cannot affect reader quality or provenance.
                title=str(article.get("title") or "").replace("\n", " ").strip(),
                summary=item.summary.replace("\n", " ").strip(),
                url=url.strip(),
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
        validation_passed=True,
    )


def summarize_result(
    articles: list[dict],
    *,
    deadline_at=None,
    attempt_artifact_path: str | Path | None = None,
    provider_candidates: list[dict[str, Any]] | None = None,
    prompt_path: str | Path | None = None,
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
            validation_passed=True,
        )

    cfg = get_config()
    providers = (
        provider_candidates
        if provider_candidates is not None
        else _provider_candidates()
    )
    if not providers:
        raise ValueError(
            "No LLM provider API key found. Set MODELSCOPE_API_KEY or SILICONFLOW_API_KEY."
        )
    compressed = compress_articles(articles)
    system_prompt = (
        load_prompt(str(prompt_path)) if prompt_path is not None else load_prompt()
    )
    input_fingerprint, prompt_fingerprint = fingerprint_summary_input(
        compressed, system_prompt
    )
    user_input = json.dumps({"articles": compressed}, ensure_ascii=False, indent=2)
    attempts: list[SummaryAttempt] = []

    for provider_index, provider in enumerate(providers):
        capability = provider.get("capability")
        if not isinstance(capability, LLMModelCapability):
            capability = resolve_model_capability(
                cfg,
                str(provider.get("provider_id") or provider["name"]),
                provider["base_url"],
                provider["model"],
            )
        execution = effective_execution_policy(
            capability.execution,
            default_max_output_tokens=int(getattr(cfg, "max_output", 2000)),
            default_attempt_timeout_seconds=float(
                getattr(getattr(cfg, "llm", None), "default_timeout_seconds", 180)
            ),
        )
        provider_started_at = datetime.now(timezone.utc)
        provider_deadline = bounded_provider_deadline(
            execution, deadline_at, now=provider_started_at
        )

        if not capability.supports_chat_completions:
            _persist_summary_attempts(
                attempt_artifact_path,
                attempts,
                input_fingerprint=input_fingerprint,
                prompt_fingerprint=prompt_fingerprint,
            )
            continue

        retry_of_sequence: int | None = None
        for provider_attempt_number in range(1, execution.max_attempts + 1):
            attempt_started_at = datetime.now(timezone.utc)
            try:
                timeout = bounded_attempt_timeout(
                    execution,
                    provider_deadline=provider_deadline,
                    run_deadline=deadline_at,
                    now=attempt_started_at,
                )
            except ExecutionBudgetExceeded as exc:
                if attempts and attempts[-1].retry_decision == "retry_scheduled":
                    attempts[-1] = attempts[-1].model_copy(
                        update={
                            "retry_decision": (
                                "run_deadline_exhausted"
                                if exc.scope == "run"
                                else "provider_budget_exhausted"
                            )
                        }
                    )
                    _persist_summary_attempts(
                        attempt_artifact_path,
                        attempts,
                        input_fingerprint=input_fingerprint,
                        prompt_fingerprint=prompt_fingerprint,
                    )
                if exc.scope == "run":
                    raise RunDeadlineExceeded(
                        "run deadline exceeded before summary attempt"
                    ) from exc
                break

            sequence = len(attempts) + 1
            started_clock = monotonic()
            completion: CompletionResult | None = None
            try:
                client = create_client(
                    provider["base_url"], provider["api_key"], timeout=timeout
                )
                params: dict[str, Any] = {
                    "model": provider["model"],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_input},
                    ],
                    # Publication still requires one complete, private JSON response.
                    "stream": execution.delivery_mode == "buffered_stream",
                }
                params[capability.max_tokens_parameter] = execution.max_output_tokens
                if capability.supports_temperature:
                    params["temperature"] = 0.2
                params.update(model_request_options(capability))
                request_completion = (
                    _request_buffered_stream_completion
                    if execution.delivery_mode == "buffered_stream"
                    else _request_non_stream_completion
                )
                completion = _coerce_completion_result(
                    request_completion(client, params)
                )
                validated = _validate_summary_payload(
                    completion.content,
                    expected_items=_summary_limit(cfg),
                    expected_article_ids={
                        article["article_id"] for article in compressed
                    },
                    compatible_contract=getattr(
                        getattr(cfg, "llm", None),
                        "compatible_output_contract",
                        True,
                    ),
                )
                elapsed_ms = max(0, round((monotonic() - started_clock) * 1000))
                successful_attempt = _summary_attempt(
                    provider,
                    capability,
                    execution=execution,
                    sequence=sequence,
                    provider_attempt_number=provider_attempt_number,
                    retry_of_sequence=retry_of_sequence,
                    retry_decision="selected",
                    attempt_timeout_seconds=timeout,
                    provider_deadline_at=provider_deadline,
                    run_deadline_at=deadline_at,
                    started_at=attempt_started_at,
                    elapsed_ms=elapsed_ms,
                    status="ok",
                    telemetry=completion.telemetry,
                    diagnostics=validated.diagnostics,
                )
                result = _parse_summary_result(
                    validated.draft,
                    articles,
                    policy="required_ai",
                    provider=provider["name"],
                    model=provider["model"],
                    input_fingerprint=input_fingerprint,
                    prompt_fingerprint=prompt_fingerprint,
                    attempts=tuple(attempts + [successful_attempt]),
                )
                try:
                    validate_summary_result(
                        result, articles, max_items=_summary_limit(cfg)
                    )
                except ValueError as exc:
                    raise SummaryProvenanceError(
                        "local source binding failed after model validation",
                        code="source_url_mismatch",
                    ) from exc
                attempts.append(successful_attempt)
                _persist_summary_attempts(
                    attempt_artifact_path,
                    attempts,
                    input_fingerprint=input_fingerprint,
                    prompt_fingerprint=prompt_fingerprint,
                    publishable=True,
                    selected_provider=provider["name"],
                    selected_model=provider["model"],
                    selected_attempt_sequence=sequence,
                )
                print(
                    f"\n   ✅ {provider['name']} succeeded: "
                    f"model={provider['model']} items={len(result.items)}"
                )
                return result
            except RunDeadlineExceeded:
                raise
            except Exception as exc:
                classification = classify_exception(exc)
                telemetry = (
                    completion.telemetry
                    if completion
                    else getattr(exc, "telemetry", None)
                )
                issue_diagnostics = tuple(
                    _issue_diagnostic(issue) for issue in getattr(exc, "issues", ())
                )
                failed_attempt = _summary_attempt(
                    provider,
                    capability,
                    execution=execution,
                    sequence=sequence,
                    provider_attempt_number=provider_attempt_number,
                    retry_of_sequence=retry_of_sequence,
                    retry_decision="not_evaluated",
                    attempt_timeout_seconds=timeout,
                    provider_deadline_at=provider_deadline,
                    run_deadline_at=deadline_at,
                    started_at=attempt_started_at,
                    elapsed_ms=max(0, round((monotonic() - started_clock) * 1000)),
                    status="failed",
                    telemetry=telemetry,
                    classification_stage=classification.stage,
                    classification_code=classification.code,
                    retryable=classification.retryable,
                    diagnostics=issue_diagnostics,
                )
                attempts.append(failed_attempt)
                # Persist the completed HTTP attempt before evaluating or waiting
                # on a retry, so an interrupted process retains the first failure.
                _persist_summary_attempts(
                    attempt_artifact_path,
                    attempts,
                    input_fingerprint=input_fingerprint,
                    prompt_fingerprint=prompt_fingerprint,
                )

                decision = evaluate_retry(
                    classification.code,
                    classification.retryable,
                    provider_attempt_number,
                    execution,
                    provider_deadline=provider_deadline,
                    run_deadline=deadline_at,
                    retry_after_seconds=classification.retry_after_seconds,
                )
                attempts[-1] = failed_attempt.model_copy(
                    update={"retry_decision": decision.reason}
                )
                _persist_summary_attempts(
                    attempt_artifact_path,
                    attempts,
                    input_fingerprint=input_fingerprint,
                    prompt_fingerprint=prompt_fingerprint,
                )
                if not decision.retry:
                    break
                retry_of_sequence = sequence
                if decision.backoff_seconds:
                    sleep(decision.backoff_seconds)

        if provider_index + 1 < len(providers) and attempts:
            last_attempt = attempts[-1]
            print(
                f"\n   ⚠️  {provider['name']} failed: "
                f"stage={last_attempt.failure_stage} code={last_attempt.failure_code}"
            )

    raise AllProvidersFailed(tuple(attempts))


def _summary_attempt(
    provider: dict[str, Any],
    capability: LLMModelCapability,
    *,
    execution: LLMExecutionPolicy,
    sequence: int,
    provider_attempt_number: int,
    retry_of_sequence: int | None,
    retry_decision: str,
    attempt_timeout_seconds: float | None,
    provider_deadline_at,
    run_deadline_at,
    started_at: datetime,
    elapsed_ms: int,
    status: str,
    telemetry: CompletionTelemetry | None = None,
    classification_stage: str | None = None,
    classification_code: str | None = None,
    retryable: bool = False,
    diagnostics: tuple[str, ...] = (),
) -> SummaryAttempt:
    telemetry = telemetry or CompletionTelemetry()
    provider_accepted = telemetry.transport_status == "completed" and (
        telemetry.http_status is None or 200 <= telemetry.http_status < 300
    )
    contract_valid = status == "ok" or classification_stage in {
        "provenance",
        "quality",
    }
    provenance_valid = status == "ok" or classification_stage == "quality"
    return SummaryAttempt(
        provider=provider["name"],
        model=provider["model"],
        status=status,
        sequence=sequence,
        provider_attempt_number=provider_attempt_number,
        provider_max_attempts=execution.max_attempts,
        retry_of_sequence=retry_of_sequence,
        retry_decision=retry_decision,
        endpoint_label=endpoint_label(provider["base_url"]),
        request_mode=capability.request_mode,
        delivery_mode=execution.delivery_mode,
        attempt_timeout_seconds=attempt_timeout_seconds,
        provider_budget_seconds=execution.provider_budget_seconds,
        provider_deadline_at=provider_deadline_at,
        run_deadline_at=run_deadline_at,
        max_output_tokens=execution.max_output_tokens,
        started_at=started_at,
        elapsed_ms=elapsed_ms,
        transport_status=telemetry.transport_status,
        http_status=telemetry.http_status,
        request_id=telemetry.request_id,
        retry_after_seconds=telemetry.retry_after_seconds,
        failure_stage=classification_stage,
        failure_code=classification_code,
        retryable=retryable,
        choices_count=telemetry.choices_count,
        content_type=telemetry.content_type,
        content_length=telemetry.content_length,
        reasoning_length=telemetry.reasoning_length,
        finish_reason=telemetry.finish_reason,
        prompt_tokens=telemetry.prompt_tokens,
        completion_tokens=telemetry.completion_tokens,
        reasoning_tokens=telemetry.reasoning_tokens,
        total_tokens=telemetry.total_tokens,
        response_sha256=telemetry.response_sha256,
        provider_accepted=provider_accepted,
        final_text_received=telemetry.final_text_received,
        contract_valid=contract_valid,
        provenance_valid=provenance_valid,
        quality_valid=status == "ok",
        publishable=status == "ok",
        diagnostics=tuple(telemetry.diagnostics) + diagnostics,
    )


def _persist_summary_attempts(
    path: str | Path | None,
    attempts: list[SummaryAttempt],
    *,
    input_fingerprint: str,
    prompt_fingerprint: str,
    publishable: bool = False,
    selected_provider: str | None = None,
    selected_model: str | None = None,
    selected_attempt_sequence: int | None = None,
) -> Path | None:
    if path is None:
        return None
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    artifact = SummaryAttemptsArtifact(
        source_type="live",
        created_at=datetime.now(timezone.utc),
        real_api_attempted=any(
            attempt.transport_status != "not_started" for attempt in attempts
        ),
        input_fingerprint=input_fingerprint,
        prompt_fingerprint=prompt_fingerprint,
        attempts=tuple(attempts),
        publishable=publishable,
        selected_provider=selected_provider,
        selected_model=selected_model,
        selected_attempt_sequence=selected_attempt_sequence,
    )
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _coerce_completion_result(value: Any) -> CompletionResult:
    """Keep legacy test/provider adapters returning only a final string working."""

    if isinstance(value, CompletionResult):
        return value
    if isinstance(value, str):
        telemetry = CompletionTelemetry(
            transport_status="completed",
            http_status=200,
            content_length=len(value),
            final_text_received=bool(value.strip()),
        )
        return CompletionResult(content=value, telemetry=telemetry)
    raise LLMCompatibilityError(
        "completion adapter returned an unsupported value",
        stage="extraction",
        code="unsupported_content",
    )


def _request_non_stream_completion(client: OpenAI, params: dict) -> CompletionResult:
    """Collect one complete response with provider-neutral extraction."""

    params["stream"] = False
    return request_chat_completion(client, params)


def _request_buffered_stream_completion(
    client: OpenAI, params: dict
) -> CompletionResult:
    """Privately buffer an SSE response before contract validation."""

    params["stream"] = True
    return request_streaming_chat_completion(client, params)


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

    sorted_articles = sorted(articles, key=lambda x: x.get("priority", 0), reverse=True)
    limit = min(len(sorted_articles), max(0, limit))
    selected = sorted_articles[:limit]
    input_fingerprint, prompt_fingerprint = fingerprint_summary_input(
        selected, "offline"
    )
    items = tuple(
        SummaryItem(
            article_id=article_id_for_index(index),
            title=(article.get("title") or "").replace("\n", "").strip(),
            summary=_offline_summary_text(article),
            url=article.get("link") or "",
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
        validation_passed=True,
    )
    validate_summary_result(result, selected, max_items=limit or 1)
    return result


def test_connection() -> bool:
    """Test API connection (primary first, then fallback)."""
    providers = _provider_candidates()

    if not providers:
        print("❌ 未找到可用 API Key（MODELSCOPE_API_KEY / SILICONFLOW_API_KEY）")
        return False

    for provider in providers:
        capability = provider["capability"]
        try:
            cfg = get_config()
            execution = effective_execution_policy(
                capability.execution,
                default_max_output_tokens=int(getattr(cfg, "max_output", 2000)),
                default_attempt_timeout_seconds=float(
                    getattr(getattr(cfg, "llm", None), "default_timeout_seconds", 180)
                ),
            )
            client = create_client(
                provider["base_url"],
                provider["api_key"],
                timeout=execution.attempt_timeout_seconds,
            )
            params: dict[str, Any] = {
                "model": provider["model"],
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "你好，请用一句话介绍自己。"},
                ],
                "stream": False,
            }
            params[capability.max_tokens_parameter] = 64
            if capability.supports_temperature:
                params["temperature"] = 0.2
            params.update(model_request_options(capability))
            completion = _coerce_completion_result(
                _request_non_stream_completion(client, params)
            )
            print("✅ API 连接成功！")
            print(f"   供应商: {provider['name']}")
            print(f"   模型: {provider['model']}")
            print(f"   非空正文长度: {len(completion.content)}")
            return True
        except Exception as exc:
            classification = classify_exception(exc)
            print(
                f"⚠️  {provider['name']} 连接失败: "
                f"stage={classification.stage} code={classification.code}"
            )

    print("❌ 所有供应商连接失败")
    return False


if __name__ == "__main__":
    raise SystemExit(0 if test_connection() else 1)
