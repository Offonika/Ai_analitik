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

from scripts.run_source_refresh_worker import claim_run_by_id, process_run
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun, SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    CREDENTIAL_SOURCES,
    SOURCE_REFRESH_MODES,
    SourceRefreshBusyError,
    SourceRefreshConfigError,
    SourceRefreshDisabledError,
    SourceRefreshService,
)
from wb_unit_economics.web.source_refresh_worker import (
    SourceRefreshWorkerLaunchError,
    enqueue_source_refresh_worker,
    launch_source_refresh_worker,
    production_source_refresh_worker_launcher,
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
    worker_launcher = production_source_refresh_worker_launcher(settings)
    queued_run_id = ""
    with session_factory() as db:
        if args.run_id:
            try:
                if worker_launcher is not None and not args.worker_id:
                    payload = launch_source_refresh_worker(
                        db,
                        refresh_run_id=args.run_id,
                        worker_launcher=worker_launcher,
                    )
                    return _print_result(payload, as_json=args.json)
                queued_run_id = args.run_id
            except (
                SourceRefreshDisabledError,
                SourceRefreshBusyError,
                SourceRefreshConfigError,
                SourceRefreshWorkerLaunchError,
                LookupError,
            ) as exc:
                print(str(exc), file=sys.stderr)
                return 2
        else:
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
                run_options = {
                    "tenant_id": args.tenant,
                    "mode": args.mode,
                    "credential_source": args.credential_source,
                    "source_report": source_report,
                    "reason": args.reason,
                    "period_start": args.period_start,
                    "period_end": args.period_end,
                    "resume_mode": args.resume_mode,
                    "resume_from_run_id": args.resume_from_run_id or None,
                }
                if args.dry_run:
                    payload = service.run(db, dry_run=True, **run_options)
                    db.commit()
                else:
                    payload = enqueue_source_refresh_worker(
                        db,
                        source_refresh_service=service,
                        worker_launcher=worker_launcher,
                        **run_options,
                    )
            except (
                SourceRefreshDisabledError,
                SourceRefreshBusyError,
                SourceRefreshConfigError,
                SourceRefreshWorkerLaunchError,
            ) as exc:
                print(str(exc), file=sys.stderr)
                return 2
            if (
                not args.dry_run
                and worker_launcher is None
                and payload.get("status") == "queued"
            ):
                queued_run_id = str(payload["id"])

    if queued_run_id:
        worker_id = args.worker_id or f"cli:{os.getpid()}:{queued_run_id}"
        with session_factory() as db:
            claimed = claim_run_by_id(
                db,
                refresh_run_id=queued_run_id,
                worker_id=worker_id,
            )
        if claimed is not None:
            process_run(
                session_factory,
                service,
                queued_run_id,
                heartbeat_seconds=30,
            )
        with session_factory() as db:
            refresh_run = db.get(SourceRefreshRun, queued_run_id)
            if refresh_run is not None:
                payload = repository.source_refresh_run_payload(refresh_run)

    return _print_result(payload, as_json=args.json)


def _print_result(payload: dict[str, object], *, as_json: bool) -> int:
    if as_json:
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
    parser.add_argument("--tenant", default="", help="Tenant id, e.g. shumeyko.")
    parser.add_argument(
        "--mode",
        default="",
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
        "--run-id",
        default="",
        help="Execute an existing queued run in a dedicated worker.",
    )
    parser.add_argument(
        "--worker-id",
        default="",
        help="Safe worker identifier recorded in refresh lineage.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print safe JSON payload.",
    )
    args = parser.parse_args()
    if args.run_id:
        if args.tenant or args.mode or args.dry_run or args.source_report_id:
            parser.error("--run-id cannot be combined with tenant or mode options")
    elif not args.tenant or not args.mode:
        parser.error("--tenant and --mode are required unless --run-id is used")
    return args


if __name__ == "__main__":
    sys.exit(main())
