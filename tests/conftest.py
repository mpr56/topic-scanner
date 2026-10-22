from datetime import UTC, datetime

import pytest

from scanner.db import init_db, make_engine, make_sessionmaker


@pytest.fixture
def engine():
    eng = make_engine("sqlite://")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with make_sessionmaker(engine)() as s:
        yield s


@pytest.fixture
def now():
    return datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


BASE_SETTINGS = dict(database_url="sqlite://", api_token="tok", app_password="pw",
                     session_secret="s", cookie_secure=False)


@pytest.fixture
def fake_llm():
    from tests.fakes import FakeLLM
    return FakeLLM()


@pytest.fixture
def make_client(fake_llm):
    from fastapi.testclient import TestClient

    from scanner.api.app import create_app
    from scanner.config import Settings

    def _make(*, sources=None, http=None, auth=True, **overrides):
        settings = Settings(_env_file=None, **{**BASE_SETTINGS, **overrides})
        client = TestClient(create_app(settings, llm=fake_llm, http=http, sources=sources or {}))
        if auth:
            client.headers["Authorization"] = "Bearer tok"
        return client

    return _make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def anon_client(make_client):
    return make_client(auth=False)
