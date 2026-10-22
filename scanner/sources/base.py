"""Source plug-in interface. A source turns one SourceConfig into a list of RawArticles."""
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from scanner.schemas import SourceConfig


@dataclass(frozen=True)
class RawArticle:
    source: str
    outlet: str
    title: str
    url: str
    published_at: datetime | None
    snippet: str = ""
    engagement: int = 0


class SourceError(Exception):
    """A source could not be fetched or parsed. Recorded on the run; never fatal."""


class Source(Protocol):
    name: str

    def fetch(self, cfg: SourceConfig, http: httpx.Client, now: datetime) -> list[RawArticle]: ...


def _get(http: httpx.Client, url: str, **kw) -> httpx.Response:
    try:
        resp = http.get(url, follow_redirects=True, **kw)
    except httpx.HTTPError as exc:
        raise SourceError(f"request to {httpx.URL(url).host} failed: {exc}") from exc
    if not resp.is_success:
        raise SourceError(f"{resp.status_code} from {resp.url.host}")
    return resp


def get_text(http: httpx.Client, url: str, **kw) -> str:
    return _get(http, url, **kw).text


def get_json(http: httpx.Client, url: str, **kw) -> Any:
    resp = _get(http, url, **kw)
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise SourceError(f"invalid JSON from {resp.url.host}") from exc


def clean_snippet(raw_html: str, max_len: int = 300) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw_html or ""))
    return " ".join(text.split())[:max_len]
