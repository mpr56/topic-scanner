"""The two AI jobs: draft a segment definition from examples, and group + score a batch of stories."""
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, Field, ValidationError

from scanner.llm.base import LLMClient, LLMError, MalformedOutput
from scanner.schemas import SegmentDefinition, SourceConfig
from scanner.sources.google_news import SECTIONS

T = TypeVar("T")

ANALYZE_SYSTEM = f"""You help a person set up a personal trend tracker.
They give a segment name, a few example stories or items, and an optional note.
Work out what the examples have in common and write a tracking definition.

Decide whether the examples share a TOPIC (e.g. EV batteries, a specific company)
or a KIND OF STORY (e.g. "huge news everyone is talking about", regardless of topic).
For a kind of story, prefer FEED mode sources (top/hot lists), because no search query can express it.
For a topic, prefer SEARCH mode with a few short, specific queries.

Available sources:
- google_news: mode "search" uses "queries"; mode "feed" uses "sections" (empty list = top stories).
  Valid sections: {", ".join(sorted(SECTIONS))}.
- reddit: mode "search" uses "queries"; mode "feed" REQUIRES "subreddits" (names without r/).
- hackernews: mode "search" uses "queries"; mode "feed" is the front page (no other fields).

Respond with a JSON object only:
{{"summary": "one or two plain sentences describing what is tracked",
  "include": ["criteria a matching item has"],
  "exclude": ["short keywords or phrases to filter out"],
  "sources": [{{"type": "...", "mode": "search|feed", "queries": [], "subreddits": [], "sections": []}}]}}"""

CLASSIFY_SYSTEM = """You sort and rate news items for a personal trend tracker.
For each candidate:
1. If it reports the same real-world event as one of the OPEN STORIES, set "same_as" to that story's number.
2. Else if it reports the same event as an EARLIER candidate in this list, set "same_as" to that candidate's key.
3. Otherwise set "same_as" to null and rate "match" from 0 to 10: how well it fits the definition.
   If the definition is about a kind of story (e.g. major news) rather than a topic, "match" means how
   major and widely relevant the event is. Give a one-line "reason".
Respond with a JSON object only:
{"results": [{"key": "<candidate key>", "same_as": <story number, earlier candidate key, or null>, "match": <0-10>, "reason": "..."}]}
Include every candidate key exactly once."""


@dataclass
class Candidate:
    key: str
    title: str
    snippet: str
    source: str


@dataclass
class OpenStory:
    id: int
    headline: str


@dataclass
class Decision:
    key: str
    story_id: int | None
    match: float | None
    reason: str | None
    same_as_key: str | None = None  # another candidate in the same batch describing the same event


class _DraftOut(BaseModel):
    summary: str = Field(min_length=1)
    include: list[str] = []
    exclude: list[str] = []
    sources: list[dict] = []


class _ClassifyOut(BaseModel):
    results: list[dict]


def _call_validated(llm: LLMClient, model: str, system: str, user: str,
                    parse: Callable[[dict], T]) -> tuple[T, int]:
    """Call the model; if the reply doesn't parse, retry once, then give up with LLMError."""
    tokens = 0
    for attempt in range(2):
        try:
            result = llm.complete_json(system, user, model=model)
        except MalformedOutput:
            if attempt == 1:
                raise
            continue
        tokens += result.tokens
        try:
            return parse(result.data), tokens
        except (ValidationError, ValueError, TypeError) as exc:
            if attempt == 1:
                raise LLMError(f"model returned an unexpected shape: {exc}") from exc
    raise AssertionError("unreachable")


def analyze_segment(llm: LLMClient, model: str, name: str, examples: list[str], note: str = "",
                    existing: SegmentDefinition | None = None) -> tuple[SegmentDefinition, int]:
    examples = [e.strip() for e in examples if e.strip()]
    if not examples:
        raise ValueError("at least one example is required")

    lines = [f"Segment name: {name}", "Examples:", *(f"- {e}" for e in examples)]
    if note.strip():
        lines.append(f"Note from the person: {note.strip()}")
    if existing is not None:
        lines.append("Current definition (revise it rather than starting over):")
        lines.append(existing.model_dump_json())

    def parse(data: dict) -> SegmentDefinition:
        draft = _DraftOut.model_validate(data)
        sources = []
        for raw in draft.sources:
            try:
                sources.append(SourceConfig.model_validate(raw))
            except ValidationError:
                continue
        if not sources:
            sources = [SourceConfig(type="google_news", queries=[name])]
        return SegmentDefinition(summary=draft.summary, include=draft.include,
                                 exclude=draft.exclude, sources=sources)

    return _call_validated(llm, model, ANALYZE_SYSTEM, "\n".join(lines), parse)


def classify_batch(llm: LLMClient, model: str, definition: SegmentDefinition,
                   candidates: list[Candidate], open_stories: list[OpenStory]) -> tuple[list[Decision], int]:
    if not candidates:
        return [], 0

    lines = [
        "DEFINITION:",
        definition.summary,
        f"Include: {json.dumps(definition.include)}",
        f"Exclude: {json.dumps(definition.exclude)}",
        "",
        "OPEN STORIES:",
        *([f"#{s.id}: {s.headline}" for s in open_stories] or ["(none)"]),
        "",
        "CANDIDATES:",
        *(f"{c.key}: {c.title} — {c.snippet[:200]} ({c.source})" for c in candidates),
    ]
    open_ids = {s.id for s in open_stories}
    keys = {c.key for c in candidates}

    def parse(data: dict) -> list[Decision]:
        out: dict[str, Decision] = {}
        for item in _ClassifyOut.model_validate(data).results:
            key = item.get("key")
            if key not in keys or key in out:
                continue
            same_as = item.get("same_as")
            if isinstance(same_as, str):
                stripped = same_as.strip()
                if stripped in keys:
                    if stripped != key:
                        out[key] = Decision(key, None, None, None, same_as_key=stripped)
                        continue
                    same_as = None
                elif stripped.lstrip("#").isdigit():
                    same_as = int(stripped.lstrip("#"))
            if isinstance(same_as, int) and not isinstance(same_as, bool) and same_as in open_ids:
                out[key] = Decision(key, same_as, None, None)
                continue
            try:
                match = min(10.0, max(0.0, float(item["match"])))
            except (KeyError, TypeError, ValueError):
                continue
            out[key] = Decision(key, None, match, str(item.get("reason") or ""))
        return list(out.values())

    return _call_validated(llm, model, CLASSIFY_SYSTEM, "\n".join(lines), parse)
