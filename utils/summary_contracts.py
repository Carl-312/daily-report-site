"""Structured, replayable daily-summary contracts and deterministic rendering."""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any, Literal

from pydantic import Field

from utils.run_contracts import StrictFrozenModel
from utils.summary_selection import (
    SUMMARY_SELECTION_POLICY,
    SUMMARY_SELECTION_POLICY_V1,
    article_id_for_index as article_id_for_index,
    article_reference_map,
    select_summary_candidates_v1,
    select_summary_candidates_with_diagnostics,
)


_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_ARTICLE_ID = re.compile(r"\[a\d+\]\s*", re.IGNORECASE)
_SUMMARY_COLON = re.compile(r"[:：]")
_SUMMARY_TRUNCATION = re.compile(r"(?:…|\.{3,})")
_VAGUE_REPORTING_ATTRIBUTION = re.compile(
    r"(?:"
    r"据(?:公开|媒体|外媒|多方|相关|最新)?报道|据悉|据称|"
    r"(?:有)?报道称|(?:有|市场|相关)?消息(?:称|显示|透露)|"
    r"消息人士(?:称|透露|表示)|"
    r"(?:知情|业内)人士(?:称|透露|表示)|"
    r"(?:外媒|媒体)(?:报道称|报道|称)|"
    r"传闻称|网传"
    r")"
)
_SUMMARY_SENTENCE_ENDINGS = frozenset("。！？")
_INTERNAL_TREND_SIGNAL = re.compile(
    r"(?:AGI\s*趋势|热度\s*\d|[↑↓]\s*\d|新上榜|"
    r"\btrend_(?:rank|heat|state|delta)\b)",
    re.IGNORECASE,
)
_INTERNAL_TREND_BADGE = re.compile(r"〔\s*AGI\s*趋势\s*#?\d+[^〕]*〕\s*", re.IGNORECASE)

# A reader-facing daily-news sentence normally needs enough room for its
# subject, action, and one useful qualifier. Prefer 35–60 visible characters,
# while the wider 30–80 hard range lets a small model preserve a complete fact
# without padding or clipping. Whitespace is not
# reader-visible and therefore does not count; all other Unicode characters
# (including punctuation and product names) do. Keep these values beside the
# shared result contract so online, offline, replay, and gray paths cannot
# silently diverge.
SUMMARY_MIN_VISIBLE_CHARS = 30
SUMMARY_TARGET_MIN_VISIBLE_CHARS = 35
SUMMARY_TARGET_MAX_VISIBLE_CHARS = 60
SUMMARY_MAX_VISIBLE_CHARS = 80
IMPACT_MIN_VISIBLE_CHARS = 15
IMPACT_MAX_VISIBLE_CHARS = 70


class SummaryItem(StrictFrozenModel):
    """One validated summary item with private source provenance."""

    article_id: str
    title: str
    summary: str
    url: str
    why_it_matters: str = ""
    source_label: str = ""
    published_at: str = ""
    confidence: str = ""


class SummaryDraftItem(StrictFrozenModel):
    """Model-facing item shape before source provenance is joined locally."""

    article_id: str
    # Accepted only for replay compatibility with older model responses.  New
    # prompts omit it, and trusted source titles are always joined locally.
    title: str = ""
    summary: str
    why_it_matters: str = ""


class SummaryDraft(StrictFrozenModel):
    """Minimal JSON contract required from an LLM daily-summary response."""

    items: tuple[SummaryDraftItem, ...]
    discussion_topic: str = "你最关注哪条AI新闻？"


class SummaryAttempt(StrictFrozenModel):
    provider: str
    model: str
    status: Literal["ok", "failed", "skipped"]
    error_kind: str | None = None


class SummaryResult(StrictFrozenModel):
    policy: Literal["required_ai", "allow_offline", "offline"]
    items: tuple[SummaryItem, ...]
    discussion_topic: str
    provider: str
    model: str
    input_fingerprint: str
    prompt_fingerprint: str
    attempts: tuple[SummaryAttempt, ...] = ()
    selection_policy: Literal["legacy", "source_balanced_v1", "source_balanced_v2"] = (
        "legacy"
    )
    candidate_article_ids: tuple[str, ...] = ()
    selection_diagnostics: dict[str, Any] = Field(default_factory=dict)
    validation_passed: bool = True
    presentation: Literal["legacy", "fact_impact_v1"] = "legacy"


def summary_visible_character_count(value: str) -> int:
    """Count reader-visible characters for the per-item summary budget."""
    return sum(not character.isspace() for character in value)


def reader_summary_issues(value: str) -> tuple[str, ...]:
    """Describe violations of the one-sentence reader-facing summary contract."""

    normalized = " ".join(value.split())
    issues: list[str] = []
    visible_characters = summary_visible_character_count(normalized)
    if not normalized:
        issues.append("must not be empty")
        return tuple(issues)
    if visible_characters < SUMMARY_MIN_VISIBLE_CHARS:
        issues.append(
            f"has {visible_characters} visible characters; expected at least "
            f"{SUMMARY_MIN_VISIBLE_CHARS}"
        )
    if visible_characters > SUMMARY_MAX_VISIBLE_CHARS:
        issues.append(
            f"has {visible_characters} visible characters; maximum is "
            f"{SUMMARY_MAX_VISIBLE_CHARS}"
        )
    if _SUMMARY_COLON.search(normalized):
        issues.append("must not contain a colon")
    if _SUMMARY_TRUNCATION.search(normalized):
        issues.append("must not contain a truncation marker")
    if _VAGUE_REPORTING_ATTRIBUTION.search(normalized):
        issues.append("must not use a vague reporting attribution")
    if _INTERNAL_TREND_SIGNAL.search(normalized):
        issues.append("must not expose internal trend signals")
    if normalized[-1] not in _SUMMARY_SENTENCE_ENDINGS:
        issues.append("must end with a complete sentence ending")
    elif any(character in _SUMMARY_SENTENCE_ENDINGS for character in normalized[:-1]):
        issues.append("must contain exactly one reader sentence")
    return tuple(issues)


def impact_summary_issues(value: str) -> tuple[str, ...]:
    """Validate one concise consequence sentence separately from the news fact."""

    normalized = " ".join(value.split())
    if not normalized:
        return ("must not be empty",)
    issues: list[str] = []
    visible = summary_visible_character_count(normalized)
    if visible < IMPACT_MIN_VISIBLE_CHARS:
        issues.append(
            f"has {visible} visible characters; expected at least "
            f"{IMPACT_MIN_VISIBLE_CHARS}"
        )
    if visible > IMPACT_MAX_VISIBLE_CHARS:
        issues.append(
            f"has {visible} visible characters; maximum is {IMPACT_MAX_VISIBLE_CHARS}"
        )
    if _SUMMARY_TRUNCATION.search(normalized):
        issues.append("must not contain a truncation marker")
    if normalized[-1] not in _SUMMARY_SENTENCE_ENDINGS:
        issues.append("must end with a complete sentence ending")
    elif any(character in _SUMMARY_SENTENCE_ENDINGS for character in normalized[:-1]):
        issues.append("must contain exactly one reader sentence")
    return tuple(issues)


def validate_summary_result(
    result: SummaryResult, articles: list[dict], *, max_items: int = 10
) -> None:
    """Validate source provenance without limiting one source to one news item."""
    if max_items < 1:
        raise ValueError("max_items must be positive")
    if not articles and result.items:
        raise ValueError("summary cannot contain items without source articles")
    if articles and not result.items:
        raise ValueError("summary must contain at least one item when sources exist")
    if len(result.items) > max_items:
        raise ValueError(
            f"summary has {len(result.items)} items, maximum allowed is {max_items}"
        )

    expected_articles = article_reference_map(articles)
    if _INTERNAL_TREND_SIGNAL.search(result.discussion_topic):
        raise ValueError("summary discussion topic exposes internal trend signals")
    if result.selection_policy in {
        SUMMARY_SELECTION_POLICY_V1,
        SUMMARY_SELECTION_POLICY,
    }:
        if result.selection_policy == SUMMARY_SELECTION_POLICY_V1:
            expected_selection = select_summary_candidates_v1(articles, max_items)
            expected_diagnostics = None
        else:
            selection = select_summary_candidates_with_diagnostics(articles, max_items)
            expected_selection = list(selection.articles)
            expected_diagnostics = selection.diagnostics
        expected_candidate_ids = tuple(
            str(article["article_id"]) for article in expected_selection
        )
        if result.candidate_article_ids != expected_candidate_ids:
            raise ValueError("summary candidate selection does not match local policy")
        output_ids = tuple(item.article_id for item in result.items)
        if output_ids != result.candidate_article_ids:
            raise ValueError(
                "summary must cover every selected candidate exactly once and in order"
            )
        if (
            expected_diagnostics is not None
            and result.selection_diagnostics != expected_diagnostics
        ):
            raise ValueError("summary selection diagnostics do not match local policy")
    for item in result.items:
        if item.article_id not in expected_articles:
            raise ValueError(f"summary references unknown article_id {item.article_id}")

        article = expected_articles[item.article_id]
        expected_url = str(article.get("link") or "").strip()
        if item.url.strip() != expected_url:
            raise ValueError(
                f"summary article_id {item.article_id} has a mismatched source URL"
            )
        if not item.title.strip() or not item.summary.strip():
            raise ValueError(
                f"summary article_id {item.article_id} must have title and summary"
            )
        if issues := reader_summary_issues(item.summary):
            raise ValueError(
                f"summary article_id {item.article_id} " + "; ".join(issues)
            )
        if result.presentation == "fact_impact_v1" and not item.why_it_matters.strip():
            raise ValueError(
                f"summary article_id {item.article_id} is missing why_it_matters"
            )
        if item.why_it_matters and (
            issues := impact_summary_issues(item.why_it_matters)
        ):
            raise ValueError(
                f"summary article_id {item.article_id} impact " + "; ".join(issues)
            )


def fingerprint_summary_input(articles: list[dict], prompt: str) -> tuple[str, str]:
    """Create stable fingerprints for article input and prompt text."""
    canonical_articles = json.dumps(
        articles, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return (
        hashlib.sha256(canonical_articles).hexdigest(),
        hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


def render_summary_markdown(result: SummaryResult) -> str:
    """Render only the reader-facing Chinese fact and consequence sentences."""

    def public_text(value: str) -> str:
        without_trends = _INTERNAL_TREND_BADGE.sub("", value)
        without_ids = _ARTICLE_ID.sub("", without_trends)
        without_links = _MARKDOWN_LINK.sub(r"\1", without_ids)
        without_urls = _URL.sub("", without_links)
        compact = " ".join(without_urls.replace("\n", " ").split())
        return re.sub(r"\s+([，。！？；：])", r"\1", compact)

    lines: list[str] = []
    if not result.items:
        lines.append("今日没有达到证据门槛的主新闻。")
    for index, item in enumerate(result.items, 1):
        summary = public_text(item.summary).replace("：", "，").replace(":", "，")
        impact = public_text(item.why_it_matters)
        sentences = f"{summary}{impact}" if impact else summary
        lines.append(f"{index}. {sentences}")
    # A blank line is required here: without it, Markdown treats the topic as
    # part of the final numbered item and renders both inside one paragraph.
    lines.extend(
        ["", f"💬 互动话题：{html.escape(public_text(result.discussion_topic))}"]
    )
    return "\n".join(lines)
