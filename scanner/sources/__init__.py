from scanner.config import Settings
from scanner.sources.base import Source
from scanner.sources.google_news import GoogleNewsSource
from scanner.sources.hackernews import HackerNewsSource
from scanner.sources.reddit import RedditSource


def build_sources(settings: Settings) -> dict[str, Source]:
    return {
        "google_news": GoogleNewsSource(),
        "reddit": RedditSource(settings.reddit_client_id, settings.reddit_client_secret, settings.user_agent),
        "hackernews": HackerNewsSource(),
    }
