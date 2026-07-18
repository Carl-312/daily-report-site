"""Validate one rendered AGI Hunt Trending pipeline run without another fetch."""

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

from scripts.agihunt_gray_health import _diagnostic_details, find_latest_manifest
from sources.agihunt_trending import AGIHUNT_TRENDING_SOURCE_LABEL
from utils.storage import atomic_write_text
from utils.summary_contracts import article_display_badge


def evaluate_trending_run(
    manifest: dict[str, Any], *, data_dir: Path
) -> dict[str, Any]:
    """Return a machine-readable health decision for one Trending run."""

    errors: list[str] = []
    checks: dict[str, Any] = {}
    sources = [
        source
        for source in manifest.get("sources", [])
        if isinstance(source, dict) and source.get("source") == "agihunt_trending"
    ]
    if len(sources) != 1:
        errors.append("expected exactly one agihunt_trending source outcome")
        source: dict[str, Any] = {}
    else:
        source = sources[0]

    report_date = str(manifest.get("report_date") or "")
    if not report_date:
        errors.append("manifest report_date is missing")
    checks["source_status"] = source.get("status")
    if source.get("status") != "ok":
        errors.append("agihunt_trending source status must be ok")

    articles = source.get("articles")
    if not isinstance(articles, list):
        articles = []
        errors.append("agihunt_trending article snapshots are missing")
    checks["accepted_count"] = source.get("accepted_count")
    checks["fetched_count"] = source.get("fetched_count")
    if source.get("accepted_count") != 15 or len(articles) != 15:
        errors.append("agihunt_trending must capture exactly 15 articles")
    if source.get("fetched_count") != 15:
        errors.append("agihunt_trending must render exactly 15 rows")

    details = _diagnostic_details(source, "agihunt_trending_snapshot")
    checks["snapshot"] = details
    for key in (
        "requested_day",
        "row_count",
        "chrome_version",
        "render_duration_ms",
        "dom_sha256",
        "parser_version",
    ):
        if not details.get(key):
            errors.append(f"snapshot diagnostic is missing {key}")
    if details.get("requested_day") != report_date:
        errors.append("snapshot day must match the report date")
    if details.get("row_count") != "15":
        errors.append("snapshot diagnostic row_count must be 15")

    ranks: list[int] = []
    term_keys: set[str] = set()
    article_links: set[str] = set()
    badges_by_link: dict[str, str] = {}
    for article in articles:
        if not isinstance(article, dict):
            errors.append("Trending article snapshot must be an object")
            continue
        link = str(article.get("link") or "")
        provenance = article.get("provenance")
        parsed_link = urlsplit(link)
        if parsed_link.scheme != "https" or parsed_link.hostname != "agihunt.info":
            errors.append("Trending detail link must use agihunt.info")
        else:
            article_links.add(link)
        if not isinstance(provenance, dict):
            errors.append("Trending article provenance is missing")
            continue
        if provenance.get("provider") != AGIHUNT_TRENDING_SOURCE_LABEL:
            errors.append("Trending provider label is invalid")
        if provenance.get("retrieval") != "homepage_trending_dom":
            errors.append("Trending retrieval mode is invalid")
        if provenance.get("trend_day") != report_date:
            errors.append("Trending article day must match the report date")
        if provenance.get("trend_window") != "1d":
            errors.append("Trending article window must be 1d")
        if provenance.get("trend_state") not in {"up", "down", "new", "steady"}:
            errors.append("Trending article state is invalid")
        try:
            float(provenance.get("trend_heat", ""))
            int(provenance.get("trend_delta", ""))
        except (TypeError, ValueError):
            errors.append("Trending heat and delta must be numeric")
        try:
            ranks.append(int(provenance.get("trend_rank", "")))
        except (TypeError, ValueError):
            errors.append("Trending rank must be an integer")
        term_key = str(provenance.get("trend_term_en") or "")
        if not term_key or term_key in term_keys:
            errors.append("Trending English title keys must be present and unique")
        term_keys.add(term_key)
        badge = article_display_badge(article)
        if not badge:
            errors.append("Trending article must contain a safe display badge")
        badges_by_link[link] = badge
    if ranks != list(range(1, 16)):
        errors.append("Trending ranks must be contiguous from 1 through 15")

    data_path = data_dir / f"{report_date}.json"
    checks["data_path"] = str(data_path)
    if not data_path.is_file():
        errors.append("generated data checkpoint is missing")
    else:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        generated_articles = payload.get("articles", [])
        generated_links = {
            str(article.get("link") or "")
            for article in generated_articles
            if isinstance(article, dict)
        }
        if not article_links <= generated_links:
            errors.append("Trending candidates are missing from generated data")
        summary = payload.get("summary", {})
        for item in summary.get("items", []) if isinstance(summary, dict) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if (
                url in badges_by_link
                and item.get("display_badge") != badges_by_link[url]
            ):
                errors.append("summary Trending badge does not match source provenance")

    publication = manifest.get("publication")
    checks["publication_status"] = (
        publication.get("status") if isinstance(publication, dict) else None
    )
    if checks["publication_status"] != "published":
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
    parser.add_argument("--output", default="agihunt-trending-health.json")
    args = parser.parse_args()

    manifest_path = find_latest_manifest(Path(args.runs_dir))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = evaluate_trending_run(manifest, data_dir=Path(args.data_dir))
    result["manifest_path"] = str(manifest_path)
    output_path = atomic_write_text(
        Path(args.output),
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    if not result["healthy"]:
        raise SystemExit(
            "AGI Hunt Trending health check failed: " + "; ".join(result["errors"])
        )
    print(f"AGI Hunt Trending health check passed: {output_path}")


if __name__ == "__main__":
    main()
