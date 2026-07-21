from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from config import load_config
from utils import news_enrichment
from utils.news_enrichment import enrich_articles_with_tavily


TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]


def test_historical_gray_fixture_now_uses_only_its_metadata_candidates(monkeypatch) -> None:
    fixture = json.loads(
        (ROOT / "tests/fixtures/tavily-gray-2026-05-11/report-minimal.json").read_text(
            encoding="utf-8"
        )
    )
    articles = [
        {
            **article,
            "description": article.get("description")
            or "Fetched source metadata preserves this direct article when Tavily has no match.",
            "publish_time": (
                fixture["report_date"]
                if article.get("publish_time") == "未知时间"
                else article.get("publish_time")
            ),
        }
        for article in fixture["articles"]
    ]
    payloads: list[dict] = []

    def fake_search(_session, _api_key, payload):
        payloads.append(payload)
        return {"latency_ms": 2.0, "response": {"results": []}}

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)
    settings = load_config().enrichment.model_copy(
        update={"enabled": True, "max_total_calls": 7}
    )
    result = enrich_articles_with_tavily(
        articles,
        report_date=fixture["report_date"],
        settings=settings,
        tavily_api_key="key",
        enabled=True,
        reference_dt=datetime(2026, 5, 11, 23, 0, tzinfo=TZ),
    )

    assert len(payloads) == 7
    assert all("include_domains" not in payload for payload in payloads)
    assert result["report"]["total_calls"] == 7
    assert result["report"]["refill_calls"] == 0
    assert result["report"]["priority_refill_runs"] == []
    assert result["report"]["secondary_refill_runs"] == []
    assert result["report"]["stop_reason"] == "budget_exhausted"
