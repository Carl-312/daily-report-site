from datetime import datetime, timezone

from sources.techcrunch import TechCrunchSource


FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>OpenAI launches a documented enterprise agent platform</title>
      <link>https://techcrunch.com/2026/07/22/openai-enterprise-agent/</link>
      <pubDate>Wed, 22 Jul 2026 20:49:03 +0000</pubDate>
      <description><![CDATA[
        <p>OpenAI launched an enterprise agent platform with deployment controls.</p>
      ]]></description>
    </item>
    <item>
      <title>Old artificial intelligence story outside the window</title>
      <link>https://techcrunch.com/2026/07/18/old-ai-story/</link>
      <pubDate>Sat, 18 Jul 2026 20:49:03 +0000</pubDate>
      <description>Old evidence text should be parsed but filtered by age.</description>
    </item>
  </channel>
</rss>
"""


class Response:
    content = FEED

    @staticmethod
    def raise_for_status() -> None:
        return None


def test_official_ai_feed_produces_direct_publishable_stories(monkeypatch) -> None:
    source = TechCrunchSource()
    monkeypatch.setattr(source, "_get", lambda *_args, **_kwargs: Response())

    articles = source.fetch(
        reference_dt=datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)
    )

    assert len(articles) == 1
    article = articles[0]
    assert article.source == "techcrunch"
    assert article.kind == "story"
    assert article.evidence_status == "direct"
    assert article.description.startswith("OpenAI launched")
    assert article.publish_time == "Wed, 22 Jul 2026 20:49:03 +0000"
    assert article.provenance == {
        "input_kind": "story",
        "retrieval": "official_ai_rss",
        "publish_time_semantics": "source_published_at",
    }
    assert source.last_fetched_count == 2
    assert source.last_accepted_count == 1
    assert source.last_status == "ok"
