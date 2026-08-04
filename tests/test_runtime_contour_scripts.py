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


def _assert_test_exec_boundaries(
    exec_start: str, *, client_login_enabled: bool
) -> None:
    assert "SHUMEYKO_RUNTIME_ENVIRONMENT=test" in exec_start
    assert "SHUMEYKO_SESSION_COOKIE_NAME=shumeyko_test_session" in exec_start
    assert (
        f"SHUMEYKO_CLIENT_LOGIN_ENABLED={str(client_login_enabled).lower()}"
        in exec_start
    )
    assert "SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED=false" in exec_start
    assert "SHUMEYKO_ALLOWED_EXPORT_ROOT=/data/shumeyko/test/reports" in exec_start
    assert (
        "SHUMEYKO_DEFAULT_REPORT_WORKBOOK=/data/shumeyko/test/reports/none.xlsx"
        in exec_start
    )
    assert (
        "SHUMEYKO_SOURCE_REFRESH_ROOT=/data/shumeyko/test/source_refresh"
        in exec_start
    )
    assert "/data/shumeyko/prod" not in exec_start


def test_r5_test_drop_in_keeps_return_reasons_staff_only() -> None:
    drop_in = (
        ROOT
        / "deploy/systemd/shumeiko-web-test.service.d/"
        "zz-logistics-r5-return-reasons.conf"
    ).read_text(encoding="utf-8")

    assert "SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED=true" in drop_in
    assert "SHUMEYKO_LOGISTICS_ANALYSIS_CLIENT_ENABLED=false" in drop_in
    assert "SHUMEYKO_LOGISTICS_RETURN_REASONS_ENABLED=true" in drop_in
    assert "SHUMEYKO_LOGISTICS_RETURN_REASONS_CLIENT_ENABLED=false" in drop_in
    assert "SHUMEYKO_LOGISTICS_FACTORS_CLIENT_ENABLED=false" in drop_in
    assert "SHUMEYKO_LOGISTICS_TARIFFS_CLIENT_ENABLED=false" in drop_in
    assert "SHUMEYKO_LOGISTICS_ROUTES_CLIENT_ENABLED=false" in drop_in
    assert "SHUMEYKO_LOGISTICS_MEASUREMENTS_CLIENT_ENABLED=false" in drop_in


def test_r6_test_drop_in_enables_all_logistics_for_client_role() -> None:
    drop_in_path = (
        ROOT
        / "deploy/systemd/shumeiko-web-test.service.d/"
        "zzz-logistics-r6-client-test.conf"
    )
    drop_in = drop_in_path.read_text(encoding="utf-8")
    exec_start = next(
        line
        for line in drop_in.splitlines()
        if line.startswith("ExecStart=/usr/bin/env ")
    )

    assert drop_in_path.name > "zz-logistics-r5-return-reasons.conf"
    assert "ExecStart=" in drop_in.splitlines()
    assert "SHUMEYKO_CLIENT_LOGIN_ENABLED=true" in drop_in
    assert "SHUMEYKO_CLIENT_LOGIN_ENABLED=true" in exec_start
    _assert_test_exec_boundaries(exec_start, client_login_enabled=True)
    for flag in (
        "SHUMEYKO_LOGISTICS_ANALYSIS",
        "SHUMEYKO_LOGISTICS_FACTORS",
        "SHUMEYKO_LOGISTICS_TARIFFS",
        "SHUMEYKO_LOGISTICS_ROUTES",
        "SHUMEYKO_LOGISTICS_MEASUREMENTS",
        "SHUMEYKO_LOGISTICS_RETURN_REASONS",
    ):
        assert f"{flag}_ENABLED=true" in drop_in
        assert f"{flag}_CLIENT_ENABLED=true" in drop_in
        assert f"{flag}_ENABLED=true" in exec_start
        assert f"{flag}_CLIENT_ENABLED=true" in exec_start
    assert "_CLIENT_ENABLED=false" not in drop_in


def test_margin_calculator_test_drop_in_is_staff_only_and_additive() -> None:
    drop_in_path = (
        ROOT
        / "deploy/systemd/shumeiko-web-test.service.d/"
        "zzzz-unit-economics-calculator-staff-test.conf"
    )
    drop_in = drop_in_path.read_text(encoding="utf-8")
    exec_start = next(
        line
        for line in drop_in.splitlines()
        if line.startswith("ExecStart=/usr/bin/env ")
    )

    assert drop_in_path.name > "zzz-logistics-r6-client-test.conf"
    assert "SHUMEYKO_UNIT_ECONOMICS_CALCULATOR_ENABLED=true" in drop_in
    assert "SHUMEYKO_UNIT_ECONOMICS_CALCULATOR_CLIENT_ENABLED=false" in drop_in
    assert "SHUMEYKO_UNIT_ECONOMICS_CALCULATOR_ENABLED=true" in exec_start
    assert "SHUMEYKO_UNIT_ECONOMICS_CALCULATOR_CLIENT_ENABLED=false" in exec_start
    _assert_test_exec_boundaries(exec_start, client_login_enabled=False)
    assert "SHUMEYKO_LOGISTICS_ANALYSIS_ENABLED" not in exec_start


def test_nginx_templates_proxy_accounting_workflow_route() -> None:
    test_config = (ROOT / "deploy/nginx/shumeiko.offonika.ru.conf").read_text(
        encoding="utf-8"
    )
    production_config = (ROOT / "deploy/nginx/analitika.offonika.ru.conf").read_text(
        encoding="utf-8"
    )

    workflow_location = test_config.index("location ^~ /accounting-workflows")
    static_fallback = test_config.rindex("location / {")
    assert workflow_location < static_fallback
    assert (
        "proxy_pass http://127.0.0.1:8098;"
        in test_config[workflow_location:static_fallback]
    )
    assert "accounting-workflows" in production_config
    assert "proxy_pass http://127.0.0.1:8097;" in production_config


def test_scheduled_refresh_builds_tuesday_report_in_production_roots() -> None:
    systemd_root = ROOT / "deploy/systemd"
    weekly_timer = (
        systemd_root / "shumeiko-source-refresh-weekly.timer"
    ).read_text(encoding="utf-8")
    daily_timer = (
        systemd_root / "shumeiko-source-refresh-daily.timer"
    ).read_text(encoding="utf-8")

    assert "Tuesday morning" in weekly_timer
    assert "OnCalendar=Tue *-*-* 06:15:00" in weekly_timer
    assert {
        line
        for line in daily_timer.splitlines()
        if line.startswith("OnCalendar=")
    } == {
        "OnCalendar=Mon *-*-* *:15:00",
        "OnCalendar=Tue *-*-* 00..05:15:00",
        "OnCalendar=Tue *-*-* 07..23:15:00",
        "OnCalendar=Wed..Sun *-*-* *:15:00",
    }
    assert "OnCalendar=Tue *-*-* 06:15:00" not in daily_timer

    for unit_name in (
        "shumeiko-source-refresh-daily.service",
        "shumeiko-source-refresh-weekly.service",
    ):
        unit = (systemd_root / unit_name).read_text(encoding="utf-8")
        exec_start = next(
            line
            for line in unit.splitlines()
            if line.startswith("ExecStart=/usr/bin/env ")
        )

        assert (
            "SHUMEYKO_ALLOWED_EXPORT_ROOT=/data/shumeyko/prod/reports "
            in exec_start
        )
        assert (
            "SHUMEYKO_DEFAULT_REPORT_WORKBOOK=/data/shumeyko/prod/reports/"
            "shumeyko_wb_excel_mvp.xlsx "
            in exec_start
        )
        assert (
            "SHUMEYKO_SOURCE_REFRESH_ROOT=/data/shumeyko/source_refresh "
            in exec_start
        )
        assert "SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB=20 " in exec_start
        assert "SHUMEYKO_SOURCE_REFRESH_ONEC_MAX_PAGES=1000 " in exec_start

    weekly_service = (
        systemd_root / "shumeiko-source-refresh-weekly.service"
    ).read_text(encoding="utf-8")
    assert "--mode full" in weekly_service


def test_systemd_templates_bound_retention_and_require_data_mounts() -> None:
    systemd_root = ROOT / "deploy/systemd"
    prune_timer = (systemd_root / "shumeiko-source-refresh-prune.timer").read_text(
        encoding="utf-8"
    )
    prune_service = (systemd_root / "shumeiko-source-refresh-prune.service").read_text(
        encoding="utf-8"
    )
    release_timer = (systemd_root / "shumeiko-runtime-release-prune.timer").read_text(
        encoding="utf-8"
    )
    release_service = (
        systemd_root / "shumeiko-runtime-release-prune.service"
    ).read_text(encoding="utf-8")
    archive_timer = (systemd_root / "shumeiko-source-snapshot-archive.timer").read_text(
        encoding="utf-8"
    )
    archive_service = (
        systemd_root / "shumeiko-source-snapshot-archive.service"
    ).read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* *:45:00" in prune_timer
    assert "--daily-keep 3 --full-keep 2 --apply" in prune_service
    assert "daily-20260712-065846" not in prune_service
    assert "RequiresMountsFor=/data/shumeyko/source_refresh" in prune_service
    assert "OnCalendar=*-*-* 04:35:00" in release_timer
    assert "--keep-latest 2 --grace-hours 24 --apply" in release_service
    assert "OnCalendar=*-*-* 04:50:00" in archive_timer
    assert "archive-eligible --apply --evict" in archive_service
    assert "--min-age-hours 48" in archive_service
    assert "RequiresMountsFor=/data/shumeyko/source_refresh" in archive_service
    assert not (systemd_root / "shumeiko-test-source-snapshot-archive.timer").exists()
    assert not (
        systemd_root / "shumeiko-test-source-snapshot-archive.service"
    ).exists()

    accounting_canary = (
        systemd_root
        / "shumeiko-web-test.service.d"
        / "accounting-canary.conf"
    ).read_text(encoding="utf-8")
    assert "SHUMEYKO_CLIENT_LOGIN_ENABLED=false" in accounting_canary
    assert "SHUMEYKO_ACCOUNTING_WORKFLOW_SCHEDULER_ENABLED=false" in (
        accounting_canary
    )
    assert (
        "SHUMEYKO_ACCOUNTING_WORKFLOW_EVIDENCE_ROOT="
        "/data/shumeyko/test/accounting_workflow_evidence"
    ) in accounting_canary

    required_mounts = {
        "shumeiko-web-prod.service": "/data/shumeyko/source_refresh",
        "shumeiko-web-test.service": "/data/shumeyko/test",
        "shumeiko-web-backup.service": "/var/backups",
        "shumeiko-source-refresh-daily.service": "/data/shumeyko/source_refresh",
        "shumeiko-source-refresh-weekly.service": "/data/shumeyko/source_refresh",
        "shumeiko-source-refresh-worker@.service": "/data/shumeyko/source_refresh",
    }
    for unit_name, mount_path in required_mounts.items():
        unit = (systemd_root / unit_name).read_text(encoding="utf-8")
        assert f"RequiresMountsFor={mount_path}" in unit

    for unit_name in (
        "shumeiko-web-prod.service",
        "shumeiko-source-refresh-daily.service",
        "shumeiko-source-refresh-weekly.service",
        "shumeiko-source-refresh-worker@.service",
    ):
        unit = (systemd_root / unit_name).read_text(encoding="utf-8")
        assert "SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB=20" in unit
        assert "/data/shumeyko/prod/reports" in unit

    production_unit = (systemd_root / "shumeiko-web-prod.service").read_text(
        encoding="utf-8"
    )
    test_unit = (systemd_root / "shumeiko-web-test.service").read_text(
        encoding="utf-8"
    )
    assert "SHUMEYKO_RUNTIME_ENVIRONMENT=production" in production_unit
    assert "SHUMEYKO_CLIENT_LOGIN_ENABLED=true" in production_unit
    assert (
        "ExecStart=/usr/bin/env SHUMEYKO_RUNTIME_ENVIRONMENT=production "
        in production_unit
    )
    assert (
        "SHUMEYKO_ALLOWED_EXPORT_ROOT=/data/shumeyko/prod/reports "
        "SHUMEYKO_DEFAULT_REPORT_WORKBOOK=/data/shumeyko/prod/reports/"
        "shumeyko_wb_excel_mvp.xlsx "
        in production_unit
    )
    proxy_dropin = (
        systemd_root
        / "shumeiko-web-prod.service.d"
        / "corporate-proxy-login-shell.conf"
    ).read_text(encoding="utf-8")
    assert "ExecStart=/bin/bash -lc 'exec /usr/bin/env " in proxy_dropin
    assert (
        "SHUMEYKO_ALLOWED_EXPORT_ROOT=/data/shumeyko/prod/reports "
        "SHUMEYKO_DEFAULT_REPORT_WORKBOOK=/data/shumeyko/prod/reports/"
        "shumeyko_wb_excel_mvp.xlsx "
        in proxy_dropin
    )
    assert "SHUMEYKO_RUNTIME_ENVIRONMENT=test" in test_unit
    assert "SHUMEYKO_CLIENT_LOGIN_ENABLED=false" in test_unit
    assert "SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED=false" in test_unit
    assert "SHUMEYKO_ALLOWED_EXPORT_ROOT=/data/shumeyko/test/reports" in test_unit
    test_exec_start = next(
        line
        for line in test_unit.splitlines()
        if line.startswith("ExecStart=/usr/bin/env ")
    )
    _assert_test_exec_boundaries(test_exec_start, client_login_enabled=False)

    health_helper = (ROOT / "scripts/check_web_cabinet_health.py").read_text(
        encoding="utf-8"
    )
    assert "http://127.0.0.1:8097/api/health" in health_helper
    assert 'default="shumeiko-web-prod.service"' in health_helper
    assert "8096/api/health" not in health_helper


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
    assert production_values["SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB"] == "20"
    assert (
        production_values["SHUMEYKO_ALLOWED_EXPORT_ROOT"]
        == "/data/shumeyko/prod/reports"
    )
    assert test_values["SHUMEYKO_BOOTSTRAP_PASSWORD"] == ""
    assert test_values["SHUMEYKO_INTEGRATION_SECRET_KEY"] == ""
    assert test_values["SHUMEYKO_OPENAI_API_KEY"] == ""
    assert test_values["ONEC_ODATA_PASSWORD"] == ""
    assert test_values["SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED"] == "false"
    assert test_values["SHUMEYKO_CLIENT_LOGIN_ENABLED"] == "false"
    assert test_values["SHUMEYKO_ALLOWED_EXPORT_ROOT"] == "/data/shumeyko/test/reports"
    assert test_values["SHUMEYKO_DATABASE_URL"].endswith("/shumeyko_web_cabinet_test")
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
                "postgresql+psycopg://test-app:placeholder@db/shumeyko_web_cabinet_test"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "placeholder" not in result.stdout
    test_values = _read_env(test)
    assert test_values["SHUMEYKO_DATABASE_URL"].startswith(
        "postgresql+psycopg://test-app:"
    )
    assert test_values["SHUMEYKO_DATABASE_URL"].endswith("/shumeyko_web_cabinet_test")


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
