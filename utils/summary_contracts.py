"""Structured, replayable daily-summary contracts and deterministic rendering."""

from __future__ import annotations

import hashlib
import html
import json
from typing import Literal

from utils.run_contracts import StrictFrozenModel


class SummaryItem(StrictFrozenModel):
    article_id: str
    title: str
    summary: str
    url: str


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


def validate_summary_result(result: SummaryResult, articles: list[dict]) -> None:
    """Validate summary provenance before a result can be rendered or published."""
    expected_count = min(10, len(articles))
    if len(result.items) != expected_count:
        raise ValueError(
            f"summary has {len(result.items)} items, expected {expected_count}"
        )

    expected_articles = {
        article_id_for_index(index): article
        for index, article in enumerate(articles, 1)
    }
    seen_ids: set[str] = set()
    for item in result.items:
        if item.article_id not in expected_articles:
            raise ValueError(f"summary references unknown article_id {item.article_id}")
        if item.article_id in seen_ids:
            raise ValueError(f"summary repeats article_id {item.article_id}")
        seen_ids.add(item.article_id)

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
    """Render a saved summary result without invoking a model."""
    lines = []
    for index, item in enumerate(result.items, 1):
        title = item.title.replace("[", "\\[").replace("]", "\\]")
        summary = item.summary.replace("\n", " ").strip()
        if item.url.startswith(("http://", "https://")):
            lines.append(f"{index}. [{title}]({item.url})：{summary}")
        else:
            lines.append(f"{index}. {title}：{summary}")
    lines.extend(["", f"💬 互动话题：{html.escape(result.discussion_topic)}"])
    return "\n".join(lines)
