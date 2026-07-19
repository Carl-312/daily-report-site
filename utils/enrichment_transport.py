"""Tavily transport boundary for the production enrichment pipeline."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

from utils.run_contracts import RunDeadlineExceeded


class TavilyTransport:
    """Own HTTP concerns while leaving matching and policy to callers."""

    url = "https://api.tavily.com/search"

    def __init__(
        self,
        session: requests.Session,
        api_key: str,
        *,
        deadline_at: datetime | None = None,
        default_timeout: float = 45,
    ) -> None:
        self.session = session
        self.api_key = api_key
        self.deadline_at = deadline_at
        self.default_timeout = default_timeout

    def search(
        self,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_timeout = self.default_timeout if timeout is None else timeout
        if self.deadline_at is not None:
            remaining = (
                self.deadline_at - datetime.now(self.deadline_at.tzinfo)
            ).total_seconds()
            if remaining <= 0:
                raise RunDeadlineExceeded("run deadline exceeded before Tavily request")
            request_timeout = min(request_timeout, remaining)

        started = time.perf_counter()
        response = self.session.post(
            self.url,
            json={"api_key": self.api_key, **payload},
            timeout=request_timeout,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        response.raise_for_status()
        return {"latency_ms": latency_ms, "response": response.json()}


def classify_request_outcome(error: Exception | None) -> str:
    """Normalize transport failures into the existing report vocabulary."""
    if error is None:
        return "success"
    if isinstance(error, requests.Timeout):
        return "timeout"
    if isinstance(error, requests.HTTPError):
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status in {401, 403}:
            return "authentication_error"
        if status in {400, 404, 405, 422}:
            return "invalid_request"
        if status == 429:
            return "rate_limited"
        return "http_error"
    if isinstance(error, requests.ConnectionError):
        return "connection_error"
    if isinstance(error, requests.RequestException):
        return "request_error"
    return "unexpected_error"
