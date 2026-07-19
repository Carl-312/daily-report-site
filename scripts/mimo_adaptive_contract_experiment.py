#!/usr/bin/env python3
"""Compare atomic and item-granular gates on live MiMo daily summaries."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import monotonic
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from summarizer import (
    SummaryContractError,
    SummaryProvenanceError,
    SummaryQualityError,
    _issue_diagnostic,
    _parse_summary_draft_with_diagnostics,
    _validate_summary_payload,
    compress_articles,
    create_client,
    evaluate_editorial_quality,
    load_prompt,
    validate_summary_provenance,
)
from utils.llm_compat import classify_exception, endpoint_label, request_chat_completion
from utils.summary_contracts import (
    SummaryDraft,
    fingerprint_summary_input,
)


MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MODELS = ("mimo-v2.5", "mimo-v2.5-pro")
_QUARANTINE_CODES = frozenset(
    {
        "quality_chinese",
        "quality_duplicate",
        "quality_length",
        "quality_near_duplicate",
        "quality_sentence",
    }
)


@dataclass(frozen=True, slots=True)
class GateResult:
    status: str
    received_items: int = 0
    accepted_items: int = 0
    quarantined_items: int = 0
    capped_items: int = 0
    diagnostics: tuple[str, ...] = ()
    draft: SummaryDraft | None = None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run secret-safe MiMo Non-think calls and compare the current atomic "
            "daily gate with the proposed item-granular gate."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Required acknowledgement that this consumes real API quota.",
    )
    parser.add_argument("--data", default="data/2026-07-14.json")
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--request-budget", type=int, default=6)
    parser.add_argument("--max-items", type=int, default=10)
    parser.add_argument("--max-completion-tokens", type=int, default=4000)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", default=None)
    return parser


def _failure_diagnostic(exc: Exception) -> str:
    code = str(getattr(exc, "code", "validation_failed"))
    issues = getattr(exc, "issues", ())
    if issues:
        return _issue_diagnostic(issues[0])
    return code


def evaluate_atomic_gate(
    content: str, *, article_ids: set[str], max_items: int
) -> GateResult:
    """Evaluate the current all-or-nothing publication gate."""

    try:
        validated = _validate_summary_payload(
            content,
            expected_items=max_items,
            expected_article_ids=article_ids,
            compatible_contract=True,
        )
    except (SummaryContractError, SummaryProvenanceError, SummaryQualityError) as exc:
        return GateResult(status="failed", diagnostics=(_failure_diagnostic(exc),))
    return GateResult(
        status="publishable",
        received_items=len(validated.draft.items),
        accepted_items=len(validated.draft.items),
        diagnostics=validated.diagnostics,
        draft=validated.draft,
    )


def evaluate_adaptive_gate(
    content: str,
    *,
    article_ids: set[str],
    source_count: int,
    max_items: int,
) -> GateResult:
    """Quarantine editorial item failures while retaining trust-level gates."""

    try:
        parsed = _parse_summary_draft_with_diagnostics(
            content, compatible_contract=True
        )
        validate_summary_provenance(parsed.draft, article_ids)
    except (SummaryContractError, SummaryProvenanceError) as exc:
        return GateResult(status="failed", diagnostics=(_failure_diagnostic(exc),))

    received_items = len(parsed.draft.items)
    issues = evaluate_editorial_quality(
        parsed.draft,
        expected_items=max_items,
        source_count=source_count,
        compatible_contract=True,
    )
    hard_issues = tuple(
        issue
        for issue in issues
        if (
            issue.code == "quality_public_safety"
            or (issue.stage == "contract" and received_items == 0)
        )
    )
    if hard_issues:
        return GateResult(
            status="failed",
            received_items=received_items,
            diagnostics=tuple(_issue_diagnostic(issue) for issue in hard_issues),
        )

    quarantined_indexes = {
        issue.item_index
        for issue in issues
        if issue.item_index is not None and issue.code in _QUARANTINE_CODES
    }
    retained = tuple(
        item
        for index, item in enumerate(parsed.draft.items, 1)
        if index not in quarantined_indexes
    )
    capped_items = max(0, len(retained) - max_items)
    retained = retained[:max_items]
    minimum_items = 7 if source_count >= 10 and max_items >= 7 else 1

    diagnostics = list(parsed.diagnostics)
    diagnostics.extend(
        _issue_diagnostic(issue)
        for issue in issues
        if issue.item_index in quarantined_indexes
    )
    if capped_items:
        diagnostics.append(f"items_capped:count={capped_items}")

    adapted = SummaryDraft(
        items=retained,
        discussion_topic=parsed.draft.discussion_topic,
    )
    if len(retained) < minimum_items:
        diagnostics.append(
            f"quality_item_coverage:accepted={len(retained)}:minimum={minimum_items}"
        )
        return GateResult(
            status="failed",
            received_items=received_items,
            accepted_items=len(retained),
            quarantined_items=len(quarantined_indexes),
            capped_items=capped_items,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )

    remaining_blockers = tuple(
        issue
        for issue in evaluate_editorial_quality(
            adapted,
            expected_items=max_items,
            source_count=source_count,
            compatible_contract=True,
        )
        if issue.blocking
    )
    if remaining_blockers:
        diagnostics.extend(_issue_diagnostic(issue) for issue in remaining_blockers)
        return GateResult(
            status="failed",
            received_items=received_items,
            accepted_items=len(retained),
            quarantined_items=len(quarantined_indexes),
            capped_items=capped_items,
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )

    return GateResult(
        status="publishable",
        received_items=received_items,
        accepted_items=len(retained),
        quarantined_items=len(quarantined_indexes),
        capped_items=capped_items,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        draft=adapted,
    )


def _telemetry_payload(telemetry: Any) -> dict[str, Any]:
    return {
        "http_status": telemetry.http_status,
        "request_id": telemetry.request_id,
        "content_length": telemetry.content_length,
        "reasoning_length": telemetry.reasoning_length,
        "finish_reason": telemetry.finish_reason,
        "prompt_tokens": telemetry.prompt_tokens,
        "completion_tokens": telemetry.completion_tokens,
        "reasoning_tokens": telemetry.reasoning_tokens,
        "total_tokens": telemetry.total_tokens,
        "response_sha256": telemetry.response_sha256,
    }


def _gate_payload(result: GateResult, *, include_output: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status,
        "received_items": result.received_items,
        "accepted_items": result.accepted_items,
        "quarantined_items": result.quarantined_items,
        "capped_items": result.capped_items,
        "diagnostics": list(result.diagnostics),
    }
    if include_output and result.status == "publishable" and result.draft is not None:
        payload["accepted_output"] = {
            "items": [
                {"article_id": item.article_id, "summary": item.summary}
                for item in result.draft.items
            ],
            "discussion_topic": result.draft.discussion_topic,
        }
    return payload


def run(args: argparse.Namespace) -> int:
    if not args.live:
        print("Refusing to call a live API without --live.", file=sys.stderr)
        return 2
    if args.samples < 1 or args.max_items < 1 or args.max_completion_tokens < 1:
        print("Samples, item limit, and token budget must be positive.", file=sys.stderr)
        return 2

    models = list(dict.fromkeys(args.models))
    requests_planned = len(models) * args.samples
    if requests_planned > args.request_budget:
        print(
            f"Experiment needs {requests_planned} requests but budget is "
            f"{args.request_budget}.",
            file=sys.stderr,
        )
        return 2
    api_key = os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        print("MIMO_API_KEY is not configured.", file=sys.stderr)
        return 2

    data_path = Path(args.data)
    report = json.loads(data_path.read_text(encoding="utf-8"))
    articles = report.get("articles")
    if not isinstance(articles, list) or not articles:
        print("The input report has no articles.", file=sys.stderr)
        return 2

    compressed = compress_articles(articles)
    article_ids = {article["article_id"] for article in compressed}
    prompt = load_prompt()
    user_input = json.dumps({"articles": compressed}, ensure_ascii=False, indent=2)
    input_fingerprint, prompt_fingerprint = fingerprint_summary_input(
        compressed, prompt
    )
    timestamp = datetime.now(timezone.utc)
    output_path = Path(
        args.output
        or ".runs/"
        f"mimo-adaptive-contract-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    )

    client = create_client(MIMO_BASE_URL, api_key, timeout=args.timeout)
    results: list[dict[str, Any]] = []
    for model in models:
        for sample in range(1, args.samples + 1):
            started = monotonic()
            try:
                completion = request_chat_completion(
                    client,
                    {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_input},
                        ],
                        "stream": False,
                        "max_completion_tokens": args.max_completion_tokens,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "extra_body": {"thinking": {"type": "disabled"}},
                    },
                )
                atomic = evaluate_atomic_gate(
                    completion.content,
                    article_ids=article_ids,
                    max_items=args.max_items,
                )
                adaptive = evaluate_adaptive_gate(
                    completion.content,
                    article_ids=article_ids,
                    source_count=len(articles),
                    max_items=args.max_items,
                )
                result = {
                    "model": model,
                    "sample": sample,
                    "status": "completed",
                    "elapsed_ms": round((monotonic() - started) * 1000),
                    "telemetry": _telemetry_payload(completion.telemetry),
                    "atomic_gate": _gate_payload(atomic, include_output=False),
                    "adaptive_gate": _gate_payload(adaptive, include_output=True),
                }
            except Exception as exc:
                classification = classify_exception(exc)
                result = {
                    "model": model,
                    "sample": sample,
                    "status": "request_failed",
                    "elapsed_ms": round((monotonic() - started) * 1000),
                    "failure_stage": classification.stage,
                    "failure_code": classification.code,
                    "http_status": classification.http_status,
                }
            results.append(result)
            atomic_status = result.get("atomic_gate", {}).get("status", "n/a")
            adaptive_status = result.get("adaptive_gate", {}).get("status", "n/a")
            print(
                f"{model} sample={sample}: request={result['status']} "
                f"atomic={atomic_status} adaptive={adaptive_status}"
            )

    completed = [result for result in results if result["status"] == "completed"]
    atomic_passes = sum(
        result["atomic_gate"]["status"] == "publishable" for result in completed
    )
    adaptive_passes = sum(
        result["adaptive_gate"]["status"] == "publishable" for result in completed
    )
    artifact = {
        "schema_version": 1,
        "source_type": "live_experiment",
        "created_at": timestamp.isoformat(),
        "branch": "experiment/mimo-adaptive-contract-20260715",
        "endpoint": endpoint_label(MIMO_BASE_URL),
        "input_path": str(data_path),
        "input_date": report.get("date"),
        "input_articles": len(articles),
        "input_fingerprint": input_fingerprint,
        "prompt_fingerprint": prompt_fingerprint,
        "request": {
            "models": models,
            "samples_per_model": args.samples,
            "requests_planned": requests_planned,
            "request_budget": args.request_budget,
            "request_mode": "json_object",
            "thinking": "disabled",
            "max_completion_tokens": args.max_completion_tokens,
            "temperature": 0.2,
            "timeout_seconds": args.timeout,
        },
        "comparison": {
            "completed_requests": len(completed),
            "atomic_publishable": atomic_passes,
            "adaptive_publishable": adaptive_passes,
            "absolute_gain": adaptive_passes - atomic_passes,
        },
        "results": results,
        "privacy": {
            "api_key_persisted": False,
            "reasoning_text_persisted": False,
            "rejected_summary_text_persisted": False,
            "accepted_summary_text_persisted": True,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote secret-safe evidence to {output_path}")
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(run(_parser().parse_args()))
