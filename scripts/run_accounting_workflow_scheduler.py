#!/usr/bin/env python3
"""Run monthly accounting workflow creation and due follow-up processing."""

from __future__ import annotations

import argparse
import json
import sys
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import accounting_workflow  # noqa: E402
from wb_unit_economics.web.database import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import Client  # noqa: E402
from wb_unit_economics.web.settings import WebSettings  # noqa: E402

MOSCOW = ZoneInfo("Europe/Moscow")


def _period_month(value: str) -> date:
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("period must use YYYY-MM") from exc
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default="", help="Limit run to one tenant.")
    parser.add_argument(
        "--period-month",
        type=_period_month,
        default=None,
        help="Reporting month in YYYY-MM; defaults to the current Moscow month.",
    )
    parser.add_argument(
        "--force-monthly",
        action="store_true",
        help="Run idempotent monthly creation before the last calendar day.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute validations and roll back all database changes.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = WebSettings()
    try:
        accounting_workflow.require_enabled(settings)
        if not settings.accounting_workflow_scheduler_enabled:
            raise accounting_workflow.WorkflowConfigurationError(
                "accounting workflow scheduler is disabled"
            )
        accounting_workflow.BusinessCalendar(settings).require_configured()
    except accounting_workflow.WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    now = datetime.now(MOSCOW)
    report_period = args.period_month or now.date().replace(day=1)
    is_last_calendar_day = now.day == monthrange(now.year, now.month)[1]
    run_monthly = args.force_monthly or (
        report_period == now.date().replace(day=1) and is_last_calendar_day
    )

    engine = make_engine(
        settings.database_url,
        statement_timeout_ms=settings.postgres_statement_timeout_ms,
    )
    init_db(engine, run_backfill=False)
    session_factory = make_session_factory(engine)
    result: dict[str, object] = {
        "periodMonth": report_period.strftime("%Y-%m"),
        "monthlyCreationRun": run_monthly,
        "dryRun": args.dry_run,
        "tenants": [],
        "followups": {"due": 0, "escalated": 0},
    }

    connection = engine.connect() if args.dry_run else None
    outer_transaction = None
    if connection is not None:
        if connection.dialect.name == "sqlite":
            # SQLite defers BEGIN until the first write. Force it before the
            # service opens a SAVEPOINT, otherwise releasing that SAVEPOINT can
            # make a nominal dry-run durable.
            connection.exec_driver_sql("BEGIN")
            outer_transaction = connection.get_transaction()
        else:
            outer_transaction = connection.begin()
    db = (
        session_factory(bind=connection, join_transaction_mode="rollback_only")
        if connection is not None
        else session_factory()
    )
    try:
        tenant_ids = list(
            db.scalars(
                select(Client.tenant_id)
                .where(Client.status == "active")
                .distinct()
                .order_by(Client.tenant_id)
            )
        )
        if args.tenant_id:
            tenant_ids = [item for item in tenant_ids if item == args.tenant_id]
            if not tenant_ids:
                raise accounting_workflow.WorkflowConfigurationError(
                    "active tenant is not configured"
                )
        for tenant_id in tenant_ids:
            tenant_result: dict[str, object] = {"tenantId": tenant_id}
            if run_monthly:
                monthly = accounting_workflow.create_month_cards(
                    db,
                    settings=settings,
                    tenant_id=tenant_id,
                    report_period=report_period,
                    user=None,
                    creation_kind="scheduled",
                    now=now,
                )
                tenant_result.update(
                    created=len(monthly["created"]),
                    existing=len(monthly["existing"]),
                    gaps=monthly["gaps"],
                )
            result["tenants"].append(tenant_result)
        followups = accounting_workflow.process_due_followups(
            db,
            settings=settings,
            now=now,
        )
        result["followups"] = followups
        if args.dry_run:
            db.flush()
        else:
            db.commit()
    except accounting_workflow.WorkflowError as exc:
        db.rollback()
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        db.close()
        if outer_transaction is not None and outer_transaction.is_active:
            outer_transaction.rollback()
        if connection is not None:
            connection.close()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "accounting_workflow_scheduler "
            f"period={result['periodMonth']} "
            f"monthly={str(run_monthly).lower()} "
            f"tenants={len(result['tenants'])} "
            f"due={result['followups']['due']} "
            f"escalated={result['followups']['escalated']} "
            f"dry_run={str(args.dry_run).lower()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
