from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from wb_unit_economics.web.database import (
    DB_FIRST_SCHEMA_VERSION,
    LOGISTICS_DIMENSIONS_SCHEMA_VERSION,
    init_db,
    make_engine,
    schema_version,
)


def test_factor_marts_created_with_nullable_facts(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)

    assert DB_FIRST_SCHEMA_VERSION == LOGISTICS_DIMENSIONS_SCHEMA_VERSION
    assert schema_version(engine) == LOGISTICS_DIMENSIONS_SCHEMA_VERSION

    inspector = inspect(engine)

    dim_cols = {
        column["name"]: column
        for column in inspector.get_columns("report_logistics_dimension_rows")
    }
    assert dim_cols, "dimension mart table must exist"
    assert {"report_run_id", "product_ref", "source_hash_digest"} <= set(dim_cols)
    # габариты/вес/сигнал nullable: пропуск остаётся явным, а не нулём
    assert dim_cols["length_cm"]["nullable"] is True
    assert dim_cols["weight_brutto_kg"]["nullable"] is True
    assert dim_cols["dimensions_valid"]["nullable"] is True
    assert dim_cols["measured_penalty_amount"]["nullable"] is True

    route_cols = {
        column["name"]: column
        for column in inspector.get_columns("report_logistics_route_rows")
    }
    assert route_cols, "route mart table must exist"
    assert {"warehouse", "destination", "chain_count"} <= set(route_cols)
    assert route_cols["week_coefficient"]["nullable"] is True
    assert route_cols["logistics_total"]["nullable"] is False

    context_cols = {
        column["name"]
        for column in inspector.get_columns("report_logistics_dimension_contexts")
    }
    assert {
        "report_run_id",
        "factor_methodology_version",
        "data_status",
        "input_hash",
        "source_snapshot_hash",
        "dimension_row_count",
        "blocking_reasons",
    } <= context_cols
    report_columns = {
        column["name"] for column in inspector.get_columns("report_runs")
    }
    assert "logistics_dimensions_required" in report_columns
