from __future__ import annotations

import json

from scripts.formal_gray_health import evaluate_formal_gray_run
from summarizer import offline_summary_result


def article(index: int, source: str) -> dict:
    return {
        "title": f"OpenAI launches documented AI platform update {index}",
        "link": f"https://{source}.example.com/ai/update-{index}",
        "description": (
            "OpenAI released a documented artificial intelligence platform "
            "update with rollout scope, measured results, and current limits."
        ),
        "publish_time": "2026-07-23T02:00:00Z",
        "content": "",
        "priority": 3,
        "source": source,
        "kind": "story",
        "evidence_status": "direct",
        "confidence": "direct",
    }


def manifest() -> dict:
    return {
        "report_date": "2026-07-23",
        "publication": {"status": "published"},
    }


def write_report(tmp_path, articles: list[dict], enrichment: dict) -> None:
    data_dir = tmp_path / "data"
    content_dir = tmp_path / "content"
    data_dir.mkdir()
    content_dir.mkdir()
    summary = offline_summary_result(articles)
    (data_dir / "2026-07-23.json").write_text(
        json.dumps(
            {
                "date": "2026-07-23",
                "articles": articles,
                "enrichment": enrichment,
                "summary": summary.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )


def test_health_accepts_tavily_fail_open_with_direct_source_diversity(
    tmp_path,
) -> None:
    articles = [article(1, "techcrunch"), article(2, "theverge")]
    write_report(
        tmp_path,
        articles,
        {
            "candidate_enrichment_runs": [{"request_outcome": "usage_limit_exceeded"}],
            "lead_unresolved_count": 3,
            "recent_dedupe": {"checked_days": []},
        },
    )

    result = evaluate_formal_gray_run(
        manifest(),
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
    )

    assert result["healthy"] is True
    assert result["checks"]["summary_source_counts"] == {
        "techcrunch": 1,
        "theverge": 1,
    }


def test_health_blocks_all_failed_enrichment_and_single_source(tmp_path) -> None:
    write_report(
        tmp_path,
        [article(1, "theverge")],
        {
            "candidate_enrichment_runs": [{"request_outcome": "http_error"}],
            "lead_unresolved_count": 12,
            "recent_dedupe": {"checked_days": []},
        },
    )

    result = evaluate_formal_gray_run(
        manifest(),
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
    )

    assert result["healthy"] is False
    assert any("collapsed to one source" in error for error in result["errors"])


def test_health_requires_previous_data_and_rejects_exact_repeats(tmp_path) -> None:
    articles = [article(1, "techcrunch"), article(2, "theverge")]
    write_report(
        tmp_path,
        articles,
        {
            "candidate_enrichment_runs": [{"request_outcome": "success"}],
            "lead_unresolved_count": 0,
            "recent_dedupe": {"checked_days": []},
        },
    )
    (tmp_path / "content" / "2026-07-22.md").write_text(
        "previous edition", encoding="utf-8"
    )

    missing = evaluate_formal_gray_run(
        manifest(),
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
    )
    assert missing["healthy"] is False
    assert any("without its data checkpoint" in error for error in missing["errors"])

    previous_summary = offline_summary_result([articles[0]])
    (tmp_path / "data" / "2026-07-22.json").write_text(
        json.dumps({"summary": previous_summary.model_dump(mode="json")}),
        encoding="utf-8",
    )
    repeated = evaluate_formal_gray_run(
        manifest(),
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
    )
    assert repeated["healthy"] is False
    assert any("repeats an exact URL" in error for error in repeated["errors"])
    assert any("did not inspect" in error for error in repeated["errors"])
