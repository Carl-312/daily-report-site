"""
Archive and prune generated daily report artifacts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import io
import json
from pathlib import Path
import shutil
import tarfile

DATE_FORMAT = "%Y-%m-%d"
DEFAULT_KEEP_DAYS = 7
DEFAULT_ARCHIVE_TAG = "daily-report-archive"


@dataclass(frozen=True)
class ArchiveCandidate:
    """Files belonging to a single report date."""

    report_date: date
    files: tuple[Path, ...]

    @property
    def slug(self) -> str:
        return self.report_date.isoformat()


def parse_report_date(path: Path) -> date | None:
    """Extract a report date from a generated filename stem."""
    try:
        return datetime.strptime(path.stem, DATE_FORMAT).date()
    except ValueError:
        return None


def collect_generated_files(
    data_dir: Path, content_dir: Path
) -> dict[date, list[Path]]:
    """Collect generated files keyed by report date."""
    grouped: dict[date, list[Path]] = {}
    for pattern in ((data_dir, "*.json"), (content_dir, "*.md")):
        directory, glob_pattern = pattern
        if not directory.exists():
            continue
        for path in sorted(directory.glob(glob_pattern)):
            report_date = parse_report_date(path)
            if report_date is None:
                continue
            grouped.setdefault(report_date, []).append(path)
    return grouped


def cutoff_date(reference_date: date, keep_days: int) -> date:
    """Return the earliest date that should remain in the repository."""
    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    return reference_date - timedelta(days=keep_days - 1)


def get_archive_candidates(
    data_dir: Path,
    content_dir: Path,
    keep_days: int = DEFAULT_KEEP_DAYS,
    reference_date: date | None = None,
) -> list[ArchiveCandidate]:
    """Return generated files that should be archived before pruning."""
    reference_date = reference_date or datetime.now().date()
    keep_from = cutoff_date(reference_date, keep_days)
    grouped = collect_generated_files(data_dir, content_dir)
    candidates = [
        ArchiveCandidate(report_date=report_date, files=tuple(sorted(files)))
        for report_date, files in sorted(grouped.items())
        if report_date < keep_from
    ]
    return candidates


def archive_name(report_date: date) -> str:
    """Build the release asset filename for one report date."""
    return f"daily-report-{report_date.isoformat()}.tar.gz"


def build_archive(
    candidate: ArchiveCandidate,
    staging_dir: Path,
    repo_root: Path,
) -> Path:
    """Create a tar.gz bundle for one report date."""
    repo_root = repo_root.resolve()
    archive_path = staging_dir / archive_name(candidate.report_date)
    with tarfile.open(archive_path, "w:gz") as tar:
        for file_path in candidate.files:
            absolute_path = file_path.resolve()
            tar.add(
                absolute_path,
                arcname=absolute_path.relative_to(repo_root).as_posix(),
            )

        manifest = json.dumps(
            {
                "date": candidate.slug,
                "files": [
                    file_path.resolve().relative_to(repo_root).as_posix()
                    for file_path in candidate.files
                ],
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        manifest_info = tarfile.TarInfo(name=f"{candidate.slug}/manifest.json")
        manifest_info.size = len(manifest)
        tar.addfile(manifest_info, io.BytesIO(manifest))
    return archive_path


def write_staging_manifest(
    staging_dir: Path,
    candidates: list[ArchiveCandidate],
    archives: list[Path],
    keep_days: int,
    archive_tag: str = DEFAULT_ARCHIVE_TAG,
) -> Path:
    """Write a summary manifest describing the staged release assets."""
    manifest_path = staging_dir / "archive-manifest.json"
    manifest = {
        "archive_tag": archive_tag,
        "keep_days": keep_days,
        "archives": [
            {
                "date": candidate.slug,
                "asset_name": archive.name,
                "files": [path.as_posix() for path in candidate.files],
            }
            for candidate, archive in zip(candidates, archives, strict=True)
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def bundle_old_entries(
    data_dir: Path,
    content_dir: Path,
    staging_dir: Path,
    keep_days: int = DEFAULT_KEEP_DAYS,
    reference_date: date | None = None,
    repo_root: Path | None = None,
) -> list[Path]:
    """Bundle generated entries older than the keep window into release assets."""
    repo_root = repo_root or Path.cwd()
    candidates = get_archive_candidates(
        data_dir, content_dir, keep_days, reference_date
    )

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    archives = [
        build_archive(candidate, staging_dir, repo_root) for candidate in candidates
    ]
    write_staging_manifest(staging_dir, candidates, archives, keep_days)
    return archives


def prune_old_entries(
    data_dir: Path,
    content_dir: Path,
    keep_days: int = DEFAULT_KEEP_DAYS,
    reference_date: date | None = None,
) -> list[Path]:
    """Delete generated entries older than the keep window from the repository."""
    candidates = get_archive_candidates(
        data_dir, content_dir, keep_days, reference_date
    )
    removed: list[Path] = []
    for candidate in candidates:
        for file_path in candidate.files:
            if file_path.exists():
                file_path.unlink()
                removed.append(file_path)
    return removed


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description="Manage generated artifact retention")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("--data-dir", default="data")
    bundle_parser.add_argument("--content-dir", default="content")
    bundle_parser.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS)
    bundle_parser.add_argument("--reference-date", default="")
    bundle_parser.add_argument("--staging-dir", default=".archive-staging")

    prune_parser = subparsers.add_parser("prune")
    prune_parser.add_argument("--data-dir", default="data")
    prune_parser.add_argument("--content-dir", default="content")
    prune_parser.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS)
    prune_parser.add_argument("--reference-date", default="")
    return parser


def parse_optional_date(value: str) -> date | None:
    """Parse a CLI date argument when provided."""
    if not value:
        return None
    return datetime.strptime(value, DATE_FORMAT).date()


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    content_dir = Path(args.content_dir)
    reference_date = parse_optional_date(args.reference_date)

    if args.command == "bundle":
        staging_dir = Path(args.staging_dir)
        archives = bundle_old_entries(
            data_dir=data_dir,
            content_dir=content_dir,
            staging_dir=staging_dir,
            keep_days=args.keep_days,
            reference_date=reference_date,
        )
        print(f"Prepared {len(archives)} archive asset(s) in {staging_dir}")
        for archive in archives:
            print(archive.as_posix())
        return

    removed = prune_old_entries(
        data_dir=data_dir,
        content_dir=content_dir,
        keep_days=args.keep_days,
        reference_date=reference_date,
    )
    print(
        f"Removed {len(removed)} file(s) outside the {args.keep_days}-day retention window"
    )
    for path in removed:
        print(path.as_posix())


if __name__ == "__main__":
    main()
