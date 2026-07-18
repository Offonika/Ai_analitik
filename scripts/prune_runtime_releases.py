#!/usr/bin/env python3
"""Prune inactive immutable runtime releases under the shared deploy lock."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wb_unit_economics.runtime_release_lock import (
    DEFAULT_RUNTIME_RELEASE_LOCK,
    exclusive_runtime_release_lock,
)


@dataclass(frozen=True)
class ReleaseInfo:
    path: Path
    modified_at: datetime
    complete: bool


def select_release_candidates(
    releases: list[ReleaseInfo],
    *,
    active_paths: set[Path],
    keep_latest: int,
    cutoff: datetime,
) -> tuple[list[ReleaseInfo], set[Path]]:
    """Return old inactive candidates and protected rollback paths."""

    inactive_complete = sorted(
        (item for item in releases if item.complete and item.path not in active_paths),
        key=lambda item: (item.modified_at, item.path.name),
        reverse=True,
    )
    rollback_paths = {item.path for item in inactive_complete[: max(0, keep_latest)]}
    candidates = [
        item
        for item in releases
        if item.path not in active_paths
        and item.path not in rollback_paths
        and item.modified_at < cutoff
    ]
    return sorted(candidates, key=lambda item: item.path.name), rollback_paths


def _load_complete_release(path: Path) -> bool:
    manifest_path = path / "release-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid immutable release manifest: {path}") from exc
    if (
        manifest.get("sourceDirty") not in (False, True)
        or not manifest.get("sourceCommit")
        or not manifest.get("contentSha256")
    ):
        raise RuntimeError(f"incomplete immutable release manifest: {path}")
    return manifest["sourceDirty"] is False


def _active_release_paths(release_root: Path, runtime_root: Path) -> set[Path]:
    active: set[Path] = set()
    for environment in ("prod", "test"):
        pointer = runtime_root / environment / "current"
        if not pointer.is_symlink():
            raise RuntimeError(f"runtime pointer is not a symlink: {pointer}")
        target = pointer.resolve(strict=True)
        if target.parent != release_root or not target.is_dir():
            raise RuntimeError(f"runtime pointer leaves release root: {pointer}")
        active.add(target)
    return active


def inspect_releases(
    release_root: Path,
    runtime_root: Path,
) -> tuple[list[ReleaseInfo], set[Path]]:
    root = release_root.resolve(strict=True)
    runtime = runtime_root.resolve(strict=True)
    active = _active_release_paths(root, runtime)
    releases: list[ReleaseInfo] = []
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(f"unexpected release-root entry: {path}")
        if path.name.startswith("runtime-"):
            complete = _load_complete_release(path)
        elif path.name.startswith(".runtime-"):
            complete = False
        else:
            raise RuntimeError(f"unexpected release directory: {path}")
        releases.append(
            ReleaseInfo(
                path=path,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
                complete=complete,
            )
        )
    if not active.issubset({item.path for item in releases}):
        raise RuntimeError("an active runtime release is absent from inventory")
    if any(item.path in active and not item.complete for item in releases):
        raise RuntimeError("an active runtime release is not immutable")
    return releases, active


def _tree_size(path: Path) -> int:
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            entry = Path(root) / name
            if not entry.is_symlink():
                total += entry.stat().st_size
    return total


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-root", type=Path, default=Path("/opt/shumeyko-releases")
    )
    parser.add_argument(
        "--runtime-root", type=Path, default=Path("/opt/shumeyko-runtime")
    )
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_RUNTIME_RELEASE_LOCK)
    parser.add_argument("--keep-latest", type=int, default=1)
    parser.add_argument("--grace-hours", type=int, default=24)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.keep_latest < 1:
        raise SystemExit("--keep-latest must be at least 1")
    if args.grace_hours < 0:
        raise SystemExit("--grace-hours cannot be negative")
    if args.apply and os.geteuid() != 0:
        raise SystemExit("--apply requires root")

    try:
        with exclusive_runtime_release_lock(args.lock_path):
            releases, active = inspect_releases(
                args.release_root,
                args.runtime_root,
            )
            cutoff = datetime.now(UTC) - timedelta(hours=args.grace_hours)
            candidates, rollback = select_release_candidates(
                releases,
                active_paths=active,
                keep_latest=args.keep_latest,
                cutoff=cutoff,
            )
            candidate_bytes = sum(_tree_size(item.path) for item in candidates)
            print(f"Runtime releases inspected: {len(releases)}")
            print(f"Active releases protected: {len(active)}")
            print(f"Rollback releases protected: {len(rollback)}")
            print(f"Delete candidates: {len(candidates)}")
            print(f"Candidate bytes: {candidate_bytes}")
            if not args.apply:
                print("Dry run only. Re-run with --apply to delete candidates.")
                return 0
            for item in candidates:
                shutil.rmtree(item.path)
            print(f"Runtime releases deleted: {len(candidates)}")
            print(f"Deleted bytes: {candidate_bytes}")
    except (OSError, RuntimeError) as exc:
        print(f"Runtime release retention failed closed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
