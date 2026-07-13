from __future__ import annotations

from types import SimpleNamespace

import pytest

import summarizer


def _llm_config(**overrides):
    cfg = {
        "api_key": "modelscope-key",
        "api_base_url": "https://modelscope.test/v1",
        "model": "ZhipuAI/GLM-5.2",
        "modelscope_secondary_model": "moonshotai/Kimi-K2.7-Code",
        "fallback_api_key": "siliconflow-key",
        "fallback_api_base_url": "https://siliconflow.test/v1",
        "fallback_model": "Pro/moonshotai/Kimi-K2.6",
        "max_output": 2000,
        "title_max": 150,
        "desc_max": 300,
        "prompt_path": "missing-prompt.md",
    }
    cfg.update(overrides)
    return SimpleNamespace(**cfg)


def _valid_summary(item_count: int = 1) -> str:
    lines = []
    for index in range(1, item_count + 1):
        lines.append(
            f"{index}. [a{index}] 人工智能公司发布重要产品更新，推动行业应用场景继续扩展"
        )
        lines.append("")
    lines.append("互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！🤔💬")
    return "\n".join(lines)


def test_provider_candidates_use_modelscope_secondary_before_siliconflow(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)

    providers = summarizer._provider_candidates()

    assert [
        (provider["name"], provider["base_url"], provider["model"])
        for provider in providers
    ] == [
        ("ModelScope", "https://modelscope.test/v1", "ZhipuAI/GLM-5.2"),
        (
            "ModelScope secondary",
            "https://modelscope.test/v1",
            "moonshotai/Kimi-K2.7-Code",
        ),
        ("SiliconFlow", "https://siliconflow.test/v1", "Pro/moonshotai/Kimi-K2.6"),
    ]


def test_provider_candidates_skip_duplicate_modelscope_model(monkeypatch) -> None:
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: _llm_config(
            modelscope_secondary_model="ZhipuAI/GLM-5.2",
            fallback_api_key="",
        ),
    )

    providers = summarizer._provider_candidates()

    assert [(provider["name"], provider["model"]) for provider in providers] == [
        ("ModelScope", "ZhipuAI/GLM-5.2")
    ]


def test_summarize_tries_modelscope_secondary_before_siliconflow(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    calls: list[tuple[str, str]] = []

    def fake_summarize_sync(client, params):
        calls.append((client, params["model"]))
        if params["model"] == "moonshotai/Kimi-K2.7-Code":
            return _valid_summary()
        raise RuntimeError("provider failed")

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    content = summarizer.summarize([{"title": "Story"}], stream=False)

    assert content == _valid_summary()
    assert calls == [
        ("https://modelscope.test/v1|modelscope-key", "ZhipuAI/GLM-5.2"),
        (
            "https://modelscope.test/v1|modelscope-key",
            "moonshotai/Kimi-K2.7-Code",
        ),
    ]


def test_summarize_treats_empty_provider_response_as_failure(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    calls: list[str] = []

    def fake_summarize_sync(client, params):
        calls.append(params["model"])
        if params["model"] == "ZhipuAI/GLM-5.2":
            return "  \n"
        return _valid_summary()

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    content = summarizer.summarize([{"title": "Story"}], stream=False)

    assert content == _valid_summary()
    assert calls == ["ZhipuAI/GLM-5.2", "moonshotai/Kimi-K2.7-Code"]


def test_summarize_result_records_provider_attempts_and_article_provenance(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )

    def fake_summarize_sync(client, params):
        if params["model"] == "ZhipuAI/GLM-5.2":
            raise RuntimeError("primary unavailable")
        return _valid_summary()

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)
    result = summarizer.summarize_result(
        [{"title": "Story", "link": "https://example.test/story"}],
        stream=False,
    )

    assert result.provider == "ModelScope secondary"
    assert result.model == "moonshotai/Kimi-K2.7-Code"
    assert [attempt.status for attempt in result.attempts] == ["failed", "ok"]
    assert result.items[0].article_id == "a1"
    assert result.items[0].url == "https://example.test/story"
    assert result.validation_passed is True


def test_validate_summary_quality_accepts_complete_chinese_digest() -> None:
    summarizer.validate_summary_quality(
        _valid_summary(item_count=10), expected_items=10
    )


def test_validate_summary_quality_rejects_more_items_than_candidates() -> None:
    with pytest.raises(summarizer.SummaryQualityError, match="maximum allowed is 4"):
        summarizer.validate_summary_quality(
            _valid_summary(item_count=10), expected_items=4
        )


def test_summarize_result_rejects_model_expansion(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    monkeypatch.setattr(
        summarizer,
        "_summarize_sync",
        lambda client, params: _valid_summary(item_count=10),
    )

    articles = [
        {"title": f"Story {index}", "link": f"https://example.test/{index}"}
        for index in range(4)
    ]

    with pytest.raises(RuntimeError, match="All LLM providers failed"):
        summarizer.summarize_result(articles, stream=False)


def test_offline_summary_does_not_expand_candidate_count() -> None:
    articles = [
        {"title": f"Story {index}", "link": f"https://example.test/{index}"}
        for index in range(4)
    ]

    summary = summarizer.offline_summary(articles)

    assert len(summarizer._numbered_items(summary)) == 4


def test_validate_summary_quality_rejects_unknown_article_id() -> None:
    with pytest.raises(summarizer.SummaryQualityError, match="unknown article_id"):
        summarizer.validate_summary_quality(
            "1. [a9] 人工智能公司发布重要产品更新，推动行业应用场景继续扩展\n\n"
            "互动话题：你最关注哪条AI新闻？",
            expected_items=1,
            expected_article_ids={"a1"},
        )


def test_validate_summary_quality_rejects_duplicate_article_id() -> None:
    content = (
        "1. [a1] 人工智能公司发布重要产品更新，推动行业应用场景继续扩展\n\n"
        "2. [a1] 人工智能公司发布重要产品更新，推动行业应用场景继续扩展\n\n"
        "互动话题：你最关注哪条AI新闻？"
    )
    with pytest.raises(summarizer.SummaryQualityError, match="repeats article_id"):
        summarizer.validate_summary_quality(
            content,
            expected_items=2,
            expected_article_ids={"a1", "a2"},
        )


def test_validate_summary_quality_rejects_english_link_list() -> None:
    content = "\n\n".join(
        [
            "1. [🔥Netflix invented binge-watching. Now it may have outgrown it.]"
            "(https://example.com/story)",
            "2. [🔥The first AI-run ransomware attack still needed a human]"
            "(https://example.com/story-2)",
            "互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！🤔💬",
        ]
    )

    with pytest.raises(summarizer.SummaryQualityError):
        summarizer.validate_summary_quality(content, expected_items=2)


def test_validate_summary_quality_rejects_incomplete_digest() -> None:
    content = "\n\n".join(
        [
            "1. 人工智能公司发布重要产品更新，推动行业应用场景继续扩展",
            "互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！🤔💬",
        ]
    )

    with pytest.raises(summarizer.SummaryQualityError):
        summarizer.validate_summary_quality(content, expected_items=10)
