# topic-scanner

A personal trend tracker. You describe a **segment** with a few example stories, an AI works out what they have in common, and every hour or two the scanner pulls fresh news, groups the coverage into stories, and scores each story by **match**, **buzz** and **freshness**.

This repo is the backend: a Python package (`scanner`), a FastAPI app under `/api`, and a GitHub Actions cron that runs the scans.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env               # add GROQ_API_KEY, API_TOKEN, APP_PASSWORD; set COOKIE_SECURE=false locally
.venv/bin/python -m scanner seed   # creates tables + a starter "Big news" segment
.venv/bin/python -m scanner run 1  # scan segment 1 right now
.venv/bin/python -m scanner serve  # API on http://localhost:8000/api (docs at /docs)
.venv/bin/pytest                   # tests (no network needed)
```

Other commands: `init-db` (create tables) and `run-due` (scan every segment whose interval has elapsed; this is what cron calls).

The starter segment's examples ("Tesla Roadster flies in public demo", "Political upheaval in France") are placeholders. Edit them.

## How a segment works

1. **Examples → draft.** `POST /api/segments/analyze` with a name, examples and an optional note. The AI returns a draft definition: a summary, include/exclude criteria, and which sources to use. Each source runs in either **search** mode (queries) or **feed** mode (top/hot lists, for "kind of story" segments like big news). Nothing is saved at this step.
2. **Edit and save.** Tweak the draft, then `POST /api/segments`. Each segment has its own sources, interval (60–1440 min, default 120), scoring weights, freshness window, buzz signals, and a cap on new stories scored per run (default 40).
3. **Scans.** Each run fetches the sources, drops exclude-term matches, and merges repeat articles. It then groups coverage of the same event into one **story**: cheap headline matching first, then the AI as part of the same batched scoring call. New stories get a match score from the AI. Buzz (number of outlets, repeat sightings, upvotes/points) and freshness are computed without AI.
4. **Editing the definition** bumps its version. Old scores stay as they were, and `POST /api/segments/{id}/rescore` re-rates the last 48h if you want.

Groq usage is limited by the per-segment cap and by `RUN_TOKEN_BUDGET`, which is shared across all segments in one `run-due`. Stories over the limit wait as `pending` and are scored first on the next run.

## API

Every route except `/api/health` needs either the session cookie from `POST /api/login` (`{"password": ...}`) or `Authorization: Bearer <API_TOKEN>`.

| Method | Path | What |
|---|---|---|
| GET | `/api/health` | liveness |
| POST | `/api/login`, `/api/logout` | cookie session |
| POST | `/api/segments/analyze` | draft a definition from name/examples/note |
| POST | `/api/segments/{id}/analyze` | re-draft for an existing segment (doesn't save) |
| GET/POST | `/api/segments` | list / create |
| GET/PATCH/DELETE | `/api/segments/{id}` | read / update (incl. `active`) / delete |
| GET | `/api/segments/{id}/stories` | ranked stories; `min_score`, `since_hours`, `include_dismissed`, `limit` |
| POST | `/api/stories/{id}/dismiss`, `/undismiss` | hide / unhide a story |
| POST | `/api/segments/{id}/rescore?hours=48` | re-rate recent stories against the current definition |
| POST | `/api/segments/{id}/run` | scan now (inline locally, GitHub dispatch in prod) |
| GET | `/api/runs?segment_id=` | recent runs with status and per-source errors |

## Deploy

1. **Database:** create a free Postgres on [Neon](https://neon.tech) (or Supabase) and copy its connection string. `postgres://…` URLs are accepted as they are.
2. **Groq:** create an API key at console.groq.com. The defaults are `openai/gpt-oss-120b` (analysis) and `openai/gpt-oss-20b` (scoring). Groq retires models regularly, so check console.groq.com/docs/deprecations and override with `GROQ_MODEL_ANALYZE` / `GROQ_MODEL_SCORE` if needed.
3. **GitHub Actions** (does the scanning; `.github/workflows/scan.yml` runs hourly at :07):
   - Secrets: `DATABASE_URL`, `GROQ_API_KEY`, and optionally `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`
   - Variables (optional): `GROQ_MODEL_SCORE`, `RUN_TOKEN_BUDGET`
4. **Vercel** (serves the API; scraping never runs inside a Vercel request in prod). Import the repo and set these env vars:
   - `DATABASE_URL`, `GROQ_API_KEY`, `API_TOKEN`, `APP_PASSWORD`, `SESSION_SECRET` (long random string), `UI_ORIGIN`
   - `RUN_NOW_MODE=github`, `GITHUB_REPO=owner/topic-scanner`, `GITHUB_TOKEN` (fine-grained token with **Actions: write** on this repo), `GITHUB_REF=main`

   Deploy the UI in the same Vercel project later so the login cookie stays same-origin.

### Reddit

Reddit blocks unauthenticated JSON requests from many networks, including GitHub's runners and, in testing, home connections (`403 Blocked`). When that happens, the run records the error and carries on with the other sources. To fix it, create a free "script" app at reddit.com/prefs/apps and set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`. The scanner then uses app-only OAuth.
