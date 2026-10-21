import pytest
from pydantic import ValidationError

from scanner.config import Settings, normalize_db_url
from scanner.schemas import ScoringConfig, SourceConfig


def test_normalize_db_url_variants():
    assert normalize_db_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("postgresql://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_db_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("sqlite:///./x.db") == "sqlite:///./x.db"


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    monkeypatch.setenv("RUN_TOKEN_BUDGET", "500")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@h/db"
    assert s.run_token_budget == 500


def test_scoring_defaults():
    c = ScoringConfig()
    assert (c.weights.match, c.weights.buzz, c.weights.freshness) == (0.5, 0.3, 0.2)
    assert (c.fresh_full_hours, c.fresh_zero_hours) == (2, 48)
    assert c.buzz_signals == ["outlets", "runs", "engagement"]
    assert c.max_new_stories_per_run == 40


def test_scoring_rejects_bad_window_and_zero_weights():
    with pytest.raises(ValidationError):
        ScoringConfig(fresh_full_hours=10, fresh_zero_hours=5)
    with pytest.raises(ValidationError):
        ScoringConfig(weights={"match": 0, "buzz": 0, "freshness": 0})


def test_source_config_defaults_and_unknown_type():
    s = SourceConfig(type="reddit")
    assert (s.mode, s.limit, s.enabled, s.region) == ("search", 25, True, "US")
    with pytest.raises(ValidationError):
        SourceConfig(type="twitter")
