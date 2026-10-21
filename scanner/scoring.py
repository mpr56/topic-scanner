"""Non-AI scoring: buzz and freshness, plus the weighted combination with the AI match score."""
from dataclasses import dataclass
from datetime import datetime
from math import log10

from scanner.models import Story
from scanner.schemas import ScoringConfig


def freshness_score(published_at: datetime | None, first_seen: datetime, now: datetime,
                    cfg: ScoringConfig) -> float:
    when = min(published_at or first_seen, now)
    age_h = (now - when).total_seconds() / 3600
    if age_h <= cfg.fresh_full_hours:
        return 10.0
    if age_h >= cfg.fresh_zero_hours:
        return 0.0
    return 10 * (cfg.fresh_zero_hours - age_h) / (cfg.fresh_zero_hours - cfg.fresh_full_hours)


def buzz_score(outlets: int, runs_seen: int, engagement: int, cfg: ScoringConfig) -> float:
    parts = {
        "outlets": min(1, max(0, outlets - 1) / 4),        # 5+ distinct outlets = full
        "runs": min(1, max(0, runs_seen - 1) / 5),         # seen in 6+ runs = full
        "engagement": min(1, log10(1 + max(0, engagement)) / 4),  # 10k = full
    }
    enabled = [parts[s] for s in cfg.buzz_signals]
    return 10 * sum(enabled) / len(enabled) if enabled else 0.0


def combined_score(match: float | None, buzz: float, freshness: float,
                   cfg: ScoringConfig) -> float | None:
    if match is None:
        return None
    w = cfg.weights
    total = (w.match * match + w.buzz * buzz + w.freshness * freshness) / (w.match + w.buzz + w.freshness)
    return round(min(10.0, max(1.0, total)), 1)


@dataclass
class StoryScores:
    match: float | None
    buzz: float
    freshness: float
    combined: float | None


def score_story(story: Story, cfg: ScoringConfig, now: datetime) -> StoryScores:
    outlets = len({a.outlet for a in story.articles})
    engagement = sum(a.engagement for a in story.articles)
    buzz = round(buzz_score(outlets, story.runs_seen, engagement, cfg), 1)
    fresh = round(freshness_score(story.published_at, story.first_seen, now, cfg), 1)
    return StoryScores(story.match_score, buzz, fresh, combined_score(story.match_score, buzz, fresh, cfg))
