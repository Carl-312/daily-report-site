"""
Experimental Tavily news enrichment replay harness.

This script is intentionally limited to dry runs against historical report
snapshots. It does not modify any production integration path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark_tavily import (  # noqa: E402
    AI_KEYWORD_RE,
    OUTPUT_DATE_FORMAT,
    REPORT_TIMEZONE,
    build_existing_report_index,
    canonical_url,
    domain_of,
    evaluate_verify_case,
    failed_run_record,
    load_reports,
    load_api_key,
    normalize_title,
    report_reference_dt,
    report_window,
    search_tavily,
    title_similarity,
    within_24h,
)
from scripts.benchmark_tavily_whitelist import ai_title_relevant  # noqa: E402

DEFAULT_MIN_ARTICLES = 10
DEFAULT_MAX_TOTAL_CALLS = 7
DEFAULT_MAX_VERIFY_CALLS = 6
DEFAULT_MAX_REFILL_ROUNDS = 1
DEFAULT_REFILL_MAX_RESULTS = 8
DEFAULT_VERIFY_SEARCH_DEPTH = "basic"
DEFAULT_VERIFY_MAX_RESULTS = 3
DEFAULT_REFILL_SEARCH_DEPTH = "advanced"
DEFAULT_MEDIA_REFILL_QUERY = (
    "OpenAI Anthropic AI model launch startup funding developer tools"
)
DEFAULT_OFFICIAL_FALLBACK_QUERY = DEFAULT_MEDIA_REFILL_QUERY
DEFAULT_PRIORITY_REFILL_MEDIA_WHITELIST = [
    "thenextweb.com",
    "venturebeat.com",
]
DEFAULT_SECONDARY_REFILL_CANDIDATE_DOMAINS = [
    "reuters.com",
    "arstechnica.com",
]
DEFAULT_OFFICIAL_FALLBACK_DOMAINS = [
    "openai.com",
    "anthropic.com",
]
AGGREGATE_SOURCE_KEYS = {"aibase"}
AGGREGATE_TITLE_PREFIXES = ("ai日报",)
TRAILING_SOURCE_SUFFIX_RE = re.compile(r"\s+-\s+[A-Za-z0-9&.' ]+$")
STORY_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._-]*")
STORY_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "more",
    "new",
    "now",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "to",
    "was",
    "with",
    "your",
}
STORY_TOKEN_GENERIC = {
    "ai",
    "agent",
    "agents",
    "developer",
    "developers",
    "funding",
    "launch",
    "launches",
    "launching",
    "latest",
    "model",
    "models",
    "news",
    "startup",
    "startups",
    "tool",
    "tools",
}
NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.82
STORY_CLUSTER_MIN_SHARED_TOKENS = 3
STORY_CLUSTER_MIN_OVERLAP_RATIO = 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an experimental Tavily news enrichment dry run against historical reports"
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory with historical report JSON files",
    )
    parser.add_argument(
        "--report-date",
        action="append",
        default=[],
        help="Historical report date to replay in YYYY-MM-DD format; repeatable",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional explicit output path for the dry run JSON",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=45,
        help="Reserved Tavily HTTP timeout in seconds for later incremental stages",
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=DEFAULT_MIN_ARTICLES,
        help="Target final article count for the experimental dry run",
    )
    parser.add_argument(
        "--max-total-calls",
        type=int,
        default=DEFAULT_MAX_TOTAL_CALLS,
        help="Maximum Tavily calls allowed across verify/refill/fallback",
    )
    parser.add_argument(
        "--max-verify-calls",
        type=int,
        default=DEFAULT_MAX_VERIFY_CALLS,
        help="Maximum Tavily calls reserved for exact verification",
    )
    parser.add_argument(
        "--max-refill-rounds",
        type=int,
        default=DEFAULT_MAX_REFILL_ROUNDS,
        help="Maximum media refill rounds for the experimental run",
    )
    parser.add_argument(
        "--refill-max-results",
        type=int,
        default=DEFAULT_REFILL_MAX_RESULTS,
        help="Maximum Tavily results requested per refill call",
    )
    parser.add_argument(
        "--verify-search-depth",
        choices=("basic", "advanced"),
        default=DEFAULT_VERIFY_SEARCH_DEPTH,
        help="Search depth for exact verify requests",
    )
    parser.add_argument(
        "--enable-fuzzy-second-pass",
        action="store_true",
        help="Reserved experimental flag; disabled by default and not used yet",
    )
    parser.add_argument(
        "--enable-official-fallback",
        action="store_true",
        help="Allow the later fallback stage to query official vendor domains",
    )
    return parser.parse_args()


def default_output_path(explicit_output: str) -> Path:
    if explicit_output:
        return Path(explicit_output).resolve()
    filename = f"tavily-enrichment-dryrun-{datetime.now(tz=REPORT_TIMEZONE).date().isoformat()}.json"
    return (REPO_ROOT / "data" / "benchmarks" / filename).resolve()


def parse_requested_dates(raw_values: list[str]) -> list[date]:
    parsed_dates: list[date] = []
    seen: set[date] = set()
    for raw_value in raw_values:
        for part in raw_value.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            parsed = datetime.strptime(candidate, OUTPUT_DATE_FORMAT).date()
            if parsed in seen:
                continue
            seen.add(parsed)
            parsed_dates.append(parsed)
    return parsed_dates


def select_report_dates(
    reports: dict[date, dict[str, Any]],
    requested_dates: list[date],
) -> list[date]:
    if not requested_dates:
        return [max(reports)]
    missing = [
        report_date.isoformat()
        for report_date in requested_dates
        if report_date not in reports
    ]
    if missing:
        raise RuntimeError(
            "Missing historical report JSON for date(s): " + ", ".join(missing)
        )
    return requested_dates


def build_report_stub(
    report_date: date, report_payload: dict[str, Any]
) -> dict[str, Any]:
    article_count = len(report_payload.get("articles", []))
    return {
        "report_date": report_date.isoformat(),
        "raw_count": article_count,
        "deduped_count": article_count,
        "prefiltered_count": None,
        "cluster_count": 0,
        "clustered_prefilter_count": 0,
        "cluster_potential_verify_saved_calls": 0,
        "verify_saved_calls": 0,
        "prefilter_stats": {},
        "verify_calls": 0,
        "refill_calls": 0,
        "fallback_calls": 0,
        "total_calls": 0,
        "verified_count": 0,
        "media_refilled_count": 0,
        "priority_refilled_count": 0,
        "secondary_refilled_count": 0,
        "official_refilled_count": 0,
        "near_duplicate_rejected_count": 0,
        "story_cluster_rejected_count": 0,
        "secondary_duplicate_slip_count": 0,
        "final_count": 0,
        "accepted_by_stage_preview": {},
        "stop_reason": "skeleton_only",
        "notes": [
            "Historical replay starts from the saved post-dedupe report snapshot.",
            "No Tavily requests were made in the skeleton stage.",
        ],
        "sample_titles": [
            article.get("title", "")
            for article in report_payload.get("articles", [])[:3]
            if article.get("title")
        ],
    }


def is_aggregate_like(article: dict[str, Any]) -> bool:
    source = (article.get("source", "") or "").strip().lower()
    title = (article.get("title", "") or "").strip().lower()
    if source in AGGREGATE_SOURCE_KEYS:
        return True
    if any(title.startswith(prefix) for prefix in AGGREGATE_TITLE_PREFIXES):
        return True
    return title.count("；") >= 2 or title.count(";") >= 2


def strip_trailing_source_suffix(title: str) -> str:
    cleaned = (title or "").strip()
    if " - " not in cleaned:
        return cleaned
    return TRAILING_SOURCE_SUFFIX_RE.sub("", cleaned).strip()


def story_tokens(title: str) -> set[str]:
    cleaned = strip_trailing_source_suffix(title).lower()
    tokens: set[str] = set()
    for token in STORY_TOKEN_RE.findall(cleaned):
        if token.isdigit() or len(token) < 3:
            continue
        if token in STORY_TOKEN_STOPWORDS or token in STORY_TOKEN_GENERIC:
            continue
        tokens.add(token)
    return tokens


def story_token_weight(token: str) -> float:
    if any(char.isdigit() for char in token):
        return 1.5
    if len(token) >= 6:
        return 1.5
    if len(token) >= 5:
        return 1.0
    return 0.5


def classify_story_relation(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    left_title = left.get("title", "")
    right_title = right.get("title", "")
    similarity = title_similarity(left_title, right_title)
    left_tokens = story_tokens(left_title)
    right_tokens = story_tokens(right_title)
    shared_tokens = sorted(left_tokens & right_tokens)
    overlap_ratio = 0.0
    if left_tokens and right_tokens:
        overlap_ratio = round(
            len(shared_tokens) / min(len(left_tokens), len(right_tokens)), 4
        )
    shared_weight = round(sum(story_token_weight(token) for token in shared_tokens), 4)
    near_duplicate = similarity >= NEAR_DUPLICATE_SIMILARITY_THRESHOLD
    story_cluster = near_duplicate or (
        len(shared_tokens) >= STORY_CLUSTER_MIN_SHARED_TOKENS
        and overlap_ratio >= STORY_CLUSTER_MIN_OVERLAP_RATIO
    )
    relation_type = None
    if near_duplicate:
        relation_type = "near_duplicate"
    elif story_cluster:
        relation_type = "story_cluster"
    return {
        "left_title": left_title,
        "right_title": right_title,
        "title_similarity": similarity,
        "shared_tokens": shared_tokens,
        "shared_weight": shared_weight,
        "overlap_ratio": overlap_ratio,
        "is_near_duplicate": near_duplicate,
        "is_story_cluster": story_cluster,
        "relation_type": relation_type,
    }


def annotate_story_clusters(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "annotated_candidates": [],
            "cluster_diagnostics": [],
            "cluster_count": 0,
            "clustered_candidate_count": 0,
            "cluster_potential_verify_saved_calls": 0,
        }

    annotated_candidates = [dict(candidate) for candidate in candidates]
    parent = list(range(len(annotated_candidates)))
    relation_pairs: list[dict[str, Any]] = []

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left_candidate in enumerate(annotated_candidates):
        for right_index in range(left_index + 1, len(annotated_candidates)):
            relation = classify_story_relation(
                left_candidate, annotated_candidates[right_index]
            )
            if not relation["is_story_cluster"]:
                continue
            relation_pairs.append(
                {
                    "left_index": left_index,
                    "right_index": right_index,
                    **relation,
                }
            )
            union(left_index, right_index)

    grouped_indices: dict[int, list[int]] = {}
    for index in range(len(annotated_candidates)):
        grouped_indices.setdefault(find(index), []).append(index)

    cluster_diagnostics: list[dict[str, Any]] = []
    cluster_counter = 0
    clustered_candidate_count = 0
    potential_verify_saved_calls = 0

    for indices in sorted(grouped_indices.values(), key=lambda item: item[0]):
        if len(indices) <= 1:
            continue
        cluster_counter += 1
        clustered_candidate_count += len(indices)
        potential_verify_saved_calls += len(indices) - 1
        cluster_id = f"cluster-{cluster_counter:02d}"
        representative = annotated_candidates[indices[0]]
        representative_title = representative.get("title", "")
        relation_preview = [
            {
                "relation_type": relation["relation_type"],
                "left_title": relation["left_title"],
                "right_title": relation["right_title"],
                "shared_tokens": relation["shared_tokens"],
                "title_similarity": relation["title_similarity"],
                "shared_weight": relation["shared_weight"],
                "overlap_ratio": relation["overlap_ratio"],
            }
            for relation in relation_pairs
            if relation["left_index"] in indices and relation["right_index"] in indices
        ]
        alternates: list[dict[str, Any]] = []
        for offset, candidate_index in enumerate(indices):
            candidate = annotated_candidates[candidate_index]
            candidate["cluster_id"] = cluster_id
            candidate["cluster_size"] = len(indices)
            candidate["cluster_role"] = "representative" if offset == 0 else "alternate"
            candidate["cluster_representative_title"] = representative_title
            if offset == 0:
                continue
            alternates.append(
                {
                    "title": candidate.get("title", ""),
                    "source": candidate.get("source", ""),
                    "link": candidate.get("link", "") or candidate.get("url", ""),
                }
            )
        cluster_diagnostics.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": len(indices),
                "cluster_representative": {
                    "title": representative_title,
                    "source": representative.get("source", ""),
                    "link": representative.get("link", "")
                    or representative.get("url", ""),
                },
                "alternates": alternates,
                "relation_preview": relation_preview,
            }
        )

    for candidate in annotated_candidates:
        candidate.setdefault("cluster_id", None)
        candidate.setdefault("cluster_size", 1)
        candidate.setdefault("cluster_role", "singleton")
        candidate.setdefault("cluster_representative_title", candidate.get("title", ""))

    return {
        "annotated_candidates": annotated_candidates,
        "cluster_diagnostics": cluster_diagnostics,
        "cluster_count": cluster_counter,
        "clustered_candidate_count": clustered_candidate_count,
        "cluster_potential_verify_saved_calls": potential_verify_saved_calls,
    }


def find_story_cluster_match(
    candidate: dict[str, Any],
    accepted_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best_match: dict[str, Any] | None = None
    best_score: tuple[int, float, int, float] | None = None
    for accepted_candidate in accepted_candidates:
        relation = classify_story_relation(candidate, accepted_candidate)
        if not relation["is_story_cluster"]:
            continue
        score = (
            1 if relation["is_near_duplicate"] else 0,
            relation["shared_weight"],
            len(relation["shared_tokens"]),
            relation["title_similarity"],
        )
        if best_score is not None and score <= best_score:
            continue
        best_score = score
        best_match = {
            "relation_type": relation["relation_type"],
            "matched_title": accepted_candidate.get("title", ""),
            "matched_source": accepted_candidate.get("source", ""),
            "matched_link": accepted_candidate.get("link", "")
            or accepted_candidate.get("url", ""),
            "shared_tokens": relation["shared_tokens"],
            "shared_weight": relation["shared_weight"],
            "overlap_ratio": relation["overlap_ratio"],
            "title_similarity": relation["title_similarity"],
        }
    return best_match


def collapse_prefilter_candidates_for_verify(
    candidates: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    verify_candidates: list[dict[str, Any]] = []
    skipped_candidates: list[dict[str, Any]] = []
    seen_clusters: set[str] = set()
    for candidate in candidates:
        cluster_id = candidate.get("cluster_id")
        if not cluster_id:
            verify_candidates.append(candidate)
            continue
        if cluster_id not in seen_clusters:
            seen_clusters.add(cluster_id)
            verify_candidates.append(candidate)
            continue
        skipped_candidates.append(
            {
                "title": candidate.get("title", ""),
                "source": candidate.get("source", ""),
                "link": candidate.get("link", ""),
                "cluster_id": cluster_id,
                "cluster_representative_title": candidate.get(
                    "cluster_representative_title",
                    "",
                ),
            }
        )
    return {
        "verify_candidates": verify_candidates,
        "skipped_candidates": skipped_candidates,
    }


def build_prefilter_summary(report_payload: dict[str, Any]) -> dict[str, Any]:
    articles = report_payload.get("articles", []) or []
    included_candidates: list[dict[str, Any]] = []
    excluded_candidates: list[dict[str, Any]] = []
    stats = {
        "total_articles": len(articles),
        "eligible_candidates": 0,
        "excluded_missing_title": 0,
        "excluded_missing_link": 0,
        "excluded_aggregate_like": 0,
        "excluded_non_ai_relevant": 0,
    }

    for index, article in enumerate(articles, start=1):
        title = (article.get("title", "") or "").strip()
        link = (article.get("link", "") or "").strip()
        aggregate_like = is_aggregate_like(article)
        ai_relevant = bool(AI_KEYWORD_RE.search(title))
        reasons: list[str] = []

        if not title:
            stats["excluded_missing_title"] += 1
            reasons.append("missing_title")
        if not link:
            stats["excluded_missing_link"] += 1
            reasons.append("missing_link")
        if aggregate_like:
            stats["excluded_aggregate_like"] += 1
            reasons.append("aggregate_like")
        if title and not ai_relevant:
            stats["excluded_non_ai_relevant"] += 1
            reasons.append("non_ai_relevant")

        candidate = {
            "index": index,
            "source": article.get("source", ""),
            "title": title,
            "link": link,
            "publish_time": article.get("publish_time", ""),
            "aggregate_like": aggregate_like,
            "ai_relevant": ai_relevant,
            "exclude_reasons": reasons,
        }
        if reasons:
            excluded_candidates.append(candidate)
            continue
        stats["eligible_candidates"] += 1
        included_candidates.append(candidate)

    return {
        "prefiltered_count": len(included_candidates),
        "prefilter_stats": stats,
        "prefilter_candidates": included_candidates,
        "excluded_prefilter_candidates": excluded_candidates,
    }


def verify_rejection_reason(run: dict[str, Any]) -> str | None:
    if run.get("error"):
        return "request_error"
    if not run.get("matched"):
        return "no_match"
    if run.get("within_24h") is False:
        return "outside_24h"
    if run.get("within_24h") is None:
        return "missing_published_date"
    return None


def run_exact_verify_stage(
    *,
    args: argparse.Namespace,
    api_key: str,
    report_date: date,
    prefilter_candidates: list[dict[str, Any]],
    session: requests.Session,
) -> dict[str, Any]:
    start_date, end_date = report_window(report_date)
    verify_budget = max(0, min(args.max_verify_calls, args.max_total_calls))
    verify_runs: list[dict[str, Any]] = []
    verified_candidates: list[dict[str, Any]] = []
    rejected_candidates: list[dict[str, Any]] = []

    for index, candidate in enumerate(prefilter_candidates[:verify_budget], start=1):
        query = f'"{candidate["title"]}"'
        payload = {
            "query": query,
            "topic": "news",
            "search_depth": args.verify_search_depth,
            "max_results": DEFAULT_VERIFY_MAX_RESULTS,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "auto_parameters": False,
            "start_date": start_date,
            "end_date": end_date,
        }
        sample = {
            "sample_id": f"{report_date.isoformat()}::prefilter::{index}",
            "report_date": report_date.isoformat(),
            "source": candidate.get("source", ""),
            "title": candidate.get("title", ""),
            "link": candidate.get("link", ""),
        }

        try:
            result = search_tavily(session, api_key, payload, args.request_timeout)
            run = evaluate_verify_case(
                response_payload=result["response"],
                sample=sample,
                scenario="verify_exact",
                query=query,
                query_type="exact_title",
                search_depth=args.verify_search_depth,
                max_results=DEFAULT_VERIFY_MAX_RESULTS,
                started_payload={
                    "start_date": start_date,
                    "end_date": end_date,
                    "latency_ms": result["latency_ms"],
                },
            )
        except Exception as exc:
            run = failed_run_record(
                scenario="verify_exact",
                sample_id=sample["sample_id"],
                report_date=sample["report_date"],
                query=query,
                query_type="exact_title",
                search_depth=args.verify_search_depth,
                max_results=DEFAULT_VERIFY_MAX_RESULTS,
                start_date=start_date,
                end_date=end_date,
                error=str(exc),
            )

        accepted = bool(run.get("matched")) and run.get("within_24h") is True
        run["accepted"] = accepted
        run["rejection_reason"] = verify_rejection_reason(run)
        verify_runs.append(run)

        candidate_summary = {
            "title": candidate.get("title", ""),
            "source": candidate.get("source", ""),
            "link": candidate.get("link", ""),
            "matched_url": run.get("matched_url"),
            "matched_title": run.get("matched_title"),
            "within_24h": run.get("within_24h"),
            "title_similarity": run.get("title_similarity"),
            "rejection_reason": run.get("rejection_reason"),
        }
        if accepted:
            verified_candidates.append(candidate_summary)
        else:
            rejected_candidates.append(candidate_summary)

    return {
        "verify_budget": verify_budget,
        "verify_calls": len(verify_runs),
        "verify_skipped_due_budget": max(0, len(prefilter_candidates) - verify_budget),
        "verify_runs": verify_runs,
        "verified_candidates": verified_candidates,
        "rejected_candidates": rejected_candidates,
        "verified_count": len(verified_candidates),
        "rejected_count": len(rejected_candidates),
    }


def build_dynamic_existing_index(
    report_payload: dict[str, Any],
    extra_candidates: list[dict[str, Any]],
) -> dict[str, set[str]]:
    existing = build_existing_report_index(report_payload)
    titles = set(existing["titles"])
    urls = set(existing["urls"])
    domains = set(existing["domains"])
    for candidate in extra_candidates:
        title = candidate.get("title", "")
        url = candidate.get("url", "") or candidate.get("matched_url", "")
        normalized_title = normalize_title(title)
        canonical = canonical_url(url)
        domain = domain_of(url)
        if normalized_title:
            titles.add(normalized_title)
        if canonical:
            urls.add(canonical)
        if domain:
            domains.add(domain)
    return {"titles": titles, "urls": urls, "domains": domains}


def run_domain_refill_stage(
    *,
    args: argparse.Namespace,
    api_key: str,
    report_date: date,
    report_payload: dict[str, Any],
    session: requests.Session,
    prior_candidates: list[dict[str, Any]],
    remaining_budget: int,
    stage_name: str,
    query: str,
    include_domains: list[str],
) -> dict[str, Any]:
    refill_runs: list[dict[str, Any]] = []
    accepted_candidates: list[dict[str, Any]] = []
    near_duplicate_rejected_count = 0
    story_cluster_rejected_count = 0
    duplicate_slip_count = 0
    if args.max_refill_rounds <= 0 or remaining_budget <= 0:
        return {
            "refill_calls": 0,
            "refill_rounds_executed": 0,
            "accepted_candidates": accepted_candidates,
            "refill_runs": refill_runs,
            "media_refilled_count": 0,
            "near_duplicate_rejected_count": 0,
            "story_cluster_rejected_count": 0,
            "duplicate_slip_count": 0,
            "remaining_budget_after_refill": remaining_budget,
        }

    start_date, end_date = report_window(report_date)
    reference_dt = report_reference_dt(report_date)
    rounds_budget = min(args.max_refill_rounds, remaining_budget)
    for round_index in range(rounds_budget):
        payload = {
            "query": query,
            "topic": "news",
            "search_depth": DEFAULT_REFILL_SEARCH_DEPTH,
            "max_results": args.refill_max_results,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "auto_parameters": False,
            "include_domains": include_domains,
            "start_date": start_date,
            "end_date": end_date,
        }
        try:
            result = search_tavily(session, api_key, payload, args.request_timeout)
            response_payload = result["response"]
            latency_ms = result["latency_ms"]
            error = None
            results = response_payload.get("results", []) or []
        except Exception as exc:
            response_payload = {}
            latency_ms = None
            error = str(exc)
            results = []

        existing_index = build_dynamic_existing_index(
            report_payload,
            prior_candidates + accepted_candidates,
        )
        run_candidates: list[dict[str, Any]] = []
        round_accepted: list[dict[str, Any]] = []
        round_near_duplicate_rejected = 0
        round_story_cluster_rejected = 0
        round_duplicate_slip_count = 0
        seen_titles: set[str] = set()

        for index, result_item in enumerate(results, start=1):
            title = result_item.get("title", "")
            url = result_item.get("url", "")
            normalized_title = normalize_title(title)
            canonical = canonical_url(url)
            duplicate_existing = (
                normalized_title in existing_index["titles"]
                or canonical in existing_index["urls"]
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
            is_within = within_24h(result_item.get("published_date"), reference_dt)
            is_ai_relevant = ai_title_relevant(title)
            accepted = (
                bool(is_within)
                and is_ai_relevant
                and not duplicate_existing
                and not duplicate_within_results
                and not near_duplicate_existing
                and not story_cluster_existing
            )
            if near_duplicate_existing:
                round_near_duplicate_rejected += 1
            elif story_cluster_existing:
                round_story_cluster_rejected += 1
            candidate = {
                "rank": index,
                "title": title,
                "url": url,
                "domain": domain_of(url),
                "published_date": result_item.get("published_date"),
                "within_24h": is_within,
                "ai_title_relevant": is_ai_relevant,
                "duplicate_existing": duplicate_existing,
                "duplicate_within_results": duplicate_within_results,
                "near_duplicate_existing": near_duplicate_existing,
                "story_cluster_existing": story_cluster_existing,
                "cluster_match": cluster_match,
                "accepted": accepted,
                "score": result_item.get("score"),
            }
            run_candidates.append(candidate)
            if accepted:
                round_accepted.append(candidate)

        refill_runs.append(
            {
                "stage": stage_name,
                "round": round_index + 1,
                "query": query,
                "search_depth": DEFAULT_REFILL_SEARCH_DEPTH,
                "max_results": args.refill_max_results,
                "include_domains": include_domains,
                "start_date": start_date,
                "end_date": end_date,
                "latency_ms": latency_ms,
                "request_id": response_payload.get("request_id"),
                "tavily_response_time": response_payload.get("response_time"),
                "result_count": len(results),
                "accepted_count": len(round_accepted),
                "near_duplicate_rejected_count": round_near_duplicate_rejected,
                "story_cluster_rejected_count": round_story_cluster_rejected,
                "duplicate_slip_count": round_duplicate_slip_count,
                "candidate_results": run_candidates,
                "error": error,
            }
        )
        accepted_candidates.extend(round_accepted)
        near_duplicate_rejected_count += round_near_duplicate_rejected
        story_cluster_rejected_count += round_story_cluster_rejected
        duplicate_slip_count += round_duplicate_slip_count
        if error:
            break

    return {
        "refill_calls": len(refill_runs),
        "refill_rounds_executed": len(refill_runs),
        "accepted_candidates": accepted_candidates,
        "refill_runs": refill_runs,
        "media_refilled_count": len(accepted_candidates),
        "near_duplicate_rejected_count": near_duplicate_rejected_count,
        "story_cluster_rejected_count": story_cluster_rejected_count,
        "duplicate_slip_count": duplicate_slip_count,
        "remaining_budget_after_refill": max(0, remaining_budget - len(refill_runs)),
    }


def run_priority_refill_stage(
    *,
    args: argparse.Namespace,
    api_key: str,
    report_date: date,
    report_payload: dict[str, Any],
    session: requests.Session,
    prior_candidates: list[dict[str, Any]],
    remaining_budget: int,
) -> dict[str, Any]:
    return run_domain_refill_stage(
        args=args,
        api_key=api_key,
        report_date=report_date,
        report_payload=report_payload,
        session=session,
        prior_candidates=prior_candidates,
        remaining_budget=remaining_budget,
        stage_name="priority_refill",
        query=DEFAULT_MEDIA_REFILL_QUERY,
        include_domains=DEFAULT_PRIORITY_REFILL_MEDIA_WHITELIST,
    )


def run_secondary_refill_stage(
    *,
    args: argparse.Namespace,
    api_key: str,
    report_date: date,
    report_payload: dict[str, Any],
    session: requests.Session,
    prior_candidates: list[dict[str, Any]],
    remaining_budget: int,
) -> dict[str, Any]:
    return run_domain_refill_stage(
        args=args,
        api_key=api_key,
        report_date=report_date,
        report_payload=report_payload,
        session=session,
        prior_candidates=prior_candidates,
        remaining_budget=remaining_budget,
        stage_name="secondary_refill",
        query=DEFAULT_MEDIA_REFILL_QUERY,
        include_domains=DEFAULT_SECONDARY_REFILL_CANDIDATE_DOMAINS,
    )


def run_official_fallback_stage(
    *,
    args: argparse.Namespace,
    api_key: str,
    report_date: date,
    report_payload: dict[str, Any],
    session: requests.Session,
    prior_candidates: list[dict[str, Any]],
    remaining_budget: int,
) -> dict[str, Any]:
    return run_domain_refill_stage(
        args=args,
        api_key=api_key,
        report_date=report_date,
        report_payload=report_payload,
        session=session,
        prior_candidates=prior_candidates,
        remaining_budget=remaining_budget,
        stage_name="official_fallback",
        query=DEFAULT_OFFICIAL_FALLBACK_QUERY,
        include_domains=DEFAULT_OFFICIAL_FALLBACK_DOMAINS,
    )


def build_scaffold_payload(
    *,
    args: argparse.Namespace,
    api_key: str | None,
    selected_dates: list[date],
    reports: dict[date, dict[str, Any]],
) -> dict[str, Any]:
    session = requests.Session() if api_key else None
    report_results: list[dict[str, Any]] = []
    for report_date in selected_dates:
        report_stub = build_report_stub(report_date, reports[report_date])
        prefilter = build_prefilter_summary(reports[report_date])
        prefilter_clusters = annotate_story_clusters(prefilter["prefilter_candidates"])
        verify_cluster_view = collapse_prefilter_candidates_for_verify(
            prefilter_clusters["annotated_candidates"]
        )
        report_stub["prefiltered_count"] = prefilter["prefiltered_count"]
        report_stub["prefilter_stats"] = prefilter["prefilter_stats"]
        report_stub["prefilter_candidates"] = prefilter_clusters["annotated_candidates"]
        report_stub["excluded_prefilter_candidates"] = prefilter[
            "excluded_prefilter_candidates"
        ]
        report_stub["cluster_count"] = prefilter_clusters["cluster_count"]
        report_stub["clustered_prefilter_count"] = prefilter_clusters[
            "clustered_candidate_count"
        ]
        report_stub["cluster_potential_verify_saved_calls"] = prefilter_clusters[
            "cluster_potential_verify_saved_calls"
        ]
        report_stub["cluster_skipped_prefilter_candidates"] = verify_cluster_view[
            "skipped_candidates"
        ]
        report_stub["cluster_diagnostics"] = prefilter_clusters["cluster_diagnostics"]
        report_stub["notes"].append(
            "Local prefilter completed before any Tavily refill attempt."
        )
        if api_key and session is not None:
            verify = run_exact_verify_stage(
                args=args,
                api_key=api_key,
                report_date=report_date,
                prefilter_candidates=verify_cluster_view["verify_candidates"],
                session=session,
            )
            baseline_verify_calls = min(
                len(prefilter_clusters["annotated_candidates"]),
                max(0, min(args.max_verify_calls, args.max_total_calls)),
            )
            report_stub["verify_saved_calls"] = max(
                0, baseline_verify_calls - verify["verify_calls"]
            )
            report_stub["verify_calls"] = verify["verify_calls"]
            report_stub["total_calls"] = verify["verify_calls"]
            report_stub["verified_count"] = verify["verified_count"]
            report_stub["final_count"] = verify["verified_count"]
            report_stub["verify_budget"] = verify["verify_budget"]
            report_stub["verify_skipped_due_budget"] = verify[
                "verify_skipped_due_budget"
            ]
            report_stub["verify_runs"] = verify["verify_runs"]
            report_stub["verified_candidates"] = verify["verified_candidates"]
            report_stub["rejected_candidates"] = verify["rejected_candidates"]
            remaining_budget = max(0, args.max_total_calls - report_stub["total_calls"])
            priority_refill = run_priority_refill_stage(
                args=args,
                api_key=api_key,
                report_date=report_date,
                report_payload=reports[report_date],
                session=session,
                prior_candidates=verify["verified_candidates"],
                remaining_budget=remaining_budget,
            )
            report_stub["refill_calls"] = priority_refill["refill_calls"]
            report_stub["total_calls"] += priority_refill["refill_calls"]
            report_stub["priority_refilled_count"] = priority_refill[
                "media_refilled_count"
            ]
            report_stub["media_refilled_count"] = priority_refill[
                "media_refilled_count"
            ]
            report_stub["near_duplicate_rejected_count"] = priority_refill[
                "near_duplicate_rejected_count"
            ]
            report_stub["story_cluster_rejected_count"] = priority_refill[
                "story_cluster_rejected_count"
            ]
            report_stub["final_count"] = (
                report_stub["verified_count"] + report_stub["priority_refilled_count"]
            )
            report_stub["priority_refill_runs"] = priority_refill["refill_runs"]
            report_stub["priority_refilled_candidates"] = priority_refill[
                "accepted_candidates"
            ]
            report_stub["media_refill_runs"] = priority_refill["refill_runs"]
            report_stub["media_refilled_candidates"] = priority_refill[
                "accepted_candidates"
            ]
            remaining_budget = priority_refill["remaining_budget_after_refill"]
            secondary_refill_executed = False
            if remaining_budget > 0 and report_stub["final_count"] < args.min_articles:
                secondary_refill = run_secondary_refill_stage(
                    args=args,
                    api_key=api_key,
                    report_date=report_date,
                    report_payload=reports[report_date],
                    session=session,
                    prior_candidates=(
                        verify["verified_candidates"]
                        + priority_refill["accepted_candidates"]
                    ),
                    remaining_budget=remaining_budget,
                )
                secondary_refill_executed = secondary_refill["refill_calls"] > 0
                report_stub["refill_calls"] += secondary_refill["refill_calls"]
                report_stub["total_calls"] += secondary_refill["refill_calls"]
                report_stub["secondary_refilled_count"] = secondary_refill[
                    "media_refilled_count"
                ]
                report_stub["near_duplicate_rejected_count"] += secondary_refill[
                    "near_duplicate_rejected_count"
                ]
                report_stub["story_cluster_rejected_count"] += secondary_refill[
                    "story_cluster_rejected_count"
                ]
                report_stub["secondary_duplicate_slip_count"] = secondary_refill[
                    "duplicate_slip_count"
                ]
                report_stub["media_refilled_count"] += report_stub[
                    "secondary_refilled_count"
                ]
                report_stub["final_count"] += report_stub["secondary_refilled_count"]
                report_stub["secondary_refill_runs"] = secondary_refill["refill_runs"]
                report_stub["secondary_refilled_candidates"] = secondary_refill[
                    "accepted_candidates"
                ]
                remaining_budget = secondary_refill["remaining_budget_after_refill"]
            if (
                args.enable_official_fallback
                and remaining_budget > 0
                and report_stub["final_count"] < args.min_articles
            ):
                official = run_official_fallback_stage(
                    args=args,
                    api_key=api_key,
                    report_date=report_date,
                    report_payload=reports[report_date],
                    session=session,
                    prior_candidates=(
                        verify["verified_candidates"]
                        + priority_refill["accepted_candidates"]
                        + report_stub.get("secondary_refilled_candidates", [])
                    ),
                    remaining_budget=remaining_budget,
                )
                report_stub["fallback_calls"] = official["refill_calls"]
                report_stub["total_calls"] += official["refill_calls"]
                report_stub["official_refilled_count"] = official[
                    "media_refilled_count"
                ]
                report_stub["near_duplicate_rejected_count"] += official[
                    "near_duplicate_rejected_count"
                ]
                report_stub["story_cluster_rejected_count"] += official[
                    "story_cluster_rejected_count"
                ]
                report_stub["final_count"] += report_stub["official_refilled_count"]
                report_stub["official_fallback_runs"] = official["refill_runs"]
                report_stub["official_refilled_candidates"] = official[
                    "accepted_candidates"
                ]
                remaining_budget = official["remaining_budget_after_refill"]
                if (
                    remaining_budget <= 0
                    and report_stub["final_count"] < args.min_articles
                ):
                    report_stub["stop_reason"] = (
                        "budget_exhausted_after_official_fallback"
                    )
                else:
                    report_stub["stop_reason"] = "official_fallback_complete"
            elif (
                remaining_budget <= 0 and report_stub["final_count"] < args.min_articles
            ):
                report_stub["stop_reason"] = (
                    "budget_exhausted_after_secondary_refill"
                    if secondary_refill_executed
                    else "budget_exhausted_after_priority_refill"
                )
            elif (
                not args.enable_official_fallback
                and report_stub["final_count"] < args.min_articles
            ):
                report_stub["stop_reason"] = "official_fallback_disabled"
            else:
                report_stub["stop_reason"] = (
                    "secondary_refill_complete"
                    if secondary_refill_executed
                    else "priority_refill_complete"
                )
            report_stub["notes"].append("Exact verify and staged refill completed.")
            if args.enable_official_fallback:
                report_stub["notes"].append(
                    "Official fallback was allowed for this run when budget remained."
                )
            else:
                report_stub["notes"].append(
                    "Official fallback was disabled for this run."
                )
        else:
            report_stub["stop_reason"] = "prefilter_only"
            report_stub["notes"].append(
                "No Tavily API key available, so verify/refill stages were skipped."
            )
        report_stub["accepted_by_stage_preview"] = {
            "verify": sample_titles(report_stub.get("verified_candidates", [])),
            "priority_refill": sample_titles(
                report_stub.get("priority_refilled_candidates", [])
            ),
            "secondary_refill": sample_titles(
                report_stub.get("secondary_refilled_candidates", [])
            ),
            "official_fallback": sample_titles(
                report_stub.get("official_refilled_candidates", [])
            ),
        }
        report_results.append(report_stub)

    return {
        "generated_at": datetime.now(tz=REPORT_TIMEZONE).isoformat(),
        "mode": "experimental_dry_run",
        "focus": "Replay harness only; no production integration",
        "boundaries": {
            "production_integration": False,
            "modifies_main_py": False,
            "modifies_summarizer_py": False,
            "official_fallback_enabled": args.enable_official_fallback,
            "fuzzy_second_pass_enabled": args.enable_fuzzy_second_pass,
        },
        "parameters": {
            "min_articles": args.min_articles,
            "max_total_calls": args.max_total_calls,
            "max_verify_calls": args.max_verify_calls,
            "max_refill_rounds": args.max_refill_rounds,
            "refill_max_results": args.refill_max_results,
            "verify_search_depth": args.verify_search_depth,
            "verify_max_results": DEFAULT_VERIFY_MAX_RESULTS,
            "priority_refill_media_whitelist": DEFAULT_PRIORITY_REFILL_MEDIA_WHITELIST,
            "secondary_refill_candidate_domains": DEFAULT_SECONDARY_REFILL_CANDIDATE_DOMAINS,
            "official_fallback_domains": DEFAULT_OFFICIAL_FALLBACK_DOMAINS,
        },
        "selected_report_dates": [
            report_date.isoformat() for report_date in selected_dates
        ],
        "report_results": report_results,
    }


def sample_titles(candidates: list[dict[str, Any]], limit: int = 3) -> list[str]:
    titles: list[str] = []
    for candidate in candidates:
        title = candidate.get("title")
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def build_markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Tavily News Enrichment Dry Run",
        "",
        "## Scope",
        "",
        "- Experimental replay harness only; no production integration was performed.",
        "- Exact verify uses the current experimental default depth.",
        "- Refill uses staged priority + secondary domain paths; official fallback is optional and may be disabled.",
        "",
        "## Run Summary",
        "",
        "| Report Date | Raw | Deduped | Prefiltered | Verify Calls | Refill Calls | Fallback Calls | Verified | Media Refilled | Official Refilled | Final | Stop Reason |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in payload.get("report_results", []):
        lines.append(
            f"| {result['report_date']} | {result['raw_count']} | {result['deduped_count']} | "
            f"{result['prefiltered_count']} | {result['verify_calls']} | {result['refill_calls']} | "
            f"{result['fallback_calls']} | {result['verified_count']} | {result['media_refilled_count']} | "
            f"{result['official_refilled_count']} | {result['final_count']} | {result['stop_reason']} |"
        )

    for result in payload.get("report_results", []):
        lines.extend(
            [
                "",
                f"## {result['report_date']}",
                "",
                f"- Input date: `{result['report_date']}`",
                f"- raw_count / deduped_count / prefiltered_count: "
                f"`{result['raw_count']}` / `{result['deduped_count']}` / `{result['prefiltered_count']}`",
                f"- cluster_count / clustered_prefilter_count / potential_verify_saved_calls / verify_saved_calls: "
                f"`{result.get('cluster_count', 0)}` / "
                f"`{result.get('clustered_prefilter_count', 0)}` / "
                f"`{result.get('cluster_potential_verify_saved_calls', 0)}` / "
                f"`{result.get('verify_saved_calls', 0)}`",
                f"- verify_calls / refill_calls / fallback_calls / total_calls: "
                f"`{result['verify_calls']}` / `{result['refill_calls']}` / "
                f"`{result['fallback_calls']}` / `{result['total_calls']}`",
                f"- near_duplicate_rejected_count / story_cluster_rejected_count: "
                f"`{result.get('near_duplicate_rejected_count', 0)}` / "
                f"`{result.get('story_cluster_rejected_count', 0)}`",
                f"- priority_refilled_count / secondary_refilled_count / secondary_duplicate_slip_count: "
                f"`{result.get('priority_refilled_count', 0)}` / "
                f"`{result.get('secondary_refilled_count', 0)}` / "
                f"`{result.get('secondary_duplicate_slip_count', 0)}`",
                f"- verified_count / media_refilled_count / official_refilled_count / final_count: "
                f"`{result['verified_count']}` / `{result['media_refilled_count']}` / "
                f"`{result['official_refilled_count']}` / `{result['final_count']}`",
                f"- stop_reason: `{result['stop_reason']}`",
            ]
        )
        verified_titles = sample_titles(result.get("verified_candidates", []))
        priority_titles = sample_titles(result.get("priority_refilled_candidates", []))
        secondary_titles = sample_titles(
            result.get("secondary_refilled_candidates", [])
        )
        official_titles = sample_titles(result.get("official_refilled_candidates", []))
        if verified_titles:
            lines.append(f"- Verified samples: {'; '.join(verified_titles)}")
        if priority_titles:
            lines.append(f"- Priority refill samples: {'; '.join(priority_titles)}")
        if secondary_titles:
            lines.append(f"- Secondary refill samples: {'; '.join(secondary_titles)}")
        if official_titles:
            lines.append(f"- Official fallback samples: {'; '.join(official_titles)}")
        stage_preview = result.get("accepted_by_stage_preview", {})
        lines.append(
            "- accepted_by_stage_preview: "
            f"verify={'; '.join(stage_preview.get('verify', [])) or '(none)'} | "
            f"priority_refill={'; '.join(stage_preview.get('priority_refill', [])) or '(none)'} | "
            f"secondary_refill={'; '.join(stage_preview.get('secondary_refill', [])) or '(none)'} | "
            f"official_fallback={'; '.join(stage_preview.get('official_fallback', [])) or '(none)'}"
        )
        cluster_diagnostics = result.get("cluster_diagnostics", [])
        if cluster_diagnostics:
            for cluster in cluster_diagnostics:
                alternate_titles = [
                    alternate.get("title", "")
                    for alternate in cluster.get("alternates", [])
                    if alternate.get("title")
                ]
                alternates_preview = (
                    "; ".join(alternate_titles) if alternate_titles else "(none)"
                )
                lines.append(
                    f"- {cluster['cluster_id']}: representative="
                    f"{cluster['cluster_representative'].get('title', '')}; "
                    f"alternates={alternates_preview}"
                )
        else:
            lines.append("- Cluster diagnostics: none")

    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    data_dir = (REPO_ROOT / args.data_dir).resolve()
    reports = load_reports(data_dir)
    requested_dates = parse_requested_dates(args.report_date)
    selected_dates = select_report_dates(reports, requested_dates)
    output_path = default_output_path(args.output)
    api_key = load_api_key()
    payload = build_scaffold_payload(
        args=args,
        api_key=api_key,
        selected_dates=selected_dates,
        reports=reports,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path = output_path.with_suffix(".md")
    markdown_path.write_text(build_markdown_report(payload), encoding="utf-8")

    print(f"Experimental dry run written to: {output_path}")
    print(f"Markdown summary written to: {markdown_path}")
    print(f"Selected report dates: {', '.join(payload['selected_report_dates'])}")


if __name__ == "__main__":
    main()
