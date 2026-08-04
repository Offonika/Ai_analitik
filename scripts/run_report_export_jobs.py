#!/usr/bin/env python3
"""Claim and execute queued report export jobs outside HTTP workers."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import or_, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.export_report_artifacts import export_report_artifacts
from wb_unit_economics.report_exports import (
    artifact_record,
    write_ozon_diagnostics_excel,
)
from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    ClientCompany,
    ReportExportJob,
    ReportRun,
    SourceRefreshTask,
)
from wb_unit_economics.web.report_kinds import ACCOUNTING_REPORT_KINDS
from wb_unit_economics.web.reports.excel import write_scenario_excel
from wb_unit_economics.web.settings import WebSettings


def claim_export_job(db) -> ReportExportJob | None:
    task = SourceRefreshTask
    statement = (
        select(ReportExportJob)
        .outerjoin(task, task.id == ReportExportJob.task_id)
        .where(
            ReportExportJob.status == "queued",
            or_(
                ReportExportJob.task_id.is_(None),
                (task.status == "queued")
                & (task.not_before <= security.utcnow()),
            ),
        )
        .order_by(ReportExportJob.created_at, ReportExportJob.id)
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True, of=ReportExportJob)
    job = db.scalar(statement)
    if job is None:
        return None
    now = security.utcnow()
    job.status = "running"
    job.started_at = job.started_at or now
    job.updated_at = now
    if job.task_id:
        queue_task = db.get(SourceRefreshTask, job.task_id)
        if queue_task is not None:
            queue_task.status = "running"
            queue_task.worker_id = f"report-export:{os.getpid()}"
            queue_task.attempt += 1
            queue_task.claimed_at = now
            queue_task.started_at = queue_task.started_at or now
            queue_task.heartbeat_at = now
            queue_task.updated_at = now
    db.commit()
    return job


def execute_export_job(db, job: ReportExportJob, settings: WebSettings) -> None:
    report = db.get(ReportRun, job.report_run_id)
    if report is None:
        raise LookupError("report_not_found")
    output_dir = (
        settings.export_root_path
        / "report_jobs"
        / _safe_segment(report.client_id)
        / _safe_segment(report.id)
    ).resolve()
    allowed_root = settings.export_root_path.resolve()
    if output_dir != allowed_root and allowed_root not in output_dir.parents:
        raise ValueError("export_path_outside_allowed_root")
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[tuple[str, dict]]
    if report.report_kind in ACCOUNTING_REPORT_KINDS:
        if job.export_format != "xlsx":
            raise ValueError("accounting_optional_export_not_supported")
        payload = repository.scenario_payload_for_report(db, report)
        payload_sha256 = str(payload.pop("payloadSha256"))
        company = db.scalar(
            select(ClientCompany)
            .where(
                ClientCompany.tenant_id == report.tenant_id,
                ClientCompany.client_id == report.client_id,
                ClientCompany.onec_organization_id == report.organization_id,
            )
            .order_by(ClientCompany.status != "active", ClientCompany.id)
            .limit(1)
        )
        path = write_scenario_excel(
            payload,
            payload_sha256,
            output_dir / f"{_safe_segment(report.id)}.xlsx",
            export_context={
                "clientName": report.client_name,
                "organizationName": company.display_name if company else "",
            },
        )
        records = [("excel", artifact_record(path))]
    elif report.lineage_type == repository.OZON_DRAFT_LINEAGE_TYPE:
        if job.export_format != "xlsx":
            raise ValueError("ozon_optional_export_not_supported")
        diagnostics = repository.ozon_draft_diagnostics_payload(
            db,
            report,
            limit=repository.OZON_PNL_MAX_SOURCE_ROWS,
            preview_max_rows=repository.OZON_PNL_MAX_SOURCE_ROWS,
        )
        path = write_ozon_diagnostics_excel(
            diagnostics,
            output_dir / f"{_safe_segment(report.id)}.xlsx",
        )
        records = [("excel", artifact_record(path))]
    else:
        summary = repository.report_full_payload(db, report)
        streaming_factory = None
        if job.export_format == "xlsx":
            summary.pop("unitRows", None)

            def streaming_factory():
                return repository.iter_report_unit_row_payloads(
                    db,
                    report,
                    page_size=1_000,
                )
        records = export_report_artifacts(
            summary,
            report_id=report.id,
            output_dir=output_dir,
            excel_path=output_dir / f"{_safe_segment(report.id)}.xlsx",
            excel=job.export_format == "xlsx",
            docx=job.export_format == "docx",
            pdf=False,
            html=job.export_format == "html",
            csv=job.export_format == "csv",
            unit_rows_factory=streaming_factory,
        )
    if not records:
        raise RuntimeError("export_created_no_artifacts")
    first_artifact = None
    for artifact_type, record in records:
        artifact = repository.record_report_artifact(
            db,
            report,
            artifact_type=artifact_type,
            path=record["path"],
            sha256=record["hash"],
            byte_size=record["byte_size"],
            status=record["status"],
        )
        first_artifact = first_artifact or artifact
    now = security.utcnow()
    job.status = "succeeded"
    job.artifact_id = first_artifact.id if first_artifact is not None else None
    job.safe_error_code = ""
    job.finished_at = now
    job.updated_at = now
    if job.task_id:
        task = db.get(SourceRefreshTask, job.task_id)
        if task is not None and task.status == "running":
            repository.complete_source_refresh_task(
                db,
                task,
                metrics={
                    "byteCount": sum(int(record["byte_size"]) for _, record in records)
                },
                finished_at=now,
            )
    db.commit()


def fail_export_job(db, job: ReportExportJob, exc: Exception) -> None:
    db.rollback()
    job = db.get(ReportExportJob, job.id)
    if job is None:
        return
    now = security.utcnow()
    job.safe_error_code = "report_export_failed"
    job.updated_at = now
    task = db.get(SourceRefreshTask, job.task_id) if job.task_id else None
    transient = isinstance(exc, OSError)
    if task is not None and task.status == "running":
        repository.fail_source_refresh_task(
            db,
            task,
            safe_error_code="report_export_failed",
            transient=transient,
            failed_at=now,
        )
        job.status = "queued" if task.status == "queued" else "failed"
    else:
        job.status = "failed"
    if job.status == "failed":
        job.finished_at = now
    db.commit()


def _safe_segment(value: str) -> str:
    safe = "".join(
        character
        for character in value
        if character.isalnum() or character in "-_"
    )
    return safe[:160] or "report"


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
        job = claim_export_job(db)
        if job is None:
            return 0
        try:
            execute_export_job(db, job, settings)
        except Exception as exc:
            fail_export_job(db, job, exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
