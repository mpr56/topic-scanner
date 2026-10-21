"""Pure text helpers for deduplication: URL canonicalisation, headline matching, exclude terms."""
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ref_src", "cmpid", "smid"}
OUTLET_SEPARATORS = (" - ", " | ", " — ")
MAX_OUTLET_WORDS = 4


def canonicalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    try:
        if "://" not in url:
            url = "https://" + url
        parts = urlsplit(url)
        scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        netloc = host + (f":{parts.port}" if parts.port else "")
        path = parts.path
        if len(path) > 1:
            path = path.rstrip("/")
        query = sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.startswith("utm_") and k not in TRACKING_PARAMS
        )
        return urlunsplit((scheme, netloc, path, urlencode(query), ""))
    except ValueError:
        return url


def normalize_title(title: str) -> str:
    cut = max(title.rfind(sep) for sep in OUTLET_SEPARATORS)
    if cut > 0:
        suffix = title[cut + 3:]
        if len(suffix.split()) <= MAX_OUTLET_WORDS:
            title = title[:cut]
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def titles_match(a: str, b: str, threshold: float = 0.85) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def matches_exclude(text: str, exclude: list[str]) -> bool:
    return any(
        re.search(rf"\b{re.escape(term.strip())}\b", text, re.IGNORECASE)
        for term in exclude if term.strip()
    )
