#!/usr/bin/env python3
"""Run a minimal, secret-safe ModelScope chat-completions probe."""

# ruff: noqa: E402

from __future__ import annotations

from pathlib import Path
import sys
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config
from summarizer import create_client, model_request_options, resolve_model_capability
from utils.llm_compat import (
    classify_exception,
    endpoint_label,
    request_chat_completion,
)


def classify_failure(exc: Exception) -> str:
    """Compatibility wrapper around the shared failure-code taxonomy."""

    return classify_exception(exc).code


def run_smoke(
    *,
    cfg=None,
    client_factory: Callable = create_client,
    emit: Callable[[str], None] = print,
) -> int:
    """Require one non-empty choice and non-empty assistant message."""
    cfg = cfg or get_config()
    endpoint = endpoint_label(cfg.api_base_url)
    model = cfg.model
    emit(f"ModelScope smoke: endpoint={endpoint} model={model}")

    if not cfg.api_key:
        emit("ModelScope smoke failed: category=missing_credentials")
        return 1

    capability = resolve_model_capability(cfg, "modelscope", cfg.api_base_url, model)
    params: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "stream": False,
    }
    params[capability.max_tokens_parameter] = 64
    if capability.supports_temperature:
        params["temperature"] = 0.2
    params.update(model_request_options(capability))

    try:
        client = client_factory(
            cfg.api_base_url,
            cfg.api_key,
            timeout=60.0,
        )
        completion = request_chat_completion(client, params)
    except Exception as exc:
        classification = classify_exception(exc)
        emit(
            "ModelScope smoke failed: "
            f"stage={classification.stage} category={classification.code} "
            f"type={type(exc).__name__}"
        )
        return 1

    telemetry = completion.telemetry
    emit(
        "ModelScope smoke succeeded: "
        f"choices={telemetry.choices_count} content_length={len(completion.content)} "
        f"reasoning_length={telemetry.reasoning_length} "
        f"finish_reason={telemetry.finish_reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_smoke())
