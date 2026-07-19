"""Small, deterministic gates between discovery leads and publishable stories."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


_SPACE_RE = re.compile(r"\s+")
_NON_EVIDENCE_HOSTS = {
    "agihunt.info",
    "www.agihunt.info",
    "news.google.com",
}
_SOCIAL_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "reddit.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}


def compact_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def canonical_story_url(value: str) -> str:
    """Return a stable exact-story URL key without tracking parameters."""

    try:
        parsed = urlparse(compact_text(value))
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = (parsed.path or "/").rstrip("/") or "/"
    return f"{parsed.netloc.lower().removeprefix('www.')}{path}"


def is_direct_evidence_url(value: str) -> bool:
    """Reject search, ranking, homepage and social URLs as story evidence."""

    try:
        parsed = urlparse(compact_text(value))
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if hostname in _SOCIAL_HOSTS or any(
        hostname.endswith(f".{domain}") for domain in _SOCIAL_HOSTS
    ):
        return False
    if hostname in _NON_EVIDENCE_HOSTS:
        query = parse_qs(parsed.query)
        return (
            hostname.endswith("agihunt.info")
            and (parsed.path or "/") not in {"", "/"}
            and not ({"t", "day"} & query.keys())
        )
    return (parsed.path or "/") not in {"", "/"}


def _has_real_publish_time(article: dict[str, Any]) -> bool:
    provenance = article.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if provenance.get("publish_time_semantics") == "trend_observed_at":
        return False
    value = compact_text(article.get("publish_time"))
    if not value or value.lower() in {"unknown", "未知", "未知时间", "none"}:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            # Tavily news results commonly use RFC 2822 dates such as
            # ``Sat, 18 Jul 2026 20:54:42 GMT``.  They are real source times,
            # not trend observation timestamps, so accept them explicitly.
            parsedate_to_datetime(value)
        except (TypeError, ValueError):
            try:
                datetime.strptime(value[:10], "%Y-%m-%d")
            except ValueError:
                return False
    return True


def article_is_lead(article: dict[str, Any]) -> bool:
    """Classify explicit signals and title-only records as discovery leads."""

    if compact_text(article.get("kind")).lower() == "lead":
        return True
    provenance = article.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    if provenance.get("input_kind") == "lead":
        return True
    if provenance.get("publish_time_semantics") == "trend_observed_at":
        return True
    evidence_text = compact_text(article.get("description")) or compact_text(
        article.get("content")
    )
    # TechCrunch's homepage adapter intentionally yields title-only records;
    # other direct adapters and external callers retain legacy compatibility.
    return not evidence_text and compact_text(article.get("source")).lower() in {
        "techcrunch"
    }


def publishability_reasons(article: dict[str, Any]) -> tuple[str, ...]:
    """Explain why a candidate cannot enter the main-news shortlist."""

    reasons: list[str] = []
    if article_is_lead(article):
        reasons.append("unresolved_lead")
    if not compact_text(article.get("title")):
        reasons.append("missing_title")
    if not is_direct_evidence_url(compact_text(article.get("link"))):
        reasons.append("non_evidence_url")
    if not _has_real_publish_time(article):
        reasons.append("missing_real_publish_time")
    if article_is_lead(article) and not (
        compact_text(article.get("description")) or compact_text(article.get("content"))
    ):
        reasons.append("missing_evidence_text")
    return tuple(dict.fromkeys(reasons))


def partition_articles_for_publication(
    articles: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Separate publishable stories, resolvable leads and rejected records."""

    stories: list[dict[str, Any]] = []
    leads: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for article in articles:
        item = dict(article)
        reasons = publishability_reasons(item)
        if not reasons:
            stories.append(item)
            continue
        if "unresolved_lead" in reasons:
            leads.append(item)
            continue
        # A record with a usable title can still be resolved by Tavily even if
        # its source adapter omitted body text, time, or a direct story URL.
        if compact_text(item.get("title")):
            item["kind"] = "lead"
            item["evidence_status"] = "unresolved"
            item["confidence"] = "signal"
            leads.append(item)
            continue
        rejected.append(
            {
                "title": compact_text(item.get("title")),
                "source": compact_text(item.get("source")),
                "reasons": list(reasons),
            }
        )
    return {"stories": stories, "leads": leads, "rejected": rejected}


def observation_signal(lead: dict[str, Any], reason: str) -> dict[str, str]:
    return {
        "title": compact_text(lead.get("title")),
        "source": compact_text(lead.get("source")),
        "signal_url": compact_text(lead.get("link")),
        "reason": reason,
    }


def remove_recent_exact_duplicates(
    articles: list[dict[str, Any]],
    *,
    data_dir: str | Path,
    report_date: str,
    window_days: int = 3,
) -> dict[str, Any]:
    """Remove exact URLs selected in recent editions; never fuzzy-drop updates."""

    try:
        current_day = date.fromisoformat(report_date)
    except ValueError:
        return {"articles": list(articles), "removed": [], "checked_days": []}

    directory = Path(data_dir)
    recent_urls: set[str] = set()
    checked_days: list[str] = []
    for offset in range(1, max(0, window_days) + 1):
        day = current_day - timedelta(days=offset)
        path = directory / f"{day.isoformat()}.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        checked_days.append(day.isoformat())
        summary = payload.get("summary") if isinstance(payload, dict) else None
        items = summary.get("items", []) if isinstance(summary, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            canonical = canonical_story_url(str(item.get("url") or ""))
            if canonical:
                recent_urls.add(canonical)

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, str]] = []
    for article in articles:
        canonical = canonical_story_url(str(article.get("link") or ""))
        if canonical and canonical in recent_urls:
            removed.append(
                {
                    "title": compact_text(article.get("title")),
                    "url_key": canonical,
                    "reason": "recent_exact_url",
                }
            )
            continue
        kept.append(article)
    return {"articles": kept, "removed": removed, "checked_days": checked_days}
