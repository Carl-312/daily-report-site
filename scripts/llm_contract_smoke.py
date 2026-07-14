#!/usr/bin/env python3
"""Run an explicit, budgeted live daily-contract probe against ModelScope."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LLMModelCapability, get_config
from summarizer import (
    AllProvidersFailed,
    create_client,
    model_request_options,
    resolve_model_capability,
    summarize_result,
)
from utils.llm_compat import (
    classify_exception,
    endpoint_label,
    extract_single_json_object,
    request_chat_completion,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Live ModelScope daily-summary contract probe. Full response and "
            "reasoning text are never written."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Required acknowledgement that this consumes real API quota.",
    )
    parser.add_argument("--data", default="data/2026-07-14.json")
    parser.add_argument("--models", nargs="+", default=None)
    parser.add_argument(
        "--prompt-path",
        default=None,
        help="Optional experiment prompt; the configured production prompt is unchanged.",
    )
    parser.add_argument(
        "--request-mode",
        choices=("prompt_only", "json_object", "json_schema"),
        default="prompt_only",
    )
    parser.add_argument(
        "--enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Probe the provider-specific extra_body.enable_thinking switch. "
            "Omit both forms to send no thinking control."
        ),
    )
    parser.add_argument(
        "--schema-conflict",
        action="store_true",
        help=(
            "Spend one extra request per model asking for a shape that conflicts "
            "with a strict boolean schema."
        ),
    )
    parser.add_argument("--request-budget", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--output", default=None)
    return parser


def _probe_capability(
    base: LLMModelCapability,
    *,
    request_mode: str,
    timeout: float | None,
    enable_thinking: bool | None,
) -> LLMModelCapability:
    values = base.model_dump()
    values["request_mode"] = request_mode
    # A live probe's CLI request budget is authoritative; do not inherit
    # application-level retries from production policy.
    values["execution"]["max_attempts"] = 1
    values["execution"]["retryable_codes"] = ()
    if request_mode == "json_object":
        values["supports_json_object"] = True
    if request_mode == "json_schema":
        # Probe-only: this enables sending the field.  The result must not be
        # copied into production config unless the conflict probe also passes.
        values["supports_json_schema"] = True
        values["enforces_json_schema"] = True
    if timeout is not None:
        values["execution"]["attempt_timeout_seconds"] = timeout
    if enable_thinking is not None:
        values["thinking_control_parameter"] = "enable_thinking"
        values["thinking_control_value"] = enable_thinking
    return LLMModelCapability.model_validate(values)


def _provider(cfg: Any, model: str, capability: LLMModelCapability) -> dict[str, Any]:
    return {
        "provider_id": "modelscope",
        "name": "ModelScope live probe",
        "base_url": cfg.api_base_url,
        "api_key": cfg.api_key,
        "model": model,
        "capability": capability,
    }


def _conflict_probe(
    cfg: Any, model: str, capability: LLMModelCapability
) -> dict[str, Any]:
    client = create_client(
        cfg.api_base_url,
        cfg.api_key,
        timeout=(
            capability.execution.attempt_timeout_seconds
            or cfg.llm.default_timeout_seconds
        ),
    )
    params: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    'Return exactly {"ok":"yes","extra":1}; the instruction '
                    "intentionally conflicts with the response schema."
                ),
            }
        ],
        "stream": False,
        capability.max_tokens_parameter: 128,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "schema_enforcement_probe",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            },
        },
    }
    if capability.supports_temperature:
        params["temperature"] = 0
    base_options = model_request_options(
        capability.model_copy(update={"request_mode": "prompt_only"})
    )
    params.update(base_options)
    try:
        completion = request_chat_completion(client, params)
        payload = extract_single_json_object(completion.content)
        enforced = set(payload) == {"ok"} and isinstance(payload.get("ok"), bool)
        return {
            "status": "enforced" if enforced else "not_enforced",
            "http_status": completion.telemetry.http_status,
            "request_id": completion.telemetry.request_id,
            "content_length": completion.telemetry.content_length,
            "reasoning_length": completion.telemetry.reasoning_length,
            "finish_reason": completion.telemetry.finish_reason,
            "response_sha256": completion.telemetry.response_sha256,
        }
    except Exception as exc:
        classification = classify_exception(exc)
        return {
            "status": "failed",
            "failure_stage": classification.stage,
            "failure_code": classification.code,
            "http_status": classification.http_status,
            "request_id": classification.request_id,
        }


def run(args: argparse.Namespace) -> int:
    if not args.live:
        print("Refusing to call a live API without --live.", file=sys.stderr)
        return 2
    if args.request_budget < 1:
        print("--request-budget must be positive.", file=sys.stderr)
        return 2

    cfg = get_config()
    if not cfg.api_key:
        print("MODELSCOPE_API_KEY is not configured.", file=sys.stderr)
        return 2
    data_path = Path(args.data)
    prompt_path = Path(args.prompt_path) if args.prompt_path else None
    if prompt_path is not None and not prompt_path.is_file():
        print(f"Prompt file does not exist: {prompt_path}", file=sys.stderr)
        return 2
    report = json.loads(data_path.read_text(encoding="utf-8"))
    articles = report.get("articles")
    if not isinstance(articles, list) or not articles:
        print("The input report has no articles.", file=sys.stderr)
        return 2

    models = list(dict.fromkeys(args.models or [cfg.model]))
    requests_needed = len(models) * (2 if args.schema_conflict else 1)
    if requests_needed > args.request_budget:
        print(
            f"Probe needs {requests_needed} requests but budget is "
            f"{args.request_budget}.",
            file=sys.stderr,
        )
        return 2

    timestamp = datetime.now(timezone.utc)
    output_path = Path(
        args.output
        or f".runs/llm-contract-smoke-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    results = []
    exit_code = 0
    for model in models:
        base_capability = resolve_model_capability(
            cfg, "modelscope", cfg.api_base_url, model
        )
        capability = _probe_capability(
            base_capability,
            request_mode=args.request_mode,
            timeout=args.timeout,
            enable_thinking=args.enable_thinking,
        )
        try:
            summary = summarize_result(
                articles,
                provider_candidates=[_provider(cfg, model, capability)],
                prompt_path=prompt_path,
            )
            contract = {
                "status": "publishable",
                "provider": summary.provider,
                "model": summary.model,
                "item_count": len(summary.items),
                "input_fingerprint": summary.input_fingerprint,
                "prompt_fingerprint": summary.prompt_fingerprint,
                "attempt": summary.attempts[-1].model_dump(mode="json"),
            }
        except AllProvidersFailed as exc:
            exit_code = 1
            contract = {
                "status": "failed",
                "model": model,
                "attempt": exc.attempts[-1].model_dump(mode="json"),
            }

        result: dict[str, Any] = {"model": model, "contract": contract}
        if args.schema_conflict:
            schema_probe = _conflict_probe(cfg, model, capability)
            result["schema_conflict"] = schema_probe
            if schema_probe["status"] != "enforced":
                exit_code = 1
        results.append(result)
        print(
            f"{model}: contract={contract['status']}"
            + (
                f" schema={result['schema_conflict']['status']}"
                if args.schema_conflict
                else ""
            )
        )

    artifact = {
        "schema_version": 1,
        "source_type": "live",
        "created_at": timestamp.isoformat(),
        "endpoint": endpoint_label(cfg.api_base_url),
        "input_path": str(data_path),
        "prompt_path": str(prompt_path) if prompt_path is not None else None,
        "request_mode": args.request_mode,
        "enable_thinking": args.enable_thinking,
        "schema_conflict_requested": args.schema_conflict,
        "request_budget": args.request_budget,
        "requests_planned": requests_needed,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote secret-safe live evidence to {output_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
