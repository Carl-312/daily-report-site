#!/usr/bin/env python3
"""Run a minimal, secret-safe ModelScope chat-completions probe."""

# ruff: noqa: E402

from __future__ import annotations

from json import JSONDecodeError
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config
from summarizer import create_client, modelscope_request_options


def _endpoint_label(base_url: str) -> str:
    """Render an endpoint without URL credentials, query parameters, or fragments."""
    parsed = urlsplit(base_url)
    host = parsed.hostname or "invalid-host"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{port}{path}"


def classify_failure(exc: Exception) -> str:
    """Map common failures to the diagnostic categories used by the runbook."""
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    if isinstance(exc, JSONDecodeError):
        return "protocol_invalid_json"
    if isinstance(exc, APIConnectionError):
        return "network_or_proxy"
    if isinstance(exc, AuthenticationError) or status in {401, 403}:
        return "authentication"
    if isinstance(exc, RateLimitError) or status == 429:
        return "quota_or_rate_limit"
    if isinstance(exc, BadRequestError) or status == 400:
        if "no provider supported" in message:
            return "model_or_provider_unavailable"
        return "bad_request"
    return "api_error"


def run_smoke(
    *,
    cfg=None,
    client_factory: Callable = create_client,
    emit: Callable[[str], None] = print,
) -> int:
    """Require one non-empty choice and non-empty assistant message."""
    cfg = cfg or get_config()
    endpoint = _endpoint_label(cfg.api_base_url)
    model = cfg.model
    emit(f"ModelScope smoke: endpoint={endpoint} model={model}")

    if not cfg.api_key:
        emit("ModelScope smoke failed: category=missing_credentials")
        return 1

    params = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "max_tokens": 64,
        "temperature": 0.2,
        "stream": False,
    }
    params.update(modelscope_request_options(model))

    try:
        client = client_factory(
            cfg.api_base_url,
            cfg.api_key,
            timeout=60.0,
        )
        response = client.chat.completions.create(**params)
    except Exception as exc:
        message = " ".join(str(exc).split())
        if cfg.api_key:
            message = message.replace(cfg.api_key, "***")
        emit(
            "ModelScope smoke failed: "
            f"category={classify_failure(exc)} type={type(exc).__name__} "
            f"message={message[:500]}"
        )
        return 1

    choices = response.choices or []
    if not choices:
        emit("ModelScope smoke failed: category=empty_choices choices=0")
        return 1

    content = choices[0].message.content or ""
    if not content.strip():
        emit(
            "ModelScope smoke failed: "
            f"category=empty_content choices={len(choices)} content_length=0"
        )
        return 1

    emit(
        "ModelScope smoke succeeded: "
        f"choices={len(choices)} content_length={len(content)} "
        f"finish_reason={choices[0].finish_reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_smoke())
