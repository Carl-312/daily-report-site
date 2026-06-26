from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests

import build
import main as daily_main
from config import load_config
from utils import news_enrichment
from utils.news_enrichment import enrich_articles_with_tavily


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "tavily-gray-2026-05-11" / "report-minimal.json"
)


def load_project_config():
    return load_config(str(REPO_ROOT / "config.yaml"))


def load_gray_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def make_tavily_result(title: str, domain: str, slug: str) -> dict:
    return {
        "title": title,
        "url": f"https://{domain}/news/{slug}",
        "published_date": "2026-05-11T12:00:00Z",
        "content": f"{title} content",
        "score": 0.95,
    }


def test_gray_fixture_replays_default_budget_into_secondary_refill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_project_config()
    fixture = load_gray_fixture()
    old_metrics = fixture["old_metrics"]
    assert old_metrics == {
        "input_count": 13,
        "prefiltered_count": 12,
        "verify_calls": 6,
        "refill_calls": 1,
        "total_calls": 7,
        "final_count": 3,
        "stop_reason": "budget_exhausted_after_priority_refill",
        "verify_budget": 6,
        "reserved_refill_calls": None,
        "secondary_refill_runs": 0,
    }

    priority_results = [
        make_tavily_result(
            "OpenAI launches AI evaluation console",
            "thenextweb.com",
            "openai-evaluation-console",
        ),
        make_tavily_result(
            "Anthropic ships Claude developer observability",
            "venturebeat.com",
            "claude-observability",
        ),
    ]
    secondary_results = [
        make_tavily_result(
            "Salesforce launches AI workflow inspector",
            "reuters.com",
            "salesforce-workflow-inspector",
        ),
        make_tavily_result(
            "Adobe releases generative design monitor",
            "arstechnica.com",
            "adobe-design-monitor",
        ),
        make_tavily_result(
            "Oracle adds AI database tuning agent",
            "reuters.com",
            "oracle-database-agent",
        ),
        make_tavily_result(
            "ServiceNow ships AI helpdesk orchestrator",
            "arstechnica.com",
            "servicenow-helpdesk-orchestrator",
        ),
        make_tavily_result(
            "Snowflake debuts machine learning catalog review",
            "reuters.com",
            "snowflake-catalog-review",
        ),
        make_tavily_result(
            "GitHub introduces Copilot security triage",
            "arstechnica.com",
            "github-security-triage",
        ),
        make_tavily_result(
            "Canva unveils generative media assistant",
            "reuters.com",
            "canva-media-assistant",
        ),
        make_tavily_result(
            "IBM releases AI risk dashboard",
            "arstechnica.com",
            "ibm-watsonx-risk-dashboard",
        ),
    ]
    seen_payloads: list[dict] = []
    expected_priority_domains = news_enrichment.priority_refill_domains(cfg.enrichment)
    expected_secondary_domains = news_enrichment.secondary_refill_domains(
        cfg.enrichment
    )

    def fake_search(session, api_key, payload):
        seen_payloads.append(payload)
        include_domains = payload.get("include_domains")
        if not include_domains:
            return {"latency_ms": 5.0, "response": {"results": []}}
        if include_domains == expected_priority_domains:
            return {"latency_ms": 10.0, "response": {"results": priority_results}}
        if include_domains == expected_secondary_domains:
            return {"latency_ms": 12.0, "response": {"results": secondary_results}}
        raise AssertionError(f"Unexpected Tavily payload: {payload}")

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        fixture["articles"],
        report_date=fixture["report_date"],
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 7,
                "max_verify_calls": 6,
                "max_refill_rounds": 1,
                "min_articles": 14,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 5, 11, 23, 0, tzinfo=REPORT_TIMEZONE),
    )

    verify_payloads = [
        payload for payload in seen_payloads if not payload.get("include_domains")
    ]
    refill_domain_groups = [
        payload["include_domains"]
        for payload in seen_payloads
        if payload.get("include_domains")
    ]
    report = result["report"]

    assert report["input_count"] == old_metrics["input_count"]
    assert report["prefiltered_count"] == old_metrics["prefiltered_count"]
    assert report["source_preserved_count"] == 12
    assert report["reserved_refill_calls"] == 2
    assert report["verify_budget"] == 5
    assert report["verify_budget"] < old_metrics["verify_budget"]
    assert report["verify_calls"] == 5
    assert len(verify_payloads) == 5
    assert report["verify_skipped_due_budget"] == 7
    assert report["refill_calls"] == 1
    assert refill_domain_groups == [expected_priority_domains]
    assert report["priority_refilled_count"] == 2
    assert report["secondary_refilled_count"] == 0
    assert report["final_count"] == 14
    assert report["final_count_delta_vs_source"] == 2
    assert report["stop_reason"] == "priority_refill_complete"
    assert report["accepted_by_stage_preview"]["priority_refill"] == [
        "OpenAI launches AI evaluation console",
        "Anthropic ships Claude developer observability",
    ]


def test_preserved_verify_errors_satisfy_minimum_without_refill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_project_config()
    articles = [
        {
            "title": "OpenAI releases AI incident review tools",
            "link": "https://example.com/openai-incident-tools",
            "description": "",
            "publish_time": "2026-05-11",
            "content": "",
            "priority": 1,
            "source": "example",
        },
        {
            "title": "Anthropic adds Claude compliance agents",
            "link": "https://example.com/claude-compliance-agents",
            "description": "",
            "publish_time": "2026-05-11",
            "content": "",
            "priority": 1,
            "source": "example",
        },
    ]
    seen_payloads: list[dict] = []

    def fake_search(session, api_key, payload):
        seen_payloads.append(payload)
        if payload.get("include_domains"):
            raise AssertionError("Refill must not run when preserved articles meet min")
        raise requests.Timeout("simulated verify timeout")

    monkeypatch.setattr(news_enrichment, "search_tavily", fake_search)

    result = enrich_articles_with_tavily(
        articles,
        report_date="2026-05-11",
        settings=cfg.enrichment.model_copy(
            update={
                "enabled": True,
                "max_total_calls": 4,
                "max_verify_calls": 4,
                "max_refill_rounds": 1,
                "min_articles": 2,
            }
        ),
        tavily_api_key="test-key",
        enabled=True,
        reference_dt=datetime(2026, 5, 11, 23, 0, tzinfo=REPORT_TIMEZONE),
    )

    assert len(seen_payloads) == 2
    assert all("include_domains" not in payload for payload in seen_payloads)
    assert result["articles"] == articles
    assert result["report"]["verified_count"] == 0
    assert result["report"]["preserved_error_count"] == 2
    assert result["report"]["refill_needed_count"] == 0
    assert result["report"]["refill_calls"] == 0
    assert result["report"]["priority_refill_runs"] == []
    assert result["report"]["secondary_refill_runs"] == []
    assert result["report"]["stop_reason"] == "min_articles_satisfied_after_verify"


def test_run_pipeline_saves_and_summarizes_tavily_refill_articles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = load_project_config()
    runtime_cfg = SimpleNamespace(
        sources={"techcrunch": True},
        max_articles=10,
        syft_web_app_url="",
        syft_secret_key="",
        data_dir=str(tmp_path / "data"),
        content_dir=str(tmp_path / "content"),
        site_dir=str(tmp_path / "dist"),
        enrichment=cfg.enrichment,
        tavily_api_key="test-key",
        api_key="",
        fallback_api_key="",
    )
    source_articles = [
        {
            "title": "OpenAI releases AI source story",
            "link": "https://example.com/source-story",
            "description": "",
            "publish_time": "2026-05-11",
            "content": "",
            "priority": 1,
            "source": "techcrunch",
        }
    ]
    enriched_articles = [
        *source_articles,
        {
            "title": "OpenAI launches AI evaluation console",
            "link": "https://thenextweb.com/news/openai-evaluation-console",
            "description": "Priority refill content",
            "publish_time": "2026-05-11T12:00:00Z",
            "content": "Priority refill content",
            "priority": 0,
            "source": "thenextweb.com",
        },
        {
            "title": "Mistral releases AI inference debugger",
            "link": "https://reuters.com/news/mistral-inference-debugger",
            "description": "Secondary refill content",
            "publish_time": "2026-05-11T12:00:00Z",
            "content": "Secondary refill content",
            "priority": 0,
            "source": "reuters.com",
        },
    ]
    order: list[str] = []
    summarized_articles: list[dict] = []
    original_save_json = daily_main.save_json
    original_save_markdown = daily_main.save_markdown

    def fake_fetch_all(**kwargs):
        order.append("fetch_all")
        return list(source_articles)

    def fake_dedupe(articles):
        assert order == ["fetch_all"]
        order.append("dedupe")
        return list(articles)

    def fake_enrich_articles_with_tavily(
        articles,
        *,
        report_date,
        settings,
        tavily_api_key,
        enabled,
    ):
        assert order == ["fetch_all", "dedupe"]
        assert articles == source_articles
        assert report_date == "2026-05-11"
        assert tavily_api_key == "test-key"
        assert enabled is True
        order.append("enrich_articles_with_tavily")
        return {
            "articles": enriched_articles,
            "report": {
                "applied": True,
                "skip_reason": None,
                "verify_calls": 1,
                "refill_calls": 2,
                "fallback_calls": 0,
                "total_calls": 3,
                "accepted_by_stage_preview": {
                    "priority_refill": ["OpenAI launches AI evaluation console"],
                    "secondary_refill": [
                        "Mistral releases AI inference debugger",
                    ],
                },
            },
        }

    def recording_save_json(dir_path, date_str, data):
        assert order == ["fetch_all", "dedupe", "enrich_articles_with_tavily"]
        order.append("save_json")
        return original_save_json(dir_path, date_str, data)

    def fake_offline_summary(articles):
        assert order == [
            "fetch_all",
            "dedupe",
            "enrich_articles_with_tavily",
            "save_json",
        ]
        order.append("offline_summary")
        summarized_articles.extend(articles)
        return "\n".join(f"- {article['title']}" for article in articles)

    def recording_save_markdown(dir_path, date_str, content):
        assert order[-1] == "offline_summary"
        order.append("save_markdown")
        return original_save_markdown(dir_path, date_str, content)

    def fake_build_site():
        assert order[-1] == "save_markdown"
        order.append("build")
        return []

    monkeypatch.setattr(daily_main, "get_config", lambda: runtime_cfg)
    monkeypatch.setattr(daily_main, "today_ymd", lambda: "2026-05-11")
    monkeypatch.setattr(daily_main, "today_cn", lambda: "2026年05月11日")
    monkeypatch.setattr(daily_main, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(daily_main, "dedupe", fake_dedupe)
    monkeypatch.setattr(
        daily_main,
        "enrich_articles_with_tavily",
        fake_enrich_articles_with_tavily,
    )
    monkeypatch.setattr(daily_main, "save_json", recording_save_json)
    monkeypatch.setattr(daily_main, "offline_summary", fake_offline_summary)
    monkeypatch.setattr(daily_main, "save_markdown", recording_save_markdown)
    monkeypatch.setattr(build, "build_site", fake_build_site)

    daily_main.cmd_run(SimpleNamespace(enrichment="on", offline=True))

    saved_report = json.loads(
        (tmp_path / "data" / "2026-05-11.json").read_text(encoding="utf-8")
    )
    markdown = (tmp_path / "content" / "2026-05-11.md").read_text(encoding="utf-8")

    assert order == [
        "fetch_all",
        "dedupe",
        "enrich_articles_with_tavily",
        "save_json",
        "offline_summary",
        "save_markdown",
        "build",
    ]
    assert saved_report["articles"] == enriched_articles
    assert saved_report["enrichment"]["refill_calls"] == 2
    assert summarized_articles == enriched_articles
    assert "OpenAI launches AI evaluation console" in markdown
    assert "Mistral releases AI inference debugger" in markdown
