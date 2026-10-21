"""Google News RSS: search feeds, top stories and topic sections."""
from calendar import timegm
from datetime import UTC, datetime
from urllib.parse import quote_plus

import feedparser
import httpx

from scanner.schemas import SourceConfig
from scanner.sources.base import RawArticle, SourceError, clean_snippet, get_text

SECTIONS = {"WORLD", "NATION", "BUSINESS", "TECHNOLOGY", "ENTERTAINMENT", "SPORTS", "SCIENCE", "HEALTH"}
BASE = "https://news.google.com/rss"


def build_urls(cfg: SourceConfig) -> list[str]:
    r = cfg.region.upper()
    locale = f"hl=en-{r}&gl={r}&ceid={r}:en"
    if cfg.mode == "feed":
        if not cfg.sections:
            return [f"{BASE}?{locale}"]
        urls = []
        for section in cfg.sections:
            s = section.strip().upper()
            if s not in SECTIONS:
                raise SourceError(f"unknown Google News section {section!r}")
            urls.append(f"{BASE}/headlines/section/topic/{s}?{locale}")
        return urls
    return [f"{BASE}/search?q={quote_plus(q + ' when:1d')}&{locale}" for q in cfg.queries]


def parse_feed(xml: str) -> list[RawArticle]:
    feed = feedparser.parse(xml)
    if not feed.entries and not feed.version:
        raise SourceError("Google News returned something that is not an RSS feed")
    articles = []
    for entry in feed.entries:
        outlet = (entry.get("source") or {}).get("title") or "Google News"
        title = entry.get("title", "")
        if title.endswith(f" - {outlet}"):
            title = title[: -len(f" - {outlet}")]
        parsed = entry.get("published_parsed")
        published = datetime.fromtimestamp(timegm(parsed), UTC) if parsed else None
        articles.append(RawArticle(
            source="google_news", outlet=outlet, title=title, url=entry.get("link", ""),
            published_at=published, snippet=clean_snippet(entry.get("summary", "")),
        ))
    return articles


class GoogleNewsSource:
    name = "google_news"

    def fetch(self, cfg: SourceConfig, http: httpx.Client, now: datetime) -> list[RawArticle]:
        out: list[RawArticle] = []
        for url in build_urls(cfg):
            out.extend(parse_feed(get_text(http, url))[: cfg.limit])
        return out
