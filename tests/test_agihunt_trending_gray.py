from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import scripts.agihunt_trending_gray as gray_script
from config import Settings
from scripts.agihunt_trending_gray import (
    private_candidate_artifact,
    reader_visibility_check,
    run_isolated_gray,
)
from sources.base import Article
from utils.run_contracts import ArticleSnapshot, Diagnostic, RunClock, SourceRunResult
from utils.summary_contracts import SummaryAttempt, SummaryItem, SummaryResult


NOW = datetime(2026, 7, 14, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def live_publication_deadline(monkeypatch) -> None:
    """Keep the fixed report date without letting its deadline expire."""

    stage_and_publish = gray_script.stage_and_publish_run

    def stage_with_live_deadline(*args, **kwargs):
        deadline_at = kwargs.get("deadline_at")
        timezone = deadline_at.tzinfo if deadline_at is not None else NOW.tzinfo
        kwargs["deadline_at"] = datetime.now(timezone) + timedelta(minutes=20)
        return stage_and_publish(*args, **kwargs)

    monkeypatch.setattr(
        gray_script,
        "stage_and_publish_run",
        stage_with_live_deadline,
    )


def agihunt_article() -> Article:
    return Article(
        title="AGIHunt fixture release",
        link="https://example.test/original-post",
        description="AGIHunt灰度测试新闻发布多项新能力，帮助开发者显著提升日常工作效率。",
        publish_time="2026-07-14T01:00:00+00:00",
        priority=3,
        source="agihunt",
        provenance={
            "provider": "AGI HUNT · agihunt.info",
            "retrieval": "channel_hot",
            "channel": "models",
            "channel_rank": "1",
            "api_day": "2026-07-14",
            "hot": "9",
        },
    )


def agihunt_outcome(article: Article) -> SourceRunResult:
    return SourceRunResult(
        source="agihunt",
        status="ok",
        attempts=0,
        duration_ms=1,
        fetched_count=1,
        accepted_count=1,
        articles=(ArticleSnapshot(**article.to_dict()),),
        diagnostics=(
            Diagnostic(
                code="agihunt_selection_stats",
                message="fixture selection",
                details=(
                    ("api_day", "2026-07-14"),
                    ("network_requests", "0"),
                    ("cache_hits", "5"),
                    ("raw_items", "24"),
                    ("accepted_items", "1"),
                ),
            ),
        ),
    )


def test_private_artifact_states_the_documented_trending_boundary() -> None:
    cfg = Settings()
    clock = RunClock.create("Asia/Shanghai", now=NOW)
    article = agihunt_article()
    artifact = private_candidate_artifact(
        clock=clock,
        config=cfg,
        source=agihunt_outcome(article),
        articles=[article.to_dict()],
        summary=None,
        prior_network_requests=11,
    )

    assert artifact["official_agent_api"]["global_trending"] == {
        "status": "not_documented",
        "actual_count": 0,
        "reason": (
            "The public v1.2.2 Agent skill lists no global Trending endpoint, "
            "so no unverified route was called."
        ),
    }
    assert artifact["official_agent_api"]["pagination"]["cursor"] == "not_documented"
    assert artifact["official_agent_api"]["channel_hot_fallback"]["selected_count"] == 1
    assert artifact["request_budget"]["session_network_requests"] == 11
    assert artifact["candidates"][0]["link"] == article.link


def test_reader_visibility_check_detects_private_data_exposure(tmp_path: Path) -> None:
    article = agihunt_article().to_dict()
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    safe_page = site_dir / "safe.html"
    safe_page.write_text("<p>可读摘要</p>", encoding="utf-8")

    assert reader_visibility_check(site_dir, [article])["safe"] is True

    (site_dir / "leak.html").write_text(
        f"<p>{article['link']} [a1]</p>", encoding="utf-8"
    )
    result = reader_visibility_check(site_dir, [article])

    assert result["safe"] is False
    assert result["exposed_source_urls"] == [article["link"]]
    assert result["exposed_article_ids"] == ["a1"]


def test_isolated_gray_writes_private_evidence_without_touching_public_paths(
    tmp_path: Path,
    live_publication_deadline,
) -> None:
    public_data = tmp_path / "public-data"
    public_content = tmp_path / "public-content"
    public_site = tmp_path / "public-site"
    cfg = Settings(
        agihunt_api_key="test-key",
        data_dir=str(public_data),
        content_dir=str(public_content),
        site_dir=str(public_site),
        publication_root=str(tmp_path / "public-publication"),
        runs_dir=str(tmp_path / "public-runs"),
    )
    article = agihunt_article()
    outcome = agihunt_outcome(article)
    calls: list[dict] = []

    def fake_fetcher(**kwargs):
        calls.append(kwargs)
        return [article], (outcome,)

    output_root = tmp_path / "gray"
    verification = run_isolated_gray(
        cfg,
        output_root,
        now=NOW,
        deadline_duration=timedelta(days=1),
        prior_network_requests=3,
        fetcher=fake_fetcher,
    )

    assert verification["healthy"] is True
    assert verification["publish"] is False
    assert verification["summary_mode"] == "offline"
    assert verification["summary_provenance"] == {
        "mode": "offline",
        "policy": "offline",
        "provider": "local",
        "model": "deterministic",
        "ai_verified": False,
    }
    assert verification["reader_visibility"]["safe"] is True
    assert verification["summary_length"]["qualified"] is True
    assert verification["summary_length"]["hard_minimum"] == 30
    assert verification["summary_length"]["preferred_target_met"] is True
    assert verification["summary_length"]["complete_sentence_met"] is True
    assert all(
        35 <= item["visible_characters"] <= 50
        for item in verification["summary_length"]["items"]
    )
    assert verification["request_budget"]["session_network_requests"] == 3
    assert calls[0]["enabled_sources"] == {"agihunt": True}
    assert calls[0]["agihunt_max_articles"] == 20
    assert not public_data.exists()
    assert not public_content.exists()
    assert not public_site.exists()

    private_artifact = json.loads(
        (output_root / "agihunt-trending-candidates.private.json").read_text(
            encoding="utf-8"
        )
    )
    assert private_artifact["summary"]["items"][0]["article_id"] == "a1"
    assert private_artifact["summary"]["items"][0]["url"] == article.link
    reader_html = (output_root / "site" / "2026-07-14.html").read_text(encoding="utf-8")
    assert article.link not in reader_html
    assert "a1" not in reader_html


def test_isolated_gray_can_use_an_ai_summary_for_prompt_validation(
    tmp_path: Path, monkeypatch, live_publication_deadline
) -> None:
    cfg = Settings(agihunt_api_key="test-key")
    article = agihunt_article()
    outcome = agihunt_outcome(article)

    def fake_fetcher(**_kwargs):
        return [article], (outcome,)

    captured: dict[str, object] = {}

    def fake_summarize_result(articles, *, stream, deadline_at):
        captured.update(
            {"articles": articles, "stream": stream, "deadline_at": deadline_at}
        )
        return SummaryResult(
            policy="required_ai",
            items=(
                SummaryItem(
                    article_id="a1",
                    title=articles[0]["title"],
                    summary=articles[0]["description"],
                    url=articles[0]["link"],
                ),
            ),
            discussion_topic="你最关注哪条AI新闻？",
            provider="fixture_ai",
            model="fixture-model",
            input_fingerprint="fixture-input",
            prompt_fingerprint="fixture-prompt",
            attempts=(
                SummaryAttempt(
                    provider="fixture_ai",
                    model="fixture-model",
                    status="ok",
                ),
            ),
        )

    monkeypatch.setattr(gray_script, "summarize_result", fake_summarize_result)

    verification = run_isolated_gray(
        cfg,
        tmp_path / "gray-ai",
        now=NOW,
        deadline_duration=timedelta(days=1),
        summary_mode="ai",
        fetcher=fake_fetcher,
    )

    assert verification["healthy"] is True
    assert verification["summary_mode"] == "ai"
    assert verification["summary_provenance"]["ai_verified"] is True
    assert verification["summary_provenance"]["policy"] == "required_ai"
    assert captured["stream"] is False
    assert captured["articles"] == [article.to_dict()]


def test_isolated_gray_refuses_to_label_an_offline_result_as_ai(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = Settings(agihunt_api_key="test-key")
    article = agihunt_article()
    outcome = agihunt_outcome(article)

    def fake_fetcher(**_kwargs):
        return [article], (outcome,)

    from summarizer import offline_summary_result

    monkeypatch.setattr(
        gray_script,
        "summarize_result",
        lambda articles, **_kwargs: offline_summary_result(articles),
    )

    with pytest.raises(RuntimeError, match="cannot be labeled as AI"):
        run_isolated_gray(
            cfg,
            tmp_path / "gray-ai-mislabeled",
            now=NOW,
            deadline_duration=timedelta(days=1),
            summary_mode="ai",
            fetcher=fake_fetcher,
        )


def test_isolated_gray_can_validate_a_reviewed_source_faithful_summary(
    tmp_path: Path,
    live_publication_deadline,
) -> None:
    cfg = Settings(agihunt_api_key="test-key")
    article = agihunt_article()
    outcome = agihunt_outcome(article)
    reviewed: dict[str, object] = {}

    def fake_fetcher(**_kwargs):
        return [article], (outcome,)

    def reviewed_summary(articles, limit):
        reviewed.update({"articles": articles, "limit": limit})
        return SummaryResult(
            policy="offline",
            items=(
                SummaryItem(
                    article_id="a1",
                    title=articles[0]["title"],
                    summary=articles[0]["description"],
                    url=articles[0]["link"],
                ),
            ),
            discussion_topic="你最关注哪条AI新闻？",
            provider="editorial_review",
            model="source_faithful",
            input_fingerprint="fixture-input",
            prompt_fingerprint="fixture-reviewed",
            attempts=(
                SummaryAttempt(
                    provider="editorial_review",
                    model="source_faithful",
                    status="ok",
                ),
            ),
        )

    verification = run_isolated_gray(
        cfg,
        tmp_path / "gray-reviewed",
        now=NOW,
        deadline_duration=timedelta(days=1),
        summary_mode="reviewed",
        summary_factory=reviewed_summary,
        fetcher=fake_fetcher,
    )

    assert verification["healthy"] is True
    assert verification["summary_mode"] == "reviewed"
    assert verification["summary_provenance"] == {
        "mode": "reviewed",
        "policy": "offline",
        "provider": "editorial_review",
        "model": "source_faithful",
        "ai_verified": False,
    }
    assert reviewed["articles"] == [article.to_dict()]
    assert reviewed["limit"] == 10
