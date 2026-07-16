# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import SourceRefreshService

WORKER_ACTIVE_STATUSES = {"running", "source_loaded", "rebuilding"}
DEFAULT_WORKER_NAME = "systemd-source-refresh-worker"


class WorkerInterrupted(RuntimeError):
    pass


def claim_next_run(
    db: Session,
    *,
    worker_id: str,
) -> SourceRefreshRun | None:
    statement = (
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.status == "queued",
            SourceRefreshRun.finished_at.is_(None),
            SourceRefreshRun.dry_run.is_(False),
        )
        .order_by(SourceRefreshRun.created_at.asc())
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    refresh_run = db.scalar(statement)
    if refresh_run is None:
        return None
    now = security.utcnow()
    repository.update_source_refresh_run(
        db,
        refresh_run,
        worker_id=worker_id,
        heartbeat_at=now,
        failure_code="",
    )
    db.commit()
    return refresh_run


def claim_run_by_id(
    db: Session,
    *,
    refresh_run_id: str,
    worker_id: str,
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(
        SourceRefreshRun.id == refresh_run_id,
        SourceRefreshRun.status == "queued",
        SourceRefreshRun.finished_at.is_(None),
        SourceRefreshRun.dry_run.is_(False),
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    refresh_run = db.scalar(statement)
    if refresh_run is None:
        return None
    repository.update_source_refresh_run(
        db,
        refresh_run,
        worker_id=worker_id,
        heartbeat_at=security.utcnow(),
        failure_code="",
    )
    db.commit()
    return refresh_run


def recover_stale_worker_runs(
    db: Session,
    *,
    worker_name: str,
    stale_after_seconds: int,
) -> int:
    cutoff = security.utcnow() - timedelta(seconds=max(60, stale_after_seconds))
    stale_runs = list(
        db.scalars(
            select(SourceRefreshRun).where(
                SourceRefreshRun.worker_id.like(f"{worker_name}:%"),
                SourceRefreshRun.status.in_(WORKER_ACTIVE_STATUSES),
                SourceRefreshRun.finished_at.is_(None),
                SourceRefreshRun.heartbeat_at.is_not(None),
                SourceRefreshRun.heartbeat_at < cutoff,
            )
        )
    )
    for refresh_run in stale_runs:
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="failed",
            failure_code="worker_heartbeat_stale",
            error_message="Source refresh worker heartbeat expired.",
            finished_at=security.utcnow(),
        )
        if refresh_run.mode == "report-generation":
            refresh_run.generation_stage = "failed"
        repository.audit(
            db,
            action="source_refresh_worker_stale",
            user=None,
            tenant_id=refresh_run.tenant_id,
            entity_type="source_refresh_run",
            entity_id=refresh_run.id,
            payload={"workerId": refresh_run.worker_id},
        )
    if stale_runs:
        db.commit()
    return len(stale_runs)


def mark_run_failed(
    session_factory: sessionmaker[Session],
    *,
    refresh_run_id: str,
    failure_code: str,
    error_type: str,
) -> None:
    with session_factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        if refresh_run is None or refresh_run.finished_at is not None:
            return
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="failed",
            failure_code=failure_code,
            error_message=f"{error_type}: source refresh worker stopped.",
            finished_at=security.utcnow(),
        )
        if refresh_run.mode == "report-generation":
            refresh_run.generation_stage = "failed"
        repository.audit(
            db,
            action="source_refresh_worker_failed",
            user=None,
            tenant_id=refresh_run.tenant_id,
            entity_type="source_refresh_run",
            entity_id=refresh_run.id,
            payload={"failureCode": failure_code, "errorType": error_type},
        )
        db.commit()


def _heartbeat_loop(
    session_factory: sessionmaker[Session],
    *,
    refresh_run_id: str,
    interval_seconds: int,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(max(5, interval_seconds)):
        try:
            with session_factory() as db:
                refresh_run = db.get(SourceRefreshRun, refresh_run_id)
                if refresh_run is None or refresh_run.finished_at is not None:
                    return
                repository.update_source_refresh_run(
                    db,
                    refresh_run,
                    heartbeat_at=security.utcnow(),
                )
                db.commit()
        except Exception:
            continue


def process_run(
    session_factory: sessionmaker[Session],
    service: SourceRefreshService,
    refresh_run_id: str,
    *,
    heartbeat_seconds: int,
) -> None:
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        kwargs={
            "session_factory": session_factory,
            "refresh_run_id": refresh_run_id,
            "interval_seconds": heartbeat_seconds,
            "stop_event": stop_event,
        },
        daemon=True,
        name="source-refresh-heartbeat",
    )
    heartbeat.start()
    try:
        with session_factory() as db:
            service.run_existing(db, refresh_run_id)
            db.commit()
    except WorkerInterrupted:
        mark_run_failed(
            session_factory,
            refresh_run_id=refresh_run_id,
            failure_code="worker_interrupted",
            error_type="WorkerInterrupted",
        )
        raise
    except Exception as exc:
        mark_run_failed(
            session_factory,
            refresh_run_id=refresh_run_id,
            failure_code="worker_failed",
            error_type=exc.__class__.__name__,
        )
    finally:
        stop_event.set()
        heartbeat.join(timeout=2)


def worker_loop(args: argparse.Namespace) -> int:
    settings = _settings(args.database_url)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    service = SourceRefreshService(settings)
    worker_id = args.worker_id or (
        f"{args.worker_name}:{socket.gethostname()}:{os.getpid()}:"
        f"{uuid.uuid4().hex[:8]}"
    )

    def interrupted(_signum, _frame):  # type: ignore[no-untyped-def]
        raise WorkerInterrupted("source refresh worker interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.run_id:
        with session_factory() as db:
            refresh_run = claim_run_by_id(
                db,
                refresh_run_id=args.run_id,
                worker_id=worker_id,
            )
        if refresh_run is None:
            return 0
        try:
            process_run(
                session_factory,
                service,
                refresh_run.id,
                heartbeat_seconds=args.heartbeat_seconds,
            )
        except WorkerInterrupted:
            return 143
        return 0
    while True:
        with session_factory() as db:
            recover_stale_worker_runs(
                db,
                worker_name=args.worker_name,
                stale_after_seconds=args.stale_after_seconds,
            )
            refresh_run = claim_next_run(db, worker_id=worker_id)
        if refresh_run is None:
            if args.once:
                return 0
            time.sleep(max(1, args.poll_seconds))
            continue
        try:
            process_run(
                session_factory,
                service,
                refresh_run.id,
                heartbeat_seconds=args.heartbeat_seconds,
            )
        except WorkerInterrupted:
            return 143
        if args.once:
            return 0


def _settings(database_url: str) -> WebSettings:
    resolved = database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    if resolved:
        return WebSettings(_env_file=None, database_url=resolved)
    return WebSettings(_env_file=None)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run queued source refresh jobs.")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--worker-name", default=DEFAULT_WORKER_NAME)
    parser.add_argument("--worker-id", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--heartbeat-seconds", type=int, default=30)
    parser.add_argument("--stale-after-seconds", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(worker_loop(_parse_args()))
