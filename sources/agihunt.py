"""Official, bounded AGIHunt Agent API source.

The adapter deliberately uses channel items as publishable candidates.  The
daily report is fetched only as a coverage/provenance diagnostic because a
single aggregate Markdown URL cannot safely back multiple published stories.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from requests.utils import get_environ_proxies

from article_identity import canonical_url, normalize_title
from config import AgihuntSettings
from utils.run_contracts import Diagnostic, RunDeadlineExceeded

from .base import Article, BaseSource


AGIHUNT_SOURCE_LABEL = "AGI HUNT · agihunt.info"
AGIHUNT_CHANNEL_HOT_FEED = "channel_hot"


class AgihuntError(RuntimeError):
    """Base class for errors that have a safe public diagnostic code."""

    diagnostic_code = "agihunt_error"
    retryable = False
    fatal = False


class AgihuntAuthenticationError(AgihuntError):
    diagnostic_code = "agihunt_authentication_failed"
    fatal = True


class AgihuntCompatibilityError(AgihuntError):
    diagnostic_code = "agihunt_skill_update_required"
    fatal = True


class AgihuntInvalidRequestError(AgihuntError):
    diagnostic_code = "agihunt_invalid_request"
    fatal = True


class AgihuntChannelNotFoundError(AgihuntError):
    diagnostic_code = "agihunt_channel_not_found"
    fatal = True


class AgihuntReportNotReadyError(AgihuntError):
    diagnostic_code = "agihunt_report_not_ready"


class AgihuntQuotaExceededError(AgihuntError):
    diagnostic_code = "agihunt_daily_quota_exceeded"


class AgihuntRequestBudgetExceededError(AgihuntError):
    diagnostic_code = "agihunt_request_budget_exhausted"


class AgihuntPayloadError(AgihuntError):
    diagnostic_code = "agihunt_invalid_payload"


class AgihuntRateLimitedError(AgihuntError):
    diagnostic_code = "agihunt_rate_limited"
    retryable = True

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("AGIHunt rate limit reached")
        self.retry_after_seconds = retry_after_seconds


class AgihuntNetworkError(AgihuntError):
    diagnostic_code = "agihunt_network_error"
    retryable = True
    retry_after_seconds = 30.0


class AgihuntServiceError(AgihuntError):
    diagnostic_code = "agihunt_service_error"
    retryable = True
    retry_after_seconds = 30.0


class AgihuntProtocolError(AgihuntError):
    diagnostic_code = "agihunt_protocol_error"


@dataclass(frozen=True, slots=True)
class AgihuntReport:
    """Validated report metadata retained for candidate provenance."""

    day: str
    markdown: str
    generated_at: str
    html_url: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    channel: str
    rank: int
    title: str
    text: str
    url: str
    author: str
    hot: float | None
    published_at: datetime


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalise_request_url(url: str) -> str:
    """Canonicalize a complete API URL before deriving its cache key."""

    parsed = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            query,
            "",
        )
    )


def _same_story(left_title: str, right_title: str) -> bool:
    """Mirror the existing dedupe guard before candidates leave this source."""

    left = normalize_title(left_title)
    right = normalize_title(right_title)
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) < 18:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.9


class AgihuntClient:
    """Small serial transport with API-specific retry and cache semantics."""

    def __init__(
        self,
        *,
        api_key: str,
        settings: AgihuntSettings,
        cache_dir: str | Path | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_budget: int | None = None,
    ) -> None:
        if (
            request_budget is not None
            and not 1 <= request_budget <= settings.request_budget
        ):
            raise ValueError(
                "AGIHunt client request_budget must be within configured limits"
            )
        self.api_key = api_key.strip()
        self.settings = settings
        self.session = session or requests.Session()
        # Only proxy routing may consult the environment below. Keep Requests
        # from applying ambient netrc/default authentication settings.
        self.session.trust_env = False
        self.sleep = sleep
        self.cache_dir = Path(cache_dir or self._default_cache_dir())
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._request_lock = threading.Lock()
        self.request_budget = request_budget or settings.request_budget
        self.network_requests = 0
        self.cache_hits = 0
        self.last_request_attempts = 0

    @staticmethod
    def _default_cache_dir() -> Path:
        user_id = getattr(os, "getuid", lambda: "user")()
        return Path(tempfile.gettempdir()) / f"daily-report-agihunt-{user_id}"

    @property
    def stats(self) -> dict[str, int]:
        return {
            "network_requests": self.network_requests,
            "cache_hits": self.cache_hits,
        }

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        deadline_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Fetch one JSON object without exceeding the configured request budget."""

        if not self.api_key:
            raise AgihuntAuthenticationError("AGIHunt API key is not configured")

        url = self._build_url(path, params or {})
        with self._request_lock:
            cached = self._read_cache(url)
            if cached is not None:
                self.cache_hits += 1
                return cached
            return self._get_uncached(url, deadline_at=deadline_at)

    def fetch_report(
        self, day: str, *, deadline_at: datetime | None = None
    ) -> AgihuntReport:
        payload = self.get_json("report", params={"day": day}, deadline_at=deadline_at)
        report_day = payload.get("day")
        markdown = payload.get("markdown")
        generated_at = payload.get("generated_at")
        html_url = payload.get("html_url")
        if (
            not isinstance(report_day, str)
            or report_day != day
            or not isinstance(markdown, str)
            or not markdown.strip()
            or not isinstance(generated_at, str)
            or not generated_at.strip()
            or not isinstance(html_url, str)
            or not _is_http_url(html_url)
        ):
            raise AgihuntPayloadError("AGIHunt report payload is invalid")
        return AgihuntReport(
            day=report_day,
            markdown=markdown,
            generated_at=generated_at,
            html_url=html_url.strip(),
        )

    def fetch_channel_items(
        self,
        channel: str,
        day: str,
        *,
        deadline_at: datetime | None = None,
    ) -> list[Any]:
        payload = self.get_json(
            f"channel/{quote(channel, safe='-')}/items",
            params={"day": day, "sort": "hot"},
            deadline_at=deadline_at,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise AgihuntPayloadError("AGIHunt channel payload has no items list")
        return items

    def fetch_channels(self, *, deadline_at: datetime | None = None) -> dict[str, Any]:
        """Expose the official channel listing for a human-authorized smoke check."""

        return self.get_json("channels", deadline_at=deadline_at)

    def _build_url(self, path: str, params: Mapping[str, str]) -> str:
        base = self.settings.api_base_url.rstrip("/")
        query = urlencode(
            sorted((str(key), str(value)) for key, value in params.items())
        )
        return _normalise_request_url(
            f"{base}/{path.lstrip('/')}" + (f"?{query}" if query else "")
        )

    def _get_uncached(
        self, url: str, *, deadline_at: datetime | None
    ) -> dict[str, Any]:
        last_error: AgihuntError | None = None
        for attempt in range(1, 3):
            if self.network_requests >= self.request_budget:
                raise AgihuntRequestBudgetExceededError(
                    "AGIHunt request budget exhausted"
                )
            self.network_requests += 1
            self.last_request_attempts = attempt
            timeout = self._bounded_timeout(deadline_at)
            proxies = (
                get_environ_proxies(url) if self.settings.use_environment_proxy else {}
            )
            try:
                response = self.session.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "X-AgiHunt-Skill-Version": self.settings.skill_version,
                        "User-Agent": (
                            f"daily-report-site-agihunt/{self.settings.skill_version}"
                        ),
                    },
                    timeout=timeout,
                    proxies=proxies,
                )
            except requests.RequestException:
                error: AgihuntError = AgihuntNetworkError("AGIHunt request failed")
            else:
                payload = self._decode_json(response)
                if response.status_code == 200:
                    if not isinstance(payload, dict):
                        error = AgihuntPayloadError(
                            "AGIHunt success response is not a JSON object"
                        )
                    else:
                        self._write_cache(url, payload)
                        return payload
                else:
                    error = self._error_from_response(response, payload)

            last_error = error
            if not error.retryable or attempt == 2:
                raise error
            self._wait_once(error, deadline_at=deadline_at)
        raise last_error or RuntimeError("unreachable AGIHunt request loop")

    def _bounded_timeout(self, deadline_at: datetime | None) -> float:
        if deadline_at is None:
            return self.settings.timeout_seconds
        remaining = (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds()
        if remaining <= 0:
            raise RunDeadlineExceeded("run deadline exceeded during AGIHunt request")
        return min(self.settings.timeout_seconds, remaining)

    def _wait_once(self, error: AgihuntError, *, deadline_at: datetime | None) -> None:
        delay = min(
            float(getattr(error, "retry_after_seconds", 30.0)),
            self.settings.retry_wait_cap_seconds,
        )
        if deadline_at is not None:
            remaining = (deadline_at - datetime.now(deadline_at.tzinfo)).total_seconds()
            if remaining <= delay:
                raise RunDeadlineExceeded(
                    "run deadline exceeded before AGIHunt retry backoff"
                )
        if delay > 0:
            self.sleep(delay)

    @staticmethod
    def _decode_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _error_from_response(
        self, response: requests.Response, payload: Any
    ) -> AgihuntError:
        status = response.status_code
        code = ""
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, Mapping):
                value = error.get("code")
                if isinstance(value, str):
                    code = value

        if status == 401 or code in {"missing_api_key", "invalid_api_key"}:
            return AgihuntAuthenticationError("AGIHunt authentication failed")
        if status == 426 or code == "skill_update_required":
            return AgihuntCompatibilityError("AGIHunt skill update is required")
        if code == "report_not_ready":
            return AgihuntReportNotReadyError("AGIHunt report is not ready")
        if code == "daily_quota_exceeded":
            return AgihuntQuotaExceededError("AGIHunt daily quota is exhausted")
        if status == 429 or code == "rate_limited":
            return AgihuntRateLimitedError(self._retry_after(response))
        if code in {"invalid_day_format", "day_out_of_range"}:
            return AgihuntInvalidRequestError("AGIHunt day parameter is invalid")
        if code == "channel_not_found":
            return AgihuntChannelNotFoundError("AGIHunt channel is not configured")
        if status >= 500:
            return AgihuntServiceError("AGIHunt service failed")
        return AgihuntProtocolError("AGIHunt returned an unexpected response")

    @staticmethod
    def _retry_after(response: requests.Response) -> float:
        value = response.headers.get("Retry-After", "")
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 30.0

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(_normalise_request_url(url).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> dict[str, Any] | None:
        path = self._cache_path(url)
        try:
            age = time.time() - path.stat().st_mtime
            if age >= self.settings.cache_ttl_seconds:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_cache(self, url: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(url)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=self.cache_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise


class AgihuntSource(BaseSource):
    """Turn a bounded selection of AGIHunt channel posts into Articles."""

    name = "agihunt"

    def __init__(
        self,
        *,
        api_key: str = "",
        settings: AgihuntSettings | None = None,
        client: AgihuntClient | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or AgihuntSettings()
        self.client = client or AgihuntClient(api_key=api_key, settings=self.settings)
        self._diagnostics: list[Diagnostic] = []
        self._rejections: Counter[str] = Counter()
        self._degraded = False

    def fetch(
        self,
        max_articles: int = 20,
        reference_dt: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> list[Article]:
        if max_articles < 1:
            raise ValueError("max_articles must be positive")
        reference = self._reference_time(reference_dt)
        day = reference.date().isoformat()
        self._reset_run_state()

        report_url = ""
        if self.settings.include_report:
            try:
                report_url = self.client.fetch_report(
                    day, deadline_at=deadline_at
                ).html_url
            except RunDeadlineExceeded:
                raise
            except AgihuntError as error:
                self._record_error(error, stage="report")
                if error.fatal:
                    self._finish([], day=day)
                    raise

        candidates_by_channel: dict[str, list[_Candidate]] = {}
        for channel in [
            *self.settings.core_channels,
            self.settings.supplemental_channel,
        ]:
            try:
                raw_items = self.client.fetch_channel_items(
                    channel, day, deadline_at=deadline_at
                )
            except RunDeadlineExceeded:
                raise
            except AgihuntRequestBudgetExceededError as error:
                self._record_error(error, stage="channel")
                break
            except AgihuntQuotaExceededError as error:
                self._record_error(error, stage="channel")
                break
            except AgihuntError as error:
                self._record_error(error, stage="channel")
                if error.fatal:
                    self._finish([], day=day)
                    raise
                continue

            self.last_fetched_count = (self.last_fetched_count or 0) + len(raw_items)
            parsed = [
                candidate
                for index, item in enumerate(raw_items, 1)
                if (
                    candidate := self._parse_candidate(
                        item, channel=channel, rank=index, reference=reference
                    )
                )
                is not None
            ]
            candidates_by_channel[channel] = self._rank_channel(parsed)

        articles = self._select_articles(
            candidates_by_channel,
            day=day,
            report_url=report_url,
            max_articles=max_articles,
        )
        self._finish(articles, day=day)
        return articles

    def _reset_run_state(self) -> None:
        self.last_attempts = 0
        self.last_fetched_count = 0
        self.last_accepted_count = 0
        self.last_status = None
        self.last_diagnostics = ()
        self._diagnostics = []
        self._rejections = Counter()
        self._degraded = False

    @staticmethod
    def _reference_time(reference_dt: datetime | None) -> datetime:
        reference = reference_dt or datetime.now(ZoneInfo("Asia/Shanghai"))
        if reference.tzinfo is None or reference.utcoffset() is None:
            raise ValueError("AGIHunt reference_dt must be timezone-aware")
        return reference

    def _record_error(self, error: AgihuntError, *, stage: str) -> None:
        self._degraded = True
        self._diagnostics.append(
            Diagnostic(
                code=error.diagnostic_code,
                message="AGIHunt request did not complete successfully",
                details=(("stage", stage),),
            )
        )

    def _parse_candidate(
        self,
        item: Any,
        *,
        channel: str,
        rank: int,
        reference: datetime,
    ) -> _Candidate | None:
        if not isinstance(item, Mapping):
            self._reject("invalid_item")
            return None
        title = item.get("title")
        url = item.get("url")
        published_at = item.get("published_at")
        if not isinstance(title, str) or not title.strip():
            self._reject("invalid_title")
            return None
        if not isinstance(url, str) or not _is_http_url(url):
            self._reject("invalid_url")
            return None
        published = self._parse_published_at(published_at)
        if published is None:
            self._reject("invalid_published_at")
            return None
        if published > reference + timedelta(
            minutes=self.settings.future_tolerance_minutes
        ):
            self._reject("future_published_at")
            return None
        if published < reference - timedelta(hours=self.settings.max_age_hours):
            self._reject("stale_published_at")
            return None

        text = item.get("text", "")
        author = item.get("author", "")
        return _Candidate(
            channel=channel,
            rank=rank,
            title=" ".join(title.split()),
            text=" ".join(text.split()) if isinstance(text, str) else "",
            url=url.strip(),
            author=" ".join(author.split()) if isinstance(author, str) else "",
            hot=self._parse_hot(item.get("hot")),
            published_at=published,
        )

    @staticmethod
    def _parse_published_at(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed

    @staticmethod
    def _parse_hot(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _rank_channel(candidates: list[_Candidate]) -> list[_Candidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.hot is None,
                -(candidate.hot or 0.0),
                candidate.rank,
            ),
        )

    def _select_articles(
        self,
        candidates_by_channel: Mapping[str, list[_Candidate]],
        *,
        day: str,
        report_url: str,
        max_articles: int,
    ) -> list[Article]:
        queues = {
            channel: candidates[: self.settings.per_channel_limit]
            for channel, candidates in candidates_by_channel.items()
        }
        selected: list[_Candidate] = []
        considered: set[tuple[str, int]] = set()
        seen_story_keys: set[str] = set()
        seen_titles: list[str] = []
        entity_counts: Counter[str] = Counter()

        def select_one(candidate: _Candidate) -> bool:
            marker = (candidate.channel, candidate.rank)
            if marker in considered:
                return False
            considered.add(marker)
            if len(selected) >= max_articles:
                self._reject("max_articles")
                return False
            story_key = canonical_url(candidate.url) or normalize_title(candidate.title)
            if (
                not story_key
                or story_key in seen_story_keys
                or any(_same_story(candidate.title, title) for title in seen_titles)
            ):
                self._reject("duplicate_story")
                return False
            entity = self._entity_for_title(candidate.title)
            if entity and entity_counts[entity] >= self.settings.entity_limit:
                self._reject("entity_limit")
                return False
            seen_story_keys.add(story_key)
            seen_titles.append(candidate.title)
            if entity:
                entity_counts[entity] += 1
            selected.append(candidate)
            return True

        def satisfy_quota(channel: str, quota: int) -> None:
            accepted = 0
            for candidate in queues.get(channel, []):
                if accepted >= quota:
                    break
                if select_one(candidate):
                    accepted += 1

        for channel in self.settings.core_channels:
            satisfy_quota(channel, self.settings.core_channel_quota)
        satisfy_quota(
            self.settings.supplemental_channel,
            self.settings.supplemental_quota,
        )

        for channel in [
            *self.settings.core_channels,
            self.settings.supplemental_channel,
        ]:
            for candidate in queues.get(channel, []):
                select_one(candidate)

        return [
            self._article_from_candidate(candidate, day=day, report_url=report_url)
            for candidate in selected
        ]

    def _entity_for_title(self, title: str) -> str:
        normalized = normalize_title(title)
        for entity in self.settings.entity_keywords:
            if normalize_title(entity) in normalized:
                return entity
        return ""

    def _article_from_candidate(
        self, candidate: _Candidate, *, day: str, report_url: str
    ) -> Article:
        provenance = {
            "provider": AGIHUNT_SOURCE_LABEL,
            "retrieval": AGIHUNT_CHANNEL_HOT_FEED,
            "channel": candidate.channel,
            "channel_rank": str(candidate.rank),
            "api_day": day,
        }
        if candidate.author:
            provenance["author"] = candidate.author
        if candidate.hot is not None:
            provenance["hot"] = f"{candidate.hot:g}"
        if report_url:
            provenance["report_url"] = report_url
        return Article(
            title=candidate.title,
            link=candidate.url,
            description=candidate.text[:400],
            publish_time=candidate.published_at.isoformat(),
            content=candidate.text[:2000],
            priority=self.settings.source_priority,
            source=self.name,
            provenance=provenance,
        )

    def _reject(self, reason: str) -> None:
        self._rejections[reason] += 1

    def _finish(self, articles: list[Article], *, day: str) -> None:
        self.last_attempts = int(getattr(self.client, "network_requests", 0))
        self.last_accepted_count = len(articles)
        raw_count = self.last_fetched_count or 0
        stats = getattr(self.client, "stats", {})
        details = (
            ("api_day", day),
            ("retrieval", AGIHUNT_CHANNEL_HOT_FEED),
            ("network_requests", str(stats.get("network_requests", 0))),
            ("cache_hits", str(stats.get("cache_hits", 0))),
            ("raw_items", str(raw_count)),
            ("accepted_items", str(len(articles))),
        )
        self._diagnostics.append(
            Diagnostic(
                code="agihunt_selection_stats",
                message="AGIHunt selection completed with bounded channel coverage",
                details=details,
            )
        )
        for reason, count in sorted(self._rejections.items()):
            self._diagnostics.append(
                Diagnostic(
                    code=f"agihunt_rejected_{reason}",
                    message="AGIHunt candidate was rejected by deterministic policy",
                    details=(("count", str(count)),),
                )
            )
        if self._degraded or (raw_count > 0 and not articles):
            self.last_status = "degraded"
        elif articles:
            self.last_status = "ok"
        else:
            self.last_status = "empty"
        self.last_diagnostics = tuple(self._diagnostics)


__all__ = [
    "AGIHUNT_SOURCE_LABEL",
    "AGIHUNT_CHANNEL_HOT_FEED",
    "AgihuntAuthenticationError",
    "AgihuntChannelNotFoundError",
    "AgihuntClient",
    "AgihuntCompatibilityError",
    "AgihuntError",
    "AgihuntInvalidRequestError",
    "AgihuntPayloadError",
    "AgihuntQuotaExceededError",
    "AgihuntRateLimitedError",
    "AgihuntReport",
    "AgihuntReportNotReadyError",
    "AgihuntRequestBudgetExceededError",
    "AgihuntSource",
]
