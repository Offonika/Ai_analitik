from __future__ import annotations

import os
import runpy
import subprocess
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from scripts.build_runtime_release import (
    RELEASE_SITE_MODULE,
    RELEASE_SITE_PTH,
    _install_release_source_bootstrap,
)
from scripts.prepare_test_database import (
    _delete_raw_snapshot_rows,
    _safe_current_source,
)
from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
)

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_release_bootstrap_prefers_its_own_source(tmp_path: Path) -> None:
    release = tmp_path / "runtime-release"
    site_packages = release / ".venv/lib/python3.12/site-packages"
    release_src = release / "src"
    site_packages.mkdir(parents=True)
    release_src.mkdir()

    bootstrap_hash = _install_release_source_bootstrap(release / ".venv")

    module = site_packages / RELEASE_SITE_MODULE
    pth = site_packages / RELEASE_SITE_PTH
    assert len(bootstrap_hash) == 64
    assert pth.read_text(encoding="utf-8") == "import shumeyko_release_site\n"
    original = list(sys.path)
    try:
        runpy.run_path(module)
        assert Path(sys.path[0]).resolve() == release_src.resolve()
    finally:
        sys.path[:] = original


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def test_runtime_env_generator_removes_production_secrets_from_test(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.env"
    production = tmp_path / "production.env"
    test = tmp_path / "test.env"
    source.write_text(
        "\n".join(
            (
                'SHUMEYKO_DATABASE_URL="postgresql+psycopg://app:db-secret@db/prod"',
                'SHUMEYKO_SESSION_SECRET="session-secret"',
                'SHUMEYKO_BOOTSTRAP_PASSWORD="bootstrap-secret"',
                'SHUMEYKO_INTEGRATION_SECRET_KEY="integration-secret"',
                'SHUMEYKO_OPENAI_API_KEY="openai-secret"',
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts/create_runtime_env_files.py"),
            "--source",
            str(source),
            "--production-output",
            str(production),
            "--test-output",
            str(test),
            "--apply",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    production_values = _read_env(production)
    test_values = _read_env(test)
    assert production_values["SHUMEYKO_BOOTSTRAP_PASSWORD"] == "bootstrap-secret"
    assert test_values["SHUMEYKO_BOOTSTRAP_PASSWORD"] == ""
    assert test_values["SHUMEYKO_INTEGRATION_SECRET_KEY"] == ""
    assert test_values["SHUMEYKO_OPENAI_API_KEY"] == ""
    assert test_values["ONEC_ODATA_PASSWORD"] == ""
    assert test_values["SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED"] == "false"
    assert test_values["SHUMEYKO_CLIENT_LOGIN_ENABLED"] == "false"
    assert test_values["SHUMEYKO_DATABASE_URL"].endswith(
        "/shumeyko_web_cabinet_test"
    )
    assert test_values["SHUMEYKO_SESSION_SECRET"] != "session-secret"
    assert production.stat().st_mode & 0o777 == 0o600
    assert test.stat().st_mode & 0o777 == 0o600


def test_runtime_env_generator_accepts_separate_test_database_role(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.env"
    production = tmp_path / "production.env"
    test = tmp_path / "test.env"
    source.write_text(
        'SHUMEYKO_DATABASE_URL="postgresql+psycopg://prod-app:placeholder@db/prod"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts/create_runtime_env_files.py"),
            "--source",
            str(source),
            "--production-output",
            str(production),
            "--test-output",
            str(test),
            "--apply",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SHUMEYKO_TEST_DATABASE_URL": (
                "postgresql+psycopg://test-app:placeholder@db/"
                "shumeyko_web_cabinet_test"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "placeholder" not in result.stdout
    test_values = _read_env(test)
    assert test_values["SHUMEYKO_DATABASE_URL"].startswith(
        "postgresql+psycopg://test-app:"
    )
    assert test_values["SHUMEYKO_DATABASE_URL"].endswith(
        "/shumeyko_web_cabinet_test"
    )


def test_test_database_sanitizer_reuses_safe_test_artifact(
    tmp_path: Path,
) -> None:
    production_root = tmp_path / "production"
    test_root = tmp_path / "test"
    production_root.mkdir()
    test_root.mkdir()
    test_artifact = test_root / "report" / "workbook-report.xlsx"
    test_artifact.parent.mkdir()
    test_artifact.write_bytes(b"safe-test-artifact")

    source, already_in_test = _safe_current_source(
        str(test_artifact),
        production_root,
        test_root,
    )

    assert source == test_artifact.resolve()
    assert already_in_test is True


def test_test_database_sanitizer_deletes_raw_snapshot_rows(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'clone_test.sqlite3'}")
    init_db(engine)
    factory = make_session_factory(engine)
    now = security.utcnow()
    with factory() as db:
        repository.ensure_tenant(db, "tenant", "Tenant")
        refresh = SourceRefreshRun(
            id="refresh-1",
            tenant_id="tenant",
            client_id="client",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            status="completed",
            reason="fixture",
            snapshot_set_id="snapshot-set",
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            root_dir="",
            workbook_path="",
            error_message="",
            created_at=now,
            updated_at=now,
        )
        collection = SourceRefreshCollection(
            refresh_run=refresh,
            tenant_id="tenant",
            client_id="client",
            source_type="raw_fixture",
            source_label="raw_fixture",
            required=True,
            status="loaded",
            row_count=1,
            loaded_at=now,
        )
        db.add_all((refresh, collection))
        db.flush()
        db.add(
            SourceSnapshotRow(
                refresh_run_id=refresh.id,
                collection_id=collection.id,
                tenant_id="tenant",
                client_id="client",
                source_type="raw_fixture",
                source_label="raw_fixture",
                source_row_id="row-1",
                row_number=1,
                raw_payload_hash="hash",
                row_payload={"raw": "must-not-survive-clone"},
                loaded_at=now,
            )
        )
        db.flush()

        deleted = _delete_raw_snapshot_rows(db)
        db.commit()

        assert deleted == 1
        assert db.scalar(select(func.count()).select_from(SourceSnapshotRow)) == 0
