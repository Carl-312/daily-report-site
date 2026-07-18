"""Structured editorial knowledge used by deterministic daily selection.

The catalog keeps stable company/model families separate from fast-changing
model versions.  Matching stays local and explainable so live, offline, replay,
and publication validation can make the same decision without an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml


CATALOG_PATH = Path(__file__).resolve().parents[1] / "editorial_catalog.yaml"
_ASCII_WORD = re.compile(r"[a-z0-9]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ModelFamilySpec:
    family_id: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntitySpec:
    entity_id: str
    name: str
    region: str
    tier: str
    requires_ai_context: bool
    aliases: tuple[str, ...]
    model_families: tuple[ModelFamilySpec, ...]


@dataclass(frozen=True, slots=True)
class EditorialCatalog:
    schema_version: int
    as_of: str
    core_ai_terms: tuple[str, ...]
    neighbor_terms: tuple[str, ...]
    actions: dict[str, tuple[str, ...]]
    objects: dict[str, tuple[str, ...]]
    topics: dict[str, tuple[str, ...]]
    entities: tuple[EntitySpec, ...]


@dataclass(frozen=True, slots=True)
class EditorialAnalysis:
    relevance_level: int
    core_ai_signal: bool
    neighbor_signal: bool
    primary_entity: str
    mentioned_entities: tuple[str, ...]
    model_families: tuple[str, ...]
    model_aliases: tuple[str, ...]
    action_keys: tuple[str, ...]
    object_keys: tuple[str, ...]
    topic: str
    regions: tuple[str, ...]


def _required_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"editorial catalog {label} must be a list of strings")
    normalized = tuple(item.strip() for item in value if item.strip())
    if len(normalized) != len(set(item.casefold() for item in normalized)):
        raise ValueError(f"editorial catalog {label} contains duplicate aliases")
    return normalized


def _term_mapping(value: Any, label: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise ValueError(f"editorial catalog {label} must be a mapping")
    return {
        str(key).strip(): _required_list(aliases, f"{label}.{key}")
        for key, aliases in value.items()
    }


@lru_cache(maxsize=1)
def load_editorial_catalog() -> EditorialCatalog:
    """Load and validate the versioned editorial catalog once per process."""

    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("editorial catalog root must be a mapping")
    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list) or not raw_entities:
        raise ValueError("editorial catalog entities must be a non-empty list")

    entities: list[EntitySpec] = []
    seen_entities: set[str] = set()
    seen_models: set[str] = set()
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, dict):
            raise ValueError("editorial catalog entity must be a mapping")
        entity_id = str(raw_entity.get("id") or "").strip()
        if not entity_id or entity_id in seen_entities:
            raise ValueError(f"invalid or duplicate editorial entity id {entity_id}")
        seen_entities.add(entity_id)

        model_families: list[ModelFamilySpec] = []
        raw_models = raw_entity.get("models", [])
        if not isinstance(raw_models, list):
            raise ValueError(f"editorial entity {entity_id} models must be a list")
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                raise ValueError(
                    f"editorial entity {entity_id} model must be a mapping"
                )
            family_id = str(raw_model.get("id") or "").strip()
            if not family_id or family_id in seen_models:
                raise ValueError(f"invalid or duplicate model family id {family_id}")
            seen_models.add(family_id)
            model_families.append(
                ModelFamilySpec(
                    family_id=family_id,
                    aliases=_required_list(
                        raw_model.get("aliases", []),
                        f"entities.{entity_id}.models.{family_id}.aliases",
                    ),
                )
            )

        entities.append(
            EntitySpec(
                entity_id=entity_id,
                name=str(raw_entity.get("name") or entity_id).strip(),
                region=str(raw_entity.get("region") or "other").strip(),
                tier=str(raw_entity.get("tier") or "broad_tech").strip(),
                requires_ai_context=bool(raw_entity.get("requires_ai_context", True)),
                aliases=_required_list(
                    raw_entity.get("aliases", []),
                    f"entities.{entity_id}.aliases",
                ),
                model_families=tuple(model_families),
            )
        )

    return EditorialCatalog(
        schema_version=int(payload.get("schema_version", 1)),
        as_of=str(payload.get("as_of") or ""),
        core_ai_terms=_required_list(payload.get("core_ai_terms", []), "core_ai_terms"),
        neighbor_terms=_required_list(
            payload.get("neighbor_terms", []), "neighbor_terms"
        ),
        actions=_term_mapping(payload.get("actions", {}), "actions"),
        objects=_term_mapping(payload.get("objects", {}), "objects"),
        topics=_term_mapping(payload.get("topics", {}), "topics"),
        entities=tuple(entities),
    )


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias.casefold())
    if _ASCII_WORD.search(alias):
        return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


@lru_cache(maxsize=2048)
def _alias_positions(text: str, alias: str) -> tuple[int, ...]:
    return tuple(
        match.start() for match in _alias_pattern(alias).finditer(text.casefold())
    )


@lru_cache(maxsize=2048)
def _model_alias_positions(text: str, alias: str) -> tuple[int, ...]:
    """Match a stable family prefix followed by an unknown numeric version."""

    escaped = re.escape(alias.casefold())
    if _ASCII_WORD.search(alias):
        pattern = re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z])", re.IGNORECASE)
    else:
        pattern = re.compile(escaped, re.IGNORECASE)
    return tuple(match.start() for match in pattern.finditer(text.casefold()))


def _mapping_matches(text: str, mapping: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(
        key
        for key, aliases in mapping.items()
        if any(_alias_positions(text, alias) for alias in aliases)
    )


def _contains_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_alias_positions(text, term) for term in terms)


def _topic_for(
    *,
    action_keys: tuple[str, ...],
    object_keys: tuple[str, ...],
    relevance_level: int,
    catalog: EditorialCatalog,
) -> str:
    action_set = set(action_keys)
    if "lawsuit" in action_set or "policy" in action_set:
        return "legal_policy"
    if "recall" in action_set or "security" in action_set:
        return "safety_security"
    if {"robotaxi", "humanoid"} & set(object_keys):
        return "robotics_autonomy"
    if {"research", "benchmark"} & action_set:
        return "research_benchmark"
    if "data_center" in object_keys:
        return "infrastructure"
    if {"funding", "deal"} & action_set:
        return "funding_business"
    if {"access", "integrate", "rename"} & action_set:
        return "product_access"
    if {"release", "train"} & action_set:
        return "model_release"
    # Keep the mapping in the data file validated and available for diagnostics,
    # even though the ordered rules above resolve overlaps explicitly.
    if catalog.topics and relevance_level >= 2:
        return "other_ai"
    return "general_technology"


def analyze_editorial_text(title: str, description: str = "") -> EditorialAnalysis:
    """Classify one candidate without making a publication decision."""

    catalog = load_editorial_catalog()
    title = str(title or "")
    description = str(description or "")
    combined = f"{title}\n{description}"
    entity_positions: dict[str, int] = {}
    model_families: set[str] = set()
    model_aliases: set[str] = set()
    entity_by_id = {entity.entity_id: entity for entity in catalog.entities}

    for entity in catalog.entities:
        positions: list[int] = []
        for alias in entity.aliases:
            positions.extend(_alias_positions(combined, alias))
        for model in entity.model_families:
            matched_aliases = [
                alias
                for alias in model.aliases
                if _model_alias_positions(combined, alias)
            ]
            if matched_aliases:
                model_families.add(model.family_id)
                model_aliases.update(alias.casefold() for alias in matched_aliases)
                for alias in matched_aliases:
                    positions.extend(_model_alias_positions(combined, alias))
        if positions:
            entity_positions[entity.entity_id] = min(positions)

    title_entity_positions: dict[str, int] = {}
    for entity in catalog.entities:
        positions: list[int] = []
        for alias in entity.aliases:
            positions.extend(_alias_positions(title, alias))
        for model in entity.model_families:
            for alias in model.aliases:
                positions.extend(_model_alias_positions(title, alias))
        if positions:
            title_entity_positions[entity.entity_id] = min(positions)

    ordered_entities = tuple(
        sorted(
            entity_positions,
            key=lambda entity_id: (entity_positions[entity_id], entity_id),
        )
    )
    primary_positions = title_entity_positions or entity_positions
    primary_entity = (
        min(
            primary_positions,
            key=lambda entity_id: (primary_positions[entity_id], entity_id),
        )
        if primary_positions
        else ""
    )

    has_core_ai_context = _contains_term(combined, catalog.core_ai_terms)
    has_neighbor_context = _contains_term(combined, catalog.neighbor_terms)
    matched_specs = [entity_by_id[entity_id] for entity_id in ordered_entities]
    direct_frontier = any(
        entity.tier == "frontier_lab" and not entity.requires_ai_context
        for entity in matched_specs
    )
    direct_infrastructure = any(
        entity.tier == "ai_infrastructure" and not entity.requires_ai_context
        for entity in matched_specs
    )
    if model_families or direct_frontier:
        relevance_level = 3
    elif has_core_ai_context or (
        matched_specs
        and any(entity.tier == "frontier_lab" for entity in matched_specs)
        and has_neighbor_context
    ):
        relevance_level = 2
    elif has_neighbor_context or direct_infrastructure:
        relevance_level = 2
    elif matched_specs:
        relevance_level = 1
    else:
        relevance_level = 0

    action_keys = _mapping_matches(combined, catalog.actions)
    object_keys = _mapping_matches(combined, catalog.objects)
    topic = _topic_for(
        action_keys=action_keys,
        object_keys=object_keys,
        relevance_level=relevance_level,
        catalog=catalog,
    )
    regions = tuple(
        sorted({entity_by_id[entity_id].region for entity_id in ordered_entities})
    )
    return EditorialAnalysis(
        relevance_level=relevance_level,
        core_ai_signal=has_core_ai_context,
        neighbor_signal=has_neighbor_context,
        primary_entity=primary_entity,
        mentioned_entities=ordered_entities,
        model_families=tuple(sorted(model_families)),
        model_aliases=tuple(sorted(model_aliases)),
        action_keys=action_keys,
        object_keys=object_keys,
        topic=topic,
        regions=regions,
    )


def analyze_article(article: dict[str, Any]) -> EditorialAnalysis:
    """Analyze the trusted candidate fields used by the local selector."""

    return analyze_editorial_text(
        str(article.get("title") or ""),
        "\n".join(
            value
            for value in (
                str(article.get("description") or "").strip(),
                str(article.get("content") or "").strip(),
            )
            if value
        ),
    )
