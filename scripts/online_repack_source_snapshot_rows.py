#!/usr/bin/env python3
"""Safely online-repack the pruned source_snapshot_rows relation."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.maintenance_safety import (
    BackupVerificationError,
    verify_backup_bundle,
)
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun, SourceSnapshotRow

ACTIVE_STATUSES = {"queued", "running", "source_loaded", "rebuilding"}
RELATION = "wb_unit_economics.source_snapshot_rows"
TIMER_UNITS = (
    "shumeiko-source-refresh-daily.timer",
    "shumeiko-source-refresh-weekly.timer",
    "shumeiko-source-refresh-watchdog.timer",
)


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        raise SystemExit("SHUMEYKO_DATABASE_URL is required")
    try:
        verification = verify_backup_bundle(
            Path(args.backup_verification),
            max_age_hours=args.backup_max_age_hours,
            postgres_data_path=Path(args.postgres_data_path),
            source_data_path=Path(args.data_path),
        )
    except BackupVerificationError as exc:
        raise SystemExit(str(exc)) from exc
    _check_timers_stopped()
    if shutil.which("pg_repack") is None:
        raise SystemExit(
            "pg_repack is not installed; install postgresql-16-repack first"
        )

    engine = make_engine(database_url, statement_timeout_ms=0)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        active = int(
            db.scalar(
                select(func.count())
                .select_from(SourceRefreshRun)
                .where(
                    SourceRefreshRun.status.in_(ACTIVE_STATUSES),
                    SourceRefreshRun.finished_at.is_(None),
                )
            )
            or 0
        )
        rows = int(db.scalar(select(func.count()).select_from(SourceSnapshotRow)) or 0)
        sizes = db.execute(
            text(
                "SELECT pg_total_relation_size(:relation), "
                "pg_relation_size(:relation), pg_indexes_size(:relation)"
            ),
            {"relation": RELATION},
        ).one()
    if active:
        raise SystemExit(f"active source refresh runs: {active}")

    relation_bytes = int(sizes[0])
    free_bytes = shutil.disk_usage(args.postgres_data_path).free
    estimated_live_bytes = max(
        int(relation_bytes * min(1, rows / max(1, args.baseline_rows))),
        1,
    )
    required_bytes = max(30 * 1024**3, int(estimated_live_bytes * 1.5))
    print(f"databaseBackup={verification.database_dump_location}")
    print(f"rolesBackup={verification.roles_dump_location}")
    print(f"rows={rows}")
    print(f"relationBytes={relation_bytes}")
    print(f"freeBytes={free_bytes}")
    print(f"requiredBytes={required_bytes}")
    if free_bytes < required_bytes:
        raise SystemExit("not enough free space for online repack")
    if not args.apply:
        print("Dry run only. Re-run with --apply after reviewing the preflight.")
        return 0

    command, env = _pg_repack_command(
        database_url,
        system_user=args.postgres_system_user,
    )
    create_extension, admin_env = _postgres_admin_command(
        database_url,
        sql="CREATE EXTENSION IF NOT EXISTS pg_repack",
        system_user=args.postgres_system_user,
    )
    drop_extension, _ = _postgres_admin_command(
        database_url,
        sql="DROP EXTENSION IF EXISTS pg_repack",
        system_user=args.postgres_system_user,
    )
    subprocess.run(create_extension, env=admin_env, check=True)
    try:
        subprocess.run(command, env=env, check=True)
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f"VACUUM (ANALYZE) {RELATION}"))
    finally:
        subprocess.run(drop_extension, env=admin_env, check=True)
    print("Online repack completed.")
    return 0


def _check_timers_stopped() -> None:
    for unit in TIMER_UNITS:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() == "active":
            raise SystemExit(f"refresh timer is still active: {unit}")


def _pg_repack_command(
    database_url: str,
    *,
    system_user: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("pg_repack requires PostgreSQL")
    database = parsed.path.lstrip("/")
    executable = shutil.which("pg_repack") or "pg_repack"
    command = [
        executable,
        "--dbname",
        database,
        "--table",
        RELATION,
        "--wait-timeout",
        "60",
        "--no-kill-backend",
        "--no-order",
    ]
    if system_user:
        command[:0] = ["sudo", "-u", system_user]
    elif parsed.hostname:
        command.extend(["--host", parsed.hostname])
    if parsed.port:
        command.extend(["--port", str(parsed.port)])
    if parsed.username and not system_user:
        command.extend(["--username", unquote(parsed.username)])
    env = os.environ.copy()
    if parsed.password and not system_user:
        env["PGPASSWORD"] = unquote(parsed.password)
    elif system_user:
        env.pop("PGPASSWORD", None)
    return command, env


def _postgres_admin_command(
    database_url: str,
    *,
    sql: str,
    system_user: str,
) -> tuple[list[str], dict[str, str]]:
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("PostgreSQL admin command requires PostgreSQL")
    database = parsed.path.lstrip("/")
    executable = shutil.which("psql") or "psql"
    command = [
        "sudo",
        "-u",
        system_user,
        executable,
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "--dbname",
        database,
    ]
    if parsed.port:
        command.extend(["--port", str(parsed.port)])
    command.extend(["--command", sql])
    env = os.environ.copy()
    env.pop("PGPASSWORD", None)
    return command, env


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--backup-verification", required=True)
    parser.add_argument("--backup-max-age-hours", type=int, default=24)
    parser.add_argument("--data-path", default="/data")
    parser.add_argument("--postgres-data-path", default="/var/lib/postgresql")
    parser.add_argument("--postgres-system-user", default="postgres")
    parser.add_argument("--baseline-rows", type=int, default=12_670_414)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
