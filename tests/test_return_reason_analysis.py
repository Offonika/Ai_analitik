from __future__ import annotations

from datetime import date
from decimal import Decimal

from wb_unit_economics.logistics_analysis import (
    LogisticsOrderRow,
    LogisticsSourceRow,
)
from wb_unit_economics.return_reason_analysis import build_return_reason_analysis
from wb_unit_economics.wb_goods_return import normalize_goods_return_source_row
from wb_unit_economics.wb_return_claims import normalize_claim_source_row


def _finance_row(*, srid: str = "finance-srid") -> LogisticsSourceRow:
    return LogisticsSourceRow(
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        source_row_id="finance-row-1",
        source_hash="finance-hash-1",
        financial_date=date(2026, 7, 20),
        order_date=date(2026, 7, 10),
        order_uid="order-1",
        nm_id="1001",
        sku="sku-1",
        vendor_code="vendor-1",
        product="Товар",
        scheme="fbo",
        warehouse="",
        destination="",
        document_type="",
        operation_name="Возврат",
        quantity=Decimal("-1"),
        retail_amount=Decimal("-100"),
        delivery_service=Decimal("50"),
        delivery_amount=None,
        return_amount=None,
        rebill_logistic_cost=None,
        finance_srid=srid,
    )


def _order_row(*, event_date: date = date(2026, 7, 20)) -> LogisticsOrderRow:
    chain_key = _finance_row().chain_key
    return LogisticsOrderRow(
        chain_key=chain_key,
        chain_segment_key=f"segment-{event_date.isoformat()}",
        countable_order=False,
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        financial_date=event_date,
        financial_week_start=event_date,
        operation_date_start=event_date,
        operation_date_end=event_date,
        order_date=date(2026, 7, 10),
        order_period_status="current_report_period",
        product_ref="product-safe-ref",
        product_key="nm:1001",
        nm_id="1001",
        sku="sku-1",
        vendor_code="vendor-1",
        product="Товар",
        scheme="fbo",
        warehouse="",
        warehouse_status="missing",
        destination="",
        destination_status="missing",
        logistics_total=Decimal("50"),
        logistics_forward=Decimal("0"),
        logistics_reverse=Decimal("50"),
        logistics_adjustment=Decimal("0"),
        logistics_unclassified=Decimal("0"),
        sales_quantity=Decimal("0"),
        return_quantity=Decimal("1"),
        net_quantity=Decimal("-1"),
        source_revenue=Decimal("-100"),
        source_row_count=1,
        logistics_row_count=1,
        classified_row_count=1,
        source_hash_digest="finance-digest",
        classification_status="ready",
        coverage_status="ready",
        data_quality_status="ready",
    )


def _goods_row(*, reason: str | None = "Не подошёл размер"):
    return normalize_goods_return_source_row(
        {
            "srid": "finance-srid",
            "order_id": "provider-order",
            "nm_id": "1001",
            "barcode": "barcode",
            "reason": reason,
            "status": "returned",
            "return_type": "buyer",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
    )


def _claim_row(*, has_user_comment: bool = True):
    return normalize_claim_source_row(
        {
            "srid": "finance-srid",
            "nm_id": "1001",
            "is_archive": False,
            "has_user_comment": has_user_comment,
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
    )


def test_builds_exact_safe_return_reason_row() -> None:
    result = build_return_reason_analysis(
        [_finance_row()],
        [_order_row()],
        [_goods_row()],
        [_claim_row()],
        goods_return_snapshot_hash="goods-snapshot",
        claims_snapshot_hash="claims-snapshot",
        goods_return_coverage_start=date(2026, 7, 1),
        goods_return_coverage_end=date(2026, 7, 23),
        claims_coverage_start=date(2026, 7, 10),
        claims_coverage_end=date(2026, 7, 23),
        claims_source_status="confirmed_nonempty",
    )

    assert result.context.data_status == "ready"
    assert result.context.finance_return_chain_count == 1
    assert result.context.goods_return_reason_available_count == 1
    assert result.context.claims_matched_chain_count == 1
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.reason_category == "Не подошёл размер"
    assert row.reason_source == "goods_return"
    assert row.evidence_type == "fact"
    assert row.match_status == "ready"
    assert row.claim_available is True
    assert row.has_user_comment is True
    assert row.chain_key == _finance_row().chain_key
    assert row.row_hash
    assert row.row_uid


def test_denied_claims_is_partial_not_blocking_and_keeps_reason_fact() -> None:
    result = build_return_reason_analysis(
        [_finance_row()],
        [_order_row()],
        [_goods_row()],
        [],
        goods_return_coverage_start=date(2026, 7, 1),
        goods_return_coverage_end=date(2026, 7, 23),
        claims_coverage_start=date(2026, 7, 10),
        claims_coverage_end=date(2026, 7, 23),
        claims_source_status="access_denied",
        claims_review_reasons=("return_claims_source_access_denied",),
    )

    assert result.context.data_status == "partial"
    assert result.context.blocking_reasons == ()
    assert result.context.claims_source_status == "access_denied"
    assert result.rows[0].reason_category == "Не подошёл размер"
    assert result.rows[0].claim_available is None
    assert result.rows[0].has_user_comment is None


def test_confirmed_empty_claims_only_proves_false_inside_source_window() -> None:
    result = build_return_reason_analysis(
        [_finance_row()],
        [_order_row(event_date=date(2026, 7, 9))],
        [_goods_row()],
        [],
        goods_return_coverage_start=date(2026, 7, 1),
        goods_return_coverage_end=date(2026, 7, 23),
        claims_coverage_start=date(2026, 7, 10),
        claims_coverage_end=date(2026, 7, 23),
        claims_source_status="confirmed_empty",
        claims_review_reasons=("return_claims_source_empty",),
    )

    assert result.rows[0].claim_available is None
    assert result.rows[0].has_user_comment is None

    inside = build_return_reason_analysis(
        [_finance_row()],
        [_order_row(event_date=date(2026, 7, 20))],
        [_goods_row()],
        [],
        goods_return_coverage_start=date(2026, 7, 1),
        goods_return_coverage_end=date(2026, 7, 23),
        claims_coverage_start=date(2026, 7, 10),
        claims_coverage_end=date(2026, 7, 23),
        claims_source_status="confirmed_empty",
        claims_review_reasons=("return_claims_source_empty",),
    )
    assert inside.rows[0].claim_available is False
    assert inside.rows[0].has_user_comment is False


def test_blocking_integrity_failure_persists_no_mart_rows() -> None:
    result = build_return_reason_analysis(
        [_finance_row()],
        [_order_row()],
        [_goods_row()],
        [_claim_row()],
        blocking_reasons=("finance_source_revision_conflict",),
    )

    assert result.context.data_status == "blocked"
    assert result.context.finance_return_chain_count == 1
    assert result.context.return_reason_row_count == 0
    assert result.rows == ()


def test_multiple_return_segments_collapse_to_latest_finance_date() -> None:
    result = build_return_reason_analysis(
        [_finance_row()],
        [
            _order_row(event_date=date(2026, 7, 18)),
            _order_row(event_date=date(2026, 7, 20)),
        ],
        [_goods_row()],
        [],
        goods_return_coverage_start=date(2026, 7, 1),
        goods_return_coverage_end=date(2026, 7, 23),
        claims_source_status="access_denied",
        claims_review_reasons=("return_claims_source_access_denied",),
    )

    assert len(result.rows) == 1
    assert result.rows[0].event_date == date(2026, 7, 20)
