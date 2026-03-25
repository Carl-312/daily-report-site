from __future__ import annotations

from pathlib import Path

from build import build_site


def test_build_site_uses_dist_as_clean_output(tmp_path: Path) -> None:
    source_dir = tmp_path / "content"
    output_dir = tmp_path / "dist"
    assets_dir = tmp_path / "assets"

    source_dir.mkdir()
    output_dir.mkdir()
    assets_dir.mkdir()

    (source_dir / "2026-03-25.md").write_text(
        """---
title: AI 新闻日报 2026-03-25
date: 2026-03-25
---

## 今日热点

1. 第一条
2. 第二条
""",
        encoding="utf-8",
    )
    (assets_dir / "style.css").write_text("body { color: black; }\n", encoding="utf-8")
    (output_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    articles = build_site(
        source_dir=source_dir, output_dir=output_dir, assets_dir=assets_dir
    )

    assert [article["filename"] for article in articles] == ["2026-03-25.html"]
    assert not (output_dir / "stale.txt").exists()
    assert (output_dir / "style.css").exists()
    assert (output_dir / "2026-03-25.html").exists()
    assert (output_dir / "index.html").read_text(encoding="utf-8").find(
        "2026-03-25.html"
    ) != -1
    assert (output_dir / "archive.html").read_text(encoding="utf-8").find(
        "AI 新闻日报 2026-03-25"
    ) != -1


def test_build_site_without_content_creates_empty_state_pages(tmp_path: Path) -> None:
    source_dir = tmp_path / "content"
    output_dir = tmp_path / "dist"
    assets_dir = tmp_path / "assets"

    source_dir.mkdir()
    assets_dir.mkdir()
    (assets_dir / "style.css").write_text("body { color: black; }\n", encoding="utf-8")

    articles = build_site(
        source_dir=source_dir, output_dir=output_dir, assets_dir=assets_dir
    )

    assert articles == []
    assert (output_dir / "index.html").exists()
    assert (output_dir / "archive.html").exists()
    assert "暂无日报" in (output_dir / "index.html").read_text(encoding="utf-8")
    assert "近期日报归档" in (output_dir / "archive.html").read_text(encoding="utf-8")
    assert not list(output_dir.glob("2026-*.html"))
