from __future__ import annotations

from utils.dedupe import dedupe


def test_dedupe_collapses_tracking_url_and_title_variants() -> None:
    articles = [
        {
            "title": "OpenAI launches a new model for developers",
            "link": "https://Example.com/story/?utm_source=feed#comments",
            "priority": 1,
        },
        {
            "title": "OpenAI launches new model for developers",
            "link": "https://example.com/story",
            "priority": 0,
        },
    ]

    result = dedupe(articles)

    assert len(result) == 1
    assert result[0]["priority"] == 1


def test_dedupe_collapses_obvious_cross_source_story_rewrite() -> None:
    articles = [
        {
            "title": "OpenAI launches a new model for developers",
            "link": "https://source-a.test/story",
            "priority": 1,
        },
        {
            "title": "OpenAI launches new model for developers",
            "link": "https://source-b.test/story",
            "priority": 0,
        },
    ]

    assert len(dedupe(articles)) == 1


def test_dedupe_keeps_distinct_stories() -> None:
    articles = [
        {
            "title": "OpenAI launches a new model for developers",
            "link": "https://source.test/one",
        },
        {
            "title": "Anthropic expands enterprise AI revenue",
            "link": "https://source.test/two",
        },
    ]

    assert len(dedupe(articles)) == 2
