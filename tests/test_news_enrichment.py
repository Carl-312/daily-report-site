from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from config import load_config
from utils import news_enrichment
from utils.news_enrichment import enrich_articles_with_tavily


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")


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


def test_enrichment_disabled_returns_original_articles() -> None:
    cfg = load_config("/home/carl/daily-report-site/config.yaml")

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
    cfg = load_config("/home/carl/daily-report-site/config.yaml")

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
    cfg = load_config("/home/carl/daily-report-site/config.yaml")

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
    assert result["report"]["rejected_candidates"][0]["validation_outcome"] == "not_evaluated"
    assert result["report"]["rejected_candidates"][0]["rejection_reason"] is None


def test_enrichment_session_trust_env_follows_settings(monkeypatch) -> None:
    cfg = load_config("/home/carl/daily-report-site/config.yaml")
    seen: list[bool] = []

    def capture_session(session, api_key, payload):
        seen.append(session.trust_env)
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr(news_enrichment, "search_tavily", capture_session)

    enrich_articles_with_tavily(
        sample_articles(),
        report_date="2026-04-01",
        settings=cfg.enrichment.model_copy(update={"enabled": True, "trust_env": False}),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 4, 1, 12, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert seen
    assert all(value is False for value in seen)


def test_enrichment_below_min_stop_reason_when_official_fallback_disabled(monkeypatch) -> None:
    cfg = load_config("/home/carl/daily-report-site/config.yaml")

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
