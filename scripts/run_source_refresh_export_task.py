#!/usr/bin/env python3
"""Retry only a failed source-refresh Excel stage from persisted marts."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.export_report_artifacts import export_report_artifacts
from scripts.run_source_refresh_worker import (
    _start_heartbeat_process,
    _stop_heartbeat_process,
)
from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun, SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import SourceRefreshService


def execute_one(db, settings: WebSettings) -> bool:
    task = repository.claim_next_source_refresh_task(
        db,
        worker_id=f"excel-retry:{os.getpid()}",
        allowed_task_types={"export_excel"},
        idempotency_prefix="pipeline-v1:",
    )
    if task is None:
        return False
    db.commit()
    refresh_run = db.get(SourceRefreshRun, task.refresh_run_id)
    report = db.get(ReportRun, task.report_run_id) if task.report_run_id else None
    if refresh_run is None or report is None:
        repository.fail_source_refresh_task(
            db,
            task,
            safe_error_code="export_report_not_found",
            transient=False,
        )
        db.commit()
        return True
    output_dir = (
        settings.export_root_path / "source_refresh" / refresh_run.id
    ).resolve()
    allowed = settings.export_root_path.resolve()
    if output_dir != allowed and allowed not in output_dir.parents:
        repository.fail_source_refresh_task(
            db,
            task,
            safe_error_code="export_path_outside_allowed_root",
            transient=False,
        )
        db.commit()
        return True
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / "shumeyko_wb_excel_mvp.xlsx"
    repository.update_source_refresh_run(
        db,
        refresh_run,
        worker_id=task.worker_id,
        heartbeat_at=security.utcnow(),
    )
    db.commit()
    heartbeat_process = _start_heartbeat_process(
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
        SourceRefreshService(settings),
        refresh_run.id,
        heartbeat_seconds=30,
    )
    event = repository.begin_source_refresh_stage(
        db,
        refresh_run,
        stage="export_excel",
        task=task,
    )
    db.commit()
    try:
        summary = repository.report_full_payload(db, report)
        summary.pop("unitRows", None)
        records = export_report_artifacts(
            summary,
            report_id=report.id,
            output_dir=output_dir,
            excel_path=excel_path,
            excel=True,
            docx=False,
            pdf=False,
            html=False,
            csv=False,
            unit_rows_factory=lambda: repository.iter_report_unit_row_payloads(
                db,
                report,
                page_size=1_000,
            ),
        )
        byte_count = 0
        for artifact_type, record in records:
            byte_count += int(record["byte_size"])
            repository.record_report_artifact(
                db,
                report,
                artifact_type=artifact_type,
                path=record["path"],
                sha256=record["hash"],
                byte_size=record["byte_size"],
                status=record["status"],
            )
        now = security.utcnow()
        repository.complete_source_refresh_task(
            db,
            task,
            metrics={"byteCount": byte_count},
            finished_at=now,
        )
        repository.finish_source_refresh_stage(
            db,
            event,
            status="succeeded",
            metrics={"byteCount": byte_count},
            finished_at=now,
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="needs_review",
            worker_id="",
            workbook_path=str(excel_path),
            new_report_run_id=report.id,
            failure_code="",
            error_message="",
            finished_at=now,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        task = db.get(type(task), task.id)
        event = db.get(type(event), event.id)
        if task is not None and task.status == "running":
            repository.fail_source_refresh_task(
                db,
                task,
                safe_error_code="excel_export_failed",
                transient=isinstance(exc, OSError),
            )
        refresh_run = db.get(SourceRefreshRun, refresh_run.id)
        if event is not None and event.status == "running":
            repository.finish_source_refresh_stage(
                db,
                event,
                status="failed",
                safe_error_code="excel_export_failed",
            )
        if refresh_run is not None:
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status=(
                    "rebuilding"
                    if task is not None and task.status == "queued"
                    else "failed"
                ),
                worker_id="",
                failure_code="excel_export_failed",
                error_message="Excel export failed; saved report marts were preserved.",
                finished_at=(
                    None
                    if task is not None and task.status == "queued"
                    else security.utcnow()
                ),
            )
        db.commit()
    finally:
        _stop_heartbeat_process(heartbeat_process)
    return True


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
        execute_one(db, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
