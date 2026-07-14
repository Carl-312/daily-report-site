from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import summarizer


def _llm_config(**overrides):
    cfg = {
        "api_key": "modelscope-key",
        "api_base_url": "https://modelscope.test/v1",
        "model": "ZhipuAI/GLM-5.2",
        "modelscope_secondary_model": "Tencent-Hunyuan/Hy3",
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
    return json.dumps(
        {
            "items": [
                {
                    "article_id": f"a{index}",
                    "title": f"第{index}条人工智能产品更新",
                    "summary": "推动行业应用场景继续扩展，并带来新的实际价值。",
                }
                for index in range(1, item_count + 1)
            ],
            "discussion_topic": "你最关注哪条AI新闻？欢迎留言分享你的看法！",
        },
        ensure_ascii=False,
    )


def _summary_with_sources(source_ids: list[str]) -> str:
    return json.dumps(
        {
            "items": [
                {
                    "article_id": source_id,
                    "title": f"第{index}条独立AI新闻",
                    "summary": "发布重要产品更新，推动行业应用场景继续扩展。",
                }
                for index, source_id in enumerate(source_ids, 1)
            ],
            "discussion_topic": "你最关注哪条AI新闻？欢迎留言分享你的看法！",
        },
        ensure_ascii=False,
    )


def _rendered_summary(item_count: int = 1) -> str:
    lines = []
    for index in range(1, item_count + 1):
        lines.append(
            f"{index}. 第{index}条人工智能产品更新："
            "推动行业应用场景继续扩展，并带来新的实际价值。"
        )
    lines.extend(["", "💬 互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！"])
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
            "Tencent-Hunyuan/Hy3",
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
        if params["model"] == "Tencent-Hunyuan/Hy3":
            return _valid_summary()
        raise RuntimeError("provider failed")

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    content = summarizer.summarize([{"title": "Story"}], stream=False)

    assert content == _rendered_summary()
    assert "a1" not in content
    assert "http" not in content
    assert calls == [
        ("https://modelscope.test/v1|modelscope-key", "ZhipuAI/GLM-5.2"),
        (
            "https://modelscope.test/v1|modelscope-key",
            "Tencent-Hunyuan/Hy3",
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

    assert content == _rendered_summary()
    assert calls == ["ZhipuAI/GLM-5.2", "Tencent-Hunyuan/Hy3"]


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
    assert result.model == "Tencent-Hunyuan/Hy3"
    assert [attempt.status for attempt in result.attempts] == ["failed", "ok"]
    assert result.items[0].article_id == "a1"
    assert result.items[0].url == "https://example.test/story"
    assert result.validation_passed is True


def test_validate_summary_quality_accepts_complete_chinese_digest() -> None:
    summarizer.validate_summary_quality(
        _valid_summary(item_count=10), expected_items=10
    )


def test_validate_summary_quality_uses_independent_daily_limit() -> None:
    summarizer.validate_summary_quality(
        _valid_summary(item_count=10), expected_items=10
    )
    with pytest.raises(summarizer.SummaryQualityError, match="maximum allowed is 4"):
        summarizer.validate_summary_quality(
            _valid_summary(item_count=10), expected_items=4
        )


def test_summarize_result_allows_multiple_news_from_source_candidates(
    monkeypatch,
) -> None:
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
        lambda client, params: _summary_with_sources(
            ["a1", "a1", "a1", "a2", "a2", "a3", "a3", "a4", "a4", "a1"]
        ),
    )

    articles = [
        {"title": f"Story {index}", "link": f"https://example.test/{index}"}
        for index in range(4)
    ]

    result = summarizer.summarize_result(articles, stream=False)

    assert len(result.items) == 10
    assert [item.article_id for item in result.items].count("a1") == 4


def test_offline_summary_does_not_expand_candidate_count() -> None:
    articles = [
        {"title": f"Story {index}", "link": f"https://example.test/{index}"}
        for index in range(4)
    ]

    summary = summarizer.offline_summary(articles)

    assert len(summarizer._numbered_items(summary)) == 4
    assert "https://" not in summary


def test_compress_articles_omits_links_from_the_model_input(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)

    compressed = summarizer.compress_articles(
        [
            {
                "title": "AI launch",
                "description": "new capability",
                "link": "https://example.test/private-source",
            }
        ]
    )

    assert compressed == [
        {
            "article_id": "a1",
            "title": "AI launch",
            "publish_time": "",
            "description": "new capability",
            "priority": 0,
        }
    ]


def test_validate_summary_quality_rejects_unknown_article_id() -> None:
    with pytest.raises(summarizer.SummaryQualityError, match="unknown article_id"):
        summarizer.validate_summary_quality(
            json.dumps(
                {
                    "items": [
                        {
                            "article_id": "a9",
                            "title": "人工智能产品更新",
                            "summary": "推动行业应用场景继续扩展。",
                        }
                    ],
                    "discussion_topic": "你最关注哪条AI新闻？",
                },
                ensure_ascii=False,
            ),
            expected_items=1,
            expected_article_ids={"a1"},
        )


def test_validate_summary_quality_allows_duplicate_article_id() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "人工智能产品更新",
                    "summary": "推动行业应用场景继续扩展。",
                },
                {
                    "article_id": "a1",
                    "title": "人工智能商业进展",
                    "summary": "带来新的行业应用和市场机会。",
                },
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )
    summarizer.validate_summary_quality(
        content,
        expected_items=2,
        expected_article_ids={"a1", "a2"},
    )


def test_validate_summary_quality_rejects_schema_drift() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "人工智能产品更新",
                    "summary": "推动行业应用场景继续扩展。",
                    "url": "https://example.test/should-not-be-returned",
                }
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="JSON matching"):
        summarizer.validate_summary_quality(content, expected_items=1)


def test_validate_summary_quality_rejects_links_in_reader_facing_fields() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "[人工智能产品](https://example.com/story)",
                    "summary": "发布重要能力并推动行业应用场景继续扩展。",
                }
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="contains a link"):
        summarizer.validate_summary_quality(content, expected_items=2)


def test_validate_summary_quality_rejects_article_ids_in_reader_facing_fields() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "[a1] 人工智能产品更新",
                    "summary": "推动行业应用场景继续扩展。",
                }
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="exposes an article_id"):
        summarizer.validate_summary_quality(content, expected_items=1)


def test_validate_summary_quality_rejects_digest_without_interaction_topic() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "人工智能产品更新",
                    "summary": "推动行业应用场景继续扩展。",
                }
            ],
            "discussion_topic": "",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="interaction topic"):
        summarizer.validate_summary_quality(content, expected_items=10)
