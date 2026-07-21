from __future__ import annotations

from types import SimpleNamespace

import pytest

import build
from main import stage_and_publish_run
from utils.publication import create_run_workspace
from utils.summary_contracts import SummaryItem, SummaryResult
from summarizer import offline_summary_result


def test_build_failure_does_not_overwrite_public_report_artifacts(
    tmp_path, monkeypatch
) -> None:
    cfg = SimpleNamespace(
        data_dir=str(tmp_path / "data"),
        content_dir=str(tmp_path / "content"),
        site_dir=str(tmp_path / "dist"),
    )
    old_json = tmp_path / "data" / "2026-07-10.json"
    old_markdown = tmp_path / "content" / "2026-07-10.md"
    old_site = tmp_path / "dist" / "index.html"
    for path, content in (
        (old_json, "old-json"),
        (old_markdown, "old-md"),
        (old_site, "old-site"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(
        build,
        "build_site",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("build failed")),
    )
    workspace = create_run_workspace(tmp_path / ".runs", "2026-07-10", "run")
    with pytest.raises(RuntimeError, match="build failed"):
        stage_and_publish_run(
            cfg,
            workspace,
            "2026-07-10",
            {"articles": [{"title": "candidate"}]},
            "candidate markdown",
        )

    assert old_json.read_text(encoding="utf-8") == "old-json"
    assert old_markdown.read_text(encoding="utf-8") == "old-md"
    assert old_site.read_text(encoding="utf-8") == "old-site"


def test_equivalent_edition_is_a_noop_without_rebuilding_site(
    tmp_path, monkeypatch
) -> None:
    cfg = SimpleNamespace(
        data_dir=str(tmp_path / "data"),
        content_dir=str(tmp_path / "content"),
        site_dir=str(tmp_path / "dist"),
    )
    report = {"articles": [{"title": "candidate"}]}
    first_json, first_markdown = stage_and_publish_run(
        cfg,
        create_run_workspace(tmp_path / ".runs", "2026-07-10", "first"),
        "2026-07-10",
        report,
        "candidate markdown",
    )
    before_json = first_json.stat().st_mtime_ns
    before_markdown = first_markdown.stat().st_mtime_ns
    monkeypatch.setattr(
        build, "build_site", lambda **kwargs: pytest.fail("must not rebuild")
    )

    second = stage_and_publish_run(
        cfg,
        create_run_workspace(tmp_path / ".runs", "2026-07-10", "second"),
        "2026-07-10",
        report,
        "candidate markdown",
    )

    assert second == (first_json, first_markdown)
    assert first_json.stat().st_mtime_ns == before_json
    assert first_markdown.stat().st_mtime_ns == before_markdown


def test_zero_story_run_publishes_a_same_day_empty_edition(tmp_path) -> None:
    cfg = SimpleNamespace(
        data_dir=str(tmp_path / "data"),
        content_dir=str(tmp_path / "content"),
        site_dir=str(tmp_path / "dist"),
        max_summary_items=10,
    )
    summary = offline_summary_result([])
    markdown = "🔥（2026年07月21日）每日AI资讯一览✨\n\n今日没有达到证据门槛的主新闻。"

    json_path, markdown_path = stage_and_publish_run(
        cfg,
        create_run_workspace(tmp_path / ".runs", "2026-07-21", "empty"),
        "2026-07-21",
        {
            "date": "2026-07-21",
            "articles": [],
            "enrichment": {"final_count": 0},
            "summary": summary.model_dump(mode="json"),
        },
        markdown,
    )

    assert json_path.name == "2026-07-21.json"
    assert markdown_path.read_text(encoding="utf-8").find(
        "今日没有达到证据门槛的主新闻"
    ) != -1


def test_publication_rejects_a_legacy_model_selected_summary(tmp_path) -> None:
    cfg = SimpleNamespace(
        data_dir=str(tmp_path / "data"),
        content_dir=str(tmp_path / "content"),
        site_dir=str(tmp_path / "dist"),
        max_summary_items=10,
    )
    articles = [
        {
            "title": "Candidate",
            "link": "https://example.test/candidate",
            "description": "候选包含足够事实，可供摘要程序稳定生成一条完整新闻。",
            "source": "one",
        }
    ]
    legacy = SummaryResult(
        policy="required_ai",
        items=(
            SummaryItem(
                article_id="a1",
                title="Candidate",
                summary="候选包含足够事实，可供摘要程序稳定生成一条完整新闻并绑定来源。",
                url="https://example.test/candidate",
            ),
        ),
        discussion_topic="你最关注哪条AI新闻？",
        provider="fixture",
        model="fixture",
        input_fingerprint="input",
        prompt_fingerprint="prompt",
    )

    with pytest.raises(ValueError, match="deterministic summary selection policy"):
        stage_and_publish_run(
            cfg,
            create_run_workspace(tmp_path / ".runs", "2026-07-10", "legacy"),
            "2026-07-10",
            {"articles": articles, "summary": legacy.model_dump(mode="json")},
            "candidate markdown",
        )
