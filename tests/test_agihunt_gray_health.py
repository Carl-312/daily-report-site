from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import main as daily_main
from config import Settings
from sources.base import Article
from scripts.agihunt_gray_health import AGIHUNT_LABEL, evaluate_shadow_run
from utils.run_contracts import ArticleSnapshot, RunClock, SourceRunResult
from utils.summary_contracts import SUMMARY_MAX_VISIBLE_CHARS


VALID_SUMMARY = (
    "发布重要产品更新，新增多项面向开发者的核心能力，"
    "推动行业应用持续扩展并进一步提升团队的实际工作效率。"
)


def source_result(*, requests: int = 5) -> dict:
    return {
        "source": "agihunt",
        "status": "ok",
        "accepted_count": 1,
        "articles": [
            {
                "title": "AGIHunt item",
                "link": "https://example.test/original-post",
                "provenance": {
                    "provider": AGIHUNT_LABEL,
                    "retrieval": "channel_hot",
                    "channel": "models",
                    "channel_rank": "1",
                    "api_day": "2026-07-13",
                },
            }
        ],
        "diagnostics": [
            {
                "code": "agihunt_selection_stats",
                "details": [["network_requests", str(requests)]],
            }
        ],
    }


def prepare_artifacts(tmp_path) -> tuple[dict, object, object]:
    data_dir = tmp_path / "data"
    content_dir = tmp_path / "content"
    data_dir.mkdir()
    content_dir.mkdir()
    (data_dir / "2026-07-13.json").write_text(
        json.dumps(
            {
                "articles": [
                    {"link": "https://example.test/original-post"},
                ],
                "summary": {
                    "items": [
                        {
                            "article_id": "a1",
                            "summary": VALID_SUMMARY,
                            "url": "https://example.test/original-post",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (content_dir / "2026-07-13.md").write_text(
        (f"日报\n\n{AGIHUNT_LABEL}\n\n1. {VALID_SUMMARY}\n"),
        encoding="utf-8",
    )
    manifest = {
        "report_date": "2026-07-13",
        "sources": [source_result()],
        "publication": {"status": "published"},
    }
    return manifest, data_dir, content_dir


def test_gray_health_accepts_a_complete_agihunt_shadow(tmp_path) -> None:
    manifest, data_dir, content_dir = prepare_artifacts(tmp_path)

    result = evaluate_shadow_run(manifest, data_dir=data_dir, content_dir=content_dir)

    assert result["healthy"] is True
    assert result["checks"]["network_requests"] == "5"
    assert result["checks"]["summary_length"] == [
        {"article_id": "a1", "visible_characters": 50}
    ]


def test_gray_health_rejects_request_budget_exhaustion(tmp_path) -> None:
    manifest, data_dir, content_dir = prepare_artifacts(tmp_path)
    manifest["sources"] = [source_result(requests=6)]

    result = evaluate_shadow_run(manifest, data_dir=data_dir, content_dir=content_dir)

    assert result["healthy"] is False
    assert "agihunt network request count exceeded 5" in result["errors"]


def test_gray_health_rejects_mismatched_provenance_day(tmp_path) -> None:
    manifest, data_dir, content_dir = prepare_artifacts(tmp_path)
    manifest["sources"][0]["articles"][0]["provenance"]["api_day"] = "2026-07-12"

    result = evaluate_shadow_run(manifest, data_dir=data_dir, content_dir=content_dir)

    assert result["healthy"] is False
    assert (
        "agihunt provenance api_day must match the run report_date" in result["errors"]
    )


def test_gray_health_rejects_oversized_summary(tmp_path) -> None:
    manifest, data_dir, content_dir = prepare_artifacts(tmp_path)
    payload_path = data_dir / "2026-07-13.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["summary"]["items"][0]["summary"] = "中" * SUMMARY_MAX_VISIBLE_CHARS + "。"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_shadow_run(manifest, data_dir=data_dir, content_dir=content_dir)

    assert result["healthy"] is False
    assert any(
        f"maximum is {SUMMARY_MAX_VISIBLE_CHARS}" in error for error in result["errors"]
    )


def test_gray_health_rejects_rendered_title_summary_colon_format(tmp_path) -> None:
    manifest, data_dir, content_dir = prepare_artifacts(tmp_path)
    (content_dir / "2026-07-13.md").write_text(
        (f"日报\n\n{AGIHUNT_LABEL}\n\n1. 人工智能产品更新：{VALID_SUMMARY}\n"),
        encoding="utf-8",
    )

    result = evaluate_shadow_run(manifest, data_dir=data_dir, content_dir=content_dir)

    assert result["healthy"] is False
    assert any("must not contain a colon" in error for error in result["errors"])


def test_full_offline_pipeline_produces_a_healthy_agihunt_shadow(
    tmp_path, monkeypatch
) -> None:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    clock = RunClock.create(
        "Asia/Shanghai",
        now=now,
    )
    report_date = clock.report_date_ymd
    article = Article(
        title="AGIHunt fixture story",
        link="https://example.test/original-post",
        description=(
            "AGIHunt灰度测试新闻发布多项面向开发者的新能力，"
            "帮助团队显著提升日常工作效率并拓展复杂业务场景的实际应用。"
        ),
        publish_time=f"{report_date}T07:00:00+08:00",
        priority=3,
        source="agihunt",
        provenance={
            "provider": AGIHUNT_LABEL,
            "retrieval": "channel_hot",
            "channel": "models",
            "channel_rank": "1",
            "api_day": report_date,
        },
    )
    source_result = SourceRunResult(
        source="agihunt",
        status="ok",
        attempts=5,
        duration_ms=1,
        fetched_count=1,
        accepted_count=1,
        articles=(ArticleSnapshot(**article.to_dict()),),
        diagnostics=(
            {
                "code": "agihunt_selection_stats",
                "message": "fixture",
                "details": (("network_requests", "5"),),
            },
        ),
    )
    cfg = Settings(
        api_key="",
        fallback_api_key="",
        sources={"agihunt": False},
        data_dir=str(tmp_path / "data"),
        content_dir=str(tmp_path / "content"),
        site_dir=str(tmp_path / "dist"),
        publication_root=str(tmp_path / "publication"),
        runs_dir=str(tmp_path / "runs"),
    )

    def fake_fetch_batch(**kwargs):
        assert kwargs["enabled_sources"] == {"agihunt": True}
        return [article], (source_result,)

    monkeypatch.setattr(daily_main, "get_config", lambda: cfg)
    monkeypatch.setattr(daily_main, "create_run_clock", lambda _cfg: clock)
    monkeypatch.setattr(daily_main, "fetch_batch", fake_fetch_batch)

    daily_main.cmd_run(SimpleNamespace(offline=True, enrichment="off", agihunt="on"))

    manifest_path = next((tmp_path / "runs").glob("*/*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = evaluate_shadow_run(
        manifest,
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
    )

    assert result["healthy"] is True


def test_deploy_workflow_uploads_a_nonhidden_agihunt_health_record() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")

    assert "--content-dir content --output agihunt-gray-health.json" in workflow
    assert "            agihunt-gray-health.json" in workflow
