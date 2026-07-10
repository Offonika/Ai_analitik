#!/usr/bin/env python3
"""Legacy recovery import from Excel into the web cabinet database.

The regular path is DB-first: sources -> calculation -> report marts -> exports.
Use this script only for emergency recovery from an already accepted workbook.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web.dashboard_payload import build_dashboard_payload
from wb_unit_economics.web.database import (
    init_db,
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.repository import (
    ensure_tenant,
    import_dashboard_payload,
    upsert_user,
)

DEFAULT_WORKBOOK = ROOT / "reports" / "shumeyko_wb_excel_mvp.xlsx"
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--tenant-id", default="shumeyko")
    parser.add_argument("--tenant-name", default="Шумейко и Партнеры")
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--admin-email", default="")
    parser.add_argument("--admin-password-env", default="SHUMEYKO_BOOTSTRAP_PASSWORD")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = args.database_url or "sqlite:///data/web/shumeyko_web.sqlite3"
    workbook = args.workbook.resolve()
    if not workbook.exists():
        raise SystemExit(f"Excel workbook not found: {workbook}")
    payload = build_dashboard_payload(workbook)
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        ensure_tenant(db, args.tenant_id, args.tenant_name)
        report = import_dashboard_payload(
            db,
            payload,
            tenant_id=args.tenant_id,
            tenant_name=args.tenant_name,
            report_id=args.report_id,
            source_workbook_path=str(workbook),
            lineage_type="legacy_excel_import",
        )
        if args.admin_email:
            password = os.getenv(args.admin_password_env)
            if not password:
                raise SystemExit(
                    f"Set {args.admin_password_env} before creating {args.admin_email}"
                )
            upsert_user(
                db,
                email=args.admin_email,
                password=password,
                tenant_id=args.tenant_id,
                role="admin",
                name="Shumeyko admin",
            )
        db.commit()
    print(f"Imported report {report.id} with {len(payload['unitRows'])} unit rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
