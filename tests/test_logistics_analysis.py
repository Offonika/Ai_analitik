from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from wb_unit_economics import logistics_analysis
from wb_unit_economics.logistics_analysis import (
    CHAIN_KEY_VERSION,
    LOGISTICS_METHODOLOGY_VERSION,
    LogisticsInputDiagnostics,
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
        "tenant_id": "tenant-1",
        "client_id": "client-1",
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
    assert LOGISTICS_METHODOLOGY_VERSION == "wb-logistics-v4"
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
    assert "invalid_required_source_fields" in result.context.blocking_reasons
    assert "chain_key_coverage_below_100pct" in result.context.blocking_reasons
    assert result.order_rows == ()
    assert result.sku_rows == ()


def test_same_raw_order_uid_in_different_cabinets_is_informational() -> None:
    rows = [
        _source_row(wb_cabinet_id="cabinet-1", source_hash="hash-1"),
        _source_row(wb_cabinet_id="cabinet-2", source_hash="hash-2"),
    ]
    unit_rows = [
        _unit_row(wb_cabinet_id="cabinet-1"),
        _unit_row(wb_cabinet_id="cabinet-2"),
    ]

    result = build_logistics_analysis(rows, unit_rows)

    assert result.context.data_status == "ready"
    assert result.context.cross_cabinet_collision_count == 0
    assert result.context.raw_order_uid_cross_cabinet_reuse_count == 1
    assert len({row.chain_key for row in result.order_rows}) == 2


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
    assert first.order_rows[0].order_period_status == "previous_report_period"
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


def test_invalid_required_payload_values_block_without_silent_defaults() -> None:
    row = source_row_from_payload(
        {
            "rrDate": "damaged-date",
            "orderUid": "order-1",
            "nmId": "101",
            "deliveryMethod": "unknown-scheme",
            "deliveryService": "not-a-number",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        fallback_date=date(2026, 7, 1),
    )

    assert row.financial_date is None
    assert row.scheme == ""
    assert row.delivery_service is None
    assert "financial_date_invalid" in row.validation_errors
    assert "scheme_invalid" in row.validation_errors
    assert "delivery_service_invalid" in row.validation_errors

    result = build_logistics_analysis([row], [_unit_row()])
    assert result.context.data_status == "blocked"
    assert result.context.invalid_source_row_count == 1
    assert result.context.required_field_error_count >= 3
    assert result.order_rows == ()


def test_dimension_reconciliation_blocks_false_global_match() -> None:
    rows = [
        _source_row(nm_id="101", sku="sku-101", delivery_service=Decimal("10")),
        _source_row(
            source_row_id="row-2",
            source_hash="hash-2",
            order_uid="order-2",
            nm_id="202",
            sku="sku-202",
            delivery_service=Decimal("20"),
        ),
    ]
    units = [
        _unit_row(nm_id="101", sku="sku-101", logistics=Decimal("20")),
        _unit_row(nm_id="202", sku="sku-202", logistics=Decimal("10")),
    ]

    result = build_logistics_analysis(rows, units)

    assert result.context.raw_logistics_total == result.context.report_logistics_total
    assert result.context.data_status == "blocked"
    assert result.context.dimension_delta_count == 2
    assert result.context.max_dimension_delta == Decimal("10")
    assert "dimension_logistics_mismatch" in result.context.blocking_reasons


def test_hash_includes_organization_mapping_and_display_metadata() -> None:
    first = build_logistics_analysis([_source_row()], [_unit_row()])
    changed_company = build_logistics_analysis(
        [_source_row(client_company_id="company-2")],
        [_unit_row(client_company_id="company-2")],
    )
    changed_title = build_logistics_analysis(
        [_source_row(product="Новое название")],
        [_unit_row(product="Новое название")],
    )

    assert first.context.input_hash != changed_company.context.input_hash
    assert first.context.input_hash != changed_title.context.input_hash


def test_chain_dimension_conflict_blocks_mixed_scheme_and_company() -> None:
    mixed_scheme = build_logistics_analysis(
        [
            _source_row(delivery_service=Decimal("10"), scheme="fbo"),
            _source_row(
                source_row_id="row-2",
                source_hash="hash-2",
                delivery_service=Decimal("20"),
                scheme="fbs",
            ),
        ],
        [
            _unit_row(logistics=Decimal("10"), scheme="fbo"),
            _unit_row(logistics=Decimal("20"), scheme="fbs"),
        ],
    )
    mixed_company = build_logistics_analysis(
        [
            _source_row(delivery_service=Decimal("10")),
            _source_row(
                source_row_id="row-2",
                source_hash="hash-2",
                client_company_id="company-2",
                delivery_service=Decimal("20"),
            ),
        ],
        [
            _unit_row(logistics=Decimal("10")),
            _unit_row(
                client_company_id="company-2", logistics=Decimal("20")
            ),
        ],
    )

    for result in (mixed_scheme, mixed_company):
        assert result.context.data_status == "blocked"
        assert result.context.chain_dimension_conflict_count == 1
        assert "chain_dimension_conflict" in result.context.blocking_reasons
        assert result.order_rows == ()
        assert result.sku_rows == ()


def test_missing_report_date_keeps_control_total_and_blocks_marts() -> None:
    result = build_logistics_analysis(
        [_source_row(delivery_service=Decimal("50"))],
        [
            _unit_row(
                financial_week_start=None,
                logistics=Decimal("50"),
                source_row_id="unit-without-date",
            )
        ],
        report_period_start=date(2026, 7, 13),
        report_period_end=date(2026, 7, 19),
    )

    assert result.context.data_status == "blocked"
    assert result.context.report_logistics_total == Decimal("50")
    assert result.context.invalid_report_row_count == 1
    assert result.context.report_required_field_error_count == 1
    assert "invalid_required_report_fields" in result.context.blocking_reasons
    assert "report_financial_date_missing" in result.context.blocking_reasons
    assert result.order_rows == ()
    assert result.sku_rows == ()


def test_invalid_report_date_and_logistics_value_block_without_crashing() -> None:
    result = build_logistics_analysis(
        [_source_row()],
        [
            _unit_row(
                financial_week_start="damaged-date",
                logistics="not-a-number",
                source_row_id="invalid-unit-row",
            )
        ],
        report_period_start=date(2026, 7, 13),
        report_period_end=date(2026, 7, 19),
    )

    assert result.context.data_status == "blocked"
    assert result.context.invalid_report_row_count == 1
    assert result.context.report_required_field_error_count == 2
    assert result.context.report_logistics_total == 0
    assert result.order_rows == ()
    assert result.sku_rows == ()


def test_report_period_changes_hash_and_previous_period_status() -> None:
    row = _source_row(
        order_date=date(2026, 7, 12),
        delivery_amount=Decimal("0"),
        return_amount=Decimal("1"),
    )
    previous = build_logistics_analysis(
        [row],
        [_unit_row()],
        report_period_start=date(2026, 7, 13),
        report_period_end=date(2026, 7, 19),
    )
    current = build_logistics_analysis(
        [row],
        [_unit_row()],
        report_period_start=date(2026, 7, 1),
        report_period_end=date(2026, 7, 31),
    )

    assert previous.context.input_hash != current.context.input_hash
    assert previous.order_rows[0].order_period_status == "previous_report_period"
    assert current.order_rows[0].order_period_status == "current_report_period"


def test_post_build_dimension_reconciliation_blocks_aggregation_drift(
    monkeypatch,
) -> None:
    from wb_unit_economics import logistics_analysis

    original = logistics_analysis.build_order_rows

    def corrupt_order_rows(*args, **kwargs):
        rows = original(*args, **kwargs)
        return [replace(rows[0], scheme="fbs")]

    monkeypatch.setattr(logistics_analysis, "build_order_rows", corrupt_order_rows)

    result = build_logistics_analysis([_source_row()], [_unit_row()])

    assert result.context.data_status == "blocked"
    assert "source_order_dimension_logistics_mismatch" in (
        result.context.blocking_reasons
    )
    assert "sku_report_dimension_logistics_mismatch" in (
        result.context.blocking_reasons
    )
    assert result.context.dimension_delta_count > 0
    assert result.order_rows == ()
    assert result.sku_rows == ()


def test_order_mart_is_daily_and_marks_mixed_route_metadata() -> None:
    rows = [
        _source_row(warehouse="Коледино", destination="Москва"),
        _source_row(
            source_row_id="row-2",
            source_hash="hash-2",
            delivery_service=Decimal("0"),
            delivery_amount=Decimal("0"),
            warehouse="Электросталь",
            destination="Тула",
        ),
        _source_row(
            source_row_id="row-3",
            source_hash="hash-3",
            financial_date=date(2026, 7, 14),
            delivery_service=Decimal("5"),
        ),
    ]
    result = build_logistics_analysis(
        rows,
        [_unit_row(logistics=Decimal("15"))],
    )

    assert result.context.data_status == "ready"
    assert len(result.order_rows) == 2
    first = result.order_rows[0]
    assert first.financial_date == date(2026, 7, 13)
    assert first.warehouse == "mixed"
    assert first.warehouse_status == "mixed"
    assert first.destination == "mixed"
    assert first.destination_status == "mixed"


def test_mixed_tenant_scope_blocks_calculation_and_marts() -> None:
    result = build_logistics_analysis(
        [
            _source_row(),
            _source_row(
                tenant_id="tenant-2",
                client_id="client-2",
                source_row_id="row-2",
                source_hash="hash-2",
                order_uid="order-2",
            ),
        ],
        [
            _unit_row(logistics=Decimal("10")),
            _unit_row(
                tenant_id="tenant-2",
                client_id="client-2",
                logistics=Decimal("10"),
            ),
        ],
        expected_tenant_id="tenant-1",
        expected_client_id="client-1",
    )

    assert result.context.data_status == "blocked"
    assert result.context.scope_mismatch_count == 2
    assert "tenant_scope_mismatch" in result.context.blocking_reasons
    assert result.order_rows == ()
    assert result.sku_rows == ()


def test_invalid_payload_shape_diagnostics_are_hashed_and_block_gate() -> None:
    baseline = build_logistics_analysis([_source_row()], [_unit_row()])
    blocked = build_logistics_analysis(
        [_source_row()],
        [_unit_row()],
        input_diagnostics=LogisticsInputDiagnostics(
            invalid_source_payload_shape_count=1,
            blocking_reasons=("invalid_source_payload_shape",),
            lineage_records=(
                {
                    "runId": "run-1",
                    "sourceHash": "invalid-shape-hash",
                    "selection": "invalid",
                },
            ),
        ),
    )

    assert blocked.context.data_status == "blocked"
    assert blocked.context.source_row_count == 2
    assert blocked.context.invalid_source_row_count == 1
    assert blocked.context.invalid_source_payload_shape_count == 1
    assert blocked.context.input_hash != baseline.context.input_hash


def test_streaming_input_hash_matches_legacy_canonical_payload() -> None:
    source_rows = [
        _source_row(),
        _source_row(
            source_row_id="row-2",
            source_hash="hash-2",
            order_uid="order-2",
        ),
    ]
    unit_rows = [_unit_row()]
    diagnostics = LogisticsInputDiagnostics(
        invalid_source_payload_shape_count=1,
        source_identity_error_count=2,
        source_revision_conflict_count=3,
        source_revision_discarded_count=4,
        scope_mismatch_count=5,
        blocking_reasons=("reason-b", "reason-a"),
        lineage_records=(
            {"runId": "run-2", "selection": "candidate"},
            {"runId": "run-1", "selection": "discarded"},
        ),
    )
    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 31)
    legacy_payload = {
        "methodology": LOGISTICS_METHODOLOGY_VERSION,
        "chain": CHAIN_KEY_VERSION,
        "reportPeriodStart": period_start.isoformat(),
        "reportPeriodEnd": period_end.isoformat(),
        "inputDiagnostics": {
            "invalidSourcePayloadShapeCount": 1,
            "sourceIdentityErrorCount": 2,
            "sourceRevisionConflictCount": 3,
            "sourceRevisionDiscardedCount": 4,
            "scopeMismatchCount": 5,
            "blockingReasons": ["reason-a", "reason-b"],
            "lineage": sorted(
                (dict(item) for item in diagnostics.lineage_records),
                key=lambda item: logistics_analysis.json.dumps(
                    item, ensure_ascii=False, sort_keys=True
                ),
            ),
        },
        "source": sorted(
            (
                logistics_analysis._source_hash_record(row)
                for row in source_rows
            ),
            key=lambda item: logistics_analysis.json.dumps(
                item, ensure_ascii=False, sort_keys=True
            ),
        ),
        "unit": sorted(
            (logistics_analysis._unit_hash_record(row) for row in unit_rows),
            key=lambda item: logistics_analysis.json.dumps(
                item, ensure_ascii=False, sort_keys=True
            ),
        ),
    }

    assert logistics_analysis._input_hash(
        source_rows,
        unit_rows,
        report_period_start=period_start,
        report_period_end=period_end,
        input_diagnostics=diagnostics,
    ) == logistics_analysis._hash_payload(legacy_payload)


def test_strict_date_and_scheme_parsers_reject_trailing_or_embedded_values() -> None:
    row = source_row_from_payload(
        {
            "rrDate": "2026-07-16-GARBAGE",
            "orderUid": "order-1",
            "nmId": "101",
            "deliveryMethod": "not-fbo-value",
            "deliveryService": "10",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        fallback_date=date(2026, 7, 1),
    )

    assert row.financial_date is None
    assert row.scheme == ""
    assert "financial_date_invalid" in row.validation_errors
    assert "scheme_invalid" in row.validation_errors


def test_signaling_nan_report_value_blocks_without_hash_crash() -> None:
    result = build_logistics_analysis(
        [_source_row()],
        [_unit_row(logistics=Decimal("sNaN"))],
    )

    assert result.context.data_status == "blocked"
    assert result.context.report_logistics_total == 0
    assert "invalid_required_report_fields" in result.context.blocking_reasons
    assert len(result.context.input_hash) == 64


def test_old_forward_order_has_neutral_period_status() -> None:
    result = build_logistics_analysis(
        [_source_row(order_date=date(2026, 6, 30))],
        [_unit_row()],
        report_period_start=date(2026, 7, 13),
        report_period_end=date(2026, 7, 19),
    )

    assert result.context.data_status == "ready"
    assert result.order_rows[0].order_period_status == "order_before_report_period"


def test_product_reference_scopes_sku_fallback_but_unifies_nm_id() -> None:
    nm_first = _source_row(wb_cabinet_id="cabinet-1", nm_id="101")
    nm_second = _source_row(wb_cabinet_id="cabinet-2", nm_id="101")
    sku_first = _source_row(wb_cabinet_id="cabinet-1", nm_id="", sku="same")
    sku_second = _source_row(wb_cabinet_id="cabinet-2", nm_id="", sku="same")

    assert nm_first.product_ref == nm_second.product_ref
    assert sku_first.product_ref != sku_second.product_ref


def test_scheme_variants_and_report_labels_are_normalized() -> None:
    fbw = source_row_from_payload(
        {
            "rrDate": "2026-07-13",
            "orderUid": "order-1",
            "nmId": "101",
            "deliveryMethod": "FBW, (МГТ, короба)",
            "deliveryService": "10",
            "deliveryAmount": "1",
            "returnAmount": "0",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        fallback_date=date(2026, 7, 1),
    )
    fbs = source_row_from_payload(
        {
            "rrDate": "2026-07-13",
            "orderUid": "order-2",
            "nmId": "202",
            "deliveryMethod": "FBS, (МГТ)",
            "deliveryService": "20",
            "deliveryAmount": "1",
            "returnAmount": "0",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        fallback_date=date(2026, 7, 1),
    )

    assert fbw.scheme == "fbo"
    assert fbs.scheme == "fbs"
    result = build_logistics_analysis(
        [fbw],
        [_unit_row(scheme="Склад WB")],
    )
    assert result.context.data_status == "ready"


def test_correction_without_delivery_method_uses_neutral_non_order_scheme() -> None:
    normal = _source_row(delivery_service=Decimal("10"))
    correction = source_row_from_payload(
        {
            "rrDate": "2026-07-13",
            "orderUid": "order-1",
            "nmId": "101",
            "sellerOperName": "Коррекция логистики",
            "deliveryService": "5",
            "deliveryAmount": "0",
            "returnAmount": "0",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        source_row_id="correction-1",
        fallback_date=date(2026, 7, 1),
    )

    assert correction.scheme == "not_applicable"
    assert "scheme_missing" not in correction.validation_errors
    result = build_logistics_analysis(
        [normal, correction],
        [_unit_row(logistics=Decimal("15"), scheme="Склад WB")],
    )

    assert result.context.data_status == "ready"
    assert result.context.chain_dimension_conflict_count == 0
    assert result.context.report_logistics_total == Decimal("15")
    assert len(result.order_rows) == 2
    correction_order = next(
        row for row in result.order_rows if row.scheme == "not_applicable"
    )
    assert correction_order.countable_order is False
    assert correction_order.logistics_adjustment == Decimal("5")
    correction_sku = next(
        row for row in result.sku_rows if row.scheme == "not_applicable"
    )
    assert correction_sku.chain_count == 0
    assert correction_sku.logistics_per_order is None


def test_zero_logistics_without_order_uid_is_financial_only() -> None:
    financial_only = source_row_from_payload(
        {
            "rrDate": "2026-07-13",
            "deliveryService": "0",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        source_row_id="financial-only-1",
        fallback_date=date(2026, 7, 1),
    )

    assert "order_uid_missing" in financial_only.validation_errors
    result = build_logistics_analysis(
        [_source_row(), financial_only],
        [_unit_row()],
    )

    assert result.context.data_status == "ready"
    assert result.context.invalid_source_row_count == 0
    assert result.context.required_field_error_count == 0
    assert len(result.order_rows) == 1


def test_zero_logistics_with_order_can_enrich_chain_without_own_scheme() -> None:
    sale = source_row_from_payload(
        {
            "rrDate": "2026-07-13",
            "orderUid": "order-1",
            "nmId": "101",
            "docTypeName": "Продажа",
            "quantity": "1",
            "retailAmount": "100",
            "deliveryService": "0",
        },
        tenant_id="tenant-1",
        client_id="client-1",
        wb_cabinet_id="cabinet-1",
        client_company_id="company-1",
        source_row_id="sale-without-scheme",
        fallback_date=date(2026, 7, 1),
    )
    assert "scheme_missing" in sale.validation_errors

    result = build_logistics_analysis([sale, _source_row()], [_unit_row()])

    assert result.context.data_status == "ready"
    assert result.context.invalid_source_row_count == 0
    assert result.context.chain_dimension_conflict_count == 0
    assert len(result.order_rows) == 1
    assert result.order_rows[0].scheme == "fbo"
    assert result.order_rows[0].sales_quantity == Decimal("1")

    zero_only = build_logistics_analysis([sale], [])
    assert zero_only.context.data_status == "ready"
    assert zero_only.order_rows == ()
    assert zero_only.sku_rows == ()


def test_partial_boundary_week_uses_exact_source_but_full_week_uses_report() -> None:
    boundary = _source_row(
        financial_date=date(2026, 4, 1),
        source_row_id="boundary",
        source_hash="boundary-hash",
        delivery_service=Decimal("10"),
    )
    full = _source_row(
        financial_date=date(2026, 4, 6),
        source_row_id="full",
        source_hash="full-hash",
        order_uid="order-2",
        delivery_service=Decimal("20"),
    )
    unit_rows = [
        _unit_row(
            financial_week_start=date(2026, 3, 30),
            logistics=Decimal("999"),
        ),
        _unit_row(
            financial_week_start=date(2026, 4, 6),
            logistics=Decimal("20"),
        ),
    ]

    result = build_logistics_analysis(
        [boundary, full],
        unit_rows,
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 4, 12),
    )

    assert result.context.data_status == "ready"
    assert result.context.raw_logistics_total == Decimal("30")
    assert result.context.report_logistics_total == Decimal("30")
    boundary_sku = next(
        row
        for row in result.sku_rows
        if row.financial_week_start == date(2026, 3, 30)
    )
    assert boundary_sku.profit_before_tax is None

    mismatch = build_logistics_analysis(
        [boundary, full],
        [unit_rows[0], replace(unit_rows[1], logistics=Decimal("21"))],
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 4, 12),
    )
    assert mismatch.context.data_status == "blocked"
    assert "dimension_logistics_mismatch" in mismatch.context.blocking_reasons
