"""Verification-stage boundary for Tavily candidate validation."""

from __future__ import annotations

from typing import Any


def run_verify_stage(**kwargs: Any) -> dict[str, Any]:
    """Run verification without exposing the legacy orchestration module."""
    from utils.news_enrichment import _run_verify_stage_legacy

    return _run_verify_stage_legacy(**kwargs)
