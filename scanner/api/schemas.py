"""Request and response bodies for the HTTP API."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from scanner.schemas import ScoringConfig, SegmentDefinition


class LoginIn(BaseModel):
    password: str


class AnalyzeIn(BaseModel):
    name: str = Field(min_length=1)
    examples: list[str] = Field(min_length=1)
    note: str = ""


class ReanalyzeIn(BaseModel):
    examples: list[str] | None = Field(None, min_length=1)
    note: str | None = None


class DraftOut(BaseModel):
    definition: SegmentDefinition


class SegmentIn(BaseModel):
    name: str = Field(min_length=1)
    examples: list[str] = Field(min_length=1)
    note: str = ""
    definition: SegmentDefinition
    scoring: ScoringConfig = ScoringConfig()
    interval_minutes: int = Field(120, ge=60, le=1440)
    active: bool = True


class SegmentPatch(BaseModel):
    name: str | None = Field(None, min_length=1)
    examples: list[str] | None = Field(None, min_length=1)
    note: str | None = None
    definition: SegmentDefinition | None = None
    scoring: ScoringConfig | None = None
    interval_minutes: int | None = Field(None, ge=60, le=1440)
    active: bool | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    segment_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    fetched: int
    new_articles: int
    new_stories: int
    updated_stories: int
    scored: int
    errors: list[dict]


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    examples: list[str]
    note: str
    definition: SegmentDefinition
    definition_version: int
    scoring: ScoringConfig
    interval_minutes: int
    active: bool
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_run: RunOut | None = None


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    outlet: str
    title: str
    url: str
    published_at: datetime | None
    engagement: int


class ScoresOut(BaseModel):
    match: float | None
    buzz: float
    freshness: float
    combined: float | None


class StoryOut(BaseModel):
    id: int
    segment_id: int
    headline: str
    status: str
    scores: ScoresOut
    reason: str | None
    scored_version: int | None
    published_at: datetime | None
    first_seen: datetime
    last_seen: datetime
    runs_seen: int
    dismissed: bool
    outlets: list[str]
    articles: list[ArticleOut]
