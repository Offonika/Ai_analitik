#!/usr/bin/env python3
"""Audit local storage pressure for source refresh without deleting files."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import defaultdict
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
    settings = _settings(args)
    source_root = Path(args.source_root or settings.source_refresh_root).resolve()
    scan_roots = _scan_roots(args)
    min_free_gb = (
        max(0.0, args.min_free_gb)
        if args.min_free_gb is not None
        else max(0.0, float(settings.source_refresh_min_free_gb))
    )

    free_gb = _free_gb(source_root)
    print(f"Source refresh root: {source_root}")
    print(f"Filesystem free GiB: {free_gb:.2f}")
    print(f"Required free GiB: {min_free_gb:.2f}")
    if min_free_gb > free_gb:
        print(f"Need to free GiB: {min_free_gb - free_gb:.2f}")
    else:
        print("Need to free GiB: 0.00")

    protected = _protected_snapshot_reasons(
        source_root,
        database_url=args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or "",
        daily_keep=args.daily_keep,
        full_keep=args.full_keep,
        extra_protected=set(args.protect_snapshot_set),
    )
    reclaimable_bytes = _print_source_refresh_snapshots(source_root, protected)
    reclaimable_gb = reclaimable_bytes / (1024**3)
    print(
        "Potential free after source_refresh prune GiB: "
        f"{free_gb + reclaimable_gb:.2f}"
    )
    if min_free_gb > free_gb + reclaimable_gb:
        print(
            "Still needed after source_refresh prune GiB: "
            f"{min_free_gb - free_gb - reclaimable_gb:.2f}"
        )
    else:
        print("Still needed after source_refresh prune GiB: 0.00")
    _print_scan_roots(scan_roots, top=args.top)
    print("Health: low_disk" if min_free_gb > free_gb else "Health: ok")
    return 1 if min_free_gb > free_gb else 0


def _print_source_refresh_snapshots(
    source_root: Path,
    protected: dict[str, set[str]],
) -> int:
    print("Source refresh snapshots:")
    if not source_root.exists():
        print("- source root missing")
        return 0
    snapshots = _snapshot_dirs(source_root)
    if not snapshots:
        print("- none")
        return 0
    reclaimable_bytes = 0
    for path in snapshots:
        size = _directory_size(path)
        reasons = protected.get(path.name, set())
        if reasons:
            status = "protected: " + ", ".join(sorted(reasons))
        else:
            status = "reclaimable by prune policy"
            reclaimable_bytes += size
        print(f"- {path.name}: {_format_gib(size)} GiB, {status}")
    print(f"Source refresh reclaimable GiB: {_format_gib(reclaimable_bytes)}")
    return reclaimable_bytes


def _print_scan_roots(scan_roots: list[Path], *, top: int) -> None:
    print("Largest project directories:")
    rows: list[tuple[int, str]] = []
    for root in scan_roots:
        if not root.exists() or not root.is_dir():
            continue
        rows.append((_directory_size(root), str(root)))
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink():
                rows.append((_directory_size(child), str(child)))
    for size, path in sorted(rows, reverse=True)[: max(1, top)]:
        print(f"- {_format_gib(size)} GiB {path}")


def _scan_roots(args: argparse.Namespace) -> list[Path]:
    if args.scan_root:
        return [Path(value).resolve() for value in args.scan_root]
    return [PROJECT_ROOT / "data", PROJECT_ROOT / "reports"]


def _snapshot_dirs(source_root: Path) -> list[Path]:
    if not source_root.exists() or not source_root.is_dir():
        return []
    return sorted(
        [
            item
            for item in source_root.iterdir()
            if item.is_dir() and not item.is_symlink()
        ],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def _protected_snapshot_reasons(
    source_root: Path,
    *,
    database_url: str,
    daily_keep: int,
    full_keep: int,
    extra_protected: set[str] | None = None,
) -> dict[str, set[str]]:
    snapshots = _snapshot_dirs(source_root)
    protected: dict[str, set[str]] = defaultdict(set)
    for name in sorted(extra_protected or set()):
        if name:
            protected[name].add("explicit protection")
    for path in _latest_by_prefix(snapshots, "daily-", daily_keep):
        protected[path.name].add("daily retention")
    for path in _latest_by_prefix(snapshots, "full-", full_keep):
        protected[path.name].add("full retention")
    if database_url:
        for name, reason in _protected_from_database(database_url).items():
            protected[name].add(reason)
    return protected


def _latest_by_prefix(candidates: list[Path], prefix: str, limit: int) -> list[Path]:
    return [item for item in candidates if item.name.startswith(prefix)][
        : max(0, limit)
    ]


def _protected_from_database(database_url: str) -> dict[str, str]:
    protected: dict[str, str] = {}
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
                protected[str(value)] = "published report"
            for run in db.scalars(
                select(SourceRefreshRun).where(SourceRefreshRun.finished_at.is_(None))
            ):
                if run.snapshot_set_id:
                    protected[run.snapshot_set_id] = "active refresh"
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


def _free_gb(path: Path) -> float:
    current = path.resolve()
    while not current.exists() and current.parent != current:
        current = current.parent
    return shutil.disk_usage(current).free / (1024**3)


def _format_gib(bytes_value: int) -> str:
    return f"{bytes_value / (1024**3):.2f}"


def _settings(args: argparse.Namespace) -> WebSettings:
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    values = {"database_url": database_url} if database_url else {}
    return WebSettings(_env_file=None, **values)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--scan-root", action="append", default=[])
    parser.add_argument("--daily-keep", type=int, default=3)
    parser.add_argument("--full-keep", type=int, default=2)
    parser.add_argument("--min-free-gb", type=float, default=None)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--protect-snapshot-set", action="append", default=[])
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
