"""Groq via its OpenAI-compatible chat completions endpoint, in JSON mode."""
import json
import time
from collections.abc import Callable

import httpx

from scanner.llm.base import LLMError, LLMResult, RateLimited

URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRY_SLEEP = 20.0


class GroqClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 3):
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=60)
        self.sleep = sleep
        self.max_retries = max_retries

    def complete_json(self, system: str, user: str, *, model: str) -> LLMResult:
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not set")
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.http.post(URL, json=body, headers=headers, timeout=60)
            except httpx.HTTPError as exc:
                raise LLMError(f"Groq request failed: {exc}") from exc
            if resp.status_code != 429:
                break
            if attempt == self.max_retries:
                raise RateLimited("Groq rate limit persisted after retries")
            try:
                wait = float(resp.headers.get("retry-after") or 2)
            except ValueError:
                wait = 2.0
            self.sleep(min(wait, MAX_RETRY_SLEEP))
        if not resp.is_success:
            raise LLMError(f"Groq returned {resp.status_code}: {resp.text[:200]}")
        try:
            payload = resp.json()
            data = json.loads(payload["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("Groq returned an unreadable response") from exc
        if not isinstance(data, dict):
            raise LLMError("Groq returned JSON that is not an object")
        return LLMResult(data, int((payload.get("usage") or {}).get("total_tokens") or 0))
