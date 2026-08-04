from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from wb_unit_economics.web.models import (
    Base,
    Client,
    ClientCompany,
    ConsultingFirm,
    ReportDocumentReconciliationRow,
    ReportLostSalesRow,
    ReportRun,
    ReportUnitRow,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
    Tenant,
    TenantIntegration,
    WbCabinet,
)

ACCOUNTING_WORKFLOW_SCHEMA_VERSION = "2026_07_16_accounting_workflow_v1"
LOGISTICS_HARDENING_V3_SCHEMA_VERSION = "2026_07_16_logistics_hardening_v3"
LOGISTICS_HARDENING_V4_SCHEMA_VERSION = "2026_07_16_logistics_hardening_v4"
LOGISTICS_HARDENING_SCHEMA_VERSION = "2026_07_18_logistics_profit_link_v5"
LOGISTICS_FACTOR_MARTS_SCHEMA_VERSION = "2026_07_19_logistics_factor_marts_v1"
LOGISTICS_DIMENSIONS_SCHEMA_VERSION = "2026_07_20_logistics_dimensions_context_v1"
LOGISTICS_TARIFFS_SCHEMA_VERSION = "2026_07_21_logistics_tariffs_context_v1"
LOGISTICS_ROUTES_SCHEMA_VERSION = "2026_07_21_logistics_routes_context_v1"
LOGISTICS_MEASUREMENTS_SCHEMA_VERSION = (
    "2026_07_21_logistics_measurements_context_v1"
)
LOGISTICS_RETURN_REASONS_SCHEMA_VERSION = (
    "2026_07_23_logistics_return_reasons_context_v1"
)
SOURCE_REFRESH_QUEUE_SCHEMA_VERSION = "2026_08_04_source_refresh_queue_v1"
DB_FIRST_SCHEMA_VERSION = SOURCE_REFRESH_QUEUE_SCHEMA_VERSION
MULTI_CLIENT_BACKFILL_VERSION = "2026_06_30_multi_client_hierarchy"
DEFAULT_CONSULTING_FIRM_ID = "firm_shumeyko_partners"
DEFAULT_CONSULTING_FIRM_NAME = "Шумейко и Партнеры"


def make_engine(
    database_url: str, *, echo: bool = False, statement_timeout_ms: int = 15000
) -> Engine:
    connect_args = {}
    execution_options = {}
    engine_options = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        execution_options["schema_translate_map"] = {"wb_unit_economics": None}
        if database_url.startswith("sqlite:///"):
            db_path = Path(database_url.removeprefix("sqlite:///"))
            if str(db_path) != ":memory:":
                db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        engine_options["pool_pre_ping"] = True
        engine_options["pool_recycle"] = 1800
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        echo=echo,
        execution_options=execution_options,
        future=True,
        **engine_options,
    )
    if database_url.startswith("sqlite"):
        _enable_sqlite_foreign_keys(engine)
    elif statement_timeout_ms > 0:
        _set_postgres_statement_timeout(engine, statement_timeout_ms)
    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _set_postgres_statement_timeout(engine: Engine, timeout_ms: int) -> None:
    @event.listens_for(engine, "connect")
    def _set_timeout(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET statement_timeout = {int(timeout_ms)}")
        cursor.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


def init_db(engine: Engine, *, run_backfill: bool = True) -> None:
    if not str(engine.url).startswith("sqlite"):
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS wb_unit_economics"))
    Base.metadata.create_all(engine)
    _ensure_report_run_db_first_columns(engine)
    _ensure_multi_report_columns_and_indexes(engine)
    _ensure_accounting_evidence_columns_and_indexes(engine)
    _ensure_report_unit_row_columns(engine)
    _ensure_report_lost_sales_columns(engine)
    _ensure_report_reconciliation_monthly_columns(engine)
    _ensure_report_document_reconciliation_columns(engine)
    _ensure_source_load_columns(engine)
    _ensure_source_refresh_resume_columns(engine)
    _ensure_marketplace_operation_fact_columns(engine)
    _ensure_marketplace_finance_daily_fact_columns(engine)
    _ensure_tax_profile_columns(engine)
    _ensure_logistics_hardening_columns_and_indexes(engine)
    _ensure_multi_client_columns(engine)
    _ensure_ai_thread_scope_columns(engine)
    _ensure_multi_client_indexes(engine)
    if run_backfill and schema_version(engine) != DB_FIRST_SCHEMA_VERSION:
        if not _schema_migration_at_least(engine, MULTI_CLIENT_BACKFILL_VERSION):
            _backfill_multi_client_hierarchy(engine)
        _record_schema_migration(engine, ACCOUNTING_WORKFLOW_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_HARDENING_V3_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_HARDENING_V4_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_HARDENING_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_FACTOR_MARTS_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_DIMENSIONS_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_TARIFFS_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_ROUTES_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_MEASUREMENTS_SCHEMA_VERSION)
        _record_schema_migration(engine, LOGISTICS_RETURN_REASONS_SCHEMA_VERSION)
        _record_schema_migration(engine, SOURCE_REFRESH_QUEUE_SCHEMA_VERSION)


def schema_version(engine: Engine) -> str:
    table_name = _table_name(engine, "schema_migrations")
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    f"SELECT version FROM {table_name} "
                    "ORDER BY applied_at DESC, version DESC LIMIT 1"
                )
            )
            value = result.scalar_one_or_none()
    except Exception:
        return ""
    return str(value or "")


def _schema_migration_at_least(engine: Engine, version: str) -> bool:
    table_name = _table_name(engine, "schema_migrations")
    try:
        with engine.begin() as connection:
            return bool(
                connection.execute(
                    text(
                        f"SELECT 1 FROM {table_name} WHERE version >= :version LIMIT 1"
                    ),
                    {"version": version},
                ).scalar()
            )
    except Exception:
        return False


def _schema(engine: Engine) -> str | None:
    return None if str(engine.url).startswith("sqlite") else "wb_unit_economics"


def _table_name(engine: Engine, table: str) -> str:
    schema = _schema(engine)
    return table if schema is None else f"{schema}.{table}"


def _record_schema_migration(engine: Engine, version: str) -> None:
    table_name = _table_name(engine, "schema_migrations")
    timestamp_type = (
        "DATETIME" if _schema(engine) is None else "TIMESTAMP WITH TIME ZONE"
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {table_name} ("
                "version VARCHAR PRIMARY KEY, "
                f"applied_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        connection.execute(
            text(
                f"INSERT INTO {table_name} (version, applied_at) "
                "VALUES (:version, :applied_at) "
                "ON CONFLICT (version) DO NOTHING"
            ),
            {"version": version, "applied_at": datetime.now(UTC)},
        )


def _ensure_report_run_db_first_columns(engine: Engine) -> None:
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns("report_runs", schema=schema)
    }
    bool_default = "0" if schema is None else "FALSE"
    column_specs = {
        "publication_status": "VARCHAR NOT NULL DEFAULT 'published'",
        "is_current": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "lineage_type": "VARCHAR NOT NULL DEFAULT 'legacy_excel_import'",
        "source_snapshot_set_id": "VARCHAR NOT NULL DEFAULT ''",
        "source_coverage_start": "DATE",
        "source_coverage_end": "DATE",
        "marketplace_expense_context_version": "VARCHAR NOT NULL DEFAULT ''",
        "logistics_analysis_required": (
            f"BOOLEAN NOT NULL DEFAULT {bool_default}"
        ),
        "logistics_dimensions_required": (
            f"BOOLEAN NOT NULL DEFAULT {bool_default}"
        ),
        "logistics_tariffs_required": (
            f"BOOLEAN NOT NULL DEFAULT {bool_default}"
        ),
        "logistics_routes_required": (
            f"BOOLEAN NOT NULL DEFAULT {bool_default}"
        ),
        "logistics_measurements_required": (
            f"BOOLEAN NOT NULL DEFAULT {bool_default}"
        ),
        "logistics_return_reasons_required": (
            f"BOOLEAN NOT NULL DEFAULT {bool_default}"
        ),
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    if not missing:
        return
    table_name = _table_name(engine, "report_runs")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )


def _ensure_logistics_hardening_columns_and_indexes(engine: Engine) -> None:
    """Apply additive logistics schema without rewriting old rows."""

    schema = _schema(engine)
    inspector = inspect(engine)
    table_specs: dict[str, dict[str, str]] = {
        "report_logistics_analysis_contexts": {
            "source_quality_status": "VARCHAR NOT NULL DEFAULT 'ready'",
            "invalid_source_row_count": "INTEGER NOT NULL DEFAULT 0",
            "required_field_error_count": "INTEGER NOT NULL DEFAULT 0",
            "invalid_report_row_count": "INTEGER NOT NULL DEFAULT 0",
            "report_required_field_error_count": "INTEGER NOT NULL DEFAULT 0",
            "chain_dimension_conflict_count": "INTEGER NOT NULL DEFAULT 0",
            "invalid_source_payload_shape_count": (
                "INTEGER NOT NULL DEFAULT 0"
            ),
            "source_identity_error_count": "INTEGER NOT NULL DEFAULT 0",
            "source_revision_conflict_count": "INTEGER NOT NULL DEFAULT 0",
            "source_revision_discarded_count": "INTEGER NOT NULL DEFAULT 0",
            "scope_mismatch_count": "INTEGER NOT NULL DEFAULT 0",
            "raw_order_uid_cross_cabinet_reuse_count": (
                "INTEGER NOT NULL DEFAULT 0"
            ),
            "unmatched_source_dimension_count": "INTEGER NOT NULL DEFAULT 0",
            "unmatched_report_dimension_count": "INTEGER NOT NULL DEFAULT 0",
            "dimension_delta_count": "INTEGER NOT NULL DEFAULT 0",
            "max_dimension_delta": "NUMERIC NOT NULL DEFAULT 0",
        },
        "report_logistics_order_rows": {
            "financial_date": "DATE",
            "order_period_status": "VARCHAR NOT NULL DEFAULT 'unknown'",
            "product_ref": "VARCHAR NOT NULL DEFAULT ''",
            "warehouse_status": "VARCHAR NOT NULL DEFAULT 'missing'",
            "destination_status": "VARCHAR NOT NULL DEFAULT 'missing'",
        },
        "report_logistics_sku_rows": {
            "tenant_id": "VARCHAR NOT NULL DEFAULT ''",
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "financial_week_end": "DATE",
            "product_ref": "VARCHAR NOT NULL DEFAULT ''",
            "financial_revenue": "NUMERIC",
        },
        "report_logistics_route_rows": {
            "financial_date": "DATE",
            "financial_week_start": "DATE",
            "product_ref": "VARCHAR NOT NULL DEFAULT ''",
            "product": "VARCHAR NOT NULL DEFAULT ''",
            "vendor_code": "VARCHAR NOT NULL DEFAULT ''",
            "chain_key": "VARCHAR NOT NULL DEFAULT ''",
            "coefficient_status": (
                "VARCHAR NOT NULL DEFAULT 'data_unavailable'"
            ),
            "data_quality_status": "VARCHAR NOT NULL DEFAULT ''",
        },
    }
    table_names = set(inspector.get_table_names(schema=schema))
    with engine.begin() as connection:
        for table, specs in table_specs.items():
            if table not in table_names:
                continue
            existing = {
                column["name"]
                for column in inspect(engine).get_columns(table, schema=schema)
            }
            table_name = _table_name(engine, table)
            for column, definition in specs.items():
                if column not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN "
                            f"{column} {definition}"
                        )
                    )
        order_table = _table_name(engine, "report_logistics_order_rows")
        sku_table = _table_name(engine, "report_logistics_sku_rows")
        route_table = _table_name(engine, "report_logistics_route_rows")
        if "report_logistics_order_rows" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_report_logistics_orders_product_ref "
                    f"ON {order_table} (report_run_id, product_ref, financial_date)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_report_logistics_orders_calendar_filter "
                    f"ON {order_table} (report_run_id, financial_date, "
                    "wb_cabinet_id, client_company_id, scheme, product_ref)"
                )
            )
        if "report_logistics_sku_rows" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_report_logistics_sku_product_ref "
                    f"ON {sku_table} (report_run_id, product_ref, "
                    "financial_week_start)"
                )
            )
        if "report_logistics_route_rows" in table_names:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_report_logistics_route_calendar_product "
                    f"ON {route_table} (report_run_id, financial_date, product_ref)"
                )
            )


def _ensure_ai_thread_scope_columns(engine: Engine) -> None:
    """Add immutable report/client scope to legacy AI threads."""

    schema = _schema(engine)
    inspector = inspect(engine)
    if "ai_threads" not in inspector.get_table_names(schema=schema):
        return
    existing = {
        column["name"] for column in inspector.get_columns("ai_threads", schema=schema)
    }
    json_default = "'{}'" if schema is None else "'{}'::json"
    timestamp_type = "DATETIME" if schema is None else "TIMESTAMP WITH TIME ZONE"
    specs = {
        "client_id": "VARCHAR",
        "scope": f"JSON NOT NULL DEFAULT {json_default}",
        "scope_hash": "VARCHAR NOT NULL DEFAULT ''",
        "archived_at": timestamp_type,
    }
    table_name = _table_name(engine, "ai_threads")
    report_table = _table_name(engine, "report_runs")
    with engine.begin() as connection:
        for column, definition in specs.items():
            if column not in existing:
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
                )
        connection.execute(
            text(
                f"UPDATE {table_name} SET client_id = ("
                f"SELECT client_id FROM {report_table} "
                f"WHERE {report_table}.id = {table_name}.report_run_id"
                ") WHERE client_id IS NULL AND report_run_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                f"UPDATE {table_name} SET archived_at = CURRENT_TIMESTAMP "
                "WHERE report_run_id IS NULL AND archived_at IS NULL"
            )
        )

    message_existing = {
        column["name"]
        for column in inspect(engine).get_columns("ai_messages", schema=schema)
    }
    if "chatkit_item_id" not in message_existing:
        message_table = _table_name(engine, "ai_messages")
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {message_table} ADD COLUMN chatkit_item_id "
                    "VARCHAR NOT NULL DEFAULT ''"
                )
            )


def _ensure_multi_report_columns_and_indexes(engine: Engine) -> None:
    """Add, backfill, and index the multi-report identity in a safe order."""

    schema = _schema(engine)
    inspector = inspect(engine)
    report_columns = {
        column["name"] for column in inspector.get_columns("report_runs", schema=schema)
    }
    report_specs = {
        "report_kind": ("VARCHAR NOT NULL DEFAULT 'marketplace_unit_economics'"),
        "organization_id": "VARCHAR",
    }
    report_table = _table_name(engine, "report_runs")
    refresh_table = _table_name(engine, "source_refresh_runs")
    with engine.begin() as connection:
        for column, definition in report_specs.items():
            if column not in report_columns:
                connection.execute(
                    text(f"ALTER TABLE {report_table} ADD COLUMN {column} {definition}")
                )
        connection.execute(
            text(
                f"UPDATE {report_table} "
                "SET report_kind = 'marketplace_unit_economics' "
                "WHERE report_kind IS NULL OR report_kind = ''"
            )
        )

    inspector = inspect(engine)
    refresh_columns = {
        column["name"]
        for column in inspector.get_columns("source_refresh_runs", schema=schema)
    }
    refresh_specs = {
        "target_report_kind": ("VARCHAR NOT NULL DEFAULT 'marketplace_unit_economics'"),
        "organization_id": "VARCHAR",
        "idempotency_key": "VARCHAR NOT NULL DEFAULT ''",
    }
    with engine.begin() as connection:
        for column, definition in refresh_specs.items():
            if column not in refresh_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE {refresh_table} ADD COLUMN {column} {definition}"
                    )
                )

        # Existing publication logic allowed only one current report per client,
        # so the backfilled legacy scope is already unique. The cleanup is still
        # deterministic for manually repaired databases before indexes are added.
        organization_scope_sql = (
            "CASE WHEN report_kind = 'marketplace_unit_economics' THEN '' "
            "ELSE COALESCE(organization_id, '') END"
        )
        duplicates = connection.execute(
            text(
                f"SELECT tenant_id, client_id, report_kind, "
                f"{organization_scope_sql}, COUNT(*) "
                f"FROM {report_table} WHERE is_current = TRUE "
                "GROUP BY tenant_id, client_id, report_kind, "
                f"{organization_scope_sql} HAVING COUNT(*) > 1"
            )
        ).fetchall()
        for tenant_id, client_id, report_kind, organization_id, _count in duplicates:
            organization_filter = (
                ""
                if report_kind == "marketplace_unit_economics"
                else "AND COALESCE(organization_id, '') = :organization_id "
            )
            rows = connection.execute(
                text(
                    f"SELECT id FROM {report_table} "
                    "WHERE tenant_id = :tenant_id AND client_id = :client_id "
                    "AND report_kind = :report_kind "
                    f"{organization_filter}"
                    "AND is_current = TRUE "
                    "ORDER BY generated_at DESC, created_at DESC, id DESC"
                ),
                {
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "report_kind": report_kind,
                    "organization_id": organization_id,
                },
            ).fetchall()
            for (report_id,) in rows[1:]:
                connection.execute(
                    text(
                        f"UPDATE {report_table} SET is_current = FALSE, "
                        "publication_status = CASE "
                        "WHEN publication_status = 'published' THEN 'superseded' "
                        "ELSE publication_status END WHERE id = :report_id"
                    ),
                    {"report_id": report_id},
                )

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_report_runs_current_marketplace "
                f"ON {report_table} (tenant_id, client_id, report_kind) "
                "WHERE is_current = TRUE "
                "AND report_kind = 'marketplace_unit_economics'"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_report_runs_current_accounting "
                f"ON {report_table} "
                "(tenant_id, client_id, report_kind, organization_id) "
                "WHERE is_current = TRUE "
                "AND report_kind IN ('month_close_control', 'tax_load') "
                "AND organization_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_source_refresh_idempotency "
                f"ON {refresh_table} (tenant_id, client_id, idempotency_key) "
                "WHERE idempotency_key <> ''"
            )
        )


def _ensure_accounting_evidence_columns_and_indexes(engine: Engine) -> None:
    """Backfill organization-scoped evidence before enforcing uniqueness."""

    schema = _schema(engine)
    inspector = inspect(engine)
    collection_table = _table_name(engine, "source_refresh_collections")
    refresh_table = _table_name(engine, "source_refresh_runs")
    request_table = _table_name(engine, "report_generation_requests")
    collection_columns = {
        column["name"]
        for column in inspector.get_columns("source_refresh_collections", schema=schema)
    }
    refresh_columns = {
        column["name"]
        for column in inspector.get_columns("source_refresh_runs", schema=schema)
    }
    with engine.begin() as connection:
        if "organization_id" not in collection_columns:
            connection.execute(
                text(
                    f"ALTER TABLE {collection_table} ADD COLUMN organization_id VARCHAR"
                )
            )
        if "generation_stage" not in refresh_columns:
            connection.execute(
                text(
                    f"ALTER TABLE {refresh_table} ADD COLUMN generation_stage "
                    "VARCHAR NOT NULL DEFAULT ''"
                )
            )

        evidence_rows = connection.execute(
            text(
                f"SELECT id, refresh_run_id, source_type, payload, loaded_at "
                f"FROM {collection_table} "
                "WHERE source_type IN "
                "('month_close_control_evidence', 'tax_load_evidence') "
                "AND (organization_id IS NULL OR organization_id = '')"
            )
        ).fetchall()
        snapshot_row_table = _table_name(engine, "source_snapshot_rows")
        for (
            collection_id,
            refresh_run_id,
            source_type,
            raw_payload,
            loaded_at,
        ) in evidence_rows:
            payload = raw_payload
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            if not isinstance(payload, dict):
                continue
            normalized = payload.get("normalizedEvidence")
            organization_id = ""
            if isinstance(normalized, dict):
                organization_id = str(normalized.get("organizationId") or "").strip()
            organization_id = (
                organization_id or str(payload.get("organizationId") or "").strip()
            )
            if organization_id:
                existing = connection.execute(
                    text(
                        f"SELECT id, loaded_at FROM {collection_table} "
                        "WHERE refresh_run_id = :refresh_run_id "
                        "AND source_type = :source_type "
                        "AND organization_id = :organization_id "
                        "AND id <> :collection_id "
                        "ORDER BY loaded_at DESC, id DESC LIMIT 1"
                    ),
                    {
                        "refresh_run_id": refresh_run_id,
                        "source_type": source_type,
                        "organization_id": organization_id,
                        "collection_id": collection_id,
                    },
                ).fetchone()
                if existing is not None:
                    current_key = (str(loaded_at or ""), int(collection_id))
                    existing_key = (str(existing[1] or ""), int(existing[0]))
                    discarded_id = (
                        existing[0] if current_key > existing_key else collection_id
                    )
                    connection.execute(
                        text(
                            f"DELETE FROM {snapshot_row_table} "
                            "WHERE collection_id = :collection_id"
                        ),
                        {"collection_id": discarded_id},
                    )
                    connection.execute(
                        text(
                            f"DELETE FROM {collection_table} WHERE id = :collection_id"
                        ),
                        {"collection_id": discarded_id},
                    )
                    if discarded_id == collection_id:
                        continue
                connection.execute(
                    text(
                        f"UPDATE {collection_table} SET organization_id = "
                        ":organization_id "
                        "WHERE id = :collection_id"
                    ),
                    {
                        "organization_id": organization_id,
                        "collection_id": collection_id,
                    },
                )

        duplicates = connection.execute(
            text(
                f"SELECT refresh_run_id, source_type, organization_id, COUNT(*) "
                f"FROM {collection_table} WHERE source_type IN "
                "('month_close_control_evidence', 'tax_load_evidence') "
                "AND organization_id IS NOT NULL AND organization_id <> '' "
                "GROUP BY refresh_run_id, source_type, organization_id "
                "HAVING COUNT(*) > 1"
            )
        ).fetchall()
        for refresh_run_id, source_type, organization_id, _count in duplicates:
            rows = connection.execute(
                text(
                    f"SELECT id FROM {collection_table} "
                    "WHERE refresh_run_id = :refresh_run_id "
                    "AND source_type = :source_type "
                    "AND organization_id = :organization_id "
                    "ORDER BY loaded_at DESC, id DESC"
                ),
                {
                    "refresh_run_id": refresh_run_id,
                    "source_type": source_type,
                    "organization_id": organization_id,
                },
            ).fetchall()
            for (collection_id,) in rows[1:]:
                connection.execute(
                    text(
                        f"DELETE FROM {snapshot_row_table} "
                        "WHERE collection_id = :collection_id"
                    ),
                    {"collection_id": collection_id},
                )
                connection.execute(
                    text(f"DELETE FROM {collection_table} WHERE id = :collection_id"),
                    {"collection_id": collection_id},
                )

        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_source_refresh_accounting_evidence "
                f"ON {collection_table} "
                "(refresh_run_id, source_type, organization_id) "
                "WHERE source_type IN "
                "('month_close_control_evidence', 'tax_load_evidence') "
                "AND organization_id IS NOT NULL AND organization_id <> ''"
            )
        )

        legacy_requests = connection.execute(
            text(
                "SELECT id, tenant_id, client_id, idempotency_key, "
                "target_report_kind, organization_id, period_start, period_end, "
                f"created_at FROM {refresh_table} "
                "WHERE mode = 'report-generation' AND idempotency_key <> ''"
            )
        ).fetchall()
        for row in legacy_requests:
            fingerprint_payload = {
                "reportKind": str(row[4] or ""),
                "organizationId": str(row[5] or ""),
                "periodStart": str(row[6] or ""),
                "periodEnd": str(row[7] or ""),
            }
            fingerprint = hashlib.sha256(
                json.dumps(
                    fingerprint_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            request_id = hashlib.sha256(
                f"{row[1]}:{row[2]}:{row[3]}".encode()
            ).hexdigest()
            connection.execute(
                text(
                    f"INSERT INTO {request_table} "
                    "(id, tenant_id, client_id, idempotency_key, "
                    "request_fingerprint, generation_run_id, created_at) "
                    "VALUES (:id, :tenant_id, :client_id, :idempotency_key, "
                    ":request_fingerprint, :generation_run_id, :created_at) "
                    "ON CONFLICT (tenant_id, client_id, idempotency_key) DO NOTHING"
                ),
                {
                    "id": request_id,
                    "tenant_id": row[1],
                    "client_id": row[2],
                    "idempotency_key": row[3],
                    "request_fingerprint": fingerprint,
                    "generation_run_id": row[0],
                    "created_at": row[8] or datetime.now(UTC),
                },
            )


def _ensure_report_unit_row_columns(engine: Engine) -> None:
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns("report_unit_rows", schema=schema)
    }
    bool_default = "0" if schema is None else "FALSE"
    column_specs = {
        "document_report": "VARCHAR NOT NULL DEFAULT ''",
        "wb_report_id": "VARCHAR NOT NULL DEFAULT ''",
        "wb_report_date": "VARCHAR NOT NULL DEFAULT ''",
        "vat_output": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input_from_wb": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input_from_1c": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input_from_import_scenario": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input_from_wb_scenario": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input_difference": "NUMERIC NOT NULL DEFAULT 0",
        "vat_input_completeness": "VARCHAR NOT NULL DEFAULT ''",
        "input_vat_mode": "VARCHAR NOT NULL DEFAULT 'accounting_fact'",
        "vat_input_confirmed": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "vat_payable": "NUMERIC NOT NULL DEFAULT 0",
        "income_tax_kind": "VARCHAR NOT NULL DEFAULT ''",
        "income_tax_base": "NUMERIC NOT NULL DEFAULT 0",
        "income_tax": "NUMERIC NOT NULL DEFAULT 0",
        "income_tax_included": "BOOLEAN NOT NULL DEFAULT FALSE",
        "tax_method": "VARCHAR",
        "tax_profile_source": "VARCHAR",
        "tax_completeness": "VARCHAR NOT NULL DEFAULT ''",
        "pnl_vat_mode": "VARCHAR NOT NULL DEFAULT ''",
        "unit_cost": "NUMERIC",
        "cost_method": "VARCHAR NOT NULL DEFAULT ''",
        "cost_match_status": "VARCHAR NOT NULL DEFAULT ''",
        "cost_source_kind": "VARCHAR NOT NULL DEFAULT ''",
        "cost_source_period_start": "DATE",
        "cost_source_period_end": "DATE",
        "cost_source_document": "TEXT NOT NULL DEFAULT ''",
        "accounting_period_date": "DATE",
        "accounting_period_source": "VARCHAR NOT NULL DEFAULT ''",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    table_name = _table_name(engine, "report_unit_rows")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_report_unit_rows_accounting_period "
                f"ON {table_name} (report_run_id, accounting_period_date)"
            )
        )


def _ensure_report_lost_sales_columns(engine: Engine) -> None:
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns(
            "report_lost_sales_rows", schema=schema
        )
    }
    column_specs = {
        "onec_stock_quantity": "NUMERIC NOT NULL DEFAULT 0",
        "onec_warehouses": "TEXT NOT NULL DEFAULT ''",
        "calculation_context": "JSON NOT NULL DEFAULT '{}'",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    if not missing:
        return
    table_name = _table_name(engine, "report_lost_sales_rows")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )


def _ensure_report_reconciliation_monthly_columns(engine: Engine) -> None:
    schema = _schema(engine)
    existing_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(
            "report_reconciliation_monthly", schema=schema
        )
    }
    existing = set(existing_columns)
    column_specs = {
        "wb_quantity": "NUMERIC NOT NULL DEFAULT 0",
        "onec_quantity": "NUMERIC",
        "quantity_delta": "NUMERIC",
        "status": "VARCHAR NOT NULL DEFAULT ''",
        "wb_basis": "TEXT NOT NULL DEFAULT ''",
        "onec_basis": "TEXT NOT NULL DEFAULT ''",
        "source_run_id": "VARCHAR NOT NULL DEFAULT ''",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    table_name = _table_name(engine, "report_reconciliation_monthly")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )
        if schema is not None:
            nullable_columns = (
                "onec_quantity",
                "quantity_delta",
                "onec_cogs",
                "cogs_delta",
                "onec_mp_expenses",
                "mp_expenses_delta",
            )
            for column in nullable_columns:
                if (
                    column not in existing_columns
                    or existing_columns[column].get("nullable") is True
                ):
                    continue
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} ALTER COLUMN {column} DROP NOT NULL"
                    )
                )


def _ensure_source_load_columns(engine: Engine) -> None:
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns("source_loads", schema=schema)
    }
    bool_default = "0" if schema is None else "FALSE"
    column_specs = {
        "source_refresh_run_id": "VARCHAR",
        "required": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "publication_required": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "coverage_start": "DATE",
        "coverage_end": "DATE",
        "lineage_role": "VARCHAR NOT NULL DEFAULT 'current'",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    if not missing:
        return
    table_name = _table_name(engine, "source_loads")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )


def _ensure_source_refresh_resume_columns(engine: Engine) -> None:
    schema = _schema(engine)
    bool_default = "0" if schema is None else "FALSE"
    specs = {
        "source_refresh_runs": {
            "resumed_from_run_id": "VARCHAR",
            "base_source_refresh_run_id": "VARCHAR",
            "blocked_by_run_id": "VARCHAR",
            "worker_id": "VARCHAR NOT NULL DEFAULT ''",
            "failure_code": "VARCHAR NOT NULL DEFAULT ''",
            "heartbeat_at": "TIMESTAMP WITH TIME ZONE",
            "source_window_start": "DATE",
            "source_window_end": "DATE",
        },
        "source_refresh_collections": {
            "publication_required": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        },
    }
    inspector = inspect(engine)
    for table, column_specs in specs.items():
        existing = {
            column["name"] for column in inspector.get_columns(table, schema=schema)
        }
        missing = [
            (column, definition)
            for column, definition in column_specs.items()
            if column not in existing
        ]
        if not missing:
            continue
        table_name = _table_name(engine, table)
        with engine.begin() as connection:
            for column, definition in missing:
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
                )


def _ensure_marketplace_operation_fact_columns(engine: Engine) -> None:
    """Add typed marketplace operation fields to an existing deployment."""
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns(
            "marketplace_operation_facts", schema=schema
        )
    }
    bool_default = "0" if schema is None else "FALSE"
    column_specs = {
        "source_row_number": "INTEGER NOT NULL DEFAULT 0",
        "barcode": "VARCHAR NOT NULL DEFAULT ''",
        "product_name": "VARCHAR NOT NULL DEFAULT ''",
        "service_key": "VARCHAR NOT NULL DEFAULT ''",
        "service_name": "VARCHAR NOT NULL DEFAULT ''",
        "logistics": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "storage": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "promotion": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "compensation": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "other_amount": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "price": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "income": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "expense": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "debit_amount": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "credit_amount": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "expenses_loaded": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "is_partial_source": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "source_endpoint": "VARCHAR NOT NULL DEFAULT ''",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    if not missing:
        return
    table_name = _table_name(engine, "marketplace_operation_facts")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )


def _ensure_marketplace_finance_daily_fact_columns(engine: Engine) -> None:
    """Add preallocated calculation fields to an existing deployment."""
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns(
            "marketplace_finance_daily_facts", schema=schema
        )
    }
    column_specs = {
        "spp_discount": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "accounting_service_input_vat": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
        "gross_profit": "NUMERIC(20, 2) NOT NULL DEFAULT 0",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    if not missing:
        return
    table_name = _table_name(engine, "marketplace_finance_daily_facts")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )


def _ensure_report_document_reconciliation_columns(engine: Engine) -> None:
    schema = _schema(engine)
    existing = {
        column["name"]
        for column in inspect(engine).get_columns(
            "report_document_reconciliation_rows", schema=schema
        )
    }
    column_specs = {
        "payout_status": "VARCHAR NOT NULL DEFAULT ''",
        "period_status": "VARCHAR NOT NULL DEFAULT ''",
        "weekly_sales_report_id": "VARCHAR NOT NULL DEFAULT ''",
        "weekly_buyout_report_id": "VARCHAR NOT NULL DEFAULT ''",
        "wb_sales_quantity": "NUMERIC",
        "wb_return_quantity": "NUMERIC",
        "wb_net_quantity": "NUMERIC",
        "onec_sales_quantity": "NUMERIC",
        "onec_return_quantity": "NUMERIC",
        "onec_net_quantity": "NUMERIC",
        "sales_quantity_delta": "NUMERIC",
        "return_quantity_delta": "NUMERIC",
        "net_quantity_delta": "NUMERIC",
        "buyout_retail_amount_sum": "NUMERIC",
        "buyout_for_pay_sum": "NUMERIC",
        "buyout_bank_payment_sum": "NUMERIC",
        "buyout_primary_document_id": "VARCHAR NOT NULL DEFAULT ''",
        "buyout_primary_document_status": "VARCHAR NOT NULL DEFAULT ''",
        "buyout_primary_document_quantity": "NUMERIC",
        "buyout_primary_document_amount": "NUMERIC",
        "buyout_primary_document_delta": "NUMERIC",
        "onec_expense_invoice_amount": "NUMERIC",
        "buyout_retail_delta": "NUMERIC",
        "buyout_for_pay_delta": "NUMERIC",
        "buyout_bank_delta": "NUMERIC",
        "onec_vat": "NUMERIC",
        "onec_cogs": "NUMERIC",
        "onec_cogs_without_vat": "NUMERIC",
        "onec_gross_profit": "NUMERIC",
    }
    missing = [
        (column, definition)
        for column, definition in column_specs.items()
        if column not in existing
    ]
    if not missing:
        return
    table_name = _table_name(engine, "report_document_reconciliation_rows")
    with engine.begin() as connection:
        for column, definition in missing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
            )


def _ensure_multi_client_columns(engine: Engine) -> None:
    specs = {
        "client_companies": {
            "onec_organization_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "report_runs": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "report_unit_rows": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "client_company_id": "VARCHAR NOT NULL DEFAULT ''",
            "wb_cabinet_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "report_lost_sales_rows": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "wb_cabinet_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "report_document_reconciliation_rows": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "client_company_id": "VARCHAR NOT NULL DEFAULT ''",
            "wb_cabinet_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "source_loads": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "wb_cabinet_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "source_refresh_runs": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "source_refresh_collections": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "wb_cabinet_id": "VARCHAR NOT NULL DEFAULT ''",
        },
        "source_snapshot_rows": {
            "client_id": "VARCHAR NOT NULL DEFAULT ''",
            "wb_cabinet_id": "VARCHAR NOT NULL DEFAULT ''",
        },
    }
    schema = _schema(engine)
    inspector = inspect(engine)
    for table, column_specs in specs.items():
        existing = {
            column["name"] for column in inspector.get_columns(table, schema=schema)
        }
        missing = [
            (column, definition)
            for column, definition in column_specs.items()
            if column not in existing
        ]
        if not missing:
            continue
        table_name = _table_name(engine, table)
        with engine.begin() as connection:
            for column, definition in missing:
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")
                )


def _ensure_tax_profile_columns(engine: Engine) -> None:
    schema = _schema(engine)
    inspector = inspect(engine)
    for table in (
        "organization_tax_profiles",
        "organization_tax_profile_overrides",
    ):
        existing = {
            column["name"] for column in inspector.get_columns(table, schema=schema)
        }
        missing_specs = {
            "tax_object": "VARCHAR NOT NULL DEFAULT ''",
            "tax_rate": "NUMERIC NOT NULL DEFAULT 0",
            "elevated_tax_rate": "NUMERIC NOT NULL DEFAULT 0",
            "vat_deduction_mode": "VARCHAR NOT NULL DEFAULT 'unknown'",
            "rate_basis_kind": "VARCHAR NOT NULL DEFAULT ''",
            "basis_document": "TEXT NOT NULL DEFAULT ''",
            "confirmed_by": "VARCHAR NOT NULL DEFAULT ''",
            "source_object_ids": "TEXT NOT NULL DEFAULT '[]'",
        }
        table_name = _table_name(engine, table)
        with engine.begin() as connection:
            for column, definition in missing_specs.items():
                if column not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}"
                        )
                    )


def _ensure_multi_client_indexes(engine: Engine) -> None:
    specs = {
        "source_loads": "ix_source_loads_tenant_client_backfill",
        "source_refresh_runs": "ix_source_refresh_runs_tenant_client_backfill",
        "source_refresh_collections": (
            "ix_source_refresh_collections_tenant_client_backfill"
        ),
        "source_snapshot_rows": "ix_source_snapshot_rows_tenant_client_backfill",
    }
    schema = _schema(engine)
    inspector = inspect(engine)
    missing_specs: list[tuple[str, str]] = []
    for table, index in specs.items():
        existing_indexes = {
            str(item.get("name") or "")
            for item in inspector.get_indexes(table, schema=schema)
        }
        if index not in existing_indexes:
            missing_specs.append((table, index))
    if not missing_specs:
        return
    with engine.begin() as connection:
        if schema is not None:
            connection.execute(text("SET LOCAL statement_timeout = 0"))
        for table, index in missing_specs:
            table_name = _table_name(engine, table)
            connection.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index} "
                    f"ON {table_name} (tenant_id, client_id)"
                )
            )


def _backfill_multi_client_hierarchy(engine: Engine) -> None:
    with Session(engine) as session:
        now = datetime.now(UTC)
        firm = session.get(ConsultingFirm, DEFAULT_CONSULTING_FIRM_ID)
        if firm is None:
            firm = ConsultingFirm(
                id=DEFAULT_CONSULTING_FIRM_ID,
                name=DEFAULT_CONSULTING_FIRM_NAME,
                status="active",
                created_at=now,
                updated_at=now,
            )
            session.add(firm)
            session.flush()
        else:
            firm.updated_at = now

        tenants = list(session.query(Tenant).order_by(Tenant.id))
        for tenant in tenants:
            _ensure_client(session, tenant.id, tenant.name, now)

        for report in session.query(ReportRun).order_by(ReportRun.id):
            if not report.client_id:
                report.client_id = _client_id_for_tenant(report.tenant_id)
            _ensure_client(session, report.tenant_id, report.client_name, now)

        for row in session.query(ReportUnitRow).order_by(ReportUnitRow.id):
            report = session.get(ReportRun, row.report_run_id)
            if report is None:
                continue
            client_id = (
                row.client_id
                or report.client_id
                or _client_id_for_tenant(report.tenant_id)
            )
            row.client_id = client_id
            company = _ensure_client_company(
                session,
                tenant_id=report.tenant_id,
                client_id=client_id,
                display_name=row.organization,
                now=now,
            )
            if company is not None and not row.client_company_id:
                row.client_company_id = company.id
            cabinet = _ensure_wb_cabinet(
                session,
                tenant_id=report.tenant_id,
                client_id=client_id,
                display_name=row.cabinet,
                client_company_id=row.client_company_id,
                now=now,
            )
            if cabinet is not None and not row.wb_cabinet_id:
                row.wb_cabinet_id = cabinet.id

        for row in session.query(ReportLostSalesRow).order_by(ReportLostSalesRow.id):
            report = session.get(ReportRun, row.report_run_id)
            if report is None:
                continue
            client_id = (
                row.client_id
                or report.client_id
                or _client_id_for_tenant(report.tenant_id)
            )
            row.client_id = client_id
            cabinet = _ensure_wb_cabinet(
                session,
                tenant_id=report.tenant_id,
                client_id=client_id,
                display_name=row.cabinet,
                now=now,
            )
            if cabinet is not None and not row.wb_cabinet_id:
                row.wb_cabinet_id = cabinet.id

        for row in session.query(ReportDocumentReconciliationRow).order_by(
            ReportDocumentReconciliationRow.id
        ):
            report = session.get(ReportRun, row.report_run_id)
            if report is None:
                continue
            client_id = (
                row.client_id
                or report.client_id
                or _client_id_for_tenant(report.tenant_id)
            )
            row.client_id = client_id
            company = _ensure_client_company(
                session,
                tenant_id=report.tenant_id,
                client_id=client_id,
                display_name=row.organization,
                now=now,
            )
            if company is not None and not row.client_company_id:
                row.client_company_id = company.id
            cabinet = _ensure_wb_cabinet(
                session,
                tenant_id=report.tenant_id,
                client_id=client_id,
                display_name=row.cabinet,
                client_company_id=row.client_company_id,
                now=now,
            )
            if cabinet is not None and not row.wb_cabinet_id:
                row.wb_cabinet_id = cabinet.id

        for integration in session.query(TenantIntegration).order_by(
            TenantIntegration.tenant_id, TenantIntegration.provider
        ):
            client_id = _client_id_for_tenant(integration.tenant_id)
            payload = dict(integration.config_payload or {})
            company = _ensure_client_company(
                session,
                tenant_id=integration.tenant_id,
                client_id=client_id,
                display_name=str(payload.get("organizationName") or "").strip(),
                now=now,
            )
            if company is not None and not payload.get("clientCompanyId"):
                payload["clientCompanyId"] = company.id
            if _provider_base(integration.provider) == "wb_api":
                cabinet = _ensure_wb_cabinet(
                    session,
                    tenant_id=integration.tenant_id,
                    client_id=client_id,
                    display_name=(
                        str(payload.get("cabinetName") or "").strip()
                        or integration.label
                        or integration.provider
                    ),
                    cabinet_key=str(
                        payload.get("connectionKey") or integration.provider
                    ),
                    provider=integration.provider,
                    client_company_id=str(payload.get("clientCompanyId") or ""),
                    now=now,
                )
                if cabinet is not None and not payload.get("wbCabinetId"):
                    payload["wbCabinetId"] = cabinet.id
            integration.config_payload = payload
            integration.updated_at = now

        tenant_client_ids = {
            tenant.id: _client_id_for_tenant(tenant.id) for tenant in tenants
        }
        session.commit()
        _bulk_backfill_source_client_ids(session, SourceRefreshRun, tenant_client_ids)
        _bulk_backfill_source_client_ids(
            session, SourceRefreshCollection, tenant_client_ids
        )
        _bulk_backfill_source_client_ids(session, SourceLoad, tenant_client_ids)
        # Historical raw snapshot rows can be very large in production. New rows are
        # written with client_id, and legacy rows still retain tenant_id for isolation.
        if _schema(engine) is None:
            _bulk_backfill_source_client_ids(
                session, SourceSnapshotRow, tenant_client_ids
            )

        session.commit()


def _bulk_backfill_source_client_ids(
    session: Session,
    model: type[SourceRefreshRun]
    | type[SourceRefreshCollection]
    | type[SourceSnapshotRow]
    | type[SourceLoad],
    tenant_client_ids: dict[str, str],
) -> None:
    for tenant_id, client_id in tenant_client_ids.items():
        if _schema(session.bind) is None:
            session.query(model).filter(
                model.tenant_id == tenant_id,
                model.client_id == "",
            ).update(
                {model.client_id: client_id},
                synchronize_session=False,
            )
            continue

        table_name = _table_name(session.bind, model.__tablename__)
        batch_size = 1000
        while True:
            result = session.execute(
                text(
                    "WITH batch AS ("
                    f"SELECT ctid FROM {table_name} "
                    "WHERE tenant_id = :tenant_id AND client_id = '' "
                    "LIMIT :batch_size"
                    ") "
                    f"UPDATE {table_name} target "
                    "SET client_id = :client_id "
                    "FROM batch "
                    "WHERE target.ctid = batch.ctid"
                ),
                {
                    "tenant_id": tenant_id,
                    "client_id": client_id,
                    "batch_size": batch_size,
                },
            )
            session.commit()
            if result.rowcount < batch_size:
                break


def _ensure_client(
    session: Session,
    tenant_id: str,
    display_name: str,
    now: datetime,
) -> Client:
    client_id = _client_id_for_tenant(tenant_id)
    client = session.get(Client, client_id)
    if client is None:
        client = Client(
            id=client_id,
            firm_id=DEFAULT_CONSULTING_FIRM_ID,
            tenant_id=tenant_id,
            name=display_name or tenant_id,
            status="active",
            default_report_settings={},
            created_at=now,
            updated_at=now,
        )
        session.add(client)
    else:
        client.firm_id = client.firm_id or DEFAULT_CONSULTING_FIRM_ID
        client.tenant_id = tenant_id
        client.name = client.name or display_name or tenant_id
        client.updated_at = now
    return client


def _ensure_client_company(
    session: Session,
    *,
    tenant_id: str,
    client_id: str,
    display_name: str,
    now: datetime,
) -> ClientCompany | None:
    label = display_name.strip()
    if not label:
        return None
    source_key = _stable_key(label)
    company_id = _stable_id("company", client_id, source_key)
    company = session.get(ClientCompany, company_id)
    if company is None:
        company = ClientCompany(
            id=company_id,
            tenant_id=tenant_id,
            client_id=client_id,
            display_name=label,
            source_key=source_key,
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(company)
    else:
        company.display_name = company.display_name or label
        company.updated_at = now
    return company


def _ensure_wb_cabinet(
    session: Session,
    *,
    tenant_id: str,
    client_id: str,
    display_name: str,
    now: datetime,
    cabinet_key: str = "",
    provider: str = "",
    client_company_id: str = "",
) -> WbCabinet | None:
    label = display_name.strip()
    key = _stable_key(cabinet_key or label)
    if not key:
        return None
    cabinet_id = _stable_id("wb", client_id, key)
    cabinet = session.get(WbCabinet, cabinet_id)
    if cabinet is None:
        cabinet = _matching_wb_cabinet(
            session,
            client_id=client_id,
            label=label,
            cabinet_key=key,
            provider=provider,
        )
    if cabinet is None:
        cabinet = WbCabinet(
            id=cabinet_id,
            tenant_id=tenant_id,
            client_id=client_id,
            client_company_id=client_company_id or None,
            display_name=label or key,
            cabinet_key=key,
            provider=provider,
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(cabinet)
    else:
        cabinet.display_name = cabinet.display_name or label or key
        cabinet.provider = cabinet.provider or provider
        if client_company_id and not cabinet.client_company_id:
            cabinet.client_company_id = client_company_id
        cabinet.updated_at = now
    return cabinet


def _matching_wb_cabinet(
    session: Session,
    *,
    client_id: str,
    label: str,
    cabinet_key: str,
    provider: str,
) -> WbCabinet | None:
    label_key = _stable_key(label)
    candidates = [
        item
        for item in session.query(WbCabinet)
        .filter(WbCabinet.client_id == client_id)
        .all()
        if (label and item.display_name == label)
        or (label_key and item.cabinet_key == label_key)
        or (provider and item.provider == provider)
        or (cabinet_key and item.cabinet_key == cabinet_key)
    ]
    if not candidates:
        return None

    def sort_key(item: WbCabinet) -> tuple[int, int, int, int, datetime, str]:
        return (
            int(not label or item.display_name != label),
            int(not label_key or item.cabinet_key != label_key),
            int(not provider or item.provider != provider),
            int(item.status != "active"),
            item.created_at,
            item.id,
        )

    return sorted(candidates, key=sort_key)[0]


def _client_id_for_tenant(tenant_id: str) -> str:
    candidate = tenant_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        return candidate
    return _stable_id("client", tenant_id)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _stable_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9а-яё]+", "_", value.strip().lower())
    return normalized.strip("_")


def _provider_base(provider: str) -> str:
    return provider.split(":", 1)[0]
