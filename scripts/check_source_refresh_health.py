# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import SOURCE_REFRESH_MODES

OK_STATUSES = {"source_loaded", "report_created", "needs_review", "dry_run_ready"}
FAILED_STATUSES = {
    "failed",
    "needs_configuration",
    "blocked_active_refresh",
    "blocked_low_disk",
    "needs_full_refresh",
}
ACTIVE_STATUSES = {"queued", "running", "source_loaded", "rebuilding"}


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    settings = (
        WebSettings(_env_file=None, database_url=database_url)
        if database_url
        else WebSettings(_env_file=None)
    )
    try:
        engine = make_engine(settings.database_url)
        session_factory = make_session_factory(engine)
        with session_factory() as db:
            refresh_run = db.scalar(
                select(SourceRefreshRun)
                .where(
                    SourceRefreshRun.tenant_id == args.tenant,
                    SourceRefreshRun.mode == args.mode,
                )
                .order_by(SourceRefreshRun.created_at.desc())
            )
            if refresh_run is None:
                print(
                    "No source refresh run for "
                    f"tenant={args.tenant} mode={args.mode}"
                )
                return 2
            active_run = db.scalar(
                select(SourceRefreshRun)
                .where(
                    SourceRefreshRun.tenant_id == args.tenant,
                    SourceRefreshRun.status.in_(ACTIVE_STATUSES),
                    SourceRefreshRun.finished_at.is_(None),
                )
                .order_by(SourceRefreshRun.created_at.desc())
            )
            return _print_and_classify(
                refresh_run,
                active_run=active_run,
                max_age_hours=args.max_age_hours,
                source_root=settings.source_refresh_root_path,
                include_systemd=args.systemd,
            )
    except SQLAlchemyError as exc:
        print(f"Source refresh health read failed: {exc.__class__.__name__}")
        return 2


def _print_and_classify(
    refresh_run: SourceRefreshRun,
    *,
    active_run: SourceRefreshRun | None,
    max_age_hours: float,
    source_root: Path,
    include_systemd: bool,
) -> int:
    age_hours = _age_hours(refresh_run)
    print(f"Source refresh: {refresh_run.id}")
    print(f"Status: {refresh_run.status}")
    print(f"Mode: {refresh_run.mode}")
    print(f"Snapshot set: {refresh_run.snapshot_set_id}")
    print(f"Period: {refresh_run.period_start} - {refresh_run.period_end}")
    print(f"Age hours: {age_hours:.2f}")
    if active_run is None:
        print("Active run: none")
    else:
        print(f"Active run: {active_run.id} ({active_run.mode}, {active_run.status})")
    free_gb = _free_gb(source_root)
    print(f"Source root free GiB: {free_gb:.2f}")
    if include_systemd:
        _print_systemd_timer_state()
    if refresh_run.new_report_run_id:
        print(f"New report: {refresh_run.new_report_run_id}")
    for item in sorted(
        refresh_run.collections,
        key=lambda value: (value.required is False, value.source_type, value.id),
    ):
        required = "required" if item.required else "optional"
        print(
            "- "
            f"{item.source_type} ({required}): "
            f"{item.status}, rows={item.row_count}"
        )

    if age_hours > max_age_hours:
        print(f"Health: stale, latest run is older than {max_age_hours:.2f}h")
        return 2
    if refresh_run.status in ACTIVE_STATUSES and refresh_run.finished_at is None:
        print("Health: refresh still active")
        return 2
    if refresh_run.status in FAILED_STATUSES:
        print("Health: failed")
        return 1
    if refresh_run.status in OK_STATUSES:
        print("Health: ok")
        return 0
    print("Health: unknown status")
    return 2


def _age_hours(refresh_run: SourceRefreshRun) -> float:
    observed_at = (
        refresh_run.finished_at or refresh_run.updated_at or refresh_run.created_at
    )
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return max((datetime.now(tz=UTC) - observed_at).total_seconds() / 3600, 0.0)


def _free_gb(path: Path) -> float:
    current = path.resolve()
    while not current.exists() and current.parent != current:
        current = current.parent
    return shutil.disk_usage(current).free / (1024**3)


def _print_systemd_timer_state() -> None:
    for unit in (
        "shumeiko-source-refresh-daily.timer",
        "shumeiko-source-refresh-weekly.timer",
    ):
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            text=True,
            capture_output=True,
            check=False,
        )
        state = (result.stdout or result.stderr).strip() or "unknown"
        print(f"Systemd {unit}: {state}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check latest source refresh health without exposing raw payloads."
    )
    parser.add_argument("--tenant", required=True, help="Tenant id, e.g. shumeyko.")
    parser.add_argument(
        "--mode",
        default="daily",
        choices=sorted(SOURCE_REFRESH_MODES),
        help="Refresh mode to inspect.",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=30.0,
        help="Maximum allowed age for the latest run.",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Database URL. Defaults to SHUMEYKO_DATABASE_URL or WebSettings.",
    )
    parser.add_argument(
        "--systemd",
        action="store_true",
        help="Also print source refresh timer active states.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
