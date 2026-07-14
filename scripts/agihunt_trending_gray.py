"""Create an isolated ``publish=false`` AGIHunt channel-hot gray edition.

The public Agent skill v1.2.2 documents per-channel ``sort=hot`` feeds, but
does not document a global Trending endpoint or pagination parameters. This
script records that boundary rather than probing guessed routes, then stages a
reader-safe preview entirely below ``tmp/`` (or an explicit output root).
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

# ``python scripts/agihunt_trending_gray.py`` puts ``scripts/`` rather than the
# repository root first on sys.path. Keep the documented direct invocation
# usable without changing callers' environment.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from config import Settings, load_config
from main import agihunt_attribution_line, stage_and_publish_run
from sources import Article, fetch_batch
from summarizer import offline_summary_result, summarize_result
from utils.dedupe import dedupe
from utils.publication import create_run_workspace, read_current_edition
from utils.run_contracts import (
    PublicationState,
    RunClock,
    SourceRunResult,
    StageResult,
    new_manifest,
    write_manifest,
)
from utils.storage import atomic_write_text
from utils.summary_contracts import (
    SUMMARY_MAX_VISIBLE_CHARS,
    SUMMARY_MIN_VISIBLE_CHARS,
    SUMMARY_TARGET_MIN_VISIBLE_CHARS,
    SUMMARY_TARGET_MAX_VISIBLE_CHARS,
    SummaryResult,
    reader_summary_issues,
    render_summary_markdown,
    summary_visible_character_count,
    validate_summary_result,
)

from scripts.agihunt_gray_health import evaluate_shadow_run


EXPLORATION_REQUEST_BUDGET = 20
_ARTICLE_ID = re.compile(r"(?<![A-Za-z0-9_])a\d+(?![A-Za-z0-9_])", re.IGNORECASE)
SummaryFactory = Callable[[list[dict[str, Any]], int], SummaryResult]


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    return atomic_write_text(
        path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )


def _isolated_settings(config: Settings, output_root: Path) -> Settings:
    """Redirect every mutable output below the gray artifact root."""

    return config.model_copy(
        update={
            "sources": {"agihunt": True},
            "data_dir": str(output_root / "data"),
            "content_dir": str(output_root / "content"),
            "site_dir": str(output_root / "site"),
            "publication_root": str(output_root / "publication"),
            "runs_dir": str(output_root / "runs"),
        }
    )


def _selection_details(source: SourceRunResult) -> dict[str, str]:
    for diagnostic in source.diagnostics:
        if diagnostic.code == "agihunt_selection_stats":
            return dict(diagnostic.details)
    return {}


def _agihunt_outcome(results: tuple[SourceRunResult, ...]) -> SourceRunResult:
    matches = [result for result in results if result.source == "agihunt"]
    if len(matches) != 1:
        raise RuntimeError("expected exactly one AGIHunt source outcome")
    return matches[0]


def private_candidate_artifact(
    *,
    clock: RunClock,
    config: Settings,
    source: SourceRunResult,
    articles: list[dict[str, Any]],
    summary: dict[str, Any] | None,
    prior_network_requests: int = 0,
) -> dict[str, Any]:
    """Build the private evidence record without serializing any secret."""

    details = _selection_details(source)
    network_requests = int(details.get("network_requests", "0"))
    session_network_requests = prior_network_requests + network_requests
    channel_counts = Counter(
        str(article.get("provenance", {}).get("channel", ""))
        for article in articles
        if isinstance(article.get("provenance"), dict)
    )
    return {
        "schema_version": 1,
        "visibility": "private_gray_artifact",
        "generated_at": clock.cutoff_at.isoformat(),
        "api_day": clock.report_date_ymd,
        "official_agent_api": {
            "skill_version": config.agihunt.skill_version,
            "global_trending": {
                "status": "not_documented",
                "actual_count": 0,
                "reason": (
                    "The public v1.2.2 Agent skill lists no global Trending "
                    "endpoint, so no unverified route was called."
                ),
            },
            "channel_hot_fallback": {
                "endpoint": "GET /channel/{slug}/items",
                "parameters": {"day": "YYYY-MM-DD", "sort": "hot"},
                "documented_response": "top-100 items per channel",
                "selected_count": len(articles),
                "target_max_articles": config.agihunt.max_articles,
                "local_candidate_buffer": (
                    (len(config.agihunt.core_channels) + 1)
                    * config.agihunt.per_channel_limit
                ),
                "channel_counts": dict(sorted(channel_counts.items())),
                "reason": "fallback used because global Trending is not documented",
            },
            "pagination": {
                "limit": "not_documented",
                "cursor": "not_documented",
                "page": "not_documented",
                "behavior": "do not probe undocumented query parameters",
            },
            "date_parameter": {
                "format": "YYYY-MM-DD (also documented: YYYYMMDD)",
                "timezone": "Asia/Shanghai",
                "retention": "three recent Beijing calendar days",
            },
        },
        "request_budget": {
            "exploration_cap": EXPLORATION_REQUEST_BUDGET,
            "configured_run_cap": config.agihunt.request_budget,
            "prior_network_requests": prior_network_requests,
            "network_requests": network_requests,
            "cache_hits": int(details.get("cache_hits", "0")),
            "session_network_requests": session_network_requests,
            "within_exploration_cap": (
                session_network_requests <= EXPLORATION_REQUEST_BUDGET
            ),
        },
        "source": {
            "status": source.status,
            "fetched_count": source.fetched_count,
            "accepted_count": source.accepted_count,
            "diagnostics": [
                diagnostic.model_dump(mode="json") for diagnostic in source.diagnostics
            ],
        },
        "candidate_goal": {
            "minimum_independent_candidates": 10,
            "target_max_candidates": config.agihunt.max_articles,
            "actual_independent_candidates": len(articles),
            "minimum_met": len(articles) >= 10,
            "max_met": len(articles) == config.agihunt.max_articles,
        },
        "candidates": articles,
        "summary": summary,
    }


def reader_visibility_check(
    site_dir: Path, articles: list[dict[str, Any]]
) -> dict[str, Any]:
    """Ensure original source URLs and private summary IDs stay out of reader HTML."""

    pages = sorted(site_dir.glob("*.html"))
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in pages)
    source_urls = sorted(
        {
            str(article.get("link", "")).strip()
            for article in articles
            if str(article.get("link", "")).strip()
        }
    )
    exposed_urls = [url for url in source_urls if url in rendered]
    exposed_article_ids = sorted(set(_ARTICLE_ID.findall(rendered)))
    return {
        "pages_checked": [path.name for path in pages],
        "source_url_count": len(source_urls),
        "exposed_source_urls": exposed_urls,
        "exposed_article_ids": exposed_article_ids,
        "safe": bool(pages) and not exposed_urls and not exposed_article_ids,
    }


def summary_length_audit(summary: SummaryResult) -> dict[str, Any]:
    """Audit target length and the no-truncation reader-sentence contract."""

    items = [
        {
            "article_id": item.article_id,
            "visible_characters": summary_visible_character_count(item.summary),
            "within_preferred_range": (
                SUMMARY_TARGET_MIN_VISIBLE_CHARS
                <= summary_visible_character_count(item.summary)
                <= SUMMARY_TARGET_MAX_VISIBLE_CHARS
            ),
            "format_issues": list(reader_summary_issues(item.summary)),
        }
        for item in summary.items
    ]
    outside_preferred_range = [
        item for item in items if not item["within_preferred_range"]
    ]
    format_violations = [item for item in items if item["format_issues"]]
    return {
        "unit": "visible_characters_without_whitespace",
        "preferred_range": {
            "minimum": SUMMARY_TARGET_MIN_VISIBLE_CHARS,
            "maximum": SUMMARY_TARGET_MAX_VISIBLE_CHARS,
        },
        "hard_minimum": SUMMARY_MIN_VISIBLE_CHARS,
        "hard_maximum": SUMMARY_MAX_VISIBLE_CHARS,
        "items": items,
        "outside_preferred_range": outside_preferred_range,
        "format_violations": format_violations,
        "preferred_target_met": not outside_preferred_range,
        "complete_sentence_met": not format_violations,
        "qualified": not format_violations,
    }


def summary_provenance_audit(
    summary_mode: Literal["offline", "ai", "reviewed"], summary: SummaryResult
) -> dict[str, Any]:
    """Keep AI, deterministic, and editorial gray evidence unambiguous."""

    is_ai_result = summary.policy == "required_ai"
    if summary_mode == "ai" and not is_ai_result:
        raise RuntimeError(
            "AI gray mode requires a required_ai SummaryResult; "
            "offline or reviewed output cannot be labeled as AI"
        )
    if summary_mode != "ai" and is_ai_result:
        raise RuntimeError(
            f"{summary_mode} gray mode cannot publish a required_ai SummaryResult"
        )
    if summary_mode == "offline" and (
        summary.policy != "offline"
        or summary.provider != "local"
        or summary.model != "deterministic"
    ):
        raise RuntimeError(
            "offline gray mode requires the local deterministic summary result"
        )
    return {
        "mode": summary_mode,
        "policy": summary.policy,
        "provider": summary.provider,
        "model": summary.model,
        "ai_verified": is_ai_result,
    }


def run_isolated_gray(
    config: Settings,
    output_root: Path,
    *,
    now: datetime | None = None,
    deadline_duration: timedelta = timedelta(minutes=20),
    prior_network_requests: int = 0,
    summary_mode: Literal["offline", "ai", "reviewed"] = "offline",
    summary_factory: SummaryFactory | None = None,
    fetcher: Callable[
        ..., tuple[list[Article], tuple[SourceRunResult, ...]]
    ] = fetch_batch,
) -> dict[str, Any]:
    """Fetch, render, and validate a non-public AGIHunt preview in one root."""

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"gray output root already exists: {output_root}")
    if not 0 <= prior_network_requests <= EXPLORATION_REQUEST_BUDGET:
        raise ValueError("prior_network_requests must fit the exploration budget")
    output_root.mkdir(parents=True)
    cfg = _isolated_settings(config, output_root)
    clock = RunClock.create(
        cfg.timezone,
        now=now or datetime.now(ZoneInfo(cfg.timezone)),
        deadline_duration=deadline_duration,
    )
    manifest = new_manifest(cfg, clock)
    workspace = create_run_workspace(
        cfg.runs_dir, clock.report_date_ymd, manifest.run_id
    )
    write_manifest(workspace.manifest_path, manifest)

    articles, source_results = fetcher(
        enabled_sources={"agihunt": True},
        max_articles=cfg.max_articles,
        syft_url=cfg.syft_web_app_url,
        syft_key=cfg.syft_secret_key,
        agihunt_api_key=cfg.agihunt_api_key,
        agihunt_settings=cfg.agihunt,
        agihunt_max_articles=cfg.agihunt.max_articles,
        reference_dt=clock.cutoff_at,
        deadline_at=clock.deadline_at,
    )
    manifest = manifest.model_copy(
        update={
            "stages": (
                StageResult(name="fetch", status="ok", started_at=clock.started_at),
            ),
            "sources": source_results,
        }
    )
    write_manifest(workspace.manifest_path, manifest)

    source = _agihunt_outcome(source_results)
    article_dicts = [
        article.to_dict() if isinstance(article, Article) else article
        for article in dedupe(articles)
    ]
    if source.status != "ok" or not article_dicts:
        artifact = private_candidate_artifact(
            clock=clock,
            config=cfg,
            source=source,
            articles=article_dicts,
            summary=None,
            prior_network_requests=prior_network_requests,
        )
        _write_json(output_root / "agihunt-trending-candidates.private.json", artifact)
        raise RuntimeError(
            "AGIHunt gray fetch did not produce an eligible candidate set"
        )

    if summary_mode == "reviewed":
        if summary_factory is None:
            raise ValueError("reviewed gray mode requires a summary_factory")
        summary_result = summary_factory(article_dicts, cfg.max_summary_items)
    elif summary_factory is not None:
        raise ValueError("summary_factory is only supported by reviewed gray mode")
    elif summary_mode == "offline":
        summary_result = offline_summary_result(
            article_dicts, limit=cfg.max_summary_items
        )
    elif summary_mode == "ai":
        # This is intentionally opt-in: gray runs normally avoid model spend,
        # but a prompt revision must be verified against a real model response.
        summary_result = summarize_result(article_dicts, deadline_at=clock.deadline_at)
    else:
        raise ValueError(f"unsupported gray summary mode: {summary_mode!r}")
    summary_provenance = summary_provenance_audit(summary_mode, summary_result)
    validate_summary_result(
        summary_result, article_dicts, max_items=cfg.max_summary_items
    )
    length_audit = summary_length_audit(summary_result)
    if not length_audit["qualified"]:
        raise RuntimeError(
            "AGIHunt gray summary violates the complete reader-sentence contract"
        )
    summary_payload = summary_result.model_dump(mode="json")
    artifact = private_candidate_artifact(
        clock=clock,
        config=cfg,
        source=source,
        articles=article_dicts,
        summary=summary_payload,
        prior_network_requests=prior_network_requests,
    )
    _write_json(output_root / "agihunt-trending-candidates.private.json", artifact)
    if not artifact["request_budget"]["within_exploration_cap"]:
        raise RuntimeError("AGIHunt exploration request budget exceeded")

    title = f"🔥（{clock.report_date_cn}）每日AI资讯一览✨"
    public_content = "\n\n".join(
        filter(
            None,
            (
                title,
                agihunt_attribution_line(article_dicts),
                render_summary_markdown(summary_result),
            ),
        )
    )
    stage_and_publish_run(
        cfg,
        workspace,
        clock.report_date_ymd,
        {
            "date": clock.report_date_ymd,
            "articles": article_dicts,
            "enrichment": {"applied": False, "skip_reason": "gray_disabled"},
            "summary": summary_payload,
        },
        public_content,
        source_results,
        deadline_at=clock.deadline_at,
    )
    edition = read_current_edition(cfg.publication_root)
    manifest = manifest.model_copy(
        update={
            "publication": PublicationState(
                status="published",
                published_run_id=edition.run_id if edition else manifest.run_id,
                reason="publish_false_isolated_gray",
            )
        }
    )
    write_manifest(workspace.manifest_path, manifest)

    health = evaluate_shadow_run(
        manifest.model_dump(mode="json"),
        data_dir=Path(cfg.data_dir),
        content_dir=Path(cfg.content_dir),
    )
    reader = reader_visibility_check(Path(cfg.site_dir), article_dicts)
    verification = {
        "schema_version": 1,
        "publish": False,
        "mode": "isolated_local_gray",
        "summary_mode": summary_mode,
        "summary_provenance": summary_provenance,
        "output_root": str(output_root),
        "manifest_path": str(workspace.manifest_path),
        "private_candidates_path": str(
            output_root / "agihunt-trending-candidates.private.json"
        ),
        "request_budget": artifact["request_budget"],
        "health": health,
        "reader_visibility": reader,
        "summary_length": length_audit,
        "healthy": bool(
            health["healthy"] and reader["safe"] and length_audit["qualified"]
        ),
    }
    _write_json(output_root / "agihunt-trending-verification.json", verification)
    if not verification["healthy"]:
        raise RuntimeError("AGIHunt isolated gray verification failed")
    return verification


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--prior-network-requests",
        type=int,
        default=0,
        help="Already consumed requests to include in the 20-request exploration cap",
    )
    parser.add_argument(
        "--confirm-live-request",
        action="store_true",
        help="Required because a cold cache may call the official Agent API",
    )
    parser.add_argument(
        "--summary-mode",
        choices=("offline", "ai"),
        default="offline",
        help="Use deterministic fallback or verify the configured AI prompt",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.confirm_live_request:
        raise SystemExit(
            "Refusing AGIHunt gray execution without --confirm-live-request"
        )
    config = load_config(args.config)
    if not config.agihunt_api_key:
        raise SystemExit("AGIHUNT_API_KEY is required; no network request was made")
    verification = run_isolated_gray(
        config,
        Path(args.output_root),
        prior_network_requests=args.prior_network_requests,
        summary_mode=args.summary_mode,
    )
    print(f"AGIHunt isolated publish=false gray passed: {verification['output_root']}")


if __name__ == "__main__":
    main()
