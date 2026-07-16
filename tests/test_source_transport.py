from __future__ import annotations

import pytest
import requests

from sources.base import BaseSource


class Source(BaseSource):
    def fetch(self, max_articles=14, reference_dt=None):
        return []


class Session:
    trust_env = False

    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0
        self.last_kwargs = {}

    def get(self, *args, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    exc = requests.HTTPError(f"HTTP {status}")
    exc.response = response
    return exc


def response(status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    return result


def test_get_retries_timeout_and_retryable_http_statuses() -> None:
    source = Source()
    source.session = Session([requests.Timeout("timeout"), error(503), response()])
    sleeps = []

    result = source._get(
        "https://example.test", sleep=sleeps.append, random_value=lambda: 0
    )

    assert result is not None
    assert source.session.calls == 3
    assert source.last_attempts == 3
    assert sleeps == [0.1, 0.2]


def test_get_does_not_retry_non_retryable_client_error() -> None:
    source = Source()
    source.session = Session([error(401)])

    with pytest.raises(requests.HTTPError):
        source._get("https://example.test", sleep=lambda _: None)
    assert source.session.calls == 1
    assert source.last_attempts == 1


def test_get_can_use_explicit_environment_proxy_without_trusting_netrc(
    monkeypatch,
) -> None:
    source = Source()
    source.session = Session([response()])
    proxy = {"https": "http://proxy.example.test:8080"}
    monkeypatch.setattr("sources.base.get_environ_proxies", lambda _url: proxy)

    source._get(
        "https://example.test",
        use_environment_proxy=True,
        sleep=lambda _: None,
    )

    assert source.session.trust_env is False
    assert source.session.last_kwargs["proxies"] == proxy
