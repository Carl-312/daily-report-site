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
