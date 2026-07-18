#!/usr/bin/env python3
"""Prune stale non-current report drafts and their registered artifacts."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import bindparam, delete, func, select, text, update
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.maintenance_safety import (
    BackupVerificationError,
    verify_backup_bundle,
)
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import (
    DataRefreshJob,
    ReportArtifact,
    ReportRun,
    SourceRefreshRun,
)

PROTECTED_REFERENCE_COLUMNS = (
    ("ai_threads", "report_run_id"),
    ("ai_client_drafts", "report_run_id"),
    ("accounting_workflow_tasks", "current_report_id"),
    ("accounting_workflow_report_revisions", "report_id"),
    ("accounting_workflow_deliveries", "report_id"),
    ("report_logistics_analysis_contexts", "report_run_id"),
    ("data_refresh_jobs", "source_report_run_id"),
)

CHILD_TABLES = (
    "report_logistics_sku_rows",
    "report_logistics_order_rows",
    "report_logistics_analysis_contexts",
    "report_unit_rows",
    "report_lost_sales_rows",
    "report_reconciliation_monthly",
    "report_marketplace_expense_rows",
    "report_document_reconciliation_rows",
    "report_artifacts",
    "source_loads",
    "live_check_cache",
    "month_close_control_reports",
    "tax_load_reports",
)

COUNTED_TABLES = tuple(table for table in CHILD_TABLES if table != "report_artifacts")


@dataclass(frozen=True)
class ReportDraftRecord:
    id: str
    tenant_id: str
    client_id: str
    report_kind: str
    organization_id: str
    created_at: datetime


@dataclass(frozen=True)
class ArtifactRecord:
    path: Path
    byte_size: int


def select_draft_candidates(
    records: list[ReportDraftRecord],
    *,
    cutoff: datetime,
    keep_latest: int,
    protected_ids: set[str],
) -> list[ReportDraftRecord]:
    grouped: dict[tuple[str, str, str, str], list[ReportDraftRecord]] = {}
    for item in records:
        key = (
            item.tenant_id,
            item.client_id,
            item.report_kind,
            item.organization_id,
        )
        grouped.setdefault(key, []).append(item)

    candidates: list[ReportDraftRecord] = []
    keep_count = max(0, keep_latest)
    for items in grouped.values():
        ordered = sorted(
            items,
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )
        for index, item in enumerate(ordered):
            if index < keep_count:
                continue
            if item.created_at >= cutoff or item.id in protected_ids:
                continue
            candidates.append(item)
    return sorted(candidates, key=lambda item: (item.created_at, item.id))


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        print("Database URL is required; no reports were deleted.", file=sys.stderr)
        return 2
    if args.apply:
        if not args.backup_verification:
            print(
                "--backup-verification is required with --apply; "
                "no reports were deleted.",
                file=sys.stderr,
            )
            return 2
        try:
            verify_backup_bundle(
                Path(args.backup_verification),
                max_age_hours=args.backup_max_age_hours,
                postgres_data_path=Path(args.postgres_data_path),
                source_data_path=Path(args.source_data_path),
            )
        except BackupVerificationError as exc:
            print(
                f"Backup preflight failed; no reports were deleted: {exc}",
                file=sys.stderr,
            )
            return 2

    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    cutoff = datetime.now(UTC) - timedelta(hours=max(0, args.grace_hours))
    try:
        with session_factory() as db:
            _set_statement_timeout(db, args.statement_timeout_ms)
            candidates = _candidates(
                db,
                tenant_id=args.tenant,
                cutoff=cutoff,
                keep_latest=args.keep_latest,
                explicit_protected=set(args.protect_report),
            )
            candidate_ids = [item.id for item in candidates]
            artifacts = _artifact_records(
                db,
                candidate_ids=candidate_ids,
                reports_root=Path(args.reports_root),
            )
            dependent_counts = _dependent_counts(db, candidate_ids)
    except Exception as exc:
        print(
            "Report retention preflight failed; no reports were deleted: "
            f"{exc.__class__.__name__}",
            file=sys.stderr,
        )
        return 2

    print(f"Drafts inspected: {_draft_count(session_factory, args.tenant)}")
    print(f"Delete candidates: {len(candidates)}")
    print(f"Dependent rows: {sum(dependent_counts.values())}")
    print(f"Artifact files: {len(artifacts)}")
    print(f"Artifact bytes: {sum(item.byte_size for item in artifacts)}")
    for item in candidates[: max(0, args.list_limit)]:
        print(
            f"- {item.id}: kind={item.report_kind} "
            f"created={item.created_at.isoformat()}"
        )
    if len(candidates) > max(0, args.list_limit):
        print(f"- ... {len(candidates) - max(0, args.list_limit)} more omitted")

    if not args.apply:
        print("Dry run only. Re-run with --apply to delete candidate drafts.")
        return 0
    if not candidates:
        print("No candidate report drafts to delete.")
        return 0

    if _active_refresh_count(session_factory, args.tenant) > 0:
        print(
            "Active source refresh blocks report retention; no reports were deleted.",
            file=sys.stderr,
        )
        return 2

    expected_ids = [item.id for item in candidates]
    try:
        deleted_counts, artifact_paths = _apply(
            session_factory,
            tenant_id=args.tenant,
            cutoff=cutoff,
            keep_latest=args.keep_latest,
            explicit_protected=set(args.protect_report),
            expected_ids=expected_ids,
            reports_root=Path(args.reports_root),
            statement_timeout_ms=args.statement_timeout_ms,
        )
    except Exception as exc:
        print(
            "Report retention apply failed; database transaction rolled back: "
            f"{exc.__class__.__name__}",
            file=sys.stderr,
        )
        return 2

    try:
        removed_files, removed_bytes = _remove_artifacts(
            artifact_paths,
            reports_root=Path(args.reports_root),
        )
    except OSError as exc:
        print(
            "Report rows were deleted, but artifact cleanup failed: "
            f"{exc.__class__.__name__}",
            file=sys.stderr,
        )
        return 2

    print(f"Deleted report drafts: {deleted_counts['report_runs']}")
    dependent_deleted = sum(deleted_counts.values()) - deleted_counts["report_runs"]
    print(f"Deleted dependent rows: {dependent_deleted}")
    print(f"Removed artifact files: {removed_files}")
    print(f"Removed artifact bytes: {removed_bytes}")
    return 0


def _draft_count(session_factory: object, tenant_id: str) -> int:
    with session_factory() as db:  # type: ignore[operator]
        statement = (
            select(func.count())
            .select_from(ReportRun)
            .where(
                ReportRun.publication_status == "draft",
                ReportRun.is_current.is_(False),
            )
        )
        if tenant_id:
            statement = statement.where(ReportRun.tenant_id == tenant_id)
        return int(db.scalar(statement) or 0)


def _draft_records(db: Session, tenant_id: str) -> list[ReportDraftRecord]:
    statement = select(
        ReportRun.id,
        ReportRun.tenant_id,
        ReportRun.client_id,
        ReportRun.report_kind,
        ReportRun.organization_id,
        ReportRun.created_at,
    ).where(
        ReportRun.publication_status == "draft",
        ReportRun.is_current.is_(False),
    )
    if tenant_id:
        statement = statement.where(ReportRun.tenant_id == tenant_id)
    return [
        ReportDraftRecord(
            id=str(item.id),
            tenant_id=str(item.tenant_id),
            client_id=str(item.client_id),
            report_kind=str(item.report_kind),
            organization_id=str(item.organization_id or ""),
            created_at=_aware(item.created_at),
        )
        for item in db.execute(statement)
    ]


def _candidates(
    db: Session,
    *,
    tenant_id: str,
    cutoff: datetime,
    keep_latest: int,
    explicit_protected: set[str],
) -> list[ReportDraftRecord]:
    records = _draft_records(db, tenant_id)
    report_ids = [item.id for item in records]
    protected = set(explicit_protected)
    for table, column in PROTECTED_REFERENCE_COLUMNS:
        protected.update(_referenced_ids(db, table, column, report_ids))
    return select_draft_candidates(
        records,
        cutoff=cutoff,
        keep_latest=keep_latest,
        protected_ids=protected,
    )


def _referenced_ids(
    db: Session,
    table: str,
    column: str,
    report_ids: list[str],
) -> set[str]:
    if not report_ids:
        return set()
    statement = text(
        f"SELECT DISTINCT {column} FROM wb_unit_economics.{table} "
        f"WHERE {column} IN :report_ids"
    ).bindparams(bindparam("report_ids", expanding=True))
    return {
        str(value)
        for value in db.scalars(statement, {"report_ids": report_ids})
        if value
    }


def _artifact_records(
    db: Session,
    *,
    candidate_ids: list[str],
    reports_root: Path,
) -> list[ArtifactRecord]:
    if not candidate_ids:
        return []
    root = reports_root.resolve(strict=True)
    rows = list(
        db.execute(
            select(
                ReportArtifact.path,
                func.max(ReportArtifact.byte_size).label("byte_size"),
                func.count().label("path_count"),
            )
            .where(ReportArtifact.report_run_id.in_(candidate_ids))
            .group_by(ReportArtifact.path)
        )
    )
    paths = {str(item.path) for item in rows}
    if paths:
        shared = db.scalar(
            select(func.count())
            .select_from(ReportArtifact)
            .where(
                ReportArtifact.path.in_(paths),
                ReportArtifact.report_run_id.not_in(candidate_ids),
            )
        )
        if int(shared or 0) > 0:
            raise ValueError("candidate report artifacts have shared paths")
    artifacts: list[ArtifactRecord] = []
    for item in rows:
        if int(item.path_count) != 1:
            raise ValueError("candidate report artifacts reuse a path")
        path = Path(str(item.path))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise ValueError("candidate artifact is outside reports_root")
        if _has_symlink_component(path, root):
            raise ValueError("candidate artifact path contains a symlink")
        if not path.exists():
            raise ValueError("candidate artifact is missing")
        if not path.is_file():
            raise ValueError("candidate artifact is not a regular file")
        artifacts.append(
            ArtifactRecord(path=resolved, byte_size=max(0, int(item.byte_size or 0)))
        )
    return sorted(artifacts, key=lambda item: str(item.path))


def _dependent_counts(db: Session, report_ids: list[str]) -> dict[str, int]:
    if not report_ids:
        return {table: 0 for table in (*COUNTED_TABLES, "report_artifacts")}
    counts: dict[str, int] = {}
    for table in (*COUNTED_TABLES, "report_artifacts"):
        statement = text(
            f"SELECT count(*) FROM wb_unit_economics.{table} "
            "WHERE report_run_id IN :report_ids"
        ).bindparams(bindparam("report_ids", expanding=True))
        counts[table] = int(db.scalar(statement, {"report_ids": report_ids}) or 0)
    return counts


def _active_refresh_count(session_factory: object, tenant_id: str) -> int:
    with session_factory() as db:  # type: ignore[operator]
        statement = (
            select(func.count())
            .select_from(SourceRefreshRun)
            .where(SourceRefreshRun.finished_at.is_(None))
        )
        if tenant_id:
            statement = statement.where(SourceRefreshRun.tenant_id == tenant_id)
        return int(db.scalar(statement) or 0)


def _apply(
    session_factory: object,
    *,
    tenant_id: str,
    cutoff: datetime,
    keep_latest: int,
    explicit_protected: set[str],
    expected_ids: list[str],
    reports_root: Path,
    statement_timeout_ms: int,
) -> tuple[dict[str, int], list[Path]]:
    with session_factory() as db:  # type: ignore[operator]
        _set_statement_timeout(db, statement_timeout_ms)
        candidates = _candidates(
            db,
            tenant_id=tenant_id,
            cutoff=cutoff,
            keep_latest=keep_latest,
            explicit_protected=explicit_protected,
        )
        candidate_ids = [item.id for item in candidates]
        if candidate_ids != expected_ids:
            raise RuntimeError("candidate report set changed after preflight")
        artifacts = _artifact_records(
            db,
            candidate_ids=candidate_ids,
            reports_root=reports_root,
        )

        db.execute(
            update(SourceRefreshRun)
            .where(SourceRefreshRun.source_report_run_id.in_(candidate_ids))
            .values(source_report_run_id=None)
        )
        db.execute(
            update(SourceRefreshRun)
            .where(SourceRefreshRun.new_report_run_id.in_(candidate_ids))
            .values(new_report_run_id=None)
        )
        db.execute(
            update(DataRefreshJob)
            .where(DataRefreshJob.new_report_run_id.in_(candidate_ids))
            .values(new_report_run_id=None)
        )

        deleted: dict[str, int] = {}
        for table in CHILD_TABLES:
            statement = text(
                f"DELETE FROM wb_unit_economics.{table} "
                "WHERE report_run_id IN :report_ids"
            ).bindparams(bindparam("report_ids", expanding=True))
            result = db.execute(statement, {"report_ids": candidate_ids})
            deleted[table] = int(result.rowcount or 0)
        result = db.execute(delete(ReportRun).where(ReportRun.id.in_(candidate_ids)))
        deleted["report_runs"] = int(result.rowcount or 0)
        if deleted["report_runs"] != len(candidate_ids):
            raise RuntimeError("not all candidate report drafts were deleted")
        db.commit()
    return deleted, [item.path for item in artifacts]


def _remove_artifacts(
    paths: list[Path],
    *,
    reports_root: Path,
) -> tuple[int, int]:
    root = reports_root.resolve(strict=True)
    removed_files = 0
    removed_bytes = 0
    for path in paths:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root) or _has_symlink_component(path, root):
            raise OSError("artifact path changed after database commit")
        if not path.exists():
            raise OSError("artifact path disappeared after database commit")
        if not path.is_file():
            raise OSError("artifact path is no longer a regular file")
        size = path.stat().st_size
        path.unlink()
        removed_files += 1
        removed_bytes += size
        parent = path.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return removed_files, removed_bytes


def _has_symlink_component(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink():
            return True
        if current.parent == current:
            return True
        current = current.parent
    return root.is_symlink()


def _set_statement_timeout(db: Session, timeout_ms: int) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    safe_timeout = max(1_000, int(timeout_ms))
    db.execute(text(f"SET LOCAL statement_timeout = {safe_timeout}"))
    db.execute(text("SET LOCAL lock_timeout = 5000"))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--tenant", default="")
    parser.add_argument("--reports-root", default=str(PROJECT_ROOT / "reports"))
    parser.add_argument("--keep-latest", type=int, default=1)
    parser.add_argument("--grace-hours", type=int, default=24)
    parser.add_argument("--protect-report", action="append", default=[])
    parser.add_argument("--list-limit", type=int, default=20)
    parser.add_argument("--statement-timeout-ms", type=int, default=600_000)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-verification", default="")
    parser.add_argument("--backup-max-age-hours", type=int, default=24)
    parser.add_argument("--postgres-data-path", default="/var/lib/postgresql")
    parser.add_argument("--source-data-path", default="/data")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
