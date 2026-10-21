from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from scanner.ai_tasks import analyze_segment
from scanner.api.auth import require_auth
from scanner.api.deps import get_llm, get_segment_or_404, get_session, get_settings_dep
from scanner.api.schemas import AnalyzeIn, DraftOut, ReanalyzeIn, RunOut, SegmentIn, SegmentOut, SegmentPatch
from scanner.config import Settings
from scanner.llm.base import LLMClient
from scanner.models import Run, Segment

router = APIRouter(dependencies=[Depends(require_auth)])


def _out(session: Session, segment: Segment) -> SegmentOut:
    last = session.scalars(select(Run).where(Run.segment_id == segment.id)
                           .order_by(Run.started_at.desc(), Run.id.desc()).limit(1)).first()
    out = SegmentOut.model_validate(segment)
    out.last_run = RunOut.model_validate(last) if last else None
    return out


def _draft(llm: LLMClient, settings: Settings, name: str, examples: list[str], note: str, existing=None) -> DraftOut:
    try:
        definition, _ = analyze_segment(llm, settings.groq_model_analyze, name, examples, note, existing)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return DraftOut(definition=definition)


@router.post("/segments/analyze", response_model=DraftOut)
def analyze(body: AnalyzeIn, llm: LLMClient = Depends(get_llm), settings: Settings = Depends(get_settings_dep)):
    return _draft(llm, settings, body.name, body.examples, body.note)


@router.post("/segments/{segment_id}/analyze", response_model=DraftOut)
def reanalyze(segment_id: int, body: ReanalyzeIn, session: Session = Depends(get_session),
              llm: LLMClient = Depends(get_llm), settings: Settings = Depends(get_settings_dep)):
    segment = get_segment_or_404(session, segment_id)
    return _draft(llm, settings, segment.name, body.examples or segment.examples,
                  segment.note if body.note is None else body.note, segment.get_definition())


@router.get("/segments", response_model=list[SegmentOut])
def list_segments(session: Session = Depends(get_session)):
    return [_out(session, s) for s in session.scalars(select(Segment).order_by(Segment.id))]


@router.post("/segments", response_model=SegmentOut, status_code=201)
def create_segment(body: SegmentIn, session: Session = Depends(get_session)):
    segment = Segment(**body.model_dump())
    session.add(segment)
    session.flush()
    return _out(session, segment)


@router.get("/segments/{segment_id}", response_model=SegmentOut)
def get_segment(segment_id: int, session: Session = Depends(get_session)):
    return _out(session, get_segment_or_404(session, segment_id))


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def update_segment(segment_id: int, body: SegmentPatch, session: Session = Depends(get_session)):
    segment = get_segment_or_404(session, segment_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("definition") is not None and changes["definition"] != segment.definition:
        segment.definition_version += 1
    for field, value in changes.items():
        if value is not None:
            setattr(segment, field, value)
    session.flush()
    return _out(session, segment)


@router.delete("/segments/{segment_id}", status_code=204)
def delete_segment(segment_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(get_segment_or_404(session, segment_id))
    return Response(status_code=204)
