from dataclasses import replace
from datetime import timedelta

from sqlalchemy import func, select

from scanner.db import make_sessionmaker
from scanner.llm.base import RateLimited
from scanner.models import Story
from scanner.runner import Budget, is_due, rescore_recent, run_due, run_segment
from scanner.schemas import ScoringConfig, SegmentDefinition, SourceConfig
from scanner.sources.base import RawArticle, SourceError
from tests.factories import make_segment, make_story
from tests.fakes import FakeLLM, FakeSource


def raw(title, url, outlet="Reuters", source="google_news", published=None, engagement=0):
    return RawArticle(source=source, outlet=outlet, title=title, url=url,
                      published_at=published, engagement=engagement)


def seg(session, sources, name="Big news", **scoring):
    definition = SegmentDefinition(
        summary="Major news",
        sources=[SourceConfig(type=t, mode="feed", subreddits=["worldnews"]) for t in sources],
    ).model_dump()
    return make_segment(session, name=name, definition=definition,
                        scoring=ScoringConfig(**scoring).model_dump())


def go(session, segment, llm, fakes, now, budget=None):
    return run_segment(session, segment, llm=llm, model="m", http=None, now=now,
                       budget=budget or Budget(10_000), sources=fakes)


def scored(key, match=8, same_as=None):
    return {"key": key, "same_as": same_as, "match": match, "reason": "r"}


def test_new_articles_grouped_and_scored(session, now):
    fakes = {"google_news": FakeSource("google_news", [raw("Tesla Roadster flies - Reuters", "https://r.com/1"),
                                                        raw("France names new PM", "https://r.com/2")]),
             "reddit": FakeSource("reddit", [raw("Tesla Roadster flies!", "https://v.com/a", outlet="r/cars", source="reddit")])}
    llm = FakeLLM({"results": [{"key": "c0", "same_as": None, "match": 9, "reason": "big"},
                               {"key": "c1", "same_as": None, "match": 4, "reason": "meh"}]})
    s = seg(session, ["google_news", "reddit"])
    run = go(session, s, llm, fakes, now)
    stories = session.scalars(select(Story).order_by(Story.match_score.desc())).all()
    assert [len(st.articles) for st in stories] == [2, 1]
    assert (run.status, run.fetched, run.new_articles, run.new_stories, run.scored) == ("success", 3, 3, 2, 2)
    assert stories[0].scored_version == 1 and s.last_run_at == now


def test_rerun_updates_without_ai_or_duplicates(session, now):
    a = raw("Tesla Roadster flies", "https://r.com/1", engagement=10)
    s = seg(session, ["google_news"])
    go(session, s, FakeLLM({"results": [scored("c0")]}), {"google_news": FakeSource("google_news", [a])}, now)
    later = now + timedelta(hours=2)
    b = replace(a, url="https://r.com/1?utm_source=x", engagement=50)
    go(session, s, FakeLLM(), {"google_news": FakeSource("google_news", [b])}, later)
    story = session.scalars(select(Story)).one()
    assert story.runs_seen == 2 and story.last_seen == later and story.articles[0].engagement == 50


def test_ai_assigns_to_existing_story(session, now):
    s = seg(session, ["google_news"])
    go(session, s, FakeLLM({"results": [scored("c0")]}),
       {"google_news": FakeSource("google_news", [raw("Tesla Roadster flies", "https://r.com/1")])}, now)
    story = session.scalars(select(Story)).one()
    llm = FakeLLM({"results": [{"key": "c0", "same_as": story.id, "match": 8, "reason": ""}]})
    go(session, s, llm, {"google_news": FakeSource("google_news",
       [raw("Musk's flying car lifts off over California", "https://bbc.com/x", outlet="BBC")])}, now + timedelta(hours=2))
    assert session.scalar(select(func.count()).select_from(Story)) == 1
    assert len(story.articles) == 2 and f"#{story.id}:" in llm.calls[0].user


def test_exclude_filter_drops_before_ai(session, now):
    s = seg(session, ["google_news"]); s.definition = {**s.definition, "exclude": ["gossip"]}
    run = go(session, s, FakeLLM(), {"google_news": FakeSource("google_news",
             [raw("Celebrity gossip roundup", "https://g.com/1")])}, now)
    assert run.fetched == 1 and run.new_articles == 0


def test_cap_leaves_pending_then_scores_pending_first(session, now):
    s = seg(session, ["google_news"], max_new_stories_per_run=1)
    src = {"google_news": FakeSource("google_news", [raw("Tesla Roadster flies", "https://r.com/1"),
                                                      raw("France names new PM", "https://r.com/2")])}
    run = go(session, s, FakeLLM({"results": [scored("c0")]}), src, now)
    pending = session.scalars(select(Story).where(Story.status == "pending")).one()
    assert run.status == "partial"
    llm = FakeLLM({"results": [scored(f"p{pending.id}", match=5)]})
    go(session, s, llm, {"google_news": FakeSource("google_news", [])}, now + timedelta(hours=2))
    assert pending.status == "scored" and pending.headline in llm.calls[0].user


def test_source_error_is_recorded_and_others_continue(session, now):
    s = seg(session, ["google_news", "reddit"])
    run = go(session, s, FakeLLM({"results": [scored("c0")]}),
             {"google_news": FakeSource("google_news", [raw("Tesla Roadster flies", "https://r.com/1")]),
              "reddit": FakeSource("reddit", SourceError("403 from www.reddit.com"))}, now)
    assert run.status == "partial" and run.errors == [{"source": "reddit", "message": "403 from www.reddit.com"}]
    assert run.new_stories == 1


def test_all_sources_fail_marks_failed(session, now):
    s = seg(session, ["google_news"])
    run = go(session, s, FakeLLM(), {"google_news": FakeSource("google_news", SourceError("boom"))}, now)
    assert run.status == "failed"


def test_rate_limited_keeps_pending(session, now):
    s = seg(session, ["google_news"])
    run = go(session, s, FakeLLM(RateLimited("429")),
             {"google_news": FakeSource("google_news", [raw("Tesla Roadster flies", "https://r.com/1")])}, now)
    assert run.status == "partial" and any(e["source"] == "llm" for e in run.errors)
    assert session.scalars(select(Story)).one().status == "pending"


def test_budget_exhausted_skips_ai(session, now):
    s = seg(session, ["google_news"])
    go(session, s, FakeLLM(), {"google_news": FakeSource("google_news",
       [raw("Tesla Roadster flies", "https://r.com/1")])}, now, budget=Budget(0))
    assert session.scalars(select(Story)).one().status == "pending"


def test_is_due_grace(session, now):
    s = seg(session, ["google_news"])
    s.last_run_at = None; assert is_due(s, now)
    s.last_run_at = now - timedelta(minutes=117); assert is_due(s, now)
    s.last_run_at = now - timedelta(minutes=110); assert not is_due(s, now)
    s.active = False; s.last_run_at = None; assert not is_due(s, now)


def test_run_due_isolates_crashing_segment(engine, now):
    factory = make_sessionmaker(engine)
    with factory() as sess:
        seg(sess, ["google_news"], name="a"); seg(sess, ["reddit"], name="b"); sess.commit()

    class Boom:
        def complete_json(self, *a, **k): raise RuntimeError("kaboom")

    fakes = {"google_news": FakeSource("google_news", [raw("Tesla Roadster flies", "https://r.com/1")]),
             "reddit": FakeSource("reddit", [])}
    runs = run_due(factory, llm=Boom(), model="m", http=None, now=now, budget=Budget(10_000), sources=fakes)
    assert sorted(r.status for r in runs) == ["failed", "success"]


def test_rescore_recent_updates_version_and_skips_old(session, now):
    s = seg(session, ["google_news"]); s.definition_version = 2
    fresh = make_story(session, s, status="scored", match_score=3, scored_version=1, last_seen=now)
    old = make_story(session, s, status="scored", match_score=3, scored_version=1, last_seen=now - timedelta(hours=72))
    n = rescore_recent(session, s, llm=FakeLLM({"results": [scored(f"p{fresh.id}", match=9)]}),
                       model="m", now=now, budget=Budget(10_000))
    assert n == 1 and (fresh.match_score, fresh.scored_version) == (9, 2) and old.scored_version == 1


def test_story_published_is_earliest_article(session, now):
    s = seg(session, ["google_news"])
    go(session, s, FakeLLM({"results": [scored("c0")]}),
       {"google_news": FakeSource("google_news", [
           raw("Tesla Roadster flies", "https://r.com/1", published=now - timedelta(hours=1)),
           raw("Tesla Roadster flies - BBC", "https://b.com/1", outlet="BBC", published=now - timedelta(hours=3))])}, now)
    assert session.scalars(select(Story)).one().published_at == now - timedelta(hours=3)
