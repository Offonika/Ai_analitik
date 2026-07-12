# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    settings = (
        WebSettings(_env_file=None, database_url=database_url)
        if database_url
        else WebSettings(_env_file=None)
    )
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, args.run_id)
        if refresh_run is None:
            print("Source refresh run not found.", file=sys.stderr)
            return 2
        if refresh_run.finished_at is not None:
            print(f"Run is already finished with status={refresh_run.status}.")
            return 0
        print(f"Run: {refresh_run.id}")
        print(f"Status: {refresh_run.status}")
        print(f"Mode: {refresh_run.mode}")
        print(f"Collections: {len(refresh_run.collections)}")
        if not args.apply:
            print("Dry-run: no database changes were made.")
            return 0
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="failed",
            failure_code=args.failure_code,
            error_message="Interrupted legacy in-process source refresh.",
            finished_at=security.utcnow(),
        )
        repository.audit(
            db,
            action="source_refresh_orphan_repaired",
            user=None,
            tenant_id=refresh_run.tenant_id,
            entity_type="source_refresh_run",
            entity_id=refresh_run.id,
            payload={
                "failureCode": args.failure_code,
                "collectionCount": len(refresh_run.collections),
            },
        )
        db.commit()
        print("Run marked failed; snapshots and collections were preserved.")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely finish an orphaned source refresh run."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--database-url", default="")
    parser.add_argument(
        "--failure-code",
        default="legacy_web_worker_interrupted",
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
