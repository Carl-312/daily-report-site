"""
Phase 0 benchmark for Tavily-based news verification and refill quality.

This script intentionally does not implement production integration.
It benchmarks the current Tavily Search API against historical project data
and writes a structured JSON report under ``data/benchmarks/``.
"""

from __future__ import annotations

import argparse
from email.utils import parsedate_to_datetime
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, time as dt_time, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import config  # noqa: E402  # Reuse project .env loading behavior.

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
OUTPUT_DATE_FORMAT = "%Y-%m-%d"
DEPLOY_HOUR = 21
DEPLOY_MINUTE = 19
REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
TITLE_SIMILARITY_MATCH_THRESHOLD = 0.82
AI_KEYWORD_RE = re.compile(
    r"\b(ai|openai|anthropic|claude|chatgpt|llm|model|models|agent|agents|robot|"
    r"robotics|startup|startups|copilot|sora)\b|"
    r"(人工智能|大模型|模型|智能体|机器人|融资|开源|发布|日报)",
    re.IGNORECASE,
)
NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 0 Tavily benchmark")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory with historical report JSON files",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional explicit output path for the benchmark JSON",
    )
    parser.add_argument(
        "--verify-samples",
        type=int,
        default=4,
        help="Number of verification seed articles to benchmark",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=45,
        help="HTTP timeout in seconds for each Tavily request",
    )
    return parser.parse_args()


def load_api_key() -> str:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing TAVILY_API_KEY in environment/.env")
    return key


def normalize_title(title: str) -> str:
    cleaned = NON_WORD_RE.sub(" ", (title or "").strip().lower())
    return SPACE_RE.sub(" ", cleaned).strip()


def title_similarity(left: str, right: str) -> float:
    return round(SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio(), 4)


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def canonical_url(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return ""
    netloc = parsed.netloc.lower()
    path = (parsed.path or "").rstrip("/")
    return f"{netloc}{path}"


def parse_published_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=REPORT_TIMEZONE)
    return parsed.astimezone(REPORT_TIMEZONE)


def report_reference_dt(report_date: date) -> datetime:
    return datetime.combine(
        report_date,
        dt_time(hour=DEPLOY_HOUR, minute=DEPLOY_MINUTE),
        tzinfo=REPORT_TIMEZONE,
    )


def report_window(report_date: date) -> tuple[str, str]:
    return ((report_date - timedelta(days=1)).isoformat(), report_date.isoformat())


def within_24h(published_date: str | None, reference_dt: datetime) -> bool | None:
    published_dt = parse_published_datetime(published_date)
    if published_dt is None:
        return None
    earliest = reference_dt - timedelta(hours=24)
    return earliest <= published_dt <= reference_dt


def avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def safe_round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def load_reports(data_dir: Path) -> dict[date, dict[str, Any]]:
    reports: dict[date, dict[str, Any]] = {}
    for path in sorted(data_dir.glob("*.json")):
        try:
            report_date = datetime.strptime(path.stem, OUTPUT_DATE_FORMAT).date()
        except ValueError:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports[report_date] = payload
    if not reports:
        raise RuntimeError(f"No report JSON files found under {data_dir}")
    return reports


def matches_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(needle in lowered for needle in needles)


def select_verify_samples(
    reports: dict[date, dict[str, Any]],
    verify_samples: int,
) -> list[dict[str, Any]]:
    recent_dates = sorted(reports.keys(), reverse=True)
    selectors: list[tuple[str, tuple[str, ...], str | None]] = [
        ("openai_case", ("openai", "sora"), "techcrunch"),
        ("anthropic_case", ("anthropic", "claude"), "techcrunch"),
        ("ai_case", (" ai ", "copilot", "model"), "techcrunch"),
        ("aibase_daily_case", ("ai日报",), "aibase"),
    ]
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def pick_one(
        selector_id: str,
        needles: tuple[str, ...],
        source: str | None,
    ) -> None:
        for report_date in recent_dates:
            for article in reports[report_date].get("articles", []):
                title = article.get("title", "")
                link = article.get("link", "")
                if not link or link in seen_urls:
                    continue
                if source and article.get("source") != source:
                    continue
                title_match = matches_any(f" {title.lower()} ", needles)
                if not title_match:
                    continue
                selected.append(
                    {
                        "sample_id": selector_id,
                        "report_date": report_date.isoformat(),
                        "source": article.get("source", ""),
                        "title": title,
                        "link": link,
                        "publish_time": article.get("publish_time", ""),
                        "selection_reason": selector_id,
                    }
                )
                seen_urls.add(link)
                return

    for selector_id, needles, source in selectors:
        if len(selected) >= verify_samples:
            break
        pick_one(selector_id, needles, source)

    if len(selected) < verify_samples:
        for report_date in recent_dates:
            for article in reports[report_date].get("articles", []):
                link = article.get("link", "")
                if not link or link in seen_urls:
                    continue
                selected.append(
                    {
                        "sample_id": f"fallback_{len(selected) + 1}",
                        "report_date": report_date.isoformat(),
                        "source": article.get("source", ""),
                        "title": article.get("title", ""),
                        "link": link,
                        "publish_time": article.get("publish_time", ""),
                        "selection_reason": "fallback_recent_article",
                    }
                )
                seen_urls.add(link)
                if len(selected) >= verify_samples:
                    return selected
    return selected[:verify_samples]


def build_refill_queries(verify_samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    report_dates = sorted(
        {datetime.strptime(sample["report_date"], OUTPUT_DATE_FORMAT).date() for sample in verify_samples},
        reverse=True,
    )
    latest_date = report_dates[0]
    chinese_date = next(
        (
            datetime.strptime(sample["report_date"], OUTPUT_DATE_FORMAT).date()
            for sample in verify_samples
            if sample.get("source") == "aibase"
        ),
        latest_date,
    )
    return [
        {
            "sample_id": "refill_en_latest",
            "report_date": latest_date.isoformat(),
            "query": "OpenAI Anthropic AI model launch startup funding developer tools",
            "query_type": "topic_refill_en",
            "language": "en",
        },
        {
            "sample_id": "refill_zh_recent",
            "report_date": chinese_date.isoformat(),
            "query": "人工智能 模型 发布 智能体 融资 开发者 工具 新闻",
            "query_type": "topic_refill_zh",
            "language": "zh",
        },
    ]


def build_existing_report_index(report_payload: dict[str, Any]) -> dict[str, set[str]]:
    titles = {normalize_title(article.get("title", "")) for article in report_payload.get("articles", [])}
    urls = {canonical_url(article.get("link", "")) for article in report_payload.get("articles", [])}
    domains = {domain_of(article.get("link", "")) for article in report_payload.get("articles", [])}
    return {"titles": titles, "urls": urls, "domains": domains}


def search_tavily(
    session: requests.Session,
    api_key: str,
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = session.post(
        TAVILY_SEARCH_URL,
        json={"api_key": api_key, **payload},
        timeout=timeout,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    body = response.json()
    return {
        "latency_ms": latency_ms,
        "response": body,
    }


def pick_best_match(results: list[dict[str, Any]], expected_title: str, expected_url: str) -> dict[str, Any] | None:
    expected_canonical = canonical_url(expected_url)
    expected_domain = domain_of(expected_url)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, result in enumerate(results):
        result_url = result.get("url", "")
        result_title = result.get("title", "")
        result_canonical = canonical_url(result_url)
        exact_url = expected_canonical == result_canonical and bool(expected_canonical)
        same_domain = domain_of(result_url) == expected_domain and bool(expected_domain)
        similarity = title_similarity(expected_title, result_title)
        score = (10 if exact_url else 0) + (2 if same_domain else 0) + similarity - (index * 0.01)
        ranked.append(
            (
                score,
                {
                    "rank": index + 1,
                    "title": result_title,
                    "url": result_url,
                    "exact_url_match": exact_url,
                    "same_domain": same_domain,
                    "title_similarity": similarity,
                    "published_date": result.get("published_date"),
                    "score": result.get("score"),
                },
            )
        )
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1]


def evaluate_verify_case(
    *,
    response_payload: dict[str, Any],
    sample: dict[str, Any],
    scenario: str,
    query: str,
    query_type: str,
    search_depth: str,
    max_results: int,
    started_payload: dict[str, Any],
) -> dict[str, Any]:
    results = response_payload.get("results", []) or []
    reference_dt = report_reference_dt(
        datetime.strptime(sample["report_date"], OUTPUT_DATE_FORMAT).date()
    )
    best_match = pick_best_match(results, sample["title"], sample["link"])
    published_with_values = [result for result in results if result.get("published_date")]
    matched = None
    same_domain = None
    matched_within_24h = None
    similarity_value = None
    best_rank = None
    matched_url = None
    matched_title = None
    exact_url_match = None
    if best_match:
        similarity_value = best_match["title_similarity"]
        same_domain = best_match["same_domain"]
        exact_url_match = best_match["exact_url_match"]
        matched = exact_url_match or (
            bool(same_domain) and similarity_value >= TITLE_SIMILARITY_MATCH_THRESHOLD
        )
        matched_within_24h = within_24h(best_match["published_date"], reference_dt)
        best_rank = best_match["rank"]
        matched_url = best_match["url"]
        matched_title = best_match["title"]

    return {
        "scenario": scenario,
        "sample_id": sample["sample_id"],
        "report_date": sample["report_date"],
        "reference_dt": reference_dt.isoformat(),
        "source": sample["source"],
        "target_title": sample["title"],
        "target_link": sample["link"],
        "query": query,
        "query_type": query_type,
        "topic": "news",
        "search_depth": search_depth,
        "max_results": max_results,
        "start_date": started_payload["start_date"],
        "end_date": started_payload["end_date"],
        "latency_ms": started_payload["latency_ms"],
        "tavily_response_time": response_payload.get("response_time"),
        "request_id": response_payload.get("request_id"),
        "result_count": len(results),
        "matched": matched,
        "same_domain": same_domain,
        "within_24h": matched_within_24h,
        "title_similarity": similarity_value,
        "published_date_availability": safe_round(
            (len(published_with_values) / len(results)) if results else None
        ),
        "matched_rank": best_rank,
        "matched_url": matched_url,
        "matched_title": matched_title,
        "exact_url_match": exact_url_match,
        "result_preview": [
            {
                "rank": index + 1,
                "title": result.get("title"),
                "url": result.get("url"),
                "domain": domain_of(result.get("url", "")),
                "published_date": result.get("published_date"),
                "score": result.get("score"),
                "title_similarity": title_similarity(sample["title"], result.get("title", "")),
            }
            for index, result in enumerate(results[: max_results])
        ],
        "error": None,
    }


def evaluate_refill_case(
    *,
    response_payload: dict[str, Any],
    refill_query: dict[str, Any],
    report_payload: dict[str, Any],
    search_depth: str,
    max_results: int,
    started_payload: dict[str, Any],
) -> dict[str, Any]:
    results = response_payload.get("results", []) or []
    report_date = datetime.strptime(refill_query["report_date"], OUTPUT_DATE_FORMAT).date()
    reference_dt = report_reference_dt(report_date)
    existing = build_existing_report_index(report_payload)
    seen_returned_titles: set[str] = set()
    candidate_results: list[dict[str, Any]] = []
    duplicate_count = 0
    valid_new_count = 0

    for index, result in enumerate(results, start=1):
        title = result.get("title", "")
        url = result.get("url", "")
        normalized = normalize_title(title)
        result_url = canonical_url(url)
        duplicate_existing = normalized in existing["titles"] or result_url in existing["urls"]
        duplicate_within_results = normalized in seen_returned_titles
        seen_returned_titles.add(normalized)
        duplicate = duplicate_existing or duplicate_within_results
        if duplicate:
            duplicate_count += 1
        published_ok = within_24h(result.get("published_date"), reference_dt)
        ai_relevant = bool(AI_KEYWORD_RE.search(title))
        valid_new = bool(published_ok) and ai_relevant and not duplicate
        if valid_new:
            valid_new_count += 1
        candidate_results.append(
            {
                "rank": index,
                "title": title,
                "url": url,
                "domain": domain_of(url),
                "published_date": result.get("published_date"),
                "within_24h": published_ok,
                "ai_relevant": ai_relevant,
                "duplicate_existing": duplicate_existing,
                "duplicate_within_results": duplicate_within_results,
                "duplicate": duplicate,
                "valid_new_candidate": valid_new,
                "score": result.get("score"),
            }
        )

    published_with_values = [result for result in results if result.get("published_date")]
    return {
        "scenario": "refill_topic",
        "sample_id": refill_query["sample_id"],
        "report_date": refill_query["report_date"],
        "reference_dt": reference_dt.isoformat(),
        "query": refill_query["query"],
        "query_type": refill_query["query_type"],
        "language": refill_query["language"],
        "topic": "news",
        "search_depth": search_depth,
        "max_results": max_results,
        "start_date": started_payload["start_date"],
        "end_date": started_payload["end_date"],
        "latency_ms": started_payload["latency_ms"],
        "tavily_response_time": response_payload.get("response_time"),
        "request_id": response_payload.get("request_id"),
        "result_count": len(results),
        "matched": None,
        "same_domain": None,
        "within_24h": None,
        "title_similarity": None,
        "published_date_availability": safe_round(
            (len(published_with_values) / len(results)) if results else None
        ),
        "new_valid_news_count": valid_new_count,
        "duplicate_count": duplicate_count,
        "candidate_results": candidate_results,
        "error": None,
    }


def failed_run_record(
    *,
    scenario: str,
    sample_id: str,
    report_date: str,
    query: str,
    query_type: str,
    search_depth: str,
    max_results: int,
    start_date: str,
    end_date: str,
    error: str,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "sample_id": sample_id,
        "report_date": report_date,
        "reference_dt": report_reference_dt(
            datetime.strptime(report_date, OUTPUT_DATE_FORMAT).date()
        ).isoformat(),
        "query": query,
        "query_type": query_type,
        "topic": "news",
        "search_depth": search_depth,
        "max_results": max_results,
        "start_date": start_date,
        "end_date": end_date,
        "latency_ms": None,
        "tavily_response_time": None,
        "request_id": None,
        "result_count": 0,
        "matched": None,
        "same_domain": None,
        "within_24h": None,
        "title_similarity": None,
        "published_date_availability": None,
        "new_valid_news_count": None,
        "duplicate_count": None,
        "candidate_results": [],
        "result_preview": [],
        "error": error,
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        key = f"{run['scenario']}::{run['search_depth']}"
        grouped[key].append(run)

    summary_groups: dict[str, Any] = {}
    for key, items in grouped.items():
        successful = [item for item in items if not item.get("error")]
        latencies = [item["latency_ms"] for item in successful if item.get("latency_ms") is not None]
        title_sim_values = [
            item["title_similarity"]
            for item in successful
            if item.get("title_similarity") is not None
        ]
        published_values = [
            item["published_date_availability"]
            for item in successful
            if item.get("published_date_availability") is not None
        ]
        summary: dict[str, Any] = {
            "run_count": len(items),
            "success_count": len(successful),
            "failure_count": len(items) - len(successful),
            "avg_latency_ms": avg(latencies),
            "avg_title_similarity": avg(title_sim_values),
            "avg_published_date_availability": avg(published_values),
        }
        if successful and successful[0]["scenario"] == "refill_topic":
            new_values = [
                item["new_valid_news_count"]
                for item in successful
                if item.get("new_valid_news_count") is not None
            ]
            duplicate_values = [
                item["duplicate_count"]
                for item in successful
                if item.get("duplicate_count") is not None
            ]
            valid_domains = Counter()
            for item in successful:
                for candidate in item.get("candidate_results", []):
                    if candidate.get("valid_new_candidate"):
                        valid_domains[candidate["domain"]] += 1
            summary.update(
                {
                    "avg_new_valid_news_count": avg(new_values),
                    "avg_duplicate_count": avg(duplicate_values),
                    "valid_domain_frequency": dict(valid_domains.most_common()),
                }
            )
        else:
            for metric in ("matched", "same_domain", "within_24h"):
                values = [
                    1.0 if item.get(metric) else 0.0
                    for item in successful
                    if item.get(metric) is not None
                ]
                summary[f"{metric}_rate"] = avg(values)
        summary_groups[key] = summary

    fuzzy_rescues = []
    per_sample: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for run in runs:
        if run["scenario"] not in {"verify_exact", "verify_fuzzy"}:
            continue
        per_sample[run["sample_id"]][f"{run['scenario']}::{run['search_depth']}"] = run
    for sample_id, sample_runs in per_sample.items():
        basic = sample_runs.get("verify_exact::basic")
        advanced = sample_runs.get("verify_exact::advanced")
        fuzzy = sample_runs.get("verify_fuzzy::advanced")
        if not fuzzy or fuzzy.get("error"):
            continue
        rescued = bool(fuzzy.get("matched")) and not any(
            run and run.get("matched")
            for run in (basic, advanced)
        )
        if rescued:
            fuzzy_rescues.append(sample_id)

    return {
        "groups": summary_groups,
        "fuzzy_rescue_sample_ids": fuzzy_rescues,
        "fuzzy_rescue_count": len(fuzzy_rescues),
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    api_key = load_api_key()
    data_dir = (REPO_ROOT / args.data_dir).resolve()
    reports = load_reports(data_dir)
    verify_samples = select_verify_samples(reports, args.verify_samples)
    refill_queries = build_refill_queries(verify_samples)
    session = requests.Session()

    runs: list[dict[str, Any]] = []

    for sample in verify_samples:
        report_date = datetime.strptime(sample["report_date"], OUTPUT_DATE_FORMAT).date()
        start_date, end_date = report_window(report_date)
        exact_query = f"\"{sample['title']}\""
        fuzzy_query = f"\"{sample['title']}\" AI"
        verify_matrix = [
            ("verify_exact", exact_query, "exact_title", "basic", 3),
            ("verify_exact", exact_query, "exact_title", "advanced", 3),
            ("verify_fuzzy", fuzzy_query, "fuzzy_title_ai", "advanced", 5),
        ]
        for scenario, query, query_type, search_depth, max_results in verify_matrix:
            payload = {
                "query": query,
                "topic": "news",
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": False,
                "include_images": False,
                "include_raw_content": False,
                "auto_parameters": False,
                "start_date": start_date,
                "end_date": end_date,
            }
            try:
                result = search_tavily(session, api_key, payload, args.request_timeout)
                runs.append(
                    evaluate_verify_case(
                        response_payload=result["response"],
                        sample=sample,
                        scenario=scenario,
                        query=query,
                        query_type=query_type,
                        search_depth=search_depth,
                        max_results=max_results,
                        started_payload={
                            "start_date": start_date,
                            "end_date": end_date,
                            "latency_ms": result["latency_ms"],
                        },
                    )
                )
            except Exception as exc:
                runs.append(
                    failed_run_record(
                        scenario=scenario,
                        sample_id=sample["sample_id"],
                        report_date=sample["report_date"],
                        query=query,
                        query_type=query_type,
                        search_depth=search_depth,
                        max_results=max_results,
                        start_date=start_date,
                        end_date=end_date,
                        error=str(exc),
                    )
                )

    for refill_query in refill_queries:
        report_date = datetime.strptime(refill_query["report_date"], OUTPUT_DATE_FORMAT).date()
        start_date, end_date = report_window(report_date)
        payload = {
            "query": refill_query["query"],
            "topic": "news",
            "search_depth": "advanced",
            "max_results": 8,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "auto_parameters": False,
            "start_date": start_date,
            "end_date": end_date,
        }
        try:
            result = search_tavily(session, api_key, payload, args.request_timeout)
            runs.append(
                evaluate_refill_case(
                    response_payload=result["response"],
                    refill_query=refill_query,
                    report_payload=reports[report_date],
                    search_depth="advanced",
                    max_results=8,
                    started_payload={
                        "start_date": start_date,
                        "end_date": end_date,
                        "latency_ms": result["latency_ms"],
                    },
                )
            )
        except Exception as exc:
            runs.append(
                failed_run_record(
                    scenario="refill_topic",
                    sample_id=refill_query["sample_id"],
                    report_date=refill_query["report_date"],
                    query=refill_query["query"],
                    query_type=refill_query["query_type"],
                    search_depth="advanced",
                    max_results=8,
                    start_date=start_date,
                    end_date=end_date,
                    error=str(exc),
                )
            )

    summary = summarize_runs(runs)
    return {
        "generated_at": datetime.now(tz=REPORT_TIMEZONE).isoformat(),
        "phase": "Phase 0",
        "focus": "Tavily benchmark only; no production integration",
        "docs_basis": {
            "context7_sources": [
                {
                    "library_id": "/tavily-ai/tavily-python",
                    "notes": [
                        "Validated TavilyClient search parameters before implementation",
                        "Confirmed topic='news', search_depth, max_results, start_date/end_date support",
                    ],
                },
                {
                    "library_id": "/websites/tavily",
                    "notes": [
                        "Validated Search API parameter surface and published_date field for news results",
                    ],
                },
            ],
            "runtime_observations": [
                "Current API response exposed response_time/request_id/results; time_taken/query_analysis were not present in this environment",
                "Historical replay uses the repo's documented deploy time (21:19 Asia/Shanghai) as the report reference timestamp",
                "Benchmark requests inherit HTTP(S)_PROXY because direct DNS resolution failed when proxy env inheritance was disabled",
            ],
        },
        "sample_selection": {
            "verify_samples": verify_samples,
            "refill_queries": refill_queries,
            "available_report_dates": [report_date.isoformat() for report_date in sorted(reports)],
            "source_counts": dict(
                Counter(
                    article.get("source", "")
                    for payload in reports.values()
                    for article in payload.get("articles", [])
                )
            ),
        },
        "runs": runs,
        "summary": summary,
    }


def default_output_path(explicit_output: str) -> Path:
    if explicit_output:
        return Path(explicit_output).resolve()
    filename = f"tavily-baseline-{datetime.now(tz=REPORT_TIMEZONE).date().isoformat()}.json"
    return (REPO_ROOT / "data" / "benchmarks" / filename).resolve()


def main() -> None:
    args = parse_args()
    benchmark = run_benchmark(args)
    output_path = default_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Benchmark written to: {output_path}")
    print(f"Verify samples: {len(benchmark['sample_selection']['verify_samples'])}")
    print(f"Refill queries: {len(benchmark['sample_selection']['refill_queries'])}")
    for group_name, metrics in benchmark["summary"]["groups"].items():
        print(group_name, json.dumps(metrics, ensure_ascii=False))
    print(f"Fuzzy rescue count: {benchmark['summary']['fuzzy_rescue_count']}")


if __name__ == "__main__":
    main()
