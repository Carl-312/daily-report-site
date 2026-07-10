"""Explicit policy decisions for optional Tavily enrichment."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnrichmentDecision:
    enabled: bool
    apply: bool
    skip_reason: str | None = None


def decide_enrichment(*, enabled: bool, api_key: str) -> EnrichmentDecision:
    """Return one explicit gate decision before any network work begins."""
    if not enabled:
        return EnrichmentDecision(False, False, "disabled")
    if not api_key:
        return EnrichmentDecision(True, False, "missing_api_key")
    return EnrichmentDecision(True, True)
