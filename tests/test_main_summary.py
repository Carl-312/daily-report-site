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
