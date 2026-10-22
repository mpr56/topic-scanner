from sqlalchemy import select
from sqlalchemy.orm import Session

from scanner.models import Segment
from scanner.schemas import ScoringConfig, SegmentDefinition, SourceConfig

BIG_NEWS = "Big news"


def seed_segments(session: Session) -> int:
    """Create the starter "Big news" segment once. Its examples are placeholders to edit."""
    if session.scalar(select(Segment).where(Segment.name == BIG_NEWS)) is not None:
        return 0
    definition = SegmentDefinition(
        summary="Major, widely-covered world events that a lot of people are talking about right now",
        exclude=["celebrity gossip", "horoscope"],
        sources=[
            SourceConfig(type="google_news", mode="feed"),
            SourceConfig(type="google_news", mode="feed", sections=["WORLD"]),
            SourceConfig(type="reddit", mode="feed", subreddits=["worldnews", "news"]),
            SourceConfig(type="hackernews", mode="feed"),
        ],
    )
    session.add(Segment(
        name=BIG_NEWS,
        examples=["Tesla Roadster flies in public demo", "Political upheaval in France"],
        definition=definition.model_dump(),
        scoring=ScoringConfig().model_dump(),
    ))
    session.commit()
    return 1
