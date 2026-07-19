"""Staged Tavily refill stage."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import requests

from utils.run_contracts import RunDeadlineExceeded


def run_domain_refill_stage(
    *,
    base_articles: list[dict[str, Any]],
    prior_candidates: list[dict[str, Any]],
    include_domains: list[str],
    query: str,
    queries: list[str] | None = None,
    stage_name: str,
    settings: Any,
    session: requests.Session,
    api_key: str,
    reference_dt: datetime,
    remaining_budget: int,
    needed_count: int,
    deadline_at: datetime | None = None,
) -> dict[str, Any]:
    from utils.news_enrichment import (
        REFILL_SEARCH_DEPTH,
        _search_tavily_with_deadline,
        build_dynamic_existing_index,
        canonical_url,
        classify_request_outcome,
        domain_of,
        empty_refill_result,
        find_story_cluster_match,
        headline_entities,
        normalize_title,
        refill_title_relevant,
        refill_request_window_hours,
        report_window,
        within_strict_hours,
    )

    accepted_candidates: list[dict[str, Any]] = []
    refill_runs: list[dict[str, Any]] = []
    near_duplicate_rejected_count = 0
    story_cluster_rejected_count = 0
    domain_quota_rejected_count = 0
    entity_quota_rejected_count = 0

    if (
        settings.max_refill_rounds <= 0
        or remaining_budget <= 0
        or needed_count <= 0
        or not include_domains
    ):
        return empty_refill_result(remaining_budget)

    request_window_hours = refill_request_window_hours(settings)
    lenient_window_hours = int(
        getattr(settings, "lenient_refill_window_hours", 72) or 72
    )
    lenient_diagnostics_enabled = bool(
        getattr(settings, "lenient_refill_diagnostics_enabled", False)
    )
    start_date, end_date = report_window(
        reference_dt,
        window_hours=request_window_hours,
    )
    stage_queries = [item.strip() for item in (queries or [query]) if item.strip()]
    if not stage_queries:
        stage_queries = [query]
    rounds_budget = min(
        settings.max_refill_rounds,
        remaining_budget,
        len(stage_queries),
    )
    for round_index in range(rounds_budget):
        needed_before_round = max(0, needed_count - len(accepted_candidates))
        if needed_before_round <= 0:
            break
        round_query = stage_queries[round_index]
        payload = {
            "query": round_query,
            "topic": "news",
            "search_depth": REFILL_SEARCH_DEPTH,
            "max_results": settings.refill_max_results,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "auto_parameters": False,
            "include_domains": include_domains,
            "start_date": start_date,
            "end_date": end_date,
        }
        latency_ms = None
        error = None
        error_obj: Exception | None = None
        results: list[dict[str, Any]] = []
        try:
            response = _search_tavily_with_deadline(
                session, api_key, payload, deadline_at
            )
            latency_ms = response["latency_ms"]
            results = response["response"].get("results", []) or []
        except RunDeadlineExceeded:
            raise
        except Exception as exc:
            error = str(exc)
            error_obj = exc

        existing = build_dynamic_existing_index(
            base_articles,
            prior_candidates + accepted_candidates,
        )
        round_accepted: list[dict[str, Any]] = []
        run_candidates: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        round_near_duplicate_rejected = 0
        round_story_cluster_rejected = 0
        round_domain_quota_rejected = 0
        round_entity_quota_rejected = 0

        diversity_pool = prior_candidates + accepted_candidates
        domain_counts = Counter(
            domain_of(item.get("link", "") or item.get("url", ""))
            for item in diversity_pool
        )
        entity_counts = Counter(
            entity
            for item in diversity_pool
            for entity in headline_entities(item.get("title", ""))
        )
        max_per_domain = max(0, int(getattr(settings, "max_refill_per_domain", 0) or 0))
        max_per_entity = max(0, int(getattr(settings, "max_refill_per_entity", 0) or 0))

        for index, result_item in enumerate(results, start=1):
            strict_slot_available = (
                len(accepted_candidates) + len(round_accepted) < needed_count
            )
            if not lenient_diagnostics_enabled and not strict_slot_available:
                break
            title = result_item.get("title", "")
            url = result_item.get("url", "")
            normalized_title = normalize_title(title)
            canonical = canonical_url(url)
            duplicate_existing = (
                normalized_title in existing["titles"] or canonical in existing["urls"]
            )
            duplicate_within_results = normalized_title in seen_titles
            seen_titles.add(normalized_title)
            cluster_match = find_story_cluster_match(
                {
                    "title": title,
                    "url": url,
                },
                prior_candidates + accepted_candidates + round_accepted,
            )
            near_duplicate_existing = (
                cluster_match is not None
                and cluster_match["relation_type"] == "near_duplicate"
            )
            story_cluster_existing = (
                cluster_match is not None
                and cluster_match["relation_type"] == "story_cluster"
            )
            within_window = within_strict_hours(
                result_item.get("published_date"),
                reference_dt=reference_dt,
                strict_hours=settings.strict_hours,
            )
            within_24h = within_strict_hours(
                result_item.get("published_date"),
                reference_dt=reference_dt,
                strict_hours=24,
            )
            lenient_within_window = within_strict_hours(
                result_item.get("published_date"),
                reference_dt=reference_dt,
                strict_hours=lenient_window_hours,
            )
            title_is_ai_relevant = refill_title_relevant(title)
            result_domain = domain_of(url)
            result_entities = headline_entities(title)
            domain_quota_reached = bool(
                max_per_domain
                and domain_counts[result_domain]
                + sum(
                    1
                    for item in round_accepted
                    if domain_of(item.get("link", "")) == result_domain
                )
                >= max_per_domain
            )
            entity_quota_reached = bool(
                max_per_entity
                and any(
                    entity_counts[entity]
                    + sum(
                        1
                        for item in round_accepted
                        if entity in headline_entities(item.get("title", ""))
                    )
                    >= max_per_entity
                    for entity in result_entities
                )
            )
            duplicate_or_cluster = (
                duplicate_existing
                or duplicate_within_results
                or near_duplicate_existing
                or story_cluster_existing
            )
            base_eligible = (
                strict_slot_available
                and bool(within_window)
                and title_is_ai_relevant
                and not duplicate_existing
                and not duplicate_within_results
                and not near_duplicate_existing
                and not story_cluster_existing
            )
            domain_quota_rejected = base_eligible and domain_quota_reached
            entity_quota_rejected = (
                base_eligible and not domain_quota_reached and entity_quota_reached
            )
            accepted = (
                base_eligible and not domain_quota_reached and not entity_quota_reached
            )
            if near_duplicate_existing:
                round_near_duplicate_rejected += 1
            elif story_cluster_existing:
                round_story_cluster_rejected += 1
            elif domain_quota_rejected:
                round_domain_quota_rejected += 1
            elif entity_quota_rejected:
                round_entity_quota_rejected += 1

            accepted_article = {
                "title": title,
                "link": url,
                "description": result_item.get("content", ""),
                "publish_time": result_item.get("published_date", "") or "",
                "content": result_item.get("content", "") or "",
                "priority": 0,
                "source": domain_of(url),
                "score": result_item.get("score"),
            }
            run_candidate = {
                "rank": index,
                "title": title,
                "url": url,
                "domain": result_domain,
                "entities": sorted(result_entities),
                "published_date": result_item.get("published_date"),
                "within_24h": within_24h,
                "within_strict_window": within_window,
                "strict_window_hours": settings.strict_hours,
                "lenient_within_window": lenient_within_window,
                "lenient_window_hours": lenient_window_hours,
                "lenient_candidate": (
                    lenient_diagnostics_enabled and lenient_within_window is not False
                ),
                "lenient_rejection_reason": (
                    f"outside_{lenient_window_hours}h"
                    if lenient_within_window is False
                    else None
                ),
                "ai_title_relevant": title_is_ai_relevant,
                "duplicate_existing": duplicate_existing,
                "duplicate_within_results": duplicate_within_results,
                "near_duplicate_existing": near_duplicate_existing,
                "story_cluster_existing": story_cluster_existing,
                "duplicate_or_cluster": duplicate_or_cluster,
                "domain_quota_reached": domain_quota_reached,
                "entity_quota_reached": entity_quota_reached,
                "domain_quota_rejected": domain_quota_rejected,
                "entity_quota_rejected": entity_quota_rejected,
                "cluster_match": cluster_match,
                "accepted": accepted,
                "score": result_item.get("score"),
            }
            run_candidates.append(run_candidate)
            if accepted:
                round_accepted.append(accepted_article)

        refill_runs.append(
            {
                "stage": stage_name,
                "round": round_index + 1,
                "query": round_query,
                "search_depth": REFILL_SEARCH_DEPTH,
                "max_results": settings.refill_max_results,
                "include_domains": include_domains,
                "start_date": start_date,
                "end_date": end_date,
                "request_window_hours": request_window_hours,
                "lenient_diagnostic_window_hours": lenient_window_hours,
                "latency_ms": latency_ms,
                "result_count": len(results),
                "needed_before": needed_before_round,
                "accepted_count": len(round_accepted),
                "remaining_needed_after": max(
                    0, needed_count - len(accepted_candidates) - len(round_accepted)
                ),
                "request_outcome": classify_request_outcome(error_obj),
                "near_duplicate_rejected_count": round_near_duplicate_rejected,
                "story_cluster_rejected_count": round_story_cluster_rejected,
                "domain_quota_rejected_count": round_domain_quota_rejected,
                "entity_quota_rejected_count": round_entity_quota_rejected,
                "duplicate_slip_count": 0,
                "candidate_results": run_candidates,
                "error": error,
            }
        )
        accepted_candidates.extend(round_accepted)
        near_duplicate_rejected_count += round_near_duplicate_rejected
        story_cluster_rejected_count += round_story_cluster_rejected
        domain_quota_rejected_count += round_domain_quota_rejected
        entity_quota_rejected_count += round_entity_quota_rejected
        if error or len(accepted_candidates) >= needed_count:
            break

    return {
        "refill_calls": len(refill_runs),
        "accepted_candidates": accepted_candidates,
        "refill_runs": refill_runs,
        "media_refilled_count": len(accepted_candidates),
        "near_duplicate_rejected_count": near_duplicate_rejected_count,
        "story_cluster_rejected_count": story_cluster_rejected_count,
        "domain_quota_rejected_count": domain_quota_rejected_count,
        "entity_quota_rejected_count": entity_quota_rejected_count,
        "duplicate_slip_count": 0,
        "remaining_budget_after_refill": max(0, remaining_budget - len(refill_runs)),
    }
