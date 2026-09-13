"""Validate the complete formal-gray publication before it can replace Pages."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from typing import Any


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from scripts.agihunt_gray_health import find_latest_manifest
from utils.story_quality import canonical_story_url
from utils.storage import atomic_write_text
from utils.summary_contracts import (
    SummaryResult,
    article_reference_map,
    validate_summary_result,
)
from utils.summary_selection import article_source_group


def _previous_day(report_date: str) -> str:
    try:
        return (date.fromisoformat(report_date) - timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def evaluate_formal_gray_run(
    manifest: dict[str, Any],
    *,
    data_dir: Path,
    content_dir: Path,
) -> dict[str, Any]:
    """Return one complete, machine-readable formal-gray quality decision."""

    errors: list[str] = []
    checks: dict[str, Any] = {}
    report_date = str(manifest.get("report_date") or "")
    if not report_date:
        errors.append("manifest report_date is missing")

    data_path = data_dir / f"{report_date}.json"
    checks["data_path"] = str(data_path)
    if not data_path.is_file():
        errors.append("generated data checkpoint is missing")
        payload: dict[str, Any] = {}
    else:
        try:
            payload = json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
            errors.append("generated data checkpoint is invalid JSON")

    articles = payload.get("articles")
    articles = articles if isinstance(articles, list) else []
    summary_payload = payload.get("summary")
    if not isinstance(summary_payload, dict):
        errors.append("generated summary checkpoint is missing")
        summary: SummaryResult | None = None
    else:
        try:
            summary = SummaryResult.model_validate(summary_payload)
            validate_summary_result(summary, articles, max_items=10)
        except Exception as exc:
            summary = None
            errors.append(f"summary contract failed: {type(exc).__name__}")

    source_counts: Counter[str] = Counter()
    summary_urls: set[str] = set()
    if summary is not None:
        references = article_reference_map(articles)
        for item in summary.items:
            source_counts[article_source_group(references[item.article_id])] += 1
            canonical = canonical_story_url(item.url)
            if canonical:
                summary_urls.add(canonical)
        checks["summary_count"] = len(summary.items)
    else:
        checks["summary_count"] = 0
    checks["summary_source_counts"] = dict(sorted(source_counts.items()))

    enrichment = payload.get("enrichment")
    enrichment = enrichment if isinstance(enrichment, dict) else {}
    request_runs = enrichment.get("candidate_enrichment_runs")
    request_runs = request_runs if isinstance(request_runs, list) else []
    request_outcomes = Counter(
        str(run.get("request_outcome") or "")
        for run in request_runs
        if isinstance(run, dict)
    )
    request_outcomes.pop("", None)
    checks["enrichment_request_outcomes"] = dict(sorted(request_outcomes.items()))
    if (
        request_runs
        and request_outcomes.get("success", 0) == 0
        and int(enrichment.get("lead_unresolved_count") or 0) > 0
        and len(source_counts) < 2
    ):
        errors.append(
            "all enrichment requests failed while the public edition collapsed "
            "to one source"
        )

    previous_day = _previous_day(report_date)
    previous_content = content_dir / f"{previous_day}.md"
    previous_data = data_dir / f"{previous_day}.json"
    checks["previous_day"] = previous_day
    checks["previous_data_present"] = previous_data.is_file()
    if previous_content.is_file() and not previous_data.is_file():
        errors.append("previous edition content exists without its data checkpoint")
    if previous_data.is_file():
        try:
            previous_payload = json.loads(previous_data.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_payload = {}
            errors.append("previous data checkpoint is invalid JSON")
        previous_summary = previous_payload.get("summary")
        previous_items = (
            previous_summary.get("items", [])
            if isinstance(previous_summary, dict)
            else []
        )
        previous_urls = {
            canonical_story_url(str(item.get("url") or ""))
            for item in previous_items
            if isinstance(item, dict)
        }
        previous_urls.discard("")
        if summary_urls & previous_urls:
            errors.append("current summary repeats an exact URL from the previous day")
        recent_dedupe = enrichment.get("recent_dedupe")
        checked_days = (
            recent_dedupe.get("checked_days", [])
            if isinstance(recent_dedupe, dict)
            else []
        )
        if previous_day not in checked_days:
            errors.append("recent dedupe did not inspect the previous data checkpoint")

    publication = manifest.get("publication")
    publication_status = (
        publication.get("status") if isinstance(publication, dict) else None
    )
    checks["publication_status"] = publication_status
    if publication_status != "published":
        errors.append("staged publication did not complete")

    return {
        "healthy": not errors,
        "report_date": report_date,
        "checks": checks,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=".runs")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--content-dir", default="content")
    parser.add_argument("--output", default="formal-gray-health.json")
    args = parser.parse_args()

    manifest_path = find_latest_manifest(Path(args.runs_dir))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = evaluate_formal_gray_run(
        manifest,
        data_dir=Path(args.data_dir),
        content_dir=Path(args.content_dir),
    )
    result["manifest_path"] = str(manifest_path)
    output_path = atomic_write_text(
        Path(args.output),
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    if not result["healthy"]:
        raise SystemExit(
            "Formal gray health check failed: " + "; ".join(result["errors"])
        )
    print(f"Formal gray health check passed: {output_path}")


if __name__ == "__main__":
    main()
