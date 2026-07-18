"""
Daily Report Site - Main Entry Point
Unified CLI for fetching news, summarizing, and building static site
"""

from __future__ import annotations
import argparse
import inspect
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import get_config
from sources import fetch_batch, Article
from utils import (
    dedupe,
    enrich_articles_with_tavily,
    today_ymd,
    today_cn,
    save_json,
    load_json,
)
from utils.run_contracts import (
    PublicationState,
    RunClock,
    StageResult,
    new_manifest,
    scrub_diagnostic,
    write_manifest,
)
from utils.publication import (
    create_run_workspace,
    mirror_public_edition,
    promote_staged_edition,
    read_current_edition,
    recover_incomplete_promotions,
)
from utils.publish_policy import decide_publication
from summarizer import (
    summarize_result,
    offline_summary,
    test_connection,
)
from utils.summary_contracts import (
    SummaryResult,
    render_summary_markdown,
    validate_summary_result,
)


def resolve_enrichment_enabled(cfg, mode: str) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    return bool(cfg.enrichment.enabled)


def resolve_enabled_sources(cfg, args) -> dict[str, bool]:
    """Apply one-run AGI Hunt overrides without changing config.yaml."""

    sources = dict(getattr(cfg, "sources", {}))
    for argument, source in (
        ("agihunt", "agihunt"),
        ("agihunt_trending", "agihunt_trending"),
    ):
        mode = getattr(args, argument, "auto")
        if mode != "auto":
            sources[source] = mode == "on"
    return sources


def agihunt_attribution_line(articles: list[Article | dict]) -> str:
    """Render a compact public attribution only when AGIHunt supplied input."""

    for article in articles:
        if isinstance(article, Article):
            source = article.source
            provenance = article.provenance
        else:
            source = str(article.get("source", ""))
            provenance = article.get("provenance", {})
        provider = (
            provenance.get("provider", "") if isinstance(provenance, dict) else ""
        )
        if source == "agihunt" or provider == "AGI HUNT · agihunt.info":
            return "> 候选来源：AGI HUNT · agihunt.info。"
    return ""


def compose_report_content(
    title: str, content: str, articles: list[Article | dict]
) -> str:
    """Keep source attribution outside the summary model's factual output."""

    parts = [title]
    attribution = agihunt_attribution_line(articles)
    if attribution:
        parts.append(attribution)
    parts.append(content)
    return "\n\n".join(parts)


def create_run_clock(cfg) -> RunClock:
    return RunClock.create(
        getattr(cfg, "timezone", "Asia/Shanghai"),
        deadline_duration=timedelta(
            minutes=float(getattr(cfg, "run_deadline_minutes", 20))
        ),
    )


def apply_enrichment(cfg, args, articles, date_str: str, clock: RunClock | None = None):
    enabled = resolve_enrichment_enabled(cfg, args.enrichment)
    print(
        "\n🧪 Tavily enrichment..."
        f" ({'enabled' if enabled else 'disabled'}, mode={args.enrichment})"
    )
    kwargs = {
        "report_date": date_str,
        "settings": cfg.enrichment,
        "tavily_api_key": cfg.tavily_api_key,
        "enabled": enabled,
        "reference_dt": clock.cutoff_at if clock else None,
    }
    if clock is not None and (
        "deadline_at" in inspect.signature(enrich_articles_with_tavily).parameters
        or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(
                enrich_articles_with_tavily
            ).parameters.values()
        )
    ):
        kwargs["deadline_at"] = clock.deadline_at
    result = enrich_articles_with_tavily(articles, **kwargs)
    report = result["report"]
    print(
        f"   Applied: {report.get('applied')} | "
        f"Skip: {report.get('skip_reason') or '-'} | "
        f"Final articles: {len(result['articles'])}"
    )
    if report.get("applied"):
        print(
            "   Calls:"
            f" verify={report.get('verify_calls', 0)},"
            f" refill={report.get('refill_calls', 0)},"
            f" fallback={report.get('fallback_calls', 0)},"
            f" total={report.get('total_calls', 0)}"
        )
    return result


def create_run_observer(cfg, clock: RunClock):
    """Create a non-public run manifest; promotion remains a later phase."""
    runs_dir = getattr(cfg, "runs_dir", ".runs")
    recover_incomplete_promotions(runs_dir)
    manifest = new_manifest(cfg, clock)
    workspace = create_run_workspace(runs_dir, clock.report_date_ymd, manifest.run_id)
    write_manifest(workspace.manifest_path, manifest)
    return manifest, workspace


def resolve_publication_root(cfg) -> Path:
    """Resolve the pointer store without leaking test/preview state globally."""
    configured = getattr(cfg, "publication_root", None)
    if configured:
        return Path(configured)
    return Path(cfg.data_dir).resolve().parent / ".publication"


def update_run_observer(path, manifest, *, stages=(), sources=(), publication=None):
    updated = manifest.model_copy(
        update={
            "stages": tuple(stages),
            "sources": tuple(sources),
            "publication": publication or manifest.publication,
        }
    )
    write_manifest(path, updated)
    return updated


def record_blocked_run(cfg, workspace, manifest, *, sources=(), error=None):
    reason = type(error).__name__ if error is not None else "run_failed"
    if error is not None:
        detail = scrub_diagnostic(str(error), cfg)
        if detail:
            reason = f"{reason}: {detail}"
    return update_run_observer(
        workspace.manifest_path,
        manifest,
        stages=manifest.stages,
        sources=tuple(sources),
        publication=PublicationState(status="blocked", reason=reason),
    )


def stage_and_publish_run(
    cfg,
    workspace,
    date_str: str,
    report: dict,
    content: str,
    source_results=(),
    deadline_at=None,
):
    """Build a complete candidate edition before changing any public artifact."""
    from build import build_site
    from utils.storage import save_json, save_markdown

    summary_payload = report.get("summary")
    if summary_payload is not None:
        summary_result = SummaryResult.model_validate(summary_payload)
        validate_summary_result(
            summary_result,
            report["articles"],
            max_items=getattr(cfg, "max_summary_items", 10),
        )

    decision = decide_publication(
        articles_count=len(report["articles"]),
        source_results=tuple(source_results),
        summary_succeeded=True,
        build_succeeded=True,
    )
    if not decision.publish:
        raise RuntimeError(f"publication blocked: {decision.reason}")
    if deadline_at is not None and deadline_at <= datetime.now(deadline_at.tzinfo):
        raise TimeoutError("run deadline exceeded before staged publication")
    staged_edition = workspace.root / "edition"
    staged_data = staged_edition / "data"
    staged_content = staged_edition / "content"
    staged_site = staged_edition / "site"
    staged_content.mkdir(parents=True, exist_ok=True)
    publication_root = resolve_publication_root(cfg)
    current = read_current_edition(publication_root)
    public_content = current.content_dir if current else Path(cfg.content_dir)
    if public_content.exists():
        shutil.copytree(public_content, staged_content, dirs_exist_ok=True)
    staged_json = save_json(str(staged_data), date_str, report)
    staged_markdown = save_markdown(str(staged_content), date_str, content)
    public_json = Path(cfg.data_dir) / f"{date_str}.json"
    public_markdown = Path(cfg.content_dir) / f"{date_str}.md"
    if (
        current is not None
        and (current.data_dir / f"{date_str}.json").is_file()
        and (current.content_dir / f"{date_str}.md").is_file()
        and staged_json.read_bytes()
        == (current.data_dir / f"{date_str}.json").read_bytes()
        and staged_markdown.read_bytes()
        == (current.content_dir / f"{date_str}.md").read_bytes()
    ):
        print("ℹ️  Equivalent edition already published; skipping promotion.")
        return public_json, public_markdown
    build_kwargs = {
        "source_dir": staged_content,
        "output_dir": staged_site,
        "assets_dir": Path("assets"),
    }
    if deadline_at is not None:
        build_kwargs["deadline_at"] = deadline_at
    build_site(**build_kwargs)
    if deadline_at is not None and deadline_at <= datetime.now(deadline_at.tzinfo):
        raise TimeoutError("run deadline exceeded after site build")
    edition = promote_staged_edition(
        staged_edition,
        publication_root,
        run_id=workspace.root.name,
        report_date=date_str,
        deadline_at=deadline_at,
    )
    try:
        mirror_public_edition(
            edition,
            {
                "data": Path(cfg.data_dir),
                "content": Path(cfg.content_dir),
                "site": Path(cfg.site_dir),
            },
            deadline_at=deadline_at,
        )
    except Exception as exc:
        print(
            f"⚠️  Legacy compatibility mirror failed after publication: {type(exc).__name__}"
        )
    return public_json, public_markdown


def rebuild_current_site(cfg, clock, workspace):
    """Rebuild a new site edition without mutating the selected edition."""
    from build import build_site

    current = read_current_edition(resolve_publication_root(cfg))
    report_date = current.report_date if current else clock.report_date_ymd
    staged_edition = workspace.root / "edition"
    staged_data = staged_edition / "data"
    staged_content = staged_edition / "content"
    staged_site = staged_edition / "site"
    source_data = current.data_dir if current else Path(cfg.data_dir)
    source_content = current.content_dir if current else Path(cfg.content_dir)
    staged_data.mkdir(parents=True, exist_ok=True)
    staged_content.mkdir(parents=True, exist_ok=True)
    if source_data.exists():
        shutil.copytree(source_data, staged_data, dirs_exist_ok=True)
    if source_content.exists():
        shutil.copytree(source_content, staged_content, dirs_exist_ok=True)
    build_site(
        source_dir=staged_content,
        output_dir=staged_site,
        assets_dir=Path("assets"),
        deadline_at=clock.deadline_at,
    )
    edition = promote_staged_edition(
        staged_edition,
        resolve_publication_root(cfg),
        run_id=workspace.root.name,
        report_date=report_date,
        deadline_at=clock.deadline_at,
    )
    try:
        mirror_public_edition(
            edition,
            {
                "data": Path(cfg.data_dir),
                "content": Path(cfg.content_dir),
                "site": Path(cfg.site_dir),
            },
            deadline_at=clock.deadline_at,
        )
    except Exception as exc:
        print(
            f"⚠️  Legacy compatibility mirror failed after publication: {type(exc).__name__}"
        )
    return edition


def persist_summary_result(workspace, result) -> Path:
    """Persist structured summary metadata for replay without publishing it."""
    target = workspace.root / "summary.json"
    target.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def summarize_or_offline(
    articles: list[dict], *, offline: bool, cfg, deadline_at=None
) -> str:
    """Generate an LLM summary, falling back to offline output when providers fail."""
    summary_limit = max(1, int(getattr(cfg, "max_summary_items", 10)))
    if offline:
        return (
            offline_summary(articles)
            if summary_limit == 10
            else offline_summary(articles, limit=summary_limit)
        )

    if not cfg.api_key and not cfg.fallback_api_key:
        print("   ⚠️  No API key, using offline mode")
        return (
            offline_summary(articles)
            if summary_limit == 10
            else offline_summary(articles, limit=summary_limit)
        )

    try:
        result = summarize_result(articles, stream=True, deadline_at=deadline_at)
        validate_summary_result(result, articles, max_items=summary_limit)
        return render_summary_markdown(result)
    except Exception as exc:
        message = (
            "AI summarization failed quality checks; refusing to publish "
            "an offline fallback because Chinese summary quality cannot be guaranteed."
        )
        print(f"   ❌  {message} Cause: {exc}")
        raise RuntimeError(message) from exc


def summarize_with_result(
    articles: list[dict], *, offline: bool, cfg, deadline_at=None
):
    """Return rendered content plus the structured result used to publish it."""
    from summarizer import offline_summary_result

    summary_limit = max(1, int(getattr(cfg, "max_summary_items", 10)))

    if offline or (not cfg.api_key and not cfg.fallback_api_key):
        content = (
            offline_summary(articles)
            if summary_limit == 10
            else offline_summary(articles, limit=summary_limit)
        )
        result = offline_summary_result(articles, limit=summary_limit)
        validate_summary_result(result, articles, max_items=summary_limit)
        return content, result
    try:
        result = summarize_result(articles, stream=True, deadline_at=deadline_at)
        validate_summary_result(result, articles, max_items=summary_limit)
        return render_summary_markdown(result), result
    except Exception as exc:
        message = (
            "AI summarization failed quality checks; refusing to publish "
            "an offline fallback because Chinese summary quality cannot be guaranteed."
        )
        print(f"   ❌  {message} Cause: {exc}")
        raise RuntimeError(message) from exc


def cmd_run(args):
    """Full pipeline: fetch → summarize → build"""
    cfg = get_config()
    clock = create_run_clock(cfg)
    try:
        date_str = today_ymd(clock)
    except TypeError:  # Compatibility with legacy helper/test doubles.
        date_str = today_ymd()
    manifest, workspace = create_run_observer(cfg, clock)

    print(f"🚀 Daily Report - {date_str}")
    print("=" * 50)

    # 1. Fetch
    print("\n📡 Fetching news...")
    source_results = ()
    try:
        articles, source_results = fetch_batch(
            enabled_sources=resolve_enabled_sources(cfg, args),
            max_articles=cfg.max_articles,
            syft_url=cfg.syft_web_app_url,
            syft_key=cfg.syft_secret_key,
            agihunt_api_key=getattr(cfg, "agihunt_api_key", ""),
            agihunt_settings=getattr(cfg, "agihunt", None),
            agihunt_max_articles=getattr(
                getattr(cfg, "agihunt", None), "max_articles", None
            ),
            agihunt_trending_settings=getattr(cfg, "agihunt_trending", None),
            agihunt_trending_max_articles=getattr(
                getattr(cfg, "agihunt_trending", None), "max_articles", None
            ),
            reference_dt=clock.cutoff_at,
            deadline_at=clock.deadline_at,
        )
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise
    manifest = update_run_observer(
        workspace.manifest_path,
        manifest,
        stages=(StageResult(name="fetch", status="ok", started_at=clock.started_at),),
        sources=source_results,
    )

    # 2. Dedupe
    print(f"\n🔄 Deduplicating {len(articles)} articles...")
    articles = dedupe(articles)
    print(f"   Remaining: {len(articles)} unique articles")

    articles_dict = [a.to_dict() if isinstance(a, Article) else a for a in articles]
    try:
        enrichment_result = apply_enrichment(cfg, args, articles_dict, date_str, clock)
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise
    articles_dict = enrichment_result["articles"]

    # 3. Summarize
    print("\n🤖 Generating summary...")
    try:
        content, summary_result = summarize_with_result(
            articles_dict,
            offline=args.offline,
            cfg=cfg,
            deadline_at=clock.deadline_at,
        )
        persist_summary_result(workspace, summary_result)
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise

    # 4. Build Markdown title
    try:
        title_date = today_cn(clock)
    except TypeError:  # Compatibility with legacy helper/test doubles.
        title_date = today_cn()
    title = f"🔥（{title_date}）每日AI资讯一览✨"
    full_content = compose_report_content(title, content, articles_dict)

    # 5. Stage JSON, Markdown, and the complete static site, then promote.
    print("\n🏗️  Building staged site and publishing complete edition...")
    try:
        json_path, md_path = stage_and_publish_run(
            cfg,
            workspace,
            date_str,
            {
                "date": date_str,
                "articles": articles_dict,
                "enrichment": enrichment_result["report"],
                "summary": summary_result.model_dump(mode="json"),
            },
            full_content,
            source_results,
            deadline_at=clock.deadline_at,
        )
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise
    current = read_current_edition(resolve_publication_root(cfg))
    published_run_id = current.run_id if current else manifest.run_id
    degraded = any(result.status in {"failed", "degraded"} for result in source_results)
    update_run_observer(
        workspace.manifest_path,
        manifest,
        stages=manifest.stages,
        sources=source_results,
        publication=PublicationState(
            status="published",
            published_run_id=published_run_id,
            reason=(
                "already_published"
                if published_run_id != manifest.run_id
                else "source_degraded"
                if degraded
                else None
            ),
        ),
    )

    print("\n" + "=" * 50)
    print("✅ Done!")
    print(f"   Articles: {len(articles)}")
    print(f"   JSON: {json_path}")
    print(f"   Markdown: {md_path}")
    print(f"   HTML: {cfg.site_dir}/")


def cmd_fetch(args):
    """Fetch only - save to JSON"""
    cfg = get_config()
    clock = create_run_clock(cfg)
    try:
        date_str = today_ymd(clock)
    except TypeError:
        date_str = today_ymd()
    manifest, workspace = create_run_observer(cfg, clock)

    print(f"📡 Fetching news for {date_str}...")
    source_results = ()
    try:
        articles, source_results = fetch_batch(
            enabled_sources=resolve_enabled_sources(cfg, args),
            max_articles=cfg.max_articles,
            syft_url=cfg.syft_web_app_url,
            syft_key=cfg.syft_secret_key,
            agihunt_api_key=getattr(cfg, "agihunt_api_key", ""),
            agihunt_settings=getattr(cfg, "agihunt", None),
            agihunt_max_articles=getattr(
                getattr(cfg, "agihunt", None), "max_articles", None
            ),
            agihunt_trending_settings=getattr(cfg, "agihunt_trending", None),
            agihunt_trending_max_articles=getattr(
                getattr(cfg, "agihunt_trending", None), "max_articles", None
            ),
            reference_dt=clock.cutoff_at,
            deadline_at=clock.deadline_at,
        )
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise
    update_run_observer(
        workspace.manifest_path,
        manifest,
        stages=(StageResult(name="fetch", status="ok", started_at=clock.started_at),),
        sources=source_results,
    )

    articles = dedupe(articles)
    articles_dict = [a.to_dict() if isinstance(a, Article) else a for a in articles]
    try:
        enrichment_result = apply_enrichment(cfg, args, articles_dict, date_str, clock)
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise
    articles_dict = enrichment_result["articles"]

    try:
        json_path = save_json(
            cfg.data_dir,
            date_str,
            {
                "date": date_str,
                "articles": articles_dict,
                "enrichment": enrichment_result["report"],
            },
        )
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, sources=source_results, error=exc)
        raise

    print(f"✅ Saved {len(articles_dict)} articles to {json_path}")


def cmd_summarize(args):
    """Summarize only - from existing JSON"""
    cfg = get_config()
    clock = create_run_clock(cfg)
    try:
        date_str = today_ymd(clock)
    except TypeError:
        date_str = today_ymd()
    _manifest, workspace = create_run_observer(cfg, clock)

    current = read_current_edition(resolve_publication_root(cfg))
    data_dir = current.data_dir if current else Path(cfg.data_dir)
    data = load_json(data_dir, date_str)
    # `fetch` writes a replay checkpoint before promotion, so allow the
    # following `summarize` command to consume that same-day root checkpoint
    # even when the current public edition is still yesterday's edition.
    if not data and current and data_dir != Path(cfg.data_dir):
        data = load_json(Path(cfg.data_dir), date_str)
    if not data:
        print(f"❌ No data found for {date_str}")
        record_blocked_run(
            cfg,
            workspace,
            _manifest,
            error=FileNotFoundError(f"no data found for {date_str}"),
        )
        raise FileNotFoundError(f"no data found for {date_str}")

    articles = dedupe(data.get("articles", []))
    print(f"🤖 Summarizing {len(articles)} articles...")

    try:
        content, summary_result = summarize_with_result(
            articles,
            offline=args.offline,
            cfg=cfg,
            deadline_at=clock.deadline_at,
        )
    except Exception as exc:
        record_blocked_run(cfg, workspace, _manifest, error=exc)
        raise

    try:
        title_date = today_cn(clock)
    except TypeError:
        title_date = today_cn()
    title = f"🔥（{title_date}）每日AI资讯一览✨"
    full_content = compose_report_content(title, content, articles)

    report = dict(data)
    report["articles"] = articles
    report["summary"] = summary_result.model_dump(mode="json")
    try:
        _json_path, md_path = stage_and_publish_run(
            cfg,
            workspace,
            date_str,
            report,
            full_content,
            deadline_at=clock.deadline_at,
        )
        persist_summary_result(workspace, summary_result)
    except Exception as exc:
        record_blocked_run(cfg, workspace, _manifest, error=exc)
        raise
    current = read_current_edition(resolve_publication_root(cfg))
    update_run_observer(
        workspace.manifest_path,
        _manifest,
        publication=PublicationState(
            status="published",
            published_run_id=current.run_id if current else _manifest.run_id,
            reason="summary_recovery",
        ),
    )
    print(f"✅ Saved to {md_path}")


def cmd_build(args):
    """Build HTML site only"""
    cfg = get_config()
    clock = create_run_clock(cfg)
    manifest, workspace = create_run_observer(cfg, clock)
    print("🏗️  Building HTML site...")
    try:
        edition = rebuild_current_site(cfg, clock, workspace)
    except Exception as exc:
        record_blocked_run(cfg, workspace, manifest, error=exc)
        raise
    update_run_observer(
        workspace.manifest_path,
        manifest,
        publication=PublicationState(
            status="published",
            published_run_id=edition.run_id,
            reason="site_rebuild",
        ),
    )


def cmd_test(args):
    """Test API connection"""
    cfg = get_config()
    create_run_observer(cfg, create_run_clock(cfg))
    test_connection()


def main():
    parser = argparse.ArgumentParser(
        description="Daily Report Site - AI News Aggregator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # run command
    p_run = subparsers.add_parser(
        "run", help="Full pipeline: fetch → summarize → build"
    )
    p_run.add_argument(
        "--offline", action="store_true", help="Use offline summarization"
    )
    p_run.add_argument(
        "--enrichment",
        choices=("auto", "on", "off"),
        default="auto",
        help="Enable, disable, or follow config for Tavily enrichment",
    )
    p_run.add_argument(
        "--agihunt",
        choices=("auto", "on", "off"),
        default="auto",
        help="Enable, disable, or follow config for the AGIHunt source",
    )
    p_run.add_argument(
        "--agihunt-trending",
        choices=("auto", "on", "off"),
        default="auto",
        help="Enable, disable, or follow config for AGI Hunt Trending",
    )
    p_run.set_defaults(func=cmd_run)

    # fetch command
    p_fetch = subparsers.add_parser("fetch", help="Fetch news only")
    p_fetch.add_argument(
        "--enrichment",
        choices=("auto", "on", "off"),
        default="auto",
        help="Enable, disable, or follow config for Tavily enrichment",
    )
    p_fetch.add_argument(
        "--agihunt",
        choices=("auto", "on", "off"),
        default="auto",
        help="Enable, disable, or follow config for the AGIHunt source",
    )
    p_fetch.add_argument(
        "--agihunt-trending",
        choices=("auto", "on", "off"),
        default="auto",
        help="Enable, disable, or follow config for AGI Hunt Trending",
    )
    p_fetch.set_defaults(func=cmd_fetch)

    # summarize command
    p_sum = subparsers.add_parser("summarize", help="Summarize from existing JSON")
    p_sum.add_argument(
        "--offline", action="store_true", help="Use offline summarization"
    )
    p_sum.set_defaults(func=cmd_summarize)

    # build command
    p_build = subparsers.add_parser("build", help="Build HTML site only")
    p_build.set_defaults(func=cmd_build)

    # test command
    p_test = subparsers.add_parser("test", help="Test API connection")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
