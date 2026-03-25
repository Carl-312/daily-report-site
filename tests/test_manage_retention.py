from __future__ import annotations

from datetime import date
from pathlib import Path
import tarfile

from scripts.manage_retention import bundle_old_entries, prune_old_entries


def write_generated_pair(base_dir: Path, report_date: str) -> None:
    data_dir = base_dir / "data"
    content_dir = base_dir / "content"
    data_dir.mkdir(exist_ok=True)
    content_dir.mkdir(exist_ok=True)
    (data_dir / f"{report_date}.json").write_text(
        '{"date": "' + report_date + '"}\n', encoding="utf-8"
    )
    (content_dir / f"{report_date}.md").write_text(
        f"# {report_date}\n", encoding="utf-8"
    )


def test_bundle_old_entries_creates_release_archives(tmp_path: Path) -> None:
    write_generated_pair(tmp_path, "2026-03-17")
    write_generated_pair(tmp_path, "2026-03-25")

    staging_dir = tmp_path / ".archive-staging"
    archives = bundle_old_entries(
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
        staging_dir=staging_dir,
        keep_days=7,
        reference_date=date(2026, 3, 25),
        repo_root=tmp_path,
    )

    assert [archive.name for archive in archives] == ["daily-report-2026-03-17.tar.gz"]

    with tarfile.open(archives[0], "r:gz") as tar:
        names = tar.getnames()

    assert "data/2026-03-17.json" in names
    assert "content/2026-03-17.md" in names
    assert "2026-03-17/manifest.json" in names
    assert (staging_dir / "archive-manifest.json").exists()


def test_prune_old_entries_keeps_recent_seven_days(tmp_path: Path) -> None:
    write_generated_pair(tmp_path, "2026-03-18")
    write_generated_pair(tmp_path, "2026-03-19")
    write_generated_pair(tmp_path, "2026-03-25")

    removed = prune_old_entries(
        data_dir=tmp_path / "data",
        content_dir=tmp_path / "content",
        keep_days=7,
        reference_date=date(2026, 3, 25),
    )

    removed_paths = {path.relative_to(tmp_path).as_posix() for path in removed}
    assert removed_paths == {"data/2026-03-18.json", "content/2026-03-18.md"}
    assert (tmp_path / "data" / "2026-03-19.json").exists()
    assert (tmp_path / "content" / "2026-03-25.md").exists()
