from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_db_url(url: str) -> str:
    """Point plain Postgres URLs (as Neon/Supabase hand them out) at the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DEFAULT_SESSION_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scanner.db"
    groq_api_key: str = ""
    groq_model_analyze: str = "openai/gpt-oss-120b"
    groq_model_score: str = "openai/gpt-oss-20b"
    api_token: str = ""
    app_password: str = ""
    session_secret: str = DEFAULT_SESSION_SECRET
    ui_origin: str = "http://localhost:5173"
    cookie_secure: bool = True
    run_token_budget: int = 20000
    run_now_mode: Literal["inline", "github"] = "inline"
    github_token: str = ""
    github_repo: str = ""
    github_ref: str = "main"
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    user_agent: str = "topic-scanner/0.1"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return normalize_db_url(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
