"""Recoverable promotion of staged daily-report files.

The filesystem cannot atomically replace several unrelated paths as one unit.
This journaled promotion keeps a complete backup until every replacement has
succeeded and restores it on any in-process failure.  A later startup-recovery
hook can inspect the same journal after a process interruption.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from utils.storage import atomic_write_text


def _require_deadline(deadline_at, stage: str) -> None:
    if deadline_at is not None and datetime.now(deadline_at.tzinfo) >= deadline_at:
        raise TimeoutError(f"run deadline exceeded during {stage}")


@dataclass(frozen=True, slots=True)
class PromotionResult:
    journal_path: Path
    backups_dir: Path
    targets: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class PublicEdition:
    """One complete, immutable public view selected by a single pointer."""

    root: Path
    pointer_path: Path
    run_id: str
    report_date: str
    data_dir: Path
    content_dir: Path
    site_dir: Path


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


def read_current_edition(publication_root: str | Path) -> PublicEdition | None:
    """Resolve the one public edition selected by the atomic pointer."""
    root = Path(publication_root).resolve()
    pointer_path = root / "public-version.json"
    if not pointer_path.is_file():
        return None

    payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported publication pointer schema")
    run_id = str(payload.get("run_id", ""))
    report_date = str(payload.get("report_date", ""))
    edition_value = payload.get("edition")
    if not run_id or not report_date or not isinstance(edition_value, str):
        raise ValueError("publication pointer is incomplete")

    edition = (root / edition_value).resolve()
    editions_root = (root / "editions").resolve()
    if not edition.is_relative_to(editions_root):
        raise ValueError("publication edition must remain below editions directory")
    if not edition.is_dir():
        raise FileNotFoundError(f"selected publication edition is missing: {edition}")

    data_dir = edition / "data"
    content_dir = edition / "content"
    site_dir = edition / "site"
    if not all(path.is_dir() for path in (data_dir, content_dir, site_dir)):
        raise ValueError("selected publication edition is incomplete")
    return PublicEdition(
        root=edition,
        pointer_path=pointer_path,
        run_id=run_id,
        report_date=report_date,
        data_dir=data_dir,
        content_dir=content_dir,
        site_dir=site_dir,
    )


def promote_staged_edition(
    staged_dir: Path,
    publication_root: str | Path,
    *,
    run_id: str,
    report_date: str,
    deadline_at=None,
) -> PublicEdition:
    """Publish a complete edition by atomically replacing one public pointer.

    The edition is first renamed into the private editions directory. Readers
    continue using the previous pointer until the final atomic pointer write;
    after that write all three artifact families resolve to the same edition.
    """
    if not staged_dir.is_dir():
        raise FileNotFoundError(f"staged publication edition missing: {staged_dir}")
    if not run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("run_id must be a simple directory component")
    required_dirs = [staged_dir / name for name in ("data", "content", "site")]
    if not all(path.is_dir() for path in required_dirs):
        raise ValueError("staged publication edition must contain data/content/site")
    _require_deadline(deadline_at, "edition promotion")

    root = Path(publication_root).resolve()
    editions_root = root / "editions"
    editions_root.mkdir(parents=True, exist_ok=True)
    target = editions_root / run_id
    if target.exists():
        raise FileExistsError(f"publication edition already exists: {target}")
    os.replace(staged_dir, target)

    pointer_path = root / "public-version.json"
    pointer = {
        "schema_version": 1,
        "run_id": run_id,
        "report_date": report_date,
        "edition": str(target.relative_to(root)),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "paths": {"data": "data", "content": "content", "site": "site"},
    }
    try:
        _require_deadline(deadline_at, "public version pointer replacement")
        atomic_write_text(
            pointer_path,
            json.dumps(pointer, ensure_ascii=False, indent=2) + "\n",
        )
    except BaseException:
        # The old pointer is still authoritative. Keep the complete orphaned
        # edition for recovery/inspection rather than deleting good data.
        raise
    return PublicEdition(
        root=target,
        pointer_path=pointer_path,
        run_id=run_id,
        report_date=report_date,
        data_dir=target / "data",
        content_dir=target / "content",
        site_dir=target / "site",
    )


def mirror_public_edition(
    edition: PublicEdition,
    targets: Mapping[str, Path],
    *,
    deadline_at=None,
) -> None:
    """Refresh legacy output paths after pointer publication.

    These paths remain for CLI and GitHub Actions compatibility. They are not
    the consistency boundary; readers needing a cross-path view must resolve
    ``public-version.json`` through :func:`read_current_edition`.
    """
    for name, source in (
        ("data", edition.data_dir),
        ("content", edition.content_dir),
        ("site", edition.site_dir),
    ):
        _require_deadline(deadline_at, f"legacy {name} mirror")
        target = Path(targets[name])
        staged = target.with_name(f".{target.name}.mirror-staging")
        if staged.exists():
            shutil.rmtree(staged) if staged.is_dir() else staged.unlink()
        shutil.copytree(source, staged)
        _require_deadline(deadline_at, f"legacy {name} mirror")
        if target.exists():
            backup = target.with_name(f".{target.name}.mirror-previous")
            if backup.exists():
                shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
            os.replace(target, backup)
        os.replace(staged, target)


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


def promote_staged_directory(staged_dir: Path, target_dir: Path) -> Path:
    """Replace a complete site directory as one rename boundary.

    The former directory remains beside the target until the caller's run
    retention policy removes it; unlike per-file promotion this cannot expose
    a mixture of old and new site pages.
    """
    if not staged_dir.is_dir():
        raise FileNotFoundError(f"staged site directory missing: {staged_dir}")
    backup = target_dir.with_name(f".{target_dir.name}.previous")
    if backup.exists():
        if backup.is_dir():
            import shutil

            shutil.rmtree(backup)
        else:
            backup.unlink()
    if target_dir.exists():
        os.replace(target_dir, backup)
    try:
        os.replace(staged_dir, target_dir)
    except BaseException:
        if backup.exists():
            os.replace(backup, target_dir)
        raise
    return target_dir


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
