#!/usr/bin/env python3
"""Run one heavy queue action, preferring retries and requested exports."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_report_export_jobs import (
    claim_export_job,
    execute_export_job,
    fail_export_job,
)
from scripts.run_source_refresh_export_task import execute_one as execute_excel_retry
from scripts.run_source_refresh_pipeline_task import run_one as run_pipeline_task
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportExportJob, SourceRefreshTask
from wb_unit_economics.web.settings import WebSettings


def active_heavy_worker_count(db) -> int:
    task_count = int(
        db.scalar(
            select(func.count())
            .select_from(SourceRefreshTask)
            .where(
                SourceRefreshTask.status == "running",
                SourceRefreshTask.task_type.in_(
                    {
                        "materialize_facts",
                        "build_report",
                        "export_excel",
                        "export_optional",
                    }
                ),
            )
        )
        or 0
    )
    job_count = int(
        db.scalar(
            select(func.count())
            .select_from(ReportExportJob)
            .where(ReportExportJob.status == "running")
        )
        or 0
    )
    return task_count + job_count


def run_one(db, settings: WebSettings) -> str:
    if not settings.source_refresh_task_queue_enabled:
        return "disabled"
    heavy_limit = max(1, min(int(settings.source_refresh_heavy_concurrency), 2))
    if active_heavy_worker_count(db) >= heavy_limit:
        return "source_active"
    if execute_excel_retry(db, settings):
        return "excel_retry"
    job = claim_export_job(db)
    if job is not None:
        try:
            execute_export_job(db, job, settings)
        except Exception as exc:
            fail_export_job(db, job, exc)
        return "report_export"
    return run_pipeline_task(db, settings=settings, worker_class="heavy")


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
        action = run_one(db, settings)
    print(f"action={action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
