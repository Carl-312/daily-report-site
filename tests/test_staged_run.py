from __future__ import annotations

from types import SimpleNamespace

import pytest

import build
from main import stage_and_publish_run
from utils.publication import create_run_workspace


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
