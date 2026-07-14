"""Pure execution-budget and retry decisions for LLM completion attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from config import LLMExecutionPolicy


RetryDecisionReason = Literal[
    "retry_scheduled",
    "max_attempts_reached",
    "retry_limit_reached",
    "failure_not_retryable",
    "code_not_allowed",
    "provider_budget_exhausted",
    "run_deadline_exhausted",
]

_SINGLE_RETRY_CODES = frozenset(
    {
        "timeout",
        "network_connection",
        "network_dns",
        "network_proxy",
        "rate_limit",
        "http_5xx",
        "http_error",
        "empty_choices",
    }
)


class ExecutionBudgetExceeded(RuntimeError):
    """Raised before a request or backoff would cross an execution boundary."""

    def __init__(self, scope: Literal["provider", "run"]) -> None:
        self.scope = scope
        super().__init__(f"{scope} execution budget exhausted")


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Secret-free result of evaluating one failed HTTP attempt."""

    retry: bool
    reason: RetryDecisionReason
    backoff_seconds: float = 0


def effective_execution_policy(
    policy: LLMExecutionPolicy,
    *,
    default_max_output_tokens: int,
    default_attempt_timeout_seconds: float,
) -> LLMExecutionPolicy:
    """Fill compatibility defaults without coupling token and time budgets."""

    values = policy.model_dump()
    values["max_output_tokens"] = (
        policy.max_output_tokens
        if policy.max_output_tokens is not None
        else int(default_max_output_tokens)
    )
    values["attempt_timeout_seconds"] = (
        policy.attempt_timeout_seconds
        if policy.attempt_timeout_seconds is not None
        else float(default_attempt_timeout_seconds)
    )
    return LLMExecutionPolicy.model_validate(values)


def bounded_provider_deadline(
    policy: LLMExecutionPolicy,
    run_deadline: datetime | None,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """Return the earlier of the configured provider and whole-run deadlines."""

    current = now or datetime.now(timezone.utc)
    provider_deadline = (
        current + timedelta(seconds=policy.provider_budget_seconds)
        if policy.provider_budget_seconds is not None
        else None
    )
    deadlines = [
        deadline
        for deadline in (provider_deadline, run_deadline)
        if deadline is not None
    ]
    return min(deadlines) if deadlines else None


def deadline_remaining_seconds(
    deadline: datetime | None, *, now: datetime | None = None
) -> float | None:
    """Return a deadline's remaining duration without hiding exhaustion."""

    if deadline is None:
        return None
    current = now or datetime.now(timezone.utc)
    return (deadline - current).total_seconds()


def bounded_attempt_timeout(
    policy: LLMExecutionPolicy,
    *,
    provider_deadline: datetime | None,
    run_deadline: datetime | None,
    now: datetime | None = None,
) -> float:
    """Bound one network timeout by attempt, provider, and whole-run budgets."""

    if policy.attempt_timeout_seconds is None:
        raise ValueError("effective execution policy requires attempt_timeout_seconds")

    current = now or datetime.now(timezone.utc)
    run_remaining = deadline_remaining_seconds(run_deadline, now=current)
    if run_remaining is not None and run_remaining <= 0:
        raise ExecutionBudgetExceeded("run")
    provider_remaining = deadline_remaining_seconds(provider_deadline, now=current)
    if provider_remaining is not None and provider_remaining <= 0:
        # When the bounded provider deadline is the run deadline, report the
        # global scope so callers stop instead of attempting another fallback.
        if run_deadline is not None and provider_deadline == run_deadline:
            raise ExecutionBudgetExceeded("run")
        raise ExecutionBudgetExceeded("provider")

    candidates = [float(policy.attempt_timeout_seconds)]
    if provider_remaining is not None:
        candidates.append(provider_remaining)
    if run_remaining is not None:
        candidates.append(run_remaining)
    return min(candidates)


def bounded_backoff(
    policy: LLMExecutionPolicy,
    *,
    provider_deadline: datetime | None,
    run_deadline: datetime | None,
    retry_after_seconds: float | None = None,
    now: datetime | None = None,
) -> float:
    """Return a backoff only when it leaves time for another request."""

    wait_seconds = (
        max(0.0, float(retry_after_seconds))
        if retry_after_seconds is not None
        else float(policy.retry_backoff_seconds)
    )
    current = now or datetime.now(timezone.utc)
    run_remaining = deadline_remaining_seconds(run_deadline, now=current)
    if run_remaining is not None and run_remaining <= wait_seconds:
        raise ExecutionBudgetExceeded("run")
    provider_remaining = deadline_remaining_seconds(provider_deadline, now=current)
    if provider_remaining is not None and provider_remaining <= wait_seconds:
        if run_deadline is not None and provider_deadline == run_deadline:
            raise ExecutionBudgetExceeded("run")
        raise ExecutionBudgetExceeded("provider")
    return wait_seconds


def evaluate_retry(
    failure_code: str,
    retryable: bool,
    attempt_number: int,
    policy: LLMExecutionPolicy,
    *,
    provider_deadline: datetime | None = None,
    run_deadline: datetime | None = None,
    retry_after_seconds: float | None = None,
    now: datetime | None = None,
) -> RetryDecision:
    """Evaluate policy, attempt count, and both time budgets after a failure."""

    if not retryable:
        return RetryDecision(False, "failure_not_retryable")
    if failure_code not in policy.retryable_codes:
        return RetryDecision(False, "code_not_allowed")
    if failure_code in _SINGLE_RETRY_CODES and attempt_number >= 2:
        return RetryDecision(False, "retry_limit_reached")
    if attempt_number >= policy.max_attempts:
        return RetryDecision(False, "max_attempts_reached")
    try:
        wait_seconds = bounded_backoff(
            policy,
            provider_deadline=provider_deadline,
            run_deadline=run_deadline,
            retry_after_seconds=retry_after_seconds,
            now=now,
        )
    except ExecutionBudgetExceeded as exc:
        reason: RetryDecisionReason = (
            "run_deadline_exhausted"
            if exc.scope == "run"
            else "provider_budget_exhausted"
        )
        return RetryDecision(False, reason)
    return RetryDecision(True, "retry_scheduled", wait_seconds)


def should_retry(
    failure_code: str,
    retryable: bool,
    attempt_number: int,
    policy: LLMExecutionPolicy,
    *,
    provider_deadline: datetime | None = None,
    run_deadline: datetime | None = None,
    retry_after_seconds: float | None = None,
    now: datetime | None = None,
) -> bool:
    """Boolean convenience wrapper around :func:`evaluate_retry`."""

    return evaluate_retry(
        failure_code,
        retryable,
        attempt_number,
        policy,
        provider_deadline=provider_deadline,
        run_deadline=run_deadline,
        retry_after_seconds=retry_after_seconds,
        now=now,
    ).retry
