from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

from wb_unit_economics.logistics_analysis import (
    LOGISTICS_MEASUREMENTS_METHODOLOGY_VERSION,
    LOGISTICS_ROUTES_METHODOLOGY_VERSION,
    LOGISTICS_TARIFFS_METHODOLOGY_VERSION,
    build_measurement_rows,
    build_route_rows,
    build_tariff_rows,
    logistics_chain_key,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import (
    DB_FIRST_SCHEMA_VERSION,
    LOGISTICS_DIMENSIONS_SCHEMA_VERSION,
    LOGISTICS_MEASUREMENTS_SCHEMA_VERSION,
    LOGISTICS_RETURN_REASONS_SCHEMA_VERSION,
    LOGISTICS_ROUTES_SCHEMA_VERSION,
    LOGISTICS_TARIFFS_SCHEMA_VERSION,
    SOURCE_REFRESH_QUEUE_SCHEMA_VERSION,
    init_db,
    make_engine,
    make_session_factory,
    schema_version,
)
from wb_unit_economics.web.models import (
    Client,
    ClientCompany,
    ConsultingFirm,
    ReportRun,
    Tenant,
    WbCabinet,
)


def test_factor_marts_created_with_nullable_facts(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)

    assert LOGISTICS_DIMENSIONS_SCHEMA_VERSION < LOGISTICS_TARIFFS_SCHEMA_VERSION
    assert LOGISTICS_ROUTES_SCHEMA_VERSION != LOGISTICS_TARIFFS_SCHEMA_VERSION
    assert LOGISTICS_MEASUREMENTS_SCHEMA_VERSION != LOGISTICS_ROUTES_SCHEMA_VERSION
    assert (
        LOGISTICS_RETURN_REASONS_SCHEMA_VERSION
        != LOGISTICS_MEASUREMENTS_SCHEMA_VERSION
    )
    assert SOURCE_REFRESH_QUEUE_SCHEMA_VERSION > LOGISTICS_RETURN_REASONS_SCHEMA_VERSION
    assert DB_FIRST_SCHEMA_VERSION == SOURCE_REFRESH_QUEUE_SCHEMA_VERSION
    assert schema_version(engine) == SOURCE_REFRESH_QUEUE_SCHEMA_VERSION

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
    assert {
        "financial_date",
        "product_ref",
        "chain_key",
        "warehouse",
        "destination",
        "chain_count",
        "coefficient_status",
    } <= set(route_cols)
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
    assert "logistics_tariffs_required" in report_columns
    assert "logistics_routes_required" in report_columns
    assert "logistics_measurements_required" in report_columns
    assert "logistics_return_reasons_required" in report_columns

    tariff_cols = {
        column["name"]: column
        for column in inspector.get_columns("report_logistics_tariff_rows")
    }
    assert {
        "financial_week_start",
        "tariff_type",
        "warehouse",
        "delivery_coefficient_pct",
        "storage_coefficient_pct",
        "evidence_type",
    } <= set(tariff_cols)
    assert tariff_cols["delivery_coefficient_pct"]["nullable"] is True
    assert tariff_cols["storage_coefficient_pct"]["nullable"] is True

    tariff_context_cols = {
        column["name"]
        for column in inspector.get_columns("report_logistics_tariff_contexts")
    }
    assert {
        "factor_methodology_version",
        "factor_snapshot_date",
        "expected_point_count",
        "factual_point_count",
        "estimated_point_count",
        "unavailable_point_count",
        "blocking_reasons",
    } <= tariff_context_cols

    route_context_cols = {
        column["name"]
        for column in inspector.get_columns("report_logistics_route_contexts")
    }
    assert {
        "factor_methodology_version",
        "source_coverage_start",
        "route_row_count",
        "total_chain_count",
        "matched_chain_count",
        "reconciliation_delta",
        "blocking_reasons",
    } <= route_context_cols

    measurement_cols = {
        column["name"]: column
        for column in inspector.get_columns("report_logistics_measurement_rows")
    }
    assert {
        "dim_id",
        "nm_id",
        "event_kind",
        "measurement_at",
        "penalty_effective_at",
        "penalty_amount",
        "reversal_amount",
        "net_penalty_amount",
        "included_in_financial_kpi",
    } <= set(measurement_cols)
    assert measurement_cols["product_ref"]["nullable"] is True
    assert measurement_cols["penalty_amount"]["nullable"] is True

    measurement_context_cols = {
        column["name"]
        for column in inspector.get_columns(
            "report_logistics_measurement_contexts"
        )
    }
    assert {
        "penalty_source_snapshot_hash",
        "warehouse_source_snapshot_hash",
        "factor_snapshot_at",
        "source_coverage_start",
        "source_coverage_end",
        "complete_endpoint_count",
        "measurement_row_count",
        "unmatched_event_count",
        "ambiguous_event_count",
        "blocking_reasons",
    } <= measurement_context_cols

    return_reason_cols = {
        column["name"]: column
        for column in inspector.get_columns("report_logistics_return_reason_rows")
    }
    assert {
        "chain_key",
        "event_date",
        "product_ref",
        "reason_category",
        "reason_source",
        "evidence_type",
        "match_status",
        "claim_available",
        "has_user_comment",
        "row_hash",
    } <= set(return_reason_cols)
    assert return_reason_cols["reason_category"]["nullable"] is True
    assert return_reason_cols["claim_available"]["nullable"] is True

    return_reason_context_cols = {
        column["name"]
        for column in inspector.get_columns(
            "report_logistics_return_reason_contexts"
        )
    }
    assert {
        "methodology_version",
        "data_status",
        "goods_return_source_status",
        "claims_source_status",
        "goods_return_coverage_start",
        "claims_coverage_end",
        "finance_return_chain_count",
        "return_reason_row_count",
        "blocking_reasons",
        "review_reasons",
    } <= return_reason_context_cols


def _tariff_sku(**changes):
    values = {
        "tenant_id": "tenant",
        "client_id": "client",
        "wb_cabinet_id": "cabinet",
        "client_company_id": "company",
        "scheme": "fbo",
        "financial_week_start": date(2026, 4, 6),
        "source_hash_digest": "sku-hash",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _measurement_sku(**changes):
    values = {
        "tenant_id": "tenant",
        "client_id": "client",
        "wb_cabinet_id": "cabinet-a",
        "client_company_id": "company",
        "scheme": "fbo",
        "product_ref": "product-ref",
        "product": "Товар",
        "nm_id": "101",
        "source_hash_digest": "sku-hash",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _measurement_penalty(**changes):
    values = {
        "tenant_id": "tenant",
        "client_id": "client",
        "wb_cabinet_id": "cabinet-a",
        "dim_id": "dim-1",
        "nm_id": "101",
        "volume": "2.50",
        "width": "10",
        "length": "25",
        "height": "10",
        "volume_sup": "2",
        "width_sup": "10",
        "length_sup": "20",
        "height_sup": "10",
        "prc_over": "125",
        "dt_bonus": "2026-07-02T01:00:00Z",
        "is_valid": False,
        "is_valid_dt": "2026-07-02T02:00:00Z",
        "penalty_amount": "10",
        "reversal_amount": "15",
        "source_hash": "penalty-hash",
    }
    values.update(changes)
    return values


def _warehouse_measurement(**changes):
    values = {
        "tenant_id": "tenant",
        "client_id": "client",
        "wb_cabinet_id": "cabinet-a",
        "dim_id": "dim-1",
        "nm_id": "101",
        "volume": "2.5",
        "width": "10",
        "length": "25",
        "height": "10",
        "dt": "2026-07-02T00:00:00Z",
        "source_hash": "warehouse-hash",
    }
    values.update(changes)
    return values


def test_build_measurement_rows_merges_exact_event_and_preserves_money() -> None:
    sku_rows = [
        _measurement_sku(),
        _measurement_sku(source_hash_digest="sku-hash-2"),
    ]
    penalty = _measurement_penalty()
    warehouse = _warehouse_measurement()

    rows = build_measurement_rows(
        sku_rows,
        [penalty, dict(penalty)],
        [warehouse, dict(warehouse)],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["event_kind"] == "merged"
    assert row["coverage_status"] == "ready"
    assert row["product_ref"] == "product-ref"
    assert row["measured_calculated_volume_l"] == Decimal("2.50")
    assert row["declared_calculated_volume_l"] == Decimal("2.00")
    assert row["volume_ratio_percent"] == Decimal("125")
    assert row["volume_excess_percent"] == Decimal("25")
    assert row["penalty_amount"] == Decimal("10")
    assert row["reversal_amount"] == Decimal("15")
    assert row["net_penalty_amount"] == Decimal("-5")
    assert row["is_valid"] is False
    assert row["included_in_financial_kpi"] is False
    assert row["accounting_reconciliation_status"] == "unreconciled"
    assert LOGISTICS_MEASUREMENTS_METHODOLOGY_VERSION in (
        "wb-logistics-measurements-v1",
    )

    repeated = build_measurement_rows(
        list(reversed(sku_rows)),
        [dict(penalty), penalty],
        [dict(warehouse), warehouse],
    )
    assert repeated[0]["row_uid"] == row["row_uid"]
    assert repeated[0]["source_hash_digest"] == row["source_hash_digest"]


def test_build_measurement_rows_isolates_cabinets_and_mapping_scope() -> None:
    rows = build_measurement_rows(
        [
            _measurement_sku(),
            _measurement_sku(
                wb_cabinet_id="cabinet-b",
                client_company_id="other-company",
                product_ref="other-product",
            ),
        ],
        [
            _measurement_penalty(),
            _measurement_penalty(
                wb_cabinet_id="cabinet-b",
                source_hash="other-penalty-hash",
            ),
        ],
        [],
    )

    assert len(rows) == 2
    mapped = {row["wb_cabinet_id"]: row["product_ref"] for row in rows}
    assert mapped == {
        "cabinet-a": "product-ref",
        "cabinet-b": "other-product",
    }

    ambiguous = build_measurement_rows(
        [
            _measurement_sku(),
            _measurement_sku(
                client_company_id="company-2",
                product_ref="product-ref-2",
            ),
        ],
        [_measurement_penalty()],
        [],
    )[0]
    assert ambiguous["coverage_status"] == "ambiguous_product_scope"
    assert ambiguous["client_company_id"] is None
    assert ambiguous["product_ref"] is None
    assert ambiguous["penalty_amount"] == Decimal("10")

    unmatched = build_measurement_rows([], [_measurement_penalty()], [])[0]
    assert unmatched["coverage_status"] == "unmatched_product"
    assert unmatched["product_ref"] is None


def test_build_measurement_rows_conflicts_fail_closed_without_fanout() -> None:
    penalty = _measurement_penalty()
    conflicting_warehouse = _warehouse_measurement(volume="3")
    row = build_measurement_rows(
        [_measurement_sku()],
        [penalty],
        [conflicting_warehouse],
    )[0]

    assert row["coverage_status"] == "conflicting_measurement"
    assert row["measured_volume_l"] is None
    assert row["penalty_amount"] is None
    assert row["net_penalty_amount"] is None

    repeated_dim = build_measurement_rows(
        [_measurement_sku()],
        [
            penalty,
            _measurement_penalty(nm_id="202", source_hash="other-nm-hash"),
        ],
        [],
    )
    assert len(repeated_dim) == 2
    assert {item["coverage_status"] for item in repeated_dim} == {
        "conflicting_measurement"
    }

    within_endpoint = build_measurement_rows(
        [_measurement_sku()],
        [penalty, _measurement_penalty(volume="4", source_hash="duplicate-hash")],
        [],
    )[0]
    assert within_endpoint["coverage_status"] == "conflicting_measurement"
    assert within_endpoint["event_kind"] == "measurement_penalty"
    assert within_endpoint["measured_volume_l"] is None


def test_build_measurement_rows_keeps_missing_and_invalid_explicit() -> None:
    invalid = _measurement_penalty(
        volume="0",
        width="bad",
        length=None,
        height="-1",
        volume_sup=None,
        width_sup=None,
        length_sup=None,
        height_sup=None,
        prc_over="0",
        penalty_amount="-1",
        reversal_amount="0",
    )
    row = build_measurement_rows([_measurement_sku()], [invalid], [])[0]

    assert row["coverage_status"] == "invalid_measurement"
    assert row["measured_volume_l"] is None
    assert row["measured_width_cm"] is None
    assert row["measured_calculated_volume_l"] is None
    assert row["volume_ratio_percent"] is None
    assert row["penalty_amount"] is None
    assert row["reversal_amount"] == Decimal("0")
    assert row["net_penalty_amount"] is None

    rounded = build_measurement_rows(
        [_measurement_sku()],
        [
            _measurement_penalty(
                volume="1",
                length="10.1",
                width="10.1",
                height="10.1",
                penalty_amount="0",
                reversal_amount="1",
            )
        ],
        [],
    )[0]
    assert rounded["measured_calculated_volume_l"] == Decimal("1.03")
    assert rounded["net_penalty_amount"] == Decimal("-1")


def test_build_tariff_rows_uses_historical_fact_and_current_estimate() -> None:
    sku_rows = [_tariff_sku(), _tariff_sku(source_hash_digest="sku-hash-2")]
    historical_box = {
        "wb_cabinet_id": "cabinet",
        "requested_date": "2026-04-06",
        "tariff_type": "box",
        "warehouse_name": "Склад A",
        "box_delivery_base": "0",
        "box_delivery_liter": "11,2",
        "box_delivery_coef_expr": "125",
        "box_storage_base": "0,14",
        "box_storage_liter": "0,07",
        "box_storage_coef_expr": "115",
        "source_hash": "box-hash",
    }
    current_pallet = {
        "wb_cabinet_id": "cabinet",
        "requested_date": "2026-07-21",
        "tariff_type": "pallet",
        "warehouse_name": "Склад A",
        "pallet_delivery_expr": "170",
        "pallet_delivery_value_base": "51",
        "pallet_storage_expr": "155",
        "pallet_storage_value_expr": "35.65",
        "source_hash": "pallet-hash",
    }
    rows = build_tariff_rows(
        sku_rows,
        [historical_box, dict(historical_box), current_pallet],
        factor_snapshot_date=date(2026, 7, 21),
    )

    assert len(rows) == 2
    box = next(row for row in rows if row["tariff_type"] == "box")
    pallet = next(row for row in rows if row["tariff_type"] == "pallet")
    assert box["evidence_type"] == "fact"
    assert box["delivery_base_rub"] == Decimal("0")
    assert box["delivery_liter_rub"] == Decimal("11.2")
    assert box["delivery_coefficient_pct"] == Decimal("125")
    assert pallet["evidence_type"] == "estimate"
    assert pallet["tariff_date"] == date(2026, 7, 21)
    assert pallet["storage_coefficient_pct"] == Decimal("155")

    repeated = build_tariff_rows(
        list(reversed(sku_rows)),
        [current_pallet, dict(historical_box), historical_box],
        factor_snapshot_date=date(2026, 7, 21),
    )
    assert [row["row_uid"] for row in repeated] == [row["row_uid"] for row in rows]
    assert [row["source_hash_digest"] for row in repeated] == [
        row["source_hash_digest"] for row in rows
    ]

    conflict = build_tariff_rows(
        sku_rows,
        [
            historical_box,
            {**historical_box, "box_delivery_coef_expr": "135"},
        ],
        factor_snapshot_date=None,
    )
    conflict_box = next(row for row in conflict if row["tariff_type"] == "box")
    assert conflict_box["coverage_status"] == "conflicting_tariff"
    assert conflict_box["delivery_coefficient_pct"] is None
    assert conflict_box["evidence_type"] == "data_unavailable"


def test_build_tariff_rows_keeps_missing_and_invalid_values_explicit() -> None:
    invalid = build_tariff_rows(
        [_tariff_sku()],
        [
            {
                "wb_cabinet_id": "cabinet",
                "requested_date": "2026-04-06",
                "tariff_type": "box",
                "warehouse_name": "Склад A",
                "box_delivery_base": "not-a-number",
                "box_delivery_coef_expr": "-1",
                "box_storage_coef_expr": "0",
                "source_hash": "invalid-box",
            }
        ],
        factor_snapshot_date=date(2026, 7, 21),
    )
    box = next(row for row in invalid if row["tariff_type"] == "box")
    pallet = next(row for row in invalid if row["tariff_type"] == "pallet")

    assert box["coverage_status"] == "invalid_tariff"
    assert box["delivery_base_rub"] is None
    assert box["delivery_coefficient_pct"] is None
    assert box["storage_coefficient_pct"] == Decimal("0")
    assert box["evidence_type"] == "data_unavailable"
    assert pallet["coverage_status"] == "data_unavailable"
    assert pallet["delivery_coefficient_pct"] is None
    assert pallet["storage_coefficient_pct"] is None


def _route_order(
    *,
    cabinet: str = "cabinet",
    order_uid: str = "srid-1",
    nm_id: str = "1001",
    segment: str = "segment-1",
    logistics_total: Decimal = Decimal("100"),
):
    return SimpleNamespace(
        tenant_id="tenant",
        client_id="client",
        wb_cabinet_id=cabinet,
        client_company_id="company",
        scheme="fbo",
        financial_date=date(2026, 4, 7),
        financial_week_start=date(2026, 4, 6),
        product_ref=f"product-{cabinet}-{nm_id}",
        product="Товар",
        vendor_code="ART-1",
        nm_id=nm_id,
        chain_key=logistics_chain_key(
            tenant_id="tenant",
            client_id="client",
            wb_cabinet_id=cabinet,
            order_uid=order_uid,
            product_key=f"nm:{nm_id}",
        ),
        chain_segment_key=segment,
        logistics_total=logistics_total,
        source_hash_digest=f"order-hash-{segment}",
    )


def test_build_route_rows_joins_exact_chain_and_marks_conflicts() -> None:
    ready = _route_order()
    other_cabinet = _route_order(cabinet="cabinet-2", segment="segment-2")
    conflict = _route_order(order_uid="srid-2", segment="segment-3")
    source = [
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "wb_cabinet_id": "cabinet",
            "srid": "srid-1",
            "nm_id": "1001",
            "warehouse_name": "Склад A",
            "country_name": "Страна",
            "region_name": "Регион A",
            "source_hash": "route-a",
        },
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "wb_cabinet_id": "cabinet",
            "srid": "srid-1",
            "nm_id": "1001",
            "warehouse_name": "Склад A",
            "country_name": "Страна",
            "region_name": "Регион A",
            "source_hash": "route-a-duplicate",
        },
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "wb_cabinet_id": "cabinet",
            "srid": "srid-2",
            "nm_id": "1001",
            "warehouse_name": "Склад A",
            "country_name": "Страна",
            "region_name": "Регион A",
            "source_hash": "route-b1",
        },
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "wb_cabinet_id": "cabinet",
            "srid": "srid-2",
            "nm_id": "1001",
            "warehouse_name": "Склад B",
            "country_name": "Страна",
            "region_name": "Регион B",
            "source_hash": "route-b2",
        },
    ]
    tariff = [
        {
            "wb_cabinet_id": "cabinet",
            "client_company_id": "company",
            "scheme": "fbo",
            "financial_week_start": date(2026, 4, 6),
            "tariff_type": "box",
            "warehouse": "Склад A",
            "delivery_coefficient_pct": Decimal("125"),
            "evidence_type": "fact",
            "coverage_status": "ready",
            "source_hash_digest": "tariff-hash",
        }
    ]

    rows = build_route_rows([conflict, other_cabinet, ready], source, tariff)
    by_segment = {row["row_uid"]: row for row in rows}
    assert len(by_segment) == 3
    ready_row = next(row for row in rows if row["chain_key"] == ready.chain_key)
    assert ready_row["warehouse"] == "Склад A"
    assert ready_row["destination"] == "Страна · Регион A"
    assert ready_row["coverage_status"] == "ready"
    assert ready_row["week_coefficient"] == Decimal("125")
    assert ready_row["coefficient_status"] == "ready"

    isolated = next(
        row for row in rows if row["chain_key"] == other_cabinet.chain_key
    )
    assert isolated["warehouse"] == ""
    assert isolated["coverage_status"] == "data_unavailable"
    assert isolated["week_coefficient"] is None

    conflicting = next(row for row in rows if row["chain_key"] == conflict.chain_key)
    assert conflicting["warehouse"] == "mixed"
    assert conflicting["destination"] == "mixed"
    assert conflicting["coverage_status"] == "conflicting_route"

    repeated = build_route_rows(
        list(reversed([conflict, other_cabinet, ready])),
        list(reversed(source)),
        tariff,
    )
    assert [row["row_uid"] for row in repeated] == [
        row["row_uid"] for row in rows
    ]
    assert [row["source_hash_digest"] for row in repeated] == [
        row["source_hash_digest"] for row in rows
    ]


def _seed_tariff_report(db) -> ReportRun:
    now = datetime(2026, 7, 21, 12, 0)
    db.add(Tenant(id="tenant", name="Tenant", created_at=now))
    db.add(
        ConsultingFirm(
            id="firm",
            name="Firm",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        Client(
            id="client",
            firm_id="firm",
            tenant_id="tenant",
            name="Client",
            status="active",
            default_report_settings={},
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        ClientCompany(
            id="company",
            tenant_id="tenant",
            client_id="client",
            display_name="Company",
            source_key="company",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        WbCabinet(
            id="cabinet",
            tenant_id="tenant",
            client_id="client",
            client_company_id="company",
            display_name="Cabinet",
            cabinet_key="cabinet",
            provider="wb_api",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    report = ReportRun(
        id="report",
        tenant_id="tenant",
        client_id="client",
        client_name="Client",
        title="Report",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        generated_at=now,
        status="ready",
        publication_status="draft",
        is_current=False,
        methodology_version="unit-economics-v1",
        source_workbook="",
        source_workbook_path="",
        return_reason_limitation="",
        created_at=now,
    )
    db.add(report)
    db.flush()
    return report


def _tariff_context(report: ReportRun, rows, *, tenant_id: str = "tenant"):
    points = {
        (
            row["wb_cabinet_id"],
            row["client_company_id"],
            row["scheme"],
            row["financial_week_start"],
            row["tariff_type"],
        )
        for row in rows
    }
    factual = {
        (
            row["wb_cabinet_id"],
            row["client_company_id"],
            row["scheme"],
            row["financial_week_start"],
            row["tariff_type"],
        )
        for row in rows
        if row["evidence_type"] == "fact" and row["coverage_status"] == "ready"
    }
    return {
        "tenant_id": tenant_id,
        "client_id": report.client_id,
        "factor_methodology_version": LOGISTICS_TARIFFS_METHODOLOGY_VERSION,
        "data_status": "ready" if points == factual else "partial",
        "input_hash": "input-hash",
        "source_snapshot_hash": "snapshot-hash",
        "source_loaded_at": datetime(2026, 7, 21, 12, 0),
        "factor_snapshot_date": date(2026, 7, 21),
        "source_row_count": len(rows),
        "tariff_row_count": len(rows),
        "expected_point_count": len(points),
        "factual_point_count": len(factual),
        "estimated_point_count": 0,
        "unavailable_point_count": len(points - factual),
        "invalid_row_count": 0,
        "conflicting_row_count": 0,
        "warehouse_count": 1,
        "blocking_reasons": [],
        "review_reasons": [],
        "created_at": datetime(2026, 7, 21, 12, 1),
    }


def test_tariff_analysis_is_atomic_and_published_report_is_immutable(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = _seed_tariff_report(db)
        rows = build_tariff_rows(
            [_tariff_sku()],
            [
                {
                    "wb_cabinet_id": "cabinet",
                    "requested_date": "2026-04-06",
                    "tariff_type": "box",
                    "warehouse_name": "Склад A",
                    "box_delivery_coef_expr": "125",
                    "box_storage_coef_expr": "115",
                }
            ],
            factor_snapshot_date=date(2026, 7, 21),
        )
        repository.replace_report_logistics_tariff_analysis(
            db,
            report,
            context=_tariff_context(report, rows),
            rows=rows,
        )
        db.flush()
        persisted_uids = sorted(
            row.row_uid for row in db.query(repository.ReportLogisticsTariffRow)
        )

        with pytest.raises(ValueError, match="tenant does not match report"):
            repository.replace_report_logistics_tariff_analysis(
                db,
                report,
                context=_tariff_context(report, rows, tenant_id="other"),
                rows=rows,
            )
        assert sorted(
            row.row_uid for row in db.query(repository.ReportLogisticsTariffRow)
        ) == persisted_uids
        assert report.logistics_tariffs_required is True

        report.publication_status = "published"
        with pytest.raises(ValueError, match="published logistics tariff"):
            repository.replace_report_logistics_tariff_analysis(
                db,
                report,
                context=_tariff_context(report, rows),
                rows=rows,
            )


def _route_context(report: ReportRun, rows, *, tenant_id: str = "tenant"):
    total = sum((row["logistics_total"] for row in rows), Decimal("0"))
    matched = {row["chain_key"] for row in rows if row["coverage_status"] == "ready"}
    chains = {row["chain_key"] for row in rows}
    return {
        "tenant_id": tenant_id,
        "client_id": report.client_id,
        "factor_methodology_version": LOGISTICS_ROUTES_METHODOLOGY_VERSION,
        "data_status": "ready",
        "input_hash": "route-input-hash",
        "source_snapshot_hash": "route-snapshot-hash",
        "source_loaded_at": datetime(2026, 7, 21, 12, 0),
        "source_coverage_start": date(2026, 4, 1),
        "source_coverage_end": date(2026, 4, 30),
        "source_row_count": 1,
        "route_row_count": len(rows),
        "total_chain_count": len(chains),
        "matched_chain_count": len(matched),
        "missing_chain_count": len(chains - matched),
        "conflicting_chain_count": 0,
        "warehouse_count": 1,
        "destination_count": 1,
        "total_logistics": total,
        "linked_logistics": total,
        "reconciliation_delta": Decimal("0"),
        "blocking_reasons": [],
        "review_reasons": [],
        "created_at": datetime(2026, 7, 21, 12, 1),
    }


def test_route_analysis_is_atomic_and_published_report_is_immutable(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = _seed_tariff_report(db)
        order = _route_order()
        rows = build_route_rows(
            [order],
            [
                {
                    "tenant_id": "tenant",
                    "client_id": "client",
                    "wb_cabinet_id": "cabinet",
                    "srid": "srid-1",
                    "nm_id": "1001",
                    "warehouse_name": "Склад A",
                    "country_name": "Страна",
                    "region_name": "Регион A",
                }
            ],
        )
        repository.replace_report_logistics_route_analysis(
            db,
            report,
            context=_route_context(report, rows),
            rows=rows,
        )
        db.flush()
        persisted_uids = sorted(
            row.row_uid for row in db.query(repository.ReportLogisticsRouteRow)
        )

        with pytest.raises(ValueError, match="tenant does not match report"):
            repository.replace_report_logistics_route_analysis(
                db,
                report,
                context=_route_context(report, rows, tenant_id="other"),
                rows=rows,
            )
        assert sorted(
            row.row_uid for row in db.query(repository.ReportLogisticsRouteRow)
        ) == persisted_uids
        assert report.logistics_routes_required is True

        report.publication_status = "published"
        with pytest.raises(ValueError, match="published logistics route"):
            repository.replace_report_logistics_route_analysis(
                db,
                report,
                context=_route_context(report, rows),
                rows=rows,
            )


def _measurement_context(
    report: ReportRun,
    rows,
    *,
    tenant_id: str = "tenant",
    row_count: int | None = None,
):
    return {
        "tenant_id": tenant_id,
        "client_id": report.client_id,
        "factor_methodology_version": LOGISTICS_MEASUREMENTS_METHODOLOGY_VERSION,
        "data_status": "ready",
        "input_hash": "measurement-input-hash",
        "penalty_source_snapshot_hash": "penalty-snapshot-hash",
        "warehouse_source_snapshot_hash": "warehouse-snapshot-hash",
        "penalty_source_loaded_at": datetime(2026, 7, 21, 12, 0),
        "warehouse_source_loaded_at": datetime(2026, 7, 21, 12, 0),
        "factor_snapshot_at": datetime(2026, 7, 21, 12, 0),
        "source_coverage_start": date(2026, 4, 1),
        "source_coverage_end": date(2026, 4, 30),
        "expected_endpoint_count": 2,
        "complete_endpoint_count": 2,
        "unavailable_endpoint_count": 0,
        "source_event_count": 2,
        "provider_event_count": 2,
        "measurement_row_count": len(rows) if row_count is None else row_count,
        "scoped_product_count": 1,
        "product_with_event_count": 1,
        "matched_event_count": len(rows),
        "unmatched_event_count": 0,
        "ambiguous_event_count": 0,
        "invalid_event_count": 0,
        "conflicting_event_count": 0,
        "penalty_event_count": len(rows),
        "reversal_event_count": len(rows),
        "warehouse_only_event_count": 0,
        "blocking_reasons": [],
        "review_reasons": [],
        "created_at": datetime(2026, 7, 21, 12, 1),
    }


def test_measurement_analysis_is_atomic_and_published_report_is_immutable(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = _seed_tariff_report(db)
        rows = build_measurement_rows(
            [
                _measurement_sku(
                    wb_cabinet_id="cabinet",
                    nm_id="101",
                )
            ],
            [
                _measurement_penalty(
                    wb_cabinet_id="cabinet",
                    nm_id="101",
                )
            ],
            [
                _warehouse_measurement(
                    wb_cabinet_id="cabinet",
                    nm_id="101",
                )
            ],
        )
        repository.replace_report_logistics_measurement_analysis(
            db,
            report,
            context=_measurement_context(report, rows),
            rows=rows,
        )
        db.flush()
        persisted_uids = sorted(
            row.row_uid for row in db.query(repository.ReportLogisticsMeasurementRow)
        )

        with pytest.raises(ValueError, match="tenant does not match report"):
            repository.replace_report_logistics_measurement_analysis(
                db,
                report,
                context=_measurement_context(report, rows, tenant_id="other"),
                rows=rows,
            )
        assert sorted(
            row.row_uid for row in db.query(repository.ReportLogisticsMeasurementRow)
        ) == persisted_uids
        assert report.logistics_measurements_required is True

        with pytest.raises(ValueError, match="row count does not match"):
            repository.replace_report_logistics_measurement_analysis(
                db,
                report,
                context=_measurement_context(report, rows, row_count=0),
                rows=rows,
            )

        report.publication_status = "published"
        with pytest.raises(ValueError, match="published logistics measurement"):
            repository.replace_report_logistics_measurement_analysis(
                db,
                report,
                context=_measurement_context(report, rows),
                rows=rows,
            )
