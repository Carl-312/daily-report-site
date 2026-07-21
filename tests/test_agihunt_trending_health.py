from __future__ import annotations

import json

from scripts.agihunt_trending_health import evaluate_trending_run


def article(rank: int) -> dict:
    state = "up" if rank == 1 else "new"
    return {
        "title": f"趋势 {rank}",
        "link": f"https://agihunt.info/?day=2026-07-18&t=Trend+{rank}",
        "description": f"趋势 {rank} 简介",
        "publish_time": "2026-07-18T08:36:00+08:00",
        "content": "",
        "priority": 4 if rank <= 3 else 3,
        "source": "agihunt_trending",
        "provenance": {
            "provider": "AGI HUNT · agihunt.info",
            "retrieval": "homepage_trending_dom",
            "trend_day": "2026-07-18",
            "trend_window": "1d",
            "trend_rank": str(rank),
            "trend_heat": "14.9",
            "trend_state": state,
            "trend_delta": "10" if rank == 1 else "0",
            "trend_term_en": f"Trend {rank}",
        },
    }


def manifest(articles: list[dict]) -> dict:
    return {
        "report_date": "2026-07-18",
        "sources": [
            {
                "source": "agihunt_trending",
                "status": "ok",
                "attempts": 1,
                "duration_ms": 5500,
                "fetched_count": 15,
                "accepted_count": 15,
                "articles": articles,
                "diagnostics": [
                    {
                        "code": "agihunt_trending_snapshot",
                        "message": "captured snapshot",
                        "details": [
                            ["requested_day", "2026-07-18"],
                            ["row_count", "15"],
                            ["chrome_version", "Google Chrome 150.0.0.0"],
                            ["render_duration_ms", "5500"],
                            ["dom_sha256", "a" * 64],
                            ["parser_version", "1"],
                        ],
                    }
                ],
            }
        ],
        "publication": {"status": "published"},
    }


def test_health_accepts_a_complete_trending_snapshot(tmp_path) -> None:
    articles = [article(rank) for rank in range(1, 16)]
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "2026-07-18.json").write_text(
        json.dumps(
            {
                "articles": articles,
                "summary": {"items": [{"url": articles[0]["link"]}]},
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_trending_run(manifest(articles), data_dir=data_dir)

    assert result["healthy"] is True
    assert result["errors"] == []


def test_health_rejects_rank_drift(tmp_path) -> None:
    articles = [article(rank) for rank in range(1, 16)]
    articles[1]["provenance"]["trend_rank"] = "7"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "2026-07-18.json").write_text(
        json.dumps({"articles": articles, "summary": {"items": []}}),
        encoding="utf-8",
    )

    result = evaluate_trending_run(manifest(articles), data_dir=data_dir)

    assert result["healthy"] is False
    assert (
        "Trending ranks must be contiguous from 1 through row_count" in result["errors"]
    )


def test_health_accepts_a_partial_degraded_snapshot_with_private_destinations(
    tmp_path,
) -> None:
    articles = [article(rank) for rank in range(1, 13)]
    run_manifest = manifest(articles)
    source = run_manifest["sources"][0]
    source.update(
        {
            "status": "degraded",
            "accepted_count": 12,
            "fetched_count": 12,
        }
    )
    source["diagnostics"][0]["details"][1] = ["row_count", "12"]
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "2026-07-18.json").write_text(
        json.dumps(
            {
                "articles": [],
                "enrichment": {
                    "observation_signals": [
                        {"signal_url": item["link"]} for item in articles[:11]
                    ],
                    "candidate_dropped": [{"signal_url": articles[11]["link"]}],
                },
                "summary": {"items": []},
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_trending_run(run_manifest, data_dir=data_dir)

    assert result["healthy"] is True
