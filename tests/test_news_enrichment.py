from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from config import load_config
from utils import news_enrichment
from utils.news_enrichment import enrich_articles_with_tavily


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config.yaml"


def load_project_config():
    return load_config(str(CONFIG_PATH))


def sample_articles() -> list[dict]:
    return [
        {
            "title": "OpenAI releases new developer tools",
            "link": "https://example.com/openai-devtools",
            "description": "Example description",
            "publish_time": "2026-04-01",
            "content": "",
            "priority": 1,
            "source": "techcrunch",
        }
    ]


def make_article(title: str, link: str = "https://example.com/story") -> dict:
    return {
        "title": title,
        "link": link,
        "description": "Example description",
        "publish_time": "2026-04-01",
        "content": "",
        "priority": 1,
        "source": "example",
    }


def test_enrichment_disabled_returns_original_articles() -> None:
    cfg = load_project_config()

    result = enrich_articles_with_tavily(
        sample_articles(),
        report_date="2026-04-01",
        settings=cfg.enrichment,
        tavily_api_key="",
        enabled=False,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["articles"] == sample_articles()
    assert result["report"]["skip_reason"] == "disabled"
    assert result["report"]["applied"] is False


def test_enrichment_missing_api_key_falls_back_safely() -> None:
    cfg = load_project_config()

    result = enrich_articles_with_tavily(
        sample_articles(),
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(update={"enabled": True}),
        tavily_api_key="",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["articles"] == sample_articles()
    assert result["report"]["skip_reason"] == "missing_api_key"
    assert result["report"]["stop_reason"] == "missing_api_key"
    assert result["report"]["applied"] is False


def test_load_config_reads_enrichment_settings(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sources:
  techcrunch: true
enrichment:
  enabled: true
  trust_env: false
  max_total_calls: 9
  trusted_domains:
    priority_refill_media_whitelist:
      - thenextweb.com
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    cfg = load_config(str(config_path))

    assert cfg.tavily_api_key == "test-key"
    assert cfg.enrichment.enabled is True
    assert cfg.enrichment.trust_env is False
    assert cfg.enrichment.max_total_calls == 9
    assert cfg.enrichment.trusted_domains.priority_refill_media_whitelist == [
        "thenextweb.com"
    ]


def test_enrichment_timeout_preserves_original_articles(monkeypatch) -> None:
    cfg = load_project_config()

    def raise_timeout(*args, **kwargs):
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr(news_enrichment, "search_tavily", raise_timeout)

    result = enrich_articles_with_tavily(
        sample_articles(),
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(update={"enabled": True}),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["articles"] == sample_articles()
    assert result["report"]["applied"] is True
    assert result["report"]["skip_reason"] is None
    assert result["report"]["verify_calls"] == 1
    assert result["report"]["preserved_error_count"] == 1
    assert result["report"]["final_count"] == 1
    assert result["report"]["parameters"]["trust_env"] is True
    assert result["report"]["verify_runs"][0]["request_outcome"] == "timeout"
    assert result["report"]["verify_runs"][0]["validation_outcome"] == "not_evaluated"
    assert result["report"]["accepted_by_stage_preview"]["preserved_errors"] == [
        "OpenAI releases new developer tools"
    ]
    assert result["report"]["rejected_candidates"][0]["request_outcome"] == "timeout"
    assert (
        result["report"]["rejected_candidates"][0]["validation_outcome"]
        == "not_evaluated"
    )
    assert result["report"]["rejected_candidates"][0]["rejection_reason"] is None


def test_enrichment_session_trust_env_follows_settings(monkeypatch) -> None:
    cfg = load_project_config()
    seen: list[bool] = []

    def capture_session(session, api_key, payload):
        seen.append(session.trust_env)
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr(news_enrichment, "search_tavily", capture_session)

    enrich_articles_with_tavily(
        sample_articles(),
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={"enabled": True, "trust_env": False}
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert seen
    assert all(value is False for value in seen)


def test_enrichment_below_min_stop_reason_when_official_fallback_disabled(
    monkeypatch,
) -> None:
    cfg = load_project_config()

    def fake_search(session, api_key, payload):
        include_domains = payload.get("include_domains") or []
        if "thenextweb.com" in include_domains or "venturebeat.com" in include_domains:
            return {"latency_ms": 10.0, "response": {"results": []}}
        if "reuters.com" in include_domains or "arstechnica.com" in include_domains:
            return {
                "latency_ms": 12.0,
                "response": {
                    "results": [
                        {
                            "title": "Anthropic expands enterprise AI revenue",
                            "url": "https://www.reuters.com/business/anthropic-expands-enterprise-ai-revenue-2026-04-01/",
                            "published_date": "2026-04-01T04:00:00Z",
                            "content": "Example content",
                            "score": 0.9,
                        }
                    ]
                },
            }
        raise AssertionError(f"Unexpected payload: {payload}")

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        [],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(update={"enabled": True}),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["report"]["input_count"] == 0
    assert result["report"]["secondary_refilled_count"] == 1
    assert (
        result["report"]["stop_reason"]
        == "below_min_articles_after_secondary_refill_official_fallback_disabled"
    )
    assert (
        "Upstream sources returned zero deduped articles, so any final output must come from Tavily refill."
        in result["report"]["notes"]
    )


def test_verify_rejects_matched_article_outside_24h(monkeypatch) -> None:
    cfg = load_project_config()
    article = sample_articles()[0]

    def fake_search(session, api_key, payload):
        assert payload["query"] == f'"{article["title"]}"'
        return {
            "latency_ms": 10.0,
            "response": {
                "results": [
                    {
                        "title": article["title"],
                        "url": article["link"],
                        "published_date": "2026-03-31T03:00:00Z",
                        "content": "Matched story outside the strict window.",
                        "score": 0.99,
                    }
                ]
            },
        }

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        [article],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 1,
                "max_verify_calls": 1,
                "min_articles": 1,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["articles"] == []
    assert result["report"]["final_count"] == 0
    assert result["report"]["verify_runs"][0]["request_outcome"] == "success"
    assert result["report"]["verify_runs"][0]["matched"] is True
    assert result["report"]["verify_runs"][0]["within_24h"] is False
    assert result["report"]["verify_runs"][0]["validation_outcome"] == "outside_24h"
    assert (
        result["report"]["rejected_candidates"][0]["rejection_reason"] == "outside_24h"
    )


def test_verify_rejects_matched_article_missing_published_date(monkeypatch) -> None:
    cfg = load_project_config()
    article = sample_articles()[0]

    def fake_search(session, api_key, payload):
        assert payload["query"] == f'"{article["title"]}"'
        return {
            "latency_ms": 10.0,
            "response": {
                "results": [
                    {
                        "title": article["title"],
                        "url": article["link"],
                        "published_date": None,
                        "content": "Matched story with missing date metadata.",
                        "score": 0.99,
                    }
                ]
            },
        }

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        [article],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 1,
                "max_verify_calls": 1,
                "min_articles": 1,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["articles"] == []
    assert result["report"]["final_count"] == 0
    assert result["report"]["verify_runs"][0]["request_outcome"] == "success"
    assert result["report"]["verify_runs"][0]["matched"] is True
    assert result["report"]["verify_runs"][0]["within_24h"] is None
    assert (
        result["report"]["verify_runs"][0]["validation_outcome"]
        == "missing_published_date"
    )
    assert (
        result["report"]["rejected_candidates"][0]["rejection_reason"]
        == "missing_published_date"
    )


def test_prefilter_keeps_ai_neighbor_in_lower_priority_bucket(monkeypatch) -> None:
    cfg = load_project_config()
    neighbor_title = (
        "California adopts new rules allowing manufacturers to test and deploy "
        "heavy-duty autonomous vehicles"
    )
    seen_queries: list[str] = []

    def fake_search(session, api_key, payload):
        seen_queries.append(payload["query"])
        return {"latency_ms": 5.0, "response": {"results": []}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        [make_article(neighbor_title)],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 1,
                "max_verify_calls": 1,
                "max_refill_rounds": 0,
                "min_articles": 0,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["report"]["prefilter_stats"]["excluded_non_ai_relevant"] == 0
    assert result["report"]["prefilter_bucket_counts"]["ai_neighbor"] == 1
    assert (
        result["report"]["prefilter_candidates"][0]["prefilter_bucket"] == "ai_neighbor"
    )
    assert seen_queries == [f'"{neighbor_title}"']


def test_verify_order_prioritizes_core_ai_then_neighbors_then_low_signal(
    monkeypatch,
) -> None:
    cfg = load_project_config()
    low_signal_title = "Startup funding round reshapes enterprise software market"
    neighbor_title = (
        "California adopts new rules allowing manufacturers to test and deploy "
        "heavy-duty autonomous vehicles"
    )
    core_ai_title = "OpenAI launches AI agents for developer tools"
    seen_queries: list[str] = []

    def fake_search(session, api_key, payload):
        seen_queries.append(payload["query"])
        return {"latency_ms": 5.0, "response": {"results": []}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        [
            make_article(low_signal_title, "https://example.com/low-signal"),
            make_article(neighbor_title, "https://example.com/neighbor"),
            make_article(core_ai_title, "https://example.com/core-ai"),
        ],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 3,
                "max_verify_calls": 3,
                "max_refill_rounds": 0,
                "min_articles": 0,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["report"]["prefilter_bucket_counts"] == {
        "core_ai": 1,
        "ai_neighbor": 1,
        "generic_or_low_signal": 1,
    }
    bucket_by_title = {
        candidate["title"]: candidate["prefilter_bucket"]
        for candidate in result["report"]["prefilter_candidates"]
    }
    assert bucket_by_title == {
        core_ai_title: "core_ai",
        neighbor_title: "ai_neighbor",
        low_signal_title: "generic_or_low_signal",
    }
    assert seen_queries == [
        f'"{core_ai_title}"',
        f'"{neighbor_title}"',
        f'"{low_signal_title}"',
    ]


def test_aggregate_like_article_is_hard_rejected_before_verify(monkeypatch) -> None:
    cfg = load_project_config()
    aggregate_article = {
        **make_article(
            "AI日报：OpenAI 发布新模型；Anthropic 获融资；Google 推出 AI 功能",
            "https://example.com/ai-daily-roundup",
        ),
        "source": "aibase",
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Aggregate-like articles must not enter Tavily verify")

    monkeypatch.setattr(news_enrichment, "search_tavily", fail_if_called)

    result = enrich_articles_with_tavily(
        [aggregate_article],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 1,
                "max_verify_calls": 1,
                "max_refill_rounds": 0,
                "min_articles": 0,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert result["report"]["prefilter_stats"]["excluded_aggregate_like"] == 1
    assert result["report"]["prefiltered_count"] == 0
    assert result["report"]["verify_calls"] == 0
    assert result["report"]["excluded_prefilter_candidates"][0]["exclude_reasons"] == [
        "aggregate_like"
    ]


def test_refill_keeps_strict_ai_title_relevance_gate(monkeypatch) -> None:
    cfg = load_project_config()

    def fake_search(session, api_key, payload):
        assert payload.get("include_domains") == ["thenextweb.com", "venturebeat.com"]
        return {
            "latency_ms": 10.0,
            "response": {
                "results": [
                    {
                        "title": "Startup funding round reshapes enterprise software market",
                        "url": "https://thenextweb.com/news/startup-funding-enterprise-software",
                        "published_date": "2026-04-01T03:30:00Z",
                        "content": "Low-signal startup funding item without a strong AI title.",
                        "score": 0.92,
                    }
                ]
            },
        }

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        [],
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 1,
                "max_verify_calls": 0,
                "max_refill_rounds": 1,
                "min_articles": 1,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    candidate = result["report"]["priority_refill_runs"][0]["candidate_results"][0]
    assert result["report"]["priority_refilled_count"] == 0
    assert result["report"]["final_count"] == 0
    assert candidate["within_24h"] is True
    assert candidate["ai_title_relevant"] is False
    assert candidate["accepted"] is False
