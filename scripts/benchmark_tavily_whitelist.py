"""
Benchmark candidate trusted domains for Tavily refill searches.

This script compares overlapping and non-overlapping domains under the same
Tavily refill-style queries so we can make a data-backed whitelist decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark_tavily import (  # noqa: E402
    OUTPUT_DATE_FORMAT,
    REPORT_TIMEZONE,
    avg,
    build_existing_report_index,
    canonical_url,
    domain_of,
    load_api_key,
    load_reports,
    normalize_title,
    report_reference_dt,
    report_window,
    safe_round,
    search_tavily,
    within_24h,
)
import requests  # noqa: E402

STRICT_AI_TITLE_RE = re.compile(
    r"\b(ai|openai|anthropic|claude|chatgpt|llm|agent|agents|"
    r"assistant|copilot|sora|generative|inference|developer tools|"
    r"machine learning|deep learning|robot|robotics)\b|"
    r"(人工智能|大模型|模型|智能体|机器人|开发者工具|生成式AI|生成式人工智能)",
    re.IGNORECASE,
)

ENGLISH_CASES = [
    {
        "case_id": "en_broad_latest",
        "report_date": "2026-03-25",
        "query": "OpenAI Anthropic AI model launch startup funding developer tools",
        "language": "en",
    },
    {
        "case_id": "en_agents_latest",
        "report_date": "2026-03-25",
        "query": "Anthropic Claude Code AI agent developer tools",
        "language": "en",
    },
    {
        "case_id": "en_broad_prior",
        "report_date": "2026-03-24",
        "query": "AI model launch developer tools OpenAI Anthropic funding",
        "language": "en",
    },
]

CHINESE_CASES = [
    {
        "case_id": "zh_broad_latest",
        "report_date": "2026-03-24",
        "query": "人工智能 模型 发布 智能体 开发者 工具 新闻",
        "language": "zh",
    },
    {
        "case_id": "zh_broad_prior",
        "report_date": "2026-03-23",
        "query": "人工智能 模型 发布 智能体 开发者 工具 新闻",
        "language": "zh",
    },
]

CANDIDATE_DOMAINS = [
    {
        "domain": "techcrunch.com",
        "label": "TechCrunch",
        "family": "media",
        "source_key": "techcrunch",
        "case_group": "en",
    },
    {
        "domain": "www.theverge.com",
        "label": "The Verge",
        "family": "media",
        "source_key": "theverge",
        "case_group": "en",
    },
    {
        "domain": "news.aibase.com",
        "label": "AIBase",
        "family": "aggregate",
        "source_key": "aibase",
        "case_group": "zh",
    },
    {
        "domain": "venturebeat.com",
        "label": "VentureBeat",
        "family": "media",
        "source_key": None,
        "case_group": "en",
    },
    {
        "domain": "thenextweb.com",
        "label": "The Next Web",
        "family": "media",
        "source_key": None,
        "case_group": "en",
    },
    {
        "domain": "arstechnica.com",
        "label": "Ars Technica",
        "family": "media",
        "source_key": None,
        "case_group": "en",
    },
    {
        "domain": "reuters.com",
        "label": "Reuters",
        "family": "wire",
        "source_key": None,
        "case_group": "en",
    },
    {
        "domain": "openai.com",
        "label": "OpenAI",
        "family": "official",
        "source_key": None,
        "case_group": "en",
    },
    {
        "domain": "anthropic.com",
        "label": "Anthropic",
        "family": "official",
        "source_key": None,
        "case_group": "en",
    },
    {
        "domain": "blog.google",
        "label": "Google Blog",
        "family": "official",
        "source_key": None,
        "case_group": "en",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Tavily trusted domain candidates"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config-path", default="config.yaml")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--request-timeout", type=int, default=45)
    parser.add_argument(
        "--domains",
        default="",
        help="Optional comma-separated domain subset to benchmark",
    )
    parser.add_argument("--output", default="")
    return parser.parse_args()


def default_output_path(explicit_output: str) -> Path:
    if explicit_output:
        return Path(explicit_output).resolve()
    filename = (
        f"tavily-whitelist-{datetime.now(tz=REPORT_TIMEZONE).date().isoformat()}.json"
    )
    return (REPO_ROOT / "data" / "benchmarks" / filename).resolve()


def parse_domain_filters(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    filters: list[str] = []
    seen: set[str] = set()
    for part in raw_value.split(","):
        domain = part.strip().lower()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        filters.append(domain)
    return filters


def select_candidate_domains(domain_filters: list[str]) -> list[dict[str, Any]]:
    if not domain_filters:
        return CANDIDATE_DOMAINS
    domain_filter_set = set(domain_filters)
    selected = [
        meta
        for meta in CANDIDATE_DOMAINS
        if meta["domain"].lower() in domain_filter_set
    ]
    selected_domains = {meta["domain"].lower() for meta in selected}
    unknown = [domain for domain in domain_filters if domain not in selected_domains]
    if unknown:
        raise ValueError(f"Unknown domain filters: {', '.join(unknown)}")
    return selected


def load_enabled_sources(config_path: Path) -> dict[str, bool]:
    if not config_path.exists():
        return {}
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return payload.get("sources", {}) or {}


def observed_source_counts(
    reports: dict[datetime.date, dict[str, Any]],
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for payload in reports.values():
        for article in payload.get("articles", []):
            source = article.get("source")
            if source:
                counter[source] += 1
    return counter


def load_phase0_valid_domains() -> set[str]:
    path = REPO_ROOT / "data" / "benchmarks" / "tavily-baseline-2026-04-01.json"
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    domains = (
        payload.get("summary", {})
        .get("groups", {})
        .get("refill_topic::advanced", {})
        .get(
            "valid_domain_frequency",
            {},
        )
    )
    return {domain.lower() for domain in domains}


def ai_title_relevant(title: str) -> bool:
    return bool(STRICT_AI_TITLE_RE.search(title or ""))


def applicable_cases(case_group: str) -> list[dict[str, Any]]:
    if case_group == "zh":
        return CHINESE_CASES
    return ENGLISH_CASES


def evaluate_case(
    *,
    domain_meta: dict[str, Any],
    case: dict[str, Any],
    reports: dict[datetime.date, dict[str, Any]],
    response_payload: dict[str, Any],
    latency_ms: float,
    max_results: int,
) -> dict[str, Any]:
    report_date = datetime.strptime(case["report_date"], OUTPUT_DATE_FORMAT).date()
    reference_dt = report_reference_dt(report_date)
    existing = build_existing_report_index(reports[report_date])
    results = response_payload.get("results", []) or []

    published_count = 0
    within_count = 0
    ai_title_count = 0
    duplicate_existing_count = 0
    unique_valid_count = 0
    seen_titles: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for index, result in enumerate(results, start=1):
        title = result.get("title", "")
        url = result.get("url", "")
        normalized_title = normalize_title(title)
        result_url = canonical_url(url)
        duplicate_existing = (
            normalized_title in existing["titles"] or result_url in existing["urls"]
        )
        duplicate_within_results = normalized_title in seen_titles
        seen_titles.add(normalized_title)

        published_date = result.get("published_date")
        has_published_date = bool(published_date)
        if has_published_date:
            published_count += 1

        is_within = within_24h(published_date, reference_dt)
        if is_within:
            within_count += 1

        ai_relevant = ai_title_relevant(title)
        if ai_relevant:
            ai_title_count += 1

        if duplicate_existing:
            duplicate_existing_count += 1

        unique_valid = (
            bool(is_within)
            and ai_relevant
            and not duplicate_existing
            and not duplicate_within_results
        )
        if unique_valid:
            unique_valid_count += 1

        candidates.append(
            {
                "rank": index,
                "title": title,
                "url": url,
                "domain": domain_of(url),
                "published_date": published_date,
                "within_24h": is_within,
                "ai_title_relevant": ai_relevant,
                "duplicate_existing": duplicate_existing,
                "duplicate_within_results": duplicate_within_results,
                "unique_valid_candidate": unique_valid,
                "score": result.get("score"),
            }
        )

    return {
        "domain": domain_meta["domain"],
        "label": domain_meta["label"],
        "family": domain_meta["family"],
        "source_key": domain_meta.get("source_key"),
        "case_id": case["case_id"],
        "report_date": case["report_date"],
        "query": case["query"],
        "language": case["language"],
        "search_depth": "advanced",
        "topic": "news",
        "max_results": max_results,
        "latency_ms": latency_ms,
        "tavily_response_time": response_payload.get("response_time"),
        "request_id": response_payload.get("request_id"),
        "result_count": len(results),
        "published_date_availability": safe_round(
            (published_count / len(results)) if results else None
        ),
        "within_24h_count": within_count,
        "within_24h_rate": safe_round(
            (within_count / len(results)) if results else None
        ),
        "ai_title_count": ai_title_count,
        "ai_title_rate": safe_round(
            (ai_title_count / len(results)) if results else None
        ),
        "duplicate_existing_count": duplicate_existing_count,
        "duplicate_existing_rate": safe_round(
            (duplicate_existing_count / len(results)) if results else None
        ),
        "unique_valid_count": unique_valid_count,
        "unique_valid_rate": safe_round(
            (unique_valid_count / len(results)) if results else None
        ),
        "candidate_results": candidates,
        "error": None,
    }


def failed_case(
    *,
    domain_meta: dict[str, Any],
    case: dict[str, Any],
    max_results: int,
    error: str,
) -> dict[str, Any]:
    return {
        "domain": domain_meta["domain"],
        "label": domain_meta["label"],
        "family": domain_meta["family"],
        "source_key": domain_meta.get("source_key"),
        "case_id": case["case_id"],
        "report_date": case["report_date"],
        "query": case["query"],
        "language": case["language"],
        "search_depth": "advanced",
        "topic": "news",
        "max_results": max_results,
        "latency_ms": None,
        "tavily_response_time": None,
        "request_id": None,
        "result_count": 0,
        "published_date_availability": None,
        "within_24h_count": 0,
        "within_24h_rate": None,
        "ai_title_count": 0,
        "ai_title_rate": None,
        "duplicate_existing_count": 0,
        "duplicate_existing_rate": None,
        "unique_valid_count": 0,
        "unique_valid_rate": None,
        "candidate_results": [],
        "error": error,
    }


def summarize_domain(
    runs: list[dict[str, Any]],
    domain_meta: dict[str, Any],
    enabled_sources: dict[str, bool],
    recent_source_counts: Counter[str],
    phase0_valid_domains: set[str],
) -> dict[str, Any]:
    successful = [run for run in runs if not run.get("error")]
    latencies = [
        run["latency_ms"] for run in successful if run.get("latency_ms") is not None
    ]
    result_counts = [run["result_count"] for run in successful]
    published = [
        run["published_date_availability"]
        for run in successful
        if run.get("published_date_availability") is not None
    ]
    within_rates = [
        run["within_24h_rate"]
        for run in successful
        if run.get("within_24h_rate") is not None
    ]
    ai_rates = [
        run["ai_title_rate"]
        for run in successful
        if run.get("ai_title_rate") is not None
    ]
    duplicate_counts = [run["duplicate_existing_count"] for run in successful]
    unique_valid_counts = [run["unique_valid_count"] for run in successful]
    unique_titles: list[str] = []
    for run in successful:
        for candidate in run.get("candidate_results", []):
            if candidate.get("unique_valid_candidate"):
                title = candidate.get("title")
                if title and title not in unique_titles:
                    unique_titles.append(title)

    source_key = domain_meta.get("source_key")
    return {
        "domain": domain_meta["domain"],
        "label": domain_meta["label"],
        "family": domain_meta["family"],
        "source_key": source_key,
        "configured_source_enabled": enabled_sources.get(source_key, False)
        if source_key
        else False,
        "observed_recent_articles": recent_source_counts.get(source_key, 0)
        if source_key
        else 0,
        "appeared_in_phase0_ungated_valid_domains": domain_meta["domain"].lower()
        in phase0_valid_domains,
        "run_count": len(runs),
        "success_count": len(successful),
        "failure_count": len(runs) - len(successful),
        "avg_latency_ms": avg(latencies),
        "avg_result_count": avg(result_counts),
        "avg_published_date_availability": avg(published),
        "avg_within_24h_rate": avg(within_rates),
        "avg_ai_title_rate": avg(ai_rates),
        "avg_duplicate_existing_count": avg(duplicate_counts),
        "avg_unique_valid_count": avg(unique_valid_counts),
        "total_unique_valid_count": sum(unique_valid_counts),
        "sample_unique_valid_titles": unique_titles[:5],
    }


def build_markdown_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Tavily Trusted Domains Research",
        "",
        "## Scope",
        "",
        "- Focused on `trusted_domains` for Tavily refill, not production integration.",
        "- Compared overlapping domains, non-overlapping media, and official vendor blogs under the same refill-style queries.",
    ]
    selected_domains = payload.get("selected_domains") or []
    if selected_domains:
        lines.append(
            f"- This run used a filtered experimental domain subset: {', '.join(selected_domains)}."
        )
    lines.extend(
        [
            "",
            "## Domain Summary",
            "",
            "| Domain | Family | Configured Source | Observed Recent Articles | Avg Unique Valid / Run | Avg Published Date Availability | Avg AI Title Rate | Avg Duplicate Existing / Run |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for summary in payload["domain_summaries"]:
        lines.append(
            f"| {summary['domain']} | {summary['family']} | "
            f"{'yes' if summary['configured_source_enabled'] else 'no'} | "
            f"{summary['observed_recent_articles']} | "
            f"{summary['avg_unique_valid_count'] if summary['avg_unique_valid_count'] is not None else 'n/a'} | "
            f"{summary['avg_published_date_availability'] if summary['avg_published_date_availability'] is not None else 'n/a'} | "
            f"{summary['avg_ai_title_rate'] if summary['avg_ai_title_rate'] is not None else 'n/a'} | "
            f"{summary['avg_duplicate_existing_count'] if summary['avg_duplicate_existing_count'] is not None else 'n/a'} |"
        )
    lines.extend(["", "## Notes", ""])
    for note in payload["research_notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    api_key = load_api_key()
    data_dir = (REPO_ROOT / args.data_dir).resolve()
    reports = load_reports(data_dir)
    enabled_sources = load_enabled_sources((REPO_ROOT / args.config_path).resolve())
    recent_counts = observed_source_counts(reports)
    phase0_valid_domains = load_phase0_valid_domains()
    domain_filters = parse_domain_filters(args.domains)
    candidate_domains = select_candidate_domains(domain_filters)

    session = requests.Session()
    runs: list[dict[str, Any]] = []

    for domain_meta in candidate_domains:
        for case in applicable_cases(domain_meta["case_group"]):
            report_date = datetime.strptime(
                case["report_date"], OUTPUT_DATE_FORMAT
            ).date()
            start_date, end_date = report_window(report_date)
            payload = {
                "query": case["query"],
                "topic": "news",
                "search_depth": "advanced",
                "max_results": args.max_results,
                "include_answer": False,
                "include_images": False,
                "include_raw_content": False,
                "auto_parameters": False,
                "include_domains": [domain_meta["domain"]],
                "start_date": start_date,
                "end_date": end_date,
            }
            try:
                result = search_tavily(session, api_key, payload, args.request_timeout)
                runs.append(
                    evaluate_case(
                        domain_meta=domain_meta,
                        case=case,
                        reports=reports,
                        response_payload=result["response"],
                        latency_ms=result["latency_ms"],
                        max_results=args.max_results,
                    )
                )
            except Exception as exc:
                runs.append(
                    failed_case(
                        domain_meta=domain_meta,
                        case=case,
                        max_results=args.max_results,
                        error=str(exc),
                    )
                )

    domain_summaries = []
    for domain_meta in candidate_domains:
        domain_runs = [run for run in runs if run["domain"] == domain_meta["domain"]]
        domain_summaries.append(
            summarize_domain(
                domain_runs,
                domain_meta,
                enabled_sources,
                recent_counts,
                phase0_valid_domains,
            )
        )

    domain_summaries.sort(
        key=lambda item: (
            item["avg_unique_valid_count"]
            if item["avg_unique_valid_count"] is not None
            else -1,
            item["avg_published_date_availability"]
            if item["avg_published_date_availability"] is not None
            else -1,
        ),
        reverse=True,
    )

    research_notes = [
        "High overlap domains reduce refill value when the same source is already present in the current report.",
        "Official vendor blogs were sparse and often had missing or unstable published_date metadata in Tavily results.",
        "Aggregate digest domains may return on-topic items, but they are a weak fit for strict article-level verification.",
        "Non-overlap editorial tech media should be judged by unique valid candidates per run, not by raw result_count alone.",
    ]

    return {
        "generated_at": datetime.now(tz=REPORT_TIMEZONE).isoformat(),
        "focus": "trusted_domains whitelist research",
        "candidate_domains": candidate_domains,
        "selected_domains": [meta["domain"] for meta in candidate_domains],
        "cases": {
            "en": ENGLISH_CASES,
            "zh": CHINESE_CASES,
        },
        "runs": runs,
        "domain_summaries": domain_summaries,
        "research_notes": research_notes,
    }


def main() -> None:
    args = parse_args()
    payload = run_benchmark(args)
    output_path = default_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    markdown_path = output_path.with_suffix(".md")
    markdown_path.write_text(build_markdown_summary(payload), encoding="utf-8")

    print(f"Whitelist benchmark written to: {output_path}")
    print(f"Markdown summary written to: {markdown_path}")
    for summary in payload["domain_summaries"]:
        print(
            summary["domain"],
            json.dumps(
                {
                    "family": summary["family"],
                    "avg_unique_valid_count": summary["avg_unique_valid_count"],
                    "avg_published_date_availability": summary[
                        "avg_published_date_availability"
                    ],
                    "avg_ai_title_rate": summary["avg_ai_title_rate"],
                    "avg_duplicate_existing_count": summary[
                        "avg_duplicate_existing_count"
                    ],
                    "observed_recent_articles": summary["observed_recent_articles"],
                },
                ensure_ascii=False,
            ),
        )


if __name__ == "__main__":
    main()
