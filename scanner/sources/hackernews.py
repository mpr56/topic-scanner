"""Hacker News via the public Algolia API: front page, or story search over the last day."""
from datetime import UTC, datetime
from urllib.parse import quote_plus

import httpx

from scanner.schemas import SourceConfig
from scanner.sources.base import RawArticle, get_json

BASE = "https://hn.algolia.com/api/v1"


def build_urls(cfg: SourceConfig, now: datetime) -> list[str]:
    if cfg.mode == "feed":
        return [f"{BASE}/search?tags=front_page&hitsPerPage={cfg.limit}"]
    since = int(now.timestamp()) - 86400
    return [
        f"{BASE}/search_by_date?query={quote_plus(q)}&tags=story&hitsPerPage={cfg.limit}"
        f"&numericFilters=created_at_i%3E{since}"
        for q in cfg.queries
    ]


def parse_hits(payload: dict) -> list[RawArticle]:
    articles = []
    for hit in payload.get("hits", []):
        created = hit.get("created_at_i")
        articles.append(RawArticle(
            source="hackernews", outlet="Hacker News", title=hit.get("title") or "",
            url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            published_at=datetime.fromtimestamp(created, UTC) if created else None,
            engagement=int(hit.get("points") or 0) + int(hit.get("num_comments") or 0),
        ))
    return articles


class HackerNewsSource:
    name = "hackernews"

    def fetch(self, cfg: SourceConfig, http: httpx.Client, now: datetime) -> list[RawArticle]:
        out: list[RawArticle] = []
        for url in build_urls(cfg, now):
            out.extend(parse_hits(get_json(http, url))[: cfg.limit])
        return out
