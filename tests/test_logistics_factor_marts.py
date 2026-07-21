from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

from wb_unit_economics.logistics_analysis import (
    LOGISTICS_ROUTES_METHODOLOGY_VERSION,
    LOGISTICS_TARIFFS_METHODOLOGY_VERSION,
    build_route_rows,
    build_tariff_rows,
    logistics_chain_key,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import (
    DB_FIRST_SCHEMA_VERSION,
    LOGISTICS_DIMENSIONS_SCHEMA_VERSION,
    LOGISTICS_ROUTES_SCHEMA_VERSION,
    LOGISTICS_TARIFFS_SCHEMA_VERSION,
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
    assert DB_FIRST_SCHEMA_VERSION == LOGISTICS_ROUTES_SCHEMA_VERSION
    assert schema_version(engine) == LOGISTICS_ROUTES_SCHEMA_VERSION

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
