"""Run a bounded, user-authorized AGIHunt Phase 0 smoke check.

The command consumes an already configured ``AGIHUNT_API_KEY``. It never starts
device authorization, never prints the key, and refuses to make a request until
``--confirm-live-request`` is supplied. Its output contains only de-identified
response shape and transport metadata, so it can be retained under ``.runs/``.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_config
from sources.agihunt import (
    AgihuntClient,
    AgihuntError,
    AgihuntReport,
    AgihuntReportNotReadyError,
)


MAX_NETWORK_REQUESTS = 3
MAX_SAMPLED_ITEMS = 3
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _url_host(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return urlsplit(value).netloc.lower()
    except ValueError:
        return ""


def _endpoint_error(error: AgihuntError) -> dict[str, str]:
    return {"status": "error", "code": error.diagnostic_code}


def summarize_channels(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Retain channel schema evidence without copying channel descriptions."""

    summary: dict[str, Any] = {
        "top_level_keys": sorted(str(key) for key in payload),
    }
    channels = payload.get("channels")
    if not isinstance(channels, list):
        summary["channels_type"] = type(channels).__name__
        return summary

    slugs: list[str] = []
    item_keys: set[str] = set()
    for channel in channels:
        if isinstance(channel, str):
            slugs.append(channel)
        elif isinstance(channel, Mapping):
            item_keys.update(str(key) for key in channel)
            slug = channel.get("slug")
            if isinstance(slug, str):
                slugs.append(slug)
    summary.update(
        {
            "channels_type": "list",
            "channel_count": len(channels),
            "channel_item_keys": sorted(item_keys),
            "channel_slugs": sorted(set(slugs)),
        }
    )
    return summary


def summarize_report(report: AgihuntReport) -> dict[str, Any]:
    """Capture report link shape and freshness without retaining its body."""

    hosts = Counter(_url_host(value) for value in _URL_RE.findall(report.markdown))
    hosts.pop("", None)
    return {
        "status": "ok",
        "day": report.day,
        "generated_at": report.generated_at,
        "html_url_host": _url_host(report.html_url),
        "markdown_characters": len(report.markdown),
        "markdown_sha256": _digest(report.markdown),
        "markdown_link_count": sum(hosts.values()),
        "markdown_link_hosts": dict(sorted(hosts.items())),
    }


def summarize_channel_items(items: list[Any]) -> dict[str, Any]:
    """Expose parser-relevant types and values while excluding source content."""

    samples: list[dict[str, Any]] = []
    schema_keys: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        schema_keys.update(str(key) for key in item)
        if len(samples) >= MAX_SAMPLED_ITEMS:
            continue
        title = item.get("title")
        text = item.get("text")
        hot = item.get("hot")
        sample: dict[str, Any] = {
            "schema_keys": sorted(str(key) for key in item),
            "title_length": len(title) if isinstance(title, str) else None,
            "title_sha256": _digest(title) if isinstance(title, str) else "",
            "text_length": len(text) if isinstance(text, str) else None,
            "url_host": _url_host(item.get("url")),
            "author_present": bool(item.get("author")),
            "published_at": item.get("published_at"),
            "published_at_type": type(item.get("published_at")).__name__,
            "hot_type": type(hot).__name__,
        }
        if isinstance(hot, int | float) and not isinstance(hot, bool):
            sample["hot"] = hot
        samples.append(sample)
    return {
        "status": "ok",
        "item_count": len(items),
        "item_schema_keys": sorted(schema_keys),
        "samples": samples,
    }


def _finalize(result: dict[str, Any], client: Any, errors: list[str]) -> dict[str, Any]:
    stats = getattr(client, "stats", {})
    if not isinstance(stats, Mapping):
        stats = {}
    network_requests = stats.get("network_requests")
    result["transport"] = {
        "network_requests": network_requests,
        "cache_hits": stats.get("cache_hits"),
        "request_limit": MAX_NETWORK_REQUESTS,
    }
    if not isinstance(network_requests, int):
        errors.append("transport did not report network_requests")
    elif network_requests == 0:
        errors.append("cache-only run is not Phase 0 live evidence")
    elif network_requests > MAX_NETWORK_REQUESTS:
        errors.append("network request count exceeded Phase 0 limit")
    result["errors"] = errors
    result["healthy"] = not errors
    return result


def run_smoke(client: Any, *, day: str, channel: str) -> dict[str, Any]:
    """Perform the three allowed endpoints serially and return a safe record."""

    result: dict[str, Any] = {
        "schema_version": 1,
        "day": day,
        "channel": channel,
    }
    errors: list[str] = []

    try:
        result["channels"] = {
            "status": "ok",
            **summarize_channels(client.fetch_channels()),
        }
    except AgihuntError as error:
        result["channels"] = _endpoint_error(error)
        errors.append("channels endpoint did not complete")
        return _finalize(result, client, errors)

    try:
        result["report"] = summarize_report(client.fetch_report(day))
    except AgihuntReportNotReadyError as error:
        result["report"] = {"status": "not_ready", "code": error.diagnostic_code}
    except AgihuntError as error:
        result["report"] = _endpoint_error(error)
        errors.append("report endpoint did not complete")

    try:
        items = client.fetch_channel_items(channel, day)
    except AgihuntError as error:
        result["channel_items"] = _endpoint_error(error)
        errors.append("channel items endpoint did not complete")
        return _finalize(result, client, errors)

    result["channel_items"] = summarize_channel_items(items)
    if not items:
        errors.append("channel items endpoint returned no items")
    return _finalize(result, client, errors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--day", default="")
    parser.add_argument("--channel", default="models")
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--confirm-live-request",
        action="store_true",
        help="Required acknowledgement before the script calls the official API",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.confirm_live_request:
        raise SystemExit(
            "Refusing live AGIHunt requests without --confirm-live-request"
        )
    day = args.day or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError as error:
        raise SystemExit("--day must use YYYY-MM-DD") from error

    config = load_config(args.config)
    if not config.agihunt_api_key:
        raise SystemExit("AGIHUNT_API_KEY is required; no network request was made")
    client = AgihuntClient(
        api_key=config.agihunt_api_key,
        settings=config.agihunt,
        request_budget=MAX_NETWORK_REQUESTS,
    )
    result = run_smoke(client, day=day, channel=args.channel)
    output = (
        Path(args.output)
        if args.output
        else Path(".runs") / f"agihunt-phase0-{day}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not result["healthy"]:
        raise SystemExit("AGIHunt Phase 0 smoke failed: " + "; ".join(result["errors"]))
    print(f"AGIHunt Phase 0 smoke passed: {output}")


if __name__ == "__main__":
    main()
