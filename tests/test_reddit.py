import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from scanner.schemas import SourceConfig
from scanner.sources.base import SourceError
from scanner.sources.reddit import RedditSource, build_urls, parse_listing

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_urls():
    assert build_urls(SourceConfig(type="reddit", queries=["tesla roadster"])) == \
        ["https://www.reddit.com/search.json?q=tesla+roadster&sort=new&t=day&limit=25"]
    assert build_urls(SourceConfig(type="reddit", mode="feed", subreddits=["worldnews"], limit=10)) == \
        ["https://www.reddit.com/r/worldnews/hot.json?limit=10"]
    with pytest.raises(SourceError):
        build_urls(SourceConfig(type="reddit", mode="feed"))


def test_parse_listing():
    link, self_post = parse_listing(json.loads((FIXTURES / "reddit_listing.json").read_text()))
    assert (link.outlet, link.engagement) == ("r/worldnews", 1500)
    assert link.published_at == datetime.fromtimestamp(1792576800, UTC)
    assert self_post.url == "https://www.reddit.com/r/news/comments/1/x/"
    assert self_post.snippet == "Body"


def test_oauth_token_fetched_once_and_used(now):
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        return httpx.Response(200, json={"data": {"children": []}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    src = RedditSource("id", "secret")
    cfg = SourceConfig(type="reddit", mode="feed", subreddits=["a", "b"])
    src.fetch(cfg, http, now)
    assert [r.url.path for r in seen].count("/api/v1/access_token") == 1
    api = [r for r in seen if r.url.host == "oauth.reddit.com"]
    assert len(api) == 2 and api[0].headers["authorization"] == "bearer T"
    assert all("user-agent" in r.headers for r in seen)


def test_blocked_raises_source_error(now):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(SourceError, match="403"):
        RedditSource().fetch(SourceConfig(type="reddit", queries=["x"]), http, now)
