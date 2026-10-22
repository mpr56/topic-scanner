from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError

from scanner.models import Article, Segment
from scanner.schemas import SegmentDefinition
from tests.factories import make_article, make_segment, make_story


def test_datetimes_round_trip_as_utc(session):
    seg = make_segment(session, last_run_at=datetime(2026, 10, 21, 9, tzinfo=UTC))
    session.commit(); session.expire_all()
    loaded = session.get(Segment, seg.id)
    assert loaded.last_run_at == datetime(2026, 10, 21, 9, tzinfo=UTC)
    assert loaded.last_run_at.tzinfo is not None


def test_naive_datetime_rejected(session):
    with pytest.raises(StatementError):  # make_segment flushes
        make_segment(session, last_run_at=datetime(2026, 10, 21, 9))  # naive


def test_article_unique_per_segment(session):
    seg = make_segment(session); story = make_story(session, seg)
    make_article(session, story, canonical_url="https://a.com/x")
    with pytest.raises(IntegrityError):
        make_article(session, story, canonical_url="https://a.com/x")


def test_delete_segment_cascades(session):
    seg = make_segment(session); make_article(session, make_story(session, seg))
    session.delete(seg); session.flush()
    assert session.scalar(select(func.count()).select_from(Article)) == 0


def test_segment_typed_helpers(session):
    seg = make_segment(session)
    assert isinstance(seg.get_definition(), SegmentDefinition)
    assert seg.get_scoring().max_new_stories_per_run == 40
