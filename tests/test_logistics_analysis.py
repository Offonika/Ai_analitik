from __future__ import annotations

from datetime import date
from decimal import Decimal

from wb_unit_economics.logistics_analysis import (
    CHAIN_KEY_VERSION,
    LogisticsSourceRow,
    UnitEconomicsSlice,
    build_logistics_analysis,
    classify_logistics_row,
    logistics_chain_key,
    source_row_from_payload,
)


def _source_row(**overrides: object) -> LogisticsSourceRow:
    values: dict[str, object] = {
        "tenant_id": "tenant-1",
        "client_id": "client-1",
        "wb_cabinet_id": "cabinet-1",
        "client_company_id": "company-1",
        "source_row_id": "row-1",
        "source_hash": "hash-1",
        "financial_date": date(2026, 7, 13),
        "order_date": date(2026, 7, 12),
        "order_uid": "order-1",
        "nm_id": "101",
        "sku": "sku-101",
        "vendor_code": "A-101",
        "product": "Товар 101",
        "scheme": "fbo",
        "warehouse": "Коледино",
        "destination": "Россия",
        "document_type": "Логистика",
        "operation_name": "Логистика",
        "quantity": Decimal("0"),
        "retail_amount": Decimal("0"),
        "delivery_service": Decimal("10"),
        "delivery_amount": Decimal("1"),
        "return_amount": Decimal("0"),
        "rebill_logistic_cost": Decimal("0"),
    }
    values.update(overrides)
    return LogisticsSourceRow(**values)  # type: ignore[arg-type]


def _unit_row(**overrides: object) -> UnitEconomicsSlice:
    values: dict[str, object] = {
        "financial_week_start": date(2026, 7, 13),
        "wb_cabinet_id": "cabinet-1",
        "client_company_id": "company-1",
        "scheme": "fbo",
        "nm_id": "101",
        "sku": "sku-101",
        "vendor_code": "A-101",
        "product": "Товар 101",
        "revenue": Decimal("100"),
        "profit_before_tax": Decimal("20"),
        "logistics": Decimal("10"),
    }
    values.update(overrides)
    return UnitEconomicsSlice(**values)  # type: ignore[arg-type]


def test_chain_key_is_scoped_by_cabinet_and_product() -> None:
    first = logistics_chain_key(
        tenant_id="tenant",
        client_id="client",
        wb_cabinet_id="cabinet-1",
        order_uid="order",
        product_key="nm:1",
    )
    same = logistics_chain_key(
        tenant_id="tenant",
        client_id="client",
        wb_cabinet_id="cabinet-1",
        order_uid="order",
        product_key="nm:1",
    )
    other_product = logistics_chain_key(
        tenant_id="tenant",
        client_id="client",
        wb_cabinet_id="cabinet-1",
        order_uid="order",
        product_key="nm:2",
    )
    other_cabinet = logistics_chain_key(
        tenant_id="tenant",
        client_id="client",
        wb_cabinet_id="cabinet-2",
        order_uid="order",
        product_key="nm:1",
    )

    assert CHAIN_KEY_VERSION == "wb-order-product-v1"
    assert first == same
    assert first != other_product
    assert first != other_cabinet
    assert len(first) == 64


def test_classifier_covers_four_categories_and_keeps_amount_sign() -> None:
    forward = _source_row(delivery_service=Decimal("10"))
    reverse = _source_row(
        delivery_service=Decimal("-8"),
        delivery_amount=Decimal("0"),
        return_amount=Decimal("1"),
    )
    adjustment = _source_row(
        delivery_service=Decimal("-2"),
        delivery_amount=Decimal("0"),
        return_amount=Decimal("0"),
        rebill_logistic_cost=Decimal("2"),
    )
    unclassified = _source_row(
        delivery_service=Decimal("3"),
        delivery_amount=Decimal("0"),
        return_amount=Decimal("0"),
        operation_name="Неизвестная операция",
    )

    assert classify_logistics_row(forward) == "forward"
    assert classify_logistics_row(reverse) == "reverse"
    assert classify_logistics_row(adjustment) == "adjustment"
    assert classify_logistics_row(unclassified) == "unclassified"

    unit = _unit_row(logistics=Decimal("3"))
    result = build_logistics_analysis(
        [forward, reverse, adjustment, unclassified], [unit]
    )
    assert result.context.data_status == "partial"
    assert result.context.raw_logistics_total == Decimal("3")
    assert result.order_rows[0].logistics_forward == Decimal("10")
    assert result.order_rows[0].logistics_reverse == Decimal("-8")
    assert result.order_rows[0].logistics_adjustment == Decimal("-2")
    assert result.order_rows[0].logistics_unclassified == Decimal("3")


def test_gate_blocks_missing_key_without_srid_fallback() -> None:
    row = _source_row(order_uid="", delivery_service=Decimal("10"))

    result = build_logistics_analysis([row], [_unit_row()])

    assert result.context.data_status == "blocked"
    assert result.context.blocking_reasons == ("chain_key_coverage_below_100pct",)
    assert result.order_rows == ()
    assert result.sku_rows == ()


def test_gate_blocks_cross_cabinet_collision() -> None:
    rows = [
        _source_row(wb_cabinet_id="cabinet-1", source_hash="hash-1"),
        _source_row(wb_cabinet_id="cabinet-2", source_hash="hash-2"),
    ]
    unit_rows = [
        _unit_row(wb_cabinet_id="cabinet-1"),
        _unit_row(wb_cabinet_id="cabinet-2"),
    ]

    result = build_logistics_analysis(rows, unit_rows)

    assert result.context.data_status == "blocked"
    assert "cross_cabinet_order_uid_collision" in result.context.blocking_reasons


def test_builds_reconciled_order_and_sku_marts_with_low_sample() -> None:
    rows = [
        _source_row(source_row_id="log-1", source_hash="hash-1"),
        _source_row(
            source_row_id="sale-1",
            source_hash="hash-2",
            document_type="Продажа",
            operation_name="Продажа",
            delivery_service=Decimal("0"),
            delivery_amount=Decimal("0"),
            quantity=Decimal("1"),
            retail_amount=Decimal("100"),
        ),
    ]

    result = build_logistics_analysis(rows, [_unit_row()])

    assert result.context.data_status == "ready"
    assert result.context.order_delta == 0
    assert result.context.sku_delta == 0
    assert len(result.order_rows) == 1
    assert result.order_rows[0].sales_quantity == 1
    assert len(result.sku_rows) == 1
    sku = result.sku_rows[0]
    assert sku.chain_count == 1
    assert sku.low_sample is True
    assert sku.logistics_share_pct == Decimal("10")
    assert sku.profit_effect_amount == Decimal("-10")
    assert sku.profit_without_logistics == Decimal("30")
    assert sku.recommendation_flags == ("check_margin",)


def test_result_hash_is_repeatable_and_return_can_reference_previous_order() -> None:
    row = _source_row(
        financial_date=date(2026, 7, 13),
        order_date=date(2026, 6, 30),
        delivery_amount=Decimal("0"),
        return_amount=Decimal("1"),
    )

    first = build_logistics_analysis([row], [_unit_row()])
    second = build_logistics_analysis([row], [_unit_row()])

    assert first.context.input_hash == second.context.input_hash
    assert first.order_rows[0].order_date == date(2026, 6, 30)
    assert first.order_rows[0].classification_status == "ready"


def test_source_payload_uses_nm_id_then_sku_and_does_not_use_srid() -> None:
    row = source_row_from_payload(
        {
            "rrDate": "2026-07-16",
            "orderUid": "order-1",
            "srid": "must-not-be-used",
            "sku": "sku-1",
            "deliveryService": "10",
            "deliveryAmount": 1,
        },
        tenant_id="tenant",
        client_id="client",
        wb_cabinet_id="cabinet",
        source_row_id="row",
        fallback_date=date(2026, 7, 1),
    )

    assert row.product_key == "sku:sku-1"
    assert row.chain_key
