from __future__ import annotations

import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    Client,
    ClientCompany,
    ReportRun,
    ReportUnitRow,
    TenantIntegration,
    WbCabinet,
)
from wb_unit_economics.web.repository import ensure_client, ensure_tenant


def test_repair_web_client_hierarchy_is_dry_run_first(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)

    dry_run = _run_repair(
        database_url,
        "--tenant-id",
        "second-client",
        "--client-id",
        "second-client",
        "--client-name",
        "Второй клиент",
        "--company",
        "ООО Второй клиент",
        "--cabinet",
        "ООО Второй клиент::WB Второй клиент",
    )

    assert dry_run.returncode == 0
    assert "DRY RUN" in dry_run.stdout
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        assert db.get(Client, "second-client") is None

    applied = _run_repair(
        database_url,
        "--tenant-id",
        "second-client",
        "--client-id",
        "second-client",
        "--client-name",
        "Второй клиент",
        "--company",
        "ООО Второй клиент",
        "--cabinet",
        "ООО Второй клиент::WB Второй клиент",
        "--apply",
    )

    assert applied.returncode == 0
    assert "APPLIED" in applied.stdout
    with session_factory() as db:
        client = db.get(Client, "second-client")
        assert client is not None
        assert client.name == "Второй клиент"
        companies = db.query(ClientCompany).filter_by(client_id="second-client").all()
        cabinets = db.query(WbCabinet).filter_by(client_id="second-client").all()
        assert [item.display_name for item in companies] == ["ООО Второй клиент"]
        assert [item.display_name for item in cabinets] == ["WB Второй клиент"]
        assert cabinets[0].client_company_id == companies[0].id


def test_repair_web_client_hierarchy_dedupes_wb_cabinets(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    now = datetime.now(UTC)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        tenant = ensure_tenant(db, "shumeyko", "Шумейко")
        client = ensure_client(
            db,
            tenant_id=tenant.id,
            client_id="shumeyko",
            name="Шумейко",
        )
        db.add_all(
            [
                WbCabinet(
                    id="wb_primary",
                    tenant_id=tenant.id,
                    client_id=client.id,
                    client_company_id=None,
                    display_name="WB Дубль",
                    cabinet_key="primary",
                    provider="wb_api",
                    status="active",
                    created_at=now,
                    updated_at=now,
                ),
                WbCabinet(
                    id="wb_label",
                    tenant_id=tenant.id,
                    client_id=client.id,
                    client_company_id=None,
                    display_name="WB Дубль",
                    cabinet_key="wb_дубль",
                    provider="wb_api",
                    status="active",
                    created_at=now,
                    updated_at=now,
                ),
                TenantIntegration(
                    tenant_id=tenant.id,
                    provider="wb_api",
                    label="WB Дубль",
                    status="configured",
                    secret_hash="hash",
                    secret_hint="***test",
                    config_payload={
                        "providerBase": "wb_api",
                        "connectionKey": "primary",
                        "connectionRole": "finance_reports",
                        "cabinetName": "WB Дубль",
                        "clientId": client.id,
                        "wbCabinetId": "wb_primary",
                    },
                    created_at=now,
                    updated_at=now,
                ),
                ReportRun(
                    id="report-1",
                    tenant_id=tenant.id,
                    client_id=client.id,
                    client_name=client.name,
                    title="Отчет",
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 4, 30),
                    period_text="Апрель 2026",
                    period_status="closed",
                    generated_at=now,
                    status="ready",
                    methodology_version="test",
                    created_at=now,
                ),
                ReportUnitRow(
                    report_run_id="report-1",
                    client_id=client.id,
                    wb_cabinet_id="wb_label",
                    row_uid="row-1",
                ),
            ]
        )
        db.commit()

    dry_run = _run_repair(
        database_url,
        "--tenant-id",
        "shumeyko",
        "--client-id",
        "shumeyko",
        "--dedupe-wb-cabinets",
    )

    assert dry_run.returncode == 0
    assert "DRY RUN" in dry_run.stdout
    with session_factory() as db:
        assert db.query(WbCabinet).filter_by(client_id="shumeyko").count() == 2

    applied = _run_repair(
        database_url,
        "--tenant-id",
        "shumeyko",
        "--client-id",
        "shumeyko",
        "--dedupe-wb-cabinets",
        "--apply",
    )

    assert applied.returncode == 0
    assert "APPLIED" in applied.stdout
    assert "merged_cabinets: 1" in applied.stdout
    with session_factory() as db:
        cabinets = db.query(WbCabinet).filter_by(client_id="shumeyko").all()
        assert [item.id for item in cabinets] == ["wb_primary"]
        row = db.query(ReportUnitRow).one()
        assert row.wb_cabinet_id == "wb_primary"


def _run_repair(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/repair_web_client_hierarchy.py",
            "--database-url",
            database_url,
            *args,
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
