from __future__ import annotations

from types import SimpleNamespace

import main as daily_main


def test_summarize_or_offline_falls_back_when_llm_fails(monkeypatch, capsys) -> None:
    articles = [{"title": "Fallback story", "priority": 0}]
    cfg = SimpleNamespace(api_key="modelscope-key", fallback_api_key="siliconflow-key")
    calls: list[str] = []

    def fake_summarize(article_payload, *, stream):
        calls.append("summarize")
        assert article_payload == articles
        assert stream is True
        raise RuntimeError("provider outage")

    def fake_offline_summary(article_payload):
        calls.append("offline_summary")
        assert article_payload == articles
        return "offline content"

    monkeypatch.setattr(daily_main, "summarize", fake_summarize)
    monkeypatch.setattr(daily_main, "offline_summary", fake_offline_summary)

    content = daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert content == "offline content"
    assert calls == ["summarize", "offline_summary"]
    assert "AI summarization failed, using offline mode" in capsys.readouterr().out


def test_summarize_or_offline_falls_back_when_llm_returns_empty(
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

    def fake_offline_summary(article_payload):
        calls.append("offline_summary")
        assert article_payload == articles
        return "offline content"

    monkeypatch.setattr(daily_main, "summarize", fake_summarize)
    monkeypatch.setattr(daily_main, "offline_summary", fake_offline_summary)

    content = daily_main.summarize_or_offline(articles, offline=False, cfg=cfg)

    assert content == "offline content"
    assert calls == ["summarize", "offline_summary"]
    assert (
        "AI summarization returned empty content, using offline mode"
        in capsys.readouterr().out
    )
