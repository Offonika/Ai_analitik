#!/usr/bin/env python3
"""Claim and execute one resumable source-refresh pipeline task."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import socket
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_source_refresh_worker import (
    _start_heartbeat_process,
    _stop_heartbeat_process,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun, SourceRefreshTask
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import SourceRefreshService

COLLECTOR_TASK_TYPES = {"collect_sources"}
HEAVY_TASK_TYPES = {"materialize_facts", "build_report"}


def claim_pipeline_task(
    db,
    *,
    settings: WebSettings,
    worker_id: str,
    worker_class: str,
) -> SourceRefreshTask | None:
    running_collectors = int(
        db.scalar(
            select(func.count())
            .select_from(SourceRefreshTask)
            .where(
                SourceRefreshTask.status == "running",
                SourceRefreshTask.task_type == "collect_sources",
            )
        )
        or 0
    )
    running_heavy = int(
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
    if worker_class == "collector":
        collector_limit = max(
            1,
            min(int(settings.source_refresh_collector_concurrency), 2),
        )
        if running_collectors >= collector_limit or running_heavy >= 2:
            return None
    else:
        heavy_limit = max(1, min(int(settings.source_refresh_heavy_concurrency), 2))
        if running_heavy >= heavy_limit or (running_collectors and running_heavy):
            return None
    allowed = (
        COLLECTOR_TASK_TYPES if worker_class == "collector" else HEAVY_TASK_TYPES
    )
    task = repository.claim_next_source_refresh_task(
        db,
        worker_id=worker_id,
        allowed_task_types=allowed,
        idempotency_prefix="pipeline-v1:",
    )
    db.commit()
    return task


def execute_pipeline_task(
    db,
    *,
    settings: WebSettings,
    task: SourceRefreshTask,
    worker_id: str,
) -> str:
    service = SourceRefreshService(settings)
    heartbeat_process = _start_heartbeat_process(
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
        service,
        task.refresh_run_id,
        heartbeat_seconds=30,
    )
    try:
        if task.task_type == "collect_sources":
            db.info["source_refresh_split_pipeline"] = True
            try:
                service.run_existing(
                    db,
                    task.refresh_run_id,
                    worker_id=worker_id,
                    stop_after_sources=True,
                )
                refresh_run = db.get(SourceRefreshRun, task.refresh_run_id)
                if refresh_run is not None and refresh_run.finished_at is None:
                    repository.update_source_refresh_run(
                        db,
                        refresh_run,
                        worker_id="",
                    )
                    db.commit()
            finally:
                db.info.pop("source_refresh_split_pipeline", None)
            return task.task_type
        if task.task_type == "materialize_facts":
            service.run_split_materialize_task(db, task, worker_id=worker_id)
            return task.task_type
        if task.task_type == "build_report":
            service.run_split_build_report_task(db, task, worker_id=worker_id)
            return task.task_type
        raise ValueError("unsupported pipeline task")
    finally:
        _stop_heartbeat_process(heartbeat_process)


def run_one(db, *, settings: WebSettings, worker_class: str) -> str:
    if not settings.source_refresh_task_queue_enabled:
        return "disabled"
    worker_id = (
        f"{worker_class}:{socket.gethostname()}:{os.getpid()}:"
        f"{uuid.uuid4().hex[:8]}"
    )
    task = claim_pipeline_task(
        db,
        settings=settings,
        worker_id=worker_id,
        worker_class=worker_class,
    )
    if task is None:
        return "idle"
    return execute_pipeline_task(
        db,
        settings=settings,
        task=task,
        worker_id=worker_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("SHUMEYKO_DATABASE_URL", ""),
    )
    parser.add_argument(
        "--worker-class",
        choices=("collector", "heavy"),
        required=True,
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
        action = run_one(
            db,
            settings=settings,
            worker_class=args.worker_class,
        )
    print(f"action={action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
