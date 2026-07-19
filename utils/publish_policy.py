"""Pure publication gate for a staged daily edition."""

from __future__ import annotations

from dataclasses import dataclass

from utils.run_contracts import SourceRunResult


@dataclass(frozen=True, slots=True)
class PublishDecision:
    status: str
    publish: bool
    reason: str | None = None


def decide_publication(
    *,
    articles_count: int,
    source_results: tuple[SourceRunResult, ...],
    summary_succeeded: bool,
    build_succeeded: bool,
    allow_empty: bool = False,
) -> PublishDecision:
    """Decide whether a complete staged edition is eligible for promotion."""
    if source_results and all(result.status == "failed" for result in source_results):
        return PublishDecision("failed", False, "all_enabled_sources_failed")
    if articles_count <= 0 and not allow_empty:
        return PublishDecision("failed", False, "no_accepted_articles")
    if not summary_succeeded:
        return PublishDecision("failed", False, "summary_failed")
    if not build_succeeded:
        return PublishDecision("failed", False, "build_failed")
    if any(result.status in {"failed", "degraded"} for result in source_results):
        return PublishDecision("degraded", True, "source_degraded")
    return PublishDecision("published", True)
