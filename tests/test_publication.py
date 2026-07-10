from __future__ import annotations

import json

import pytest

from utils import publication


def test_promotion_replaces_complete_staged_files_and_keeps_backups(tmp_path) -> None:
    staged_json = tmp_path / "run" / "articles.json"
    staged_markdown = tmp_path / "run" / "summary.md"
    target_json = tmp_path / "data" / "2026-07-10.json"
    target_markdown = tmp_path / "content" / "2026-07-10.md"
    for path, content in ((staged_json, "new-json"), (staged_markdown, "new-markdown")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for path, content in ((target_json, "old-json"), (target_markdown, "old-markdown")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    result = publication.promote_staged_files(
        {staged_json: target_json, staged_markdown: target_markdown},
        journal_path=tmp_path / "run" / "promotion.json",
    )

    assert target_json.read_text(encoding="utf-8") == "new-json"
    assert target_markdown.read_text(encoding="utf-8") == "new-markdown"
    assert (result.backups_dir / "0-2026-07-10.json").read_text(
        encoding="utf-8"
    ) == "old-json"
    assert (
        json.loads(result.journal_path.read_text(encoding="utf-8"))["state"]
        == "published"
    )


def test_failed_promotion_restores_last_known_good_files(tmp_path, monkeypatch) -> None:
    staged_one = tmp_path / "run" / "one"
    staged_two = tmp_path / "run" / "two"
    target_one = tmp_path / "public" / "one"
    target_two = tmp_path / "public" / "two"
    for path, content in ((staged_one, "new-one"), (staged_two, "new-two")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for path, content in ((target_one, "old-one"), (target_two, "old-two")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    real_replace = publication.os.replace
    calls = 0

    def fail_second_stage(source, destination):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected second promotion failure")
        return real_replace(source, destination)

    monkeypatch.setattr(publication.os, "replace", fail_second_stage)
    journal = tmp_path / "run" / "promotion.json"
    with pytest.raises(OSError, match="injected second promotion failure"):
        publication.promote_staged_files(
            {staged_one: target_one, staged_two: target_two}, journal_path=journal
        )

    assert target_one.read_text(encoding="utf-8") == "old-one"
    assert target_two.read_text(encoding="utf-8") == "old-two"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "rolled_back"
