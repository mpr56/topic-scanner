from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from scanner.schemas import ScoringConfig, SegmentDefinition


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo on its own)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware UTC")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    examples: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[dict] = mapped_column(JSON)
    definition_version: Mapped[int] = mapped_column(Integer, default=1)
    scoring: Mapped[dict] = mapped_column(JSON, default=lambda: ScoringConfig().model_dump())
    interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    stories: Mapped[list["Story"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan", passive_deletes=True)
    runs: Mapped[list["Run"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan", passive_deletes=True)

    def get_definition(self) -> SegmentDefinition:
        return SegmentDefinition.model_validate(self.definition)

    def get_scoring(self) -> ScoringConfig:
        return ScoringConfig.model_validate(self.scoring)


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    headline: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    match_score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    scored_version: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    runs_seen: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_run_id: Mapped[int | None] = mapped_column(Integer)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    segment: Mapped[Segment] = relationship(back_populates="stories")
    articles: Mapped[list["Article"]] = relationship(
        back_populates="story", cascade="all, delete-orphan", passive_deletes=True)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("segment_id", "canonical_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    outlet: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(String(2000))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    snippet: Mapped[str] = mapped_column(Text, default="")
    engagement: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime)

    story: Mapped[Story] = relationship(back_populates="articles")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_articles: Mapped[int] = mapped_column(Integer, default=0)
    new_stories: Mapped[int] = mapped_column(Integer, default=0)
    updated_stories: Mapped[int] = mapped_column(Integer, default=0)
    scored: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)

    segment: Mapped[Segment] = relationship(back_populates="runs")
