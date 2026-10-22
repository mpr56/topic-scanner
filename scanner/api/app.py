from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from scanner.api import auth, runs, segments, stories
from scanner.config import Settings, get_settings
from scanner.db import init_db, make_engine, make_sessionmaker
from scanner.llm.base import LLMClient, LLMError, RateLimited
from scanner.llm.groq import GroqClient
from scanner.sources import build_sources
from scanner.sources.base import Source


def create_app(settings: Settings | None = None, *, llm: LLMClient | None = None,
               session_factory: sessionmaker | None = None, http: httpx.Client | None = None,
               sources: Mapping[str, Source] | None = None) -> FastAPI:
    settings = settings or get_settings()
    if session_factory is None:
        engine = make_engine(settings.database_url)
        init_db(engine)
        session_factory = make_sessionmaker(engine)

    app = FastAPI(title="Topic Scanner API")
    app.state.settings = settings
    app.state.llm = llm or GroqClient(settings.groq_api_key)
    app.state.session_factory = session_factory
    app.state.http = http or httpx.Client(timeout=20, headers={"User-Agent": settings.user_agent})
    app.state.sources = sources if sources is not None else build_sources(settings)
    app.state.clock = lambda: datetime.now(UTC)

    app.add_middleware(CORSMiddleware, allow_origins=[settings.ui_origin], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RateLimited)
    def _rate_limited(_request: Request, _exc: RateLimited):
        return JSONResponse({"detail": "AI provider is rate limited, try again shortly"}, status_code=503)

    @app.exception_handler(LLMError)
    def _llm_error(_request: Request, exc: LLMError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health():
        return {"ok": True}

    api.include_router(auth.router)
    api.include_router(segments.router)
    api.include_router(stories.router)
    api.include_router(runs.router)
    app.include_router(api)
    return app
