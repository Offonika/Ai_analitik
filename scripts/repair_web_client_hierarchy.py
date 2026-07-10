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
    parser.add_argument("--tenant-name", default="")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--client-name", default="")
    parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="Client organization display name. Can be passed more than once.",
    )
    parser.add_argument(
        "--cabinet",
        action="append",
        default=[],
        help=(
            "WB cabinet display name, or 'Organization::Cabinet' to link it "
            "to a company. Can be passed more than once."
        ),
    )
    parser.add_argument(
        "--link-existing-reports",
        action="store_true",
        help=(
            "Link existing tenant reports to --client-id. By default this is "
            "automatic only for the tenant default client id."
        ),
    )
    parser.add_argument(
        "--dedupe-wb-cabinets",
        action="store_true",
        help=(
            "Merge duplicate WB cabinet rows with the same client and display "
            "name, retargeting report rows and tenant integration metadata."
        ),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")
    if not args.client_name and not args.dedupe_wb_cabinets:
        raise SystemExit(
            "--client-name is required unless --dedupe-wb-cabinets is used"
        )
    engine = make_engine(args.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        counts: dict[str, int] = {}
        client_id = args.client_id
        if not args.client_name:
            if args.dedupe_wb_cabinets:
                counts.update(
                    repository.dedupe_wb_cabinets(
                        db,
                        tenant_id=args.tenant_id,
                        client_id=args.client_id,
                    )
                )
            if args.apply:
                db.commit()
                action = "APPLIED"
            else:
                db.rollback()
                action = "DRY RUN"
            _print_result(action, args.tenant_id, client_id or "(tenant)", counts)
            return 0

        tenant = repository.ensure_tenant(
            db,
            args.tenant_id,
            args.tenant_name or args.client_name,
        )
        default_client_id = repository.client_id_for_tenant(tenant.id)
        try:
            client = repository.ensure_client(
                db,
                tenant_id=tenant.id,
                client_id=args.client_id or default_client_id,
                name=args.client_name,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        client_id = client.id
        db.flush()

        report_ids = list(
            db.scalars(
                select(ReportRun.id)
                .where(ReportRun.tenant_id == tenant.id)
                .order_by(ReportRun.generated_at.desc())
            )
        )

        counts["client"] = 1
        company_ids_by_label = _ensure_requested_companies(
            db,
            tenant_id=tenant.id,
            client_id=client_id,
            labels=args.company,
        )
        cabinet_ids_by_label = _ensure_requested_cabinets(
            db,
            tenant_id=tenant.id,
            client_id=client_id,
            company_ids_by_label=company_ids_by_label,
            values=args.cabinet,
        )
        counts["requested_companies"] = len(company_ids_by_label)
        counts["requested_cabinets"] = len(cabinet_ids_by_label)

        should_link_reports = bool(report_ids) and (
            args.link_existing_reports or client_id == default_client_id
        )
        if should_link_reports:
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
                if organization and company_id:
                    company_ids_by_label[str(organization)] = company_id
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
        elif report_ids:
            counts["skipped_existing_reports"] = len(report_ids)

        if args.dedupe_wb_cabinets:
            for key, value in repository.dedupe_wb_cabinets(
                db,
                tenant_id=tenant.id,
                client_id=client_id,
            ).items():
                counts[f"dedupe_{key}"] = value

        if args.apply:
            db.commit()
            action = "APPLIED"
        else:
            db.rollback()
            action = "DRY RUN"

    _print_result(action, args.tenant_id, client_id, counts, name=args.client_name)
    return 0


def _print_result(
    action: str,
    tenant_id: str,
    client_id: str,
    counts: dict[str, int],
    *,
    name: str = "",
) -> None:
    suffix = f" name={name}" if name else ""
    print(f"{action}: tenant={tenant_id} client={client_id}{suffix}")
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")


def _ensure_requested_companies(
    db,
    *,
    tenant_id: str,
    client_id: str,
    labels: list[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for label in labels:
        company = repository.ensure_client_company(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            display_name=label,
        )
        if company is not None:
            result[company.display_name] = company.id
    return result


def _ensure_requested_cabinets(
    db,
    *,
    tenant_id: str,
    client_id: str,
    company_ids_by_label: dict[str, str],
    values: list[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_value in values:
        company_label, cabinet_label = _cabinet_parts(raw_value)
        company_id = company_ids_by_label.get(company_label, "")
        cabinet = repository.ensure_wb_cabinet(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            display_name=cabinet_label,
            client_company_id=company_id,
        )
        if cabinet is not None:
            result[cabinet.display_name] = cabinet.id
    return result


def _cabinet_parts(value: str) -> tuple[str, str]:
    if "::" not in value:
        return "", value.strip()
    company, cabinet = value.split("::", 1)
    return company.strip(), cabinet.strip()


def _bulk_update(db, statement) -> int:
    result = db.execute(statement.execution_options(synchronize_session=False))
    return int(result.rowcount or 0)


if __name__ == "__main__":
    raise SystemExit(main())
