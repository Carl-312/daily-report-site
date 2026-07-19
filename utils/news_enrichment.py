"""
Tavily-based post-fetch news enrichment for the formal pipeline.

This module keeps the production integration isolated from the experiment
scripts while reusing the same verified enrichment strategy.
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from sources.base import Article
from utils.editorial_catalog import analyze_editorial_text
from utils.enrichment_policy import decide_enrichment
from utils.enrichment_transport import (
    TavilyTransport,
    classify_request_outcome as classify_transport_outcome,
)
from utils.run_contracts import RunDeadlineExceeded, scrub_diagnostic
from utils.story_quality import partition_articles_for_publication

REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
REFILL_SEARCH_DEPTH = "advanced"
VERIFY_MAX_RESULTS = 3
TITLE_SIMILARITY_MATCH_THRESHOLD = 0.82
REQUEST_TIMEOUT_SECONDS = 45
REFILL_STAGE_NAMES = (
    "priority_refill",
    "secondary_refill",
    "official_fallback",
)

NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")
TRAILING_SOURCE_SUFFIX_RE = re.compile(r"\s+-\s+[A-Za-z0-9&.' ]+$")
STORY_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+._-]*")

AGGREGATE_SOURCE_KEYS = {"aibase"}
AGGREGATE_TITLE_PREFIXES = ("ai日报",)
NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.82
STORY_CLUSTER_MIN_SHARED_TOKENS = 3
STORY_CLUSTER_MIN_OVERLAP_RATIO = 0.35
PREFILTER_BUCKETS = ("core_ai", "ai_neighbor", "generic_or_low_signal")
PREFILTER_BUCKET_RANK = {bucket: rank for rank, bucket in enumerate(PREFILTER_BUCKETS)}

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


def article_to_dict(article: Article | dict[str, Any]) -> dict[str, Any]:
    if isinstance(article, Article):
        return article.to_dict()
    return dict(article)


def normalize_title(title: str) -> str:
    cleaned = NON_WORD_RE.sub(" ", (title or "").strip().lower())
    return SPACE_RE.sub(" ", cleaned).strip()


def title_similarity(left: str, right: str) -> float:
    return round(
        SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio(), 4
    )


def domain_of(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:
        return ""


def canonical_url(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return ""
    netloc = parsed.netloc.lower()
    path = (parsed.path or "").rstrip("/")
    return f"{netloc}{path}"


def parse_published_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=REPORT_TIMEZONE)
    return parsed.astimezone(REPORT_TIMEZONE)


def within_strict_hours(
    published_date: str | None,
    *,
    reference_dt: datetime,
    strict_hours: int,
) -> bool | None:
    published_dt = parse_published_datetime(published_date)
    if published_dt is None:
        return None
    earliest = reference_dt - timedelta(hours=strict_hours)
    return earliest <= published_dt <= reference_dt


def report_window(reference_dt: datetime, *, window_hours: int = 24) -> tuple[str, str]:
    window_hours = max(1, int(window_hours or 24))
    return (
        (reference_dt - timedelta(hours=window_hours)).date().isoformat(),
        reference_dt.date().isoformat(),
    )


def refill_request_window_hours(settings: Any) -> int:
    configured_hours = int(getattr(settings, "refill_search_window_hours", 24) or 24)
    if getattr(settings, "lenient_refill_diagnostics_enabled", False):
        diagnostic_hours = int(
            getattr(settings, "lenient_refill_window_hours", 72) or 72
        )
        return max(configured_hours, diagnostic_hours)
    return configured_hours


def configured_query_pack(
    settings: Any, *, plural_name: str, singular_name: str
) -> list[str]:
    """Use structured query packs while preserving singular config replay."""

    configured = getattr(settings, plural_name, None) or []
    queries = [str(query).strip() for query in configured if str(query).strip()]
    if queries:
        return queries
    singular = str(getattr(settings, singular_name, "") or "").strip()
    return [singular] if singular else []


def is_aggregate_like(article: dict[str, Any]) -> bool:
    source = (article.get("source", "") or "").strip().lower()
    title = (article.get("title", "") or "").strip().lower()
    if source in AGGREGATE_SOURCE_KEYS:
        return True
    if any(title.startswith(prefix) for prefix in AGGREGATE_TITLE_PREFIXES):
        return True
    return title.count("；") >= 2 or title.count(";") >= 2


def ai_title_relevant(title: str) -> bool:
    return analyze_editorial_text(title).relevance_level >= 2


def classify_prefilter_bucket(title: str) -> str:
    analysis = analyze_editorial_text(title)
    if analysis.relevance_level >= 3 or analysis.core_ai_signal:
        return "core_ai"
    if analysis.relevance_level >= 2 or analysis.neighbor_signal:
        return "ai_neighbor"
    return "generic_or_low_signal"


def empty_prefilter_bucket_counts() -> dict[str, int]:
    return {bucket: 0 for bucket in PREFILTER_BUCKETS}


def sort_candidates_by_prefilter_bucket(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda candidate: (
            PREFILTER_BUCKET_RANK.get(
                candidate.get("prefilter_bucket", "generic_or_low_signal"),
                len(PREFILTER_BUCKETS),
            ),
            candidate.get("index", 0),
        ),
    )


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
                    "left_title": left_candidate.get("title", ""),
                    "right_title": annotated_candidates[right_index].get("title", ""),
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
                    "link": candidate.get("link", ""),
                }
            )
        cluster_diagnostics.append(
            {
                "cluster_id": cluster_id,
                "cluster_size": len(indices),
                "cluster_representative": {
                    "title": representative_title,
                    "source": representative.get("source", ""),
                    "link": representative.get("link", ""),
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
                "prefilter_bucket": candidate.get("prefilter_bucket"),
                "cluster_id": cluster_id,
                "cluster_representative_title": candidate.get(
                    "cluster_representative_title", ""
                ),
            }
        )
    return {
        "verify_candidates": verify_candidates,
        "skipped_candidates": skipped_candidates,
    }


def build_existing_index(articles: list[dict[str, Any]]) -> dict[str, set[str]]:
    return {
        "titles": {normalize_title(article.get("title", "")) for article in articles},
        "urls": {canonical_url(article.get("link", "")) for article in articles},
    }


def build_dynamic_existing_index(
    base_articles: list[dict[str, Any]],
    extra_candidates: list[dict[str, Any]],
) -> dict[str, set[str]]:
    existing = build_existing_index(base_articles)
    titles = set(existing["titles"])
    urls = set(existing["urls"])
    for candidate in extra_candidates:
        title = candidate.get("title", "")
        url = candidate.get("link", "") or candidate.get("url", "")
        normalized_title = normalize_title(title)
        canonical = canonical_url(url)
        if normalized_title:
            titles.add(normalized_title)
        if canonical:
            urls.add(canonical)
    return {"titles": titles, "urls": urls}


def search_tavily(
    session: requests.Session,
    api_key: str,
    payload: dict[str, Any],
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    deadline_at: datetime | None = None,
) -> dict[str, Any]:
    return TavilyTransport(
        session,
        api_key,
        deadline_at=deadline_at,
        default_timeout=timeout,
    ).search(payload)


def _search_tavily_with_deadline(
    session: requests.Session,
    api_key: str,
    payload: dict[str, Any],
    deadline_at: datetime | None,
) -> dict[str, Any]:
    """Keep legacy test doubles/callers compatible when no deadline is set."""
    if deadline_at is None:
        return search_tavily(session, api_key, payload)
    return search_tavily(session, api_key, payload, deadline_at=deadline_at)


def classify_request_outcome(error: Exception | None) -> str:
    if isinstance(error, RunDeadlineExceeded):
        return "deadline_exceeded"
    return classify_transport_outcome(error)


def pick_best_match(
    results: list[dict[str, Any]],
    *,
    expected_title: str,
    expected_url: str,
) -> dict[str, Any] | None:
    expected_canonical = canonical_url(expected_url)
    expected_domain = domain_of(expected_url)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, result in enumerate(results):
        result_url = result.get("url", "")
        result_title = result.get("title", "")
        exact_url = expected_canonical == canonical_url(result_url) and bool(
            expected_canonical
        )
        same_domain = domain_of(result_url) == expected_domain and bool(expected_domain)
        similarity = title_similarity(expected_title, result_title)
        score = (
            (10 if exact_url else 0)
            + (2 if same_domain else 0)
            + similarity
            - (index * 0.01)
        )
        ranked.append(
            (
                score,
                {
                    "rank": index + 1,
                    "title": result_title,
                    "url": result_url,
                    "exact_url_match": exact_url,
                    "same_domain": same_domain,
                    "title_similarity": similarity,
                    "published_date": result.get("published_date"),
                    "score": result.get("score"),
                },
            )
        )
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1]


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


def build_prefilter_summary(articles: list[dict[str, Any]]) -> dict[str, Any]:
    included_candidates: list[dict[str, Any]] = []
    excluded_candidates: list[dict[str, Any]] = []
    bucket_counts = empty_prefilter_bucket_counts()
    stats = {
        "total_articles": len(articles),
        "eligible_candidates": 0,
        "excluded_missing_title": 0,
        "excluded_missing_link": 0,
        "excluded_aggregate_like": 0,
        "excluded_non_ai_relevant": 0,
        "soft_non_ai_relevant": 0,
    }
    for index, article in enumerate(articles, start=1):
        title = (article.get("title", "") or "").strip()
        link = (article.get("link", "") or "").strip()
        aggregate_like = is_aggregate_like(article)
        core_ai_relevant = ai_title_relevant(title)
        prefilter_bucket = classify_prefilter_bucket(title)
        ai_relevant = prefilter_bucket != "generic_or_low_signal"
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

        candidate = {
            "index": index,
            "source": article.get("source", ""),
            "title": title,
            "link": link,
            "publish_time": article.get("publish_time", ""),
            "aggregate_like": aggregate_like,
            "ai_relevant": ai_relevant,
            "core_ai_relevant": core_ai_relevant,
            "prefilter_bucket": prefilter_bucket,
            "exclude_reasons": reasons,
            "article": dict(article),
        }
        if reasons:
            excluded_candidates.append(candidate)
            continue
        stats["eligible_candidates"] += 1
        if not ai_relevant:
            stats["soft_non_ai_relevant"] += 1
        bucket_counts[prefilter_bucket] += 1
        included_candidates.append(candidate)

    included_candidates = sort_candidates_by_prefilter_bucket(included_candidates)
    return {
        "prefiltered_count": len(included_candidates),
        "prefilter_stats": stats,
        "prefilter_bucket_counts": bucket_counts,
        "prefilter_candidates": included_candidates,
        "excluded_prefilter_candidates": excluded_candidates,
    }


def build_initial_report(
    *,
    report_date: str,
    reference_dt: datetime,
    articles: list[dict[str, Any]],
    enabled: bool,
    settings: Any,
) -> dict[str, Any]:
    return {
        "report_date": report_date,
        "reference_dt": reference_dt.isoformat(),
        "enabled": enabled,
        "applied": False,
        "skip_reason": None,
        "error": None,
        "input_count": len(articles),
        "input_story_count": 0,
        "input_lead_count": 0,
        "lead_resolution_calls": 0,
        "lead_resolved_count": 0,
        "lead_unresolved_count": 0,
        "lead_resolution_runs": [],
        "lead_terminal_error_code": None,
        "observation_signals": [],
        "publishability_rejected": [],
        "stage_failures": [],
        "prefiltered_count": len(articles),
        "prefilter_stats": {},
        "prefilter_bucket_counts": empty_prefilter_bucket_counts(),
        "verify_calls": 0,
        "refill_calls": 0,
        "fallback_calls": 0,
        "total_calls": 0,
        "cluster_count": 0,
        "clustered_prefilter_count": 0,
        "cluster_potential_verify_saved_calls": 0,
        "verify_saved_calls": 0,
        "reserved_refill_calls": 0,
        "verified_count": 0,
        "neighbor_candidates_verified_count": 0,
        "neighbor_candidates_outside_24h_count": 0,
        "neighbor_candidates_no_match_count": 0,
        "preserved_error_count": 0,
        "preserved_budget_count": 0,
        "priority_refilled_count": 0,
        "secondary_refilled_count": 0,
        "media_refilled_count": 0,
        "official_refilled_count": 0,
        "refill_needed_count": 0,
        "refill_remaining_count": 0,
        "near_duplicate_rejected_count": 0,
        "story_cluster_rejected_count": 0,
        "secondary_duplicate_slip_count": 0,
        "final_count": len(articles),
        "strict_final_count": len(articles),
        "strict_refill_accepted_count": 0,
        "lenient_candidate_count": 0,
        "proven_within_72h_count": 0,
        "missing_date_unproven_count": 0,
        "outside_72h_rejected_count": 0,
        "lenient_non_ai_count": 0,
        "lenient_duplicate_or_cluster_count": 0,
        "lenient_selected_preview": [],
        "lenient_refill_diagnostics": {
            "enabled": bool(
                getattr(settings, "lenient_refill_diagnostics_enabled", False)
            ),
            "window_hours": int(
                getattr(settings, "lenient_refill_window_hours", 72) or 72
            ),
            "request_window_hours": refill_request_window_hours(settings),
            "start_date": None,
            "end_date": None,
            "stages": {},
        },
        "stop_reason": "not_started",
        "priority_refill_runs": [],
        "secondary_refill_runs": [],
        "official_fallback_runs": [],
        "priority_refilled_candidates": [],
        "secondary_refilled_candidates": [],
        "official_refilled_candidates": [],
        "accepted_by_stage_preview": {},
        "parameters": {
            "min_articles": settings.min_articles,
            "strict_hours": settings.strict_hours,
            "trust_env": settings.trust_env,
            "max_total_calls": settings.max_total_calls,
            "max_verify_calls": settings.max_verify_calls,
            "max_refill_rounds": settings.max_refill_rounds,
            "refill_max_results": settings.refill_max_results,
            "refill_search_window_hours": getattr(
                settings, "refill_search_window_hours", 24
            ),
            "verify_search_depth": settings.verify_search_depth,
            "verify_max_results": VERIFY_MAX_RESULTS,
            "max_lead_candidates": int(getattr(settings, "max_lead_candidates", 5)),
            "lead_search_rounds": int(getattr(settings, "lead_search_rounds", 2)),
            "lead_search_depth": str(
                getattr(settings, "lead_search_depth", "advanced")
            ),
            "lead_max_age_hours": int(getattr(settings, "lead_max_age_hours", 72)),
            "priority_refill_media_whitelist": list(
                settings.trusted_domains.priority_refill_media_whitelist
            ),
            "secondary_refill_candidate_domains": list(
                settings.trusted_domains.secondary_refill_candidate_domains
            ),
            "official_fallback_domains": list(
                settings.trusted_domains.official_fallback_domains
            ),
            "enable_fuzzy_second_pass": settings.enable_fuzzy_second_pass,
            "enable_official_fallback": settings.enable_official_fallback,
            "lenient_refill_diagnostics_enabled": bool(
                getattr(settings, "lenient_refill_diagnostics_enabled", False)
            ),
            "lenient_refill_window_hours": int(
                getattr(settings, "lenient_refill_window_hours", 72) or 72
            ),
        },
        "notes": [],
    }


def update_stage_failures(report: dict[str, Any]) -> None:
    """Expose stable, non-secret error codes for reader-visible diagnostics."""

    counts: dict[tuple[str, str], int] = {}
    skip_reason = report.get("skip_reason")
    if skip_reason == "missing_api_key":
        counts[("enrichment", "missing_api_key")] = 1
    elif skip_reason == "enrichment_error":
        counts[
            ("enrichment", str(report.get("terminal_error_code") or "enrichment_error"))
        ] = 1
    for report_key, default_stage in (
        ("lead_resolution_runs", "lead_resolution"),
        ("verify_runs", "verify"),
        ("priority_refill_runs", "priority_refill"),
        ("secondary_refill_runs", "secondary_refill"),
        ("official_fallback_runs", "official_fallback"),
    ):
        for run in report.get(report_key, []) or []:
            outcome = str(run.get("request_outcome") or "")
            if not outcome or outcome == "success":
                continue
            stage = str(run.get("stage") or default_stage)
            counts[(stage, outcome)] = counts.get((stage, outcome), 0) + 1
    report["stage_failures"] = [
        {"stage": stage, "code": code, "count": count}
        for (stage, code), count in sorted(counts.items())
    ]


def sample_titles(candidates: list[dict[str, Any]], limit: int = 3) -> list[str]:
    titles: list[str] = []
    for candidate in candidates:
        title = candidate.get("title")
        if title:
            titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def below_min_stop_reason(*, secondary_refill_executed: bool) -> str:
    if secondary_refill_executed:
        return "below_min_articles_after_secondary_refill_official_fallback_disabled"
    return "below_min_articles_after_priority_refill_official_fallback_disabled"


def empty_refill_result(remaining_budget: int) -> dict[str, Any]:
    return {
        "refill_calls": 0,
        "accepted_candidates": [],
        "refill_runs": [],
        "media_refilled_count": 0,
        "near_duplicate_rejected_count": 0,
        "story_cluster_rejected_count": 0,
        "duplicate_slip_count": 0,
        "remaining_budget_after_refill": remaining_budget,
    }


def stage_candidate_results(
    report: dict[str, Any], stage_name: str
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for run in report.get(f"{stage_name}_runs", []) or []:
        candidates.extend(run.get("candidate_results") or [])
    return candidates


def summarize_lenient_stage(
    report: dict[str, Any],
    stage_name: str,
    *,
    window_hours: int,
) -> dict[str, Any]:
    runs = report.get(f"{stage_name}_runs", []) or []
    candidates = stage_candidate_results(report, stage_name)
    lenient_candidates = [
        candidate for candidate in candidates if candidate.get("lenient_candidate")
    ]
    duplicate_or_cluster = [
        candidate
        for candidate in lenient_candidates
        if candidate.get("duplicate_existing")
        or candidate.get("duplicate_within_results")
        or candidate.get("near_duplicate_existing")
        or candidate.get("story_cluster_existing")
    ]
    return {
        "window_hours": window_hours,
        "start_date": next(
            (run.get("start_date") for run in runs if run.get("start_date")),
            None,
        ),
        "end_date": next(
            (run.get("end_date") for run in runs if run.get("end_date")),
            None,
        ),
        "result_count": sum(int(run.get("result_count") or 0) for run in runs),
        "lenient_candidate_count": len(lenient_candidates),
        "proven_within_window_count": sum(
            1
            for candidate in lenient_candidates
            if candidate.get("lenient_within_window") is True
        ),
        "missing_date_unproven_count": sum(
            1 for candidate in lenient_candidates if not candidate.get("published_date")
        ),
        "outside_window_rejected_count": sum(
            1
            for candidate in candidates
            if candidate.get("lenient_within_window") is False
        ),
        "lenient_non_ai_count": sum(
            1
            for candidate in lenient_candidates
            if candidate.get("ai_title_relevant") is False
        ),
        "lenient_duplicate_or_cluster_count": len(duplicate_or_cluster),
        "lenient_selected_preview": [
            {
                "title": candidate.get("title", ""),
                "domain": candidate.get("domain", ""),
                "published_date": candidate.get("published_date"),
                "proven_within_window": candidate.get("lenient_within_window"),
                "ai_title_relevant": candidate.get("ai_title_relevant"),
                "duplicate_or_cluster": candidate in duplicate_or_cluster,
            }
            for candidate in lenient_candidates
            if candidate.get("title")
        ][:5],
    }


def apply_lenient_refill_diagnostics(
    report: dict[str, Any],
    settings: Any,
) -> None:
    window_hours = int(getattr(settings, "lenient_refill_window_hours", 72) or 72)
    enabled = bool(getattr(settings, "lenient_refill_diagnostics_enabled", False))
    stage_summaries = {
        stage_name: summarize_lenient_stage(
            report,
            stage_name,
            window_hours=window_hours,
        )
        for stage_name in REFILL_STAGE_NAMES
    }
    start_date = next(
        (
            summary.get("start_date")
            for summary in stage_summaries.values()
            if summary.get("start_date")
        ),
        None,
    )
    end_date = next(
        (
            summary.get("end_date")
            for summary in stage_summaries.values()
            if summary.get("end_date")
        ),
        None,
    )
    selected_preview = [
        item
        for summary in stage_summaries.values()
        for item in summary["lenient_selected_preview"]
    ][:5]
    report["strict_final_count"] = report.get("final_count", 0)
    report["strict_refill_accepted_count"] = (
        int(report.get("priority_refilled_count") or 0)
        + int(report.get("secondary_refilled_count") or 0)
        + int(report.get("official_refilled_count") or 0)
    )
    report["lenient_candidate_count"] = sum(
        summary["lenient_candidate_count"] for summary in stage_summaries.values()
    )
    report["proven_within_72h_count"] = sum(
        summary["proven_within_window_count"] for summary in stage_summaries.values()
    )
    report["missing_date_unproven_count"] = sum(
        summary["missing_date_unproven_count"] for summary in stage_summaries.values()
    )
    report["outside_72h_rejected_count"] = sum(
        summary["outside_window_rejected_count"] for summary in stage_summaries.values()
    )
    report["lenient_non_ai_count"] = sum(
        summary["lenient_non_ai_count"] for summary in stage_summaries.values()
    )
    report["lenient_duplicate_or_cluster_count"] = sum(
        summary["lenient_duplicate_or_cluster_count"]
        for summary in stage_summaries.values()
    )
    report["lenient_selected_preview"] = selected_preview
    report["lenient_refill_diagnostics"] = {
        "enabled": enabled,
        "window_hours": window_hours,
        "request_window_hours": refill_request_window_hours(settings),
        "start_date": start_date,
        "end_date": end_date,
        "stages": stage_summaries,
    }


def planned_refill_stage_count(settings: Any) -> int:
    stage_count = 2  # priority_refill + secondary_refill
    if settings.enable_official_fallback:
        stage_count += 1
    return stage_count


def reserved_refill_call_budget(
    settings: Any, available_budget: int | None = None
) -> int:
    if settings.max_refill_rounds <= 0 or settings.min_articles <= 1:
        return 0
    desired_refill_calls = settings.max_refill_rounds * planned_refill_stage_count(
        settings
    )
    max_total_calls = max(
        0,
        settings.max_total_calls
        if available_budget is None
        else min(settings.max_total_calls, available_budget),
    )
    if settings.max_verify_calls > 0:
        max_reservable_calls = max(0, max_total_calls - 1)
    else:
        max_reservable_calls = max_total_calls
    return min(desired_refill_calls, max_reservable_calls)


def run_verify_stage(**kwargs: Any) -> dict[str, Any]:
    """Delegate verification through its stable module boundary."""
    from utils.enrichment_verification import run_verify_stage as run_stage

    return run_stage(**kwargs)


def run_domain_refill_stage(**kwargs: Any) -> dict[str, Any]:
    """Delegate refill through its stable module boundary."""
    from utils.enrichment_refill import run_domain_refill_stage as run_stage

    return run_stage(**kwargs)


def enrich_articles_with_tavily(
    articles: list[Article | dict[str, Any]],
    *,
    report_date: str,
    settings: Any,
    tavily_api_key: str,
    enabled: bool,
    reference_dt: datetime | None = None,
    deadline_at: datetime | None = None,
) -> dict[str, Any]:
    article_dicts = [article_to_dict(article) for article in articles]
    reference_dt = reference_dt or datetime.now(tz=REPORT_TIMEZONE)
    report = build_initial_report(
        report_date=report_date,
        reference_dt=reference_dt,
        articles=article_dicts,
        enabled=enabled,
        settings=settings,
    )
    input_partition = partition_articles_for_publication(article_dicts)
    report["input_story_count"] = len(input_partition["stories"])
    report["input_lead_count"] = len(input_partition["leads"])
    report["publishability_rejected"] = input_partition["rejected"]

    decision = decide_enrichment(enabled=enabled, api_key=tavily_api_key)
    if not decision.apply:
        report["skip_reason"] = decision.skip_reason
        report["stop_reason"] = decision.skip_reason
        if decision.skip_reason == "disabled":
            report["notes"].append("Tavily enrichment is disabled for this run.")
        else:
            report["notes"].append(
                "TAVILY_API_KEY is missing, so the pipeline safely fell back to the deduped articles."
            )
        report["accepted_by_stage_preview"] = {
            "verify": [],
            "priority_refill": [],
            "secondary_refill": [],
            "official_fallback": [],
        }
        report["observation_signals"] = [
            {
                "title": str(lead.get("title") or "").strip(),
                "source": str(lead.get("source") or "").strip(),
                "signal_url": str(lead.get("link") or "").strip(),
                "reason": decision.skip_reason or "enrichment_skipped",
            }
            for lead in input_partition["leads"]
        ]
        report["lead_unresolved_count"] = len(report["observation_signals"])
        report["final_count"] = len(input_partition["stories"])
        report["strict_final_count"] = report["final_count"]
        update_stage_failures(report)
        return {"articles": input_partition["stories"], "report": report}

    session = requests.Session()
    session.trust_env = settings.trust_env

    try:
        from utils.lead_resolution import run_lead_resolution_stage

        lead_resolution = run_lead_resolution_stage(
            leads=input_partition["leads"],
            settings=settings,
            session=session,
            api_key=tavily_api_key,
            reference_dt=reference_dt,
            remaining_budget=max(0, int(settings.max_total_calls)),
            deadline_at=deadline_at,
        )
        report["lead_resolution_calls"] = lead_resolution["calls"]
        report["lead_resolution_runs"] = lead_resolution["runs"]
        report["lead_terminal_error_code"] = lead_resolution["terminal_error_code"]
        report["lead_resolved_count"] = len(lead_resolution["resolved_articles"])
        report["lead_unresolved_count"] = len(lead_resolution["unresolved_leads"])
        report["observation_signals"] = lead_resolution["unresolved_leads"]
        report["total_calls"] = lead_resolution["calls"]
        working_articles = (
            input_partition["stories"] + lead_resolution["resolved_articles"]
        )

        prefilter = build_prefilter_summary(working_articles)
        prefilter_clusters = annotate_story_clusters(prefilter["prefilter_candidates"])
        verify_view = collapse_prefilter_candidates_for_verify(
            prefilter_clusters["annotated_candidates"]
        )
        preverified_candidates = []
        for candidate in verify_view["verify_candidates"]:
            article = candidate.get("article", {})
            provenance = article.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            if provenance.get("resolution_stage") == "tavily_lead_resolution" or (
                article.get("kind") == "story"
                and article.get("evidence_status") in {"direct", "corroborated"}
            ):
                # A direct URL, source publication time and evidence text have
                # already passed the Story gate. Searching the title again adds
                # cost and can incorrectly discard a valid source article when
                # Tavily happens to return a nearby story.
                preverified_candidates.append(candidate)
        preverified_ids = {id(candidate) for candidate in preverified_candidates}
        verify_view["verify_candidates"] = [
            candidate
            for candidate in verify_view["verify_candidates"]
            if id(candidate) not in preverified_ids
        ]

        report["applied"] = True
        report["prefiltered_count"] = prefilter["prefiltered_count"]
        report["prefilter_stats"] = prefilter["prefilter_stats"]
        report["prefilter_bucket_counts"] = prefilter["prefilter_bucket_counts"]
        report["prefilter_candidates"] = prefilter_clusters["annotated_candidates"]
        report["excluded_prefilter_candidates"] = prefilter[
            "excluded_prefilter_candidates"
        ]
        report["cluster_count"] = prefilter_clusters["cluster_count"]
        report["clustered_prefilter_count"] = prefilter_clusters[
            "clustered_candidate_count"
        ]
        report["cluster_potential_verify_saved_calls"] = prefilter_clusters[
            "cluster_potential_verify_saved_calls"
        ]
        report["cluster_skipped_prefilter_candidates"] = verify_view[
            "skipped_candidates"
        ]
        report["cluster_diagnostics"] = prefilter_clusters["cluster_diagnostics"]
        report["notes"].append(
            "Local prefilter completed before any Tavily refill attempt."
        )
        if not working_articles:
            report["notes"].append(
                "Upstream sources returned zero deduped articles, so any final output must come from Tavily refill."
            )

        verify = run_verify_stage(
            candidates=verify_view["verify_candidates"],
            settings=settings,
            session=session,
            api_key=tavily_api_key,
            reference_dt=reference_dt,
            remaining_budget=lead_resolution["remaining_budget"],
            deadline_at=deadline_at,
        )
        baseline_verify_calls = min(
            len(prefilter_clusters["annotated_candidates"]),
            max(
                0,
                min(
                    settings.max_verify_calls,
                    lead_resolution["remaining_budget"],
                ),
            ),
        )
        report["verify_saved_calls"] = max(
            0, baseline_verify_calls - verify["verify_calls"]
        )
        report["verify_calls"] = verify["verify_calls"]
        report["total_calls"] += verify["verify_calls"]
        report["verified_count"] = len(verify["verified_articles"]) + len(
            preverified_candidates
        )
        report["preserved_error_count"] = len(verify["preserved_error_articles"])
        report["preserved_budget_count"] = len(verify["preserved_budget_articles"])
        report["verify_budget"] = verify["verify_budget"]
        report["reserved_refill_calls"] = verify["reserved_refill_calls"]
        report["verify_skipped_due_budget"] = verify["verify_skipped_due_budget"]
        report["verify_runs"] = verify["verify_runs"]
        report["verified_candidates"] = verify["verified_candidates"]
        report["rejected_candidates"] = verify["rejected_candidates"]
        report["neighbor_candidates_verified_count"] = sum(
            1
            for candidate in verify["verified_candidates"]
            if candidate.get("prefilter_bucket") == "ai_neighbor"
        )
        report["neighbor_candidates_outside_24h_count"] = sum(
            1
            for candidate in verify["rejected_candidates"]
            if candidate.get("prefilter_bucket") == "ai_neighbor"
            and candidate.get("validation_outcome") == "outside_24h"
        )
        report["neighbor_candidates_no_match_count"] = sum(
            1
            for candidate in verify["rejected_candidates"]
            if candidate.get("prefilter_bucket") == "ai_neighbor"
            and candidate.get("validation_outcome") == "no_match"
        )

        preverified_articles = [
            dict(candidate["article"]) for candidate in preverified_candidates
        ]
        verified_output_articles = (
            preverified_articles
            + verify["preserved_budget_articles"]
            + verify["preserved_error_articles"]
            + verify["verified_articles"]
        )
        report["refill_needed_count"] = max(
            0, settings.min_articles - len(verified_output_articles)
        )

        remaining_budget = max(0, settings.max_total_calls - report["total_calls"])
        priority_refill = empty_refill_result(remaining_budget)
        if report["refill_needed_count"] > 0:
            priority_refill = run_domain_refill_stage(
                base_articles=working_articles,
                prior_candidates=verified_output_articles,
                include_domains=list(
                    settings.trusted_domains.priority_refill_media_whitelist
                ),
                query=configured_query_pack(
                    settings,
                    plural_name="priority_refill_queries",
                    singular_name="priority_refill_query",
                ),
                stage_name="priority_refill",
                settings=settings,
                session=session,
                api_key=tavily_api_key,
                reference_dt=reference_dt,
                remaining_budget=remaining_budget,
                needed_count=report["refill_needed_count"],
                deadline_at=deadline_at,
            )
        report["refill_calls"] = priority_refill["refill_calls"]
        report["total_calls"] += priority_refill["refill_calls"]
        report["priority_refilled_count"] = priority_refill["media_refilled_count"]
        report["media_refilled_count"] = priority_refill["media_refilled_count"]
        report["near_duplicate_rejected_count"] = priority_refill[
            "near_duplicate_rejected_count"
        ]
        report["story_cluster_rejected_count"] = priority_refill[
            "story_cluster_rejected_count"
        ]
        report["priority_refill_runs"] = priority_refill["refill_runs"]
        report["priority_refilled_candidates"] = priority_refill["accepted_candidates"]
        remaining_budget = priority_refill["remaining_budget_after_refill"]

        secondary_refill_executed = False
        secondary_candidates: list[dict[str, Any]] = []
        secondary_needed_count = max(
            0,
            settings.min_articles
            - len(verified_output_articles)
            - len(priority_refill["accepted_candidates"]),
        )
        if remaining_budget > 0 and secondary_needed_count > 0:
            secondary_refill = run_domain_refill_stage(
                base_articles=working_articles,
                prior_candidates=(
                    verified_output_articles + priority_refill["accepted_candidates"]
                ),
                include_domains=list(
                    settings.trusted_domains.secondary_refill_candidate_domains
                ),
                query=configured_query_pack(
                    settings,
                    plural_name="priority_refill_queries",
                    singular_name="priority_refill_query",
                ),
                stage_name="secondary_refill",
                settings=settings,
                session=session,
                api_key=tavily_api_key,
                reference_dt=reference_dt,
                remaining_budget=remaining_budget,
                needed_count=secondary_needed_count,
                deadline_at=deadline_at,
            )
            secondary_refill_executed = secondary_refill["refill_calls"] > 0
            secondary_candidates = secondary_refill["accepted_candidates"]
            report["refill_calls"] += secondary_refill["refill_calls"]
            report["total_calls"] += secondary_refill["refill_calls"]
            report["secondary_refilled_count"] = secondary_refill[
                "media_refilled_count"
            ]
            report["media_refilled_count"] += report["secondary_refilled_count"]
            report["near_duplicate_rejected_count"] += secondary_refill[
                "near_duplicate_rejected_count"
            ]
            report["story_cluster_rejected_count"] += secondary_refill[
                "story_cluster_rejected_count"
            ]
            report["secondary_duplicate_slip_count"] = secondary_refill[
                "duplicate_slip_count"
            ]
            report["secondary_refill_runs"] = secondary_refill["refill_runs"]
            report["secondary_refilled_candidates"] = secondary_candidates
            remaining_budget = secondary_refill["remaining_budget_after_refill"]

        official_candidates: list[dict[str, Any]] = []
        official_needed_count = max(
            0,
            settings.min_articles
            - len(verified_output_articles)
            - len(priority_refill["accepted_candidates"])
            - len(secondary_candidates),
        )
        if (
            settings.enable_official_fallback
            and remaining_budget > 0
            and official_needed_count > 0
        ):
            official = run_domain_refill_stage(
                base_articles=working_articles,
                prior_candidates=(
                    verified_output_articles
                    + priority_refill["accepted_candidates"]
                    + secondary_candidates
                ),
                include_domains=list(
                    settings.trusted_domains.official_fallback_domains
                ),
                query=configured_query_pack(
                    settings,
                    plural_name="official_fallback_queries",
                    singular_name="official_fallback_query",
                ),
                stage_name="official_fallback",
                settings=settings,
                session=session,
                api_key=tavily_api_key,
                reference_dt=reference_dt,
                remaining_budget=remaining_budget,
                needed_count=official_needed_count,
                deadline_at=deadline_at,
            )
            official_candidates = official["accepted_candidates"]
            report["fallback_calls"] = official["refill_calls"]
            report["total_calls"] += official["refill_calls"]
            report["official_refilled_count"] = official["media_refilled_count"]
            report["near_duplicate_rejected_count"] += official[
                "near_duplicate_rejected_count"
            ]
            report["story_cluster_rejected_count"] += official[
                "story_cluster_rejected_count"
            ]
            report["official_fallback_runs"] = official["refill_runs"]
            report["official_refilled_candidates"] = official_candidates
            remaining_budget = official["remaining_budget_after_refill"]

        final_articles = (
            verified_output_articles
            + priority_refill["accepted_candidates"]
            + secondary_candidates
            + official_candidates
        )
        final_partition = partition_articles_for_publication(final_articles)
        final_articles = final_partition["stories"]
        report["publishability_rejected"].extend(final_partition["rejected"])
        report["final_count"] = len(final_articles)
        report["refill_remaining_count"] = max(
            0, settings.min_articles - report["final_count"]
        )
        report["accepted_by_stage_preview"] = {
            "evidence_gate": sample_titles(preverified_articles),
            "preserved_budget": sample_titles(verify["preserved_budget_articles"]),
            "preserved_errors": sample_titles(verify["preserved_error_articles"]),
            "verify": sample_titles(verify["verified_articles"]),
            "priority_refill": sample_titles(priority_refill["accepted_candidates"]),
            "secondary_refill": sample_titles(secondary_candidates),
            "official_fallback": sample_titles(official_candidates),
        }
        apply_lenient_refill_diagnostics(report, settings)
        if report["refill_needed_count"] == 0:
            report["stop_reason"] = "min_articles_satisfied_after_verify"
        elif report["final_count"] >= settings.min_articles:
            if report["fallback_calls"] > 0:
                report["stop_reason"] = "official_fallback_complete"
            elif secondary_refill_executed:
                report["stop_reason"] = "secondary_refill_complete"
            else:
                report["stop_reason"] = "priority_refill_complete"
        elif settings.enable_official_fallback:
            if remaining_budget <= 0:
                report["stop_reason"] = "budget_exhausted_after_official_fallback"
            else:
                report["stop_reason"] = "below_min_articles_after_official_fallback"
        elif remaining_budget <= 0 and report["final_count"] < settings.min_articles:
            report["stop_reason"] = (
                "budget_exhausted_after_secondary_refill"
                if secondary_refill_executed
                else "budget_exhausted_after_priority_refill"
            )
        elif report["final_count"] < settings.min_articles:
            report["stop_reason"] = below_min_stop_reason(
                secondary_refill_executed=secondary_refill_executed
            )
        if verify["preserved_error_articles"]:
            report["notes"].append(
                "Verify request errors preserved the original deduped articles to keep fail-open behavior."
            )
        if verify["preserved_budget_articles"]:
            report["notes"].append(
                "Verify budget exhaustion preserved direct source stories instead of dropping them."
            )
        report["notes"].append("Exact verify and staged refill completed.")
        update_stage_failures(report)
        return {"articles": final_articles, "report": report}
    except Exception as exc:
        report["applied"] = False
        report["skip_reason"] = "enrichment_error"
        report["error"] = scrub_diagnostic(str(exc), settings)
        report["terminal_error_code"] = classify_request_outcome(exc)
        report["stop_reason"] = "enrichment_error"
        report["notes"].append(
            "The pipeline fell back to the deduped articles after an enrichment error."
        )
        report["accepted_by_stage_preview"] = {
            "verify": [],
            "priority_refill": [],
            "secondary_refill": [],
            "official_fallback": [],
        }
        report["observation_signals"] = [
            {
                "title": str(lead.get("title") or "").strip(),
                "source": str(lead.get("source") or "").strip(),
                "signal_url": str(lead.get("link") or "").strip(),
                "reason": "enrichment_error",
            }
            for lead in input_partition["leads"]
        ]
        report["lead_unresolved_count"] = len(report["observation_signals"])
        report["final_count"] = len(input_partition["stories"])
        report["strict_final_count"] = report["final_count"]
        update_stage_failures(report)
        return {"articles": input_partition["stories"], "report": report}
