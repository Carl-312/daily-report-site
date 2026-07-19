from __future__ import annotations

from utils.summary_contracts import (
    SUMMARY_MAX_VISIBLE_CHARS,
    SUMMARY_MIN_VISIBLE_CHARS,
    SummaryItem,
    SummaryResult,
    fingerprint_summary_input,
    render_summary_markdown,
    reader_summary_issues,
    summary_visible_character_count,
    validate_summary_result,
)
from summarizer import offline_summary_result


def test_structured_summary_renders_fact_and_direct_source_without_article_ids() -> (
    None
):
    input_hash, prompt_hash = fingerprint_summary_input(
        [{"title": "AI launch", "link": "https://example.test/a"}], "prompt"
    )
    result = SummaryResult(
        policy="offline",
        items=(
            SummaryItem(
                article_id="a1",
                title="AI launch",
                summary="人工智能产品发布新能力，帮助开发者提升工作效率。",
                url="https://example.test/a",
            ),
        ),
        discussion_topic="你会如何使用这项能力？",
        provider="local",
        model="deterministic",
        input_fingerprint=input_hash,
        prompt_fingerprint=prompt_hash,
    )

    assert render_summary_markdown(result) == (
        "### 1. AI launch\n\n"
        "发生了什么：人工智能产品发布新能力，帮助开发者提升工作效率。\n\n"
        "来源：[example.test](https://example.test/a)\n\n"
        "💬 互动话题：你会如何使用这项能力？"
    )


def test_renderer_removes_links_from_untrusted_offline_text() -> None:
    result = SummaryResult(
        policy="offline",
        items=(
            SummaryItem(
                article_id="a1",
                title="[a1] [AI launch](https://example.test/a)",
                summary="详情见 www.example.test/a ，发布了新能力。",
                url="https://example.test/a",
            ),
        ),
        discussion_topic="去 https://example.test/a 查看详情吗？",
        provider="local",
        model="deterministic",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    rendered = render_summary_markdown(result)

    assert rendered.count("https://") == 1
    assert "[example.test](https://example.test/a)" in rendered
    assert "www.example.test" not in rendered
    assert "[a1]" not in rendered
    assert "### 1. AI launch" in rendered
    assert "发生了什么：详情见，发布了新能力。" in rendered


def test_summary_fingerprints_are_stable_for_identical_input() -> None:
    first = fingerprint_summary_input([{"title": "A"}], "prompt")
    second = fingerprint_summary_input([{"title": "A"}], "prompt")
    changed = fingerprint_summary_input([{"title": "B"}], "prompt")

    assert first == second
    assert changed[0] != first[0]


def test_summary_visible_character_count_ignores_whitespace() -> None:
    assert summary_visible_character_count("人工 智能\n产品") == 6


def test_offline_summary_result_keeps_article_provenance() -> None:
    result = offline_summary_result(
        [
            {
                "title": "AI launch",
                "description": (
                    "该产品发布多项核心能力，帮助开发者提升日常工作效率，"
                    "并进一步拓展团队在复杂业务场景中的实际应用范围。"
                ),
                "link": "https://example.test/a",
                "priority": 1,
            }
        ]
    )

    assert result.policy == "offline"
    assert result.items[0].article_id == "a1"
    assert result.items[0].url == "https://example.test/a"


def test_trending_signal_stays_private_and_is_not_rendered() -> None:
    article = {
        "title": "月之暗面 Kimi K3 发布引关注",
        "description": (
            "月之暗面发布 Kimi K3，并在多项评测中获得关注，"
            "其定价、实际能力和后续开放计划也引发开发者持续讨论。"
        ),
        "link": "https://agihunt.info/?day=2026-07-18&t=Moonshot+Kimi+K3",
        "priority": 4,
        "source": "agihunt_trending",
        "provenance": {
            "trend_rank": "1",
            "trend_heat": "14.9",
            "trend_state": "up",
            "trend_delta": "10",
        },
    }

    result = offline_summary_result([article])

    assert "display_badge" not in result.items[0].model_dump()
    rendered = render_summary_markdown(result)
    assert rendered.startswith("### 1. 月之暗面 Kimi K3 发布引关注")
    assert "发生了什么：月之暗面发布 Kimi K3" in rendered
    assert "AGI趋势" not in rendered
    assert "热度" not in rendered
    assert "↑" not in rendered
    validate_summary_result(result, [article])

    legacy_item = result.items[0].model_copy(
        update={"summary": f"〔AGI趋势 #1｜热度14.9｜↑10〕{result.items[0].summary}"}
    )
    legacy_result = result.model_copy(update={"items": (legacy_item,)})
    assert "AGI趋势" not in render_summary_markdown(legacy_result)


def test_summary_contract_allows_multiple_items_from_one_source() -> None:
    result = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="AI launch",
                summary=(
                    "发布多项面向开发者的重要能力，推动行业实际应用持续扩展，"
                    "并进一步提升团队在复杂任务中的执行效率。"
                ),
                url="https://example.test/a",
            ),
            SummaryItem(
                article_id="a1",
                title="AI launch again",
                summary=(
                    "继续发布面向开发者的新能力，推动相关行业应用持续扩展，"
                    "并进一步提升企业团队的部署效率和实际工作质量。"
                ),
                url="https://example.test/a",
            ),
        ),
        discussion_topic="你会如何使用这项能力？",
        provider="local",
        model="test",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    validate_summary_result(
        result,
        [
            {"title": "AI launch", "link": "https://example.test/a"},
            {"title": "Second story", "link": "https://example.test/b"},
        ],
    )


def test_summary_contract_rejects_summary_above_complete_sentence_limit() -> None:
    result = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="人工智能产品更新",
                summary="中" * SUMMARY_MAX_VISIBLE_CHARS + "。",
                url="https://example.test/a",
            ),
        ),
        discussion_topic="你会如何使用这项能力？",
        provider="local",
        model="test",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    try:
        validate_summary_result(
            result, [{"title": "AI launch", "link": "https://example.test/a"}]
        )
    except ValueError as exc:
        assert f"maximum is {SUMMARY_MAX_VISIBLE_CHARS}" in str(exc)
    else:
        raise AssertionError("oversized summary was accepted")


def test_summary_contract_rejects_colon_and_truncated_reader_text() -> None:
    result = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="人工智能产品更新",
                summary="某公司：发布面向开发者的新模型能力…",
                url="https://example.test/a",
            ),
        ),
        discussion_topic="你会如何使用这项能力？",
        provider="local",
        model="test",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    try:
        validate_summary_result(
            result, [{"title": "AI launch", "link": "https://example.test/a"}]
        )
    except ValueError as exc:
        assert "must not contain a colon" in str(exc)
        assert "must not contain a truncation marker" in str(exc)
    else:
        raise AssertionError("invalid reader text was accepted")


def test_reader_summary_contract_accepts_complete_sentence_above_target_range() -> None:
    summary = (
        "近期LLM在电脑操控能力上出现显著跃迁，但不同场景下的实际体验、"
        "执行稳定性与能力宣传仍存在明显分歧。"
    )

    assert summary_visible_character_count(summary) >= SUMMARY_MIN_VISIBLE_CHARS
    assert reader_summary_issues(summary) == ()


def test_reader_summary_contract_rejects_vague_reporting_attribution() -> None:
    for attribution in ("据报道", "市场消息显示", "知情人士称"):
        summary = (
            f"{attribution}，某人工智能公司发布面向开发者的新模型，"
            "并计划在未来数周逐步开放更多核心能力和配套工具。"
        )

        assert "must not use a vague reporting attribution" in reader_summary_issues(
            summary
        )


def test_reader_summary_contract_rejects_internal_trend_signals() -> None:
    summary = (
        "某公司发布面向开发者的新模型能力，内部榜单显示热度14.9并标记为新上榜，"
        "相关能力现已开放测试。"
    )

    assert "must not expose internal trend signals" in reader_summary_issues(summary)


def test_summary_contract_still_rejects_source_url_mismatch() -> None:
    result = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="AI launch",
                summary="发布了新能力",
                url="https://example.test/other",
            ),
        ),
        discussion_topic="你会如何使用这项能力？",
        provider="local",
        model="test",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    try:
        validate_summary_result(
            result,
            [{"title": "AI launch", "link": "https://example.test/a"}],
        )
    except ValueError as exc:
        assert "mismatched source URL" in str(exc)
    else:
        raise AssertionError("invalid summary contract was accepted")


def test_summary_contract_rejects_empty_result_with_sources() -> None:
    result = SummaryResult(
        policy="offline",
        items=(),
        discussion_topic="暂无新闻。",
        provider="local",
        model="deterministic",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    try:
        validate_summary_result(
            result, [{"title": "AI launch", "link": "https://example.test/a"}]
        )
    except ValueError as exc:
        assert "at least one item" in str(exc)
    else:
        raise AssertionError("empty summary was accepted with source articles")
