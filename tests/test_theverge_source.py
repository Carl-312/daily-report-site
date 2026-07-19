from __future__ import annotations

from datetime import datetime, timezone

from sources.theverge import TheVergeSource


ATOM_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title type="html"><![CDATA[OpenAI&#8217;s new agent ships today]]></title>
    <link rel="alternate" href="https://www.theverge.com/ai-artificial-intelligence/123/openai-agent"/>
    <published>2026-07-16T08:00:00-04:00</published>
    <summary type="html"><![CDATA[<p>A <strong>useful</strong> summary.</p>]]></summary>
  </entry>
  <entry>
    <title>Google updates its AI platform</title>
    <link rel="alternate" href="https://www.theverge.com/tech/456/google-ai"/>
    <published>2026-07-15T08:00:00-04:00</published>
    <summary>Platform details.</summary>
  </entry>
  <entry>
    <title>This old story must be filtered out</title>
    <link rel="alternate" href="https://www.theverge.com/tech/789/old-story"/>
    <published>2026-07-14T08:00:00-04:00</published>
    <summary>Old details.</summary>
  </entry>
  <entry>
    <title>External links are not Verge source articles</title>
    <link rel="alternate" href="https://example.com/external"/>
    <published>2026-07-16T08:00:00-04:00</published>
  </entry>
</feed>
"""


class Response:
    content = ATOM_FEED

    @staticmethod
    def raise_for_status() -> None:
        return None


def test_fetch_uses_atom_dates_and_cleans_html(monkeypatch) -> None:
    source = TheVergeSource()
    requested: list[str] = []

    def get(url, **kwargs):
        requested.append(url)
        assert kwargs["use_environment_proxy"] is True
        return Response()

    monkeypatch.setattr(source, "_get", get)

    articles = source.fetch(
        max_articles=14,
        reference_dt=datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc),
    )

    assert requested == [source.FEED_URL]
    assert [article.title for article in articles] == [
        "OpenAI\u2019s new agent ships today",
        "Google updates its AI platform",
    ]
    assert articles[0].description == "A useful summary."
    assert articles[0].publish_time == "2026-07-16T08:00:00-04:00"
    assert all(article.source == "theverge" for article in articles)
    assert source.last_fetched_count == 3
    assert source.last_accepted_count == 2
    assert source.last_status == "ok"


def test_fetch_honors_article_limit(monkeypatch) -> None:
    source = TheVergeSource()
    monkeypatch.setattr(source, "_get", lambda *_args, **_kwargs: Response())

    articles = source.fetch(
        max_articles=1,
        reference_dt=datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc),
    )

    assert len(articles) == 1
    assert source.last_fetched_count == 3
    assert source.last_accepted_count == 1


def test_recent_window_rejects_stale_and_future_timestamps() -> None:
    source = TheVergeSource()
    reference = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)

    assert source._is_recent("2026-07-14T12:00:00+00:00", reference)
    assert not source._is_recent("2026-07-14T11:59:59+00:00", reference)
    assert source._is_recent("2026-07-16T12:05:00+00:00", reference)
    assert not source._is_recent("2026-07-16T12:05:01+00:00", reference)
    assert not source._is_recent("not-a-date", reference)
