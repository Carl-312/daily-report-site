from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from utils.run_contracts import Diagnostic, SourceRunResult, StageResult


NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


def test_source_results_accept_documented_outcomes() -> None:
    assert (
        SourceRunResult(
            source="one",
            status="ok",
            attempts=1,
            duration_ms=0,
            fetched_count=1,
            accepted_count=1,
        ).status
        == "ok"
    )
    assert (
        SourceRunResult(
            source="two",
            status="empty",
            attempts=1,
            duration_ms=0,
            fetched_count=0,
            accepted_count=0,
        ).status
        == "empty"
    )
    assert (
        SourceRunResult(
            source="three",
            status="degraded",
            attempts=1,
            duration_ms=1,
            fetched_count=2,
            accepted_count=1,
            error_kind="parse",
        ).status
        == "degraded"
    )
    assert (
        SourceRunResult(
            source="four",
            status="failed",
            attempts=1,
            duration_ms=1,
            fetched_count=0,
            accepted_count=0,
            diagnostics=(Diagnostic(code="timeout", message="timed out"),),
        ).status
        == "failed"
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": "unknown"}, "Input should be"),
        ({"fetched_count": 0, "accepted_count": 1}, "must not exceed"),
        ({"status": "empty", "fetched_count": 1}, "empty sources"),
        ({"status": "ok", "error_kind": "network"}, "ok sources"),
    ],
)
def test_source_results_reject_invalid_outcomes(kwargs, message: str) -> None:
    values = {
        "source": "source",
        "status": "ok",
        "attempts": 1,
        "duration_ms": 0,
        "fetched_count": 1,
        "accepted_count": 1,
    }
    values.update(kwargs)
    with pytest.raises((ValidationError, ValueError), match=message):
        SourceRunResult(**values)


def test_contracts_are_strict_frozen_and_reject_naive_times() -> None:
    stage = StageResult(name="fetch", status="ok", started_at=NOW)
    with pytest.raises(ValidationError):
        StageResult(name="fetch", status="ok", started_at=datetime(2026, 7, 10))
    with pytest.raises(ValidationError):
        SourceRunResult(
            source="source",
            status="ok",
            attempts=1,
            duration_ms=0,
            fetched_count=1,
            accepted_count=1,
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        stage.status = "failed"
