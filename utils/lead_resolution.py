"""Resolve a small number of high-value discovery leads into evidenced stories."""

from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
import re
from typing import Any

import requests

from utils.editorial_catalog import analyze_article, analyze_editorial_text
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
    "ai",
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
    terms: set[str] = set()
    for token in _WORD_RE.findall(compact_text(value)):
        for part in (token, *re.split(r"[-.]", token)):
            normalized = _normalize_word(part)
            if normalized and normalized not in _QUERY_FILLER_TERMS:
                terms.add(normalized)
    return terms


def _version_terms(terms: set[str]) -> set[str]:
    """Return model/hardware identifiers such as K3, V4 and B300."""

    return {
        term
        for term in terms
        if re.search(r"[a-z]", term, re.IGNORECASE) and re.search(r"\d", term)
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
    lead_analysis = analyze_article(lead)
    result_analysis = analyze_editorial_text(result_title)
    if (
        lead_analysis.primary_entity
        and result_analysis.primary_entity
        and lead_analysis.primary_entity != result_analysis.primary_entity
    ):
        return False
    if lead_analysis.model_families and not (
        set(lead_analysis.model_families) & set(result_analysis.model_families)
    ):
        return False
    lead_terms = _identity_terms(lead_identity)
    title_terms = _identity_terms(result_title)
    required_versions = _version_terms(lead_terms)
    if required_versions and not required_versions.issubset(title_terms):
        return False
    title_overlap = lead_terms & title_terms
    minimum_overlap = 2 if len(lead_terms) >= 2 else 1
    if len(title_overlap) >= minimum_overlap:
        return True

    lead_cjk = _CJK_RE.findall(lead_identity)
    result_cjk = _CJK_RE.findall(result_title)
    return any(
        left in right or right in left for left in lead_cjk for right in result_cjk
    )


def _published_timestamp(value: Any) -> float:
    text = compact_text(value)
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return 0.0
    if parsed.tzinfo is None:
        return parsed.timestamp()
    return parsed.timestamp()


def _candidate_order(
    candidate: dict[str, Any], index: int
) -> tuple[int, int, float, int, int]:
    provenance = candidate.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    analysis = analyze_article(candidate)
    return (
        -analysis.relevance_level,
        -_safe_int(candidate.get("priority"), 0),
        -_published_timestamp(candidate.get("publish_time")),
        _safe_int(provenance.get("trend_rank"), 1_000_000),
        index,
    )


def build_candidate_queue(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order from fetch metadata, then interleave repeated primary entities."""

    ranked = [
        candidate
        for index, candidate in sorted(
            enumerate(candidates), key=lambda item: _candidate_order(item[1], item[0])
        )
    ]
    buckets: dict[str, list[dict[str, Any]]] = {}
    bucket_order: list[str] = []
    for index, candidate in enumerate(ranked):
        entity = analyze_article(candidate).primary_entity or f"__unknown_{index}"
        if entity not in buckets:
            buckets[entity] = []
            bucket_order.append(entity)
        buckets[entity].append(candidate)

    queue: list[dict[str, Any]] = []
    while any(buckets.values()):
        for entity in bucket_order:
            if buckets[entity]:
                queue.append(buckets[entity].pop(0))
    return queue


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
        "snippet": text,
        "score": score,
        "origin": "tavily",
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
        "evidence": selected_evidence,
    }


def _original_evidence(article: dict[str, Any], settings: Any) -> dict[str, Any] | None:
    """Represent fetched source metadata without pretending Tavily returned it."""

    from utils.news_enrichment import domain_of

    url = compact_text(article.get("link"))
    published_date = compact_text(article.get("publish_time"))
    text = compact_text(article.get("content")) or compact_text(
        article.get("description")
    )
    if not (is_direct_evidence_url(url) and published_date and text):
        return None
    max_chars = int(getattr(settings, "lead_evidence_chars_per_source", 600))
    snippet = text[:max_chars].rstrip()
    return {
        "title": compact_text(article.get("title")),
        "url": url,
        "domain": domain_of(url),
        "published_date": published_date,
        "text": snippet,
        "snippet": snippet,
        "score": 1.0,
        "origin": "fetch",
    }


def _enriched_direct_story(
    article: dict[str, Any], evidence: list[dict[str, Any]], settings: Any
) -> dict[str, Any]:
    """Keep the fetched event identity while attaching bounded evidence."""

    from utils.news_enrichment import canonical_url

    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    original = _original_evidence(article, settings)
    for item in ([original] if original else []) + sorted(
        evidence, key=lambda value: -_safe_float(value.get("score"))
    ):
        if item is None:
            continue
        key = canonical_url(compact_text(item.get("url")))
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        selected.append(item)
        if len(selected) >= 3:
            break

    enriched = dict(article)
    if evidence:
        evidence_text = " ".join(
            f"[{item['domain']}] {item['snippet']}"
            for item in evidence[:3]
            if item.get("snippet")
        )[:2400].rstrip()
        original_text = compact_text(article.get("description"))
        enriched["description"] = " ".join(
            part for part in (original_text, evidence_text) if part
        )[:3000].rstrip()
        enriched["content"] = enriched["description"]
    if selected:
        enriched["evidence"] = selected

    provenance = article.get("provenance")
    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    provenance.update(
        {
            "input_kind": "story",
            "resolution_stage": "tavily_story_enrichment",
            "evidence_count": str(len(selected)),
            "evidence_urls": "|".join(item["url"] for item in selected),
        }
    )
    enriched["provenance"] = provenance
    domains = {item.get("domain") for item in selected if item.get("domain")}
    if evidence:
        enriched["evidence_status"] = (
            "corroborated" if len(domains) >= 2 else "direct"
        )
        enriched["confidence"] = enriched["evidence_status"]
    enriched["kind"] = "story"
    return enriched


def run_candidate_enrichment_stage(
    *,
    candidates: list[dict[str, Any]],
    settings: Any,
    session: requests.Session,
    api_key: str,
    reference_dt: datetime,
    remaining_budget: int,
    deadline_at: datetime | None = None,
) -> dict[str, Any]:
    """Enrich only fetched candidates, with one pass for all before pass two."""

    from utils.news_enrichment import (
        _search_tavily_with_deadline,
        classify_request_outcome,
        report_window,
    )
    from utils.story_quality import article_is_lead

    queue = build_candidate_queue(candidates)
    states: list[dict[str, Any]] = []
    for candidate in queue:
        snapshot = dict(candidate)
        provenance = snapshot.get("provenance")
        provenance = dict(provenance) if isinstance(provenance, dict) else {}
        provenance.update(
            {
                "selection_title": compact_text(candidate.get("title")),
                "selection_description": compact_text(candidate.get("description")),
                "selection_content": compact_text(candidate.get("content")),
            }
        )
        snapshot["provenance"] = provenance
        states.append(
            {
                "article": snapshot,
                "is_lead": article_is_lead(snapshot),
                "evidence": [],
                "processed": False,
            }
        )
    max_rounds = min(2, max(1, int(getattr(settings, "lead_search_rounds", 2))))
    start_date, end_date = report_window(
        reference_dt,
        window_hours=int(getattr(settings, "lead_max_age_hours", 72)),
    )
    runs: list[dict[str, Any]] = []
    used_calls = 0
    terminal_error_code: str | None = None
    deadline_exhausted = False

    # Breadth first guarantees that each metadata-selected candidate reaches
    # Tavily before any one candidate consumes its optional second round.
    for round_index in range(1, max_rounds + 1):
        for candidate_index, state in enumerate(states, start=1):
            if used_calls >= remaining_budget or terminal_error_code:
                break
            article = state["article"]
            evidence = state["evidence"]
            query = (
                _discovery_query(article)
                if round_index == 1
                else _followup_query(article, evidence)
            )
            if not state["is_lead"] and round_index == 1:
                query = f"{compact_text(article.get('title'))} {compact_text(article.get('link'))}"[:400]
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
            except Exception as exc:
                error_obj = exc
            used_calls += 1
            state["processed"] = True

            seen = {compact_text(item.get("url")) for item in evidence}
            accepted = 0
            irrelevant = 0
            invalid = 0
            for result in results:
                if not _result_matches_lead(result, article):
                    irrelevant += 1
                    continue
                normalized = _normalize_evidence(
                    result, reference_dt=reference_dt, settings=settings
                )
                if normalized is None or normalized["url"] in seen:
                    invalid += 1
                    continue
                seen.add(normalized["url"])
                evidence.append(normalized)
                accepted += 1
                if len(evidence) >= 3:
                    break

            outcome = classify_request_outcome(error_obj)
            if outcome in {
                "authentication_error",
                "invalid_request",
                "rate_limited",
                "deadline_exceeded",
            }:
                terminal_error_code = outcome
            if isinstance(error_obj, RunDeadlineExceeded):
                deadline_exhausted = True
            runs.append(
                {
                    "stage": "candidate_enrichment",
                    "candidate_index": candidate_index,
                    "candidate_kind": "lead" if state["is_lead"] else "story",
                    "round": round_index,
                    "candidate_title": compact_text(article.get("title")),
                    "query": query,
                    "search_depth": payload["search_depth"],
                    "latency_ms": latency_ms,
                    "result_count": len(results),
                    "accepted_evidence_count": accepted,
                    "rejected_irrelevant_count": irrelevant,
                    "rejected_invalid_count": invalid,
                    "request_outcome": outcome,
                    "error_code": outcome if outcome != "success" else None,
                }
            )
            if deadline_exhausted:
                break
        if used_calls >= remaining_budget or terminal_error_code or deadline_exhausted:
            break

    articles: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    for state in states:
        article = state["article"]
        evidence = state["evidence"]
        if state["is_lead"]:
            if evidence:
                articles.append(_resolved_story(article, evidence))
            else:
                reason = (
                    "enrichment_deadline_exceeded"
                    if deadline_exhausted and not state["processed"]
                    else "candidate_budget_exhausted"
                    if not state["processed"]
                    else "lead_resolution_request_failed"
                    if any(
                        run["candidate_title"] == compact_text(article.get("title"))
                        and run["request_outcome"] != "success"
                        for run in runs
                    )
                    else "no_publishable_evidence"
                )
                unresolved.append(observation_signal(article, reason))
        else:
            articles.append(_enriched_direct_story(article, evidence, settings))

    return {
        "articles": articles,
        "unresolved_leads": unresolved,
        "runs": runs,
        "calls": used_calls,
        "lead_calls": sum(run["candidate_kind"] == "lead" for run in runs),
        "story_calls": sum(run["candidate_kind"] == "story" for run in runs),
        "queue_count": len(queue),
        "processed_count": sum(bool(state["processed"]) for state in states),
        "remaining_budget": max(0, remaining_budget - used_calls),
        "terminal_error_code": terminal_error_code,
        "deadline_exhausted": deadline_exhausted,
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
    max_leads = int(getattr(settings, "max_lead_candidates", 5))
    selected_leads: list[dict[str, Any]] = []
    seen_primary_entities: set[str] = set()
    deferred_reasons: dict[int, str] = {}
    for lead in ranked_leads:
        primary_entity = analyze_article(lead).primary_entity
        if primary_entity and primary_entity in seen_primary_entities:
            deferred_reasons[id(lead)] = "lead_duplicate_entity"
            continue
        if len(selected_leads) >= max_leads:
            continue
        selected_leads.append(lead)
        if primary_entity:
            seen_primary_entities.add(primary_entity)
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
            else deferred_reasons.get(id(lead), "lead_candidate_limit"),
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
