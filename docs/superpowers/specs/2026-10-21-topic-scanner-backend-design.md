# Topic Scanner — Backend Design

Date: 2026-10-21
Scope: backend only (data model, AI tasks, scrapers, scheduler, HTTP API). The React + TypeScript UI is designed separately afterwards and consumes the API described here.

## Intent

Manav wants a personal trend tracker. They define **segments**: things they want to keep an eye on, such as "big news events" (e.g. the Tesla Roadster flying, the recent France news). They don't write search rules for them. They give a handful of **examples** and an optional plain-language note. An AI works out what the examples have in common and drafts a definition of what to track and where to look. Manav reviews and tweaks that definition, then saves it.

Every 1–2 hours each active segment scrapes its sources, the AI rates what it found, and the results land in a per-segment table that Manav reads like a report.

The point is low effort: examples in, a ranked feed of matching stories out, with no hand-written queries. It also has to be cheap to run, using free tiers wherever possible.

## Goals

1. **Segment creation by example.** Name + examples + optional note → AI-drafted definition → user edits → saved segment. The definition stays editable later.
2. **Per-segment configuration.** Every behaviour that could differ between segments is a setting on the segment, with sensible defaults: sources (and their queries), run interval, scoring weights, freshness window, buzz signals.
3. **Scheduled scraping.** Each active segment runs on its own interval (default 2h, allowed 1h–24h).
4. **Rating.** Each story (one real-world event, grouped across sources) gets a combined 1–10 score built from three stored sub-scores (match, buzz, freshness), plus a one-line AI reason.
5. **Deduplication.** The same story seen again, or seen from another source, updates one row instead of adding new ones.
6. **HTTP API** that exposes everything the UI will need.
7. **Runs anywhere locally** with one command against SQLite. Production uses hosted Postgres.

## Non-goals (for this phase)

- The UI (comes next, designed by Manav).
- Multiple AI providers / fallback switcher. **Groq is the only provider for now**, but all AI calls go through one small interface so a switcher can be added later without touching callers.
- Non-news sources (car sale sites, etc.). The source system must make these easy to add later, but none ship now.
- Notifications (email/push), multi-user accounts, sharing.

## Anti-goals (failure even if it "works")

- **Burning AI quota.** Re-scoring stories already scored, or one LLM call per story when batching is possible. Groq's free tier has rate and token limits, and the design has to stay inside them.
- **A table full of duplicates** of the same story.
- **Silent failure.** A source erroring or Groq rate-limiting must be recorded on the run and visible through the API, and must not crash the other segments.
- **An open API on the internet** that anyone can use to edit segments or trigger runs.

## Architecture & hosting (decided)

| Part | Choice | Notes |
|---|---|---|
| Language | Python | |
| API | FastAPI, deployed on Vercel (Python runtime, free plan) | |
| Scheduler | GitHub Actions cron, free | Vercel Hobby cron is limited to daily, so it can't be used here |
| Database | Postgres on Neon or Supabase free tier in prod; SQLite file locally | Same code path via SQLAlchemy and a `DATABASE_URL` env var |
| AI | Groq | Behind an `LLMClient` interface |
| UI | React + TypeScript | Later, separate |

**Scheduling model.** GitHub Actions runs **hourly** and calls one CLI entrypoint (e.g. `python -m scanner run-due`). That command runs every active segment whose `last_run_at + interval` has passed. This gives per-segment intervals from a single cron. The same command must also work locally, and there must be a way to run one segment on demand (CLI and API).

## Core concepts

### Segment
- `name`
- `examples`: list of free-text strings (headlines, URLs, short descriptions)
- `note`: optional free text from the user ("only UK", "skip celebrity gossip")
- `definition` is AI-drafted and user-editable. At minimum it holds:
  - `summary`: a short plain-language statement of what's being tracked (the "pattern")
  - `include` / `exclude`: lists of criteria
  - per-source queries (see Sources)
- `sources`: which sources are enabled for this segment, plus each one's config/queries
- `interval_minutes`: default 120
- `scoring`: weights (default match 0.5 / buzz 0.3 / freshness 0.2), freshness window (default: full marks under 2h, decaying to ~0 by 48h), which buzz signals count
- `active` flag, `last_run_at`, timestamps

### Segment creation flow
1. The client sends name + examples + note to an **analyze** endpoint. It returns a *draft* definition, including suggested source queries, and doesn't save anything.
2. The user edits the draft in the UI.
3. The client saves the segment with the (possibly edited) definition.
4. Re-analyzing an existing segment, e.g. after adding examples, returns a new draft without overwriting the saved one until the user saves it.

### Run
One execution of one segment: start/end time, status (success / partial / failed), counts (fetched, new, updated, scored), and per-source errors. Runs are queryable so the UI can show "last updated" and problems.

### Story and Article *(Claude's call)*
A table row is a **story**: one real-world event, like "Tesla Roadster flies". It isn't one article. Under each story sit the **articles** that cover it, from any source.

- **Article:** title, canonical URL, source, published time, snippet, raw engagement metrics (upvotes, comments, points), first-seen/last-seen.
- **Story:** a headline (the best article title or an AI-written one), its articles, first-seen/last-seen, how many runs have seen it, the three sub-scores, the combined score, the AI reason, the definition version it was scored against, and a dismissed flag. Users can dismiss stories to hide them from the table. Pinning is optional.

Grouping into stories is described under Deduplication.

## Sources

A source is a plug-in. Adding one means writing one new module that implements a common interface (given the segment's config for that source, return a list of raw articles with whatever engagement metrics it has). Sources ship for news only.

Each source supports two modes, because some segments are about a **topic** ("EV battery news") and others about a **kind of story** ("big news events"), which a search query can't express *(Claude's call)*:

- **Search mode:** query-based.
- **Feed mode:** pulls what's currently top or hot, with no query.

| Source | Search mode | Feed mode | Buzz signals |
|---|---|---|---|
| **Google News RSS** | search feed | top stories / topic sections (world, tech, business…) | appearing in multiple outlets |
| **Reddit** | search | hot/top of chosen subreddits (e.g. r/worldnews, r/news) | upvotes, comments |
| **Hacker News** | Algolia search API | front page / top stories | points, comments |

All three are free and need no paid keys. When the AI drafts a definition, it chooses the mode for each enabled source and suggests queries, subreddits, or feed sections. The user can edit all of these. For the "big news" seed segment, the expected draft is mostly feed mode.

## Scoring

Scoring happens per **story**.

- **Match (0–10):** the AI rates the story against the segment's definition and writes a one-line reason. "Match" means whatever the definition says. For a topic segment that's topical relevance. For "big news" it's significance, i.e. how major and widely relevant the event is. Stories are **batched** per LLM call. A story is scored once. New articles joining it don't trigger a new AI call.
- **Buzz (0–10):** computed without AI from the number of distinct outlets/sources covering the story, how many runs have seen it, and the articles' engagement metrics, normalised within the segment.
- **Freshness (0–10):** computed without AI from the earliest article's published time, using the segment's freshness window.
- **Combined:** the weighted sum, using the segment's weights, shown as 1–10. Freshness changes over time, so combined scores must reflect the current time when stories are listed (recompute on read or on each run; builder's call).

**Definition edits** *(Claude's call)*: each saved definition gets a version number, and each score records which version it used. Editing a definition doesn't automatically rescore anything. New stories are scored against the new version. A separate, explicit "rescore" API action re-rates recent stories, limited to the last 48h by default, so one edit can't burn through the daily quota.

**Quota budget** *(Claude's call)*: before the AI step, a cheap non-AI pre-filter drops articles that clearly hit the definition's `exclude` keywords. Each run also caps the number of new stories it sends for scoring (setting on the segment, default 40). Stories over the cap wait as "pending" for the next run, highest-buzz first. The `run-due` loop shares one token budget across all segments in a single invocation.

## Deduplication and story grouping *(Claude's call)*

Grouping happens in two steps, both within a segment:

1. **Same article:** articles merge when their canonical URL matches (strip tracking params, normalise host/scheme).
2. **Same event:** cheap first, AI second. New articles with near-identical titles to an existing story join it directly. The rest go to the AI in the same batched call as scoring. The prompt includes the headlines of the segment's open stories from roughly the last 48h, and the AI either assigns each new article to one of them or declares a new story, then scores any new stories. There's no separate clustering call and no embeddings, which Groq doesn't offer.

Articles joining an existing story update its buzz and last-seen time.

## AI layer

- A single `LLMClient` interface covering what we need, essentially "send prompt, get validated JSON back". Groq is the one implementation for now.
- Model names come from config/env, not code. A larger model can be used for segment analysis (rare, quality matters) and a small, fast one for batch scoring (frequent, cost matters).
- Responses are validated against a schema. Malformed output is retried once, then recorded as an error.
- Rate limits (HTTP 429) get backoff. If the limit persists, the run stops scoring, saves unscored stories as "pending", and finishes as partial. The next run scores the pending stories first.

## HTTP API (what the UI will need)

- Segments: list, get, create, update, delete, activate/deactivate.
- Analyze: draft a definition from name/examples/note, for both new and existing segments.
- Stories for a segment: sorted by combined score by default, with filters for minimum score, time range, and hide dismissed. Each story includes its sub-score breakdown and its articles.
- Story actions: dismiss / undismiss.
- Rescore recent stories for a segment (see Scoring).
- Runs: list recent runs (per segment and overall) with status and errors.
- Trigger a run of one segment now.
- Health check.

**Auth** *(Claude's call)*: one user, no accounts. The UI will probably be a public site on Vercel, so no secret can live in the browser bundle. Instead:

- `POST /login` takes a password (env `APP_PASSWORD`) and sets a signed, httpOnly, secure session cookie.
- All other endpoints require either that cookie or an `Authorization: Bearer <API_TOKEN>` header, for scripts and the CLI.
- CORS allows only the configured UI origin, with credentials.

## Configuration / secrets

Env vars: `DATABASE_URL`, `GROQ_API_KEY`, model names, `API_TOKEN`, `APP_PASSWORD`, `SESSION_SECRET`, `UI_ORIGIN`, and optional Reddit credentials if they turn out to be needed. A `.env.example` documents them. GitHub Actions and Vercel each get the secrets they need.

## Quality bar

- Tests (pytest) for dedup, scoring math, the run orchestration, and each source's parsing, using saved sample responses and no live network. The LLM is replaced by a fake in tests.
- A README covering local setup, running one segment by hand, and deploying (Neon, Vercel, GitHub Actions).
- A seed/example segment for "big news" so a fresh local install has something to run.

## Left to the builder

- Project layout, ORM details, migration tool, and HTTP client library.
- Exact prompts and JSON schemas for analysis and scoring.
- Exact buzz normalisation formula and the near-duplicate title threshold.
- Expected scale: assume a handful of active segments (≈3–10) with tens to low hundreds of articles per run. The per-run cap and shared budget handle anything beyond that.
- Story retention (e.g. prune dismissed or old low-score stories after N days).
- Which specific Groq models to default to. Check what's currently available and cheap.

## Known risks to check early

- **Reddit may block unauthenticated requests from cloud IPs** such as GitHub Actions runners. If it does, support optional Reddit app credentials (free) and fall back gracefully when they're absent.
- **Vercel Python function timeouts.** API requests stay short, and scraping only happens in GitHub Actions, not on Vercel. A "run now" call from the API must not do the scrape inside the request if that would exceed the timeout. It can dispatch the GitHub Actions workflow instead, or run only when it fits (builder's call).
- **GitHub Actions cron is best-effort** and can run several minutes late. That's acceptable.
