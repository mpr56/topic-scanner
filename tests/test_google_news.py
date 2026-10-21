from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scanner.schemas import SourceConfig
from scanner.sources.base import SourceError
from scanner.sources.google_news import GoogleNewsSource, build_urls, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_urls_modes():
    loc = "hl=en-US&gl=US&ceid=US:en"
    assert build_urls(SourceConfig(type="google_news", mode="feed")) == [f"https://news.google.com/rss?{loc}"]
    assert build_urls(SourceConfig(type="google_news", mode="feed", sections=["world"])) == \
        [f"https://news.google.com/rss/headlines/section/topic/WORLD?{loc}"]
    assert build_urls(SourceConfig(type="google_news", queries=["tesla roadster"])) == \
        [f"https://news.google.com/rss/search?q=tesla+roadster+when%3A1d&{loc}"]
    assert "gl=AU" in build_urls(SourceConfig(type="google_news", mode="feed", region="AU"))[0]


def test_unknown_section_raises():
    with pytest.raises(SourceError):
        build_urls(SourceConfig(type="google_news", mode="feed", sections=["memes"]))


def test_parse_feed():
    a, b = parse_feed((FIXTURES / "google_news.xml").read_text())
    assert (a.title, a.outlet, a.source) == ("Tesla Roadster flies", "Reuters", "google_news")
    assert a.published_at == datetime(2026, 10, 21, 10, tzinfo=UTC)
    assert "<a" not in a.snippet
    assert (b.outlet, b.published_at) == ("BBC News", None)


def test_fetch_follows_redirects(now):
    xml = (FIXTURES / "google_news.xml").read_text()

    def handler(req):
        if "section" in req.url.path:
            return httpx.Response(302, headers={"location": "https://news.google.com/rss/topics/XYZ"})
        return httpx.Response(200, text=xml)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = SourceConfig(type="google_news", mode="feed", sections=["WORLD"])
    assert len(GoogleNewsSource().fetch(cfg, http, now)) == 2


def test_fetch_raises_source_error_on_http_failure(now):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(SourceError, match="503"):
        GoogleNewsSource().fetch(SourceConfig(type="google_news", mode="feed"), http, now)
