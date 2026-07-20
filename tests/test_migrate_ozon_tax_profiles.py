from __future__ import annotations

from sqlalchemy import create_engine, text

from scripts.migrate_ozon_tax_profiles import _dry_run_summary


def test_migration_dry_run_uses_organization_run_and_checks_global_positions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    statements = (
        "CREATE TABLE clients (id TEXT PRIMARY KEY, status TEXT)",
        "CREATE TABLE source_refresh_runs ("
        "id TEXT PRIMARY KEY, client_id TEXT, created_at TEXT, status TEXT)",
        "CREATE TABLE source_snapshot_rows ("
        "refresh_run_id TEXT, collection_id INTEGER, row_number INTEGER, "
        "source_type TEXT, wb_cabinet_id TEXT, raw_payload_hash TEXT, "
        "row_payload JSON)",
        "CREATE TABLE source_refresh_collections ("
        "refresh_run_id TEXT, source_type TEXT)",
        "CREATE TABLE client_companies ("
        "id TEXT, client_id TEXT, display_name TEXT, source_key TEXT, "
        "status TEXT, onec_organization_id TEXT)",
        "CREATE TABLE wb_cabinets ("
        "id TEXT, client_id TEXT, status TEXT, provider TEXT, "
        "client_company_id TEXT)",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text("INSERT INTO clients VALUES ('client', 'active')")
        )
        connection.execute(
            text(
                "INSERT INTO source_refresh_runs VALUES "
                "('old', 'client', '2026-07-01', 'report_created'), "
                "('new', 'client', '2026-07-02', 'report_created'), "
                "('other', 'other-client', '2026-07-03', 'failed')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO source_snapshot_rows VALUES "
                "('old', 1, 1, 'onec_organizations', '', 'org', '{}'), "
                "('other', 2, 1, 'ozon_realization', '', 'a', '{}'), "
                "('other', 2, 1, 'ozon_realization', '', 'b', '{}')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO source_refresh_collections "
                "VALUES ('old', 'onec_organizations')"
            )
        )

    summary = _dry_run_summary(engine)

    assert summary["targetRuns"] == 1
    assert summary["positionDuplicateGroups"] == 1
