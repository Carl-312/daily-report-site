"""AGI Hunt's rendered homepage Trending list as a deterministic news source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import re
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from bs4.element import Tag

from config import AgihuntTrendingSettings
from utils.headless_chrome import RenderedDom, render_page_dom
from utils.run_contracts import Diagnostic

from .base import Article, BaseSource


AGIHUNT_TRENDING_SOURCE_LABEL = "AGI HUNT · agihunt.info"
PARSER_VERSION = "1"
_MOVEMENT_UP = re.compile(r"(?:▲|↑)\s*(\d+)")
_MOVEMENT_DOWN = re.compile(r"(?:▼|↓)\s*(\d+)")
_MOVEMENT_NEW = re.compile(r"(?:新上榜|NEW)", re.IGNORECASE)
_MOVEMENT_STEADY = re.compile(r"(?:—|-|持平)")
_HEAT = re.compile(r"\d+(?:\.\d+)?")


class AgihuntTrendingError(RuntimeError):
    diagnostic_code = "agihunt_trending_error"


class AgihuntTrendingDomError(AgihuntTrendingError):
    diagnostic_code = "agihunt_trending_invalid_dom"


@dataclass(frozen=True, slots=True)
class TrendItem:
    rank: int
    title: str
    term_en: str
    blurb: str
    heat: str
    state: str
    delta: int
    movement: str


def _normalize_heat(value: str) -> str:
    compact = value.strip()
    if not _HEAT.fullmatch(compact):
        raise AgihuntTrendingDomError("trend heat is not numeric")
    try:
        heat = Decimal(compact)
    except InvalidOperation as exc:
        raise AgihuntTrendingDomError("trend heat is invalid") from exc
    if heat < 0:
        raise AgihuntTrendingDomError("trend heat must not be negative")
    return compact


def _parse_movement(value: str) -> tuple[str, int]:
    compact = " ".join(value.split())
    if _MOVEMENT_NEW.fullmatch(compact):
        return "new", 0
    if match := _MOVEMENT_UP.fullmatch(compact):
        return "up", int(match.group(1))
    if match := _MOVEMENT_DOWN.fullmatch(compact):
        return "down", int(match.group(1))
    if _MOVEMENT_STEADY.fullmatch(compact):
        return "steady", 0
    raise AgihuntTrendingDomError("trend movement label is unknown")


def _looks_like_trending_list(node: Tag) -> bool:
    rows = node.find_all("li", recursive=False)
    if not rows:
        return False
    first_button = rows[0].find("button", recursive=False)
    return bool(first_button and first_button.find("span", attrs={"title": True}))


def parse_trending_dom(html: str, *, maximum_rows: int = 20) -> list[TrendItem]:
    """Parse the visible desktop Trending rail without relying on CSS classes."""

    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    if main is None:
        raise AgihuntTrendingDomError("rendered page has no main content")
    candidates = [
        node for node in main.find_all("ol") if _looks_like_trending_list(node)
    ]
    if len(candidates) != 1:
        raise AgihuntTrendingDomError(
            "rendered page must contain exactly one main Trending list"
        )

    row_nodes = candidates[0].find_all("li", recursive=False)
    if not row_nodes or len(row_nodes) > maximum_rows:
        raise AgihuntTrendingDomError("Trending row count is outside parser bounds")

    trends: list[TrendItem] = []
    for row in row_nodes:
        button = row.find("button", recursive=False)
        columns = button.find_all("span", recursive=False) if button else []
        if len(columns) != 2:
            raise AgihuntTrendingDomError("trend row has an unexpected column shape")
        try:
            rank = int(columns[0].get_text(" ", strip=True))
        except ValueError as exc:
            raise AgihuntTrendingDomError("trend rank is not an integer") from exc

        body = columns[1]
        title_node = body.find("span", attrs={"title": True}, recursive=False)
        if title_node is None:
            raise AgihuntTrendingDomError("trend row has no stable title key")
        blurb_node = title_node.find_next_sibling("span")
        meta_node = blurb_node.find_next_sibling("span") if blurb_node else None
        meta_fields = meta_node.find_all("span", recursive=False) if meta_node else []
        if len(meta_fields) != 3:
            raise AgihuntTrendingDomError("trend row has incomplete metadata")

        title = title_node.get_text(" ", strip=True)
        term_en = str(title_node.get("title") or "").strip()
        blurb = blurb_node.get_text(" ", strip=True) if blurb_node else ""
        movement = meta_fields[0].get_text(" ", strip=True)
        state, delta = _parse_movement(movement)
        heat = _normalize_heat(meta_fields[2].get_text(" ", strip=True))
        if not title or not term_en or not blurb:
            raise AgihuntTrendingDomError("trend row is missing reader content")
        trends.append(
            TrendItem(
                rank=rank,
                title=title,
                term_en=term_en,
                blurb=blurb,
                heat=heat,
                state=state,
                delta=delta,
                movement=movement,
            )
        )

    if [trend.rank for trend in trends] != list(range(1, len(trends) + 1)):
        raise AgihuntTrendingDomError("trend ranks must be contiguous from one")
    if len({trend.term_en for trend in trends}) != len(trends):
        raise AgihuntTrendingDomError("trend title keys must be unique")
    return trends


def _query_url(page_url: str, **values: str) -> str:
    parts = urlsplit(page_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", urlencode(query), "")
    )


class AgihuntTrendingSource(BaseSource):
    """Fetch exactly one rendered daily Trending snapshot."""

    name = "agihunt_trending"

    def __init__(
        self,
        settings: AgihuntTrendingSettings | None = None,
        *,
        renderer: Callable[..., RenderedDom] = render_page_dom,
    ) -> None:
        super().__init__()
        self.settings = settings or AgihuntTrendingSettings()
        self.renderer = renderer

    def fetch(
        self,
        max_articles: int = 15,
        reference_dt: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> list[Article]:
        timezone = ZoneInfo(self.settings.timezone)
        observed_at = reference_dt or datetime.now(timezone)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("AGI Hunt Trending reference time must be timezone-aware")
        observed_at = observed_at.astimezone(timezone)
        trend_day = observed_at.date() + timedelta(days=self.settings.day_offset)
        page_url = _query_url(
            self.settings.page_url,
            day=trend_day.isoformat(),
            window=self.settings.window,
        )

        self.last_attempts = 1
        rendered = self.renderer(
            page_url,
            configured_binary=self.settings.chrome_binary,
            language=self.settings.language,
            timeout_seconds=self.settings.render_timeout_seconds,
            virtual_time_budget_ms=self.settings.virtual_time_budget_ms,
            max_dom_bytes=self.settings.max_dom_bytes,
            deadline_at=deadline_at,
        )
        trends = parse_trending_dom(rendered.html)
        self.last_fetched_count = len(trends)
        if len(trends) < self.settings.minimum_articles:
            raise AgihuntTrendingDomError("too few Trending rows were rendered")

        diagnostics: list[Diagnostic] = [
            Diagnostic(
                code="agihunt_trending_snapshot",
                message="captured one rendered AGI Hunt Trending snapshot",
                details=(
                    ("requested_day", trend_day.isoformat()),
                    ("row_count", str(len(trends))),
                    ("chrome_version", rendered.chrome_version),
                    ("render_duration_ms", str(rendered.duration_ms)),
                    (
                        "dom_sha256",
                        hashlib.sha256(rendered.html.encode("utf-8")).hexdigest(),
                    ),
                    ("parser_version", PARSER_VERSION),
                ),
            )
        ]
        if len(trends) != self.settings.expected_articles:
            diagnostics.append(
                Diagnostic(
                    code="agihunt_trending_unexpected_count",
                    message="Trending row count differs from the expected contract",
                    details=(
                        ("expected", str(self.settings.expected_articles)),
                        ("actual", str(len(trends))),
                    ),
                )
            )
            self.last_status = "degraded"
        else:
            self.last_status = "ok"

        accepted_limit = min(max_articles, self.settings.max_articles)
        articles = [
            self._article(trend, trend_day.isoformat(), observed_at, rendered)
            for trend in trends[:accepted_limit]
        ]
        self.last_accepted_count = len(articles)
        self.last_diagnostics = tuple(diagnostics)
        return articles

    def _article(
        self,
        trend: TrendItem,
        trend_day: str,
        observed_at: datetime,
        rendered: RenderedDom,
    ) -> Article:
        if trend.rank <= 3:
            priority = self.settings.source_priority + 1
        elif trend.rank <= 10:
            priority = self.settings.source_priority
        else:
            priority = max(0, self.settings.source_priority - 1)
        detail_url = _query_url(
            self.settings.page_url,
            day=trend_day,
            t=trend.term_en,
        )
        return Article(
            title=trend.title,
            link=detail_url,
            description=trend.blurb,
            publish_time=observed_at.isoformat(timespec="seconds"),
            priority=priority,
            source=self.name,
            kind="lead",
            evidence_status="unresolved",
            confidence="signal",
            provenance={
                "provider": AGIHUNT_TRENDING_SOURCE_LABEL,
                "retrieval": "homepage_trending_dom",
                "trend_day": trend_day,
                "trend_window": self.settings.window,
                "trend_rank": str(trend.rank),
                "trend_heat": trend.heat,
                "trend_state": trend.state,
                "trend_delta": str(trend.delta),
                "trend_term_en": trend.term_en,
                "observed_at": observed_at.isoformat(timespec="seconds"),
                "publish_time_semantics": "trend_observed_at",
                "chrome_version": rendered.chrome_version,
            },
        )
