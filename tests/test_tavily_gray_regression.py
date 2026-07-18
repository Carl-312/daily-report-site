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

    def fake_search(session, api_key, payload):
        seen_payloads.append(payload)
        include_domains = payload.get("include_domains")
        if not include_domains:
            return {"latency_ms": 5.0, "response": {"results": []}}
        if include_domains == ["thenextweb.com", "venturebeat.com"]:
            return {"latency_ms": 10.0, "response": {"results": priority_results}}
        if include_domains == ["reuters.com", "arstechnica.com"]:
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
                "min_articles": 10,
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
    assert report["reserved_refill_calls"] == 2
    assert report["verify_budget"] == 5
    assert report["verify_budget"] < old_metrics["verify_budget"]
    assert report["verify_calls"] == 5
    assert len(verify_payloads) == 5
    assert report["verify_skipped_due_budget"] == 7
    assert report["refill_calls"] == 2
    assert refill_domain_groups == [
        ["thenextweb.com", "venturebeat.com"],
        ["reuters.com", "arstechnica.com"],
    ]
    assert report["priority_refilled_count"] == 2
    assert report["secondary_refilled_count"] == 6
    assert report["final_count"] == 8
    assert report["stop_reason"] == "budget_exhausted_after_secondary_refill"
    assert report["accepted_by_stage_preview"]["secondary_refill"] == [
        "Salesforce launches AI workflow inspector",
        "Oracle adds AI database tuning agent",
        "ServiceNow ships AI helpdesk orchestrator",
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
        runs_dir=str(tmp_path / "runs"),
        timezone="Asia/Shanghai",
        enrichment=cfg.enrichment,
        tavily_api_key="test-key",
        api_key="",
        fallback_api_key="",
    )
    source_articles = [
        {
            "title": "OpenAI releases AI source story",
            "link": "https://example.com/source-story",
            "description": (
                "OpenAI发布新的人工智能能力，面向开发者提供更完整的模型使用支持，"
                "并提升复杂业务场景中的部署与评估效率。"
            ),
            "publish_time": "2026-05-11",
            "content": (
                "OpenAI发布新的人工智能能力，面向开发者提供更完整的模型使用支持，"
                "并提升复杂业务场景中的部署与评估效率。"
            ),
            "priority": 1,
            "source": "techcrunch",
        }
    ]
    enriched_articles = [
        *source_articles,
        {
            "title": "OpenAI launches AI evaluation console",
            "link": "https://thenextweb.com/news/openai-evaluation-console",
            "description": (
                "OpenAI推出人工智能评估控制台，帮助开发者系统验证模型输出质量，"
                "并在部署前识别复杂任务中的稳定性问题。"
            ),
            "publish_time": "2026-05-11T12:00:00Z",
            "content": (
                "OpenAI推出人工智能评估控制台，帮助开发者系统验证模型输出质量，"
                "并在部署前识别复杂任务中的稳定性问题。"
            ),
            "priority": 0,
            "source": "thenextweb.com",
        },
        {
            "title": "Mistral releases AI inference debugger",
            "link": "https://reuters.com/news/mistral-inference-debugger",
            "description": (
                "Mistral发布人工智能推理调试工具，帮助团队定位模型服务运行问题，"
                "并缩短复杂生产环境中的故障排查时间。"
            ),
            "publish_time": "2026-05-11T12:00:00Z",
            "content": (
                "Mistral发布人工智能推理调试工具，帮助团队定位模型服务运行问题，"
                "并缩短复杂生产环境中的故障排查时间。"
            ),
            "priority": 0,
            "source": "reuters.com",
        },
    ]
    order: list[str] = []
    summarized_articles: list[dict] = []

    def fake_fetch_batch(**kwargs):
        order.append("fetch_all")
        return list(source_articles), ()

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
        reference_dt,
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

    def fake_offline_summary(articles):
        assert order == ["fetch_all", "dedupe", "enrich_articles_with_tavily"]
        order.append("offline_summary")
        summarized_articles.extend(articles)
        return "\n".join(f"- {article['title']}" for article in articles)

    def fake_build_site(**kwargs):
        assert order[-1] == "offline_summary"
        kwargs["output_dir"].mkdir(parents=True, exist_ok=True)
        order.append("build")
        return []

    monkeypatch.setattr(daily_main, "get_config", lambda: runtime_cfg)
    monkeypatch.setattr(daily_main, "today_ymd", lambda: "2026-05-11")
    monkeypatch.setattr(daily_main, "today_cn", lambda: "2026年05月11日")
    monkeypatch.setattr(daily_main, "fetch_batch", fake_fetch_batch)
    monkeypatch.setattr(daily_main, "dedupe", fake_dedupe)
    monkeypatch.setattr(
        daily_main,
        "enrich_articles_with_tavily",
        fake_enrich_articles_with_tavily,
    )
    monkeypatch.setattr(daily_main, "offline_summary", fake_offline_summary)
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
        "offline_summary",
        "build",
    ]
    assert saved_report["articles"] == enriched_articles
    assert saved_report["enrichment"]["refill_calls"] == 2
    assert summarized_articles == enriched_articles
    assert "OpenAI launches AI evaluation console" in markdown
    assert "Mistral releases AI inference debugger" in markdown
