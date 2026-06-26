from __future__ import annotations

import json
from pathlib import Path

from scripts.tavily_gray_scorecard import build_scorecard, render_scorecard_markdown


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_scorecard_explains_budget_and_metadata_low_count(
    tmp_path: Path,
) -> None:
    artifact_dir = (
        tmp_path
        / "tavily-gray-2026-05-11-25680995172"
        / "gray"
        / "tavily"
        / "2026-05-11"
    )
    (artifact_dir / "logs").mkdir(parents=True)
    (artifact_dir / "logs" / "run.log").write_text(
        "Tavily gray run date: 2026-05-11\n"
        "Command: python3 main.py run --offline --enrichment on\n",
        encoding="utf-8",
    )
    (artifact_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    write_json(
        artifact_dir / "manifest.json",
        {
            "date": "2026-05-11",
            "artifact_path": "gray/tavily/2026-05-11/",
            "purpose": "tavily_gray_validation",
        },
    )
    enrichment = {
        "report_date": "2026-05-11",
        "applied": True,
        "input_count": 3,
        "prefiltered_count": 2,
        "prefilter_stats": {"excluded_aggregate_like": 1},
        "prefilter_bucket_counts": {
            "core_ai": 1,
            "ai_neighbor": 0,
            "generic_or_low_signal": 1,
        },
        "prefilter_candidates": [
            {
                "source": "techcrunch",
                "title": "OpenAI launches AI tools",
                "aggregate_like": False,
            },
            {
                "source": "techcrunch",
                "title": "Enterprise software roundup",
                "aggregate_like": False,
            },
        ],
        "excluded_prefilter_candidates": [
            {
                "source": "aibase",
                "title": "AI daily roundup",
                "aggregate_like": True,
            }
        ],
        "verify_runs": [
            {
                "request_outcome": "success",
                "validation_outcome": "accepted",
            },
            {
                "request_outcome": "success",
                "validation_outcome": "missing_published_date",
            },
        ],
        "rejected_candidates": [{"title": "Enterprise software roundup"}],
        "verified_count": 1,
        "preserved_error_count": 0,
        "priority_refill_runs": [
            {
                "stage": "priority_refill",
                "request_outcome": "success",
                "result_count": 2,
                "accepted_count": 0,
                "candidate_results": [
                    {
                        "title": "Anthropic ships AI console",
                        "published_date": None,
                        "within_24h": None,
                        "ai_title_relevant": True,
                        "accepted": False,
                    },
                    {
                        "title": "OpenAI updates developer tools",
                        "published_date": "",
                        "within_24h": None,
                        "ai_title_relevant": True,
                        "accepted": False,
                    },
                ],
            }
        ],
        "secondary_refill_runs": [],
        "official_fallback_runs": [],
        "priority_refilled_count": 0,
        "secondary_refilled_count": 0,
        "official_refilled_count": 0,
        "total_calls": 3,
        "reserved_refill_calls": None,
        "verify_budget": 2,
        "verify_skipped_due_budget": 0,
        "final_count": 1,
        "refill_remaining_count": 2,
        "stop_reason": "budget_exhausted_after_priority_refill",
        "accepted_by_stage_preview": {
            "verify": ["OpenAI launches AI tools"],
            "priority_refill": [],
            "secondary_refill": [],
            "official_fallback": [],
        },
        "parameters": {
            "min_articles": 3,
            "max_total_calls": 3,
            "max_verify_calls": 2,
            "enable_official_fallback": False,
        },
    }
    write_json(
        artifact_dir / "report.json",
        {
            "date": "2026-05-11",
            "articles": [{"title": "OpenAI launches AI tools", "source": "techcrunch"}],
            "enrichment": enrichment,
        },
    )
    write_json(
        artifact_dir / "enrichment-summary.json",
        {"date": "2026-05-11", "enrichment": enrichment},
    )

    scorecard = build_scorecard(artifact_dir)

    assert scorecard["metadata"]["run_id"] == "25680995172"
    assert (
        scorecard["metadata"]["command"]
        == "python3 main.py run --offline --enrichment on"
    )
    assert scorecard["input_quality"]["source_distribution"] == {
        "aibase": 1,
        "techcrunch": 2,
    }
    assert scorecard["input_quality"]["aggregate_title_count"] == 1
    assert scorecard["refill"]["priority_refill"]["published_date_missing_rate"] == 1.0
    assert scorecard["budget"]["secondary_entered"] is False
    assert scorecard["diagnosis"]["primary_limiter"] == "source_count_reduced"
    assert "published_date_missing" in scorecard["diagnosis"]["contributing_factors"]
    assert (
        "final_count_below_source_valid_count"
        in scorecard["diagnosis"]["contributing_factors"]
    )
    assert scorecard["safety_gate"] == {
        "safe_to_commit": False,
        "source_input_count": 3,
        "source_valid_count": 2,
        "final_count": 1,
        "final_count_delta_vs_source": -1,
        "reason": "final_count_below_source_valid_count",
    }
    assert scorecard["diagnosis"]["needs_fixture"] is True
    assert scorecard["trend_metrics"] == {
        "final_count": 1,
        "verified_count": 1,
        "priority_refilled_count": 0,
        "secondary_refilled_count": 0,
        "published_date_missing_rate": 1.0,
        "source_preserved_count": 2,
        "source_dropped_count": 0,
        "hard_rejected_count": 0,
        "preserved_unverified_count": 0,
        "refill_rounds": 1,
        "added_by_tavily_count": 0,
        "strict_refill_accepted_count": 0,
        "soft_refill_accepted_count": 0,
        "final_count_delta_vs_source": -1,
        "lenient_candidate_count": 0,
        "proven_within_72h_count": 0,
        "missing_date_unproven_count": 0,
        "total_calls": 3,
        "stop_reason": "budget_exhausted_after_priority_refill",
    }

    markdown = render_scorecard_markdown(scorecard)
    assert "Primary limiter: `source_count_reduced`" in markdown
    assert "Fixture candidate: true" in markdown
    assert "| refill_rounds | `1` |" in markdown


def test_scorecard_prioritizes_network_failure_diagnosis(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "gray" / "tavily" / "2026-05-12"
    enrichment = {
        "report_date": "2026-05-12",
        "applied": True,
        "input_count": 2,
        "prefiltered_count": 2,
        "verify_runs": [
            {
                "request_outcome": "timeout",
                "validation_outcome": "not_evaluated",
            }
        ],
        "verified_count": 0,
        "preserved_error_count": 0,
        "priority_refill_runs": [],
        "secondary_refill_runs": [],
        "official_fallback_runs": [],
        "priority_refilled_count": 0,
        "secondary_refilled_count": 0,
        "official_refilled_count": 0,
        "total_calls": 1,
        "final_count": 0,
        "stop_reason": "below_min_articles_after_priority_refill_official_fallback_disabled",
        "parameters": {"min_articles": 2, "max_total_calls": 7},
    }
    write_json(
        artifact_dir / "report.json",
        {"date": "2026-05-12", "articles": [], "enrichment": enrichment},
    )

    scorecard = build_scorecard(artifact_dir)

    assert scorecard["diagnosis"]["primary_limiter"] == "source_count_reduced"
    assert "network_failures" in scorecard["diagnosis"]["contributing_factors"]
    assert (
        "final_count_below_source_valid_count"
        in scorecard["diagnosis"]["contributing_factors"]
    )
    assert scorecard["safety_gate"]["safe_to_commit"] is False
    assert scorecard["verify"]["request_outcomes"] == {"timeout": 1}


def test_scorecard_surfaces_lenient_refill_diagnostics(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "gray" / "tavily" / "2026-05-30"
    enrichment = {
        "report_date": "2026-05-30",
        "applied": True,
        "input_count": 0,
        "prefiltered_count": 0,
        "verify_runs": [],
        "verified_count": 0,
        "preserved_error_count": 0,
        "priority_refill_runs": [
            {
                "stage": "priority_refill",
                "request_outcome": "success",
                "result_count": 3,
                "accepted_count": 0,
                "candidate_results": [
                    {
                        "title": "OpenAI launches AI research agent",
                        "published_date": "2026-05-30T08:00:00Z",
                        "lenient_candidate": True,
                        "lenient_within_window": True,
                        "ai_title_relevant": True,
                        "accepted": False,
                    },
                    {
                        "title": "Anthropic updates Claude developer tools",
                        "published_date": None,
                        "lenient_candidate": True,
                        "lenient_within_window": None,
                        "ai_title_relevant": True,
                        "accepted": False,
                    },
                    {
                        "title": "Mistral debuts AI inference platform",
                        "published_date": "2026-05-25T08:00:00Z",
                        "lenient_candidate": False,
                        "lenient_within_window": False,
                        "ai_title_relevant": True,
                        "accepted": False,
                    },
                ],
            }
        ],
        "secondary_refill_runs": [],
        "official_fallback_runs": [],
        "priority_refilled_count": 0,
        "secondary_refilled_count": 0,
        "official_refilled_count": 0,
        "total_calls": 1,
        "final_count": 0,
        "strict_final_count": 0,
        "strict_refill_accepted_count": 0,
        "lenient_candidate_count": 2,
        "proven_within_72h_count": 1,
        "missing_date_unproven_count": 1,
        "outside_72h_rejected_count": 1,
        "lenient_non_ai_count": 0,
        "lenient_duplicate_or_cluster_count": 0,
        "lenient_selected_preview": [
            {"title": "OpenAI launches AI research agent"},
            {"title": "Anthropic updates Claude developer tools"},
        ],
        "lenient_refill_diagnostics": {
            "enabled": True,
            "window_hours": 72,
            "request_window_hours": 72,
            "start_date": "2026-05-27",
            "end_date": "2026-05-30",
            "stages": {},
        },
        "stop_reason": "budget_exhausted_after_priority_refill",
        "parameters": {
            "min_articles": 10,
            "max_total_calls": 7,
            "refill_search_window_hours": 72,
            "lenient_refill_window_hours": 72,
            "enable_official_fallback": False,
        },
    }
    write_json(
        artifact_dir / "report.json",
        {"date": "2026-05-30", "articles": [], "enrichment": enrichment},
    )

    scorecard = build_scorecard(artifact_dir)
    markdown = render_scorecard_markdown(scorecard)

    assert scorecard["output"]["strict_final_count"] == 0
    assert scorecard["lenient_diagnostics"]["enabled"] is True
    assert scorecard["lenient_diagnostics"]["request_window_hours"] == 72
    assert scorecard["lenient_diagnostics"]["lenient_candidate_count"] == 2
    assert scorecard["lenient_diagnostics"]["proven_within_72h_count"] == 1
    assert scorecard["lenient_diagnostics"]["missing_date_unproven_count"] == 1
    assert scorecard["lenient_diagnostics"]["outside_72h_rejected_count"] == 1
    assert scorecard["trend_metrics"]["lenient_candidate_count"] == 2
    assert "## Lenient Diagnostics" in markdown
