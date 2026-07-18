from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from wb_unit_economics.web import repository
from wb_unit_economics.web.database import (
    _ensure_accounting_evidence_columns_and_indexes,
    _ensure_ai_thread_scope_columns,
    _ensure_marketplace_finance_daily_fact_columns,
    _ensure_marketplace_finance_daily_fact_indexes,
    _ensure_multi_report_columns_and_indexes,
    _ensure_source_load_columns,
    _ensure_source_refresh_resume_columns,
    init_db,
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import (
    ReportGenerationRequest,
    SourceRefreshCollection,
)


def test_ai_thread_scope_migration_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'ai-thread-scope.sqlite3'}")
    init_db(engine)

    _ensure_ai_thread_scope_columns(engine)
    _ensure_ai_thread_scope_columns(engine)

    thread_columns = {
        item["name"] for item in inspect(engine).get_columns("ai_threads")
    }
    message_columns = {
        item["name"] for item in inspect(engine).get_columns("ai_messages")
    }
    assert {"client_id", "scope", "scope_hash", "archived_at"} <= thread_columns
    assert "chatkit_item_id" in message_columns


def test_multi_report_migration_backfills_before_unique_indexes(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy-multi-report.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE report_runs ("
                "id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, "
                "client_id VARCHAR NOT NULL, is_current BOOLEAN NOT NULL, "
                "publication_status VARCHAR NOT NULL, "
                "generated_at DATETIME NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO report_runs VALUES "
                "('old', 'tenant-a', 'client-a', 1, 'published', "
                "'2026-06-01', '2026-06-01'), "
                "('new', 'tenant-a', 'client-a', 1, 'published', "
                "'2026-07-01', '2026-07-01')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE source_refresh_runs ("
                "id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, "
                "client_id VARCHAR NOT NULL)"
            )
        )

    _ensure_multi_report_columns_and_indexes(engine)
    _ensure_multi_report_columns_and_indexes(engine)

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, report_kind, is_current, publication_status "
                "FROM report_runs ORDER BY id"
            )
        ).fetchall()
        assert rows == [
            ("new", "marketplace_unit_economics", 1, "published"),
            ("old", "marketplace_unit_economics", 0, "superseded"),
        ]
        indexes = {item["name"] for item in inspect(engine).get_indexes("report_runs")}
        assert {
            "uq_report_runs_current_marketplace",
            "uq_report_runs_current_accounting",
        }.issubset(indexes)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO report_runs "
                "(id, tenant_id, client_id, is_current, publication_status, "
                "generated_at, created_at, report_kind, organization_id) "
                "VALUES ('duplicate', 'tenant-a', 'client-a', 1, 'draft', "
                "'2026-08-01', '2026-08-01', "
                "'marketplace_unit_economics', NULL)"
            )
        )


def test_make_engine_recycles_and_pre_pings_non_sqlite() -> None:
    engine = make_engine("postgresql+psycopg://user:pass@localhost/db")

    assert getattr(engine.pool, "_pre_ping", False) is True
    assert getattr(engine.pool, "_recycle", -1) == 1800


def test_make_engine_keeps_sqlite_file_setup(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "web.sqlite3"
    engine = make_engine(f"sqlite:///{db_path}")

    assert db_path.parent.exists()
    assert getattr(engine.pool, "_pre_ping", False) is False


def test_source_refresh_worker_and_lineage_migration_is_idempotent(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE source_refresh_runs (id VARCHAR PRIMARY KEY)")
        )
        connection.execute(
            text("CREATE TABLE source_refresh_collections (id VARCHAR PRIMARY KEY)")
        )

    _ensure_source_refresh_resume_columns(engine)
    _ensure_source_refresh_resume_columns(engine)

    run_columns = {
        item["name"] for item in inspect(engine).get_columns("source_refresh_runs")
    }
    assert {
        "resumed_from_run_id",
        "base_source_refresh_run_id",
        "blocked_by_run_id",
        "worker_id",
        "failure_code",
        "heartbeat_at",
        "source_window_start",
        "source_window_end",
    }.issubset(run_columns)


def test_source_load_incremental_lineage_migration_is_idempotent(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy-loads.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE source_loads (id INTEGER PRIMARY KEY)"))

    _ensure_source_load_columns(engine)
    _ensure_source_load_columns(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("source_loads")}
    assert {
        "coverage_start",
        "coverage_end",
        "lineage_role",
    }.issubset(columns)


def test_daily_fact_preallocated_fields_migration_is_idempotent(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy-daily-facts.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE marketplace_finance_daily_facts (id INTEGER PRIMARY KEY)"
            )
        )

    _ensure_marketplace_finance_daily_fact_columns(engine)
    _ensure_marketplace_finance_daily_fact_columns(engine)

    columns = {
        item["name"]
        for item in inspect(engine).get_columns("marketplace_finance_daily_facts")
    }
    assert {
        "spp_discount",
        "accounting_service_input_vat",
        "gross_profit",
    }.issubset(columns)


def test_daily_fact_replacement_indexes_are_idempotent(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'daily-fact-indexes.sqlite3'}")
    init_db(engine)

    _ensure_marketplace_finance_daily_fact_indexes(engine)
    _ensure_marketplace_finance_daily_fact_indexes(engine)

    indexes = {
        item["name"]: tuple(item["column_names"])
        for item in inspect(engine).get_indexes("marketplace_finance_daily_facts")
    }
    assert indexes["ix_marketplace_daily_facts_refresh_run"] == (
        "tenant_id",
        "client_id",
        "marketplace",
        "source_refresh_run_id",
    )
    assert indexes["ix_marketplace_daily_facts_report_key"] == (
        "tenant_id",
        "client_id",
        "marketplace",
        "seller_account_id",
        "marketplace_report_id",
    )


def test_accounting_evidence_migration_backfills_deduplicates_and_maps_keys(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'accounting-evidence.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        repository.ensure_tenant(db, "tenant-a", "Tenant A")
        repository.ensure_client_company(
            db,
            tenant_id="tenant-a",
            client_id="tenant-a",
            display_name="Tenant A",
        )
        run = repository.create_source_refresh_run(
            db,
            tenant_id="tenant-a",
            client_id="tenant-a",
            mode="report-generation",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="legacy-evidence-run",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            enforce_active_check=False,
        )
        run.target_report_kind = "month_close_control"
        run.organization_id = "ORG-1"
        run.idempotency_key = "legacy-key"
        for marker in ("old", "new"):
            repository.add_source_refresh_collection(
                db,
                run,
                source_type="month_close_control_evidence",
                source_label=marker,
                required=True,
                status="loaded",
                payload={
                    "organizationId": "ORG-1",
                    "normalizedEvidence": {"organizationId": "ORG-1"},
                },
            )
        run_id = run.id
        db.commit()

    _ensure_accounting_evidence_columns_and_indexes(engine)
    _ensure_accounting_evidence_columns_and_indexes(engine)

    with session_factory() as db:
        evidence = list(
            db.scalars(
                select(SourceRefreshCollection).where(
                    SourceRefreshCollection.refresh_run_id == run_id,
                    SourceRefreshCollection.source_type
                    == "month_close_control_evidence",
                )
            )
        )
        assert len(evidence) == 1
        assert evidence[0].organization_id == "ORG-1"
        key = db.scalar(
            select(ReportGenerationRequest).where(
                ReportGenerationRequest.idempotency_key == "legacy-key"
            )
        )
        assert key is not None
        assert key.generation_run_id == run_id
