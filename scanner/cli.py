"""Entry point: `python -m scanner <command>`. GitHub Actions calls `run-due` hourly."""
import argparse
import logging
import sys
from datetime import UTC, datetime

import httpx

from scanner.config import get_settings
from scanner.db import get_sessionmaker
from scanner.llm.groq import GroqClient
from scanner.models import Run, Segment
from scanner.runner import Budget, run_due, run_segment
from scanner.seed import seed_segments
from scanner.sources import build_sources


def _print_runs(runs: list[Run], names: dict[int, str]) -> int:
    for run in runs:
        print(f"segment={names.get(run.segment_id, run.segment_id)} status={run.status} fetched={run.fetched} "
              f"new_stories={run.new_stories} scored={run.scored} errors={len(run.errors)}")
        for err in run.errors:
            print(f"  error source={err['source']}: {err['message']}")
    return 1 if runs and all(r.status == "failed" for r in runs) else 0


def _scan(args) -> int:
    settings = get_settings()
    factory = get_sessionmaker()
    common = dict(
        llm=GroqClient(settings.groq_api_key), model=settings.groq_model_score,
        http=httpx.Client(timeout=20, headers={"User-Agent": settings.user_agent}),
        now=datetime.now(UTC), budget=Budget(settings.run_token_budget), sources=build_sources(settings),
    )
    with factory() as session:
        names = {s.id: s.name for s in session.query(Segment)}

    if args.command == "run-due":
        return _print_runs(run_due(factory, **common), names)

    with factory() as session:
        segment = session.get(Segment, args.segment_id)
        if segment is None:
            print(f"no segment with id {args.segment_id}", file=sys.stderr)
            return 2
        run = run_segment(session, segment, **common)
        session.commit()
    return _print_runs([run], names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scanner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create tables")
    sub.add_parser("seed", help="create tables and the starter 'Big news' segment")
    sub.add_parser("run-due", help="scan every segment whose interval has elapsed")
    run_p = sub.add_parser("run", help="scan one segment now")
    run_p.add_argument("segment_id", type=int)
    serve_p = sub.add_parser("serve", help="run the API locally with reload")
    serve_p.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "init-db":
        get_sessionmaker()  # creates tables
        return 0
    if args.command == "seed":
        with get_sessionmaker()() as session:
            created = seed_segments(session)
        print(f"seeded {created} segment(s)")
        return 0
    if args.command == "serve":
        import uvicorn
        uvicorn.run("scanner.api.app:create_app", factory=True, reload=True, port=args.port)
        return 0
    return _scan(args)
