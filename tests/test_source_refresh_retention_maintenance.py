from __future__ import annotations

import importlib.util
import os
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_source_refresh_retention_maintenance.py"
)
SPEC = importlib.util.spec_from_file_location("retention_maintenance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)


def test_prune_old_maintenance_bundles_keeps_newest(tmp_path: Path) -> None:
    bundles: list[Path] = []
    for index in range(3):
        path = tmp_path / f"bundle-{index}"
        path.mkdir()
        os.utime(path, (index + 1, index + 1))
        bundles.append(path)

    removed = maintenance.prune_old_maintenance_bundles(tmp_path, keep=1)

    assert removed == list(reversed(bundles[:2]))
    assert bundles[-1].exists()
    assert not bundles[0].exists()
    assert not bundles[1].exists()


def test_prune_old_maintenance_bundles_can_remove_all(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    removed = maintenance.prune_old_maintenance_bundles(tmp_path, keep=0)

    assert removed == [bundle]
    assert not bundle.exists()


def test_parse_args_accepts_s3_config() -> None:
    args = maintenance.parse_args(
        ["--apply", "--s3-config", "/root/.config/shumeyko/s3-backup.json"]
    )

    assert args.apply is True
    assert args.s3_config == Path("/root/.config/shumeyko/s3-backup.json")


def test_dry_run_checks_report_drafts_before_raw_and_filesystem(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime = tmp_path / "runtime"
    python = runtime / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        maintenance,
        "run",
        lambda command, capture=False: calls.append(command) or "",
    )
    args = maintenance.parse_args(
        [
            "--runtime-current",
            str(runtime),
            "--reports-root",
            str(tmp_path / "reports"),
        ]
    )

    maintenance.maintenance(args)

    assert calls[0][1].endswith("scripts/prune_report_drafts.py")
    assert calls[1][1].endswith("scripts/prune_source_refresh_database.py")
    assert calls[2][1].endswith("scripts/prune_source_refresh.py")
    assert calls[3][1].endswith("scripts/prune_runtime_releases.py")
