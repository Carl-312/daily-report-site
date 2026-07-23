from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import summarizer
from utils.summary_contracts import (
    SUMMARY_MAX_VISIBLE_CHARS,
    SUMMARY_MIN_VISIBLE_CHARS,
    reader_summary_issues,
    summary_visible_character_count,
)


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
                    "summary": (
                        "发布重要产品更新，新增多项面向开发者的核心能力，"
                        "推动行业应用持续扩展并进一步提升团队的实际工作效率。"
                    ),
                    "why_it_matters": (
                        "这会降低开发团队采用相关能力的门槛，并改变产品迭代效率。"
                    ),
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
                    "summary": (
                        "发布重要产品更新，新增多项面向开发者的核心能力，"
                        "推动行业应用持续扩展并进一步提升团队的实际工作效率。"
                    ),
                    "why_it_matters": (
                        "这会降低开发团队采用相关能力的门槛，并改变产品迭代效率。"
                    ),
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
            f"{index}. 发布重要产品更新，新增多项面向开发者的核心能力，"
            "推动行业应用持续扩展并进一步提升团队的实际工作效率。"
            "这会降低开发团队采用相关能力的门槛，并改变产品迭代效率。"
        )
    lines.extend(["", "💬 互动话题：你最关注哪条AI新闻？欢迎留言分享你的看法！"])
    return "\n".join(lines)


def test_source_grounding_rejects_an_invented_legal_claim() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "summary": (
                        "苹果公司正式起诉OpenAI，并指控其侵犯知识产权，双方进入公开法律对抗。"
                    ),
                    "why_it_matters": "这场诉讼可能改变两家公司未来的产品竞争关系。",
                }
            ],
            "discussion_topic": "你如何看待这场诉讼？",
        },
        ensure_ascii=False,
    )
    draft = summarizer.validate_summary_quality(
        content,
        expected_items=1,
        expected_article_ids=("a1",),
        require_impact=True,
    )

    with pytest.raises(
        summarizer.SummaryQualityError,
        match="unsupported source claim intellectual_property",
    ):
        summarizer.validate_summary_source_grounding(
            draft,
            {
                "a1": {
                    "title": "Apple sues OpenAI",
                    "description": "Apple is suing OpenAI in a public legal fight.",
                }
            },
        )


def test_source_grounding_accepts_a_claim_present_in_the_article() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "summary": (
                        "苹果公司正式起诉OpenAI，并指控其侵犯知识产权，双方进入公开法律对抗。"
                    ),
                    "why_it_matters": "这场诉讼可能改变两家公司未来的产品竞争关系。",
                }
            ],
            "discussion_topic": "你如何看待这场诉讼？",
        },
        ensure_ascii=False,
    )
    draft = summarizer.validate_summary_quality(
        content,
        expected_items=1,
        expected_article_ids=("a1",),
        require_impact=True,
    )

    summarizer.validate_summary_source_grounding(
        draft,
        {
            "a1": {
                "title": "Apple sues OpenAI over intellectual property",
                "description": "The complaint alleges an intellectual property violation.",
            }
        },
    )


def test_source_grounding_rejects_a_number_missing_from_evidence() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "summary": (
                        "该公司发布开发者工具，并宣布投入500亿美元扩大产品覆盖范围。"
                    ),
                    "why_it_matters": "这会提高企业采用相关开发能力的成本门槛。",
                }
            ]
        },
        ensure_ascii=False,
    )
    draft = summarizer.validate_summary_quality(
        content,
        expected_items=1,
        expected_article_ids=("a1",),
        require_impact=True,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="unsupported numeric"):
        summarizer.validate_summary_source_grounding(
            draft,
            {
                "a1": {
                    "title": "Company releases developer tools",
                    "description": "The company released tools for teams.",
                }
            },
        )


def test_number_grounding_normalizes_abbreviations_units_and_english_words() -> None:
    supported = summarizer._normalized_number_claims(
        "The company raised $15M after six months; another deal was $1.5 billion."
    )

    assert {"15000000", "6", "1500000000"} <= supported
    assert summarizer._normalized_number_claims("1500万、6个月、15亿元") <= supported


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


def test_glm52_modelscope_request_disables_thinking() -> None:
    assert summarizer.modelscope_request_options("ZhipuAI/GLM-5.2") == {
        "extra_body": {"enable_thinking": False}
    }
    assert summarizer.modelscope_request_options("custom/model") == {}


def test_qwen35_modelscope_request_disables_thinking() -> None:
    assert summarizer.modelscope_request_options("Qwen/Qwen3.5-35B-A3B") == {
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": False},
        }
    }


def test_summarize_applies_verified_glm52_request_controls(monkeypatch) -> None:
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: _llm_config(
            modelscope_secondary_model="ZhipuAI/GLM-5.2",
            fallback_api_key="",
        ),
    )
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    captured: dict = {}

    def fake_summarize_sync(_client, params):
        captured.update(params)
        return _valid_summary()

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    summarizer.summarize_result([{"title": "Story"}], stream=False)

    assert captured["model"] == "ZhipuAI/GLM-5.2"
    assert captured["temperature"] == 0.2
    assert captured["stream"] is False
    assert captured["extra_body"] == {"enable_thinking": False}


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


def test_summarize_sync_rejects_an_empty_choices_list() -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(choices=[])
            )
        )
    )

    with pytest.raises(summarizer.SummaryQualityError, match="empty choices"):
        summarizer._summarize_sync(client, {})


def test_summarize_sync_rejects_empty_message_content() -> None:
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="  \n"))]
                )
            )
        )
    )

    with pytest.raises(summarizer.SummaryQualityError, match="empty message content"):
        summarizer._summarize_sync(client, {})


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
    assert result.items[0].title == "Story"
    assert result.items[0].url == "https://example.test/story"
    assert result.validation_passed is True


def test_validate_summary_quality_accepts_complete_chinese_digest() -> None:
    summarizer.validate_summary_quality(
        _valid_summary(item_count=10), expected_items=10
    )


def test_validate_summary_quality_accepts_the_minimal_small_model_shape() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "summary": (
                        "人工智能公司发布面向开发者的新模型能力，"
                        "并在本周开始逐步开放相关工具和测试资格。"
                    ),
                }
            ]
        },
        ensure_ascii=False,
    )

    draft = summarizer.validate_summary_quality(
        content, expected_items=1, expected_article_ids=("a1",)
    )

    assert draft.items[0].title == ""
    assert draft.discussion_topic == "你最关注哪条AI新闻？"


def test_daily_prompt_declares_complete_sentence_and_length_contract() -> None:
    prompt = (Path(__file__).resolve().parents[1] / "prompts" / "daily.md").read_text(
        encoding="utf-8"
    )

    assert (
        f"{SUMMARY_MIN_VISIBLE_CHARS}–{SUMMARY_MAX_VISIBLE_CHARS} 个可见字符" in prompt
    )
    assert "每条输入必须输出一次" in prompt
    assert "保持 `article_id` 和顺序" in prompt
    assert "输入已经由程序完成选题、去重、排序和来源配额" in prompt
    assert "不输出标题" in prompt
    assert "不要复述 `trend_signal`" in prompt
    assert "`evidence_status`、`confidence`、`publish_time`" in prompt
    assert "不得把证据域数量写成新闻事实" in prompt
    assert "把它作为主要选题信号" not in prompt
    assert len(prompt.splitlines()) <= 12


def test_validate_summary_quality_uses_independent_daily_limit() -> None:
    summarizer.validate_summary_quality(
        _valid_summary(item_count=10), expected_items=10
    )
    with pytest.raises(summarizer.SummaryQualityError, match="maximum allowed is 4"):
        summarizer.validate_summary_quality(
            _valid_summary(item_count=10), expected_items=4
        )


def test_summarize_result_rejects_missing_or_duplicate_selected_candidates(
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

    with pytest.raises(RuntimeError, match="cover every selected candidate"):
        summarizer.summarize_result(articles, stream=False)


def test_offline_summary_does_not_expand_candidate_count() -> None:
    articles = [
        {
            "title": f"Story {index}",
            "description": (
                f"第{index}条测试新闻发布多项新功能，面向开发者开放核心能力，"
                "并通过更稳定的执行效果提升团队工作效率和复杂任务交付质量。"
            ),
            "link": f"https://example.test/{index}",
        }
        for index in range(4)
    ]

    summary = summarizer.offline_summary(articles)

    assert len(summarizer._numbered_items(summary)) == 4
    assert "https://example.test/" not in summary


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
            "description": "new capability",
            "evidence_status": "direct",
            "confidence": "reported",
            "publish_time": "",
            "evidence_domain_count": 1,
        }
    ]


def test_compress_articles_exposes_private_editorial_metadata(monkeypatch) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)

    compressed = summarizer.compress_articles(
        [
            {
                "title": "AI launch",
                "description": "new capability",
                "link": "https://www.example.test/private-source",
                "publish_time": "Tue, 21 Jul 2026 16:58:25 GMT",
                "evidence_status": "corroborated",
                "confidence": "corroborated",
                "evidence": [
                    {
                        "title": "Corroboration",
                        "url": "https://reuters.com/technology/corroboration",
                        "published_date": "2026-07-21",
                        "snippet": "A second direct report.",
                    },
                    {
                        "title": "Same domain",
                        "url": "https://example.test/duplicate-domain",
                        "published_date": "2026-07-21",
                        "snippet": "The original domain again.",
                    },
                ],
            }
        ]
    )

    assert compressed[0]["evidence_status"] == "corroborated"
    assert compressed[0]["confidence"] == "corroborated"
    assert compressed[0]["publish_time"] == "2026-07-21T16:58:25Z"
    assert compressed[0]["evidence_domain_count"] == 2
    assert "link" not in compressed[0]


def test_live_offline_and_publication_validation_share_the_p1_shortlist(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        summarizer, "get_config", lambda: _llm_config(max_summary_items=1)
    )
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(
        summarizer,
        "create_client",
        lambda base_url, api_key: f"{base_url}|{api_key}",
    )
    captured_input: dict = {}

    def fake_summarize_sync(_client, params):
        captured_input.update(json.loads(params["messages"][-1]["content"]))
        return _summary_with_sources(["a2"])

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)
    articles = [
        {
            "title": "AI assistant Alpha launches a workflow update",
            "description": (
                "The AI report documents a concrete product change and its result."
            ),
            "link": "https://news.example/alpha",
            "publish_time": "2026-07-22T10:00:00Z",
            "priority": 1,
            "source": "same-source",
        },
        {
            "title": "AI assistant Beta launches a workflow update",
            "description": (
                "The AI report documents a concrete product change and its result."
            ),
            "link": "https://news.example/beta",
            "publish_time": "2026-07-21T10:00:00Z",
            "priority": 1,
            "source": "same-source",
            "evidence_status": "corroborated",
            "confidence": "corroborated",
            "evidence": [
                {"url": "https://reuters.com/technology/beta", "snippet": "Report"}
            ],
        },
    ]

    live = summarizer.summarize_result(articles, stream=False)
    offline = summarizer.offline_summary_result(articles, limit=1)

    assert live.candidate_article_ids == offline.candidate_article_ids == ("a2",)
    assert [item["article_id"] for item in captured_input["articles"]] == ["a2"]
    assert captured_input["articles"][0]["evidence_domain_count"] == 2
    assert live.selection_diagnostics == offline.selection_diagnostics


def test_compress_articles_exposes_trending_rank_and_heat_to_the_editor(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summarizer, "get_config", _llm_config)

    compressed = summarizer.compress_articles(
        [
            {
                "title": "Kimi K3 enters AGI Hunt Trending",
                "description": "A ranked trend candidate",
                "link": "https://agihunt.info/private-source",
                "source": "agihunt_trending",
                "provenance": {
                    "trend_rank": "2",
                    "trend_heat": "14.9",
                    "trend_state": "up",
                    "trend_delta": "7",
                },
            }
        ]
    )

    assert compressed[0]["trend_signal"] == {
        "rank": 2,
        "heat": 14.9,
        "state": "up",
        "delta": 7,
    }
    assert "link" not in compressed[0]


def test_validate_summary_quality_rejects_unknown_article_id() -> None:
    with pytest.raises(summarizer.SummaryQualityError, match="unknown article_id"):
        summarizer.validate_summary_quality(
            json.dumps(
                {
                    "items": [
                        {
                            "article_id": "a9",
                            "title": "人工智能产品更新",
                            "summary": (
                                "发布重要产品更新，新增多项面向开发者的核心能力，"
                                "推动行业应用持续扩展并进一步提升团队的实际工作效率。"
                            ),
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
                    "summary": (
                        "发布重要产品更新，新增多项面向开发者的核心能力，"
                        "推动行业应用持续扩展并进一步提升团队的实际工作效率。"
                    ),
                },
                {
                    "article_id": "a1",
                    "title": "人工智能商业进展",
                    "summary": (
                        "带来新的行业应用机会，推动市场持续发展并完善关键产品能力，"
                        "进一步提升企业用户的实际部署与应用价值。"
                    ),
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


@pytest.mark.parametrize(
    "summary_length", [SUMMARY_MIN_VISIBLE_CHARS - 1, SUMMARY_MAX_VISIBLE_CHARS + 1]
)
def test_validate_summary_quality_rejects_summary_outside_complete_sentence_range(
    summary_length: int,
) -> None:
    summary = "中" * (summary_length - 1) + "。"
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "人工智能产品更新",
                    "summary": summary,
                }
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="visible characters"):
        summarizer.validate_summary_quality(content, expected_items=1)


def test_validate_summary_quality_rejects_vague_reporting_attribution() -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "人工智能产品更新",
                    "summary": (
                        "据报道，某人工智能公司发布面向开发者的新模型，"
                        "并计划在未来数周逐步开放更多核心能力和配套工具。"
                    ),
                }
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match="vague reporting"):
        summarizer.validate_summary_quality(content, expected_items=1)


def test_summary_provider_repairs_one_reader_contract_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: _llm_config(modelscope_secondary_model="", fallback_api_key=""),
    )
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args: "client")
    responses = [
        json.dumps(
            {
                "items": [
                    {
                        "article_id": "a1",
                        "title": "人工智能产品更新",
                        "summary": "人工智能公司发布新模型，并逐步开放更多核心能力。",
                    }
                ],
                "discussion_topic": "你最关注哪条AI新闻？",
            },
            ensure_ascii=False,
        ),
        _valid_summary(),
    ]
    calls: list[dict] = []

    def fake_summarize_sync(_client, params):
        calls.append(params)
        return responses.pop(0)

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    result = summarizer.summarize_result([{"title": "Story"}], stream=False)

    assert result.provider == "ModelScope"
    assert len(calls) == 2
    repair_message = calls[1]["messages"][-1]["content"]
    assert "30–80 个可见字符" in repair_message
    assert "逐条保留输入 article_id 和顺序" in repair_message


def test_summary_provider_repairs_grounding_failure_after_shape_repair(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        summarizer,
        "get_config",
        lambda: _llm_config(modelscope_secondary_model="", fallback_api_key=""),
    )
    monkeypatch.setattr(summarizer, "load_prompt", lambda: "prompt")
    monkeypatch.setattr(summarizer, "create_client", lambda *_args: "client")
    responses = [
        json.dumps(
            {
                "items": [
                    {
                        "article_id": "a1",
                        "summary": "人工智能公司发布新工具，并扩大产品能力。",
                    }
                ],
                "discussion_topic": "你最关注哪条AI新闻？",
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "items": [
                    {
                        "article_id": "a1",
                        "summary": (
                            "人工智能公司发布开发者工具，并计划在未来5年扩大产品覆盖范围。"
                        ),
                        "why_it_matters": "这会改变开发团队采用相关能力的成本与效率。",
                    }
                ],
                "discussion_topic": "你最关注哪条AI新闻？",
            },
            ensure_ascii=False,
        ),
        _valid_summary(),
    ]
    calls: list[dict] = []

    def fake_summarize_sync(_client, params):
        calls.append(params)
        return responses.pop(0)

    monkeypatch.setattr(summarizer, "_summarize_sync", fake_summarize_sync)

    result = summarizer.summarize_result([{"title": "Story"}], stream=False)

    assert result.provider == "ModelScope"
    assert len(calls) == 3
    grounding_repair = calls[2]["messages"][-1]["content"]
    assert "unsupported numeric claims: 5" in grounding_repair
    assert "不要换成另一个数字" in grounding_repair


def test_offline_summary_preserves_a_complete_source_sentence_without_truncation() -> (
    None
):
    result = summarizer.offline_summary_result(
        [
            {
                "title": "AI 产品发布",
                "description": (
                    "该产品发布了多项新能力，并通过更快的推理速度和更低成本，"
                    "帮助开发团队提升日常工作效率并优化复杂任务的交付质量。"
                ),
                "link": "https://example.test/story",
            }
        ]
    )

    summary = result.items[0].summary

    assert summary == (
        "该产品发布了多项新能力，并通过更快的推理速度和更低成本，"
        "帮助开发团队提升日常工作效率并优化复杂任务的交付质量。"
    )
    assert (
        SUMMARY_MIN_VISIBLE_CHARS
        <= summary_visible_character_count(summary)
        <= SUMMARY_MAX_VISIBLE_CHARS
    )
    assert summary.endswith("。")
    assert "…" not in summary
    assert ":" not in summary
    assert "：" not in summary
    assert "https://" not in summary


def test_offline_summary_turns_a_colon_headline_into_a_complete_sentence() -> None:
    result = summarizer.offline_summary_result(
        [
            {
                "title": "Sam Altman：模型终于会做设计了",
                "description": (
                    "Sam Altman表示，模型在复杂设计任务上的表现已明显改善，"
                    "目前的完成质量和执行稳定性都令他感到惊讶。"
                ),
                "link": "https://example.test/story",
            }
        ]
    )

    summary = result.items[0].summary

    assert summary == (
        "Sam Altman表示，模型在复杂设计任务上的表现已明显改善，"
        "目前的完成质量和执行稳定性都令他感到惊讶。"
    )
    assert "：" not in summary
    assert "…" not in summary
    assert reader_summary_issues(summary) == ()


def test_offline_summary_expands_a_compressed_headline_without_clipping() -> None:
    result = summarizer.offline_summary_result(
        [
            {
                "title": "LLM电脑操控能力飞跃引争议",
                "description": (
                    "近期LLM在电脑操控能力上出现显著跃迁，但不同场景下的实际体验、"
                    "执行稳定性与能力宣传仍存在明显分歧。"
                ),
                "link": "https://example.test/story",
            }
        ]
    )

    summary = result.items[0].summary

    assert (
        summary
        == "近期LLM在电脑操控能力上出现显著跃迁，但不同场景下的实际体验、执行稳定性与能力宣传仍存在明显分歧。"
    )
    assert reader_summary_issues(summary) == ()


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("某公司：发布面向开发者的新模型能力。", "must not contain a colon"),
        ("某公司发布面向开发者的新模型能力…", "must not contain a truncation marker"),
        ("某公司发布新模型能力。开发者已可使用。", "must contain exactly one"),
    ],
)
def test_validate_summary_quality_rejects_non_reader_sentence_format(
    summary: str, expected: str
) -> None:
    content = json.dumps(
        {
            "items": [
                {
                    "article_id": "a1",
                    "title": "人工智能产品更新",
                    "summary": summary,
                }
            ],
            "discussion_topic": "你最关注哪条AI新闻？",
        },
        ensure_ascii=False,
    )

    with pytest.raises(summarizer.SummaryQualityError, match=expected):
        summarizer.validate_summary_quality(content, expected_items=1)


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
