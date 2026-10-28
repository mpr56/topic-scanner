import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from scanner.models import Run
from tests.factories import BODY, NOW, make_article, make_segment, make_story
from tests.fakes import FakeSource


@pytest.fixture
def seeded(client):
    app = client.app
    app.state.clock = lambda: NOW
    with app.state.session_factory() as s:
        seg = make_segment(s)
        high = make_story(s, seg, headline="High", match_score=9)
        make_article(s, high, outlet="Reuters")
        make_article(s, high, outlet="BBC")
        make_story(s, seg, headline="Low", match_score=2)
        make_story(s, seg, headline="Pending", status="pending", match_score=None)
        make_story(s, seg, headline="Old", match_score=1,
                   first_seen=NOW - timedelta(hours=72), last_seen=NOW - timedelta(hours=72))
        s.add(Run(segment=seg, started_at=NOW - timedelta(hours=2), status="success", errors=[]))
        s.add(Run(segment=seg, started_at=NOW, status="partial", errors=[]))
        s.commit()
        return SimpleNamespace(segment_id=seg.id, high_id=high.id)


def test_stories_sorted_with_breakdown(client, seeded):
    rows = client.get(f"/api/segments/{seeded.segment_id}/stories").json()
    assert [r["headline"] for r in rows] == ["High", "Low", "Old", "Pending"]
    assert set(rows[0]["scores"]) == {"match", "buzz", "freshness", "combined"}
    assert rows[0]["articles"][0]["outlet"] == "Reuters" and rows[-1]["scores"]["combined"] is None


def test_story_filters(client, seeded):
    base = f"/api/segments/{seeded.segment_id}/stories"
    assert [r["headline"] for r in client.get(base, params={"min_score": 6}).json()] == ["High"]
    assert "Old" not in [r["headline"] for r in client.get(base, params={"since_hours": 24}).json()]


def test_dismiss_hides_story(client, seeded):
    client.post(f"/api/stories/{seeded.high_id}/dismiss")
    base = f"/api/segments/{seeded.segment_id}/stories"
    assert "High" not in [r["headline"] for r in client.get(base).json()]
    assert "High" in [r["headline"] for r in client.get(base, params={"include_dismissed": True}).json()]
    assert client.post(f"/api/stories/{seeded.high_id}/undismiss").json()["dismissed"] is False


def test_runs_list_newest_first(client, seeded):
    rows = client.get("/api/runs", params={"segment_id": seeded.segment_id}).json()
    assert len(rows) == 2
    assert [r["id"] for r in rows] == sorted([r["id"] for r in rows], reverse=True)


def test_run_now_inline(make_client):
    c = make_client(sources={"google_news": FakeSource("google_news", [])})
    sid = c.post("/api/segments", json=BODY).json()["id"]
    r = c.post(f"/api/segments/{sid}/run")
    assert r.status_code == 202 and r.json()["mode"] == "inline" and r.json()["run"]["status"] == "success"


def test_run_now_github_dispatch(make_client):
    seen = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(204)))
    c = make_client(run_now_mode="github", github_token="gh", github_repo="o/r", http=http)
    sid = c.post("/api/segments", json=BODY).json()["id"]
    assert c.post(f"/api/segments/{sid}/run").json() == {"mode": "github"}
    assert str(seen[0].url) == "https://api.github.com/repos/o/r/actions/workflows/scan.yml/dispatches"
    assert json.loads(seen[0].content) == {"ref": "main", "inputs": {"segment_id": str(sid)}}
    assert seen[0].headers["authorization"] == "Bearer gh"


def test_run_now_github_failure_is_502(make_client):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    c = make_client(run_now_mode="github", github_token="gh", github_repo="o/r", http=http)
    sid = c.post("/api/segments", json=BODY).json()["id"]
    assert c.post(f"/api/segments/{sid}/run").status_code == 502


def github_api(runs, jobs=(), status=200):
    """Fake GitHub API: `runs` for the workflow-runs listing, `jobs` for any run's jobs listing."""
    seen = []

    def handle(r):
        seen.append(r)
        if status != 200:
            return httpx.Response(status)
        if r.url.path.endswith("/jobs"):
            return httpx.Response(200, json={"jobs": list(jobs)})
        return httpx.Response(200, json={"workflow_runs": list(runs)})

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


GH_RUN = {"id": 99, "run_number": 12, "event": "schedule", "status": "completed", "conclusion": "failure",
          "html_url": "https://github.com/o/r/actions/runs/99", "created_at": "2026-10-28T03:07:12Z"}


def test_actions_status_reports_latest_failure(make_client):
    jobs = [{"steps": [{"name": "Set up job", "conclusion": "success"},
                       {"name": "Run python -m scanner init-db", "conclusion": "failure"},
                       {"name": "Scan", "conclusion": "skipped"}]}]
    http, seen = github_api([GH_RUN], jobs)
    c = make_client(github_token="gh", github_repo="o/r", http=http)
    assert c.get("/api/actions/status").json() == {"failure": {
        "run_number": 12, "event": "schedule", "conclusion": "failure", "created_at": "2026-10-28T03:07:12Z",
        "html_url": "https://github.com/o/r/actions/runs/99", "failed_step": "Run python -m scanner init-db"}}
    assert str(seen[0].url).startswith("https://api.github.com/repos/o/r/actions/workflows/scan.yml/runs?")
    assert seen[0].url.params["status"] == "completed"
    assert seen[0].headers["authorization"] == "Bearer gh"
    assert str(seen[1].url) == "https://api.github.com/repos/o/r/actions/runs/99/jobs"


def test_actions_status_clear_after_success(make_client):
    http, seen = github_api([{**GH_RUN, "conclusion": "success"}])
    c = make_client(github_token="gh", github_repo="o/r", http=http)
    assert c.get("/api/actions/status").json() == {"failure": None}
    assert len(seen) == 1  # no jobs lookup


def test_actions_status_without_github_config(make_client):
    http, seen = github_api([GH_RUN])
    assert make_client(http=http).get("/api/actions/status").json() == {"failure": None}
    assert seen == []


def test_actions_status_github_error_is_502(make_client):
    http, _ = github_api([], status=401)
    c = make_client(github_token="gh", github_repo="o/r", http=http)
    assert c.get("/api/actions/status").status_code == 502


def test_rescore_endpoint(client, seeded, fake_llm):
    fake_llm.queue({"results": []})
    assert client.post(f"/api/segments/{seeded.segment_id}/rescore").json() == {"rescored": 0, "remaining": 0}
