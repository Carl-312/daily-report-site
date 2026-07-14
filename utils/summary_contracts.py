"""Structured, replayable daily-summary contracts and deterministic rendering."""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Literal

from utils.run_contracts import StrictFrozenModel


_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


class SummaryItem(StrictFrozenModel):
    """One validated summary item with private source provenance."""

    article_id: str
    title: str
    summary: str
    url: str


class SummaryDraftItem(StrictFrozenModel):
    """Model-facing item shape before source provenance is joined locally."""

    article_id: str
    title: str
    summary: str


class SummaryDraft(StrictFrozenModel):
    """Minimal JSON contract required from an LLM daily-summary response."""

    items: tuple[SummaryDraftItem, ...]
    discussion_topic: str


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
    validation_passed: bool = True


def article_id_for_index(index: int) -> str:
    """Return the compact, deterministic ID used inside one candidate snapshot."""
    if index < 1:
        raise ValueError("article index must be positive")
    return f"a{index}"


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

    expected_articles = {
        article_id_for_index(index): article
        for index, article in enumerate(articles, 1)
    }
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
    """Render reader-facing Markdown without exposing source IDs or URLs."""

    def public_text(value: str) -> str:
        without_links = _MARKDOWN_LINK.sub(r"\1", value)
        without_urls = _URL.sub("", without_links)
        compact = " ".join(without_urls.replace("\n", " ").split())
        return re.sub(r"\s+([，。！？；：])", r"\1", compact)

    lines = []
    for index, item in enumerate(result.items, 1):
        title = public_text(item.title).replace("[", "\\[").replace("]", "\\]")
        summary = public_text(item.summary)
        lines.append(f"{index}. {title}：{summary}")
    lines.extend(
        ["", f"💬 互动话题：{html.escape(public_text(result.discussion_topic))}"]
    )
    return "\n".join(lines)
