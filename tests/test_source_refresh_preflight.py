from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import TenantIntegration


def test_source_refresh_preflight_reports_missing_integrations_and_disk(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    _seed_db(database_url)
    mapping_dir = _mapping_dir(tmp_path)

    result = _run_preflight(
        tmp_path,
        database_url,
        "--mapping-dir",
        str(mapping_dir),
        "--source-refresh-root",
        str(tmp_path / "source_refresh"),
        "--min-free-gb",
        "1000000",
    )

    assert result.returncode == 1
    assert "wb_api tenant integration is not configured" in result.stdout
    assert "Ozon API integrations: not configured (optional)" in result.stdout
    assert "onec_readonly tenant integration is not configured" in result.stdout
    assert "Mapping source: loaded" in result.stdout
    assert "source refresh low disk:" in result.stdout
    assert "Health: blocked" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_source_refresh_preflight_accepts_runtime_ready_integrations(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    _seed_db(database_url, integrations=True)
    mapping_dir = _mapping_dir(tmp_path)

    result = _run_preflight(
        tmp_path,
        database_url,
        "--mapping-dir",
        str(mapping_dir),
        "--source-refresh-root",
        str(tmp_path / "source_refresh"),
        "--min-free-gb",
        "0",
    )

    assert result.returncode == 0
    assert "WB API ready integrations: 1" in result.stdout
    assert "Ozon API ready integrations: 1" in result.stdout
    assert "1C read-only integration: runtime-ready" in result.stdout
    assert "Health: ready_with_warnings" in result.stdout


def test_ozon_only_preflight_ignores_broken_wb_and_requires_ozon(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    _seed_db(database_url, integrations=True)
    session_factory = make_session_factory(make_engine(database_url))
    with session_factory() as db:
        wb = db.query(TenantIntegration).filter_by(
            tenant_id="shumeyko",
            provider="wb_api",
        ).one()
        wb.status = "check_failed"
        db.commit()

    result = _run_preflight(
        tmp_path,
        database_url,
        "--mapping-dir",
        str(_mapping_dir(tmp_path)),
        "--source-refresh-root",
        str(tmp_path / "source_refresh"),
        "--min-free-gb",
        "0",
        mode="ozon-only",
    )

    assert result.returncode == 0
    assert "Ozon API ready integrations: 1" in result.stdout
    assert "WB API ready integrations" not in result.stdout
    assert "wb_api tenant integrations are not runtime-ready" not in result.stdout
    assert "Health: ready_with_warnings" in result.stdout


def _seed_db(database_url: str, *, integrations: bool = False) -> None:
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        repository.ensure_tenant(db, "shumeyko", "Шумейко и Партнеры")
        if integrations:
            now = security.utcnow()
            db.add(
                TenantIntegration(
                    tenant_id="shumeyko",
                    provider="wb_api",
                    label="Wildberries API",
                    status="configured",
                    secret_hash="hash",
                    secret_hint="",
                    config_payload={
                        "storage": "encrypted",
                        "providerBase": "wb_api",
                        "connectionRole": "finance_reports",
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                TenantIntegration(
                    tenant_id="shumeyko",
                    provider="onec_readonly",
                    label="1C read-only",
                    status="configured",
                    secret_hash="hash",
                    secret_hint="",
                    config_payload={
                        "storage": "encrypted",
                        "providerBase": "onec_readonly",
                        "connectionRole": "full_readonly",
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            db.add(
                TenantIntegration(
                    tenant_id="shumeyko",
                    provider="ozon_api",
                    label="Ozon Seller API",
                    status="configured",
                    secret_hash="hash",
                    secret_hint="",
                    config_payload={
                        "storage": "encrypted",
                        "providerBase": "ozon_api",
                        "connectionRole": "finance_reports",
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()


def _mapping_dir(tmp_path: Path) -> Path:
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "mapping.txt").write_text("safe fixture\n", encoding="utf-8")
    return mapping_dir


def _run_preflight(
    tmp_path: Path,
    database_url: str,
    *args: str,
    mode: str = "daily",
):
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/check_source_refresh_preflight.py",
            "--database-url",
            database_url,
            "--tenant",
            "shumeyko",
            "--mode",
            mode,
            *args,
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
