from datetime import timedelta

import pytest

from scanner.schemas import ScoringConfig
from scanner.scoring import buzz_score, combined_score, freshness_score, score_story
from tests.factories import make_article, make_segment, make_story

cfg = ScoringConfig()


def test_freshness_curve(now):
    assert freshness_score(now - timedelta(hours=1), now, now, cfg) == 10
    assert freshness_score(now - timedelta(hours=48), now, now, cfg) == 0
    assert freshness_score(now - timedelta(hours=25), now, now, cfg) == pytest.approx(5.0)


def test_freshness_missing_and_future(now):
    assert freshness_score(None, now - timedelta(hours=1), now, cfg) == 10
    assert freshness_score(now + timedelta(hours=3), now, now, cfg) == 10


def test_buzz_bounds_and_signals():
    assert buzz_score(1, 1, 0, cfg) == 0
    assert buzz_score(5, 6, 9999, cfg) == pytest.approx(10)
    assert buzz_score(3, 1, 0, cfg) == pytest.approx(5 / 3)
    assert buzz_score(3, 1, 0, ScoringConfig(buzz_signals=["outlets"])) == pytest.approx(5)


def test_combined():
    assert combined_score(None, 5, 5, cfg) is None
    assert combined_score(10, 10, 10, cfg) == 10
    assert combined_score(0, 0, 0, cfg) == 1.0
    assert combined_score(8, 4, 10, cfg) == 7.2


def test_score_story(session, now):
    seg = make_segment(session)
    story = make_story(session, seg, match_score=8, published_at=now - timedelta(hours=1))
    make_article(session, story, outlet="Reuters", engagement=10, canonical_url="https://a/1")
    make_article(session, story, outlet="BBC", engagement=90, canonical_url="https://a/2")
    s = score_story(story, cfg, now)
    assert s.buzz == pytest.approx(2.5, abs=0.05)
    assert s.freshness == 10
    assert s.combined == pytest.approx(0.5 * 8 + 0.3 * s.buzz + 0.2 * 10, abs=0.1)
