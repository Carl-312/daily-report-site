"""Refill-stage boundary for staged Tavily candidate acquisition."""

from __future__ import annotations

from typing import Any


def run_domain_refill_stage(**kwargs: Any) -> dict[str, Any]:
    """Run refill without exposing the legacy orchestration module."""
    from utils.news_enrichment import _run_domain_refill_stage_legacy

    return _run_domain_refill_stage_legacy(**kwargs)
