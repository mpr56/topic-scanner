"""One scan of one segment: fetch, dedupe, group into stories, AI-score within cap and budget."""
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from scanner.ai_tasks import Candidate, Decision, OpenStory, classify_batch
from scanner.llm.base import LLMClient, LLMError
from scanner.models import Article, Run, Segment, Story
from scanner.schemas import SegmentDefinition
from scanner.scoring import score_story
from scanner.sources.base import RawArticle, Source
from scanner.text import canonicalize_url, matches_exclude, titles_match

log = logging.getLogger(__name__)

MIN_GRACE = timedelta(minutes=5)
OPEN_WINDOW = timedelta(hours=48)
RETENTION = timedelta(days=30)
MAX_URL_LEN = 2000
MAX_OUTLET_LEN = 200
BATCH_SIZE = 15
MAX_OPEN_STORIES = 40

Group = list[tuple[str, RawArticle]]  # (canonical_url, article); first entry is the representative


class Budget:
    """Token allowance shared by every segment in one invocation."""

    def __init__(self, tokens: int):
        self.remaining = tokens

    def spend(self, n: int) -> None:
        self.remaining -= n

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


def is_due(segment: Segment, now: datetime) -> bool:
    if not segment.active:
        return False
    if segment.last_run_at is None:
        return True
    interval = timedelta(minutes=segment.interval_minutes)
    # GitHub cron often starts 10-20 min late; a quarter-interval grace keeps the cadence from slipping.
    grace = max(MIN_GRACE, interval / 4)
    return now >= segment.last_run_at + interval - grace


def _chunks(items: Sequence, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _story_candidate(story: Story) -> Candidate:
    first = story.articles[0] if story.articles else None
    return Candidate(f"p{story.id}", story.headline, first.snippet if first else "", first.source if first else "")


def _apply_score(story: Story, decision: Decision, version: int) -> None:
    story.match_score = decision.match
    story.reason = decision.reason
    story.status = "scored"
    story.scored_version = version


def _fetch_all(definition: SegmentDefinition, sources: Mapping[str, Source], http, now,
               errors: list[dict]) -> tuple[list[RawArticle], int]:
    raws: list[RawArticle] = []
    enabled = [cfg for cfg in definition.sources if cfg.enabled]
    for cfg in enabled:
        source = sources.get(cfg.type)
        if source is None:
            errors.append({"source": cfg.type, "message": "source not available"})
            continue
        try:
            raws.extend(source.fetch(cfg, http, now))
        except Exception as exc:  # any source failure is recorded, never fatal
            errors.append({"source": cfg.type, "message": str(exc)[:300]})
    return raws, len(enabled)


def _add_article(session: Session, story: Story, canonical: str, raw: RawArticle, now: datetime) -> None:
    session.add(Article(
        story=story, segment_id=story.segment_id, source=raw.source, outlet=raw.outlet[:MAX_OUTLET_LEN],
        title=raw.title, url=raw.url, canonical_url=canonical[:MAX_URL_LEN],
        published_at=min(raw.published_at, now) if raw.published_at else None, snippet=raw.snippet,
        engagement=raw.engagement, first_seen=now, last_seen=now,
    ))


def _new_story(session: Session, segment: Segment, run: Run, headline: str, now: datetime) -> Story:
    story = Story(segment=segment, headline=headline, status="pending", first_seen=now, last_seen=now,
                  runs_seen=1, last_seen_run_id=run.id)
    session.add(story)
    session.flush()
    return story


def _open_stories(session: Session, segment: Segment, now: datetime) -> list[Story]:
    return list(session.scalars(
        select(Story)
        .where(Story.segment_id == segment.id, Story.last_seen >= now - OPEN_WINDOW)
        .order_by(Story.last_seen.desc())
        .limit(MAX_OPEN_STORIES)
    ))


def _group_new(new_raws: list[tuple[str, RawArticle]], open_stories: list[Story]) -> tuple[list[tuple[Story, str, RawArticle]], list[Group]]:
    """Cheap title matching: attach to an open story, or cluster with other new articles."""
    attached: list[tuple[Story, str, RawArticle]] = []
    groups: list[Group] = []
    for canonical, raw in new_raws:
        story = next((s for s in open_stories
                      if titles_match(raw.title, s.headline) or any(titles_match(raw.title, a.title) for a in s.articles)),
                     None)
        if story is not None:
            attached.append((story, canonical, raw))
            continue
        group = next((g for g in groups if titles_match(raw.title, g[0][1].title)), None)
        if group is not None:
            group.append((canonical, raw))
        else:
            groups.append([(canonical, raw)])
    groups.sort(key=lambda g: -len({r.outlet for _, r in g}))
    return attached, groups


def run_segment(session: Session, segment: Segment, *, llm: LLMClient, model: str, http: httpx.Client | None,
                now: datetime, budget: Budget, sources: Mapping[str, Source]) -> Run:
    definition = segment.get_definition()
    scoring = segment.get_scoring()
    version = segment.definition_version
    errors: list[dict] = []
    run = Run(segment=segment, started_at=now, status="running", errors=[])
    session.add(run)
    session.flush()

    # Fetch, filter, dedupe within the batch.
    raws, enabled_count = _fetch_all(definition, sources, http, now, errors)
    run.fetched = len(raws)
    unique: dict[str, RawArticle] = {}
    for r in raws:
        if matches_exclude(f"{r.title} {r.snippet}", definition.exclude):
            continue
        canonical = canonicalize_url(r.url)[:MAX_URL_LEN]
        if canonical and canonical not in unique:
            unique[canonical] = r

    # Articles already known: refresh them and touch their story.
    touched: dict[int, Story] = {}
    grown: dict[int, Story] = {}
    existing = {a.canonical_url: a for a in session.scalars(
        select(Article).where(Article.segment_id == segment.id, Article.canonical_url.in_(list(unique))))}
    new_raws = []
    for canonical, r in unique.items():
        article = existing.get(canonical)
        if article is None:
            new_raws.append((canonical, r))
            continue
        article.last_seen = now
        article.engagement = max(article.engagement, r.engagement)
        touched[article.story_id] = article.story

    open_stories = _open_stories(session, segment, now)
    attached, groups = _group_new(new_raws, open_stories)
    for story, canonical, r in attached:
        _add_article(session, story, canonical, r, now)
        touched[story.id] = grown[story.id] = story
    run.new_articles = len(new_raws)

    # AI phase: pending stories first, then new groups, within the cap and the token budget.
    cap = scoring.max_new_stories_per_run
    sent = 0
    ai_ok = True
    pending = list(session.scalars(select(Story).where(
        Story.segment_id == segment.id, Story.status == "pending", Story.dismissed.is_(False))))
    pending.sort(key=lambda s: score_story(s, scoring, now).buzz, reverse=True)
    pending_by_key = {f"p{s.id}": s for s in pending[:cap]}
    merged_away: set[int] = set()
    for chunk in _chunks(list(pending_by_key.values()), BATCH_SIZE):
        if budget.exhausted:
            break
        chunk_ids = {s.id for s in chunk}
        refs = [OpenStory(s.id, s.headline) for s in open_stories
                if s.id not in chunk_ids and s.id not in merged_away]
        try:
            decisions, tokens = classify_batch(llm, model, definition, [_story_candidate(s) for s in chunk], refs)
        except LLMError as exc:
            errors.append({"source": "llm", "message": str(exc)[:300]})
            ai_ok = False
            break
        budget.spend(tokens)
        sent += len(chunk)
        for d in decisions:
            story = pending_by_key.get(d.key)
            if story is None:
                continue
            target = next((s for s in open_stories if s.id == d.story_id), None) if d.story_id else None
            if target is not None:
                for article in list(story.articles):
                    article.story = target
                touched[target.id] = grown[target.id] = target
                touched.pop(story.id, None)
                grown.pop(story.id, None)
                merged_away.add(story.id)
                session.delete(story)
                run.scored += 1
            elif d.match is not None:
                _apply_score(story, d, version)
                run.scored += 1
    session.flush()
    open_stories = [s for s in open_stories if s.id not in merged_away]

    decided: dict[int, Decision] = {}
    eligible = list(enumerate(groups))[: max(0, cap - sent)] if ai_ok else []
    open_refs = [OpenStory(s.id, s.headline) for s in open_stories]
    for chunk in _chunks(eligible, BATCH_SIZE):
        if budget.exhausted:
            break
        candidates = [Candidate(f"c{i}", g[0][1].title, g[0][1].snippet, g[0][1].source) for i, g in chunk]
        try:
            decisions, tokens = classify_batch(llm, model, definition, candidates, open_refs)
        except LLMError as exc:
            errors.append({"source": "llm", "message": str(exc)[:300]})
            break
        budget.spend(tokens)
        for d in decisions:
            decided[int(d.key[1:])] = d

    open_by_id = {s.id: s for s in open_stories}
    story_for_group: dict[int, Story] = {}

    def follows(i: int) -> int | None:
        d = decided.get(i)
        if d is None or d.same_as_key is None:
            return None
        j = int(d.same_as_key[1:])
        target = decided.get(j)  # follow only a root (undecided or standalone), never a chain
        return j if j != i and j < len(groups) and (target is None or target.same_as_key is None) else None

    for i, group in enumerate(groups):
        if follows(i) is not None:
            continue
        d = decided.get(i)
        if d is not None and d.story_id in open_by_id:
            story = open_by_id[d.story_id]
            touched[story.id] = story
        else:
            story = _new_story(session, segment, run, group[0][1].title, now)
            run.new_stories += 1
            if d is not None and d.match is not None:
                _apply_score(story, d, version)
                run.scored += 1
        story_for_group[i] = story
    for i, group in enumerate(groups):
        j = follows(i)
        if j is not None:
            story_for_group[i] = story_for_group[j]
        story = story_for_group[i]
        for canonical, r in group:
            _add_article(session, story, canonical, r, now)
        session.flush()
        grown[story.id] = story

    # Bookkeeping on touched and grown stories.
    for story in touched.values():
        story.last_seen = now
        if story.last_seen_run_id != run.id:
            story.runs_seen += 1
            story.last_seen_run_id = run.id
    for story in grown.values():
        dates = [a.published_at for a in story.articles if a.published_at is not None]
        story.published_at = min(dates) if dates else None
    run.updated_stories = len(touched)

    for old in session.scalars(select(Story).where(Story.segment_id == segment.id,
                                                   Story.last_seen < now - RETENTION)):
        session.delete(old)
    session.flush()
    still_pending = session.scalar(select(func.count()).select_from(Story).where(
        Story.segment_id == segment.id, Story.status == "pending", Story.dismissed.is_(False)))
    source_errors = [e for e in errors if e["source"] != "llm"]
    if enabled_count and len(source_errors) >= enabled_count:
        run.status = "failed"
    elif errors or still_pending:
        run.status = "partial"
    else:
        run.status = "success"
    run.errors = errors
    run.finished_at = now
    segment.last_run_at = now
    session.flush()
    return run


def run_due(session_factory: sessionmaker, *, llm: LLMClient, model: str, http: httpx.Client | None,
            now: datetime, budget: Budget, sources: Mapping[str, Source]) -> list[Run]:
    with session_factory() as session:
        segments = session.scalars(select(Segment).where(Segment.active.is_(True))
                                   .order_by(Segment.last_run_at.is_(None).desc(), Segment.last_run_at)).all()
        due_ids = [s.id for s in segments if is_due(s, now)]

    runs: list[Run] = []
    for segment_id in due_ids:
        with session_factory() as session:
            segment = session.get(Segment, segment_id)
            try:
                run = run_segment(session, segment, llm=llm, model=model, http=http, now=now,
                                  budget=budget, sources=sources)
                session.commit()
            except Exception as exc:
                log.exception("segment %s crashed", segment_id)
                session.rollback()
                segment = session.get(Segment, segment_id)
                run = Run(segment=segment, started_at=now, finished_at=now, status="failed",
                          errors=[{"source": "runner", "message": repr(exc)[:300]}])
                segment.last_run_at = now
                session.add(run)
                session.commit()
            runs.append(run)
    return runs


def rescore_recent(session: Session, segment: Segment, *, llm: LLMClient, model: str, now: datetime,
                   budget: Budget, hours: int = 48) -> tuple[int, int]:
    """Re-rate recent stories not yet scored against the current definition. Returns (updated, remaining).
    Commits after every batch so a later rate limit or timeout keeps what was already paid for."""
    definition = segment.get_definition()
    version = segment.definition_version
    stories = list(session.scalars(
        select(Story)
        .where(Story.segment_id == segment.id, Story.dismissed.is_(False),
               Story.last_seen >= now - timedelta(hours=hours))
        .order_by(Story.last_seen.desc())
    ))
    stories = [s for s in stories if not (s.status == "scored" and s.scored_version == version)]
    by_key = {f"p{s.id}": s for s in stories}
    updated = sent = 0
    for chunk in _chunks(stories, BATCH_SIZE):
        if budget.exhausted:
            break
        try:
            decisions, tokens = classify_batch(llm, model, definition, [_story_candidate(s) for s in chunk], [])
        except LLMError:
            log.warning("rescore stopped early for segment %s", segment.id, exc_info=True)
            break
        budget.spend(tokens)
        sent += len(chunk)
        for d in decisions:
            if d.match is not None and d.key in by_key:
                _apply_score(by_key[d.key], d, version)
                updated += 1
        session.commit()
    return updated, len(stories) - sent
