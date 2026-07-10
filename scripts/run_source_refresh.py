# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    CREDENTIAL_SOURCES,
    SOURCE_REFRESH_MODES,
    SourceRefreshBusyError,
    SourceRefreshConfigError,
    SourceRefreshDisabledError,
    SourceRefreshService,
)

FAILED_EXIT_STATUSES = {
    "failed",
}


def main() -> int:
    args = _parse_args()
    settings = _settings_from_args(args)
    engine = make_engine(settings.database_url)
    init_db(engine, run_backfill=False)
    session_factory = make_session_factory(engine)
    service = SourceRefreshService(settings)
    with session_factory() as db:
        source_report = None
        if args.source_report_id:
            source_report = db.get(ReportRun, args.source_report_id)
            if source_report is None:
                print(
                    f"source report not found: {args.source_report_id}",
                    file=sys.stderr,
                )
                return 2
        try:
            payload = service.run(
                db,
                tenant_id=args.tenant,
                mode=args.mode,
                credential_source=args.credential_source,
                dry_run=args.dry_run,
                source_report=source_report,
                reason=args.reason,
                period_start=args.period_start,
                period_end=args.period_end,
                resume_mode=args.resume_mode,
                resume_from_run_id=args.resume_from_run_id or None,
            )
        except (
            SourceRefreshDisabledError,
            SourceRefreshBusyError,
            SourceRefreshConfigError,
        ) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        db.commit()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Source refresh: {payload['id']}")
        print(f"Status: {payload['status']}")
        print(f"Mode: {payload['mode']}")
        print(f"Snapshot set: {payload['snapshotSetId']}")
        print(f"Period: {payload['periodStart']} - {payload['periodEnd']}")
        if payload.get("newReportRunId"):
            print(f"New report: {payload['newReportRunId']}")
        if payload.get("errorMessage"):
            print(f"Error: {payload['errorMessage']}")
        for item in payload.get("collections", []):
            required = "required" if item.get("required") else "optional"
            print(
                "- "
                f"{item['sourceType']} ({required}): "
                f"{item['status']}, rows={item['rowCount']}"
            )
    return 1 if payload["status"] in FAILED_EXIT_STATUSES else 0


def _settings_from_args(args: argparse.Namespace) -> WebSettings:
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    if database_url:
        return WebSettings(_env_file=None, database_url=database_url)
    return WebSettings(_env_file=None)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only WB/1C source refresh into local snapshots."
    )
    parser.add_argument("--tenant", required=True, help="Tenant id, e.g. shumeyko.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(SOURCE_REFRESH_MODES),
        help="Refresh mode.",
    )
    parser.add_argument(
        "--credential-source",
        choices=sorted(CREDENTIAL_SOURCES),
        default="tenant",
        help="Use encrypted tenant integrations by default; env is local fallback.",
    )
    parser.add_argument(
        "--source-report-id",
        default="",
        help="Optional report id to link the refresh lineage to.",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Database URL. Defaults to SHUMEYKO_DATABASE_URL or WebSettings.",
    )
    parser.add_argument(
        "--reason",
        default="scheduled source refresh",
        help="Short safe audit reason.",
    )
    parser.add_argument("--period-start", type=date.fromisoformat, default=None)
    parser.add_argument("--period-end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--resume-mode",
        choices=("auto", "never"),
        default="auto",
        help="Continue a compatible immutable 1C checkpoint when available.",
    )
    parser.add_argument(
        "--resume-from-run-id",
        default="",
        help="Explicit compatible source refresh run to continue from.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and lineage without external source reads.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print safe JSON payload.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
