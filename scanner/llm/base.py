"""The one interface every AI call goes through, so providers can be swapped or chained later."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    data: dict
    tokens: int


class LLMError(Exception):
    """The provider failed or returned something unusable."""


class MalformedOutput(LLMError):
    """The provider itself rejected the model's output as invalid JSON; worth one retry."""


class RateLimited(LLMError):
    """The provider kept rate-limiting us after retries."""


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, *, model: str) -> LLMResult: ...
