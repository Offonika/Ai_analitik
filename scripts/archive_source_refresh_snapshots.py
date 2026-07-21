# ruff: noqa: E402
from __future__ import annotations

import argparse
import fcntl
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import func, select

from wb_unit_economics.snapshot_archive import archive_snapshot, restore_snapshot
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun


def main() -> int:
    args = _parse_args()
    lock_path = Path("/run/lock/shumeiko-snapshot-archive.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Snapshot archive is already running", file=sys.stderr)
            return 2
        if args.command == "restore":
            restored = restore_snapshot(
                Path(args.receipt),
                source_root=Path(args.source_root),
                s3_config_path=Path(args.s3_config),
            )
            print(f"Restored snapshot: {restored.name}")
            return 0
        snapshots = [Path(value) for value in getattr(args, "snapshot", [])]
        if args.command == "archive-eligible":
            _assert_no_active_refresh()
            snapshots = _eligible(args)
        if not snapshots:
            print("Archive candidates: 0")
            return 0
        print(f"Archive candidates: {len(snapshots)}")
        if not args.apply:
            for item in snapshots:
                print(f"- would archive: {item.name}")
            return 0
        for item in snapshots:
            receipt = archive_snapshot(
                item,
                source_root=Path(args.source_root),
                receipt_dir=Path(args.receipt_dir),
                verify_dir=Path(args.verify_dir),
                s3_config_path=Path(args.s3_config),
                prefix=args.prefix,
                evict=args.evict,
                pre_evict_check=_assert_no_active_refresh if args.evict else None,
            )
            print(f"Archived snapshot: {item.name}; receipt={receipt}")
        return 0


def _eligible(args: argparse.Namespace) -> list[Path]:
    root = Path(args.source_root).resolve(strict=True)
    now = datetime.now().timestamp()
    candidates = [
        item
        for item in root.iterdir()
        if item.is_dir()
        and not item.is_symlink()
        and not item.name.startswith(".")
        and now - item.stat().st_mtime >= args.min_age_hours * 3600
    ]
    newest = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)
    protected = {
        item.name
        for item in [x for x in newest if x.name.startswith("daily-")][
            : args.keep_daily
        ]
    }
    protected.update(
        item.name
        for item in [x for x in newest if x.name.startswith("full-")][: args.keep_full]
    )
    selected = [item for item in reversed(newest) if item.name not in protected]
    return selected[: args.max_snapshots]


def _assert_no_active_refresh() -> None:
    database_url = os.getenv("SHUMEYKO_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("SHUMEYKO_DATABASE_URL is required for eligible archival")
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        active = int(
            db.scalar(
                select(func.count(SourceRefreshRun.id)).where(
                    SourceRefreshRun.finished_at.is_(None)
                )
            )
            or 0
        )
    engine.dispose()
    if active:
        raise RuntimeError("active source refresh blocks snapshot archival")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive source refresh snapshots to versioned S3"
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--source-root", default="/data/shumeyko/source_refresh")
    common.add_argument("--s3-config", default="/root/.config/shumeyko/s3-backup.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    archive = subparsers.add_parser("archive", parents=[common])
    archive.add_argument("--snapshot", action="append", required=True)
    _archive_options(archive)
    eligible = subparsers.add_parser("archive-eligible", parents=[common])
    _archive_options(eligible)
    eligible.add_argument("--min-age-hours", type=int, default=48)
    eligible.add_argument("--keep-daily", type=int, default=3)
    eligible.add_argument("--keep-full", type=int, default=2)
    eligible.add_argument("--max-snapshots", type=int, default=1)
    restore = subparsers.add_parser("restore", parents=[common])
    restore.add_argument("--receipt", required=True)
    return parser.parse_args()


def _archive_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--receipt-dir", default="/var/lib/shumeyko/source-archive-receipts"
    )
    parser.add_argument("--verify-dir", default="/data/shumeyko/.source-archive-verify")
    parser.add_argument("--prefix", default="source-refresh-snapshots")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--evict", action="store_true")


if __name__ == "__main__":
    raise SystemExit(main())
