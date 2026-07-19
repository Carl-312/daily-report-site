"""Resolve a small number of high-value discovery leads into evidenced stories."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

import requests

from utils.editorial_catalog import analyze_article
from utils.run_contracts import RunDeadlineExceeded
from utils.story_quality import (
    compact_text,
    is_direct_evidence_url,
    observation_signal,
)


_EXCLUDED_DISCOVERY_DOMAINS = [
    "agihunt.info",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "reddit.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
]

_WORD_RE = re.compile(r"[a-z0-9]+(?:[.+#-][a-z0-9]+)*", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_QUERY_FILLER_TERMS = {
    "a",
    "an",
    "and",
    "announcement",
    "are",
    "at",
    "by",
    "detail",
    "for",
    "from",
    "funding",
    "hot",
    "impact",
    "in",
    "is",
    "list",
    "of",
    "official",
    "on",
    "or",
    "pricing",
    "rumored",
    "soon",
    "the",
    "to",
    "top",
    "vs",
    "was",
    "were",
    "with",
}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_word(value: str) -> str:
    word = value.lower().strip("-.")
    if word.endswith("ies") and len(word) > 4:
        return f"{word[:-3]}y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 4:
        return word[:-1]
    return word


def _identity_terms(value: Any) -> set[str]:
    return {
        normalized
        for token in _WORD_RE.findall(compact_text(value))
        if (normalized := _normalize_word(token))
        and normalized not in _QUERY_FILLER_TERMS
    }


def _result_matches_lead(result: dict[str, Any], lead: dict[str, Any]) -> bool:
    """Require the direct story title to preserve the lead's identity.

    Tavily relevance scores are query-relative, but a result can still be a
    nearby story (for example Kimi coverage returned for a DeepSeek lead).
    A title-level identity overlap is a small deterministic guard against
    silently changing the subject while resolving a lead.
    """

    from utils.news_enrichment import canonical_url

    expected_url = canonical_url(compact_text(lead.get("link")))
    result_url = canonical_url(compact_text(result.get("url")))
    if expected_url and result_url and expected_url == result_url:
        return True

    provenance = lead.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    lead_identity = " ".join(
        part
        for part in (
            compact_text(lead.get("title")),
            compact_text(provenance.get("trend_term_en")),
        )
        if part
    )
    result_title = compact_text(result.get("title"))
    lead_terms = _identity_terms(lead_identity)
    title_terms = _identity_terms(result_title)
    if lead_terms and lead_terms & title_terms:
        return True

    lead_cjk = _CJK_RE.findall(lead_identity)
    result_cjk = _CJK_RE.findall(result_title)
    return any(
        left in right or right in left for left in lead_cjk for right in result_cjk
    )


def _lead_order(lead: dict[str, Any], index: int) -> tuple[int, int, int, int]:
    provenance = lead.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    analysis = analyze_article(lead)
    return (
        -analysis.relevance_level,
        -_safe_int(lead.get("priority"), 0),
        _safe_int(provenance.get("trend_rank"), 1_000_000),
        index,
    )


def _discovery_query(lead: dict[str, Any]) -> str:
    provenance = lead.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    parts = [
        compact_text(lead.get("title")),
        compact_text(provenance.get("trend_term_en")),
        compact_text(lead.get("description")),
    ]
    query = " ".join(part for part in parts if part)
    return query[:380]


def _followup_query(lead: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    best_title = compact_text(evidence[0].get("title")) if evidence else ""
    base = best_title or _discovery_query(lead)
    return f"{base} official announcement details pricing benchmark funding impact"[
        :400
    ]


def _evidence_text(result: dict[str, Any], *, max_chars: int) -> str:
    snippet = compact_text(result.get("content"))
    raw_content = compact_text(result.get("raw_content"))
    if raw_content and raw_content not in snippet:
        snippet = f"{snippet} {raw_content}".strip()
    return snippet[:max_chars].rstrip()


def _normalize_evidence(
    result: dict[str, Any],
    *,
    reference_dt: datetime,
    settings: Any,
) -> dict[str, Any] | None:
    from utils.news_enrichment import domain_of, within_strict_hours

    url = compact_text(result.get("url"))
    if not is_direct_evidence_url(url):
        return None
    published_date = compact_text(result.get("published_date"))
    within_window = within_strict_hours(
        published_date,
        reference_dt=reference_dt,
        strict_hours=int(getattr(settings, "lead_max_age_hours", 72)),
    )
    if within_window is not True:
        return None
    text = _evidence_text(
        result,
        max_chars=int(getattr(settings, "lead_evidence_chars_per_source", 600)),
    )
    if len(text) < int(getattr(settings, "lead_min_evidence_chars", 80)):
        return None
    score = _safe_float(result.get("score"))
    if score < 0.15:
        return None
    return {
        "title": compact_text(result.get("title")),
        "url": url,
        "domain": domain_of(url),
        "published_date": published_date,
        "text": text,
        "score": score,
    }


def _resolved_story(
    lead: dict[str, Any], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    from utils.news_enrichment import canonical_url

    unique: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in sorted(evidence, key=lambda value: -_safe_float(value.get("score"))):
        canonical = canonical_url(str(item.get("url") or ""))
        if not canonical or canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        unique.append(item)
    best = unique[0]
    distinct_domains = {item["domain"] for item in unique if item.get("domain")}
    corroborated = len(distinct_domains) >= 2
    selected_evidence = unique[:3]
    evidence_text = " ".join(
        f"[{item['domain']}] {item['text']}" for item in selected_evidence
    )[:1800].rstrip()
    provenance = lead.get("provenance")
    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    provenance.update(
        {
            "input_kind": "story",
            "resolution_stage": "tavily_lead_resolution",
            "lead_title": compact_text(lead.get("title")),
            "lead_source": compact_text(lead.get("source")),
            "signal_url": compact_text(lead.get("link")),
            "evidence_count": str(len(selected_evidence)),
            "evidence_domains": ",".join(sorted(distinct_domains)),
            "evidence_urls": "|".join(item["url"] for item in selected_evidence),
            "publish_time_semantics": "source_published_at",
        }
    )
    return {
        "title": best["title"] or compact_text(lead.get("title")),
        "link": best["url"],
        "description": evidence_text,
        "publish_time": best["published_date"],
        "content": evidence_text,
        "priority": _safe_int(lead.get("priority"), 0),
        "source": best["domain"],
        "kind": "story",
        "evidence_status": "corroborated" if corroborated else "reported",
        "confidence": "corroborated" if corroborated else "reported",
        "provenance": provenance,
    }


def run_lead_resolution_stage(
    *,
    leads: list[dict[str, Any]],
    settings: Any,
    session: requests.Session,
    api_key: str,
    reference_dt: datetime,
    remaining_budget: int,
    deadline_at: datetime | None = None,
) -> dict[str, Any]:
    """Use two bounded searches per important lead and keep only direct evidence."""

    from utils.news_enrichment import (
        _search_tavily_with_deadline,
        classify_request_outcome,
        report_window,
    )

    indexed_leads = list(enumerate(leads))
    ranked_leads = [
        lead
        for index, lead in sorted(
            indexed_leads, key=lambda item: _lead_order(item[1], item[0])
        )
    ]
    selected_leads = ranked_leads[: int(getattr(settings, "max_lead_candidates", 5))]
    max_rounds = int(getattr(settings, "lead_search_rounds", 2))
    start_date, end_date = report_window(
        reference_dt,
        window_hours=int(getattr(settings, "lead_max_age_hours", 72)),
    )
    resolved_articles: list[dict[str, Any]] = []
    unresolved_leads: list[dict[str, str]] = []
    runs: list[dict[str, Any]] = []
    used_calls = 0
    processed_lead_ids: set[int] = set()
    deadline_exhausted = False
    terminal_error_code: str | None = None

    for lead_index, lead in enumerate(selected_leads, start=1):
        processed_lead_ids.add(id(lead))
        if used_calls >= remaining_budget:
            unresolved_leads.append(observation_signal(lead, "lead_budget_exhausted"))
            continue
        evidence: list[dict[str, Any]] = []
        seen_evidence_urls: set[str] = set()
        for round_index in range(1, max_rounds + 1):
            if used_calls >= remaining_budget:
                break
            query = (
                _discovery_query(lead)
                if round_index == 1
                else _followup_query(lead, evidence)
            )
            payload = {
                "query": query,
                "topic": "news",
                "search_depth": getattr(settings, "lead_search_depth", "advanced"),
                "chunks_per_source": 3,
                "max_results": int(getattr(settings, "lead_max_results", 5)),
                "include_answer": False,
                "include_images": False,
                "include_raw_content": "text",
                "auto_parameters": False,
                "exclude_domains": _EXCLUDED_DISCOVERY_DOMAINS,
                "start_date": start_date,
                "end_date": end_date,
            }
            latency_ms = None
            results: list[dict[str, Any]] = []
            error_obj: Exception | None = None
            try:
                response = _search_tavily_with_deadline(
                    session, api_key, payload, deadline_at
                )
                latency_ms = response["latency_ms"]
                results = response["response"].get("results", []) or []
            except RunDeadlineExceeded as exc:
                error_obj = exc
            except Exception as exc:
                error_obj = exc
            used_calls += 1

            accepted_this_round = 0
            rejected_irrelevant_count = 0
            for result in results:
                if not _result_matches_lead(result, lead):
                    rejected_irrelevant_count += 1
                    continue
                normalized = _normalize_evidence(
                    result,
                    reference_dt=reference_dt,
                    settings=settings,
                )
                if normalized is None or normalized["url"] in seen_evidence_urls:
                    continue
                seen_evidence_urls.add(normalized["url"])
                evidence.append(normalized)
                accepted_this_round += 1
            outcome = classify_request_outcome(error_obj)
            if outcome in {
                "authentication_error",
                "invalid_request",
                "rate_limited",
                "deadline_exceeded",
            }:
                terminal_error_code = outcome
            runs.append(
                {
                    "stage": "lead_resolution",
                    "lead_index": lead_index,
                    "round": round_index,
                    "lead_title": compact_text(lead.get("title")),
                    "query": query,
                    "search_depth": payload["search_depth"],
                    "latency_ms": latency_ms,
                    "result_count": len(results),
                    "accepted_evidence_count": accepted_this_round,
                    "rejected_irrelevant_count": rejected_irrelevant_count,
                    "request_outcome": outcome,
                    "error_code": outcome if outcome != "success" else None,
                }
            )
            if isinstance(error_obj, RunDeadlineExceeded):
                deadline_exhausted = True
                break
            if terminal_error_code:
                break

        if evidence:
            resolved_articles.append(_resolved_story(lead, evidence))
        else:
            reason = (
                "lead_resolution_request_failed"
                if any(
                    run["lead_index"] == lead_index
                    and run["request_outcome"] != "success"
                    for run in runs
                )
                else "no_publishable_evidence"
            )
            unresolved_leads.append(observation_signal(lead, reason))
        if deadline_exhausted or terminal_error_code:
            break

    unresolved_leads.extend(
        observation_signal(
            lead,
            "enrichment_deadline_exceeded"
            if deadline_exhausted and lead in selected_leads
            else f"lead_resolution_{terminal_error_code}"
            if terminal_error_code and lead in selected_leads
            else "lead_candidate_limit",
        )
        for lead in leads
        if id(lead) not in processed_lead_ids
    )
    return {
        "resolved_articles": resolved_articles,
        "unresolved_leads": unresolved_leads,
        "runs": runs,
        "calls": used_calls,
        "remaining_budget": (
            0 if terminal_error_code else max(0, remaining_budget - used_calls)
        ),
        "terminal_error_code": terminal_error_code,
    }
