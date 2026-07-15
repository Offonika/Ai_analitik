#!/usr/bin/env python3
"""Queue a staff-only accounting report canary without exposing client data."""

from __future__ import annotations

import argparse
import json
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository  # noqa: E402
from wb_unit_economics.web.database import (  # noqa: E402
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import (  # noqa: E402
    Client,
    ClientCompany,
    User,
    UserTenantAccess,
)
from wb_unit_economics.web.report_kinds import (  # noqa: E402
    MONTH_CLOSE_CONTROL,
    TAX_LOAD,
)
from wb_unit_economics.web.settings import WebSettings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--client-match")
    scope.add_argument("--tenant-id")
    parser.add_argument("--client-id")
    organization = parser.add_mutually_exclusive_group(required=True)
    organization.add_argument("--company-match")
    organization.add_argument("--reference-organization-file", type=Path)
    parser.add_argument("--period-month", required=True)
    parser.add_argument(
        "--report-kind",
        choices=(MONTH_CLOSE_CONTROL, TAX_LOAD),
        required=True,
    )
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args()
    if args.tenant_id and not args.client_id:
        parser.error("--client-id is required with --tenant-id")
    if args.client_match and args.client_id:
        parser.error("--client-id cannot be combined with --client-match")
    return args


def _period(period_month: str) -> tuple[date, date]:
    year_text, month_text = period_month.split("-", 1)
    year = int(year_text)
    month = int(month_text)
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _reference_organization_id(path: Path) -> str:
    resolved = path.resolve()
    allowed_root = (ROOT / "data").resolve()
    if not resolved.is_relative_to(allowed_root) or not resolved.is_file():
        raise SystemExit("reference organization file is outside local data")
    if resolved.stat().st_size > 10 * 1024 * 1024:
        raise SystemExit("reference organization file is too large")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    rows = payload.get("value") if isinstance(payload, dict) else None
    organization_ids = {
        str(row.get("Ref_Key") or "").strip()
        for row in rows or []
        if isinstance(row, dict) and str(row.get("Ref_Key") or "").strip()
    }
    if len(organization_ids) != 1:
        raise SystemExit("reference file must contain exactly one organization")
    return next(iter(organization_ids))


def _resolve_client_scope(db: object, args: argparse.Namespace) -> tuple[str, str]:
    if args.client_match:
        needle = str(args.client_match).strip().casefold()
        if not needle:
            raise SystemExit("client match cannot be empty")
        clients = [
            client
            for client in db.scalars(select(Client).order_by(Client.name))
            if needle in client.name.casefold()
        ]
        if len(clients) != 1:
            raise SystemExit("client match must resolve to exactly one client")
        return clients[0].tenant_id, clients[0].id
    tenant_id = str(args.tenant_id or "").strip()
    client_id = str(args.client_id or "").strip()
    client = db.get(Client, client_id)
    if client is None or client.tenant_id != tenant_id:
        raise SystemExit("tenant and client scope do not match")
    return tenant_id, client_id


def main() -> int:
    args = parse_args()
    settings = WebSettings()
    engine = make_engine(
        settings.database_url,
        statement_timeout_ms=settings.postgres_statement_timeout_ms,
    )
    session_factory = make_session_factory(engine)
    period_start, period_end = _period(args.period_month)
    with session_factory() as db:
        tenant_id, client_id = _resolve_client_scope(db, args)
        companies = list(
            db.scalars(
                select(ClientCompany).where(
                    ClientCompany.tenant_id == tenant_id,
                    ClientCompany.client_id == client_id,
                    ClientCompany.status == "active",
                    ClientCompany.onec_organization_id != "",
                )
            )
        )
        if args.reference_organization_file:
            reference_id = _reference_organization_id(
                args.reference_organization_file
            )
            matched = [
                company
                for company in companies
                if company.onec_organization_id == reference_id
            ]
        else:
            company_match = str(args.company_match or "").casefold()
            matched = [
                company
                for company in companies
                if company_match in company.display_name.casefold()
            ]
        if len(matched) != 1:
            raise SystemExit("company match must resolve to exactly one organization")
        accesses = list(
            db.scalars(
                select(UserTenantAccess)
                .join(User)
                .where(
                    UserTenantAccess.tenant_id == tenant_id,
                    UserTenantAccess.role.in_(repository.STAFF_ROLES),
                    User.is_active.is_(True),
                )
            )
        )
        accesses.sort(key=lambda item: (item.role != "admin", item.id))
        if not accesses:
            raise SystemExit("active staff user not found")
        user = db.get(User, accesses[0].user_id)
        if user is None:
            raise SystemExit("active staff user not found")
        run, deduplicated = repository.generate_accounting_report(
            db,
            user=user,
            client_id=client_id,
            report_kind=args.report_kind,
            organization_id=matched[0].onec_organization_id,
            period_start=period_start,
            period_end=period_end,
            idempotency_key=args.idempotency_key,
        )
        db.commit()
        print(f"generation_run_id={run.id}")
        print(f"status={run.status}")
        print(f"deduplicated={str(deduplicated).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
