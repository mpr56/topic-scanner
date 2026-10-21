from scanner.llm.base import LLMError, RateLimited
from tests.factories import BODY, DEF


def test_health_open(anon_client):
    assert anon_client.get("/api/health").json() == {"ok": True}


def test_bearer_auth(anon_client, client):
    assert anon_client.get("/api/segments").status_code == 401
    assert anon_client.get("/api/segments", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/segments").status_code == 200


def test_login_cookie_flow(anon_client):
    assert anon_client.post("/api/login", json={"password": "bad"}).status_code == 401
    r = anon_client.post("/api/login", json={"password": "pw"})
    assert r.status_code == 204 and "httponly" in r.headers["set-cookie"].lower()
    assert anon_client.get("/api/segments").status_code == 200
    anon_client.post("/api/logout")
    assert anon_client.get("/api/segments").status_code == 401


def test_login_disabled_without_password(make_client):
    c = make_client(app_password="")
    assert c.post("/api/login", json={"password": ""}).status_code == 401


def test_cors_only_ui_origin(anon_client):
    def pre(origin):
        return anon_client.options("/api/segments", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    ok = pre("http://localhost:5173")
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert ok.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in pre("https://evil.example").headers


def test_analyze_returns_draft_and_saves_nothing(client, fake_llm):
    fake_llm.queue(DEF)
    r = client.post("/api/segments/analyze", json={"name": "Big news", "examples": ["Tesla Roadster flies"]})
    assert r.status_code == 200 and r.json()["definition"]["summary"] == "Major world events"
    assert client.get("/api/segments").json() == []
    assert client.post("/api/segments/analyze", json={"name": "x", "examples": []}).status_code == 422


def test_analyze_errors_map_to_5xx(client, fake_llm):
    fake_llm.queue(RateLimited("429"), LLMError("bad"))
    body = {"name": "x", "examples": ["y"]}
    assert client.post("/api/segments/analyze", json=body).status_code == 503
    assert client.post("/api/segments/analyze", json=body).status_code == 502


def test_crud_and_definition_versioning(client):
    sid = client.post("/api/segments", json=BODY).json()["id"]
    assert client.get(f"/api/segments/{sid}").json()["definition_version"] == 1
    assert client.patch(f"/api/segments/{sid}", json={"name": "Renamed"}).json()["definition_version"] == 1
    new_def = {**DEF, "summary": "Changed"}
    assert client.patch(f"/api/segments/{sid}", json={"definition": new_def}).json()["definition_version"] == 2
    assert client.patch(f"/api/segments/{sid}", json={"interval_minutes": 30}).status_code == 422
    assert client.delete(f"/api/segments/{sid}").status_code == 204
    assert client.get(f"/api/segments/{sid}").status_code == 404


def test_reanalyze_existing_keeps_saved(client, fake_llm):
    sid = client.post("/api/segments", json=BODY).json()["id"]
    fake_llm.queue({**DEF, "summary": "Draft v2"})
    r = client.post(f"/api/segments/{sid}/analyze", json={"note": "only UK"})
    assert r.json()["definition"]["summary"] == "Draft v2"
    assert "Major world events" in fake_llm.calls[-1].user and "only UK" in fake_llm.calls[-1].user
    assert client.get(f"/api/segments/{sid}").json()["definition"]["summary"] == "Major world events"
