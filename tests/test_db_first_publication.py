from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sqlalchemy import inspect, text

from wb_unit_economics.report_exports import file_sha256
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import (
    DAILY_FACT_REPLACEMENT_INDEX_SCHEMA_VERSION,
    DB_FIRST_SCHEMA_VERSION,
    LOGISTICS_HARDENING_SCHEMA_VERSION,
    init_db,
    make_engine,
    make_session_factory,
    schema_version,
)
from wb_unit_economics.web.models import ReportRun
from wb_unit_economics.web.repository import save_report_marts, upsert_user


def _payload() -> dict:
    return {
        "meta": {
            "title": "Кабинет юнит-экономики WB",
            "client": "Шумейко и Партнеры",
            "period": "01.03.2026 - 17.06.2026",
            "reportPeriod": "01.03.2026 - 17.06.2026",
            "periodText": "март-июнь 2026",
            "periodStatus": "",
            "sourceCoverage": "01.03.2026 - 17.06.2026",
            "sourceCoverageStart": "2026-03-01",
            "sourceCoverageEnd": "2026-06-17",
            "methodologyVersion": "DB-first test",
            "generatedAt": "20.06.2026 12:00",
            "sourceWorkbook": "",
            "returnReasonLimitation": "",
        },
        "readiness": {},
        "options": {},
        "monthly": [],
        "expenses": [],
        "unitRows": [
            {
                "id": "unit-1",
                "week": "2026-04-06",
                "month": "Апрель 2026",
                "documentReport": "Отчет комиссионера · 06.04.2026-12.04.2026",
                "organization": "Организация A",
                "cabinet": "Кабинет A",
                "product": "Товар",
                "nmId": "1001",
                "articleWb": "WB-1",
                "article1c": "A-1",
                "barcode": "BAR-1",
                "scheme": "FBO",
                "sales": 1,
                "returns": 0,
                "netQty": 1,
                "returnRate": 0,
                "revenueBeforeSpp": 1000,
                "spp": 0,
                "revenue": 1000,
                "vat": 48,
                "revenueWithoutVat": 952,
                "cost": 300,
                "commission": 100,
                "logistics": 50,
                "storage": 0,
                "acceptance": 0,
                "promotion": 0,
                "penalties": 0,
                "acquiring": 10,
                "usn": 10,
                "profitBeforeTax": 540,
                "profit": 482,
                "margin": 0.482,
                "unitProfit": 482,
                "status": "ОК",
                "statusReason": "Данные достаточны для расчета",
                "sppStatus": "ОК",
                "lossClass": "Без критичных проблем",
                "lossDriver": "Без критичных проблем",
            }
        ],
        "returns": [],
        "lostSales": [],
        "reconciliation": [],
        "reconciliationMonthly": [],
        "documentReconciliation": [],
    }


def test_db_first_publication_keeps_single_current_report_and_rollback(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    assert schema_version(engine) == DB_FIRST_SCHEMA_VERSION
    inspector = inspect(engine)
    assert "logistics_analysis_required" in {
        column["name"] for column in inspector.get_columns("report_runs")
    }
    assert {
        "source_quality_status",
        "required_field_error_count",
        "invalid_report_row_count",
        "report_required_field_error_count",
        "chain_dimension_conflict_count",
        "invalid_source_payload_shape_count",
        "source_identity_error_count",
        "source_revision_conflict_count",
        "source_revision_discarded_count",
        "scope_mismatch_count",
        "max_dimension_delta",
    } <= {
        column["name"]
        for column in inspector.get_columns("report_logistics_analysis_contexts")
    }
    with engine.begin() as connection:
        versions = set(
            connection.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
    assert LOGISTICS_HARDENING_SCHEMA_VERSION in versions
    assert DAILY_FACT_REPLACEMENT_INDEX_SCHEMA_VERSION in versions
    assert {"tenant_id", "client_id"} <= {
        column["name"]
        for column in inspector.get_columns("report_logistics_sku_rows")
    }
    assert "ix_report_logistics_orders_calendar_filter" in {
        index["name"]
        for index in inspector.get_indexes("report_logistics_order_rows")
    }
    postgres_schema = Path("sql/postgres_schema.sql").read_text(encoding="utf-8")
    for column in (
        "invalid_report_row_count",
        "report_required_field_error_count",
        "chain_dimension_conflict_count",
        "invalid_source_payload_shape_count",
        "source_revision_conflict_count",
        "scope_mismatch_count",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in postgres_schema
    init_db(engine)
    assert schema_version(engine) == DB_FIRST_SCHEMA_VERSION
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        user = upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="admin",
        )
        first = save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-old",
        )
        second_payload = deepcopy(_payload())
        second_payload["unitRows"][0]["id"] = "unit-2"
        second = save_report_marts(
            db,
            second_payload,
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-new",
        )
        artifact = tmp_path / "reports" / "shumeyko_wb_excel_mvp.xlsx"
        artifact.parent.mkdir()
        artifact.write_bytes(b"db-first workbook")
        repository.record_report_artifact(
            db,
            second,
            artifact_type="excel",
            path=artifact,
            sha256=file_sha256(artifact),
            byte_size=artifact.stat().st_size,
        )
        db.commit()

        latest = repository.latest_report_for_user(db, user)
        old = db.get(ReportRun, first.id)
        new = db.get(ReportRun, second.id)
        artifact_path = repository.report_artifact_path(
            db,
            new,
            "excel",
            tmp_path / "reports",
        )

    assert latest is not None
    assert latest.id == "report-new"
    assert old is not None and old.is_current is False
    assert new is not None and new.is_current is True
    assert new.lineage_type == "db_first_report_marts"
    assert new.source_coverage_start is not None
    assert new.source_coverage_start.isoformat() == "2026-03-01"
    assert new.source_coverage_end is not None
    assert new.source_coverage_end.isoformat() == "2026-06-17"
    assert artifact_path == artifact.resolve()
