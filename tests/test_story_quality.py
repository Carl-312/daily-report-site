from __future__ import annotations

import json

from utils.story_quality import (
    partition_articles_for_publication,
    remove_recent_exact_duplicates,
)


def test_trending_and_title_only_techcrunch_are_leads() -> None:
    result = partition_articles_for_publication(
        [
            {
                "title": "Trending signal",
                "link": "https://agihunt.info/?day=2026-07-19&t=Signal",
                "description": "One trend blurb.",
                "publish_time": "2026-07-19T08:00:00+08:00",
                "source": "agihunt_trending",
                "kind": "lead",
                "provenance": {"publish_time_semantics": "trend_observed_at"},
            },
            {
                "title": "TechCrunch title only",
                "link": "https://techcrunch.com/2026/07/19/story/",
                "description": "",
                "publish_time": "2026-07-19",
                "source": "techcrunch",
            },
        ]
    )

    assert result["stories"] == []
    assert [lead["title"] for lead in result["leads"]] == [
        "Trending signal",
        "TechCrunch title only",
    ]


def test_tavily_rfc2822_publish_time_is_a_real_story_time() -> None:
    article = {
        "title": "Direct Tavily result",
        "link": "https://example.com/news/direct-result",
        "description": "The article contains direct evidence for the reported change.",
        "publish_time": "Sat, 18 Jul 2026 20:54:42 GMT",
        "source": "example.com",
        "kind": "story",
        "evidence_status": "corroborated",
    }

    result = partition_articles_for_publication([article])

    assert result["stories"] == [article]
    assert result["leads"] == []


def test_recent_exact_selected_url_is_removed(tmp_path) -> None:
    (tmp_path / "2026-07-18.json").write_text(
        json.dumps(
            {
                "summary": {
                    "items": [{"url": "https://example.com/story?utm_source=ignored"}]
                }
            }
        ),
        encoding="utf-8",
    )
    articles = [
        {
            "title": "Repeated story",
            "link": "https://example.com/story?different=tracking",
        },
        {"title": "New story", "link": "https://example.com/new"},
    ]

    result = remove_recent_exact_duplicates(
        articles,
        data_dir=tmp_path,
        report_date="2026-07-19",
        window_days=3,
    )

    assert result["articles"] == [articles[1]]
    assert result["removed"][0]["reason"] == "recent_exact_url"
