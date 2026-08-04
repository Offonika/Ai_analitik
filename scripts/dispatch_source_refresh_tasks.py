#!/usr/bin/env python3
"""Execute one queued collector task inside the bounded collector service."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_source_refresh_pipeline_task import run_one
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.settings import WebSettings


def dispatch_one(db, settings: WebSettings) -> str:
    return run_one(db, settings=settings, worker_class="collector")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    args = parser.parse_args()
    settings = (
        WebSettings(_env_file=None, database_url=args.database_url)
        if args.database_url
        else WebSettings(_env_file=None)
    )
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        action = dispatch_one(db, settings)
    print(f"action={action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
