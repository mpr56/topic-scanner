from dataclasses import dataclass

from scanner.llm.base import LLMResult
from scanner.sources.base import RawArticle


@dataclass
class FakeCall:
    system: str
    user: str
    model: str


class FakeLLM:
    """Returns queued responses in order; raises queued exceptions; fails on unexpected calls."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[FakeCall] = []

    def complete_json(self, system: str, user: str, *, model: str) -> LLMResult:
        self.calls.append(FakeCall(system, user, model))
        if not self._responses:
            raise AssertionError("unexpected LLM call")
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return LLMResult(resp, 100)


class FakeSource:
    def __init__(self, name: str, articles: list[RawArticle] | Exception):
        self.name = name
        self.articles = articles
        self.configs = []

    def fetch(self, cfg, http, now):
        self.configs.append(cfg)
        if isinstance(self.articles, Exception):
            raise self.articles
        return list(self.articles)
