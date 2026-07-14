from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from config import LLMExecutionPolicy
from utils.llm_execution import (
    bounded_attempt_timeout,
    bounded_provider_deadline,
    effective_execution_policy,
    evaluate_retry,
    should_retry,
)


NOW = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)


def test_model_output_and_attempt_timeout_defaults_are_independent() -> None:
    token_override = effective_execution_policy(
        LLMExecutionPolicy(max_output_tokens=4096),
        default_max_output_tokens=2000,
        default_attempt_timeout_seconds=60,
    )
    timeout_override = effective_execution_policy(
        LLMExecutionPolicy(attempt_timeout_seconds=90),
        default_max_output_tokens=2000,
        default_attempt_timeout_seconds=60,
    )

    assert token_override.max_output_tokens == 4096
    assert token_override.attempt_timeout_seconds == 60
    assert timeout_override.max_output_tokens == 2000
    assert timeout_override.attempt_timeout_seconds == 90


def test_attempt_timeout_is_bounded_by_provider_and_run_deadlines() -> None:
    policy = LLMExecutionPolicy(
        attempt_timeout_seconds=60,
        provider_budget_seconds=30,
    )
    provider_deadline = bounded_provider_deadline(
        policy, NOW + timedelta(seconds=45), now=NOW
    )

    assert provider_deadline == NOW + timedelta(seconds=30)
    assert (
        bounded_attempt_timeout(
            policy,
            provider_deadline=provider_deadline,
            run_deadline=NOW + timedelta(seconds=45),
            now=NOW,
        )
        == 30
    )


def test_empty_choices_gets_at_most_one_same_model_retry() -> None:
    policy = LLMExecutionPolicy(
        max_attempts=3,
        retry_backoff_seconds=0,
        retryable_codes=("empty_choices",),
    )

    assert should_retry("empty_choices", True, 1, policy) is True
    decision = evaluate_retry("empty_choices", True, 2, policy)
    assert decision.retry is False
    assert decision.reason == "retry_limit_reached"


@pytest.mark.parametrize(
    "failure_code",
    [
        "incomplete_output",
        "authentication",
        "bad_request",
        "protocol_multi_document",
        "contract_shape",
        "quality_length",
    ],
)
def test_non_retryable_failures_never_retry_even_if_listed(
    failure_code: str,
) -> None:
    policy = LLMExecutionPolicy(
        max_attempts=2,
        retryable_codes=(failure_code,),
    )

    decision = evaluate_retry(failure_code, False, 1, policy)
    assert decision.retry is False
    assert decision.reason == "failure_not_retryable"


def test_retry_requires_explicit_code_and_more_than_one_attempt() -> None:
    disabled = LLMExecutionPolicy(
        max_attempts=1,
        retryable_codes=("timeout",),
    )
    code_not_allowed = LLMExecutionPolicy(max_attempts=2)

    assert evaluate_retry("timeout", True, 1, disabled).reason == (
        "max_attempts_reached"
    )
    assert evaluate_retry("timeout", True, 1, code_not_allowed).reason == (
        "code_not_allowed"
    )


@pytest.mark.parametrize(
    ("provider_deadline", "run_deadline", "reason"),
    [
        (NOW + timedelta(seconds=1), None, "provider_budget_exhausted"),
        (None, NOW + timedelta(seconds=1), "run_deadline_exhausted"),
    ],
)
def test_retry_backoff_must_leave_time_inside_both_budgets(
    provider_deadline: datetime | None,
    run_deadline: datetime | None,
    reason: str,
) -> None:
    policy = LLMExecutionPolicy(
        max_attempts=2,
        retry_backoff_seconds=2,
        retryable_codes=("http_5xx",),
    )

    decision = evaluate_retry(
        "http_5xx",
        True,
        1,
        policy,
        provider_deadline=provider_deadline,
        run_deadline=run_deadline,
        now=NOW,
    )

    assert decision.retry is False
    assert decision.reason == reason


def test_retry_after_replaces_default_backoff_and_must_fit_budget() -> None:
    policy = LLMExecutionPolicy(
        max_attempts=2,
        retry_backoff_seconds=0,
        retryable_codes=("rate_limit",),
    )

    decision = evaluate_retry(
        "rate_limit",
        True,
        1,
        policy,
        run_deadline=NOW + timedelta(seconds=3),
        retry_after_seconds=5,
        now=NOW,
    )

    assert decision.retry is False
    assert decision.reason == "run_deadline_exhausted"
