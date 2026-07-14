from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo

import pytest
import requests

import main as daily_main
import sources as source_registry
from config import AgihuntSettings
from sources import fetch_batch
from sources.agihunt import (
    AGIHUNT_SOURCE_LABEL,
    AgihuntAuthenticationError,
    AgihuntClient,
    AgihuntCompatibilityError,
    AgihuntPayloadError,
    AgihuntQuotaExceededError,
    AgihuntRateLimitedError,
    AgihuntReport,
    AgihuntReportNotReadyError,
    AgihuntRequestBudgetExceededError,
    AgihuntSource,
)
from utils.run_contracts import RunDeadlineExceeded


REFERENCE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 13, 8, 36, tzinfo=REFERENCE)
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agihunt" / "channel-items.json"


def test_utils_can_be_imported_before_sources_without_a_cycle() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from utils import storage; from sources import Article; assert storage and Article",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def settings(**updates) -> AgihuntSettings:
    values = {
        "api_base_url": "https://agihunt.test/agent/v1",
        "include_report": False,
        "core_channels": ["models", "research", "coding-agents"],
        "supplemental_channel": "products",
        "request_budget": 5,
        "max_articles": 14,
        "per_channel_limit": 4,
        "core_channel_quota": 1,
        "supplemental_quota": 1,
        "max_age_hours": 30,
        "entity_limit": 2,
        "entity_keywords": ["openai"],
    }
    values.update(updates)
    if "max_articles" not in updates:
        values["max_articles"] = min(
            values["max_articles"],
            (len(values["core_channels"]) + 1) * values["per_channel_limit"],
        )
    return AgihuntSettings(**values)


def response(payload: object, status: int = 200, **headers: str) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode("utf-8")
    result.headers.update(headers)
    return result


class RecordingSession:
    trust_env = True

    def __init__(self, outcomes: list[requests.Response | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[tuple[tuple, dict]] = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FixtureClient:
    def __init__(self, fixture: dict, *, report_error: Exception | None = None) -> None:
        self.fixture = fixture
        self.report_error = report_error
        self.network_requests = 0
        self.cache_hits = 0
        self.calls: list[tuple[str, str]] = []

    @property
    def stats(self) -> dict[str, int]:
        return {
            "network_requests": self.network_requests,
            "cache_hits": self.cache_hits,
        }

    def fetch_report(self, day: str, *, deadline_at=None) -> AgihuntReport:
        self.network_requests += 1
        self.calls.append(("report", day))
        if self.report_error:
            raise self.report_error
        return AgihuntReport(**self.fixture["report"])

    def fetch_channel_items(self, channel: str, day: str, *, deadline_at=None):
        self.network_requests += 1
        self.calls.append((channel, day))
        return self.fixture["channels"].get(channel, [])


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_client_sends_required_headers_and_uses_ten_minute_cache(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("sources.agihunt.get_environ_proxies", lambda _url: {})
    session = RecordingSession([response({"items": []})])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(),
        cache_dir=tmp_path,
        session=session,
    )

    assert client.fetch_channel_items("models", "2026-07-13") == []
    assert client.fetch_channel_items("models", "2026-07-13") == []

    assert len(session.calls) == 1
    _args, request_kwargs = session.calls[0]
    assert request_kwargs["headers"] == {
        "Authorization": "Bearer test-key",
        "X-AgiHunt-Skill-Version": "1.2.2",
        "User-Agent": "daily-report-site-agihunt/1.2.2",
    }
    assert request_kwargs["proxies"] == {}
    assert client.network_requests == 1
    assert client.cache_hits == 1
    assert list(tmp_path.glob("*.json"))


def test_client_uses_explicit_environment_proxy_lookup(tmp_path, monkeypatch) -> None:
    proxy = {"https": "http://proxy.example.test:8080"}
    monkeypatch.setattr("sources.agihunt.get_environ_proxies", lambda _url: proxy)
    session = RecordingSession([response({"items": []})])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(),
        cache_dir=tmp_path,
        session=session,
    )

    client.fetch_channel_items("models", "2026-07-13")

    _args, request_kwargs = session.calls[0]
    assert client.session.trust_env is False
    assert request_kwargs["proxies"] == proxy


def test_client_can_disable_environment_proxy_lookup(tmp_path, monkeypatch) -> None:
    called = False

    def proxy_lookup(_url: str) -> dict[str, str]:
        nonlocal called
        called = True
        return {"https": "http://proxy.example.test:8080"}

    monkeypatch.setattr("sources.agihunt.get_environ_proxies", proxy_lookup)
    session = RecordingSession([response({"items": []})])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(use_environment_proxy=False),
        cache_dir=tmp_path,
        session=session,
    )

    client.fetch_channel_items("models", "2026-07-13")

    _args, request_kwargs = session.calls[0]
    assert called is False
    assert request_kwargs["proxies"] == {}


def test_missing_key_never_issues_a_network_request(tmp_path) -> None:
    session = RecordingSession([])
    client = AgihuntClient(
        api_key="", settings=settings(), cache_dir=tmp_path, session=session
    )

    with pytest.raises(AgihuntAuthenticationError):
        client.fetch_channel_items("models", "2026-07-13")

    assert session.calls == []


@pytest.mark.parametrize(
    ("status", "payload", "error_type"),
    [
        (401, {"error": {"code": "invalid_api_key"}}, AgihuntAuthenticationError),
        (426, {"error": {"code": "skill_update_required"}}, AgihuntCompatibilityError),
        (429, {"error": {"code": "daily_quota_exceeded"}}, AgihuntQuotaExceededError),
    ],
)
def test_client_maps_non_retryable_api_errors(
    tmp_path, status: int, payload: dict, error_type: type[Exception]
) -> None:
    session = RecordingSession([response(payload, status)])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(),
        cache_dir=tmp_path,
        session=session,
    )

    with pytest.raises(error_type):
        client.fetch_channel_items("models", "2026-07-13")

    assert len(session.calls) == 1


def test_client_retries_rate_limited_once_with_retry_after(tmp_path) -> None:
    sleeps: list[float] = []
    session = RecordingSession(
        [
            response(
                {"error": {"code": "rate_limited"}},
                429,
                **{"Retry-After": "7"},
            ),
            response({"items": []}),
        ]
    )
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(retry_wait_cap_seconds=10),
        cache_dir=tmp_path,
        session=session,
        sleep=sleeps.append,
    )

    assert client.fetch_channel_items("models", "2026-07-13") == []
    assert client.network_requests == 2
    assert sleeps == [7.0]


def test_client_retries_a_service_error_once(tmp_path) -> None:
    session = RecordingSession(
        [
            response({"error": {"code": "server_failure"}}, 503),
            response({"items": []}),
        ]
    )
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(retry_wait_cap_seconds=0),
        cache_dir=tmp_path,
        session=session,
        sleep=lambda _: None,
    )

    assert client.fetch_channel_items("models", "2026-07-13") == []
    assert client.network_requests == 2


def test_client_refuses_a_retry_that_would_cross_the_run_deadline(tmp_path) -> None:
    session = RecordingSession(
        [
            response(
                {"error": {"code": "rate_limited"}},
                429,
                **{"Retry-After": "7"},
            )
        ]
    )
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(retry_wait_cap_seconds=10),
        cache_dir=tmp_path,
        session=session,
        sleep=lambda _: None,
    )

    with pytest.raises(RunDeadlineExceeded):
        client.fetch_channel_items(
            "models",
            "2026-07-13",
            deadline_at=datetime.now(REFERENCE) + timedelta(seconds=1),
        )

    assert client.network_requests == 1


def test_client_uses_budget_for_physical_retries(tmp_path) -> None:
    session = RecordingSession([response({"error": {"code": "server_failure"}}, 503)])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(
            core_channels=["models"],
            request_budget=2,
            retry_wait_cap_seconds=0,
        ),
        cache_dir=tmp_path,
        session=session,
        sleep=lambda _: None,
    )
    client.network_requests = 1

    with pytest.raises(AgihuntRequestBudgetExceededError):
        client.fetch_channel_items("models", "2026-07-13")

    assert client.network_requests == 2
    assert len(session.calls) == 1


def test_client_can_apply_a_lower_phase_zero_request_budget(tmp_path) -> None:
    session = RecordingSession([response({"items": []}) for _ in range(3)])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(),
        cache_dir=tmp_path,
        session=session,
        request_budget=3,
    )

    for channel in ("models", "research", "coding-agents"):
        assert client.fetch_channel_items(channel, "2026-07-13") == []
    with pytest.raises(AgihuntRequestBudgetExceededError):
        client.fetch_channel_items("products", "2026-07-13")

    assert client.network_requests == 3
    assert len(session.calls) == 3


def test_client_rejects_invalid_channel_payload(tmp_path) -> None:
    session = RecordingSession([response({"items": "not-a-list"})])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(),
        cache_dir=tmp_path,
        session=session,
    )

    with pytest.raises(AgihuntPayloadError):
        client.fetch_channel_items("models", "2026-07-13")


def test_client_maps_report_not_ready_without_retrying(tmp_path) -> None:
    session = RecordingSession([response({"error": {"code": "report_not_ready"}}, 404)])
    client = AgihuntClient(
        api_key="test-key",
        settings=settings(include_report=True),
        cache_dir=tmp_path,
        session=session,
    )

    with pytest.raises(AgihuntReportNotReadyError):
        client.fetch_report("2026-07-13")

    assert len(session.calls) == 1


def test_client_serializes_concurrent_calls(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()

    class SlowSession:
        trust_env = True

        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        def get(self, *args, **kwargs):
            with state_lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                started.set()
            release.wait(timeout=1)
            with state_lock:
                self.active -= 1
            return response({"items": []})

    session = SlowSession()
    client = AgihuntClient(
        api_key="test-key", settings=settings(), cache_dir=tmp_path, session=session
    )
    first = threading.Thread(
        target=client.fetch_channel_items, args=("models", "2026-07-13")
    )
    second = threading.Thread(
        target=client.fetch_channel_items, args=("research", "2026-07-13")
    )

    first.start()
    assert started.wait(timeout=1)
    second.start()
    time.sleep(0.02)
    assert session.max_active == 1
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)
    assert not first.is_alive()
    assert not second.is_alive()


def test_source_uses_channel_quotas_without_comparing_hot_across_channels() -> None:
    fixture = load_fixture()
    source = AgihuntSource(client=FixtureClient(fixture), settings=settings())

    articles = source.fetch(max_articles=4, reference_dt=NOW)

    assert [article.title for article in articles] == [
        "Model higher hot",
        "Research very high hot",
        "Coding agent story",
        "Product story",
    ]
    assert all(article.priority == 3 for article in articles)
    assert all(article.source == "agihunt" for article in articles)


def test_source_can_select_twenty_candidates_with_four_channel_prefixes() -> None:
    channels = ("models", "research", "coding-agents", "products")
    distinct_topics = (
        "foundation release",
        "robotics benchmark",
        "security evaluation",
        "developer workflow",
        "multimodal product launch",
    )
    fixture = {
        "report": {
            "day": "2026-07-13",
            "markdown": "report",
            "generated_at": "2026-07-13T00:00:00+00:00",
            "html_url": "https://agihunt.info/daily/2026-07-13",
        },
        "channels": {
            channel: [
                {
                    "title": f"{channel} {distinct_topics[index - 1]}",
                    "text": "valid candidate",
                    "url": f"https://example.test/{channel}/{index}",
                    "hot": 100 - index,
                    "published_at": "2026-07-13T07:00:00+08:00",
                }
                for index in range(1, 6)
            ]
            for channel in channels
        },
    }
    source = AgihuntSource(
        client=FixtureClient(fixture),
        settings=settings(
            max_articles=20,
            per_channel_limit=5,
            entity_keywords=[],
        ),
    )

    articles = source.fetch(reference_dt=NOW)

    assert len(articles) == 20
    assert source.last_accepted_count == 20
    assert {article.provenance["channel"] for article in articles} == set(channels)
    assert {article.provenance["retrieval"] for article in articles} == {"channel_hot"}


def test_registry_can_override_only_the_agihunt_candidate_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channels = ("models", "research", "coding-agents", "products")
    distinct_topics = (
        "foundation release",
        "robotics benchmark",
        "security evaluation",
        "developer workflow",
        "multimodal product launch",
    )
    fixture = {
        "report": {
            "day": "2026-07-13",
            "markdown": "report",
            "generated_at": "2026-07-13T00:00:00+00:00",
            "html_url": "https://agihunt.info/daily/2026-07-13",
        },
        "channels": {
            channel: [
                {
                    "title": f"{channel} {distinct_topics[index - 1]}",
                    "url": f"https://example.test/cap/{channel}/{index}",
                    "hot": 100 - index,
                    "published_at": "2026-07-13T07:00:00+08:00",
                }
                for index in range(1, 6)
            ]
            for channel in channels
        },
    }
    source = AgihuntSource(
        client=FixtureClient(fixture),
        settings=settings(
            max_articles=20,
            per_channel_limit=5,
            entity_keywords=[],
        ),
    )
    monkeypatch.setattr(source_registry, "AgihuntSource", lambda **_kwargs: source)

    articles, outcomes = source_registry.fetch_batch(
        {"agihunt": True},
        max_articles=14,
        agihunt_settings=source.settings,
        agihunt_max_articles=20,
        reference_dt=NOW,
    )

    assert len(articles) == 20
    assert outcomes[0].accepted_count == 20


def test_source_rejects_invalid_times_urls_duplicates_and_entity_overflow() -> None:
    fixture = load_fixture()
    fixture["channels"] = {
        "models": [
            {
                "title": "OpenAI first announcement",
                "text": "valid",
                "url": "https://example.test/openai/one",
                "hot": 9,
                "published_at": "2026-07-13T07:00:00+08:00",
            },
            {
                "title": "OpenAI first announcement",
                "text": "duplicate title",
                "url": "https://example.test/openai/title-duplicate",
                "hot": 8.5,
                "published_at": "2026-07-13T07:00:30+08:00",
            },
            {
                "title": "Different title same source URL",
                "text": "duplicate URL",
                "url": "https://example.test/openai/one",
                "hot": 8,
                "published_at": "2026-07-13T07:01:00+08:00",
            },
            {
                "title": "OpenAI second announcement",
                "text": "entity cap",
                "url": "https://example.test/openai/two",
                "hot": 7,
                "published_at": "2026-07-13T07:02:00+08:00",
            },
            {
                "title": "Bad URL",
                "url": "ftp://example.test/not-publishable",
                "hot": 6,
                "published_at": "2026-07-13T07:03:00+08:00",
            },
            {
                "title": "Future item",
                "url": "https://example.test/future",
                "hot": 5,
                "published_at": "2026-07-13T09:00:00+08:00",
            },
            {
                "title": "Stale item",
                "url": "https://example.test/stale",
                "hot": 4,
                "published_at": "2026-07-11T00:00:00+08:00",
            },
        ],
        "products": [
            {
                "title": "Independent product story",
                "text": "valid product",
                "url": "https://example.test/product/one",
                "hot": 1,
                "published_at": "2026-07-13T07:05:00+08:00",
            }
        ],
    }
    source = AgihuntSource(
        client=FixtureClient(fixture),
        settings=settings(
            include_report=True,
            core_channels=["models"],
            supplemental_channel="products",
            entity_limit=1,
        ),
    )

    articles = source.fetch(max_articles=4, reference_dt=NOW)
    diagnostic_codes = {diagnostic.code for diagnostic in source.last_diagnostics}

    assert [article.title for article in articles] == [
        "OpenAI first announcement",
        "Independent product story",
    ]
    assert articles[0].provenance == {
        "provider": AGIHUNT_SOURCE_LABEL,
        "retrieval": "channel_hot",
        "channel": "models",
        "channel_rank": "1",
        "api_day": "2026-07-13",
        "hot": "9",
        "report_url": "https://agihunt.info/daily/2026-07-13",
    }
    assert {
        "agihunt_rejected_duplicate_story",
        "agihunt_rejected_entity_limit",
        "agihunt_rejected_invalid_url",
        "agihunt_rejected_future_published_at",
        "agihunt_rejected_stale_published_at",
    } <= diagnostic_codes


def test_report_not_ready_is_a_degraded_diagnostic_and_channels_continue() -> None:
    source = AgihuntSource(
        client=FixtureClient(
            load_fixture(),
            report_error=AgihuntReportNotReadyError("not ready"),
        ),
        settings=settings(include_report=True),
    )

    articles = source.fetch(max_articles=4, reference_dt=NOW)

    assert len(articles) == 4
    assert source.last_status == "degraded"
    assert "agihunt_report_not_ready" in {
        diagnostic.code for diagnostic in source.last_diagnostics
    }


def test_registry_records_missing_key_as_a_failed_source_without_network() -> None:
    articles, outcomes = fetch_batch(
        {"agihunt": True},
        agihunt_settings=settings(),
        reference_dt=NOW,
    )

    assert articles == []
    assert outcomes[0].status == "failed"
    assert outcomes[0].error_kind == "AgihuntAuthenticationError"
    assert "agihunt_authentication_failed" in {
        diagnostic.code for diagnostic in outcomes[0].diagnostics
    }


def test_registry_preserves_agihunt_provenance_in_the_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AgihuntSource(client=FixtureClient(load_fixture()), settings=settings())
    monkeypatch.setattr(source_registry, "AgihuntSource", lambda **_kwargs: source)

    articles, outcomes = source_registry.fetch_batch(
        {"agihunt": True},
        agihunt_settings=settings(),
        reference_dt=NOW,
        max_articles=4,
    )

    assert len(articles) == 4
    assert outcomes[0].status == "ok"
    assert outcomes[0].fetched_count == 5
    assert outcomes[0].accepted_count == 4
    assert outcomes[0].articles[0].provenance["provider"] == AGIHUNT_SOURCE_LABEL


def test_one_run_agihunt_override_does_not_mutate_config_sources() -> None:
    config = type("Config", (), {"sources": {"agihunt": False, "aibase": True}})()

    enabled = daily_main.resolve_enabled_sources(
        config, type("Args", (), {"agihunt": "on"})()
    )

    assert enabled == {"agihunt": True, "aibase": True}
    assert config.sources["agihunt"] is False


def test_agihunt_attribution_is_added_without_changing_summary_facts() -> None:
    content = daily_main.compose_report_content(
        "日报标题",
        "1. [原帖](https://example.test/story)：摘要",
        [
            {
                "source": "agihunt",
                "provenance": {"provider": AGIHUNT_SOURCE_LABEL},
            }
        ],
    )

    assert "候选来源：AGI HUNT · agihunt.info" in content
    assert "[原帖](https://example.test/story)" in content


def test_agihunt_settings_rejects_an_endpoint_plan_above_budget() -> None:
    with pytest.raises(ValueError, match="request_budget"):
        settings(include_report=True, request_budget=4)


def test_rate_limit_error_carries_the_retry_delay() -> None:
    assert AgihuntRateLimitedError(12).retry_after_seconds == 12
