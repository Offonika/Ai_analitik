# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings

SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
CLI_WORKER_ID = re.compile(r"^cli:(?P<pid>[1-9][0-9]*):")


def cli_worker_process_exists(worker_id: str) -> bool:
    match = CLI_WORKER_ID.match(worker_id)
    if match is None:
        return False
    process_dir = Path("/proc") / match.group("pid")
    try:
        command = (process_dir / "cmdline").read_bytes().replace(b"\0", b" ")
    except (FileNotFoundError, ProcessLookupError):
        return False
    except PermissionError:
        return process_dir.exists()
    return b"run_source_refresh.py" in command


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    settings = (
        WebSettings(_env_file=None, database_url=database_url)
        if database_url
        else WebSettings(_env_file=None)
    )
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    cutoff = security.utcnow() - timedelta(seconds=max(60, args.stale_seconds))
    with factory() as db:
        stale_runs = list(
            db.scalars(
                select(SourceRefreshRun).where(
                    or_(
                        SourceRefreshRun.worker_id.like("systemd:%"),
                        SourceRefreshRun.worker_id.like("cli:%"),
                    ),
                    SourceRefreshRun.status.in_(
                        repository.ACTIVE_SOURCE_REFRESH_STATUSES
                    ),
                    SourceRefreshRun.finished_at.is_(None),
                    SourceRefreshRun.heartbeat_at.is_not(None),
                    SourceRefreshRun.heartbeat_at < cutoff,
                )
            )
        )
    actionable_runs = [
        refresh_run
        for refresh_run in stale_runs
        if not refresh_run.worker_id.startswith("cli:")
        or not cli_worker_process_exists(refresh_run.worker_id)
    ]
    live_cli_count = len(stale_runs) - len(actionable_runs)
    print(f"Stale source refresh workers: {len(actionable_runs)}")
    if live_cli_count:
        print(f"CLI workers still alive despite stale heartbeat: {live_cli_count}")
    if not actionable_runs:
        return 0
    if not args.apply:
        print("Dry-run: worker units and database rows were not changed.")
        return 2
    for stale_run in actionable_runs:
        refresh_run_id = stale_run.id
        if not SAFE_RUN_ID.fullmatch(refresh_run_id):
            continue
        if stale_run.worker_id.startswith("systemd:"):
            unit = (
                f"{settings.source_refresh_worker_unit_prefix}"
                f"@{refresh_run_id}.service"
            )
            subprocess.run(
                ["systemctl", "stop", unit],
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
        with factory() as db:
            refresh_run = db.get(SourceRefreshRun, refresh_run_id)
            if refresh_run is None or refresh_run.finished_at is not None:
                continue
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="failed",
                failure_code="worker_heartbeat_stale",
                error_message="Source refresh worker heartbeat expired.",
                finished_at=security.utcnow(),
            )
            repository.audit(
                db,
                action="source_refresh_worker_stale",
                user=None,
                tenant_id=refresh_run.tenant_id,
                entity_type="source_refresh_run",
                entity_id=refresh_run.id,
                payload={
                    "workerAssigned": True,
                    "workerType": (
                        "cli"
                        if stale_run.worker_id.startswith("cli:")
                        else "systemd"
                    ),
                },
            )
            db.commit()
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect and stop source refresh workers with stale heartbeat."
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument("--stale-seconds", type=int, default=300)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
