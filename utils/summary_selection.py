"""Deterministic candidate selection for the daily summary.

The language model is deliberately not the news editor.  This module chooses a
small, source-balanced set first; the model only rewrites those facts in
Chinese.  Keeping the policy here makes the same decision reproducible in live,
offline, replay, and publication validation paths.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import floor
import re
from typing import Any
from urllib.parse import urlsplit

from utils.editorial_catalog import (
    EditorialAnalysis,
    analyze_article,
    load_editorial_catalog,
)

SUMMARY_SELECTION_POLICY_V1 = "source_balanced_v1"
SUMMARY_SELECTION_POLICY = "source_balanced_v2"
MAX_SOURCE_SHARE = 0.60
MAX_PRIMARY_ENTITY_ITEMS = 2
MAX_MENTIONED_ENTITY_ITEMS = 3
MAX_MODEL_FAMILY_ITEMS = 1
MIN_TITLE_ONLY_VISIBLE_CHARS = 24
_ARTICLE_ID = re.compile(r"a[1-9]\d*")
_AI_TOPIC = re.compile(
    r"(?:人工智能|大模型|机器学习|深度学习|生成式|智能体|机器人|算力|推理|"
    r"(?<![a-z])ai(?![a-z])|artificial intelligence|machine learning|"
    r"(?<![a-z])llm(?![a-z])|openai|anthropic|claude|gemini|gpt|xai|deepseek|"
    r"qwen|kimi|grok|copilot|agentic|neural|inference|robot)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    article_id: str
    original_index: int
    article: dict
    source_group: str
    qualified: bool
    ai_topic: bool
    priority: int
    trend_rank: int
    trend_heat: float


def article_id_for_index(index: int) -> str:
    """Return the stable private ID for one position in a candidate snapshot."""

    if index < 1:
        raise ValueError("article index must be positive")
    return f"a{index}"


def article_reference_id(article: dict, index: int) -> str:
    """Use a preserved snapshot ID when present, otherwise derive one by index."""

    value = str(article.get("article_id") or "").strip()
    if value and not _ARTICLE_ID.fullmatch(value):
        raise ValueError(f"invalid candidate article_id {value}")
    return value or article_id_for_index(index)


def article_reference_map(articles: list[dict]) -> dict[str, dict]:
    """Index articles by their stable private reference and reject collisions."""

    references: dict[str, dict] = {}
    for index, article in enumerate(articles, 1):
        article_id = article_reference_id(article, index)
        if article_id in references:
            raise ValueError(f"duplicate candidate article_id {article_id}")
        references[article_id] = article
    return references


def article_source_group(article: dict) -> str:
    """Return the source family used by the diversity policy."""

    source = str(article.get("source") or "").strip().lower()
    if source in {"agihunt", "agihunt_trending"}:
        return "agihunt"
    if source:
        return source
    hostname = (urlsplit(str(article.get("link") or "")).hostname or "").lower()
    return hostname or "unknown"


def article_source_label(article: dict) -> str:
    """Return a truthful reader-facing label for one selected candidate."""

    source = str(article.get("source") or "").strip().lower()
    labels = {
        "agihunt": "AGI HUNT · agihunt.info",
        "agihunt_trending": "AGI HUNT · agihunt.info",
        "aibase": "AIBase",
        "techcrunch": "TechCrunch",
        "theverge": "The Verge",
        "syft": "Syft",
    }
    if source in labels:
        return labels[source]
    hostname = (urlsplit(str(article.get("link") or "")).hostname or "").lower()
    return hostname.removeprefix("www.") or source


def candidate_has_enough_facts(article: dict) -> bool:
    """Apply a small, explainable content floor before promising diversity."""

    title = "".join(str(article.get("title") or "").split())
    if not title:
        return False
    if (
        str(article.get("description") or "").strip()
        or str(article.get("content") or "").strip()
    ):
        return True
    return len(title) >= MIN_TITLE_ONLY_VISIBLE_CHARS


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_v1(article: dict, index: int) -> _Candidate:
    provenance = article.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    return _Candidate(
        article_id=article_reference_id(article, index),
        original_index=index,
        article=article,
        source_group=article_source_group(article),
        qualified=candidate_has_enough_facts(article),
        ai_topic=_has_ai_topic(article),
        priority=_safe_int(article.get("priority"), 0),
        trend_rank=_safe_int(provenance.get("trend_rank"), 1_000_000),
        trend_heat=_safe_float(provenance.get("trend_heat"), 0.0),
    )


def _has_ai_topic(article: dict) -> bool:
    """Give a small deterministic boost to explicit AI topics without filtering."""

    title = str(article.get("title") or "")
    description = str(article.get("description") or "")
    return bool(_AI_TOPIC.search(f"{title}\n{description}"))


def _base_order_v1(candidate: _Candidate) -> tuple[int, int, int, float, int]:
    return (
        -candidate.priority,
        -int(candidate.ai_topic),
        candidate.trend_rank,
        -candidate.trend_heat,
        candidate.original_index,
    )


def select_summary_candidates_v1(articles: list[dict], limit: int) -> list[dict]:
    """Select a deterministic, source-balanced set and preserve snapshot IDs.

    One qualified candidate is reserved for every available source before the
    remaining slots are filled by priority.  With at least two qualified source
    families, a source is capped at 60% while alternatives remain.  The cap is
    relaxed only when it would otherwise leave the digest under-filled.
    """

    if limit < 1 or not articles:
        return []
    ranked_candidates = sorted(
        (_candidate_v1(article, index) for index, article in enumerate(articles, 1)),
        key=_base_order_v1,
    )
    qualified_candidates = [item for item in ranked_candidates if item.qualified]
    # A low-information fallback keeps tiny tests/manual inputs usable, but it
    # never competes with a candidate that passed the content floor.
    candidates = qualified_candidates or ranked_candidates
    target = min(limit, len(candidates))
    qualified_groups: list[str] = []
    for candidate in candidates:
        if candidate.qualified and candidate.source_group not in qualified_groups:
            qualified_groups.append(candidate.source_group)

    selected: list[_Candidate] = []
    selected_ids: set[str] = set()
    counts: Counter[str] = Counter()

    # Reserve one slot for each qualified source family.  If there are more
    # source families than slots, their strongest candidate determines order.
    for source_group in qualified_groups[:target]:
        candidate = next(
            item
            for item in candidates
            if item.qualified and item.source_group == source_group
        )
        selected.append(candidate)
        selected_ids.add(candidate.article_id)
        counts[candidate.source_group] += 1

    source_cap = (
        max(1, floor(target * MAX_SOURCE_SHARE))
        if len(qualified_groups) >= 2
        else target
    )
    while len(selected) < target:
        remaining = [item for item in candidates if item.article_id not in selected_ids]
        if not remaining:
            break
        qualified_remaining = [item for item in remaining if item.qualified]
        if qualified_remaining:
            remaining = qualified_remaining
        within_cap = [
            item for item in remaining if counts[item.source_group] < source_cap
        ]
        pool = within_cap or remaining
        candidate = min(
            pool,
            key=lambda item: (
                -item.priority,
                -int(item.ai_topic),
                counts[item.source_group],
                item.trend_rank,
                -item.trend_heat,
                item.original_index,
            ),
        )
        selected.append(candidate)
        selected_ids.add(candidate.article_id)
        counts[candidate.source_group] += 1

    # Keep the editorial importance order in the model input. Source diversity
    # is guaranteed by membership and later exact-ID validation, not by relying
    # on input position.
    selected.sort(key=_base_order_v1)
    result: list[dict] = []
    for candidate in selected:
        article = dict(candidate.article)
        article["article_id"] = candidate.article_id
        result.append(article)
    return result


@dataclass(frozen=True, slots=True)
class _EditorialCandidate:
    article_id: str
    original_index: int
    article: dict
    source_group: str
    qualified: bool
    priority: int
    trend_rank: int
    trend_heat: float
    analysis: EditorialAnalysis
    number_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SummarySelection:
    """Selected candidates plus private, JSON-safe decision diagnostics."""

    articles: tuple[dict, ...]
    diagnostics: dict[str, Any]


_NUMBER_KEY = re.compile(
    r"(?<![a-z0-9])[$¥]?\d+(?:\.\d+)?\s*(?:trillion|billion|million|[tbm]|万|亿)?",
    re.IGNORECASE,
)
_GENERIC_MODEL_ALIASES = {
    "chatgpt",
    "claude",
    "deepseek",
    "gemini",
    "glm",
    "gpt",
    "grok",
    "hunyuan",
    "kimi",
    "llama",
    "qwen",
}


def _number_keys(article: dict) -> tuple[str, ...]:
    text = f"{article.get('title') or ''}\n{article.get('description') or ''}"
    return tuple(
        sorted(
            {
                "".join(match.group(0).casefold().split())
                for match in _NUMBER_KEY.finditer(text)
            }
        )
    )


def _editorial_candidate(article: dict, index: int) -> _EditorialCandidate:
    provenance = article.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    return _EditorialCandidate(
        article_id=article_reference_id(article, index),
        original_index=index,
        article=article,
        source_group=article_source_group(article),
        qualified=candidate_has_enough_facts(article),
        priority=_safe_int(article.get("priority"), 0),
        trend_rank=_safe_int(provenance.get("trend_rank"), 1_000_000),
        trend_heat=_safe_float(provenance.get("trend_heat"), 0.0),
        analysis=analyze_article(article),
        number_keys=_number_keys(article),
    )


def _base_order_v2(
    candidate: _EditorialCandidate,
) -> tuple[int, int, int, float, int]:
    return (
        -candidate.analysis.relevance_level,
        -candidate.priority,
        candidate.trend_rank,
        -candidate.trend_heat,
        candidate.original_index,
    )


def _story_relation(
    left: _EditorialCandidate, right: _EditorialCandidate
) -> str | None:
    """Return a conservative cross-language same-story reason."""

    shared_entities = set(left.analysis.mentioned_entities) & set(
        right.analysis.mentioned_entities
    )
    shared_actions = set(left.analysis.action_keys) & set(right.analysis.action_keys)
    if len(shared_entities) >= 2 and shared_actions:
        return "shared_entities_action"
    if not shared_entities or not shared_actions:
        return None

    shared_objects = set(left.analysis.object_keys) & set(right.analysis.object_keys)
    shared_numbers = set(left.number_keys) & set(right.number_keys)
    shared_model_aliases = (
        set(left.analysis.model_aliases)
        & set(right.analysis.model_aliases) - _GENERIC_MODEL_ALIASES
    )
    if shared_objects:
        return "shared_entity_action_object"
    if shared_model_aliases:
        return "shared_entity_action_model"
    if shared_numbers:
        return "shared_entity_action_number"
    return None


def _collapse_story_clusters(
    candidates: list[_EditorialCandidate],
) -> tuple[list[_EditorialCandidate], list[dict[str, Any]]]:
    representatives: list[_EditorialCandidate] = []
    clusters: list[dict[str, Any]] = []
    cluster_by_representative: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        match: _EditorialCandidate | None = None
        reason = ""
        for representative in representatives:
            relation = _story_relation(candidate, representative)
            if relation:
                match = representative
                reason = relation
                break
        if match is None:
            representatives.append(candidate)
            continue
        cluster = cluster_by_representative.get(match.article_id)
        if cluster is None:
            cluster = {
                "representative_id": match.article_id,
                "member_ids": [match.article_id],
                "reasons": [],
            }
            cluster_by_representative[match.article_id] = cluster
            clusters.append(cluster)
        cluster["member_ids"].append(candidate.article_id)
        if reason not in cluster["reasons"]:
            cluster["reasons"].append(reason)
    return representatives, clusters


def _candidate_violations(
    candidate: _EditorialCandidate,
    *,
    source_counts: Counter[str],
    primary_counts: Counter[str],
    mentioned_counts: Counter[str],
    model_counts: Counter[str],
    source_cap: int,
) -> set[str]:
    violations: set[str] = set()
    if source_counts[candidate.source_group] >= source_cap:
        violations.add("source_cap")
    primary = candidate.analysis.primary_entity
    if primary and primary_counts[primary] >= MAX_PRIMARY_ENTITY_ITEMS:
        violations.add("primary_entity")
    if any(
        mentioned_counts[entity_id] >= MAX_MENTIONED_ENTITY_ITEMS
        for entity_id in candidate.analysis.mentioned_entities
    ):
        violations.add("mentioned_entity")
    if any(
        model_counts[family_id] >= MAX_MODEL_FAMILY_ITEMS
        for family_id in candidate.analysis.model_families
    ):
        violations.add("model_family")
    return violations


def _selection_key(
    candidate: _EditorialCandidate,
    *,
    source_counts: Counter[str],
    topic_counts: Counter[str],
) -> tuple[int, int, int, int, int, float, int]:
    # The third item from one topic is softly delayed, while relevance and
    # source priority remain the stronger editorial signals.
    topic_penalty = max(0, topic_counts[candidate.analysis.topic] - 1)
    return (
        -candidate.analysis.relevance_level,
        -candidate.priority,
        topic_penalty,
        source_counts[candidate.source_group],
        candidate.trend_rank,
        -candidate.trend_heat,
        candidate.original_index,
    )


def _choose_candidate(
    pool: list[_EditorialCandidate],
    *,
    source_counts: Counter[str],
    primary_counts: Counter[str],
    mentioned_counts: Counter[str],
    model_counts: Counter[str],
    topic_counts: Counter[str],
    source_cap: int,
) -> tuple[_EditorialCandidate, tuple[str, ...]]:
    relaxations = (
        frozenset(),
        frozenset({"model_family"}),
        frozenset({"model_family", "mentioned_entity"}),
        frozenset({"model_family", "mentioned_entity", "primary_entity"}),
        frozenset({"model_family", "mentioned_entity", "primary_entity", "source_cap"}),
    )
    for allowed in relaxations:
        eligible = [
            candidate
            for candidate in pool
            if _candidate_violations(
                candidate,
                source_counts=source_counts,
                primary_counts=primary_counts,
                mentioned_counts=mentioned_counts,
                model_counts=model_counts,
                source_cap=source_cap,
            )
            <= allowed
        ]
        if eligible:
            candidate = min(
                eligible,
                key=lambda item: _selection_key(
                    item,
                    source_counts=source_counts,
                    topic_counts=topic_counts,
                ),
            )
            violations = _candidate_violations(
                candidate,
                source_counts=source_counts,
                primary_counts=primary_counts,
                mentioned_counts=mentioned_counts,
                model_counts=model_counts,
                source_cap=source_cap,
            )
            return candidate, tuple(sorted(violations))
    raise ValueError("candidate pool unexpectedly became unselectable")


def _increment_selection_counts(
    candidate: _EditorialCandidate,
    *,
    source_counts: Counter[str],
    primary_counts: Counter[str],
    mentioned_counts: Counter[str],
    model_counts: Counter[str],
    topic_counts: Counter[str],
    region_counts: Counter[str],
) -> None:
    source_counts[candidate.source_group] += 1
    if candidate.analysis.primary_entity:
        primary_counts[candidate.analysis.primary_entity] += 1
    mentioned_counts.update(candidate.analysis.mentioned_entities)
    model_counts.update(candidate.analysis.model_families)
    topic_counts[candidate.analysis.topic] += 1
    region_counts.update(candidate.analysis.regions)


def select_summary_candidates_with_diagnostics(
    articles: list[dict], limit: int
) -> SummarySelection:
    """Apply the source-balanced v2 editorial policy with replay diagnostics."""

    catalog = load_editorial_catalog()
    if limit < 1 or not articles:
        return SummarySelection(
            articles=(),
            diagnostics={
                "selection_policy": SUMMARY_SELECTION_POLICY,
                "catalog_schema_version": catalog.schema_version,
                "catalog_as_of": catalog.as_of,
                "input_count": len(articles),
                "selected_count": 0,
            },
        )

    ranked = sorted(
        (
            _editorial_candidate(article, index)
            for index, article in enumerate(articles, 1)
        ),
        key=_base_order_v2,
    )
    qualified = [candidate for candidate in ranked if candidate.qualified]
    base_candidates = qualified or ranked
    representatives, story_clusters = _collapse_story_clusters(base_candidates)
    core_candidates = [
        candidate
        for candidate in representatives
        if candidate.analysis.relevance_level >= 2
    ]
    target_before_relevance = min(limit, len(representatives))
    candidates = (
        core_candidates
        if len(core_candidates) >= target_before_relevance
        else representatives
    )
    target = min(limit, len(candidates))

    source_groups: list[str] = []
    for candidate in candidates:
        if candidate.source_group not in source_groups:
            source_groups.append(candidate.source_group)
    source_cap = (
        max(1, floor(target * MAX_SOURCE_SHARE)) if len(source_groups) >= 2 else target
    )

    selected: list[_EditorialCandidate] = []
    selected_ids: set[str] = set()
    source_counts: Counter[str] = Counter()
    primary_counts: Counter[str] = Counter()
    mentioned_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    quota_relaxations: list[dict[str, Any]] = []

    def add(candidate: _EditorialCandidate, relaxed: tuple[str, ...]) -> None:
        selected.append(candidate)
        selected_ids.add(candidate.article_id)
        _increment_selection_counts(
            candidate,
            source_counts=source_counts,
            primary_counts=primary_counts,
            mentioned_counts=mentioned_counts,
            model_counts=model_counts,
            topic_counts=topic_counts,
            region_counts=region_counts,
        )
        if relaxed:
            quota_relaxations.append(
                {"article_id": candidate.article_id, "constraints": list(relaxed)}
            )

    # Preserve source breadth, but choose a different story/entity from a source
    # when its strongest candidate would repeat an already reserved family.
    for source_group in source_groups[:target]:
        pool = [
            candidate
            for candidate in candidates
            if candidate.source_group == source_group
            and candidate.article_id not in selected_ids
        ]
        if not pool:
            continue
        candidate, relaxed = _choose_candidate(
            pool,
            source_counts=source_counts,
            primary_counts=primary_counts,
            mentioned_counts=mentioned_counts,
            model_counts=model_counts,
            topic_counts=topic_counts,
            source_cap=source_cap,
        )
        add(candidate, relaxed)

    while len(selected) < target:
        pool = [
            candidate
            for candidate in candidates
            if candidate.article_id not in selected_ids
        ]
        if not pool:
            break
        candidate, relaxed = _choose_candidate(
            pool,
            source_counts=source_counts,
            primary_counts=primary_counts,
            mentioned_counts=mentioned_counts,
            model_counts=model_counts,
            topic_counts=topic_counts,
            source_cap=source_cap,
        )
        add(candidate, relaxed)

    selected.sort(key=_base_order_v2)
    selected_articles: list[dict] = []
    selected_metadata: list[dict[str, Any]] = []
    for candidate in selected:
        article = dict(candidate.article)
        article["article_id"] = candidate.article_id
        selected_articles.append(article)
        selected_metadata.append(
            {
                "article_id": candidate.article_id,
                "relevance_level": candidate.analysis.relevance_level,
                "primary_entity": candidate.analysis.primary_entity,
                "mentioned_entities": list(candidate.analysis.mentioned_entities),
                "model_families": list(candidate.analysis.model_families),
                "topic": candidate.analysis.topic,
                "regions": list(candidate.analysis.regions),
            }
        )

    diagnostics: dict[str, Any] = {
        "selection_policy": SUMMARY_SELECTION_POLICY,
        "catalog_schema_version": catalog.schema_version,
        "catalog_as_of": catalog.as_of,
        "input_count": len(articles),
        "qualified_count": len(qualified),
        "core_ai_input_count": sum(
            candidate.analysis.relevance_level >= 2 for candidate in ranked
        ),
        "candidate_story_count": len(representatives),
        "selected_count": len(selected_articles),
        "unique_story_count": len(selected_articles),
        "duplicate_story_rejected_count": sum(
            len(cluster["member_ids"]) - 1 for cluster in story_clusters
        ),
        "story_clusters": story_clusters,
        "source_counts": dict(sorted(source_counts.items())),
        "primary_entity_counts": dict(sorted(primary_counts.items())),
        "mentioned_entity_counts": dict(sorted(mentioned_counts.items())),
        "model_family_counts": dict(sorted(model_counts.items())),
        "topic_counts": dict(sorted(topic_counts.items())),
        "region_counts": dict(sorted(region_counts.items())),
        "quota_relaxations": quota_relaxations,
        "selected_metadata": selected_metadata,
    }
    return SummarySelection(articles=tuple(selected_articles), diagnostics=diagnostics)


def select_summary_candidates(articles: list[dict], limit: int) -> list[dict]:
    """Return the v2 deterministic shortlist used by all current runs."""

    return list(select_summary_candidates_with_diagnostics(articles, limit).articles)


def selected_source_counts(articles: list[dict]) -> dict[str, int]:
    """Return stable source-family counts for diagnostics and tests."""

    return dict(Counter(article_source_group(article) for article in articles))
