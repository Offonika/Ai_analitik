#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.input_vat_overlay import (  # noqa: E402
    overlay_management_input_vat_rows,
)
from wb_unit_economics.web import repository  # noqa: E402
from wb_unit_economics.web.database import (  # noqa: E402
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import (  # noqa: E402
    ReportRun,
    SourceRefreshRun,
    Tenant,
    User,
)
from wb_unit_economics.web.settings import WebSettings  # noqa: E402

IMMUTABLE_PNL_FIELDS = (
    "revenue",
    "revenueWithoutVat",
    "cost",
    "profitBeforeTax",
)


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    settings = (
        WebSettings(_env_file=None, database_url=database_url)
        if database_url
        else WebSettings(_env_file=None)
    )
    session_factory = make_session_factory(make_engine(settings.database_url))
    with session_factory() as db:
        source = _require_report(db, args.source_report_id)
        scenario = _require_report(db, args.scenario_report_id)
        refresh = db.get(SourceRefreshRun, args.refresh_run_id)
        user = db.get(User, args.user_id)
        if refresh is None:
            raise ValueError("source refresh run not found")
        if user is None:
            raise ValueError("audit user not found")
        _validate_scope(source, scenario, refresh)
        existing_output = db.get(ReportRun, args.output_report_id)
        if existing_output is not None and (
            existing_output.is_current
            or existing_output.publication_status == "published"
        ):
            raise ValueError("existing output report is not a replaceable draft")

        source_payload = repository.report_full_payload(db, source)
        scenario_payload = repository.report_full_payload(db, scenario)
        source_rows = source_payload.get("unitRows") or []
        scenario_rows = scenario_payload.get("unitRows") or []
        before = _money_totals(source_rows, IMMUTABLE_PNL_FIELDS)
        overlay = overlay_management_input_vat_rows(source_rows, scenario_rows)
        after = _money_totals(source_rows, IMMUTABLE_PNL_FIELDS)
        if after != before:
            raise ValueError(
                f"management VAT overlay changed immutable P&L: {before} != {after}"
            )

        _apply_scenario_metadata(source_payload, scenario_payload)
        summary = {
            "mode": "apply" if args.apply else "dry-run",
            "sourceReportId": source.id,
            "scenarioReportId": scenario.id,
            "outputReportId": args.output_report_id,
            "sourceRefreshRunId": refresh.id,
            "immutablePnl": before,
            "overlay": overlay,
        }
        if not args.apply:
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            return 0

        tenant = db.get(Tenant, source.tenant_id)
        report = repository.save_report_marts(
            db,
            source_payload,
            tenant_id=source.tenant_id,
            tenant_name=tenant.name if tenant is not None else source.client_name,
            report_id=args.output_report_id,
            publication_status="draft",
            publish=False,
            source_snapshot_set_id=scenario.source_snapshot_set_id,
        )
        base_refresh = (
            db.get(SourceRefreshRun, refresh.base_source_refresh_run_id)
            if refresh.base_source_refresh_run_id
            else None
        )
        repository.replace_source_loads_from_refresh(
            db,
            report,
            refresh,
            base_refresh_run=base_refresh,
        )
        repository.reconcile_report_mapping_source_load(db, report)
        scenario.publication_status = "superseded"
        scenario.is_current = False
        repository.audit(
            db,
            action="management_input_vat_overlay_materialized",
            user=user,
            tenant_id=source.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={
                "sourceReportId": source.id,
                "scenarioReportId": scenario.id,
                "sourceRefreshRunId": refresh.id,
                "immutablePnl": {key: str(value) for key, value in before.items()},
                "overlayTotals": {
                    key: str(value) for key, value in overlay["totals"].items()
                },
                "createdAt": datetime.now(tz=UTC).isoformat(),
            },
        )
        db.commit()
        summary["publicationStatus"] = report.publication_status
        summary["isCurrent"] = report.is_current
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a VAT-only management-assumption draft while preserving "
            "the source report P&L."
        )
    )
    parser.add_argument("--source-report-id", required=True)
    parser.add_argument("--scenario-report-id", required=True)
    parser.add_argument("--refresh-run-id", required=True)
    parser.add_argument("--output-report-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _require_report(db: Any, report_id: str) -> ReportRun:
    report = db.get(ReportRun, report_id)
    if report is None:
        raise ValueError(f"report not found: {report_id}")
    return report


def _validate_scope(
    source: ReportRun,
    scenario: ReportRun,
    refresh: SourceRefreshRun,
) -> None:
    if source.tenant_id != scenario.tenant_id or source.client_id != scenario.client_id:
        raise ValueError("source and scenario reports belong to different clients")
    if (source.period_start, source.period_end) != (
        scenario.period_start,
        scenario.period_end,
    ):
        raise ValueError("source and scenario report periods differ")
    if refresh.tenant_id != source.tenant_id or refresh.client_id != source.client_id:
        raise ValueError("source refresh does not belong to report client")
    if refresh.new_report_run_id != scenario.id:
        raise ValueError("scenario report is not the result of the selected refresh")
    if source.publication_status != "published" or not source.is_current:
        raise ValueError("source report must still be the current published report")
    if (
        scenario.publication_status not in {"draft", "superseded"}
        or scenario.is_current
    ):
        raise ValueError("scenario report must be non-current and unpublished")


def _apply_scenario_metadata(
    source_payload: dict[str, Any],
    scenario_payload: Mapping[str, Any],
) -> None:
    source_meta = source_payload.setdefault("meta", {})
    scenario_meta = scenario_payload.get("meta") or {}
    for field in (
        "methodologyVersion",
        "generatedAt",
        "generatedAtIso",
        "sourceSnapshotSetId",
    ):
        if scenario_meta.get(field) not in (None, ""):
            source_meta[field] = scenario_meta[field]
    source_meta["publicationStatus"] = "draft"
    source_meta["isCurrent"] = False
    for field in (
        "taxContext",
        "taxProfileSync",
        "taxInputReconciliation",
        "latestSourceRefresh",
    ):
        if field in scenario_payload:
            source_payload[field] = scenario_payload[field]


def _money_totals(
    rows: list[Mapping[str, Any]], fields: tuple[str, ...]
) -> dict[str, Decimal]:
    return {
        field: sum(
            (Decimal(str(row.get(field) or 0)) for row in rows), Decimal("0")
        )
        for field in fields
    }


if __name__ == "__main__":
    raise SystemExit(main())
