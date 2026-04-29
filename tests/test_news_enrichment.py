from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import load_config
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
    assert cfg.enrichment.max_total_calls == 9
    assert cfg.enrichment.trusted_domains.priority_refill_media_whitelist == [
        "thenextweb.com"
    ]
