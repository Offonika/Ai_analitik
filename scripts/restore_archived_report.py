#!/usr/bin/env python3
"""Restore a verified report archive as a non-current read-only report."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.report_archive import restore_archived_report
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportArchiveRecord


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--archive-id", required=True)
    parser.add_argument("--s3-config", type=Path, required=True)
    args = parser.parse_args()
    if not args.database_url:
        print("Database URL is required; no report was restored.", file=sys.stderr)
        return 2
    engine = make_engine(args.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        record = db.get(ReportArchiveRecord, args.archive_id)
        if record is None:
            print("Archive record not found.", file=sys.stderr)
            return 2
        restored = restore_archived_report(
            db,
            record,
            s3_config_path=args.s3_config,
        )
        db.commit()
        print(
            f"Restored report: {restored.id}; "
            f"publication={restored.publication_status}; current={restored.is_current}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
