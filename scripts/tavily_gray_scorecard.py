"""
Build a normalized scorecard from a Tavily gray validation artifact.

The parser is intentionally offline-only: it reads the files produced by the
GitHub Actions gray workflow and never calls Tavily or project fetch sources.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
from typing import Any

NETWORK_OUTCOMES = {
    "timeout",
    "http_error",
    "connection_error",
    "request_error",
    "unexpected_error",
}
REFILL_STAGES = ("priority_refill", "secondary_refill", "official_fallback")
UNKNOWN = "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a scorecard from a Tavily gray artifact directory"
    )
    parser.add_argument(
        "artifact_dir",
        help="Directory containing report.json and enrichment-summary.json",
    )
    parser.add_argument("--run-id", default="", help="GitHub Actions run id")
    parser.add_argument("--command", default="", help="Command used for the gray run")
    parser.add_argument("--old-commit", default="", help="Commit before the gray run")
    parser.add_argument("--new-commit", default="", help="Commit evaluated by the run")
    parser.add_argument(
        "--artifact-path",
        default="",
        help="Artifact path shown in GitHub Actions, if different from manifest.json",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Output JSON path. Defaults to ARTIFACT_DIR/scorecard.json",
    )
    parser.add_argument(
        "--output-md",
        default="",
        help="Output Markdown path. Defaults to ARTIFACT_DIR/scorecard.md",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def value_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        value = item.get(key)
        counts[str(value if value not in (None, "") else UNKNOWN)] += 1
    return dict(sorted(counts.items()))


def rate(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(part / total, 4)


def extract_run_id(artifact_dir: Path, explicit: str) -> str:
    if explicit:
        return explicit
    match = re.search(r"tavily-gray-\d{4}-\d{2}-\d{2}-(\d+)", str(artifact_dir))
    if match:
        return match.group(1)
    return ""


def extract_command(log_text: str, explicit: str) -> str:
    if explicit:
        return explicit
    for line in log_text.splitlines():
        if line.startswith("Command:"):
            return line.split(":", 1)[1].strip()
    return ""


def artifact_candidates(enrichment: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *as_list(enrichment.get("prefilter_candidates")),
        *as_list(enrichment.get("excluded_prefilter_candidates")),
    ]


def source_distribution(
    report_payload: dict[str, Any],
    enrichment: dict[str, Any],
) -> dict[str, int]:
    candidates = artifact_candidates(enrichment)
    if candidates:
        sources = [candidate.get("source") or UNKNOWN for candidate in candidates]
    else:
        sources = [
            article.get("source") or UNKNOWN
            for article in as_list(report_payload.get("articles"))
        ]
    return dict(sorted(Counter(sources).items()))


def aggregate_title_count(enrichment: dict[str, Any]) -> int:
    candidates = artifact_candidates(enrichment)
    counted = sum(1 for candidate in candidates if candidate.get("aggregate_like"))
    stats_count = int(
        (enrichment.get("prefilter_stats") or {}).get("excluded_aggregate_like", 0)
    )
    return max(counted, stats_count)


def stage_runs(enrichment: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    key = f"{stage}_runs"
    return as_list(enrichment.get(key))


def stage_candidates(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for run in runs:
        candidates.extend(as_list(run.get("candidate_results")))
    return candidates


def summarize_refill_stage(enrichment: dict[str, Any], stage: str) -> dict[str, Any]:
    runs = stage_runs(enrichment, stage)
    candidates = stage_candidates(runs)
    lenient_candidates = [
        candidate for candidate in candidates if candidate.get("lenient_candidate")
    ]
    missing_published = sum(
        1 for candidate in candidates if not candidate.get("published_date")
    )
    rejected_candidates = [
        candidate for candidate in candidates if candidate.get("accepted") is not True
    ]
    accepted_count = sum(int(run.get("accepted_count") or 0) for run in runs)
    return {
        "calls": len(runs),
        "result_count": sum(int(run.get("result_count") or 0) for run in runs),
        "accepted_count": accepted_count,
        "published_date_missing_count": missing_published,
        "published_date_missing_rate": rate(missing_published, len(candidates)),
        "request_outcomes": value_counts(runs, "request_outcome"),
        "near_duplicate_rejected_count": sum(
            int(run.get("near_duplicate_rejected_count") or 0) for run in runs
        ),
        "story_cluster_rejected_count": sum(
            int(run.get("story_cluster_rejected_count") or 0) for run in runs
        ),
        "duplicate_rejected_count": sum(
            1
            for candidate in rejected_candidates
            if candidate.get("duplicate_existing")
            or candidate.get("duplicate_within_results")
        ),
        "non_ai_rejected_count": sum(
            1
            for candidate in rejected_candidates
            if candidate.get("ai_title_relevant") is False
        ),
        "outside_window_rejected_count": sum(
            1
            for candidate in rejected_candidates
            if candidate.get("within_24h") is False
        ),
        "lenient_candidate_count": len(lenient_candidates),
        "proven_within_lenient_window_count": sum(
            1
            for candidate in lenient_candidates
            if candidate.get("lenient_within_window") is True
        ),
        "missing_date_unproven_count": sum(
            1 for candidate in lenient_candidates if not candidate.get("published_date")
        ),
        "outside_lenient_window_rejected_count": sum(
            1
            for candidate in candidates
            if candidate.get("lenient_within_window") is False
        ),
        "lenient_non_ai_count": sum(
            1
            for candidate in lenient_candidates
            if candidate.get("ai_title_relevant") is False
        ),
        "lenient_duplicate_or_cluster_count": sum(
            1
            for candidate in lenient_candidates
            if candidate.get("duplicate_existing")
            or candidate.get("duplicate_within_results")
            or candidate.get("near_duplicate_existing")
            or candidate.get("story_cluster_existing")
        ),
        "accepted_preview": [
            candidate.get("title", "")
            for candidate in candidates
            if candidate.get("accepted") is True and candidate.get("title")
        ][:3],
        "rejected_preview": [
            candidate.get("title", "")
            for candidate in rejected_candidates
            if candidate.get("title")
        ][:3],
    }


def summarize_lenient_diagnostics(
    enrichment: dict[str, Any],
    refill_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    diagnostic = enrichment.get("lenient_refill_diagnostics") or {}
    selected_preview = enrichment.get("lenient_selected_preview")
    if selected_preview is None:
        selected_preview = []
    return {
        "enabled": bool(diagnostic.get("enabled")),
        "window_hours": diagnostic.get("window_hours")
        or (enrichment.get("parameters") or {}).get("lenient_refill_window_hours"),
        "request_window_hours": diagnostic.get("request_window_hours")
        or (enrichment.get("parameters") or {}).get("refill_search_window_hours"),
        "start_date": diagnostic.get("start_date"),
        "end_date": diagnostic.get("end_date"),
        "strict_final_count": int(
            enrichment.get("strict_final_count")
            if enrichment.get("strict_final_count") is not None
            else enrichment.get("final_count") or 0
        ),
        "strict_refill_accepted_count": int(
            enrichment.get("strict_refill_accepted_count")
            if enrichment.get("strict_refill_accepted_count") is not None
            else sum(
                int(enrichment.get(key) or 0)
                for key in (
                    "priority_refilled_count",
                    "secondary_refilled_count",
                    "official_refilled_count",
                )
            )
        ),
        "lenient_candidate_count": int(
            enrichment.get("lenient_candidate_count")
            if enrichment.get("lenient_candidate_count") is not None
            else sum(
                summary["lenient_candidate_count"]
                for summary in refill_summaries.values()
            )
        ),
        "proven_within_72h_count": int(
            enrichment.get("proven_within_72h_count")
            if enrichment.get("proven_within_72h_count") is not None
            else sum(
                summary["proven_within_lenient_window_count"]
                for summary in refill_summaries.values()
            )
        ),
        "missing_date_unproven_count": int(
            enrichment.get("missing_date_unproven_count")
            if enrichment.get("missing_date_unproven_count") is not None
            else sum(
                summary["missing_date_unproven_count"]
                for summary in refill_summaries.values()
            )
        ),
        "outside_72h_rejected_count": int(
            enrichment.get("outside_72h_rejected_count")
            if enrichment.get("outside_72h_rejected_count") is not None
            else sum(
                summary["outside_lenient_window_rejected_count"]
                for summary in refill_summaries.values()
            )
        ),
        "lenient_non_ai_count": int(
            enrichment.get("lenient_non_ai_count")
            if enrichment.get("lenient_non_ai_count") is not None
            else sum(
                summary["lenient_non_ai_count"] for summary in refill_summaries.values()
            )
        ),
        "lenient_duplicate_or_cluster_count": int(
            enrichment.get("lenient_duplicate_or_cluster_count")
            if enrichment.get("lenient_duplicate_or_cluster_count") is not None
            else sum(
                summary["lenient_duplicate_or_cluster_count"]
                for summary in refill_summaries.values()
            )
        ),
        "lenient_selected_preview": selected_preview[:5],
        "stages": diagnostic.get("stages") or {},
    }


def summarize_verify(enrichment: dict[str, Any]) -> dict[str, Any]:
    runs = as_list(enrichment.get("verify_runs"))
    rejected = as_list(enrichment.get("rejected_candidates"))
    return {
        "calls": len(runs),
        "verified_count": int(enrichment.get("verified_count") or 0),
        "preserved_error_count": int(enrichment.get("preserved_error_count") or 0),
        "validation_outcomes": value_counts(runs, "validation_outcome"),
        "request_outcomes": value_counts(runs, "request_outcome"),
        "rejected_preview": [
            candidate.get("title", "")
            for candidate in rejected
            if candidate.get("title")
        ][:3],
    }


def network_failure_count(
    verify_summary: dict[str, Any], refill_summaries: dict[str, dict[str, Any]]
) -> int:
    count = 0
    for outcome, total in verify_summary["request_outcomes"].items():
        if outcome in NETWORK_OUTCOMES:
            count += total
    for summary in refill_summaries.values():
        for outcome, total in summary["request_outcomes"].items():
            if outcome in NETWORK_OUTCOMES:
                count += total
    return count


def quality_rejection_count(refill_summaries: dict[str, dict[str, Any]]) -> int:
    keys = (
        "near_duplicate_rejected_count",
        "story_cluster_rejected_count",
        "duplicate_rejected_count",
        "non_ai_rejected_count",
        "outside_window_rejected_count",
    )
    return sum(
        int(summary.get(key) or 0)
        for summary in refill_summaries.values()
        for key in keys
    )


def aggregate_published_date_missing_rate(
    refill_summaries: dict[str, dict[str, Any]],
) -> float | None:
    missing_count = sum(
        int(summary.get("published_date_missing_count") or 0)
        for summary in refill_summaries.values()
    )
    result_count = sum(
        int(summary.get("result_count") or 0) for summary in refill_summaries.values()
    )
    return rate(missing_count, result_count)


def build_diagnosis(
    *,
    report_json_present: bool,
    enrichment: dict[str, Any],
    verify_summary: dict[str, Any],
    refill_summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    parameters = enrichment.get("parameters") or {}
    min_articles = int(parameters.get("min_articles") or 0)
    final_count = int(enrichment.get("final_count") or 0)
    total_calls = int(enrichment.get("total_calls") or 0)
    max_total_calls = parameters.get("max_total_calls")
    stop_reason = enrichment.get("stop_reason") or UNKNOWN
    missing_dates = sum(
        int(summary.get("published_date_missing_count") or 0)
        for summary in refill_summaries.values()
    )
    network_failures = network_failure_count(verify_summary, refill_summaries)
    quality_rejections = quality_rejection_count(refill_summaries)
    budget_exhausted = "budget_exhausted" in stop_reason
    if max_total_calls is not None:
        budget_exhausted = budget_exhausted or total_calls >= int(max_total_calls)

    factors: list[str] = []
    if budget_exhausted:
        factors.append("budget_exhausted")
    if missing_dates:
        factors.append("published_date_missing")
    if quality_rejections:
        factors.append("candidate_quality_rejections")
    if network_failures:
        factors.append("network_failures")
    if int(enrichment.get("input_count") or 0) == 0:
        factors.append("source_empty")
    if enrichment.get("skip_reason"):
        factors.append(f"skip_reason:{enrichment['skip_reason']}")

    if not report_json_present:
        primary = "report_json_missing"
    elif not enrichment:
        primary = "enrichment_missing"
    elif enrichment.get("applied") is not True:
        primary = f"enrichment_not_applied:{enrichment.get('skip_reason') or UNKNOWN}"
    elif min_articles and final_count >= min_articles:
        primary = "min_articles_satisfied"
    elif network_failures:
        primary = "network_failure"
    elif int(enrichment.get("input_count") or 0) == 0:
        primary = "source_empty"
    elif budget_exhausted:
        primary = "budget_exhausted"
    elif missing_dates:
        primary = "metadata_missing"
    elif quality_rejections:
        primary = "candidate_quality"
    else:
        primary = "below_min_unresolved"

    stage_counts = {
        "preserved_errors": int(enrichment.get("preserved_error_count") or 0),
        "verify": int(enrichment.get("verified_count") or 0),
        "priority_refill": int(enrichment.get("priority_refilled_count") or 0),
        "secondary_refill": int(enrichment.get("secondary_refilled_count") or 0),
        "official_fallback": int(enrichment.get("official_refilled_count") or 0),
    }
    remaining = max(0, min_articles - final_count) if min_articles else 0
    explanation = (
        f"{final_count} final articles = "
        f"{stage_counts['preserved_errors']} preserved + "
        f"{stage_counts['verify']} verify + "
        f"{stage_counts['priority_refill']} priority refill + "
        f"{stage_counts['secondary_refill']} secondary refill + "
        f"{stage_counts['official_fallback']} official fallback; "
        f"{remaining} below min_articles={min_articles or 'unknown'}."
    )

    return {
        "primary_limiter": primary,
        "contributing_factors": factors,
        "stage_counts": stage_counts,
        "final_count_explanation": explanation,
        "needs_fixture": primary
        not in {"min_articles_satisfied", "enrichment_not_applied:disabled"},
        "cannot_prove": [
            "This artifact is a single live run, not evidence for default enablement.",
            "It does not prove Tavily result stability across days or runner environments.",
            "It does not prove broader domain, query, timeout, or official fallback changes are safe.",
        ],
    }


def build_scorecard(
    artifact_dir: Path,
    *,
    run_id: str = "",
    command: str = "",
    old_commit: str = "",
    new_commit: str = "",
    artifact_path: str = "",
) -> dict[str, Any]:
    report_path = artifact_dir / "report.json"
    summary_path = artifact_dir / "enrichment-summary.json"
    manifest_path = artifact_dir / "manifest.json"
    markdown_path = artifact_dir / "report.md"
    log_path = artifact_dir / "logs" / "run.log"

    report_payload = load_json(report_path)
    summary_payload = load_json(summary_path)
    manifest = load_json(manifest_path)
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

    enrichment = (
        report_payload.get("enrichment") or summary_payload.get("enrichment") or {}
    )
    report_json_present = report_path.exists()
    report_markdown_present = markdown_path.exists()
    verify_summary = summarize_verify(enrichment)
    refill_summaries = {
        stage: summarize_refill_stage(enrichment, stage) for stage in REFILL_STAGES
    }
    lenient_diagnostics = summarize_lenient_diagnostics(
        enrichment,
        refill_summaries,
    )
    parameters = enrichment.get("parameters") or {}
    final_count = int(enrichment.get("final_count") or 0)
    min_articles = parameters.get("min_articles")
    refill_remaining_count = enrichment.get("refill_remaining_count")
    if refill_remaining_count is None and min_articles is not None:
        refill_remaining_count = max(0, int(min_articles) - final_count)

    scorecard = {
        "metadata": {
            "date": report_payload.get("date")
            or summary_payload.get("date")
            or manifest.get("date")
            or enrichment.get("report_date")
            or "",
            "run_id": extract_run_id(artifact_dir, run_id),
            "command": extract_command(log_text, command),
            "artifact_path": artifact_path
            or manifest.get("artifact_path")
            or summary_payload.get("artifact_path")
            or str(artifact_dir),
            "old_commit": old_commit,
            "new_commit": new_commit,
            "report_json_present": report_json_present,
            "report_markdown_present": report_markdown_present,
        },
        "input_quality": {
            "input_count": int(enrichment.get("input_count") or 0),
            "prefiltered_count": int(enrichment.get("prefiltered_count") or 0),
            "source_distribution": source_distribution(report_payload, enrichment),
            "aggregate_title_count": aggregate_title_count(enrichment),
            "prefilter_bucket_counts": enrichment.get("prefilter_bucket_counts") or {},
        },
        "verify": verify_summary,
        "refill": refill_summaries,
        "budget": {
            "reserved_refill_calls": enrichment.get("reserved_refill_calls"),
            "verify_budget": enrichment.get("verify_budget"),
            "verify_skipped_due_budget": enrichment.get("verify_skipped_due_budget"),
            "max_total_calls": parameters.get("max_total_calls"),
            "max_verify_calls": parameters.get("max_verify_calls"),
            "total_calls": int(enrichment.get("total_calls") or 0),
            "secondary_entered": bool(stage_runs(enrichment, "secondary_refill")),
            "official_fallback_enabled": bool(
                parameters.get("enable_official_fallback")
            ),
        },
        "output": {
            "article_count": len(as_list(report_payload.get("articles"))),
            "final_count": final_count,
            "strict_final_count": lenient_diagnostics["strict_final_count"],
            "min_articles": min_articles,
            "refill_remaining_count": refill_remaining_count,
            "stop_reason": enrichment.get("stop_reason") or UNKNOWN,
            "accepted_by_stage_preview": enrichment.get("accepted_by_stage_preview")
            or {},
        },
        "lenient_diagnostics": lenient_diagnostics,
    }
    scorecard["diagnosis"] = build_diagnosis(
        report_json_present=report_json_present,
        enrichment=enrichment,
        verify_summary=verify_summary,
        refill_summaries=refill_summaries,
    )
    scorecard["trend_metrics"] = {
        "final_count": scorecard["output"]["final_count"],
        "verified_count": scorecard["verify"]["verified_count"],
        "priority_refilled_count": int(enrichment.get("priority_refilled_count") or 0),
        "secondary_refilled_count": int(
            enrichment.get("secondary_refilled_count") or 0
        ),
        "published_date_missing_rate": aggregate_published_date_missing_rate(
            refill_summaries
        ),
        "lenient_candidate_count": lenient_diagnostics["lenient_candidate_count"],
        "proven_within_72h_count": lenient_diagnostics["proven_within_72h_count"],
        "missing_date_unproven_count": lenient_diagnostics[
            "missing_date_unproven_count"
        ],
        "total_calls": scorecard["budget"]["total_calls"],
        "stop_reason": scorecard["output"]["stop_reason"],
    }
    return scorecard


def markdown_value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return "`" + json.dumps(value, ensure_ascii=False, sort_keys=True) + "`"
    return f"`{value}`"


def render_scorecard_markdown(scorecard: dict[str, Any]) -> str:
    metadata = scorecard["metadata"]
    input_quality = scorecard["input_quality"]
    output = scorecard["output"]
    budget = scorecard["budget"]
    verify = scorecard["verify"]
    refill = scorecard["refill"]
    lenient = scorecard["lenient_diagnostics"]
    diagnosis = scorecard["diagnosis"]

    lines = [
        f"# Tavily Gray Scorecard: {metadata['date'] or 'unknown'}",
        "",
        "## Source",
        "",
        f"- Run id: {markdown_value(metadata['run_id'])}",
        f"- Command: {markdown_value(metadata['command'])}",
        f"- Artifact path: {markdown_value(metadata['artifact_path'])}",
        f"- Old commit: {markdown_value(metadata['old_commit'])}",
        f"- New commit: {markdown_value(metadata['new_commit'])}",
        f"- Report JSON present: {markdown_value(metadata['report_json_present'])}",
        f"- Report Markdown present: {markdown_value(metadata['report_markdown_present'])}",
        "",
        "## Core Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| input_count | {markdown_value(input_quality['input_count'])} |",
        f"| prefiltered_count | {markdown_value(input_quality['prefiltered_count'])} |",
        f"| aggregate_title_count | {markdown_value(input_quality['aggregate_title_count'])} |",
        f"| verified_count | {markdown_value(verify['verified_count'])} |",
        f"| preserved_error_count | {markdown_value(verify['preserved_error_count'])} |",
        f"| final_count | {markdown_value(output['final_count'])} |",
        f"| strict_final_count | {markdown_value(output['strict_final_count'])} |",
        f"| min_articles | {markdown_value(output['min_articles'])} |",
        f"| refill_remaining_count | {markdown_value(output['refill_remaining_count'])} |",
        f"| total_calls | {markdown_value(budget['total_calls'])} |",
        f"| stop_reason | {markdown_value(output['stop_reason'])} |",
        "",
        "## Stage Outcomes",
        "",
        "| Stage | Calls | Results | Accepted | Missing Date Rate | Request Outcomes |",
        "|---|---:|---:|---:|---:|---|",
        (
            "| verify | "
            f"{markdown_value(verify['calls'])} | - | "
            f"{markdown_value(verify['verified_count'])} | - | "
            f"{markdown_value(verify['request_outcomes'])} |"
        ),
    ]

    for stage in REFILL_STAGES:
        summary = refill[stage]
        lines.append(
            f"| {stage} | {markdown_value(summary['calls'])} | "
            f"{markdown_value(summary['result_count'])} | "
            f"{markdown_value(summary['accepted_count'])} | "
            f"{markdown_value(summary['published_date_missing_rate'])} | "
            f"{markdown_value(summary['request_outcomes'])} |"
        )

    lines.extend(
        [
            "",
            "## Lenient Diagnostics",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| enabled | {markdown_value(lenient['enabled'])} |",
            f"| request_window_hours | {markdown_value(lenient['request_window_hours'])} |",
            f"| window_hours | {markdown_value(lenient['window_hours'])} |",
            f"| start_date | {markdown_value(lenient['start_date'])} |",
            f"| end_date | {markdown_value(lenient['end_date'])} |",
            f"| strict_refill_accepted_count | {markdown_value(lenient['strict_refill_accepted_count'])} |",
            f"| lenient_candidate_count | {markdown_value(lenient['lenient_candidate_count'])} |",
            f"| proven_within_72h_count | {markdown_value(lenient['proven_within_72h_count'])} |",
            f"| missing_date_unproven_count | {markdown_value(lenient['missing_date_unproven_count'])} |",
            f"| outside_72h_rejected_count | {markdown_value(lenient['outside_72h_rejected_count'])} |",
            f"| lenient_non_ai_count | {markdown_value(lenient['lenient_non_ai_count'])} |",
            f"| lenient_duplicate_or_cluster_count | {markdown_value(lenient['lenient_duplicate_or_cluster_count'])} |",
            "",
            f"- Lenient preview: {markdown_value(lenient['lenient_selected_preview'])}",
            "",
            "## Budget",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| reserved_refill_calls | {markdown_value(budget['reserved_refill_calls'])} |",
            f"| verify_budget | {markdown_value(budget['verify_budget'])} |",
            f"| verify_skipped_due_budget | {markdown_value(budget['verify_skipped_due_budget'])} |",
            f"| max_total_calls | {markdown_value(budget['max_total_calls'])} |",
            f"| max_verify_calls | {markdown_value(budget['max_verify_calls'])} |",
            f"| secondary_entered | {markdown_value(budget['secondary_entered'])} |",
            "",
            "## Stage Preview",
            "",
            f"- Accepted: {markdown_value(output['accepted_by_stage_preview'])}",
            f"- Verify rejected: {markdown_value(verify['rejected_preview'])}",
        ]
    )
    for stage in REFILL_STAGES:
        lines.append(
            f"- {stage} rejected: {markdown_value(refill[stage]['rejected_preview'])}"
        )

    lines.extend(
        [
            "",
            "## Diagnosis",
            "",
            f"- Primary limiter: {markdown_value(diagnosis['primary_limiter'])}",
            f"- Contributing factors: {markdown_value(diagnosis['contributing_factors'])}",
            f"- Fixture candidate: {markdown_value(diagnosis['needs_fixture'])}",
            f"- Final count: {diagnosis['final_count_explanation']}",
            "",
            "## Cannot Prove",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in diagnosis["cannot_prove"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    artifact_dir = Path(args.artifact_dir).resolve()
    scorecard = build_scorecard(
        artifact_dir,
        run_id=args.run_id,
        command=args.command,
        old_commit=args.old_commit,
        new_commit=args.new_commit,
        artifact_path=args.artifact_path,
    )
    output_json = Path(args.output_json or artifact_dir / "scorecard.json")
    output_md = Path(args.output_md or artifact_dir / "scorecard.md")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(render_scorecard_markdown(scorecard), encoding="utf-8")
    print(f"Wrote Tavily gray scorecard JSON: {output_json}")
    print(f"Wrote Tavily gray scorecard Markdown: {output_md}")


if __name__ == "__main__":
    main()
