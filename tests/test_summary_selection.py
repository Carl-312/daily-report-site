from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils.summary_contracts import SummaryItem, SummaryResult, validate_summary_result
from utils.summary_selection import (
    SUMMARY_SELECTION_POLICY,
    SUMMARY_SELECTION_POLICY_V1,
    article_reference_map,
    select_summary_candidates,
    select_summary_candidates_v1,
    select_summary_candidates_with_diagnostics,
    selected_source_counts,
)


SNAPSHOT = (
    Path(__file__).resolve().parent / "fixtures" / "summary-selection-2026-07-18.json"
)
VALID_SUMMARY = (
    "该候选清楚说明了新闻主体、已经发生的动作以及目前可确认的结果，"
    "并保留原始信息中的事实状态。"
)


def _production_articles() -> list[dict]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["articles"]


def _result(
    articles: list[dict], candidate_ids: tuple[str, ...], output_ids: tuple[str, ...]
) -> SummaryResult:
    references = article_reference_map(articles)
    return SummaryResult(
        policy="required_ai",
        items=tuple(
            SummaryItem(
                article_id=article_id,
                title=str(references[article_id]["title"]),
                summary=VALID_SUMMARY,
                url=str(references[article_id].get("link") or ""),
            )
            for article_id in output_ids
        ),
        discussion_topic="你最关注哪条AI新闻？",
        provider="fixture",
        model="small-model",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
        selection_policy=SUMMARY_SELECTION_POLICY,
        candidate_article_ids=candidate_ids,
        selection_diagnostics=select_summary_candidates_with_diagnostics(
            articles, 10
        ).diagnostics,
    )


def test_issue_snapshot_selects_a_source_balanced_shortlist() -> None:
    articles = _production_articles()

    selected = select_summary_candidates(articles, 10)

    assert [article["article_id"] for article in selected] == [
        "a1",
        "a2",
        "a4",
        "a6",
        "a9",
        "a14",
        "a33",
        "a30",
        "a16",
        "a17",
    ]
    assert selected_source_counts(selected) == {
        "agihunt": 6,
        "techcrunch": 2,
        "theverge": 2,
    }
    assert selected[0]["provenance"]["trend_rank"] == "1"
    assert selected[0]["provenance"]["trend_heat"] == "7.8"

    diagnostics = select_summary_candidates_with_diagnostics(articles, 10).diagnostics
    assert diagnostics["duplicate_story_rejected_count"] == 2
    assert diagnostics["story_clusters"] == [
        {
            "representative_id": "a4",
            "member_ids": ["a4", "a31"],
            "reasons": ["shared_entities_action"],
        },
        {
            "representative_id": "a10",
            "member_ids": ["a10", "a29"],
            "reasons": ["shared_entity_action_object"],
        },
    ]
    assert diagnostics["primary_entity_counts"]["anthropic"] == 1
    assert diagnostics["mentioned_entity_counts"]["anthropic"] == 2
    assert max(diagnostics["primary_entity_counts"].values()) <= 2
    assert max(diagnostics["model_family_counts"].values()) <= 1
    assert diagnostics["quota_relaxations"] == []


def _tie_candidate(
    title: str,
    *,
    link: str,
    publish_time: str,
    priority: int = 1,
    evidence: list[dict] | None = None,
    provenance: dict | None = None,
) -> dict:
    return {
        "title": title,
        "description": (
            "The AI report documents a concrete product change and its current result."
        ),
        "link": link,
        "publish_time": publish_time,
        "priority": priority,
        "source": "same-source",
        "evidence_status": "direct",
        "confidence": "reported",
        "provenance": provenance or {},
        "evidence": evidence or [],
    }


def test_equal_candidates_prefer_more_distinct_direct_evidence_domains() -> None:
    articles = [
        _tie_candidate(
            "AI assistant Alpha launches a workflow update",
            link="https://news.example/alpha",
            publish_time="2026-07-22T10:00:00Z",
            evidence=[
                {"url": "https://www.news.example/alpha-copy"},
                {"url": "https://news.example/alpha-second-copy"},
            ],
        ),
        _tie_candidate(
            "AI assistant Beta launches a workflow update",
            link="https://news.example/beta",
            publish_time="2026-07-21T10:00:00Z",
            evidence=[
                {"url": "https://reuters.com/technology/beta"},
                {"url": "https://www.reuters.com/technology/beta-copy"},
            ],
        ),
    ]

    selection = select_summary_candidates_with_diagnostics(articles, 1)

    assert [article["article_id"] for article in selection.articles] == ["a2"]
    assert selection.diagnostics["selected_metadata"][0]["evidence_domain_count"] == 2


def test_equal_evidence_candidates_prefer_newer_real_source_time() -> None:
    articles = [
        _tie_candidate(
            "AI assistant Alpha launches a workflow update",
            link="https://news.example/alpha",
            publish_time="Mon, 20 Jul 2026 10:00:00 GMT",
        ),
        _tie_candidate(
            "AI assistant Beta launches a workflow update",
            link="https://news.example/beta",
            publish_time="2026-07-22T10:00:00+00:00",
        ),
    ]

    selection = select_summary_candidates_with_diagnostics(articles, 1)

    assert [article["article_id"] for article in selection.articles] == ["a2"]
    assert selection.diagnostics["selected_metadata"][0]["publish_time"] == (
        "2026-07-22T10:00:00Z"
    )


def test_trending_observation_time_cannot_win_the_freshness_tiebreak() -> None:
    articles = [
        _tie_candidate(
            "AI assistant Alpha launches a workflow update",
            link="https://news.example/alpha",
            publish_time="2026-07-23T10:00:00Z",
            provenance={"publish_time_semantics": "trend_observed_at"},
        ),
        _tie_candidate(
            "AI assistant Beta launches a workflow update",
            link="https://news.example/beta",
            publish_time="2026-07-20T10:00:00Z",
        ),
    ]

    selected = select_summary_candidates(articles, 1)

    assert [article["article_id"] for article in selected] == ["a2"]


def test_evidence_and_freshness_never_override_relevance_or_priority() -> None:
    strong_metadata = [
        {"url": "https://reuters.com/technology/corroboration"},
        {"url": "https://apnews.com/article/corroboration"},
    ]
    lower_relevance = _tie_candidate(
        "AI startup publishes an industry workflow analysis",
        link="https://news.example/lower-relevance",
        publish_time="2026-07-23T10:00:00Z",
        priority=5,
        evidence=strong_metadata,
    )
    higher_relevance = _tie_candidate(
        "OpenAI launches a new GPT model for developers",
        link="https://news.example/higher-relevance",
        publish_time="2026-07-20T10:00:00Z",
        priority=1,
    )
    selected = select_summary_candidates([lower_relevance, higher_relevance], 1)
    assert [article["article_id"] for article in selected] == ["a2"]

    high_priority = _tie_candidate(
        "AI assistant Gamma launches a workflow update",
        link="https://news.example/high-priority",
        publish_time="2026-07-20T10:00:00Z",
        priority=5,
    )
    low_priority = _tie_candidate(
        "AI assistant Delta launches a workflow update",
        link="https://news.example/low-priority",
        publish_time="2026-07-23T10:00:00Z",
        priority=1,
        evidence=strong_metadata,
    )
    selected = select_summary_candidates([high_priority, low_priority], 1)
    assert [article["article_id"] for article in selected] == ["a1"]


def test_single_source_story_remains_eligible_but_signal_does_not() -> None:
    articles = [
        _tie_candidate(
            "AI assistant Alpha launches a workflow update",
            link="https://news.example/alpha",
            publish_time="2026-07-22T10:00:00Z",
        ),
        {
            **_tie_candidate(
                "AI assistant Beta launches a workflow update",
                link="https://news.example/beta",
                publish_time="2026-07-23T10:00:00Z",
                evidence=[{"url": "https://reuters.com/technology/beta"}],
            ),
            "evidence_status": "signal",
            "confidence": "signal",
        },
    ]

    selected = select_summary_candidates(articles, 2)

    assert [article["article_id"] for article in selected] == ["a1"]


def test_selection_does_not_promise_diversity_for_an_empty_stub_source() -> None:
    articles = [
        {
            "title": f"主来源候选 {index}",
            "description": "该候选包含足够的事实描述，可供摘要程序稳定改写。",
            "source": "primary",
        }
        for index in range(1, 4)
    ] + [{"title": "短讯", "description": "", "source": "stub"}]

    selected = select_summary_candidates(articles, 2)

    assert selected_source_counts(selected) == {"primary": 2}


def test_selection_prefers_an_explicit_ai_story_within_one_source() -> None:
    articles = [
        {
            "title": "A new phone accessory reaches stores this week",
            "source": "tech",
        },
        {
            "title": "OpenAI launches an AI agent for software developers",
            "source": "tech",
        },
    ]

    selected = select_summary_candidates(articles, 1)

    assert [article["article_id"] for article in selected] == ["a2"]


def test_selection_does_not_fill_an_ai_edition_with_generic_technology() -> None:
    articles = [
        {
            "title": "OpenAI launches an AI agent for software developers",
            "description": "The product update documents the new agent workflow.",
            "source": "ai-news",
        },
        {
            "title": "The apps and gadgets every reader needs this week",
            "description": "A general list of consumer applications and hardware.",
            "source": "tech-news",
        },
    ]

    selection = select_summary_candidates_with_diagnostics(articles, 8)

    assert [article["article_id"] for article in selection.articles] == ["a1"]
    assert selection.diagnostics["selected_count"] == 1


def test_tavily_navigation_text_cannot_turn_a_generic_event_into_ai_news() -> None:
    articles = [
        {
            "title": "OpenAI launches an AI agent for developers",
            "description": "The release documents the agent workflow.",
            "source": "ai-news",
            "provenance": {
                "selection_title": "OpenAI launches an AI agent for developers",
                "selection_description": "The release documents the agent workflow.",
                "selection_content": "",
            },
        },
        {
            "title": "Hackers exploit two WordPress vulnerabilities",
            "description": (
                "The article describes remote code execution. Navigation: Google "
                "Meta Microsoft AI Robotics Security."
            ),
            "source": "generic-tech",
            "provenance": {
                "selection_title": "Hackers exploit two WordPress vulnerabilities",
                "selection_description": "",
                "selection_content": "",
            },
        },
    ]

    selection = select_summary_candidates_with_diagnostics(articles, 10)

    assert [article["article_id"] for article in selection.articles] == ["a1"]


def test_selection_keeps_distinct_stories_that_only_share_body_entities() -> None:
    articles = [
        {
            "title": "Kimi K3 model release draws attention in Silicon Valley",
            "description": (
                "Moonshot released Kimi K3 and compared its coding results with "
                "OpenAI and Anthropic models."
            ),
            "source": "source-one",
        },
        {
            "title": "Open-weight models turn inference into a control point",
            "description": (
                "An industry analysis compares OpenAI and Anthropic pricing and "
                "explains why model routing changes infrastructure control."
            ),
            "source": "source-two",
        },
    ]

    selection = select_summary_candidates_with_diagnostics(articles, 8)

    assert len(selection.articles) == 2
    assert selection.diagnostics["duplicate_story_rejected_count"] == 0


def test_summary_gate_requires_the_exact_local_shortlist() -> None:
    articles = _production_articles()
    selected = select_summary_candidates(articles, 10)
    candidate_ids = tuple(str(article["article_id"]) for article in selected)
    result = _result(articles, candidate_ids, candidate_ids)

    validate_summary_result(result, articles, max_items=10)

    with pytest.raises(ValueError, match="cover every selected candidate"):
        validate_summary_result(
            _result(articles, candidate_ids, candidate_ids[:-1]),
            articles,
            max_items=10,
        )
    with pytest.raises(ValueError, match="selection does not match local policy"):
        validate_summary_result(
            _result(
                articles, tuple(f"a{index}" for index in range(1, 11)), candidate_ids
            ),
            articles,
            max_items=10,
        )


def test_v1_snapshot_remains_replayable() -> None:
    articles = _production_articles()
    selected = select_summary_candidates_v1(articles, 10)
    candidate_ids = tuple(str(article["article_id"]) for article in selected)
    references = article_reference_map(articles)
    result = SummaryResult(
        policy="required_ai",
        items=tuple(
            SummaryItem(
                article_id=article_id,
                title=str(references[article_id]["title"]),
                summary=VALID_SUMMARY,
                url=str(references[article_id].get("link") or ""),
            )
            for article_id in candidate_ids
        ),
        discussion_topic="你最关注哪条AI新闻？",
        provider="fixture",
        model="legacy-v1",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
        selection_policy=SUMMARY_SELECTION_POLICY_V1,
        candidate_article_ids=candidate_ids,
    )

    validate_summary_result(result, articles, max_items=10)
