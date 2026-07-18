#!/usr/bin/env python3
"""Atomically point a runtime contour at a verified immutable release."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from wb_unit_economics.runtime_release_lock import (
    DEFAULT_RUNTIME_RELEASE_LOCK,
    exclusive_runtime_release_lock,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("prod", "test"), required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("/opt/shumeyko-runtime"),
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=Path("/opt/shumeyko-releases"),
    )
    parser.add_argument(
        "--lock-path", type=Path, default=DEFAULT_RUNTIME_RELEASE_LOCK
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with exclusive_runtime_release_lock(args.lock_path):
            return _promote_release(args)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


def _promote_release(args: argparse.Namespace) -> int:
    release = args.release_dir.resolve()
    release_root = args.release_root.resolve()
    if not release.is_relative_to(release_root):
        raise SystemExit("Release is outside the allowed release root")
    manifest_path = release / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sourceDirty") is not False:
        raise SystemExit("Refusing to promote a dirty release")
    if not manifest.get("sourceCommit") or not manifest.get("contentSha256"):
        raise SystemExit("Release manifest is incomplete")

    runtime_root = args.runtime_root.resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_root.chmod(0o711)
    contour_dir = runtime_root / args.environment
    contour_dir.mkdir(parents=True, exist_ok=True)
    contour_dir.chmod(0o711)
    target = contour_dir / "current"
    temporary = contour_dir / ".current-next"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release, target_is_directory=True)
    os.replace(temporary, target)
    print(
        f"environment={args.environment} release={release} "
        f"sourceCommit={manifest['sourceCommit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
