#!/usr/bin/env python3
"""Sanitize a production database clone before starting the test contour."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository, security  # noqa: E402
from wb_unit_economics.web.database import (  # noqa: E402
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import (  # noqa: E402
    DataRefreshJob,
    LiveCheckCache,
    ReportArtifact,
    ReportGenerationRequest,
    ReportRun,
    SessionToken,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
    TenantIntegration,
    User,
)
from wb_unit_economics.web.settings import WebSettings  # noqa: E402

SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--production-report-root",
        type=Path,
        default=ROOT / "reports",
    )
    parser.add_argument(
        "--test-report-root",
        type=Path,
        default=Path("/data/shumeyko/test/reports"),
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _is_test_database(database_url: str) -> bool:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return Path(url.database or "").stem.endswith("_test")
    return str(url.database or "").endswith("_test")


def _safe_source(path_value: str, allowed_root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    root = allowed_root.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _safe_current_source(
    path_value: str,
    production_root: Path,
    test_root: Path,
) -> tuple[Path | None, bool]:
    production_source = _safe_source(path_value, production_root)
    if production_source is not None:
        return production_source, False
    test_source = _safe_source(path_value, test_root)
    if test_source is not None:
        return test_source, True
    return None, False


def _artifact_destination(
    test_root: Path,
    *,
    report_id: str,
    source: Path,
    discriminator: str,
) -> Path:
    safe_report_id = SAFE_NAME.sub("-", report_id).strip("-") or "report"
    safe_discriminator = SAFE_NAME.sub("-", discriminator).strip("-") or "file"
    return test_root / safe_report_id / f"{safe_discriminator}-{source.name}"


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _delete_raw_snapshot_rows(db: Session) -> int:
    count = int(
        db.scalar(select(func.count()).select_from(SourceSnapshotRow)) or 0
    )
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("TRUNCATE TABLE wb_unit_economics.source_snapshot_rows")
        )
    else:
        db.execute(delete(SourceSnapshotRow))
    return count


def main() -> int:
    args = parse_args()
    settings = WebSettings(_env_file=None)
    if settings.runtime_environment != "test":
        raise SystemExit("Refusing: SHUMEYKO_RUNTIME_ENVIRONMENT must be test")
    if not _is_test_database(settings.database_url):
        raise SystemExit("Refusing: target database name must end with _test")

    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    production_root = args.production_report_root.resolve()
    test_root = args.test_report_root.resolve()

    with factory() as db:
        current_reports = list(
            db.scalars(
                select(ReportRun).where(
                    ReportRun.publication_status == "published",
                    ReportRun.is_current.is_(True),
                )
            )
        )
        users = list(db.scalars(select(User)))
        integrations = list(db.scalars(select(TenantIntegration)))
        active_runs = list(
            db.scalars(
                select(SourceRefreshRun).where(
                    SourceRefreshRun.status.in_(
                        repository.ACTIVE_SOURCE_REFRESH_STATUSES
                    ),
                    SourceRefreshRun.finished_at.is_(None),
                )
            )
        )
        summary = {
            "currentReports": len(current_reports),
            "clientOnlyUsers": sum(
                1
                for user in users
                if not repository.has_role(user, repository.STAFF_ROLES)
            ),
            "integrations": len(integrations),
            "activeRuns": len(active_runs),
            "rawSnapshotRows": int(
                db.scalar(select(func.count()).select_from(SourceSnapshotRow)) or 0
            ),
            "apply": bool(args.apply),
        }
        print(" ".join(f"{key}={value}" for key, value in summary.items()))
        if not args.apply:
            print("Dry-run: test database and report files were not changed.")
            return 0

        copied_workbooks = 0
        copied_artifacts = 0
        reused_workbooks = 0
        reused_artifacts = 0
        current_ids = {report.id for report in current_reports}
        for report in db.scalars(select(ReportRun)):
            source, already_in_test = (
                _safe_current_source(
                    report.source_workbook_path,
                    production_root,
                    test_root,
                )
                if report.id in current_ids
                else (None, False)
            )
            if source is None:
                report.source_workbook_path = ""
                report.source_workbook = ""
                continue
            if already_in_test:
                reused_workbooks += 1
                continue
            destination = _artifact_destination(
                test_root,
                report_id=report.id,
                source=source,
                discriminator="workbook",
            )
            _copy_file(source, destination)
            report.source_workbook_path = str(destination)
            report.source_workbook = destination.name
            copied_workbooks += 1

        for artifact in db.scalars(select(ReportArtifact)):
            source, already_in_test = (
                _safe_current_source(
                    artifact.path,
                    production_root,
                    test_root,
                )
                if artifact.report_run_id in current_ids
                else (None, False)
            )
            if source is None:
                artifact.path = f"unavailable/{artifact.id}"
                artifact.status = "unavailable"
                continue
            if already_in_test:
                reused_artifacts += 1
                continue
            destination = _artifact_destination(
                test_root,
                report_id=artifact.report_run_id,
                source=source,
                discriminator=f"artifact-{artifact.id}",
            )
            _copy_file(source, destination)
            artifact.path = str(destination)
            copied_artifacts += 1

        now = security.utcnow()
        db.execute(delete(SessionToken))
        db.execute(delete(LiveCheckCache))
        db.execute(delete(ReportGenerationRequest))
        db.execute(delete(DataRefreshJob))
        deleted_snapshot_rows = _delete_raw_snapshot_rows(db)

        for user in users:
            if not repository.has_role(user, repository.STAFF_ROLES):
                user.is_active = False
        for integration in integrations:
            integration.status = "disabled"
            integration.secret_hash = ""
            integration.secret_hint = ""
            integration.config_payload = {}
            integration.last_checked_at = None
            integration.disabled_at = now
            integration.updated_at = now
        for refresh_run in db.scalars(select(SourceRefreshRun)):
            refresh_run.root_dir = ""
            refresh_run.workbook_path = ""
        for collection in db.scalars(select(SourceRefreshCollection)):
            collection.raw_path = ""
        for refresh_run in active_runs:
            refresh_run.status = "failed"
            refresh_run.failure_code = "test_clone_reset"
            refresh_run.error_message = (
                "Pending production job removed from test clone."
            )
            refresh_run.finished_at = now
            refresh_run.updated_at = now

        db.commit()
        print(
            f"copiedWorkbooks={copied_workbooks} "
            f"copiedArtifacts={copied_artifacts} "
            f"reusedWorkbooks={reused_workbooks} "
            f"reusedArtifacts={reused_artifacts} "
            f"deletedRawSnapshotRows={deleted_snapshot_rows} status=prepared"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
