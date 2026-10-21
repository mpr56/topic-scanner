from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from scanner.config import Settings
from scanner.llm.base import LLMClient
from scanner.models import Segment


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session
        session.commit()


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


def get_segment_or_404(session: Session, segment_id: int) -> Segment:
    segment = session.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "Segment not found")
    return segment
