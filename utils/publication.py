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
