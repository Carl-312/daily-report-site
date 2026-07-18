from __future__ import annotations

from utils.summary_contracts import (
    SUMMARY_MAX_VISIBLE_CHARS,
    SummaryItem,
    SummaryResult,
    fingerprint_summary_input,
    render_summary_markdown,
    reader_summary_issues,
    summary_visible_character_count,
    validate_summary_result,
)
from summarizer import offline_summary_result


def test_structured_summary_renders_without_article_ids_or_links() -> None:
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
        "1. 人工智能产品发布新能力，帮助开发者提升工作效率。"
        "\n\n💬 互动话题：你会如何使用这项能力？"
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

    assert "https://" not in rendered
    assert "www.example.test" not in rendered
    assert "[a1]" not in rendered
    assert "[AI launch]" not in rendered
    assert "1. 详情见，发布了新能力。" in rendered
    assert "：" not in rendered.splitlines()[0]


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
                "description": "该产品发布新能力，帮助开发者提升日常工作效率并拓展应用场景。",
                "link": "https://example.test/a",
                "priority": 1,
            }
        ]
    )

    assert result.policy == "offline"
    assert result.items[0].article_id == "a1"
    assert result.items[0].url == "https://example.test/a"


def test_trending_badge_is_bound_and_rendered_locally() -> None:
    article = {
        "title": "月之暗面 Kimi K3 发布引关注",
        "description": (
            "月之暗面发布 Kimi K3，并在多项评测中获得关注，"
            "其定价和实际能力也引发开发者讨论。"
        ),
        "link": "https://agihunt.info/?day=2026-07-18&t=Moonshot+Kimi+K3",
        "priority": 4,
        "source": "agihunt_trending",
        "provenance": {
            "trend_badge": "〔AGI趋势 #1｜热度14.9｜↑10〕",
        },
    }

    result = offline_summary_result([article])

    assert result.items[0].display_badge == "〔AGI趋势 #1｜热度14.9｜↑10〕"
    assert render_summary_markdown(result).startswith(
        "1. 〔AGI趋势 #1｜热度14.9｜↑10〕"
    )
    validate_summary_result(result, [article])


def test_summary_contract_allows_multiple_items_from_one_source() -> None:
    result = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="AI launch",
                summary="发布重要的新能力，推动行业实际应用持续扩展并提升开发者效率。",
                url="https://example.test/a",
            ),
            SummaryItem(
                article_id="a1",
                title="AI launch again",
                summary="重复发布新能力，推动相关行业应用持续扩展并提升实际工作效率。",
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
    summary = "近期LLM在电脑操控能力上出现显著跃迁，实际体验仍存在明显分歧。"

    assert summary_visible_character_count(summary) > 30
    assert reader_summary_issues(summary) == ()


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
