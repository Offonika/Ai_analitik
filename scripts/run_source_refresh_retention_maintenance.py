#!/usr/bin/env python3
"""Run fail-closed source-refresh retention maintenance."""

from __future__ import annotations

import argparse
import fcntl
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

DEFAULT_TIMERS = (
    "shumeiko-source-refresh-daily.timer",
    "shumeiko-source-refresh-weekly.timer",
    "shumeiko-source-refresh-watchdog.timer",
)


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def active_workers() -> list[str]:
    output = run(
        [
            "systemctl",
            "list-units",
            "--type=service",
            "--state=running,activating",
            "--no-legend",
            "--plain",
            "shumeiko-source-refresh-worker@*.service",
        ],
        capture=True,
    )
    return [line.split()[0] for line in output.splitlines() if line.split()]


def is_active(unit: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", unit],
        check=False,
    )
    return result.returncode == 0


@contextmanager
def paused_refresh_schedulers() -> object:
    active_timers = [unit for unit in DEFAULT_TIMERS if is_active(unit)]
    try:
        for unit in active_timers:
            run(["systemctl", "stop", unit])
        if is_active("shumeiko-source-refresh-watchdog.service"):
            run(["systemctl", "stop", "shumeiko-source-refresh-watchdog.service"])
        workers = active_workers()
        if workers:
            raise RuntimeError(
                "active source-refresh workers block retention: " + ", ".join(workers)
            )
        yield
    finally:
        for unit in active_timers:
            subprocess.run(["systemctl", "start", unit], check=False)


def prune_old_maintenance_bundles(root: Path, *, keep: int) -> list[Path]:
    if not root.exists():
        return []
    bundles = sorted(
        (path for path in root.iterdir() if path.is_dir() and not path.is_symlink()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    removed = bundles[max(0, keep) :]
    for path in removed:
        shutil.rmtree(path)
    return removed


def require_free_space(path: Path, minimum_bytes: int) -> None:
    free = shutil.disk_usage(path).free
    if free < minimum_bytes:
        raise RuntimeError(
            f"insufficient backup space: free={free} required={minimum_bytes}"
        )


def vacuum_retained_tables(python: Path, runtime: Path) -> None:
    code = """
import os
import psycopg
database_url = os.environ['SHUMEYKO_DATABASE_URL'].replace(
    'postgresql+psycopg://', 'postgresql://', 1
)
with psycopg.connect(database_url, autocommit=True) as connection:
    for table in (
        'source_snapshot_rows',
        'report_unit_rows',
        'report_lost_sales_rows',
        'report_marketplace_expense_rows',
        'report_document_reconciliation_rows',
        'report_runs',
    ):
        connection.execute(f'VACUUM (ANALYZE) wb_unit_economics.{table}')
print('VACUUM ANALYZE completed')
""".strip()
    run([str(python), "-c", code])


def maintenance(args: argparse.Namespace) -> None:
    runtime = args.runtime_current.resolve(strict=True)
    python = runtime / ".venv/bin/python"
    if not python.is_file():
        raise RuntimeError(f"runtime Python is missing: {python}")

    database_prune = [
        str(python),
        str(runtime / "scripts/prune_source_refresh_database.py"),
        "--source-root",
        str(args.source_root),
        "--daily-keep",
        str(args.daily_keep),
        "--full-keep",
        str(args.full_keep),
        "--grace-hours",
        str(args.grace_hours),
        "--statement-timeout-ms",
        "600000",
        "--postgres-data-path",
        "/data/postgresql/16/main",
        "--source-data-path",
        "/data",
        "--progress-every",
        "20",
        "--list-limit",
        "20",
    ]
    report_prune = [
        str(python),
        str(runtime / "scripts/prune_report_drafts.py"),
        "--tenant",
        args.tenant,
        "--reports-root",
        str(args.reports_root),
        "--keep-latest",
        str(args.report_draft_keep),
        "--grace-hours",
        str(args.report_draft_grace_hours),
        "--statement-timeout-ms",
        "600000",
        "--list-limit",
        "20",
    ]
    filesystem_prune = [
        str(python),
        str(runtime / "scripts/prune_source_refresh.py"),
        "--source-root",
        str(args.source_root),
        "--daily-keep",
        str(args.daily_keep),
        "--full-keep",
        str(args.full_keep),
        "--protect-snapshot-set",
        args.protect_snapshot_set,
    ]
    if not args.apply:
        print("Dry run: report draft retention")
        run(report_prune)
        print("Dry run: database retention")
        run(database_prune)
        print("Dry run: filesystem retention")
        run(filesystem_prune)
        print("Runtime release cleanup is disabled: deployment lock is required")
        return

    if os.geteuid() != 0:
        raise RuntimeError("--apply requires root")
    with paused_refresh_schedulers():
        if args.backup_verification is not None:
            verification_path = args.backup_verification.resolve(strict=True)
            print(f"Reusing verified maintenance backup: {verification_path}")
        else:
            backup_command = [
                str(python),
                str(runtime / "scripts/create_maintenance_backup.py"),
                "--postgres-data-path",
                "/data/postgresql/16/main",
                "--source-data-path",
                "/data",
                "--roles-system-user",
                "postgres",
            ]
            if args.s3_config is not None:
                s3_config = args.s3_config.resolve(strict=True)
                backup_command.extend(
                    [
                        "--s3-config",
                        str(s3_config),
                        "--verification-dir",
                        str(args.verification_dir),
                    ]
                )
            else:
                require_free_space(args.backup_mount, args.minimum_backup_free_bytes)
                backup_command.extend(["--backup-mount", str(args.backup_mount)])
            backup_output = run(backup_command, capture=True)
            print(backup_output)
            verification_path = Path(backup_output.splitlines()[-1]).resolve(
                strict=True
            )
        run(
            [
                *report_prune,
                "--backup-verification",
                str(verification_path),
                "--apply",
            ]
        )
        run(
            [
                *database_prune,
                "--backup-verification",
                str(verification_path),
                "--apply",
            ]
        )
        vacuum_retained_tables(python, runtime)
        run([*filesystem_prune, "--apply"])
        local_bundles_to_keep = 0 if args.s3_config is not None else 1
        removed = prune_old_maintenance_bundles(
            args.maintenance_root,
            keep=local_bundles_to_keep,
        )
        print(f"Old maintenance backup bundles removed: {len(removed)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--runtime-current",
        type=Path,
        default=Path("/opt/shumeyko-runtime/prod/current"),
    )
    parser.add_argument(
        "--source-root", type=Path, default=Path("/data/shumeyko/source_refresh")
    )
    parser.add_argument("--backup-mount", type=Path, default=Path("/"))
    parser.add_argument("--s3-config", type=Path, default=None)
    parser.add_argument("--backup-verification", type=Path, default=None)
    parser.add_argument(
        "--verification-dir",
        type=Path,
        default=Path("/var/lib/shumeiko/maintenance-backups"),
    )
    parser.add_argument(
        "--maintenance-root", type=Path, default=Path("/shumeiko-maintenance")
    )
    parser.add_argument("--minimum-backup-free-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--daily-keep", type=int, default=3)
    parser.add_argument("--full-keep", type=int, default=2)
    parser.add_argument("--grace-hours", type=int, default=24)
    parser.add_argument("--tenant", default="shumeyko")
    parser.add_argument(
        "--reports-root",
        type=Path,
        default=Path("/opt/shumeyko-partners-wb-unit-economics/reports"),
    )
    parser.add_argument("--report-draft-keep", type=int, default=1)
    parser.add_argument("--report-draft-grace-hours", type=int, default=24)
    parser.add_argument("--protect-snapshot-set", default="daily-20260712-065846")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    lock_path = Path("/run/lock/shumeiko-source-retention-maintenance.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Retention maintenance is already running", file=sys.stderr)
            return 75
        try:
            maintenance(args)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"Retention maintenance failed closed: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
