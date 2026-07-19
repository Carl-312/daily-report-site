"""Tavily candidate verification stage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from utils.run_contracts import RunDeadlineExceeded


def run_verify_stage(
    *,
    candidates: list[dict[str, Any]],
    settings: Any,
    session: requests.Session,
    api_key: str,
    reference_dt: datetime,
    remaining_budget: int | None = None,
    deadline_at: datetime | None = None,
) -> dict[str, Any]:
    from utils.news_enrichment import (
        TITLE_SIMILARITY_MATCH_THRESHOLD,
        VERIFY_MAX_RESULTS,
        _search_tavily_with_deadline,
        classify_request_outcome,
        pick_best_match,
        report_window,
        reserved_refill_call_budget,
        within_strict_hours,
    )

    start_date, end_date = report_window(reference_dt)
    available_budget = (
        max(0, settings.max_total_calls)
        if remaining_budget is None
        else max(0, min(settings.max_total_calls, remaining_budget))
    )
    reserved_refill_calls = reserved_refill_call_budget(
        settings, available_budget=available_budget
    )
    verify_budget = max(
        0,
        min(
            settings.max_verify_calls,
            max(0, available_budget - reserved_refill_calls),
        ),
    )
    verify_runs: list[dict[str, Any]] = []
    verified_articles: list[dict[str, Any]] = []
    preserved_error_articles: list[dict[str, Any]] = []
    preserved_budget_articles = [
        dict(candidate["article"]) for candidate in candidates[verify_budget:]
    ]
    verified_candidates: list[dict[str, Any]] = []
    rejected_candidates: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates[:verify_budget], start=1):
        prefilter_bucket = candidate.get("prefilter_bucket", "generic_or_low_signal")
        query = f'"{candidate["title"]}"'
        payload = {
            "query": query,
            "topic": "news",
            "search_depth": settings.verify_search_depth,
            "max_results": VERIFY_MAX_RESULTS,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "auto_parameters": False,
            "start_date": start_date,
            "end_date": end_date,
        }

        matched = False
        matched_url = None
        matched_title = None
        matched_published_date = None
        title_similarity_value = None
        within_window = None
        error = None
        error_obj: Exception | None = None
        latency_ms = None
        results: list[dict[str, Any]] = []

        try:
            response = _search_tavily_with_deadline(
                session, api_key, payload, deadline_at
            )
            latency_ms = response["latency_ms"]
            body = response["response"]
            results = body.get("results", []) or []
            best_match = pick_best_match(
                results,
                expected_title=candidate["title"],
                expected_url=candidate["link"],
            )
            if best_match:
                title_similarity_value = best_match["title_similarity"]
                matched = best_match["exact_url_match"] or (
                    bool(best_match["same_domain"])
                    and title_similarity_value >= TITLE_SIMILARITY_MATCH_THRESHOLD
                )
                matched_url = best_match["url"]
                matched_title = best_match["title"]
                matched_published_date = best_match["published_date"]
                within_window = within_strict_hours(
                    matched_published_date,
                    reference_dt=reference_dt,
                    strict_hours=settings.strict_hours,
                )
        except RunDeadlineExceeded:
            raise
        except Exception as exc:
            error = str(exc)
            error_obj = exc

        accepted = bool(matched) and within_window is True
        request_outcome = classify_request_outcome(error_obj)
        if request_outcome != "success":
            validation_outcome = "not_evaluated"
        elif accepted:
            validation_outcome = "accepted"
        elif not matched:
            validation_outcome = "no_match"
        elif within_window is False:
            validation_outcome = "outside_24h"
        else:
            validation_outcome = "missing_published_date"
        verify_runs.append(
            {
                "sample_id": f"{reference_dt.date().isoformat()}::prefilter::{index}",
                "query": query,
                "prefilter_bucket": prefilter_bucket,
                "search_depth": settings.verify_search_depth,
                "latency_ms": latency_ms,
                "result_count": len(results),
                "matched": matched,
                "within_24h": within_window,
                "matched_url": matched_url,
                "matched_title": matched_title,
                "matched_published_date": matched_published_date,
                "title_similarity": title_similarity_value,
                "accepted": accepted,
                "request_outcome": request_outcome,
                "validation_outcome": validation_outcome,
                "error": error,
            }
        )

        candidate_summary = {
            "title": candidate.get("title", ""),
            "source": candidate.get("source", ""),
            "link": candidate.get("link", ""),
            "prefilter_bucket": prefilter_bucket,
            "matched_url": matched_url,
            "matched_title": matched_title,
            "within_24h": within_window,
            "title_similarity": title_similarity_value,
            "cluster_id": candidate.get("cluster_id"),
            "cluster_role": candidate.get("cluster_role"),
            "cluster_representative_title": candidate.get(
                "cluster_representative_title"
            ),
            "request_outcome": request_outcome,
            "validation_outcome": validation_outcome,
            "transport_error": error,
            "rejection_reason": None,
        }
        if request_outcome == "success" and not matched:
            candidate_summary["rejection_reason"] = "no_match"
        elif request_outcome == "success" and within_window is False:
            candidate_summary["rejection_reason"] = "outside_24h"
        elif request_outcome == "success" and within_window is None:
            candidate_summary["rejection_reason"] = "missing_published_date"

        if accepted:
            article = dict(candidate["article"])
            if matched_published_date:
                article["publish_time"] = matched_published_date
            verified_articles.append(article)
            verified_candidates.append(candidate_summary)
        else:
            rejected_candidates.append(candidate_summary)
            if error:
                preserved_error_articles.append(dict(candidate["article"]))

    return {
        "verify_budget": verify_budget,
        "reserved_refill_calls": reserved_refill_calls,
        "verify_calls": len(verify_runs),
        "verify_skipped_due_budget": max(0, len(candidates) - verify_budget),
        "verify_runs": verify_runs,
        "verified_articles": verified_articles,
        "preserved_error_articles": preserved_error_articles,
        "preserved_budget_articles": preserved_budget_articles,
        "verified_candidates": verified_candidates,
        "rejected_candidates": rejected_candidates,
    }
