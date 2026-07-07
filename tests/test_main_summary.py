from __future__ import annotations

from types import SimpleNamespace

import pytest

import main as daily_main


def test_summarize_or_offline_raises_when_llm_fails_with_provider_key(
    monkeypatch, capsys
) -> None:
    articles = [{"title": "Fallback story", "priority": 0}]
    cfg = SimpleNamespace(api_key="modelscope-key", fallback_api_key="siliconflow-key")
    calls: list[str] = []

    def fake_summarize(article_payload, *, stream):
        calls.append("summarize")
        assert article_payload == articles
        assert stream is True
        raise RuntimeError("provider outage")

    monkeypatch.setattr(daily_main, "summarize", fake_summarize)

    with pytest.raises(RuntimeError, match="failed quality checks"):
        daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert calls == ["summarize"]
    assert "refusing to publish an offline fallback" in capsys.readouterr().out


def test_summarize_or_offline_raises_when_llm_returns_invalid_content(
    monkeypatch, capsys
) -> None:
    articles = [{"title": "Empty response story", "priority": 0}]
    cfg = SimpleNamespace(api_key="modelscope-key", fallback_api_key="")
    calls: list[str] = []

    def fake_summarize(article_payload, *, stream):
        calls.append("summarize")
        assert article_payload == articles
        assert stream is True
        return " \n"

    monkeypatch.setattr(daily_main, "summarize", fake_summarize)

    with pytest.raises(RuntimeError, match="failed quality checks"):
        daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert calls == ["summarize"]
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
