from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text

from wb_unit_economics.report_exports import file_sha256
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import (
    DB_FIRST_SCHEMA_VERSION,
    LOGISTICS_HARDENING_SCHEMA_VERSION,
    init_db,
    make_engine,
    make_session_factory,
    schema_version,
)
from wb_unit_economics.web.models import ReportRun, ReportUnitRow
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
    assert "logistics_dimensions_required" in {
        column["name"] for column in inspector.get_columns("report_runs")
    }
    assert "logistics_tariffs_required" in {
        column["name"] for column in inspector.get_columns("report_runs")
    }
    assert "logistics_routes_required" in {
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
    sku_columns = {
        column["name"]: column
        for column in inspector.get_columns("report_logistics_sku_rows")
    }
    assert {"tenant_id", "client_id", "financial_revenue"} <= set(sku_columns)
    assert sku_columns["financial_revenue"]["nullable"] is True
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
        "financial_revenue",
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


def test_unit_rows_are_inserted_in_bounded_core_batches_with_value_parity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    payload = _payload()
    template = payload["unitRows"][0]
    payload["unitRows"] = [
        {
            **deepcopy(template),
            "id": f"unit-{index}",
            "product": f"Товар {index}",
            "revenue": 1000 + index,
        }
        for index in range(1, 6)
    ]
    batch_sizes: list[int] = []
    original_insert_batch = repository._insert_report_unit_row_batch

    def record_insert_batch(db, rows) -> None:
        batch_sizes.append(len(rows))
        original_insert_batch(db, rows)

    monkeypatch.setattr(repository, "REPORT_UNIT_ROW_INSERT_BATCH_SIZE", 2)
    monkeypatch.setattr(
        repository,
        "_insert_report_unit_row_batch",
        record_insert_batch,
    )

    with session_factory() as db:
        report = save_report_marts(
            db,
            payload,
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-batched-unit-rows",
        )
        db.flush()
        assert not any(
            isinstance(instance, ReportUnitRow)
            for instance in db.identity_map.values()
        )
        rows = list(
            db.scalars(
                select(ReportUnitRow)
                .where(ReportUnitRow.report_run_id == report.id)
                .order_by(ReportUnitRow.row_uid)
            )
        )

    assert batch_sizes == [2, 2, 1]
    assert [(row.row_uid, row.product, row.revenue) for row in rows] == [
        (f"unit-{index}", f"Товар {index}", 1000 + index)
        for index in range(1, 6)
    ]


def test_unit_row_batch_failure_rolls_back_report_and_keeps_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        current = save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-current",
        )
        db.commit()
        current_id = current.id

    payload = _payload()
    template = payload["unitRows"][0]
    payload["unitRows"] = [
        {**deepcopy(template), "id": f"failing-unit-{index}"}
        for index in range(1, 6)
    ]
    original_insert_batch = repository._insert_report_unit_row_batch
    insert_calls = 0

    def fail_second_insert_batch(db, rows) -> None:
        nonlocal insert_calls
        insert_calls += 1
        if insert_calls == 2:
            raise RuntimeError("synthetic batch failure")
        original_insert_batch(db, rows)

    monkeypatch.setattr(repository, "REPORT_UNIT_ROW_INSERT_BATCH_SIZE", 2)
    monkeypatch.setattr(
        repository,
        "_insert_report_unit_row_batch",
        fail_second_insert_batch,
    )

    with session_factory() as db:
        with pytest.raises(RuntimeError, match="synthetic batch failure"):
            save_report_marts(
                db,
                payload,
                tenant_id="shumeyko",
                tenant_name="Шумейко и Партнеры",
                report_id="report-must-rollback",
            )
        db.rollback()
        current = db.get(ReportRun, current_id)
        failed = db.get(ReportRun, "report-must-rollback")
        failed_row_count = db.scalar(
            select(func.count())
            .select_from(ReportUnitRow)
            .where(ReportUnitRow.report_run_id == "report-must-rollback")
        )

    assert insert_calls == 2
    assert current is not None and current.is_current is True
    assert failed is None
    assert failed_row_count == 0


def test_logistics_financial_revenue_migration_is_idempotent(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE report_logistics_sku_rows "
                "DROP COLUMN financial_revenue"
            )
        )

    init_db(engine)
    init_db(engine)

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("report_logistics_sku_rows")
    }
    assert columns["revenue"]["nullable"] is False
    assert columns["financial_revenue"]["nullable"] is True
    postgres_schema = Path("sql/postgres_schema.sql").read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS financial_revenue numeric" in postgres_schema
