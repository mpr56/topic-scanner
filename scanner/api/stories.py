from dataclasses import asdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from scanner.api.auth import require_auth
from scanner.api.deps import get_segment_or_404, get_session
from scanner.api.schemas import ArticleOut, ScoresOut, StoryOut
from scanner.models import Story
from scanner.runner import Budget, rescore_recent
from scanner.schemas import ScoringConfig
from scanner.scoring import score_story

router = APIRouter(dependencies=[Depends(require_auth)])


def story_out(story: Story, scoring: ScoringConfig, now: datetime) -> StoryOut:
    articles = sorted(story.articles, key=lambda a: a.id)
    return StoryOut(
        id=story.id, segment_id=story.segment_id, headline=story.headline, status=story.status,
        scores=ScoresOut(**asdict(score_story(story, scoring, now))), reason=story.reason,
        scored_version=story.scored_version, published_at=story.published_at, first_seen=story.first_seen,
        last_seen=story.last_seen, runs_seen=story.runs_seen, dismissed=story.dismissed,
        outlets=sorted({a.outlet for a in articles}),
        articles=[ArticleOut.model_validate(a) for a in articles],
    )


@router.get("/segments/{segment_id}/stories", response_model=list[StoryOut])
def list_stories(request: Request, segment_id: int, min_score: float | None = None,
                 since_hours: int = Query(168, ge=1, le=24 * 30), include_dismissed: bool = False,
                 limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)):
    segment = get_segment_or_404(session, segment_id)
    now = request.app.state.clock()
    query = (select(Story).options(selectinload(Story.articles))
             .where(Story.segment_id == segment.id, Story.last_seen >= now - timedelta(hours=since_hours)))
    if not include_dismissed:
        query = query.where(Story.dismissed.is_(False))
    scoring = segment.get_scoring()
    rows = [story_out(s, scoring, now) for s in session.scalars(query)]
    if min_score is not None:
        rows = [r for r in rows if r.scores.combined is not None and r.scores.combined >= min_score]
    rows.sort(key=lambda r: (r.scores.combined is None, -(r.scores.combined or 0), -r.last_seen.timestamp()))
    return rows[:limit]


def _set_dismissed(request: Request, session: Session, story_id: int, value: bool) -> StoryOut:
    story = session.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    story.dismissed = value
    session.flush()
    return story_out(story, story.segment.get_scoring(), request.app.state.clock())


@router.post("/stories/{story_id}/dismiss", response_model=StoryOut)
def dismiss(request: Request, story_id: int, session: Session = Depends(get_session)):
    return _set_dismissed(request, session, story_id, True)


@router.post("/stories/{story_id}/undismiss", response_model=StoryOut)
def undismiss(request: Request, story_id: int, session: Session = Depends(get_session)):
    return _set_dismissed(request, session, story_id, False)


@router.post("/segments/{segment_id}/rescore")
def rescore(request: Request, segment_id: int, hours: int = Query(48, ge=1, le=24 * 30),
            session: Session = Depends(get_session)):
    state = request.app.state
    segment = get_segment_or_404(session, segment_id)
    n, remaining = rescore_recent(session, segment, llm=state.llm, model=state.settings.groq_model_score,
                                  now=state.clock(), budget=Budget(state.settings.run_token_budget), hours=hours)
    return {"rescored": n, "remaining": remaining}
