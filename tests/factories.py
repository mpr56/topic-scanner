from datetime import UTC, datetime
from itertools import count

from scanner.models import Article, Segment, Story
from scanner.schemas import ScoringConfig, SegmentDefinition, SourceConfig

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
_seq = count(1)


def make_segment(session, **overrides) -> Segment:
    fields = dict(
        name="Big news",
        examples=["Tesla Roadster flies"],
        definition=SegmentDefinition(
            summary="Major news", sources=[SourceConfig(type="google_news", mode="feed")]
        ).model_dump(),
        scoring=ScoringConfig().model_dump(),
    )
    fields.update(overrides)
    seg = Segment(**fields)
    session.add(seg)
    session.flush()
    return seg


def make_story(session, segment, **overrides) -> Story:
    fields = dict(headline=f"Story {next(_seq)}", status="scored", match_score=5.0,
                  first_seen=NOW, last_seen=NOW)
    fields.update(overrides)
    story = Story(segment=segment, **fields)
    session.add(story)
    session.flush()
    return story


def make_article(session, story, **overrides) -> Article:
    n = next(_seq)
    fields = dict(source="google_news", outlet="Reuters", title=story.headline,
                  url=f"https://example.com/{n}", canonical_url=f"https://example.com/{n}",
                  first_seen=NOW, last_seen=NOW)
    fields.update(overrides)
    article = Article(story=story, segment_id=story.segment_id, **fields)
    session.add(article)
    session.flush()
    return article

DEF = {"summary": "Major world events", "sources": [{"type": "google_news", "mode": "feed"}]}
BODY = {"name": "Big news", "examples": ["Tesla Roadster flies"], "definition": DEF}
