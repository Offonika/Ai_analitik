from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_prune_source_refresh_dry_run_and_apply(tmp_path: Path) -> None:
    root = tmp_path / "source_refresh"
    root.mkdir()
    _snapshot_dir(root / "daily-20260622-001500", mtime=1)
    _snapshot_dir(root / "daily-20260623-001500", mtime=2)
    _snapshot_dir(root / "full-20260620-001500", mtime=3)
    _snapshot_dir(root / "full-20260624-001500", mtime=4)

    dry_run = _run_prune(
        root,
        "--daily-keep",
        "1",
        "--full-keep",
        "1",
    )
    assert dry_run.returncode == 0
    assert "Dry run only" in dry_run.stdout
    assert (root / "daily-20260622-001500").exists()
    assert (root / "full-20260620-001500").exists()

    applied = _run_prune(
        root,
        "--daily-keep",
        "1",
        "--full-keep",
        "1",
        "--apply",
    )
    assert applied.returncode == 0
    assert not (root / "daily-20260622-001500").exists()
    assert (root / "daily-20260623-001500").exists()
    assert not (root / "full-20260620-001500").exists()
    assert (root / "full-20260624-001500").exists()


def test_prune_source_refresh_keeps_explicitly_protected_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source_refresh"
    root.mkdir()
    _snapshot_dir(root / "daily-20260622-001500", mtime=1)
    _snapshot_dir(root / "daily-20260623-001500", mtime=2)

    applied = _run_prune(
        root,
        "--daily-keep",
        "0",
        "--full-keep",
        "0",
        "--protect-snapshot-set",
        "daily-20260622-001500",
        "--apply",
    )

    assert applied.returncode == 0
    assert (root / "daily-20260622-001500").exists()
    assert not (root / "daily-20260623-001500").exists()


def _snapshot_dir(path: Path, *, mtime: int) -> None:
    path.mkdir()
    (path / "payload.json").write_text("{}", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _run_prune(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SHUMEYKO_DATABASE_URL", None)
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/prune_source_refresh.py",
            "--source-root",
            str(root),
            *args,
        ],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
