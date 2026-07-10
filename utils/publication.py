"""Recoverable promotion of staged daily-report files.

The filesystem cannot atomically replace several unrelated paths as one unit.
This journaled promotion keeps a complete backup until every replacement has
succeeded and restores it on any in-process failure.  A later startup-recovery
hook can inspect the same journal after a process interruption.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from utils.storage import atomic_write_text


@dataclass(frozen=True, slots=True)
class PromotionResult:
    journal_path: Path
    backups_dir: Path
    targets: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class RunWorkspace:
    """Run-local locations for artifacts before they become public."""

    root: Path
    manifest_path: Path
    articles_path: Path
    summary_path: Path
    content_dir: Path
    site_dir: Path
    journal_path: Path


def create_run_workspace(
    runs_dir: str | Path, report_date: str, run_id: str
) -> RunWorkspace:
    """Create a constrained, run-scoped staging workspace."""
    if report_date in {"", ".", ".."} or "/" in report_date or "\\" in report_date:
        raise ValueError("report_date must be a simple directory component")
    if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a simple directory component")
    runs_root = Path(runs_dir).resolve()
    root = (runs_root / report_date / run_id).resolve()
    if not root.is_relative_to(runs_root):
        raise ValueError("run workspace must remain below runs_dir")
    root.mkdir(parents=True, exist_ok=True)
    return RunWorkspace(
        root=root,
        manifest_path=root / "manifest.json",
        articles_path=root / "articles.json",
        summary_path=root / "summary.md",
        content_dir=root / "content",
        site_dir=root / "site",
        journal_path=root / "promotion.json",
    )


def promote_staged_files(
    staged_to_target: Mapping[Path, Path], *, journal_path: Path
) -> PromotionResult:
    """Promote complete staged files while preserving last-known-good backups."""
    if not staged_to_target:
        raise ValueError("at least one staged file is required")
    missing = [str(path) for path in staged_to_target if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"staged files missing: {', '.join(missing)}")

    backups_dir = journal_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (staged, target) in enumerate(staged_to_target.items()):
        entries.append(
            {
                "index": index,
                "staged": str(staged),
                "target": str(target),
                "backup": str(backups_dir / f"{index}-{target.name}"),
                "target_existed": target.exists(),
            }
        )
    _write_journal(journal_path, "preparing", entries)

    replaced: list[dict[str, object]] = []
    try:
        for entry in entries:
            target = Path(str(entry["target"]))
            staged = Path(str(entry["staged"]))
            backup = Path(str(entry["backup"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                os.replace(target, backup)
            os.replace(staged, target)
            replaced.append(entry)
        _write_journal(journal_path, "published", entries)
        return PromotionResult(
            journal_path=journal_path,
            backups_dir=backups_dir,
            targets=tuple(Path(str(entry["target"])) for entry in entries),
        )
    except BaseException:
        _restore(entries, replaced)
        _write_journal(journal_path, "rolled_back", entries)
        raise


def _restore(
    entries: list[dict[str, object]], replaced: list[dict[str, object]]
) -> None:
    for entry in reversed(replaced):
        target = Path(str(entry["target"]))
        backup = Path(str(entry["backup"]))
        if target.exists():
            target.unlink()
        if backup.exists():
            os.replace(backup, target)
    for entry in entries:
        if entry not in replaced and bool(entry["target_existed"]):
            target = Path(str(entry["target"]))
            backup = Path(str(entry["backup"]))
            if backup.exists() and not target.exists():
                os.replace(backup, target)


def _write_journal(path: Path, state: str, entries: list[dict[str, object]]) -> None:
    atomic_write_text(
        path,
        json.dumps({"state": state, "entries": entries}, ensure_ascii=False, indent=2)
        + "\n",
    )


def recover_incomplete_promotion(journal_path: Path) -> bool:
    """Restore last-known-good files for a journal left in `preparing` state."""
    if not journal_path.is_file():
        return False
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("state") in {"published", "rolled_back"}:
        return False
    entries = list(journal.get("entries", []))
    for entry in reversed(entries):
        target = Path(str(entry["target"]))
        backup = Path(str(entry["backup"]))
        if backup.exists():
            if target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
    _write_journal(journal_path, "rolled_back", entries)
    return True


def recover_incomplete_promotions(runs_dir: str | Path) -> int:
    """Recover every interrupted run journal below the configured runs directory."""
    root = Path(runs_dir)
    if not root.exists():
        return 0
    return sum(
        recover_incomplete_promotion(path) for path in root.glob("*/*/promotion.json")
    )
