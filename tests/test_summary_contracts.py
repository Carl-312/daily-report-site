from __future__ import annotations

from utils.summary_contracts import (
    SummaryItem,
    SummaryResult,
    fingerprint_summary_input,
    render_summary_markdown,
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
                summary="发布了新能力",
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
        "1. AI launch：发布了新能力\n\n💬 互动话题：你会如何使用这项能力？"
    )


def test_renderer_removes_links_from_untrusted_offline_text() -> None:
    result = SummaryResult(
        policy="offline",
        items=(
            SummaryItem(
                article_id="a1",
                title="[AI launch](https://example.test/a)",
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
    assert "[AI launch]" not in rendered
    assert "1. AI launch：详情见，发布了新能力。" in rendered


def test_summary_fingerprints_are_stable_for_identical_input() -> None:
    first = fingerprint_summary_input([{"title": "A"}], "prompt")
    second = fingerprint_summary_input([{"title": "A"}], "prompt")
    changed = fingerprint_summary_input([{"title": "B"}], "prompt")

    assert first == second
    assert changed[0] != first[0]


def test_offline_summary_result_keeps_article_provenance() -> None:
    result = offline_summary_result(
        [
            {
                "title": "AI launch",
                "description": "new capability",
                "link": "https://example.test/a",
                "priority": 1,
            }
        ]
    )

    assert result.policy == "offline"
    assert result.items[0].article_id == "a1"
    assert result.items[0].url == "https://example.test/a"


def test_summary_contract_allows_multiple_items_from_one_source() -> None:
    result = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="AI launch",
                summary="发布了新能力",
                url="https://example.test/a",
            ),
            SummaryItem(
                article_id="a1",
                title="AI launch again",
                summary="重复发布了新能力",
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
