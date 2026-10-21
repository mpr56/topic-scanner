# Topic Scanner Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python backend that turns example-driven "segments" into scheduled news scans, groups the results into stories, scores them with Groq plus non-AI signals, and serves them over an authenticated HTTP API for a future React UI.

**Architecture:** There is one Python package, `scanner`. The pure modules (`text`, `scoring`, `sources/*`) parse and compute. `ai_tasks` wraps the two LLM jobs (analyze a segment, classify and score a batch). `runner` orchestrates one scan per segment against the database. `api` is a FastAPI app mounted under `/api` and deployed to Vercel. `cli` is the entrypoint that GitHub Actions cron calls hourly (`run-due`). SQLAlchemy targets SQLite locally and Postgres (Neon/Supabase) in production through `DATABASE_URL`.

**Tech Stack:** Python ≥3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2 + pydantic-settings, httpx, feedparser, itsdangerous, psycopg[binary], pytest. The Groq API is called directly over httpx using its OpenAI-compatible endpoint.

**Spec:** `docs/superpowers/specs/2026-10-21-topic-scanner-backend-design.md`

## Global Constraints

- Groq is the only AI provider, and every AI call goes through `LLMClient` (`scanner/llm/base.py`). Nothing else imports `scanner.llm.groq`, except the CLI/API wiring.
- Model names come from env: `GROQ_MODEL_ANALYZE` (default `llama-3.3-70b-versatile`) and `GROQ_MODEL_SCORE` (default `llama-3.1-8b-instant`). Check both on console.groq.com/docs/models in Task 1, and replace either default if it's deprecated.
- Default scoring weights are match 0.5 / buzz 0.3 / freshness 0.2. Freshness is full under 2h and reaches 0 at 48h. The cap is 40 new stories scored per segment per run. Rescore defaults to the last 48h.
- `interval_minutes` defaults to 120, with an allowed range of 60–1440.
- Tests never touch the network. HTTP goes through `httpx.MockTransport`, the LLM through `tests/fakes.FakeLLM`, and sources through `tests/fakes.FakeSource`.
- All datetimes are timezone-aware UTC. Storing a naive datetime is an error.
- Auth uses a session cookie (from `POST /api/login`) or `Authorization: Bearer <API_TOKEN>`. Only `GET /api/health` is open. CORS allows only `UI_ORIGIN`, with credentials.
- Production scraping never runs inside a Vercel request. Production sets `RUN_NOW_MODE=github`.
- Every API route lives under `/api`, so the UI can later be deployed to the same Vercel project (same origin, `SameSite=Lax` cookie).

## Review Focus

1. **A source that times out, returns an HTTP error, or returns malformed data.** The run should finish as `partial` with the error recorded and other sources' results saved. Covered in Task 9 (`test_source_error_is_recorded_and_others_continue`, `test_all_sources_fail_marks_failed`).
2. **The LLM returning unknown story ids, out-of-range scores, or skipping candidates.** Unknown ids become new stories, scores are clamped to 0–10, and skipped candidates stay pending. Covered in Task 8 (`test_classify_sanitises_response`).
3. **Missing, future, or naive timestamps from feeds, and SQLite returning naive datetimes.** Freshness falls back to first-seen and clamps future times, and loaded datetimes are always UTC-aware. Covered in Task 2 (`test_datetimes_round_trip_as_utc`) and Task 4 (`test_freshness_missing_and_future`).
4. **GitHub cron firing a few minutes early or late.** A segment due "now-ish" still runs, with a 5-minute grace. Covered in Task 9 (`test_is_due_grace`).
5. **Junk or tracking-laden URLs** (no scheme, `utm_*`, uppercase host, empty string). Canonicalisation must not raise, and the same article must collapse to one row. Covered in Task 3 (`test_canonicalize_url_*`).

---

## File Structure

```
pyproject.toml                 package + deps + pytest config
requirements.txt               "." (lets Vercel install the package)
.env.example
vercel.json                    rewrites /api/* → api/index.py
api/index.py                   Vercel entry: app = create_app()
.github/workflows/scan.yml     hourly cron + manual dispatch
scanner/
  __init__.py
  __main__.py                  → cli.main()
  config.py                    Settings, normalize_db_url, get_settings
  schemas.py                   SourceConfig, SegmentDefinition, ScoringConfig
  db.py                        make_engine, make_sessionmaker, init_db, get_sessionmaker
  models.py                    Base, UTCDateTime, Segment, Story, Article, Run
  text.py                      canonicalize_url, normalize_title, titles_match, matches_exclude
  scoring.py                   freshness/buzz/combined, score_story
  sources/
    __init__.py                build_sources(settings)
    base.py                    RawArticle, SourceError, Source protocol, http helpers
    google_news.py
    reddit.py
    hackernews.py
  llm/
    __init__.py
    base.py                    LLMResult, LLMError, RateLimited, LLMClient
    groq.py                    GroqClient
  ai_tasks.py                  analyze_segment, classify_batch, Candidate, OpenStory, Decision
  runner.py                    Budget, is_due, run_segment, run_due, rescore_recent
  seed.py                      seed_segments
  cli.py                       main(argv)
  api/
    __init__.py
    app.py                     create_app
    auth.py                    login/logout routes, require_auth dependency
    schemas.py                 request/response models
    segments.py                segment CRUD + analyze routes
    stories.py                 stories, dismiss, rescore routes
    runs.py                    runs list + run-now routes
tests/
  conftest.py                  engine/session fixtures, now fixture
  fakes.py                     FakeLLM, FakeSource
  factories.py                 make_segment, make_story, make_article
  fixtures/google_news.xml, reddit_listing.json, hn_hits.json
  test_config.py test_models.py test_text.py test_scoring.py
  test_google_news.py test_reddit.py test_hackernews.py
  test_groq.py test_ai_tasks.py test_runner.py
  test_api_segments.py test_api_stories_runs.py test_cli.py
```

---

### Task 1: Project scaffold, settings, domain schemas

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.env.example`, `scanner/__init__.py`, `scanner/config.py`, `scanner/schemas.py`, `tests/__init__.py` (empty), `tests/test_config.py`
- Modify: `.gitignore` (append; keep the existing two lines)

**Interfaces:**
- Produces:
  - `normalize_db_url(url: str) -> str`
  - `class Settings(BaseSettings)` with fields (env names are the upper-cased field names, read from `.env` if present): `database_url="sqlite:///./scanner.db"`, `groq_api_key=""`, `groq_model_analyze`, `groq_model_score`, `api_token=""`, `app_password=""`, `session_secret="dev-insecure-change-me"`, `ui_origin="http://localhost:5173"`, `cookie_secure: bool=True`, `run_token_budget: int=20000`, `run_now_mode: Literal["inline","github"]="inline"`, `github_token=""`, `github_repo=""` (`owner/name`), `github_ref="main"`, `reddit_client_id=""`, `reddit_client_secret=""`, `user_agent="topic-scanner/0.1"`. A field validator applies `normalize_db_url` to `database_url`.
  - `get_settings() -> Settings`, cached with `functools.lru_cache`
  - `SourceType = Literal["google_news","reddit","hackernews"]`
  - `class SourceConfig(BaseModel)`: `type: SourceType`, `mode: Literal["search","feed"]="search"`, `queries: list[str]=[]`, `subreddits: list[str]=[]`, `sections: list[str]=[]`, `region: str="US"`, `limit: int=Field(25, ge=1, le=100)`, `enabled: bool=True`
  - `class SegmentDefinition(BaseModel)`: `summary: str`, `include: list[str]=[]`, `exclude: list[str]=[]`, `sources: list[SourceConfig]=[]`
  - `class ScoringWeights(BaseModel)`: `match=0.5`, `buzz=0.3`, `freshness=0.2` (each `ge=0`; a model validator requires sum > 0)
  - `BuzzSignal = Literal["outlets","runs","engagement"]`
  - `class ScoringConfig(BaseModel)`: `weights: ScoringWeights`, `fresh_full_hours: float=2`, `fresh_zero_hours: float=48` (validator: zero > full), `buzz_signals: list[BuzzSignal]=["outlets","runs","engagement"]`, `max_new_stories_per_run: int=Field(40, ge=1)`

- [ ] **Step 1: Create `pyproject.toml`.** Use setuptools, package `scanner*`, `requires-python = ">=3.12"`. Deps: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2.0`, `pydantic>=2`, `pydantic-settings`, `httpx`, `feedparser`, `itsdangerous`, `psycopg[binary]`. Extra `dev`: `pytest`. `[tool.pytest.ini_options] testpaths=["tests"]`. `requirements.txt` holds the single line `.`. `.env.example` lists every Settings env var with a one-line comment. Append `.venv/`, `__pycache__/`, `*.db`, `.env`, `*.egg-info/` to `.gitignore`.

- [ ] **Step 2: Create the venv and install.**
Run: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
Expected: installs without errors.

- [ ] **Step 3: Write failing tests in `tests/test_config.py`.**

```python
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
```

- [ ] **Step 4: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_config.py -v`. Expected: FAIL (ImportError).

- [ ] **Step 5: Implement `scanner/config.py` and `scanner/schemas.py`** according to the Interfaces above. Check the two default Groq model names against Groq's current model list.

- [ ] **Step 6: Run them to make sure they pass.** Run: `.venv/bin/pytest tests/test_config.py -v`. Expected: PASS.

- [ ] **Step 7: Commit.**
```bash
git add pyproject.toml requirements.txt .env.example .gitignore scanner tests
git commit -m "feat: project scaffold, settings and domain schemas"
```

---

### Task 2: Database models and session

**Files:**
- Create: `scanner/db.py`, `scanner/models.py`, `tests/conftest.py`, `tests/factories.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: `SegmentDefinition`, `ScoringConfig`, `get_settings` (Task 1)
- Produces:
  - `make_engine(url: str) -> Engine`. For SQLite it sets `check_same_thread=False`, uses `StaticPool` when the URL is in-memory (`sqlite://` or `:memory:`), and enables `PRAGMA foreign_keys=ON` through a connect event. Otherwise it uses `pool_pre_ping=True`.
  - `make_sessionmaker(engine) -> sessionmaker[Session]` (`expire_on_commit=False`)
  - `init_db(engine) -> None` (`Base.metadata.create_all`, idempotent)
  - `get_sessionmaker() -> sessionmaker[Session]`, cached and built from `get_settings().database_url`
  - `class UTCDateTime(TypeDecorator)`: a binding of a naive datetime raises `ValueError`. Values are stored as UTC and loaded with `tzinfo=timezone.utc`.
  - `Segment`: `id`, `name: str`, `examples: JSON list[str]`, `note: str=""`, `definition: JSON dict`, `definition_version: int=1`, `scoring: JSON dict`, `interval_minutes: int=120`, `active: bool=True`, `last_run_at: UTCDateTime|None`, `created_at`, `updated_at`. It has relationships `stories` and `runs` (cascade `all, delete-orphan`) and methods `get_definition() -> SegmentDefinition` and `get_scoring() -> ScoringConfig`.
  - `Story`: `id`, `segment_id` (FK, `ondelete=CASCADE`), `headline`, `status: str` (`"pending"`|`"scored"`), `match_score: float|None`, `reason: str|None`, `scored_version: int|None`, `published_at|None`, `first_seen`, `last_seen`, `runs_seen: int=1`, `last_seen_run_id: int|None`, `dismissed: bool=False`. It has an `articles` relationship (cascade).
  - `Article`: `id`, `segment_id` (FK cascade), `story_id` (FK cascade), `source: str`, `outlet: str`, `title`, `url`, `canonical_url`, `published_at|None`, `snippet: str=""`, `engagement: int=0`, `first_seen`, `last_seen`, with `UniqueConstraint("segment_id","canonical_url")`.
  - `Run`: `id`, `segment_id` (FK cascade), `started_at`, `finished_at|None`, `status: str` (`running|success|partial|failed`), `fetched`, `new_articles`, `new_stories`, `updated_stories`, `scored` (ints, default 0), `errors: JSON list[dict]` (`{"source": str, "message": str}`).
  - `tests/conftest.py` fixtures: `engine` (in-memory + `init_db`), `session`, and `now` (`datetime(2026,10,21,12,0,tzinfo=UTC)`).
  - `tests/factories.py`: `make_segment(session, **overrides) -> Segment` (defaults: name `"Big news"`, examples `["Tesla Roadster flies"]`, a definition with summary `"Major news"` and one `google_news` feed source, default scoring), `make_story(session, segment, **overrides) -> Story`, `make_article(session, story, **overrides) -> Article`. Each one flushes and returns.

- [ ] **Step 1: Write failing tests in `tests/test_models.py`.**

```python
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
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_models.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `scanner/db.py`, `scanner/models.py`, `tests/conftest.py`, and `tests/factories.py`** according to the Interfaces above.
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit.** `git add scanner tests && git commit -m "feat: database models with UTC-safe datetimes"`

---

### Task 3: Text helpers (URL canonicalisation, title matching, exclude filter)

**Files:**
- Create: `scanner/text.py`, `tests/test_text.py`

**Interfaces:**
- Produces:
  - `canonicalize_url(url: str) -> str`. Strips whitespace. Adds `https://` if no scheme, forces `http`→`https`, lowercases the host, and strips a leading `www.`. Drops the fragment and any query keys that start with `utm_` or are in `{"fbclid","gclid","ref","ref_src","cmpid","smid"}`, then sorts the remaining query keys. Strips a trailing `/` from non-root paths. It never raises: `""` maps to `""`, and anything unparseable is returned stripped.
  - `normalize_title(title: str) -> str`. Removes one trailing outlet suffix after `" - "`, `" | "` or `" — "` when the suffix is at most 4 words. Then it lowercases, replaces non-alphanumerics with spaces, and collapses whitespace.
  - `titles_match(a: str, b: str, threshold: float = 0.85) -> bool`. Returns `difflib.SequenceMatcher` ratio ≥ threshold on the normalized titles. Empty normalized titles never match.
  - `matches_exclude(text: str, exclude: list[str]) -> bool`. A case-insensitive, word-boundary match on any term.

- [ ] **Step 1: Write failing tests in `tests/test_text.py`.**

```python
@pytest.mark.parametrize("raw,expected", [
    ("https://www.Example.com/a/?utm_source=x&id=2&fbclid=y#frag", "https://example.com/a?id=2"),
    ("http://example.com/a/", "https://example.com/a"),
    ("example.com/a", "https://example.com/a"),
    ("https://example.com/?b=2&a=1", "https://example.com/?a=1&b=2"),
    ("  https://example.com/x  ", "https://example.com/x"),
])
def test_canonicalize_url_cases(raw, expected):
    assert canonicalize_url(raw) == expected

def test_canonicalize_url_never_raises_on_junk():
    assert canonicalize_url("") == ""
    assert isinstance(canonicalize_url("not a url at all ::::"), str)
    assert isinstance(canonicalize_url("http://[broken"), str)

def test_normalize_title_strips_outlet_suffix():
    assert normalize_title("Tesla Roadster flies - Reuters") == "tesla roadster flies"
    assert normalize_title("Tesla Roadster flies | The Verge") == "tesla roadster flies"
    assert normalize_title("Why the war - and the peace - matter to five big nations") == \
        "why the war and the peace matter to five big nations"

def test_titles_match():
    assert titles_match("Tesla Roadster takes flight in demo - BBC",
                        "Tesla Roadster takes flight in demo | The Verge")
    assert not titles_match("Tesla Roadster flies", "France elects new prime minister")
    assert not titles_match("", "")

def test_matches_exclude():
    assert matches_exclude("Celebrity gossip roundup", ["gossip"])
    assert not matches_exclude("Gossipy neighbours", ["gossip"])
    assert not matches_exclude("anything", [])
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_text.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `scanner/text.py`** according to the Interfaces above.
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest tests/test_text.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** `git add scanner/text.py tests/test_text.py && git commit -m "feat: url canonicalisation and title matching"`

---

### Task 4: Scoring math

**Files:**
- Create: `scanner/scoring.py`, `tests/test_scoring.py`

**Interfaces:**
- Consumes: `ScoringConfig` (Task 1), `Story`/`Article` (Task 2)
- Produces:
  - `freshness_score(published_at: datetime|None, first_seen: datetime, now: datetime, cfg: ScoringConfig) -> float`. Uses `published_at`, falling back to `first_seen`, with future times clamped to `now`. The score is 10 when age ≤ full, 0 when age ≥ zero, and linear in between.
  - `buzz_score(outlets: int, runs_seen: int, engagement: int, cfg: ScoringConfig) -> float`. It's 10 × the mean of the enabled parts:
    ```
    outlets    = min(1, (outlets - 1) / 4)          # 5+ distinct outlets = full
    runs       = min(1, (runs_seen - 1) / 5)        # seen in 6+ runs = full
    engagement = min(1, log10(1 + engagement) / 4)  # 10k = full
    ```
  - `combined_score(match: float|None, buzz: float, freshness: float, cfg: ScoringConfig) -> float|None`. Returns `None` if match is `None`. Otherwise it's the weighted mean (weights divided by their sum), clamped to [1, 10] and rounded to 1 decimal.
  - `@dataclass StoryScores: match: float|None; buzz: float; freshness: float; combined: float|None`
  - `score_story(story: Story, cfg: ScoringConfig, now: datetime) -> StoryScores`. `outlets` is the count of distinct `article.outlet` and engagement is the sum of `article.engagement`. Buzz and freshness are rounded to 1 decimal.

- [ ] **Step 1: Write failing tests in `tests/test_scoring.py`** (`cfg = ScoringConfig()`, `now` fixture):

```python
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
    assert s.combined == pytest.approx(0.5*8 + 0.3*s.buzz + 0.2*10, abs=0.1)
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_scoring.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `scanner/scoring.py`.**
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest tests/test_scoring.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** `git add scanner/scoring.py tests/test_scoring.py && git commit -m "feat: buzz, freshness and combined scoring"`

---

### Task 5: Source base and Google News

**Files:**
- Create: `scanner/sources/__init__.py`, `scanner/sources/base.py`, `scanner/sources/google_news.py`, `tests/fixtures/google_news.xml`, `tests/test_google_news.py`

**Interfaces:**
- Consumes: `SourceConfig` (Task 1)
- Produces:
  - `@dataclass(frozen=True) RawArticle: source: str; outlet: str; title: str; url: str; published_at: datetime|None; snippet: str = ""; engagement: int = 0`
  - `class SourceError(Exception)`
  - `class Source(Protocol): name: str; def fetch(self, cfg: SourceConfig, http: httpx.Client, now: datetime) -> list[RawArticle]`
  - `get_text(http, url, **kw) -> str` / `get_json(http, url, **kw) -> Any` in `base.py`. These raise `SourceError(f"{status} from {host}")` on a non-2xx response, and wrap `httpx.HTTPError` and parse errors in `SourceError`.
  - `clean_snippet(html: str, max_len: int = 300) -> str`. Strips tags, unescapes entities, and collapses whitespace.
  - `google_news.SECTIONS = {"WORLD","NATION","BUSINESS","TECHNOLOGY","ENTERTAINMENT","SPORTS","SCIENCE","HEALTH"}`
  - `google_news.build_urls(cfg: SourceConfig) -> list[str]`. Locale params are `hl=en-{R}&gl={R}&ceid={R}:en` (R = `cfg.region`). Feed mode with no sections gives `https://news.google.com/rss?{locale}`. Each section gives `https://news.google.com/rss/headlines/section/topic/{SECTION}?{locale}`, case-insensitive, and an unknown section raises `SourceError`. Search mode gives `https://news.google.com/rss/search?q={urlencoded(query + " when:1d")}&{locale}` per query.
  - `google_news.parse_feed(xml: str) -> list[RawArticle]`. Uses feedparser. `outlet` comes from `entry.source.title` (fallback `"Google News"`), and a trailing `" - {outlet}"` is stripped from the title. `published_at` comes from `published_parsed` as UTC, or `None`.
  - `class GoogleNewsSource: name = "google_news"`. `fetch` gets each URL and concatenates parsed articles, truncated to `cfg.limit` per URL.
  - `sources/__init__.py`: `build_sources(settings: Settings) -> dict[str, Source]`. Reddit and HN are added in Task 6.

- [ ] **Step 1: Write the fixture.** `tests/fixtures/google_news.xml` is a minimal RSS 2.0 file with two `<item>`s:
  1. title `Tesla Roadster flies - Reuters`, link `https://news.google.com/rss/articles/abc`, pubDate `Tue, 21 Oct 2026 10:00:00 GMT`, `<source url="https://reuters.com">Reuters</source>`, description `<a href="x">Tesla Roadster flies</a>&nbsp;Reuters`
  2. title `France names new PM - BBC News`, no pubDate, `<source>BBC News</source>`

- [ ] **Step 2: Write failing tests in `tests/test_google_news.py`.**

```python
def test_build_urls_modes():
    loc = "hl=en-US&gl=US&ceid=US:en"
    assert build_urls(SourceConfig(type="google_news", mode="feed")) == [f"https://news.google.com/rss?{loc}"]
    assert build_urls(SourceConfig(type="google_news", mode="feed", sections=["world"])) == \
        [f"https://news.google.com/rss/headlines/section/topic/WORLD?{loc}"]
    assert build_urls(SourceConfig(type="google_news", queries=["tesla roadster"])) == \
        [f"https://news.google.com/rss/search?q=tesla+roadster+when%3A1d&{loc}"]
    assert "gl=AU" in build_urls(SourceConfig(type="google_news", mode="feed", region="AU"))[0]

def test_unknown_section_raises():
    with pytest.raises(SourceError):
        build_urls(SourceConfig(type="google_news", mode="feed", sections=["memes"]))

def test_parse_feed():
    a, b = parse_feed((FIXTURES / "google_news.xml").read_text())
    assert (a.title, a.outlet, a.source) == ("Tesla Roadster flies", "Reuters", "google_news")
    assert a.published_at == datetime(2026, 10, 21, 10, tzinfo=UTC)
    assert "<a" not in a.snippet
    assert (b.outlet, b.published_at) == ("BBC News", None)

def test_fetch_raises_source_error_on_http_failure(now):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(SourceError, match="503"):
        GoogleNewsSource().fetch(SourceConfig(type="google_news", mode="feed"), http, now)
```

- [ ] **Step 3: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_google_news.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement `sources/base.py`, `sources/google_news.py`, and `sources/__init__.py`.**
- [ ] **Step 5: Run them to make sure they pass.** Run: `.venv/bin/pytest tests/test_google_news.py -v`. Expected: PASS.
- [ ] **Step 6: Commit.** `git add scanner/sources tests && git commit -m "feat: source interface and google news source"`

---

### Task 6: Reddit and Hacker News sources

**Files:**
- Create: `scanner/sources/reddit.py`, `scanner/sources/hackernews.py`, `tests/fixtures/reddit_listing.json`, `tests/fixtures/hn_hits.json`, `tests/test_reddit.py`, `tests/test_hackernews.py`
- Modify: `scanner/sources/__init__.py` (register both)

**Interfaces:**
- Consumes: `RawArticle`, `SourceError`, `get_json`, `clean_snippet` (Task 5)
- Produces:
  - `reddit.build_urls(cfg: SourceConfig, base: str = "https://www.reddit.com") -> list[str]`. Search mode gives `{base}/search.json?q={q}&sort=new&t=day&limit={limit}` per query. Feed mode gives `{base}/r/{sub}/hot.json?limit={limit}` per subreddit, and an empty `subreddits` list raises `SourceError("reddit feed mode needs at least one subreddit")`.
  - `reddit.parse_listing(payload: dict) -> list[RawArticle]`. Skips `stickied` posts. `url` is `"https://www.reddit.com" + permalink` when `is_self`, else `url`. `outlet` is `f"r/{subreddit}"`, `engagement` is `score + num_comments`, `published_at` comes from `created_utc`, and `snippet` is `clean_snippet(selftext)`.
  - `class RedditSource(client_id: str = "", client_secret: str = "", user_agent: str = "topic-scanner/0.1")`, `name = "reddit"`. Every request sends a `User-Agent`. With credentials, it POSTs once per instance to `https://www.reddit.com/api/v1/access_token` (`grant_type=client_credentials`, basic auth), caches the token, and requests via base `https://oauth.reddit.com` with `Authorization: bearer <token>`. Without credentials it uses `https://www.reddit.com`.
  - `hackernews.build_urls(cfg: SourceConfig, now: datetime) -> list[str]`. Feed mode gives `https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}`. Search mode gives `https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=story&hitsPerPage={limit}&numericFilters=created_at_i%3E{int(now.timestamp()) - 86400}`.
  - `hackernews.parse_hits(payload: dict) -> list[RawArticle]`. If `url` is null it uses `https://news.ycombinator.com/item?id={objectID}`. `engagement` is `(points or 0) + (num_comments or 0)`, `outlet` is `"Hacker News"`, and `published_at` comes from `created_at_i`.
  - `class HackerNewsSource`, `name = "hackernews"`
  - `build_sources(settings)` now returns all three, passing `settings.reddit_client_id/secret` and `settings.user_agent` to `RedditSource`.

- [ ] **Step 1: Write the fixtures.** `reddit_listing.json` is `{"data":{"children":[...]}}` with three posts: an external link (`subreddit` "worldnews", score 1200, num_comments 300, created_utc 1792576800), a self post (`is_self` true, permalink `/r/news/comments/1/x/`, selftext `"<p>Body</p>"`), and a `stickied` post. `hn_hits.json` is `{"hits":[...]}` with one hit that has a url, points 250 and num_comments 80, and one with `url: null`, `objectID: "42"`, `points: null`.

- [ ] **Step 2: Write failing tests.**

```python
# tests/test_reddit.py
def test_build_urls():
    assert build_urls(SourceConfig(type="reddit", queries=["tesla roadster"])) == \
        ["https://www.reddit.com/search.json?q=tesla+roadster&sort=new&t=day&limit=25"]
    assert build_urls(SourceConfig(type="reddit", mode="feed", subreddits=["worldnews"], limit=10)) == \
        ["https://www.reddit.com/r/worldnews/hot.json?limit=10"]
    with pytest.raises(SourceError):
        build_urls(SourceConfig(type="reddit", mode="feed"))

def test_parse_listing():
    link, self_post = parse_listing(json.loads((FIXTURES / "reddit_listing.json").read_text()))
    assert (link.outlet, link.engagement) == ("r/worldnews", 1500)
    assert link.published_at == datetime.fromtimestamp(1792576800, UTC)
    assert self_post.url == "https://www.reddit.com/r/news/comments/1/x/"
    assert self_post.snippet == "Body"

def test_oauth_token_fetched_once_and_used(now):
    seen = []
    def handler(req):
        seen.append(req)
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        return httpx.Response(200, json={"data": {"children": []}})
    http = httpx.Client(transport=httpx.MockTransport(handler))
    src = RedditSource("id", "secret")
    cfg = SourceConfig(type="reddit", mode="feed", subreddits=["a", "b"])
    src.fetch(cfg, http, now)
    assert [r.url.path for r in seen].count("/api/v1/access_token") == 1
    api = [r for r in seen if r.url.host == "oauth.reddit.com"]
    assert len(api) == 2 and api[0].headers["authorization"] == "bearer T"
    assert all("user-agent" in r.headers for r in seen)

def test_blocked_raises_source_error(now):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(SourceError, match="403"):
        RedditSource().fetch(SourceConfig(type="reddit", queries=["x"]), http, now)

# tests/test_hackernews.py
def test_build_urls(now):
    assert build_urls(SourceConfig(type="hackernews", mode="feed"), now) == \
        ["https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=25"]
    [u] = build_urls(SourceConfig(type="hackernews", queries=["tesla roadster"]), now)
    assert u.startswith("https://hn.algolia.com/api/v1/search_by_date?query=tesla+roadster&tags=story")
    assert f"created_at_i%3E{int(now.timestamp()) - 86400}" in u

def test_parse_hits():
    a, b = parse_hits(json.loads((FIXTURES / "hn_hits.json").read_text()))
    assert (a.engagement, a.outlet) == (330, "Hacker News")
    assert b.url == "https://news.ycombinator.com/item?id=42" and b.engagement >= 0
```

- [ ] **Step 3: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_reddit.py tests/test_hackernews.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement both sources and register them.**
- [ ] **Step 5: Run them to make sure they pass.** Run: `.venv/bin/pytest -v`. Expected: all PASS.
- [ ] **Step 6: Commit.** `git add scanner/sources tests && git commit -m "feat: reddit and hacker news sources"`

---

### Task 7: LLM interface and Groq client

**Files:**
- Create: `scanner/llm/__init__.py`, `scanner/llm/base.py`, `scanner/llm/groq.py`, `tests/fakes.py`, `tests/test_groq.py`

**Interfaces:**
- Produces:
  - `@dataclass LLMResult: data: dict; tokens: int`
  - `class LLMError(Exception)`; `class RateLimited(LLMError)`
  - `class LLMClient(Protocol): def complete_json(self, system: str, user: str, *, model: str) -> LLMResult`
  - `class GroqClient(api_key: str, http: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep, max_retries: int = 3)`. It POSTs `https://api.groq.com/openai/v1/chat/completions` with `{"model", "messages":[system,user], "response_format":{"type":"json_object"}, "temperature":0.2}` and a Bearer key, timeout 60s. On 429 it sleeps `min(float(retry-after or 2), 20)` and retries up to `max_retries` times, then raises `RateLimited`. Any other non-2xx, transport error, or non-JSON/non-object content raises `LLMError`. An empty `api_key` raises `LLMError("GROQ_API_KEY is not set")` at call time. `tokens` is `usage.total_tokens`, or 0 if absent.
  - `tests/fakes.py`: `FakeLLM(*responses: dict | Exception)`. Its `complete_json` pops the next response, raises it if it's an Exception, and otherwise returns `LLMResult(resp, 100)`. It appends `FakeCall(system, user, model)` to `.calls`. When exhausted it raises `AssertionError("unexpected LLM call")`. Also `FakeSource(name: str, articles: list[RawArticle] | Exception)`, whose `fetch` returns the articles or raises, and records the `SourceConfig` it was given in `.configs`.

- [ ] **Step 1: Write failing tests in `tests/test_groq.py`** (each one builds `httpx.Client(transport=MockTransport(handler))` and `sleeps = []`):

```python
def ok(content='{"a": 1}', tokens=321):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"total_tokens": tokens}})

def test_success_shapes_request():
    reqs = []
    client = make(lambda r: reqs.append(r) or ok())
    res = client.complete_json("sys", "usr", model="m1")
    assert res == LLMResult({"a": 1}, 321)
    body = json.loads(reqs[0].content)
    assert body["model"] == "m1" and body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert reqs[0].headers["authorization"] == "Bearer key"

def test_retries_after_429_then_succeeds():
    responses = iter([httpx.Response(429, headers={"retry-after": "2"}), ok()])
    client = make(lambda r: next(responses))
    assert client.complete_json("s", "u", model="m").data == {"a": 1}
    assert sleeps == [2.0]

def test_persistent_429_raises_rate_limited():
    client = make(lambda r: httpx.Response(429))
    with pytest.raises(RateLimited):
        client.complete_json("s", "u", model="m")
    assert len(sleeps) == 3

@pytest.mark.parametrize("resp", [httpx.Response(500), ok(content="not json"), ok(content="[1,2]")])
def test_errors_raise_llm_error(resp):
    with pytest.raises(LLMError):
        make(lambda r: resp).complete_json("s", "u", model="m")

def test_missing_key():
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        GroqClient("").complete_json("s", "u", model="m")
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_groq.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `scanner/llm/*` and `tests/fakes.py`.**
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest tests/test_groq.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** `git add scanner/llm tests && git commit -m "feat: LLM interface and Groq client"`

---

### Task 8: AI tasks: analyze segment, classify-and-score batch

**Files:**
- Create: `scanner/ai_tasks.py`, `tests/test_ai_tasks.py`

**Interfaces:**
- Consumes: `LLMClient`, `LLMError` (Task 7); `SegmentDefinition`, `SourceConfig` (Task 1)
- Produces:
  - `analyze_segment(llm: LLMClient, model: str, name: str, examples: list[str], note: str = "", existing: SegmentDefinition | None = None) -> tuple[SegmentDefinition, int]`. It raises `ValueError` if there are no non-blank examples. The system prompt describes the job and the three sources with both modes. It lists Google News `SECTIONS`, says that Reddit feed mode needs subreddits, and says to prefer **feed mode** when the examples share a kind of story (significance) rather than a topic. It asks for JSON `{"summary","include","exclude","sources":[SourceConfig…]}`. The user prompt contains the name, each example, the note, and `existing` (as JSON) when given. Source entries whose type is unknown or that fail validation are dropped. If no sources survive, it falls back to `[SourceConfig(type="google_news", queries=[name])]`. On invalid JSON shape (missing summary) it retries once, and a second failure raises `LLMError`. The returned int is the total tokens.
  - `@dataclass Candidate: key: str; title: str; snippet: str; source: str`
  - `@dataclass OpenStory: id: int; headline: str`
  - `@dataclass Decision: key: str; story_id: int | None; match: float | None; reason: str | None`
  - `classify_batch(llm, model, definition: SegmentDefinition, candidates: list[Candidate], open_stories: list[OpenStory]) -> tuple[list[Decision], int]`. With no candidates it returns `([], 0)` and makes no call. The prompt contains the definition (summary/include/exclude), each open story as `#{id}: {headline}`, and each candidate as `{key}: {title} — {snippet[:200]} ({source})`. It instructs the model that `match` 0–10 means fit to the definition, which for significance-type definitions means how major and widely relevant the story is. Expected JSON is `{"results":[{"key","same_as": int|null,"match": number,"reason": str}]}`. Post-processing: a `same_as` value that isn't among the open ids becomes `story_id=None`. When `story_id` is set, match and reason are `None`. `match` is clamped to [0,10] and a missing match makes the result skip that key. Unknown keys are ignored, and keys missing from the response are absent from the return. Same retry-once rule as above.

- [ ] **Step 1: Write failing tests in `tests/test_ai_tasks.py`.**

```python
GOOD = {"summary": "Major world events", "include": ["global impact"], "exclude": ["gossip"],
        "sources": [{"type": "google_news", "mode": "feed", "sections": ["WORLD"]},
                    {"type": "twitter", "mode": "feed"}]}

def test_analyze_parses_and_drops_unknown_sources():
    llm = FakeLLM(GOOD)
    d, tokens = analyze_segment(llm, "big-model", "Big news", ["Tesla Roadster flies", "France turmoil"], "skip celebs")
    assert d.summary == "Major world events" and [s.type for s in d.sources] == ["google_news"]
    assert tokens == 100 and llm.calls[0].model == "big-model"
    for text in ["Tesla Roadster flies", "France turmoil", "skip celebs"]:
        assert text in llm.calls[0].user

def test_analyze_falls_back_to_google_search():
    d, _ = analyze_segment(FakeLLM({**GOOD, "sources": []}), "m", "Big news", ["x"])
    assert d.sources == [SourceConfig(type="google_news", queries=["Big news"])]

def test_analyze_retries_once_then_fails():
    assert analyze_segment(FakeLLM({"nope": 1}, GOOD), "m", "n", ["x"])[1] == 200
    with pytest.raises(LLMError):
        analyze_segment(FakeLLM({"nope": 1}, {"nope": 2}), "m", "n", ["x"])

def test_analyze_requires_examples():
    with pytest.raises(ValueError):
        analyze_segment(FakeLLM(), "m", "n", ["  "])

def test_analyze_includes_existing_definition():
    llm = FakeLLM(GOOD)
    analyze_segment(llm, "m", "n", ["x"], existing=SegmentDefinition(summary="OLD SUMMARY"))
    assert "OLD SUMMARY" in llm.calls[0].user

def test_classify_sanitises_response():
    llm = FakeLLM({"results": [
        {"key": "c0", "same_as": 7, "match": 9, "reason": "dup"},
        {"key": "c1", "same_as": 999, "match": 6, "reason": "new"},
        {"key": "c2", "same_as": None, "match": 12, "reason": "huge"},
        {"key": "zz", "same_as": None, "match": 5, "reason": "?"},
    ]})
    cands = [Candidate(f"c{i}", f"t{i}", "", "google_news") for i in range(4)]
    out, tokens = classify_batch(llm, "m", SegmentDefinition(summary="S", exclude=["gossip"]),
                                 cands, [OpenStory(7, "Tesla Roadster flies")])
    by = {d.key: d for d in out}
    assert by["c0"] == Decision("c0", 7, None, None)
    assert (by["c1"].story_id, by["c1"].match) == (None, 6)
    assert by["c2"].match == 10
    assert "c3" not in by and "zz" not in by and tokens == 100
    assert "#7: Tesla Roadster flies" in llm.calls[0].user and "gossip" in llm.calls[0].user

def test_classify_empty_makes_no_call():
    assert classify_batch(FakeLLM(), "m", SegmentDefinition(summary="S"), [], []) == ([], 0)
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_ai_tasks.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `scanner/ai_tasks.py`.** Validate the response with private Pydantic models.
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest tests/test_ai_tasks.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** `git add scanner/ai_tasks.py tests/test_ai_tasks.py && git commit -m "feat: segment analysis and batch classify/score"`

---

### Task 9: Runner: scan pipeline, scheduling, budget, rescore

**Files:**
- Create: `scanner/runner.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 2–8
- Produces:
  - `class Budget(tokens: int)` with `.remaining: int`, `.spend(n: int) -> None`, and `.exhausted -> bool` (`remaining <= 0`)
  - `GRACE = timedelta(minutes=5)`, `OPEN_WINDOW = timedelta(hours=48)`, `BATCH_SIZE = 15`, `MAX_OPEN_STORIES = 40`
  - `is_due(segment: Segment, now: datetime) -> bool`. Returns `active` and (`last_run_at is None` or `now >= last_run_at + interval - GRACE`).
  - `run_segment(session: Session, segment: Segment, *, llm: LLMClient, model: str, http: httpx.Client | None, now: datetime, budget: Budget, sources: Mapping[str, Source]) -> Run`. It flushes but doesn't commit.
  - `run_due(session_factory: sessionmaker, *, llm, model, http, now, budget, sources) -> list[Run]`. It processes active segments ordered by `last_run_at` (nulls first), each in its own session, and commits each. If `run_segment` raises, it rolls back and then commits a `Run(status="failed", errors=[{"source": "runner", "message": repr(exc)[:300]}])` with `segment.last_run_at = now`. Other segments still run.
  - `rescore_recent(session, segment, *, llm, model, now, budget, hours: int = 48) -> int`. Re-classifies non-dismissed stories with `last_seen >= now - hours`, passing `open_stories=[]` in batches. For each decision it sets `match_score`, `reason`, `status="scored"`, `scored_version=segment.definition_version`, stops when the budget runs out, and returns the count updated.

`run_segment` algorithm (the order matters and the tests depend on it):

```
1. run = Run(segment, started_at=now, status="running"); flush.
2. For each enabled cfg in definition.sources: fetch via sources[cfg.type];
   on any Exception append {"source": cfg.type, "message": str(exc)[:300]} and continue.
   run.fetched = total raw count.
3. Drop raws where matches_exclude(title + " " + snippet, definition.exclude).
4. Canonicalise urls; drop in-batch duplicates (keep first).
5. Existing Article with same (segment_id, canonical_url): update last_seen=now,
   engagement=max(old,new); mark its story touched. Others are "new raws".
6. open = non-dismissed stories of this segment with last_seen >= now - OPEN_WINDOW
   (most recent first, at most MAX_OPEN_STORIES).
7. Each new raw: if titles_match with an open story's headline or any of its article titles
   → attach (new Article) to that story, touch it. Otherwise put it in a group: join the first
   existing group whose representative title titles_match, else start a new group.
   Order groups by number of distinct outlets desc (stable).
8. AI phase, stop entirely on RateLimited / LLMError (append {"source": "llm", ...}) or budget.exhausted;
   `cap` = scoring.max_new_stories_per_run counts stories sent to the AI this run:
   a. Pending stories of this segment (status="pending", not dismissed), ordered by
      score_story(...).buzz desc, up to cap: classify_batch(open_stories=[]) in BATCH_SIZE chunks,
      keys "p{story.id}"; set match/reason/status="scored"/scored_version.
   b. Groups up to the remaining cap, in BATCH_SIZE chunks with keys "c0","c1",… in group order:
      classify_batch(candidates=representative article of each group, open_stories=open).
      Decision.story_id → attach the group's articles to that story (touch it).
      Decision with match → new Story(status="scored", headline=rep title, match, reason,
      scored_version=definition_version).
   c. Any group with no decision (cap, budget, error, or omitted by the model)
      → new Story(status="pending", headline=rep title).
   Spend each call's tokens on the budget; run.scored += decisions applied.
9. New stories: first_seen=last_seen=now, runs_seen=1, last_seen_run_id=run.id.
   Touched existing stories: last_seen=now; if last_seen_run_id != run.id → runs_seen += 1, set it.
   Every story that gained articles: published_at = min of its articles' non-null published_at.
10. Counts: new_articles, new_stories, updated_stories (touched existing).
    status = "failed" if every enabled source errored (and there was ≥1);
             "partial" if any error or this segment still has pending stories; else "success".
    segment.last_run_at = now; run.finished_at = now; flush; return run.
```

- [ ] **Step 1: Write failing tests in `tests/test_runner.py`.** Helper: `raw(title, url, outlet="Reuters", source="google_news", published=None, engagement=0)` builds a `RawArticle`. `seg(session, sources=[...], **scoring)` uses `make_segment` with a definition whose sources are `SourceConfig(type=...)` for each fake. `go(session, segment, llm, fakes, now, budget=Budget(10_000))` calls `run_segment(..., model="m", http=None, sources=fakes)`.

```python
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
    go(session, s, FakeLLM({"results": [{"key": "c0", "same_as": None, "match": 8, "reason": "r"}]}),
       {"google_news": FakeSource("google_news", [a])}, now)
    later = now + timedelta(hours=2)
    b = replace(a, url="https://r.com/1?utm_source=x", engagement=50)
    go(session, s, FakeLLM(), {"google_news": FakeSource("google_news", [b])}, later)
    story = session.scalars(select(Story)).one()
    assert story.runs_seen == 2 and story.last_seen == later and story.articles[0].engagement == 50

def test_ai_assigns_to_existing_story(session, now):
    s = seg(session, ["google_news"])
    go(session, s, FakeLLM({"results": [{"key": "c0", "same_as": None, "match": 8, "reason": "r"}]}),
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
    run = go(session, s, FakeLLM({"results": [{"key": "c0", "same_as": None, "match": 8, "reason": "r"}]}), src, now)
    pending = session.scalars(select(Story).where(Story.status == "pending")).one()
    assert run.status == "partial"
    llm = FakeLLM({"results": [{"key": f"p{pending.id}", "same_as": None, "match": 5, "reason": "r"}]})
    go(session, s, llm, {"google_news": FakeSource("google_news", [])}, now + timedelta(hours=2))
    assert pending.status == "scored" and pending.headline in llm.calls[0].user

def test_source_error_is_recorded_and_others_continue(session, now):
    s = seg(session, ["google_news", "reddit"])
    run = go(session, s, FakeLLM({"results": [{"key": "c0", "same_as": None, "match": 8, "reason": "r"}]}),
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
    n = rescore_recent(session, s, llm=FakeLLM({"results": [{"key": f"p{fresh.id}", "same_as": None, "match": 9, "reason": "r"}]}),
                       model="m", now=now, budget=Budget(10_000))
    assert n == 1 and (fresh.match_score, fresh.scored_version) == (9, 2) and old.scored_version == 1

def test_story_published_is_earliest_article(session, now):
    s = seg(session, ["google_news"])
    go(session, s, FakeLLM({"results": [{"key": "c0", "same_as": None, "match": 8, "reason": "r"}]}),
       {"google_news": FakeSource("google_news", [
           raw("Tesla Roadster flies", "https://r.com/1", published=now - timedelta(hours=1)),
           raw("Tesla Roadster flies - BBC", "https://b.com/1", outlet="BBC", published=now - timedelta(hours=3))])}, now)
    assert session.scalars(select(Story)).one().published_at == now - timedelta(hours=3)
```

`seg(...)` takes `name=` and scoring kwargs. `make_segment` must accept `name`.

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_runner.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `scanner/runner.py`** following the algorithm above. Keep `run_segment` readable by splitting steps 2–9 into private helpers (`_fetch_all`, `_merge_existing`, `_group_new`, `_ai_phase`, `_touch`).
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit.** `git add scanner/runner.py tests/test_runner.py && git commit -m "feat: scan runner with grouping, cap, budget and rescore"`

---

### Task 10: API part 1: app factory, auth, segments and analyze

**Files:**
- Create: `scanner/api/__init__.py`, `scanner/api/app.py`, `scanner/api/auth.py`, `scanner/api/schemas.py`, `scanner/api/segments.py`, `tests/test_api_segments.py`
- Modify: `tests/fakes.py` (add `FakeLLM.queue`), `tests/conftest.py` (client fixtures)

**Interfaces:**
- Consumes: `Settings` (1), db/models (2), `analyze_segment` (8), `LLMError`/`RateLimited`/`GroqClient` (7), `build_sources` (5/6)
- Produces:
  - `create_app(settings: Settings | None = None, *, llm: LLMClient | None = None, session_factory: sessionmaker | None = None, http: httpx.Client | None = None, sources: Mapping[str, Source] | None = None) -> FastAPI`. Defaults: `get_settings()`, `GroqClient(settings.groq_api_key)`, a sessionmaker from `settings.database_url` (calls `init_db`), `httpx.Client(timeout=20, headers={"User-Agent": settings.user_agent})`, and `build_sources(settings)`. These are stored on `app.state`. It adds `CORSMiddleware(allow_origins=[settings.ui_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`. Every router is mounted at the prefix `/api`.
  - `GET /api/health` → `{"ok": true}`, no auth
  - `auth.py`: `require_auth(request) -> None` dependency. It accepts `Authorization: Bearer <api_token>` (only if `api_token` is non-empty) or a valid `ts_session` cookie signed with `itsdangerous.URLSafeTimedSerializer(session_secret)`, with a max age of 30 days. Otherwise it raises 401. Comparisons use `hmac.compare_digest`. `POST /api/login {"password"}` returns 204 and sets `ts_session` (httponly, `secure=settings.cookie_secure`, `samesite="lax"`, max_age 30d). A wrong password, or an empty `app_password`, returns 401. `POST /api/logout` returns 204 and deletes the cookie.
  - Dependencies `get_session(request)` (yields a session and commits on success) and `get_llm(request)`.
  - `api/schemas.py`:
    - `AnalyzeIn{name: str (min 1), examples: list[str] (min 1), note: str = ""}`
    - `ReanalyzeIn{examples: list[str] | None, note: str | None}`
    - `DraftOut{definition: SegmentDefinition}`
    - `SegmentIn{name, examples (min 1), note="", definition: SegmentDefinition, scoring: ScoringConfig = default, interval_minutes: int = Field(120, ge=60, le=1440), active=True}`
    - `SegmentPatch` (all fields optional, same constraints)
    - `RunOut{id, segment_id, started_at, finished_at, status, fetched, new_articles, new_stories, updated_stories, scored, errors}`
    - `SegmentOut{id, name, examples, note, definition, definition_version, scoring, interval_minutes, active, last_run_at, created_at, updated_at, last_run: RunOut | None}`
  - Routes (all `require_auth`):
    - `POST /api/segments/analyze` → `DraftOut`. It saves nothing and uses `settings.groq_model_analyze`.
    - `POST /api/segments/{id}/analyze` (`ReanalyzeIn`) → `DraftOut`. It uses the saved name, plus the body's examples/note or the saved ones, and `existing=` the saved definition. It doesn't modify the segment.
    - `GET /api/segments` → `list[SegmentOut]`
    - `POST /api/segments` → 201 `SegmentOut`
    - `GET /api/segments/{id}`
    - `PATCH /api/segments/{id}`. `definition_version += 1` only when the definition actually changed.
    - `DELETE /api/segments/{id}` → 204
    - A missing id gives 404. `RateLimited` maps to 503 `{"detail": "AI provider is rate limited, try again shortly"}` and other `LLMError`s to 502 `{"detail": str(exc)}`, via exception handlers in `app.py`.
  - Test fixture `client` (in `tests/conftest.py`): `TestClient(create_app(Settings(_env_file=None, database_url="sqlite://", api_token="tok", app_password="pw", session_secret="s", cookie_secure=False), llm=fake_llm, http=..., sources={}))`, with the header `Authorization: Bearer tok` set by default. A `fake_llm` fixture yields a `FakeLLM()` that tests load by appending to its private response list (add a `queue(*responses)` method to `FakeLLM`).

- [ ] **Step 1: Write failing tests in `tests/test_api_segments.py`.**

```python
DEF = {"summary": "Major world events", "sources": [{"type": "google_news", "mode": "feed"}]}
BODY = {"name": "Big news", "examples": ["Tesla Roadster flies"], "definition": DEF}

def test_health_open(anon_client): assert anon_client.get("/api/health").json() == {"ok": True}

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
    pre = lambda o: anon_client.options("/api/segments", headers={"Origin": o, "Access-Control-Request-Method": "GET"})
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
```

Fixtures to add to `conftest.py`: `make_client(**settings_overrides)` (a factory), `client` (bearer), `anon_client` (no default header), and `fake_llm`.

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_api_segments.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the `scanner/api/` modules listed** according to the Interfaces above.
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit.** `git add scanner/api tests && git commit -m "feat: API app, auth and segment routes"`

---

### Task 11: API part 2: stories, dismiss, rescore, runs, run-now

**Files:**
- Create: `scanner/api/stories.py`, `scanner/api/runs.py`, `tests/test_api_stories_runs.py`
- Modify: `scanner/api/schemas.py`, `scanner/api/app.py` (include the routers)

**Interfaces:**
- Consumes: `score_story` (4), `run_segment`, `rescore_recent`, `Budget` (9), Task 10's app state and dependencies
- Produces:
  - Schemas: `ArticleOut{id, source, outlet, title, url, published_at, engagement}` and `StoryOut{id, segment_id, headline, status, scores: {match, buzz, freshness, combined}, reason, scored_version, published_at, first_seen, last_seen, runs_seen, dismissed, outlets: list[str], articles: list[ArticleOut]}`
  - `GET /api/segments/{id}/stories?min_score: float|None&since_hours: int|None&include_dismissed: bool=False&limit: int=100 (le=500)` → `list[StoryOut]`. Scores are computed at request time with `datetime.now(UTC)` (the injectable `app.state.clock`, default `lambda: datetime.now(UTC)`). Results are sorted by combined desc, with pending (`None`) last ordered by `last_seen` desc. `min_score` excludes pending stories, and `since_hours` filters on `last_seen`.
  - `POST /api/stories/{id}/dismiss` and `/undismiss` → `StoryOut`
  - `POST /api/segments/{id}/rescore?hours=48` → `{"rescored": int}`, using `Budget(settings.run_token_budget)` and `groq_model_score`
  - `GET /api/runs?segment_id: int|None&limit: int=20 (le=100)` → `list[RunOut]`, newest first
  - `POST /api/segments/{id}/run` → 202. In `inline` mode it calls `run_segment` with app state and returns `{"mode": "inline", "run": RunOut}`. In `github` mode it POSTs `https://api.github.com/repos/{github_repo}/actions/workflows/scan.yml/dispatches` with JSON `{"ref": github_ref, "inputs": {"segment_id": str(id)}}`, headers `Authorization: Bearer {github_token}` and `Accept: application/vnd.github+json`, and returns `{"mode": "github"}`. A non-204 GitHub response gives 502.

- [ ] **Step 1: Write failing tests in `tests/test_api_stories_runs.py`.** Seed data directly through `app.state.session_factory` with `tests/factories.py`, and set `app.state.clock = lambda: NOW`.

```python
def test_stories_sorted_with_breakdown(client, seeded):
    rows = client.get(f"/api/segments/{seeded.segment_id}/stories").json()
    assert [r["headline"] for r in rows] == ["High", "Low", "Pending"]
    assert set(rows[0]["scores"]) == {"match", "buzz", "freshness", "combined"}
    assert rows[0]["articles"][0]["outlet"] == "Reuters" and rows[2]["scores"]["combined"] is None

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

def test_rescore_endpoint(client, seeded, fake_llm):
    fake_llm.queue({"results": []})
    assert client.post(f"/api/segments/{seeded.segment_id}/rescore").json() == {"rescored": 0}
```

`seeded` fixture: one segment with these stories:
- "High": match 9, 2 articles, one of them from Reuters
- "Low": match 2
- "Pending": status pending
- "Old": last_seen 72h ago, match 1

Plus two Runs, and a `NOW` clock. `make_client` (Task 10) must also accept the `sources=` and `http=` overrides alongside settings overrides. `BODY` is reused from the Task 10 tests and should be moved into `tests/factories.py`.

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_api_stories_runs.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `stories.py`, `runs.py`, the schemas, and router wiring.**
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest -v`. Expected: all PASS.
- [ ] **Step 5: Commit.** `git add scanner/api tests && git commit -m "feat: story, run and run-now API routes"`

---

### Task 12: CLI, seed segment, deploy config, README

**Files:**
- Create: `scanner/cli.py`, `scanner/__main__.py`, `scanner/seed.py`, `api/index.py`, `vercel.json`, `.github/workflows/scan.yml`, `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `seed_segments(session) -> int` creates a "Big news" segment if no segment with that name exists, and returns the number created (1 on the first call, 0 after). Examples: `["Tesla Roadster flies in public demo", "Political upheaval in France"]`, labelled in the README as placeholders to edit. Definition: summary `"Major, widely-covered world events that a lot of people are talking about right now"`, exclude `["celebrity gossip", "horoscope"]`. Sources: `google_news` feed (no sections = top stories), `google_news` feed `sections=["WORLD"]`, `reddit` feed `subreddits=["worldnews","news"]`, and `hackernews` feed.
  - `main(argv: list[str] | None = None) -> int` with argparse subcommands:
    - `init-db`
    - `seed` (runs init-db first)
    - `run-due`
    - `run SEGMENT_ID`
    - `serve [--port 8000]` (uvicorn `scanner.api.app:create_app --factory --reload`)

    `run-due`/`run` build a `GroqClient`, `httpx.Client(timeout=20, headers={"User-Agent": settings.user_agent})`, `Budget(settings.run_token_budget)`, `build_sources(settings)`, and `model=settings.groq_model_score`. They print one line per run (`segment=<name> status=<status> fetched=<n> new_stories=<n> scored=<n> errors=<n>`) and return exit code 0 unless every run failed (1). `run` with an unknown id prints an error and returns 2.
  - `api/index.py`: `from scanner.api.app import create_app; app = create_app()`
  - `vercel.json`: `{"rewrites": [{"source": "/api/(.*)", "destination": "/api/index"}]}`
  - `.github/workflows/scan.yml`, named `scan`:
    - triggers `schedule: cron "7 * * * *"` and `workflow_dispatch` with an optional input `segment_id`
    - `concurrency: {group: scan, cancel-in-progress: false}`
    - job steps: checkout, setup-python 3.12 with pip cache, `pip install .`, `python -m scanner init-db`, then `python -m scanner run "$SEGMENT_ID"` if the input is set, else `python -m scanner run-due`
    - env from secrets: `DATABASE_URL`, `GROQ_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, and vars `GROQ_MODEL_SCORE`, `RUN_TOKEN_BUDGET`

- [ ] **Step 1: Write failing tests in `tests/test_cli.py`.**

```python
def test_seed_is_idempotent(session):
    assert seed_segments(session) == 1
    assert seed_segments(session) == 0
    seg = session.scalars(select(Segment)).one()
    assert {s.type for s in seg.get_definition().sources} == {"google_news", "reddit", "hackernews"}
    assert all(s.mode == "feed" for s in seg.get_definition().sources)

def test_cli_init_and_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    get_settings.cache_clear(); get_sessionmaker.cache_clear()
    assert main(["seed"]) == 0
    assert main(["run", "999"]) == 2

def test_vercel_entry_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/v.db")
    get_settings.cache_clear(); get_sessionmaker.cache_clear()
    import importlib.util
    spec = importlib.util.spec_from_file_location("vercel_index", "api/index.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.app.title
```

- [ ] **Step 2: Run them to make sure they fail.** Run: `.venv/bin/pytest tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `seed.py`, `cli.py`, `__main__.py`, and `api/index.py`, and write `vercel.json` and `scan.yml`.**
- [ ] **Step 4: Run them to make sure they pass.** Run: `.venv/bin/pytest -v`. Expected: all PASS.
- [ ] **Step 5: Run a real local smoke test with network access** (manual and optional; it needs a real `GROQ_API_KEY` in `.env`): `.venv/bin/python -m scanner seed && .venv/bin/python -m scanner run 1`. Expected: one summary line with `fetched>0`. Report the actual output, including any Reddit 403s.
- [ ] **Step 6: Write `README.md`.** Cover:
  - what it is (2 lines)
  - local setup (venv, `.env` from `.env.example`, `seed`, `serve`, `run 1`)
  - how a segment works (examples → analyze → edit → save)
  - deploy: create a Neon DB and copy its URL; Vercel project env vars (`DATABASE_URL`, `GROQ_API_KEY`, `API_TOKEN`, `APP_PASSWORD`, `SESSION_SECRET`, `UI_ORIGIN`, `RUN_NOW_MODE=github`, `GITHUB_TOKEN` (a fine-grained token with Actions: write), `GITHUB_REPO`); GitHub repo secrets and vars for the workflow
  - the API endpoint list
  - a note that Reddit may need free app credentials from cloud IPs
- [ ] **Step 7: Commit.** `git add -A scanner api vercel.json .github README.md tests && git commit -m "feat: CLI, seed segment, Vercel and GitHub Actions deploy"`
