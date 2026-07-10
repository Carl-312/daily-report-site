from __future__ import annotations

import pytest

from utils.publish_policy import decide_publication
from utils.run_contracts import Diagnostic, SourceRunResult


def source(status: str) -> SourceRunResult:
    return SourceRunResult(
        source="fixture",
        status=status,
        attempts=1,
        duration_ms=1,
        fetched_count=1 if status == "ok" else 0,
        accepted_count=1 if status == "ok" else 0,
        diagnostics=(Diagnostic(code="failure", message="failed"),)
        if status in {"failed", "degraded"}
        else (),
    )


@pytest.mark.parametrize(
    ("articles_count", "sources", "summary", "build", "reason"),
    [
        (1, (source("failed"),), True, True, "all_enabled_sources_failed"),
        (0, (source("ok"),), True, True, "no_accepted_articles"),
        (1, (source("ok"),), False, True, "summary_failed"),
        (1, (source("ok"),), True, False, "build_failed"),
    ],
)
def test_blocking_gates_do_not_publish(
    articles_count, sources, summary, build, reason
) -> None:
    decision = decide_publication(
        articles_count=articles_count,
        source_results=sources,
        summary_succeeded=summary,
        build_succeeded=build,
    )
    assert decision.publish is False
    assert decision.status == "failed"
    assert decision.reason == reason


def test_partial_source_failure_is_explicitly_degraded() -> None:
    decision = decide_publication(
        articles_count=1,
        source_results=(source("ok"), source("failed")),
        summary_succeeded=True,
        build_succeeded=True,
    )
    assert decision == decision.__class__("degraded", True, "source_degraded")
