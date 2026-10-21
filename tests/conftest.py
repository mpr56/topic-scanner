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
