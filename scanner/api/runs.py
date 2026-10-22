import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from scanner.api.auth import require_auth
from scanner.api.deps import get_segment_or_404, get_session
from scanner.api.schemas import RunOut
from scanner.models import Run
from scanner.runner import Budget, run_segment

router = APIRouter(dependencies=[Depends(require_auth)])

WORKFLOW = "scan.yml"


@router.get("/runs", response_model=list[RunOut])
def list_runs(segment_id: int | None = None, limit: int = Query(20, ge=1, le=100),
              session: Session = Depends(get_session)):
    query = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
    if segment_id is not None:
        query = query.where(Run.segment_id == segment_id)
    return list(session.scalars(query))


@router.post("/segments/{segment_id}/run", status_code=202)
def run_now(request: Request, segment_id: int, session: Session = Depends(get_session)):
    state = request.app.state
    settings = state.settings
    segment = get_segment_or_404(session, segment_id)

    if settings.run_now_mode == "github":
        if not (settings.github_token and settings.github_repo):
            raise HTTPException(502, "GitHub dispatch is not configured")
        url = f"https://api.github.com/repos/{settings.github_repo}/actions/workflows/{WORKFLOW}/dispatches"
        try:
            resp = state.http.post(url, json={"ref": settings.github_ref, "inputs": {"segment_id": str(segment.id)}},
                                   headers={"Authorization": f"Bearer {settings.github_token}",
                                            "Accept": "application/vnd.github+json"})
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"GitHub dispatch failed: {exc}") from exc
        if resp.status_code != 204:
            raise HTTPException(502, f"GitHub dispatch returned {resp.status_code}")
        return JSONResponse({"mode": "github"}, status_code=202)

    run = run_segment(session, segment, llm=state.llm, model=settings.groq_model_score, http=state.http,
                      now=state.clock(), budget=Budget(settings.run_token_budget), sources=state.sources)
    return JSONResponse({"mode": "inline", "run": RunOut.model_validate(run).model_dump(mode="json")},
                        status_code=202)
