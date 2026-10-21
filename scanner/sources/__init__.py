from scanner.config import Settings
from scanner.sources.base import Source
from scanner.sources.google_news import GoogleNewsSource


def build_sources(settings: Settings) -> dict[str, Source]:
    return {"google_news": GoogleNewsSource()}
