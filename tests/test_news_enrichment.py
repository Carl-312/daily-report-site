from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import load_config
from utils import news_enrichment
from utils.news_enrichment import enrich_articles_with_tavily


TZ = ZoneInfo("Asia/Shanghai")
REFERENCE = datetime(2026, 7, 21, 12, 0, tzinfo=TZ)


def settings(**updates):
    return load_config().enrichment.model_copy(
        update={
            "enabled": True,
            "max_total_calls": 30,
            "lead_search_rounds": 2,
            **updates,
        }
    )


def story(index: int, *, entity: str = "OpenAI") -> dict:
    return {
        "title": f"{entity} releases developer model update {index}",
        "link": f"https://example.com/news/{entity.lower()}-{index}",
        "description": (
            f"{entity} released update {index} with documented rollout scope, "
            "developer access details, measured results, and current limitations."
        ),
        "publish_time": "2026-07-21T02:00:00Z",
        "content": "",
        "priority": 3,
        "source": "example.com",
        "kind": "story",
        "evidence_status": "direct",
        "confidence": "direct",
    }


def lead(title: str = "DeepSeek V4 release details") -> dict:
    return {
        "title": title,
        "link": "https://agihunt.info/?day=2026-07-21&t=DeepSeek+V4",
        "description": "A trend signal without a direct source article.",
        "publish_time": "2026-07-21T08:00:00+08:00",
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


def result_for(article: dict, *, suffix: str = "evidence", score: float = 0.9) -> dict:
    return {
        "title": article["title"],
        "url": f"https://wire.example.com/news/{suffix}",
        "published_date": "2026-07-21T03:00:00Z",
        "content": (
            f"{article['title']} is documented with specific product scope, "
            "release timing, numeric results, rollout limits, and user impact."
        ),
        "raw_content": "Additional direct article body supplies background and constraints.",
        "score": score,
    }


def test_disabled_or_missing_key_preserves_stories_and_keeps_leads_private() -> None:
    direct = story(1)
    signal = lead()
    for enabled, key, reason in (
        (False, "key", "disabled"),
        (True, "", "missing_api_key"),
    ):
        enriched = enrich_articles_with_tavily(
            [direct, signal],
            report_date="2026-07-21",
            settings=settings(),
            tavily_api_key=key,
            enabled=enabled,
            reference_dt=REFERENCE,
        )
        assert enriched["articles"] == [direct]
        assert enriched["report"]["skip_reason"] == reason
        assert enriched["report"]["observation_signals"][0]["title"] == signal["title"]


def test_empty_metadata_queue_never_calls_tavily_or_refill(monkeypatch) -> None:
    monkeypatch.setattr(
        news_enrichment,
        "search_tavily",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected call")
        ),
    )
    enriched = enrich_articles_with_tavily(
        [],
        report_date="2026-07-21",
        settings=settings(),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )
    assert enriched["articles"] == []
    assert enriched["report"]["total_calls"] == 0
    assert enriched["report"]["refill_calls"] == 0
    assert enriched["report"]["stop_reason"] == "candidate_queue_exhausted"


def test_every_candidate_gets_round_one_before_any_round_two(monkeypatch) -> None:
    candidates = [
        story(index, entity=entity)
        for index, entity in enumerate(
            ("OpenAI", "Anthropic", "Google", "Microsoft"), 1
        )
    ]
    queries: list[str] = []

    def fake_search(_session, _api_key, payload):
        assert "include_domains" not in payload
        queries.append(payload["query"])
        return {"latency_ms": 5.0, "response": {"results": []}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)
    enriched = enrich_articles_with_tavily(
        candidates,
        report_date="2026-07-21",
        settings=settings(max_total_calls=6),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert len(queries) == 6
    assert all(
        candidate["link"] in queries[index]
        for index, candidate in enumerate(candidates)
    )
    assert enriched["report"]["candidate_processed_count"] == 4
    assert enriched["report"]["total_calls"] == 6
    assert enriched["report"]["refill_calls"] == 0
    assert enriched["report"]["stop_reason"] == "budget_exhausted"


def test_direct_story_failure_keeps_original_identity_and_content(monkeypatch) -> None:
    direct = story(1)
    monkeypatch.setattr(
        news_enrichment,
        "search_tavily",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.Timeout("private")),
    )
    enriched = enrich_articles_with_tavily(
        [direct],
        report_date="2026-07-21",
        settings=settings(max_total_calls=2),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )
    kept = enriched["articles"][0]
    for field in ("title", "link", "description", "publish_time", "source"):
        assert kept[field] == direct[field]
    assert kept["evidence"][0]["origin"] == "fetch"
    assert enriched["report"]["total_calls"] == 2
    assert enriched["report"]["refill_calls"] == 0


def test_lead_without_same_event_evidence_never_enters_main_news(monkeypatch) -> None:
    signal = lead("OpenAI launches a new coding agent")
    unrelated = {
        "title": "ServiceNow launches a workflow agent with OpenAI integration",
        "url": "https://example.net/news/servicenow-workflow-agent",
        "published_date": "2026-07-21T03:00:00Z",
        "content": "ServiceNow launched a workflow product for enterprise customers.",
        "score": 0.99,
    }
    monkeypatch.setattr(
        news_enrichment,
        "search_tavily",
        lambda *_args, **_kwargs: {
            "latency_ms": 5.0,
            "response": {"results": [unrelated]},
        },
    )
    enriched = enrich_articles_with_tavily(
        [signal],
        report_date="2026-07-21",
        settings=settings(max_total_calls=2),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )
    assert enriched["articles"] == []
    assert enriched["report"]["lead_resolved_count"] == 0
    assert enriched["report"]["lead_unresolved_count"] == 1
    assert all(
        run["rejected_irrelevant_count"] == 1
        for run in enriched["report"]["candidate_enrichment_runs"]
    )


def test_evidence_packet_is_structured_bounded_and_keeps_story_identity(
    monkeypatch,
) -> None:
    direct = story(1)
    calls = 0

    def fake_search(_session, _api_key, _payload):
        nonlocal calls
        calls += 1
        return {
            "latency_ms": 5.0,
            "response": {
                "results": [
                    result_for(
                        direct, suffix=f"{calls}-{index}", score=0.9 - index / 100
                    )
                    for index in range(4)
                ]
            },
        }

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)
    enriched = enrich_articles_with_tavily(
        [direct],
        report_date="2026-07-21",
        settings=settings(max_total_calls=2),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )
    item = enriched["articles"][0]
    assert item["title"] == direct["title"]
    assert item["link"] == direct["link"]
    assert len(item["evidence"]) == 3
    assert all(
        {"title", "url", "published_date", "snippet"} <= set(evidence)
        for evidence in item["evidence"]
    )


def test_daily_budget_is_hard_capped_at_thirty(monkeypatch) -> None:
    candidates = [story(index, entity=f"Vendor{index}") for index in range(20)]
    monkeypatch.setattr(
        news_enrichment,
        "search_tavily",
        lambda *_args, **_kwargs: {"latency_ms": 1.0, "response": {"results": []}},
    )
    enriched = enrich_articles_with_tavily(
        candidates,
        report_date="2026-07-21",
        settings=settings(max_total_calls=30),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )
    assert enriched["report"]["total_calls"] == 30
    assert enriched["report"]["candidate_processed_count"] == 20
    assert len(enriched["articles"]) == 20
    assert enriched["report"]["refill_calls"] == 0


def test_metadata_admission_caps_the_queue_so_every_candidate_is_searched(
    monkeypatch,
) -> None:
    candidates = [story(index, entity=f"Vendor{index}") for index in range(31)]
    monkeypatch.setattr(
        news_enrichment,
        "search_tavily",
        lambda *_args, **_kwargs: {"latency_ms": 1.0, "response": {"results": []}},
    )
    enriched = enrich_articles_with_tavily(
        candidates,
        report_date="2026-07-21",
        settings=settings(max_total_calls=30),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert enriched["report"]["input_count"] == 31
    assert enriched["report"]["candidate_queue_count"] == 30
    assert enriched["report"]["candidate_processed_count"] == 30
    assert enriched["report"]["candidate_dropped_count"] == 0
    assert enriched["report"]["candidate_unenriched_story_count"] == 1
    assert enriched["report"]["total_calls"] == 30
    assert len(enriched["articles"]) == 31


def test_usage_limit_stops_requests_and_preserves_all_direct_stories(
    monkeypatch,
) -> None:
    response = requests.Response()
    response.status_code = 432
    calls = 0

    def fail_with_usage_limit(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(news_enrichment, "search_tavily", fail_with_usage_limit)
    direct_stories = [story(index, entity=f"Vendor{index}") for index in range(31)]
    signal = lead()

    enriched = enrich_articles_with_tavily(
        [*direct_stories, signal],
        report_date="2026-07-21",
        settings=settings(max_total_calls=30),
        tavily_api_key="key",
        enabled=True,
        reference_dt=REFERENCE,
    )

    assert calls == 1
    assert len(enriched["articles"]) == 31
    assert enriched["report"]["terminal_error_code"] == "usage_limit_exceeded"
    assert enriched["report"]["stop_reason"] == (
        "candidate_enrichment_usage_limit_exceeded"
    )
    assert enriched["report"]["lead_unresolved_count"] == 1
