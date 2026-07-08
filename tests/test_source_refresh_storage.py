from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_source_refresh_storage_audit_marks_reclaimable_snapshots(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source_refresh"
    root.mkdir()
    _snapshot_dir(root / "full-20260620-001500", mtime=1, payload="old")
    _snapshot_dir(root / "full-20260624-001500", mtime=2, payload="new")

    result = _run_storage(
        root,
        "--full-keep",
        "1",
        "--daily-keep",
        "0",
        "--min-free-gb",
        "0",
        "--scan-root",
        str(tmp_path),
    )

    assert result.returncode == 0
    assert "full-20260624-001500" in result.stdout
    assert "protected: full retention" in result.stdout
    assert "full-20260620-001500" in result.stdout
    assert "reclaimable by prune policy" in result.stdout
    assert "Potential free after source_refresh prune GiB:" in result.stdout
    assert "Health: ok" in result.stdout
    assert (root / "full-20260620-001500").exists()


def test_source_refresh_storage_audit_reports_low_disk_without_delete(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source_refresh"
    root.mkdir()
    _snapshot_dir(root / "full-20260624-001500", mtime=1, payload="new")

    result = _run_storage(
        root,
        "--full-keep",
        "1",
        "--min-free-gb",
        "1000000",
        "--scan-root",
        str(tmp_path),
    )

    assert result.returncode == 1
    assert "Need to free GiB:" in result.stdout
    assert "Still needed after source_refresh prune GiB:" in result.stdout
    assert "Health: low_disk" in result.stdout
    assert (root / "full-20260624-001500").exists()


def test_source_refresh_storage_audit_marks_explicit_protection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source_refresh"
    root.mkdir()
    _snapshot_dir(root / "full-20260620-001500", mtime=1, payload="old")

    result = _run_storage(
        root,
        "--full-keep",
        "0",
        "--daily-keep",
        "0",
        "--protect-snapshot-set",
        "full-20260620-001500",
        "--min-free-gb",
        "0",
        "--scan-root",
        str(tmp_path),
    )

    assert result.returncode == 0
    assert "full-20260620-001500" in result.stdout
    assert "protected: explicit protection" in result.stdout


def _snapshot_dir(path: Path, *, mtime: int, payload: str) -> None:
    path.mkdir()
    (path / "payload.json").write_text(payload, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _run_storage(root: Path, *args: str):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("SHUMEYKO_DATABASE_URL", None)
    return subprocess.run(
        [
            sys.executable,
            "scripts/check_source_refresh_storage.py",
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
