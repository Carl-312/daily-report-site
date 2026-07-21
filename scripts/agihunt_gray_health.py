"""Validate one AGIHunt shadow run before calling its preview artifact healthy."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from utils.summary_contracts import (
    reader_summary_issues,
    summary_visible_character_count,
)


AGIHUNT_LABEL = "AGI HUNT · agihunt.info"
AGIHUNT_CHANNEL_HOT_FEED = "channel_hot"


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def find_latest_manifest(runs_dir: Path) -> Path:
    manifests = list(runs_dir.glob("*/*/manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"no run manifest found under {runs_dir}")
    return max(manifests, key=lambda path: path.stat().st_mtime_ns)


def _diagnostic_details(source: dict[str, Any], code: str) -> dict[str, str]:
    for diagnostic in source.get("diagnostics", []):
        if diagnostic.get("code") != code:
            continue
        raw_details = diagnostic.get("details", [])
        return {
            str(key): str(value)
            for pair in raw_details
            if isinstance(pair, list | tuple) and len(pair) == 2
            for key, value in [pair]
        }
    return {}


def evaluate_shadow_run(
    manifest: dict[str, Any], *, data_dir: Path, content_dir: Path
) -> dict[str, Any]:
    """Return a durable, machine-readable health decision for a shadow run."""

    errors: list[str] = []
    checks: dict[str, Any] = {}
    sources = [
        source
        for source in manifest.get("sources", [])
        if isinstance(source, dict) and source.get("source") == "agihunt"
    ]
    if len(sources) != 1:
        errors.append("expected exactly one agihunt source outcome")
        source: dict[str, Any] = {}
    else:
        source = sources[0]

    report_date = manifest.get("report_date")
    if not isinstance(report_date, str) or not report_date:
        errors.append("manifest report_date is missing")
        report_date = ""

    status = source.get("status")
    checks["source_status"] = status
    if status != "ok":
        errors.append(f"agihunt source status must be ok, got {status!r}")

    accepted_count = source.get("accepted_count")
    articles = source.get("articles", [])
    checks["accepted_count"] = accepted_count
    if not isinstance(accepted_count, int) or accepted_count <= 0:
        errors.append("agihunt must accept at least one candidate")
    if not isinstance(articles, list) or len(articles) != accepted_count:
        errors.append("agihunt accepted_count must match captured candidate snapshots")

    details = _diagnostic_details(source, "agihunt_selection_stats")
    request_count = details.get("network_requests")
    checks["network_requests"] = request_count
    try:
        requests = int(request_count or "")
    except ValueError:
        errors.append("agihunt selection stats must include network_requests")
    else:
        if requests > 5:
            errors.append("agihunt network request count exceeded 5")

    article_links: set[str] = set()
    for article in articles if isinstance(articles, list) else []:
        if not isinstance(article, dict):
            errors.append("agihunt article snapshot must be an object")
            continue
        link = article.get("link")
        if not is_http_url(link):
            errors.append("agihunt candidate link must be HTTP(S)")
        else:
            article_links.add(link)
        provenance = article.get("provenance")
        if not isinstance(provenance, dict):
            errors.append("agihunt candidate must contain provenance")
            continue
        for key in ("channel", "channel_rank", "api_day"):
            if not provenance.get(key):
                errors.append(f"agihunt provenance is missing {key}")
        if provenance.get("provider") != AGIHUNT_LABEL:
            errors.append("agihunt provenance has an unexpected provider label")
        if provenance.get("retrieval") != AGIHUNT_CHANNEL_HOT_FEED:
            errors.append("agihunt provenance must identify the channel_hot feed")
        if report_date and provenance.get("api_day") != report_date:
            errors.append("agihunt provenance api_day must match the run report_date")
    data_path = data_dir / f"{report_date}.json"
    content_path = content_dir / f"{report_date}.md"
    summary_items: list[Any] = []
    checks["data_path"] = str(data_path)
    checks["content_path"] = str(content_path)
    if not data_path.is_file():
        errors.append("generated data checkpoint is missing")
    else:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            errors.append("generated data checkpoint must be an object")
        else:
            input_links = {
                item.get("link")
                for item in payload.get("articles", [])
                if isinstance(item, dict) and is_http_url(item.get("link"))
            }
            if not article_links <= input_links:
                errors.append("agihunt candidate links are missing from generated data")
            summary = payload.get("summary", {})
            if not isinstance(summary, dict):
                errors.append("generated summary must be an object")
            else:
                summary_items = summary.get("items", [])
                if not isinstance(summary_items, list):
                    errors.append("generated summary items must be a list")
                    summary_items = []
                elif not summary_items:
                    errors.append("generated summary must contain at least one item")
                summary_lengths: list[dict[str, Any]] = []
                summary_formats: list[dict[str, Any]] = []
                checks["summary_length"] = summary_lengths
                checks["summary_format"] = summary_formats
                for item in summary_items:
                    if (
                        not isinstance(item, dict)
                        or not is_http_url(item.get("url"))
                        or item.get("url") not in input_links
                    ):
                        errors.append("summary URL must match an input candidate link")
                        break
                    summary_text = item.get("summary")
                    if not isinstance(summary_text, str):
                        errors.append("summary item must include a text summary")
                        break
                    visible_characters = summary_visible_character_count(summary_text)
                    summary_lengths.append(
                        {
                            "article_id": item.get("article_id"),
                            "visible_characters": visible_characters,
                        }
                    )
                    issues = list(reader_summary_issues(summary_text))
                    summary_formats.append(
                        {
                            "article_id": item.get("article_id"),
                            "issues": issues,
                        }
                    )
                    if issues:
                        errors.append(
                            "summary item violates the complete reader-sentence "
                            "contract: " + "; ".join(issues)
                        )
                        break
    if not content_path.is_file():
        errors.append("generated Markdown report is missing")
    else:
        markdown = content_path.read_text(encoding="utf-8")
        if AGIHUNT_LABEL in markdown:
            errors.append("generated Markdown must keep source attribution private")
        rendered_items: list[str] = []
        for line in markdown.splitlines():
            if line.startswith("发生了什么："):
                rendered_items.append(line.split("发生了什么：", 1)[1])
            elif line[:1].isdigit() and ". " in line:
                rendered_items.append(line.split(". ", 1)[1])
        rendered_formats = [
            {
                "index": index,
                "issues": ["must not contain a colon"]
                if ":" in item or "：" in item
                else [],
            }
            for index, item in enumerate(rendered_items, 1)
        ]
        checks["rendered_summary_format"] = rendered_formats
        if summary_items and len(rendered_items) != len(summary_items):
            errors.append("generated Markdown item count must match the summary")
        for item in summary_items:
            if (
                isinstance(item, dict)
                and is_http_url(item.get("url"))
                and item["url"] in markdown
            ):
                errors.append(
                    "generated Markdown must keep direct source links private"
                )
                break
        if "观察信号" in markdown or "运行诊断" in markdown:
            errors.append("generated Markdown exposes private pipeline metadata")
        for item in rendered_formats:
            if item["issues"]:
                errors.append(
                    "rendered Markdown item violates the complete reader-sentence "
                    "contract: " + "; ".join(item["issues"])
                )
                break

    publication = manifest.get("publication", {})
    if not isinstance(publication, dict):
        publication = {}
    checks["publication_status"] = publication.get("status")
    if publication.get("status") != "published":
        errors.append("staged publication did not complete")

    return {
        "healthy": not errors,
        "report_date": report_date,
        "checks": checks,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", default=".runs")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--content-dir", default="content")
    parser.add_argument("--output", default=".runs/agihunt-gray-health.json")
    args = parser.parse_args()

    manifest_path = find_latest_manifest(Path(args.runs_dir))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = evaluate_shadow_run(
        manifest,
        data_dir=Path(args.data_dir),
        content_dir=Path(args.content_dir),
    )
    result["manifest_path"] = str(manifest_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not result["healthy"]:
        raise SystemExit(
            "AGIHunt shadow health check failed: " + "; ".join(result["errors"])
        )
    print(f"AGIHunt shadow health check passed: {output_path}")


if __name__ == "__main__":
    main()
