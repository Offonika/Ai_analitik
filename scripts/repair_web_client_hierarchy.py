#!/usr/bin/env python3
"""Repair lightweight client hierarchy links for existing web report marts."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import func, select, update

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import (
    ReportDocumentReconciliationRow,
    ReportLostSalesRow,
    ReportRun,
    ReportUnitRow,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
)


DEFAULT_LOCAL_POSTGRES_URL = (
    "postgresql+psycopg://postgres@/shumeyko_web_cabinet"
    "?host=/var/run/postgresql&port=55433"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("SHUMEYKO_DATABASE_URL") or DEFAULT_LOCAL_POSTGRES_URL,
    )
    parser.add_argument("--tenant-id", default="shumeyko")
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = make_engine(args.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        tenant = db.get(repository.Tenant, args.tenant_id)
        if tenant is None:
            raise SystemExit(f"tenant not found: {args.tenant_id}")

        client = repository.ensure_client_for_tenant(
            db,
            tenant_id=tenant.id,
            name=tenant.name,
        )
        client.name = args.client_name
        client_id = client.id
        db.flush()

        report_ids = list(
            db.scalars(
                select(ReportRun.id)
                .where(ReportRun.tenant_id == tenant.id)
                .order_by(ReportRun.generated_at.desc())
            )
        )
        if not report_ids:
            print(f"No report runs found for tenant={tenant.id}")
            return 0

        counts: dict[str, int] = {}
        counts["report_runs"] = _bulk_update(
            db,
            update(ReportRun)
            .where(ReportRun.id.in_(report_ids))
            .values(client_id=client_id, client_name=args.client_name),
        )

        pair_rows = list(
            db.execute(
                select(
                    ReportUnitRow.organization,
                    ReportUnitRow.cabinet,
                    func.count(ReportUnitRow.id),
                )
                .where(ReportUnitRow.report_run_id.in_(report_ids))
                .group_by(ReportUnitRow.organization, ReportUnitRow.cabinet)
                .order_by(func.count(ReportUnitRow.id).desc())
            )
        )
        cabinet_ids_by_label: dict[str, str] = {}
        for organization, cabinet_label, _count in pair_rows:
            company = repository.ensure_client_company(
                db,
                tenant_id=tenant.id,
                client_id=client_id,
                display_name=organization or "",
            )
            cabinet = repository.ensure_wb_cabinet(
                db,
                tenant_id=tenant.id,
                client_id=client_id,
                display_name=cabinet_label or "",
                client_company_id=company.id if company else "",
            )
            company_id = company.id if company else ""
            cabinet_id = cabinet.id if cabinet else ""
            if cabinet_label and cabinet_id:
                cabinet_ids_by_label[str(cabinet_label)] = cabinet_id
            counts["unit_rows"] = counts.get("unit_rows", 0) + _bulk_update(
                db,
                update(ReportUnitRow)
                .where(
                    ReportUnitRow.report_run_id.in_(report_ids),
                    ReportUnitRow.organization == organization,
                    ReportUnitRow.cabinet == cabinet_label,
                )
                .values(
                    client_id=client.id,
                    client_company_id=company_id,
                    wb_cabinet_id=cabinet_id,
                ),
            )
            counts["document_rows"] = counts.get("document_rows", 0) + _bulk_update(
                db,
                update(ReportDocumentReconciliationRow)
                .where(
                    ReportDocumentReconciliationRow.report_run_id.in_(report_ids),
                    ReportDocumentReconciliationRow.organization == organization,
                    ReportDocumentReconciliationRow.cabinet == cabinet_label,
                )
                .values(
                    client_id=client.id,
                    client_company_id=company_id,
                    wb_cabinet_id=cabinet_id,
                ),
            )

        lost_cabinets = list(
            db.execute(
                select(
                    ReportLostSalesRow.cabinet,
                    func.count(ReportLostSalesRow.id),
                )
                .where(ReportLostSalesRow.report_run_id.in_(report_ids))
                .group_by(ReportLostSalesRow.cabinet)
            )
        )
        for cabinet_label, _count in lost_cabinets:
            cabinet_id = cabinet_ids_by_label.get(str(cabinet_label or ""))
            if not cabinet_id:
                cabinet = repository.ensure_wb_cabinet(
                    db,
                    tenant_id=tenant.id,
                    client_id=client_id,
                    display_name=cabinet_label or "",
                )
                cabinet_id = cabinet.id if cabinet else ""
            counts["lost_rows"] = counts.get("lost_rows", 0) + _bulk_update(
                db,
                update(ReportLostSalesRow)
                .where(
                    ReportLostSalesRow.report_run_id.in_(report_ids),
                    ReportLostSalesRow.cabinet == cabinet_label,
                )
                .values(client_id=client_id, wb_cabinet_id=cabinet_id),
            )

        counts["source_loads"] = _bulk_update(
            db,
            update(SourceLoad)
            .where(SourceLoad.report_run_id.in_(report_ids))
            .values(client_id=client_id),
        )
        counts["source_refresh_runs"] = _bulk_update(
            db,
            update(SourceRefreshRun)
            .where(
                SourceRefreshRun.tenant_id == tenant.id,
                (
                    SourceRefreshRun.new_report_run_id.in_(report_ids)
                    | SourceRefreshRun.source_report_run_id.in_(report_ids)
                ),
            )
            .values(client_id=client_id),
        )
        refresh_run_ids = list(
            db.scalars(
                select(SourceRefreshRun.id).where(
                    SourceRefreshRun.tenant_id == tenant.id,
                    SourceRefreshRun.client_id == client_id,
                )
            )
        )
        if refresh_run_ids:
            counts["source_refresh_collections"] = _bulk_update(
                db,
                update(SourceRefreshCollection)
                .where(SourceRefreshCollection.refresh_run_id.in_(refresh_run_ids))
                .values(client_id=client.id),
            )

        if args.dry_run:
            db.rollback()
            action = "DRY RUN"
        else:
            db.commit()
            action = "APPLIED"

    print(
        f"{action}: tenant={args.tenant_id} "
        f"client={client_id} name={args.client_name}"
    )
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


def _bulk_update(db, statement) -> int:
    result = db.execute(statement.execution_options(synchronize_session=False))
    return int(result.rowcount or 0)


if __name__ == "__main__":
    raise SystemExit(main())
