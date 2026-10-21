import importlib.util

from sqlalchemy import select

from scanner.cli import main
from scanner.config import get_settings
from scanner.db import get_sessionmaker
from scanner.models import Segment
from scanner.seed import seed_segments


def test_seed_is_idempotent(session):
    assert seed_segments(session) == 1
    assert seed_segments(session) == 0
    seg = session.scalars(select(Segment)).one()
    assert {s.type for s in seg.get_definition().sources} == {"google_news", "reddit", "hackernews"}
    assert all(s.mode == "feed" for s in seg.get_definition().sources)


def test_cli_init_and_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    get_settings.cache_clear(); get_sessionmaker.cache_clear()
    try:
        assert main(["seed"]) == 0
        assert main(["run", "999"]) == 2
    finally:
        get_settings.cache_clear(); get_sessionmaker.cache_clear()


def test_vercel_entry_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/v.db")
    get_settings.cache_clear(); get_sessionmaker.cache_clear()
    try:
        spec = importlib.util.spec_from_file_location("vercel_index", "api/index.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        assert mod.app.title
    finally:
        get_settings.cache_clear(); get_sessionmaker.cache_clear()
