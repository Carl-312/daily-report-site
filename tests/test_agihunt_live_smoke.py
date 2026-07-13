from __future__ import annotations

import json

from scripts.agihunt_live_smoke import MAX_NETWORK_REQUESTS, run_smoke
from sources.agihunt import AgihuntReport, AgihuntReportNotReadyError


DAY = "2026-07-13"


class SmokeClient:
    def __init__(
        self, *, report_error: Exception | None = None, items: list | None = None
    ):
        self.report_error = report_error
        self.items = (
            items
            if items is not None
            else [
                {
                    "title": "Sensitive title that must not enter the artifact",
                    "text": "Private source content that must not enter the artifact",
                    "url": "https://news.example.test/story?secret=not-retained",
                    "author": "Private author",
                    "hot": 42,
                    "published_at": "2026-07-13T08:00:00+08:00",
                }
            ]
        )
        self.calls: list[tuple[str, str]] = []
        self.network_requests = 0

    @property
    def stats(self) -> dict[str, int]:
        return {"network_requests": self.network_requests, "cache_hits": 0}

    def fetch_channels(self):
        self.calls.append(("channels", ""))
        self.network_requests += 1
        return {"channels": [{"slug": "models", "name": "Models"}]}

    def fetch_report(self, day: str):
        self.calls.append(("report", day))
        self.network_requests += 1
        if self.report_error:
            raise self.report_error
        return AgihuntReport(
            day=day,
            markdown="[source](https://news.example.test/story)\n",
            generated_at="2026-07-13T06:01:00+08:00",
            html_url="https://agihunt.info/report/2026-07-13",
        )

    def fetch_channel_items(self, channel: str, day: str):
        self.calls.append((channel, day))
        self.network_requests += 1
        return self.items


class CacheOnlySmokeClient(SmokeClient):
    @property
    def stats(self) -> dict[str, int]:
        return {"network_requests": 0, "cache_hits": 3}


def test_phase_zero_smoke_is_serial_bounded_and_deidentified() -> None:
    client = SmokeClient()

    result = run_smoke(client, day=DAY, channel="models")

    assert result["healthy"] is True
    assert client.calls == [("channels", ""), ("report", DAY), ("models", DAY)]
    assert result["transport"] == {
        "network_requests": 3,
        "cache_hits": 0,
        "request_limit": MAX_NETWORK_REQUESTS,
    }
    serialized = json.dumps(result)
    assert "Sensitive title" not in serialized
    assert "Private source content" not in serialized
    assert "Private author" not in serialized
    assert "secret=not-retained" not in serialized
    assert result["channel_items"]["samples"][0]["url_host"] == "news.example.test"
    assert result["report"]["markdown_link_hosts"] == {"news.example.test": 1}


def test_report_not_ready_remains_a_valid_phase_zero_outcome() -> None:
    client = SmokeClient(report_error=AgihuntReportNotReadyError("not ready"))

    result = run_smoke(client, day=DAY, channel="models")

    assert result["healthy"] is True
    assert result["report"] == {
        "status": "not_ready",
        "code": "agihunt_report_not_ready",
    }
    assert client.network_requests == 3


def test_phase_zero_smoke_rejects_empty_channel_or_budget_overrun() -> None:
    empty = run_smoke(SmokeClient(items=[]), day=DAY, channel="models")
    assert empty["healthy"] is False
    assert "channel items endpoint returned no items" in empty["errors"]

    client = SmokeClient()
    client.network_requests = MAX_NETWORK_REQUESTS
    exceeded = run_smoke(client, day=DAY, channel="models")
    assert exceeded["healthy"] is False
    assert "network request count exceeded Phase 0 limit" in exceeded["errors"]


def test_phase_zero_smoke_does_not_treat_a_cache_only_run_as_live_evidence() -> None:
    result = run_smoke(CacheOnlySmokeClient(), day=DAY, channel="models")

    assert result["healthy"] is False
    assert "cache-only run is not Phase 0 live evidence" in result["errors"]
