import json

import httpx
import pytest

from scanner.llm.base import LLMError, LLMResult, RateLimited
from scanner.llm.groq import GroqClient

sleeps: list[float] = []


@pytest.fixture(autouse=True)
def _reset_sleeps():
    sleeps.clear()


def make(handler) -> GroqClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return GroqClient("key", http=http, sleep=sleeps.append)


def ok(content='{"a": 1}', tokens=321):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"total_tokens": tokens}})


def test_success_shapes_request():
    reqs = []
    client = make(lambda r: reqs.append(r) or ok())
    res = client.complete_json("sys", "usr", model="m1")
    assert res == LLMResult({"a": 1}, 321)
    body = json.loads(reqs[0].content)
    assert body["model"] == "m1" and body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert reqs[0].headers["authorization"] == "Bearer key"


def test_retries_after_429_then_succeeds():
    responses = iter([httpx.Response(429, headers={"retry-after": "2"}), ok()])
    client = make(lambda r: next(responses))
    assert client.complete_json("s", "u", model="m").data == {"a": 1}
    assert sleeps == [2.0]


def test_persistent_429_raises_rate_limited():
    client = make(lambda r: httpx.Response(429))
    with pytest.raises(RateLimited):
        client.complete_json("s", "u", model="m")
    assert len(sleeps) == 3


@pytest.mark.parametrize("resp", [httpx.Response(500), ok(content="not json"), ok(content="[1,2]")])
def test_errors_raise_llm_error(resp):
    with pytest.raises(LLMError):
        make(lambda r: resp).complete_json("s", "u", model="m")


def test_missing_key():
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        GroqClient("").complete_json("s", "u", model="m")
