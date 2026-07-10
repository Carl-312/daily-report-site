from __future__ import annotations

import json
from pathlib import Path

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


def test_run_workspace_is_run_scoped_and_rejects_path_escape(tmp_path) -> None:
    workspace = publication.create_run_workspace(
        tmp_path / ".runs", "2026-07-10", "run-1"
    )

    assert workspace.root == (tmp_path / ".runs" / "2026-07-10" / "run-1").resolve()
    assert workspace.articles_path == workspace.root / "articles.json"
    assert workspace.site_dir == workspace.root / "site"

    with pytest.raises(ValueError, match="report_date"):
        publication.create_run_workspace(tmp_path, "../outside", "run-1")
    with pytest.raises(ValueError, match="report_date"):
        publication.create_run_workspace(tmp_path, "..", "run-1")
    with pytest.raises(ValueError, match="run_id"):
        publication.create_run_workspace(tmp_path, "2026-07-10", "../outside")


def test_recovery_restores_backup_from_interrupted_journal(tmp_path) -> None:
    target = tmp_path / "public" / "report.json"
    backup = tmp_path / "runs" / "2026-07-10" / "run" / "backups" / "0-report.json"
    target.parent.mkdir(parents=True)
    backup.parent.mkdir(parents=True)
    backup.write_text("last-known-good", encoding="utf-8")
    journal = backup.parents[1] / "promotion.json"
    journal.write_text(
        json.dumps(
            {
                "state": "preparing",
                "entries": [
                    {
                        "target": str(target),
                        "backup": str(backup),
                        "staged": str(backup.parents[1] / "staged.json"),
                        "target_existed": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert publication.recover_incomplete_promotions(tmp_path / "runs") == 1
    assert target.read_text(encoding="utf-8") == "last-known-good"
    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == "rolled_back"


def test_public_edition_switches_all_reader_paths_with_one_pointer(tmp_path) -> None:
    staged = tmp_path / "run" / "edition"
    for name in ("data", "content", "site"):
        (staged / name).mkdir(parents=True)
        (staged / name / "marker").write_text("new\n", encoding="utf-8")

    edition = publication.promote_staged_edition(
        staged,
        tmp_path / "public",
        run_id="run-new",
        report_date="2026-07-10",
    )

    assert edition.run_id == "run-new"
    pointer = (tmp_path / "public" / "public-version.json").read_text(
        encoding="utf-8"
    )
    assert '"run_id": "run-new"' in pointer
    resolved = publication.read_current_edition(tmp_path / "public")
    assert resolved == edition
    assert {
        path.read_text(encoding="utf-8")
        for path in (
            resolved.data_dir / "marker",
            resolved.content_dir / "marker",
            resolved.site_dir / "marker",
        )
    } == {"new\n"}


def test_failed_pointer_write_keeps_previous_selected_edition(tmp_path, monkeypatch) -> None:
    public_root = tmp_path / "public"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for staged, marker, run_id in (
        (first, "old", "run-old"),
        (second, "new", "run-new"),
    ):
        for name in ("data", "content", "site"):
            (staged / name).mkdir(parents=True)
            (staged / name / "marker").write_text(marker, encoding="utf-8")
        if run_id == "run-old":
            publication.promote_staged_edition(
                staged,
                public_root,
                run_id=run_id,
                report_date="2026-07-10",
            )

    real_atomic_write = publication.atomic_write_text

    def fail_pointer(path, text):
        if Path(path).name == "public-version.json":
            raise OSError("injected pointer failure")
        return real_atomic_write(path, text)

    monkeypatch.setattr(publication, "atomic_write_text", fail_pointer)
    with pytest.raises(OSError, match="injected pointer failure"):
        publication.promote_staged_edition(
            second,
            public_root,
            run_id="run-new",
            report_date="2026-07-10",
        )

    resolved = publication.read_current_edition(public_root)
    assert resolved.run_id == "run-old"
    assert (resolved.data_dir / "marker").read_text(encoding="utf-8") == "old"
