import json
from pathlib import Path

from scanner.schemas import SourceConfig
from scanner.sources.hackernews import build_urls, parse_hits

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_urls(now):
    assert build_urls(SourceConfig(type="hackernews", mode="feed"), now) == \
        ["https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=25"]
    [u] = build_urls(SourceConfig(type="hackernews", queries=["tesla roadster"]), now)
    assert u.startswith("https://hn.algolia.com/api/v1/search_by_date?query=tesla+roadster&tags=story")
    assert f"created_at_i%3E{int(now.timestamp()) - 86400}" in u


def test_parse_hits():
    a, b = parse_hits(json.loads((FIXTURES / "hn_hits.json").read_text()))
    assert (a.engagement, a.outlet) == (330, "Hacker News")
    assert b.url == "https://news.ycombinator.com/item?id=42" and b.engagement >= 0
