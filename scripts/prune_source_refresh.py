# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun, SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings


def main() -> int:
    args = _parse_args()
    settings = _settings_from_args(args)
    source_root = Path(args.source_root or settings.source_refresh_root).resolve()
    if not source_root.exists():
        print(f"Source refresh root does not exist: {source_root}")
        return 0
    if not source_root.is_dir():
        print(f"Source refresh root is not a directory: {source_root}", file=sys.stderr)
        return 2

    candidates = _snapshot_dirs(source_root)
    protected = _protected_snapshot_names(
        candidates,
        database_url=args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or "",
        daily_keep=args.daily_keep,
        full_keep=args.full_keep,
        extra_protected=set(args.protect_snapshot_set),
    )
    deletable = [item for item in candidates if item.name not in protected]
    print(f"Source refresh root: {source_root}")
    print(f"Directories: {len(candidates)}")
    print(f"Protected: {len(protected)}")
    print(f"Delete candidates: {len(deletable)}")
    for path in deletable:
        size = _directory_size(path)
        action = "delete" if args.apply else "would delete"
        print(f"- {action}: {path.name} ({size} bytes)")
        if args.apply:
            if path.is_symlink() or not _is_child(path, source_root):
                print(f"  skipped unsafe path: {path}", file=sys.stderr)
                continue
            shutil.rmtree(path)
    if not args.apply:
        print("Dry run only. Re-run with --apply to delete candidates.")
    return 0


def _settings_from_args(args: argparse.Namespace) -> WebSettings:
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    if database_url:
        return WebSettings(_env_file=None, database_url=database_url)
    return WebSettings(_env_file=None)


def _snapshot_dirs(source_root: Path) -> list[Path]:
    return sorted(
        [
            item
            for item in source_root.iterdir()
            if item.is_dir() and not item.is_symlink()
        ],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def _protected_snapshot_names(
    candidates: list[Path],
    *,
    database_url: str,
    daily_keep: int,
    full_keep: int,
    extra_protected: set[str] | None = None,
) -> set[str]:
    protected: set[str] = set()
    protected.update(value for value in (extra_protected or set()) if value)
    protected.update(
        path.name for path in _latest_by_prefix(candidates, "daily-", daily_keep)
    )
    protected.update(
        path.name for path in _latest_by_prefix(candidates, "full-", full_keep)
    )
    if database_url:
        protected.update(_protected_from_database(database_url))
    return protected


def _latest_by_prefix(candidates: list[Path], prefix: str, limit: int) -> list[Path]:
    return [item for item in candidates if item.name.startswith(prefix)][
        : max(0, limit)
    ]


def _protected_from_database(database_url: str) -> set[str]:
    protected: set[str] = set()
    try:
        engine = make_engine(database_url)
        session_factory = make_session_factory(engine)
        with session_factory() as db:
            for value in db.scalars(
                select(ReportRun.source_snapshot_set_id).where(
                    ReportRun.publication_status == "published",
                    ReportRun.source_snapshot_set_id != "",
                )
            ):
                protected.add(str(value))
            for run in db.scalars(
                select(SourceRefreshRun).where(SourceRefreshRun.finished_at.is_(None))
            ):
                if run.snapshot_set_id:
                    protected.add(run.snapshot_set_id)
    except SQLAlchemyError as exc:
        print(
            f"Database protection read failed: {exc.__class__.__name__}",
            file=sys.stderr,
        )
    return protected


def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


def _is_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune old local source_refresh raw snapshot directories."
    )
    parser.add_argument(
        "--source-root",
        default="",
        help="Source refresh root. Defaults to SHUMEYKO_SOURCE_REFRESH_ROOT setting.",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Database URL used only to protect published/current snapshots.",
    )
    parser.add_argument(
        "--daily-keep",
        type=int,
        default=3,
        help="Number of newest daily-* directories to protect.",
    )
    parser.add_argument(
        "--full-keep",
        type=int,
        default=2,
        help="Number of newest full-* directories to protect.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete candidates. Default is dry-run.",
    )
    parser.add_argument(
        "--protect-snapshot-set",
        action="append",
        default=[],
        help="Snapshot set id to keep even if it is outside retention.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
