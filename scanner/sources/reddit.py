"""Reddit: search, or hot posts from chosen subreddits. Optional app-only OAuth for cloud IPs."""
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus

import httpx

from scanner.schemas import SourceConfig
from scanner.sources.base import RawArticle, SourceError, clean_snippet, get_json

PUBLIC_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


def build_urls(cfg: SourceConfig, base: str = PUBLIC_BASE) -> list[str]:
    if cfg.mode == "feed":
        if not cfg.subreddits:
            raise SourceError("reddit feed mode needs at least one subreddit")
        return [f"{base}/r/{sub.strip().removeprefix('r/')}/hot.json?limit={cfg.limit}" for sub in cfg.subreddits]
    return [f"{base}/search.json?q={quote_plus(q)}&sort=new&t=day&limit={cfg.limit}" for q in cfg.queries]


def parse_listing(payload: dict) -> list[RawArticle]:
    articles = []
    for child in (payload.get("data") or {}).get("children", []):
        post = child.get("data") or {}
        if post.get("stickied"):
            continue
        url = PUBLIC_BASE + post.get("permalink", "") if post.get("is_self") else post.get("url", "")
        created = post.get("created_utc")
        articles.append(RawArticle(
            source="reddit", outlet=f"r/{post.get('subreddit', '')}", title=post.get("title", ""), url=url,
            published_at=datetime.fromtimestamp(created, UTC) if created else None,
            snippet=clean_snippet(post.get("selftext", "")),
            engagement=int(post.get("score") or 0) + int(post.get("num_comments") or 0),
        ))
    return articles


class RedditSource:
    name = "reddit"

    def __init__(self, client_id: str = "", client_secret: str = "", user_agent: str = "topic-scanner/0.1"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self._token: str | None = None
        self._token_expires = 0.0

    def _get_token(self, http: httpx.Client) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        try:
            resp = http.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                             auth=(self.client_id, self.client_secret), headers={"User-Agent": self.user_agent})
        except httpx.HTTPError as exc:
            raise SourceError(f"reddit token request failed: {exc}") from exc
        if not resp.is_success:
            raise SourceError(f"{resp.status_code} from reddit token endpoint")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + float(body.get("expires_in", 3600)) - 60
        return self._token

    def fetch(self, cfg: SourceConfig, http: httpx.Client, now: datetime) -> list[RawArticle]:
        headers = {"User-Agent": self.user_agent}
        base = PUBLIC_BASE
        if self.client_id and self.client_secret:
            headers["Authorization"] = f"bearer {self._get_token(http)}"
            base = OAUTH_BASE
        out: list[RawArticle] = []
        for url in build_urls(cfg, base):
            out.extend(parse_listing(get_json(http, url, headers=headers))[: cfg.limit])
        return out
