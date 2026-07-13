from __future__ import annotations

from utils.summary_contracts import (
    SummaryItem,
    SummaryResult,
    fingerprint_summary_input,
    render_summary_markdown,
    validate_summary_result,
)
from summarizer import offline_summary_result


def test_structured_summary_renders_deterministically_with_article_links() -> None:
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
        "1. [AI launch](https://example.test/a)：发布了新能力\n\n"
        "💬 互动话题：你会如何使用这项能力？"
    )


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


def test_summary_contract_rejects_duplicate_ids_and_source_mismatch() -> None:
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
            [
                {"title": "AI launch", "link": "https://example.test/a"},
                {"title": "Second story", "link": "https://example.test/b"},
            ],
        )
    except ValueError as exc:
        assert "repeats article_id" in str(exc)
    else:
        raise AssertionError("invalid summary contract was accepted")
