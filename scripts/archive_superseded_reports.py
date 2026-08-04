#!/usr/bin/env python3
"""Dry-run or archive one old superseded report revision to versioned S3."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.report_archive import (
    archive_report_to_s3,
    select_archive_candidates,
)
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--s3-config", type=Path)
    parser.add_argument("--tenant", default="")
    parser.add_argument("--retention-days", type=int, default=365)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        print("Database URL is required; no report was archived.", file=sys.stderr)
        return 2
    if args.apply and args.s3_config is None:
        print("--s3-config is required with --apply.", file=sys.stderr)
        return 2
    engine = make_engine(args.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    cutoff = datetime.now(UTC) - timedelta(days=max(1, args.retention_days))
    with session_factory() as db:
        candidates = select_archive_candidates(
            db,
            cutoff=cutoff,
            tenant_id=args.tenant,
        )
        print(f"Archive candidates: {len(candidates)}")
        for report in candidates[:20]:
            print(f"- {report.id}: created={report.created_at.isoformat()}")
        if not args.apply:
            print("Dry run only. No report marts or artifacts were changed.")
            return 0
        active = int(
            db.scalar(
                select(func.count())
                .select_from(SourceRefreshRun)
                .where(
                    SourceRefreshRun.finished_at.is_(None),
                    SourceRefreshRun.status.in_({"queued", "running", "rebuilding"}),
                )
            )
            or 0
        )
        if active:
            print("Active source refresh blocks report archive.", file=sys.stderr)
            return 2
        if not candidates:
            return 0
        record = archive_report_to_s3(
            db,
            candidates[0],
            s3_config_path=args.s3_config,
        )
        db.commit()
        print(
            f"Archived report: {record.report_run_id}; "
            f"bytes={record.bundle_byte_size}; status={record.status}"
        )
    print("Original report marts were retained pending restore-smoke.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
