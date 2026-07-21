from __future__ import annotations

from types import SimpleNamespace

import pytest

import main as daily_main
from utils.summary_contracts import SummaryItem, SummaryResult


def _valid_summary_result() -> SummaryResult:
    return SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="人工智能产品更新",
                summary="推动行业应用场景继续扩展。",
                url="",
            ),
        ),
        discussion_topic="你最关注哪条AI新闻？",
        provider="test",
        model="test",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )


def test_summarize_or_offline_raises_when_llm_fails_with_provider_key(
    monkeypatch, capsys
) -> None:
    articles = [{"title": "Fallback story", "priority": 0}]
    cfg = SimpleNamespace(api_key="modelscope-key", fallback_api_key="siliconflow-key")
    calls: list[str] = []

    def fake_summarize_result(article_payload, *, stream, deadline_at):
        calls.append("summarize_result")
        assert article_payload == articles
        assert stream is True
        assert deadline_at is None
        raise RuntimeError("provider outage")

    monkeypatch.setattr(daily_main, "summarize_result", fake_summarize_result)

    with pytest.raises(RuntimeError, match="failed quality checks"):
        daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert calls == ["summarize_result"]
    assert "refusing to publish an offline fallback" in capsys.readouterr().out


def test_summarize_or_offline_raises_when_llm_returns_invalid_result(
    monkeypatch, capsys
) -> None:
    articles = [{"title": "Empty response story", "priority": 0}]
    cfg = SimpleNamespace(api_key="modelscope-key", fallback_api_key="")
    calls: list[str] = []

    def fake_summarize_result(article_payload, *, stream, deadline_at):
        calls.append("summarize_result")
        assert article_payload == articles
        assert stream is True
        assert deadline_at is None
        return _valid_summary_result().model_copy(update={"items": ()})

    monkeypatch.setattr(daily_main, "summarize_result", fake_summarize_result)

    with pytest.raises(RuntimeError, match="failed quality checks"):
        daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert calls == ["summarize_result"]
    assert "refusing to publish an offline fallback" in capsys.readouterr().out


def test_summarize_or_offline_uses_offline_when_no_provider_key(monkeypatch) -> None:
    articles = [{"title": "Fallback story", "priority": 0}]
    cfg = SimpleNamespace(api_key="", fallback_api_key="")
    calls: list[str] = []

    def fake_offline_summary(article_payload):
        calls.append("offline_summary")
        assert article_payload == articles
        return "offline content"

    monkeypatch.setattr(daily_main, "offline_summary", fake_offline_summary)

    content = daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert content == "offline content"
    assert calls == ["offline_summary"]


def test_source_attribution_lists_only_selected_sources() -> None:
    articles = [
        {
            "title": "Trending candidate",
            "link": "https://agihunt.info/story",
            "source": "agihunt_trending",
        },
        {
            "title": "Selected TechCrunch candidate",
            "link": "https://techcrunch.com/story",
            "source": "techcrunch",
        },
        {
            "title": "Unselected Verge candidate",
            "link": "https://theverge.com/story",
            "source": "theverge",
        },
    ]
    result = _valid_summary_result().model_copy(
        update={
            "items": (
                SummaryItem(
                    article_id="a2",
                    title="Selected TechCrunch candidate",
                    summary="TechCrunch 的候选新闻已被本地短名单选中并进入最终日报正文。",
                    url="https://techcrunch.com/story",
                ),
            )
        }
    )

    attribution = daily_main.selected_source_attribution_line(result, articles)

    assert attribution == "> 入选来源：TechCrunch。"
    assert "AGI HUNT" not in attribution
    assert "The Verge" not in attribution


def test_public_report_omits_private_titles_sources_signals_and_diagnostics() -> None:
    result = _valid_summary_result()
    content = daily_main.compose_report_content(
        "日报标题",
        "1. 中文事实句。中文意义句。",
        [{"title": "English original headline", "source": "example"}],
        result,
        observation_signals=[{"title": "Private signal"}],
        pipeline_diagnostics={"status": "degraded"},
    )

    assert content == "日报标题\n\n1. 中文事实句。中文意义句。"
    assert "English original headline" not in content
    assert "Private signal" not in content
    assert "degraded" not in content
