from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from scripts import run_source_refresh
from scripts.run_source_refresh import _settings_from_args
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.repository import ensure_tenant


def test_run_source_refresh_cli_help_loads_from_project_root() -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/run_source_refresh.py", "--help"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--tenant" in result.stdout
    assert "--mode" in result.stdout
    assert "--dry-run" in result.stdout


def test_run_source_refresh_cli_reports_missing_tenant_without_traceback(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_source_refresh.py",
            "--tenant",
            "missing",
            "--mode",
            "full",
            "--dry-run",
            "--database-url",
            f"sqlite:///{tmp_path / 'source-refresh.sqlite3'}",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "tenant not found: missing" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_run_source_refresh_cli_settings_ignore_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHUMEYKO_DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "SHUMEYKO_DATABASE_URL=sqlite:///should-not-be-used.sqlite3\n",
        encoding="utf-8",
    )

    settings = _settings_from_args(argparse.Namespace(database_url=""))

    assert settings.database_url == "sqlite:///data/web/shumeyko_web.sqlite3"


def test_run_source_refresh_cli_skips_startup_backfill(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def commit(self) -> None:
            return None

    class _Service:
        def __init__(self, _settings) -> None:
            return None

        def run(self, *_args, **_kwargs):
            return {
                "id": "source_refresh_test",
                "status": "blocked_low_disk",
                "mode": "daily",
                "snapshotSetId": "snapshot_test",
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-01",
                "collections": [],
            }

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_source_refresh.py",
            "--tenant",
            "shumeyko",
            "--mode",
            "daily",
            "--database-url",
            "sqlite:///:memory:",
        ],
    )
    monkeypatch.setattr(run_source_refresh, "make_engine", lambda _url: object())
    monkeypatch.setattr(
        run_source_refresh,
        "init_db",
        lambda _engine, **kwargs: calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        run_source_refresh,
        "make_session_factory",
        lambda _engine: _Session,
    )
    monkeypatch.setattr(run_source_refresh, "SourceRefreshService", _Service)

    assert run_source_refresh.main() == 0
    assert calls == [{"run_backfill": False}]


def test_run_source_refresh_cli_reports_missing_source_report_without_run(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_source_refresh.py",
            "--tenant",
            "shumeyko",
            "--mode",
            "full",
            "--dry-run",
            "--source-report-id",
            "missing-report",
            "--database-url",
            f"sqlite:///{tmp_path / 'source-refresh.sqlite3'}",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "source report not found: missing-report" in result.stderr
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_run_source_refresh_cli_returns_zero_for_controlled_low_disk_block(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'source-refresh.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        ensure_tenant(db, "shumeyko", "Шумейко и Партнеры")
        db.commit()
    env = os.environ.copy()
    env.update(
        {
            "SHUMEYKO_SOURCE_REFRESH_ENABLED": "true",
            "SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB": "1000000",
            "SHUMEYKO_SOURCE_REFRESH_ROOT": str(tmp_path / "source_refresh"),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_source_refresh.py",
            "--tenant",
            "shumeyko",
            "--mode",
            "daily",
            "--database-url",
            database_url,
        ],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "blocked_low_disk" in result.stdout
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_run_source_refresh_cli_returns_zero_for_controlled_configuration_block(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'source-refresh.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        ensure_tenant(db, "shumeyko", "Шумейко и Партнеры")
        db.commit()
    env = os.environ.copy()
    env.update(
        {
            "SHUMEYKO_SOURCE_REFRESH_ENABLED": "true",
            "SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB": "0",
            "SHUMEYKO_SOURCE_REFRESH_ROOT": str(tmp_path / "source_refresh"),
            "SHUMEYKO_SOURCE_REFRESH_MAPPING_DIR": str(tmp_path / "mapping"),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_source_refresh.py",
            "--tenant",
            "shumeyko",
            "--mode",
            "daily",
            "--database-url",
            database_url,
        ],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "needs_configuration" in result.stdout
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout
