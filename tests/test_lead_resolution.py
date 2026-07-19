from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import load_config
from utils import news_enrichment
from utils.news_enrichment import enrich_articles_with_tavily
from utils.pipeline_diagnostics import (
    collect_pipeline_diagnostics,
    render_pipeline_diagnostics_markdown,
)


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
REFERENCE = datetime(2026, 7, 19, 12, 0, tzinfo=REPORT_TIMEZONE)


def _settings(**updates):
    return load_config().enrichment.model_copy(
        update={
            "enabled": True,
            "max_total_calls": 2,
            "max_lead_candidates": 1,
            "lead_search_rounds": 2,
            "max_verify_calls": 0,
            "max_refill_rounds": 0,
            "min_articles": 1,
            **updates,
        }
    )


def _lead() -> dict:
    return {
        "title": "DeepSeek V4 发布窗口与能力细节引发关注",
        "link": "https://agihunt.info/?day=2026-07-19&t=DeepSeek+V4",
        "description": "趋势页称 DeepSeek V4 接近发布，但没有给出原始报道。",
        "publish_time": "2026-07-19T08:36:00+08:00",
        "priority": 4,
        "source": "agihunt_trending",
        "kind": "lead",
        "evidence_status": "unresolved",
        "confidence": "signal",
        "provenance": {
            "trend_rank": "1",
            "trend_term_en": "DeepSeek V4",
            "publish_time_semantics": "trend_observed_at",
        },
    }


def _evidence(domain: str, slug: str, score: float) -> dict:
    return {
        "title": "DeepSeek V4 model release details and API availability",
        "url": f"https://{domain}/ai/{slug}",
        "published_date": "2026-07-19T02:00:00Z",
        "content": (
            "DeepSeek is preparing a V4 model release with new reasoning and API "
            "capabilities. The report identifies the release status, deployment "
            "scope, developer access, pricing context, and remaining uncertainty."
        ),
        "raw_content": (
            "Additional source text explains the product changes, rollout sequence, "
            "technical constraints, and the evidence behind the reported timeline."
        ),
        "score": score,
    }


def test_important_lead_uses_two_tavily_rounds_and_becomes_a_story(
    monkeypatch,
) -> None:
    payloads: list[dict] = []

    def fake_search(_session, _api_key, payload):
        payloads.append(payload)
        result = (
            _evidence("reuters.com", "deepseek-v4", 0.93)
            if len(payloads) == 1
            else _evidence("deepseek.com", "v4-release", 0.88)
        )
        return {"latency_ms": 12.0, "response": {"results": [result]}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)
    result = enrich_articles_with_tavily(
        [_lead()],
        report_date="2026-07-19",
        settings=_settings(),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert len(payloads) == 2
    assert all(payload["search_depth"] == "advanced" for payload in payloads)
    assert all(payload["include_raw_content"] == "text" for payload in payloads)
    assert result["report"]["lead_resolution_calls"] == 2
    assert result["report"]["lead_resolved_count"] == 1
    assert result["report"]["lead_unresolved_count"] == 0
    assert len(result["articles"]) == 1
    story = result["articles"][0]
    assert story["kind"] == "story"
    assert story["confidence"] == "corroborated"
    assert story["link"] == "https://reuters.com/ai/deepseek-v4"
    assert "reuters.com" in story["description"]
    assert "deepseek.com" in story["description"]
    assert story["provenance"]["resolution_stage"] == "tavily_lead_resolution"


def test_lead_resolution_failure_preserves_direct_story_and_surfaces_codes(
    monkeypatch,
) -> None:
    direct_story = {
        "title": "OpenAI publishes a direct product update",
        "link": "https://openai.com/index/product-update",
        "description": "The official post documents the shipped capability and rollout.",
        "publish_time": "2026-07-19T01:00:00Z",
        "source": "openai.com",
        "kind": "story",
        "evidence_status": "direct",
        "confidence": "reported",
    }

    def fail_search(*_args, **_kwargs):
        raise requests.Timeout("sensitive transport detail must stay private")

    monkeypatch.setattr(news_enrichment, "search_tavily", fail_search)
    result = enrich_articles_with_tavily(
        [direct_story, _lead()],
        report_date="2026-07-19",
        settings=_settings(),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert result["articles"] == [direct_story]
    assert result["report"]["lead_unresolved_count"] == 1
    assert result["report"]["preserved_budget_count"] == 0
    assert result["report"]["accepted_by_stage_preview"]["evidence_gate"] == [
        direct_story["title"]
    ]
    assert result["report"]["stage_failures"] == [
        {"stage": "lead_resolution", "code": "timeout", "count": 2}
    ]

    diagnostics = collect_pipeline_diagnostics(enrichment_report=result["report"])
    rendered = render_pipeline_diagnostics_markdown(diagnostics)
    assert "`enrichment.lead_resolution`：`timeout` ×2" in rendered
    assert "sensitive transport detail" not in rendered


def test_lead_resolution_rejects_a_nearby_story_with_a_different_subject(
    monkeypatch,
) -> None:
    unrelated = _evidence("axios.com", "kimi-k3", 0.96)
    unrelated["title"] = (
        "Claude Code and DeepSeek powered a Chinese cyber espionage campaign"
    )
    unrelated["content"] = (
        "The security report says DeepSeek-v4-pro was used inside an intrusion, "
        "but it provides no direct DeepSeek V4 release announcement or details."
    )

    def fake_search(_session, _api_key, _payload):
        return {"latency_ms": 12.0, "response": {"results": [unrelated]}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)
    result = enrich_articles_with_tavily(
        [_lead()],
        report_date="2026-07-19",
        settings=_settings(),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert result["articles"] == []
    assert result["report"]["lead_resolved_count"] == 0
    assert result["report"]["lead_unresolved_count"] == 1
    assert all(
        run["rejected_irrelevant_count"] == 1
        for run in result["report"]["lead_resolution_runs"]
    )


def test_lead_resolution_spends_rounds_on_distinct_primary_entities(
    monkeypatch,
) -> None:
    kimi = _lead()
    kimi.update(
        {
            "title": "Kimi K3 tops the coding leaderboard",
            "description": "A trend signal about the Kimi K3 model release.",
        }
    )
    kimi["provenance"] = {
        **kimi["provenance"],
        "trend_rank": "1",
        "trend_term_en": "Kimi K3 coding leaderboard",
    }
    duplicate_kimi = {
        **kimi,
        "title": "Kimi: threat or menace?",
        "provenance": {**kimi["provenance"], "trend_rank": "2"},
    }

    def fake_search(_session, _api_key, payload):
        if "Kimi" in payload["query"]:
            evidence = _evidence("reuters.com", "kimi-k3", 0.93)
            evidence["title"] = "Kimi K3 model release and benchmark details"
        else:
            evidence = _evidence("reuters.com", "deepseek-v4", 0.93)
        return {"latency_ms": 12.0, "response": {"results": [evidence]}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)
    result = enrich_articles_with_tavily(
        [kimi, duplicate_kimi, _lead()],
        report_date="2026-07-19",
        settings=_settings(max_total_calls=4, max_lead_candidates=2),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert result["report"]["lead_resolution_calls"] == 4
    assert result["report"]["lead_resolved_count"] == 2
    assert any(
        signal["reason"] == "lead_duplicate_entity"
        for signal in result["report"]["observation_signals"]
    )


def test_generic_ai_word_cannot_resolve_a_different_event(monkeypatch) -> None:
    lead = _lead()
    lead.update(
        {
            "title": "AI intelligence costs are falling faster than PCs",
            "description": "A chart claims AI intelligence is getting cheaper.",
        }
    )
    lead["provenance"] = {
        **lead["provenance"],
        "trend_term_en": "AI costs plunge past PCs",
    }
    nearby = _evidence("axios.com", "ai-shopping-agents", 0.94)
    nearby["title"] = "Retailers embrace AI as shopping bots become buyers"

    monkeypatch.setattr(
        news_enrichment,
        "search_tavily",
        lambda *_args, **_kwargs: {
            "latency_ms": 12.0,
            "response": {"results": [nearby]},
        },
    )
    result = enrich_articles_with_tavily(
        [lead],
        report_date="2026-07-19",
        settings=_settings(),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert result["articles"] == []
    assert result["report"]["lead_resolved_count"] == 0
    assert all(
        run["rejected_irrelevant_count"] == 1
        for run in result["report"]["lead_resolution_runs"]
    )
