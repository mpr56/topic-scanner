import pytest

from scanner.ai_tasks import Candidate, Decision, OpenStory, analyze_segment, classify_batch
from scanner.llm.base import LLMError
from scanner.schemas import SegmentDefinition, SourceConfig
from tests.fakes import FakeLLM

GOOD = {"summary": "Major world events", "include": ["global impact"], "exclude": ["gossip"],
        "sources": [{"type": "google_news", "mode": "feed", "sections": ["WORLD"]},
                    {"type": "twitter", "mode": "feed"}]}


def test_analyze_parses_and_drops_unknown_sources():
    llm = FakeLLM(GOOD)
    d, tokens = analyze_segment(llm, "big-model", "Big news", ["Tesla Roadster flies", "France turmoil"], "skip celebs")
    assert d.summary == "Major world events" and [s.type for s in d.sources] == ["google_news"]
    assert tokens == 100 and llm.calls[0].model == "big-model"
    for text in ["Tesla Roadster flies", "France turmoil", "skip celebs"]:
        assert text in llm.calls[0].user


def test_analyze_falls_back_to_google_search():
    d, _ = analyze_segment(FakeLLM({**GOOD, "sources": []}), "m", "Big news", ["x"])
    assert d.sources == [SourceConfig(type="google_news", queries=["Big news"])]


def test_analyze_retries_once_then_fails():
    assert analyze_segment(FakeLLM({"nope": 1}, GOOD), "m", "n", ["x"])[1] == 200
    with pytest.raises(LLMError):
        analyze_segment(FakeLLM({"nope": 1}, {"nope": 2}), "m", "n", ["x"])


def test_analyze_requires_examples():
    with pytest.raises(ValueError):
        analyze_segment(FakeLLM(), "m", "n", ["  "])


def test_analyze_includes_existing_definition():
    llm = FakeLLM(GOOD)
    analyze_segment(llm, "m", "n", ["x"], existing=SegmentDefinition(summary="OLD SUMMARY"))
    assert "OLD SUMMARY" in llm.calls[0].user


def test_classify_sanitises_response():
    llm = FakeLLM({"results": [
        {"key": "c0", "same_as": 7, "match": 9, "reason": "dup"},
        {"key": "c1", "same_as": 999, "match": 6, "reason": "new"},
        {"key": "c2", "same_as": None, "match": 12, "reason": "huge"},
        {"key": "zz", "same_as": None, "match": 5, "reason": "?"},
    ]})
    cands = [Candidate(f"c{i}", f"t{i}", "", "google_news") for i in range(4)]
    out, tokens = classify_batch(llm, "m", SegmentDefinition(summary="S", exclude=["gossip"]),
                                 cands, [OpenStory(7, "Tesla Roadster flies")])
    by = {d.key: d for d in out}
    assert by["c0"] == Decision("c0", 7, None, None)
    assert (by["c1"].story_id, by["c1"].match) == (None, 6)
    assert by["c2"].match == 10
    assert "c3" not in by and "zz" not in by and tokens == 100
    assert "#7: Tesla Roadster flies" in llm.calls[0].user and "gossip" in llm.calls[0].user


def test_classify_empty_makes_no_call():
    assert classify_batch(FakeLLM(), "m", SegmentDefinition(summary="S"), [], []) == ([], 0)
