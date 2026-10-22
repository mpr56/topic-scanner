"""Domain models stored as JSON on a segment: its definition, sources and scoring settings."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["google_news", "reddit", "hackernews"]
BuzzSignal = Literal["outlets", "runs", "engagement"]


class SourceConfig(BaseModel):
    type: SourceType
    mode: Literal["search", "feed"] = "search"
    queries: list[str] = []
    subreddits: list[str] = []
    sections: list[str] = []
    region: str = "US"
    limit: int = Field(25, ge=1, le=100)
    enabled: bool = True


class SegmentDefinition(BaseModel):
    summary: str
    include: list[str] = []
    exclude: list[str] = []
    sources: list[SourceConfig] = []


class ScoringWeights(BaseModel):
    match: float = Field(0.5, ge=0)
    buzz: float = Field(0.3, ge=0)
    freshness: float = Field(0.2, ge=0)

    @model_validator(mode="after")
    def _some_weight(self):
        if self.match + self.buzz + self.freshness <= 0:
            raise ValueError("at least one scoring weight must be positive")
        return self


class ScoringConfig(BaseModel):
    weights: ScoringWeights = ScoringWeights()
    fresh_full_hours: float = Field(2, ge=0)
    fresh_zero_hours: float = 48
    buzz_signals: list[BuzzSignal] = ["outlets", "runs", "engagement"]
    max_new_stories_per_run: int = Field(40, ge=1)

    @model_validator(mode="after")
    def _window_order(self):
        if self.fresh_zero_hours <= self.fresh_full_hours:
            raise ValueError("fresh_zero_hours must be greater than fresh_full_hours")
        return self
