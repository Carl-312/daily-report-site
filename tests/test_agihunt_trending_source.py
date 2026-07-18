from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pytest

import main as daily_main
import sources as source_registry
from config import AgihuntTrendingSettings
from sources.agihunt_trending import (
    AGIHUNT_TRENDING_SOURCE_LABEL,
    AgihuntTrendingDomError,
    AgihuntTrendingSource,
    parse_trending_dom,
)
from sources.base import Article
from utils.headless_chrome import RenderedDom
from utils.publish_policy import decide_publication


NOW = datetime(2026, 7, 18, 8, 36, tzinfo=ZoneInfo("Asia/Shanghai"))


def trending_html(count: int = 15, *, rank_offset: int = 0) -> str:
    movements = ("▲ 10", "▼ 1", "新上榜", "—", "NEW")

    def rows() -> str:
        rendered = []
        for index in range(1, count + 1):
            rank = index + rank_offset
            movement = movements[(index - 1) % len(movements)]
            term_en = escape(f"Trend {index} & launch", quote=True)
            rendered.append(
                "<li><button>"
                f"<span>{rank}</span>"
                "<span>"
                f'<span title="{term_en}">趋势 {index}</span>'
                f"<span>趋势 {index} 的中文简介。</span>"
                "<span>"
                f"<span>{movement}</span>"
                '<span class="heat-bar"><i></i></span>'
                f"<span>{16 - index}.0</span>"
                "</span>"
                "</span>"
                "</button></li>"
            )
        return "".join(rendered)

    # The real SPA renders a hidden mobile copy outside main. The parser must
    # select only the desktop rail inside main.
    return f"<html><body><aside><ol>{rows()}</ol></aside><main><ol>{rows()}</ol></main></body></html>"


def settings(**updates) -> AgihuntTrendingSettings:
    values = {
        "page_url": "https://agihunt.info/",
        "expected_articles": 15,
        "minimum_articles": 10,
        "max_articles": 15,
    }
    values.update(updates)
    return AgihuntTrendingSettings(**values)


def test_parser_extracts_one_main_list_and_bilingual_movements() -> None:
    trends = parse_trending_dom(trending_html())

    assert len(trends) == 15
    assert [trend.rank for trend in trends] == list(range(1, 16))
    assert [trend.state for trend in trends[:5]] == [
        "up",
        "down",
        "new",
        "steady",
        "new",
    ]
    assert trends[0].term_en == "Trend 1 & launch"
    assert trends[0].heat == "15.0"


def test_parser_fails_closed_on_non_contiguous_ranks() -> None:
    with pytest.raises(AgihuntTrendingDomError, match="contiguous"):
        parse_trending_dom(trending_html(rank_offset=1))


def test_source_renders_once_and_maps_all_fifteen_articles() -> None:
    calls: list[tuple[str, dict]] = []

    def renderer(url: str, **kwargs) -> RenderedDom:
        calls.append((url, kwargs))
        return RenderedDom(
            html=trending_html(),
            chrome_version="Google Chrome 150.0.0.0",
            duration_ms=5432,
        )

    source = AgihuntTrendingSource(settings(), renderer=renderer)
    articles = source.fetch(max_articles=15, reference_dt=NOW)

    assert len(calls) == 1
    assert "/api/" not in calls[0][0]
    assert "day=2026-07-18" in calls[0][0]
    assert "window=1d" in calls[0][0]
    assert len(articles) == 15
    assert [article.priority for article in articles] == [
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        3,
        3,
        3,
        2,
        2,
        2,
        2,
        2,
    ]
    first = articles[0]
    assert first.source == "agihunt_trending"
    assert first.link == ("https://agihunt.info/?day=2026-07-18&t=Trend+1+%26+launch")
    assert first.provenance == {
        "provider": AGIHUNT_TRENDING_SOURCE_LABEL,
        "retrieval": "homepage_trending_dom",
        "trend_day": "2026-07-18",
        "trend_window": "1d",
        "trend_rank": "1",
        "trend_heat": "15.0",
        "trend_state": "up",
        "trend_delta": "10",
        "trend_term_en": "Trend 1 & launch",
        "observed_at": "2026-07-18T08:36:00+08:00",
        "publish_time_semantics": "trend_observed_at",
        "chrome_version": "Google Chrome 150.0.0.0",
    }
    assert source.last_status == "ok"
    assert source.last_fetched_count == 15
    assert source.last_accepted_count == 15
    assert {item.code for item in source.last_diagnostics} == {
        "agihunt_trending_snapshot"
    }


def test_partial_snapshot_is_explicitly_degraded_without_fabricating_rows() -> None:
    source = AgihuntTrendingSource(
        settings(),
        renderer=lambda *_args, **_kwargs: RenderedDom(
            html=trending_html(12),
            chrome_version="Google Chrome 150.0.0.0",
            duration_ms=100,
        ),
    )

    articles = source.fetch(max_articles=15, reference_dt=NOW)

    assert len(articles) == 12
    assert source.last_status == "degraded"
    assert "agihunt_trending_unexpected_count" in {
        diagnostic.code for diagnostic in source.last_diagnostics
    }


def test_registry_uses_the_trending_specific_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AgihuntTrendingSource(
        settings(),
        renderer=lambda *_args, **_kwargs: RenderedDom(
            html=trending_html(),
            chrome_version="Google Chrome 150.0.0.0",
            duration_ms=100,
        ),
    )
    monkeypatch.setattr(
        source_registry, "AgihuntTrendingSource", lambda **_kwargs: source
    )

    articles, outcomes = source_registry.fetch_batch(
        {"agihunt_trending": True},
        max_articles=14,
        agihunt_trending_settings=source.settings,
        agihunt_trending_max_articles=15,
        reference_dt=NOW,
    )

    assert len(articles) == 15
    assert outcomes[0].source == "agihunt_trending"
    assert outcomes[0].status == "ok"
    assert outcomes[0].accepted_count == 15


def test_trending_fetch_failure_does_not_block_the_production_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingTrendingSource:
        last_attempts = 1
        last_fetched_count = 0
        last_diagnostics = ()

        def fetch(self, **_kwargs):
            raise AgihuntTrendingDomError("fixture DOM drift")

    class HealthySource:
        last_attempts = 1
        last_fetched_count = 1
        last_status = "ok"
        last_diagnostics = ()

        def fetch(self, **_kwargs):
            return [
                Article(
                    title="Healthy fallback source",
                    link="https://example.test/fallback",
                    description="Fallback source remains available",
                    source="aibase",
                )
            ]

    monkeypatch.setattr(
        source_registry,
        "AgihuntTrendingSource",
        lambda **_kwargs: FailingTrendingSource(),
    )
    monkeypatch.setitem(source_registry.REGISTRY, "aibase", HealthySource)

    articles, outcomes = source_registry.fetch_batch(
        {"agihunt_trending": True, "aibase": True},
        agihunt_trending_settings=settings(),
        reference_dt=NOW,
    )

    assert len(articles) == 1
    assert [(outcome.source, outcome.status) for outcome in outcomes] == [
        ("agihunt_trending", "failed"),
        ("aibase", "ok"),
    ]
    decision = decide_publication(
        articles_count=len(articles),
        source_results=outcomes,
        summary_succeeded=True,
        build_succeeded=True,
    )
    assert decision.publish is True
    assert decision.status == "degraded"


def test_one_run_trending_override_does_not_mutate_config_sources() -> None:
    config = type(
        "Config",
        (),
        {"sources": {"agihunt_trending": False, "aibase": True}},
    )()

    enabled = daily_main.resolve_enabled_sources(
        config,
        type(
            "Args",
            (),
            {"agihunt": "auto", "agihunt_trending": "on"},
        )(),
    )

    assert enabled == {"agihunt_trending": True, "aibase": True}
    assert config.sources["agihunt_trending"] is False
