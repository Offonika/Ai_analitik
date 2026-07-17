from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

LOGISTICS_METHODOLOGY_VERSION = "wb-logistics-v4"
CHAIN_KEY_VERSION = "wb-order-product-v1"
RECONCILIATION_TOLERANCE = Decimal("0.01")
LOW_SAMPLE_THRESHOLD = 10

LogisticsClass = Literal["forward", "reverse", "adjustment", "unclassified"]

_ADJUSTMENT_OPERATION_MARKERS = (
    "перерасчет",
    "перерасчёт",
    "коррекц",
    "корректиров",
    "возмещени",
)
_BLOCKING_SOURCE_ERRORS = {
    "tenant_id_missing",
    "client_id_missing",
    "wb_cabinet_id_missing",
    "client_company_id_missing",
    "financial_date_missing",
    "financial_date_invalid",
    "scheme_missing",
    "scheme_invalid",
    "delivery_service_missing",
    "delivery_service_invalid",
}


@dataclass(frozen=True)
class LogisticsSourceRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    client_company_id: str
    source_row_id: str
    source_hash: str
    financial_date: date | None
    order_date: date | None
    order_uid: str
    nm_id: str
    sku: str
    vendor_code: str
    product: str
    scheme: str
    warehouse: str
    destination: str
    document_type: str
    operation_name: str
    quantity: Decimal | None
    retail_amount: Decimal | None
    delivery_service: Decimal | None
    delivery_amount: Decimal | None
    return_amount: Decimal | None
    rebill_logistic_cost: Decimal | None
    validation_errors: tuple[str, ...] = ()

    @property
    def product_key(self) -> str:
        if self.nm_id.strip():
            return f"nm:{self.nm_id.strip()}"
        if self.sku.strip():
            return f"sku:{self.sku.strip()}"
        return ""

    @property
    def week_start(self) -> date | None:
        if self.financial_date is None:
            return None
        return self.financial_date - timedelta(days=self.financial_date.weekday())

    @property
    def chain_key(self) -> str:
        if (
            not self.tenant_id.strip()
            or not self.client_id.strip()
            or not self.wb_cabinet_id.strip()
            or not self.order_uid.strip()
            or not self.product_key
        ):
            return ""
        return logistics_chain_key(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            wb_cabinet_id=self.wb_cabinet_id,
            order_uid=self.order_uid,
            product_key=self.product_key,
        )

    @property
    def product_ref(self) -> str:
        return logistics_product_ref(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            wb_cabinet_id=self.wb_cabinet_id,
            client_company_id=self.client_company_id,
            scheme=self.scheme,
            nm_id=self.nm_id,
            sku=self.sku,
        )


@dataclass(frozen=True)
class UnitEconomicsSlice:
    tenant_id: str
    client_id: str
    financial_week_start: date | None
    wb_cabinet_id: str
    client_company_id: str
    scheme: str
    nm_id: str
    sku: str
    vendor_code: str
    product: str
    revenue: Decimal
    profit_before_tax: Decimal
    logistics: Decimal | None
    source_row_id: str = ""
    validation_errors: tuple[str, ...] = ()

    @property
    def product_key(self) -> str:
        if self.nm_id.strip():
            return f"nm:{self.nm_id.strip()}"
        if self.sku.strip():
            return f"sku:{self.sku.strip()}"
        return ""


@dataclass(frozen=True)
class LogisticsOrderRow:
    chain_key: str
    chain_segment_key: str
    countable_order: bool
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    client_company_id: str
    financial_date: date
    financial_week_start: date
    operation_date_start: date
    operation_date_end: date
    order_date: date | None
    order_period_status: str
    product_ref: str
    product_key: str
    nm_id: str
    sku: str
    vendor_code: str
    product: str
    scheme: str
    warehouse: str
    warehouse_status: str
    destination: str
    destination_status: str
    logistics_total: Decimal
    logistics_forward: Decimal
    logistics_reverse: Decimal
    logistics_adjustment: Decimal
    logistics_unclassified: Decimal
    sales_quantity: Decimal
    return_quantity: Decimal
    net_quantity: Decimal
    source_revenue: Decimal
    source_row_count: int
    logistics_row_count: int
    classified_row_count: int
    source_hash_digest: str
    classification_status: str
    coverage_status: str
    data_quality_status: str


@dataclass(frozen=True)
class LogisticsSkuRow:
    tenant_id: str
    client_id: str
    financial_week_start: date
    financial_week_end: date
    wb_cabinet_id: str
    client_company_id: str
    scheme: str
    product_ref: str
    product_key: str
    nm_id: str
    sku: str
    vendor_code: str
    product: str
    logistics_total: Decimal
    logistics_forward: Decimal
    logistics_reverse: Decimal
    logistics_adjustment: Decimal
    logistics_unclassified: Decimal
    revenue: Decimal
    profit_before_tax: Decimal | None
    profit_without_logistics: Decimal | None
    profit_effect_amount: Decimal
    logistics_share_pct: Decimal | None
    logistics_per_order: Decimal | None
    logistics_per_sale: Decimal | None
    sales_quantity: Decimal
    return_quantity: Decimal
    chain_count: int
    logistics_row_count: int
    classified_row_count: int
    low_sample: bool
    classification_status: str
    coverage_status: str
    data_quality_status: str
    recommendation_flags: tuple[str, ...]
    source_hash_digest: str


@dataclass(frozen=True)
class LogisticsAnalysisContext:
    data_status: str
    source_quality_status: str
    methodology_version: str
    chain_key_version: str
    source_row_count: int
    logistics_row_count: int
    keyed_logistics_row_count: int
    product_logistics_row_count: int
    invalid_source_row_count: int
    required_field_error_count: int
    invalid_report_row_count: int
    report_required_field_error_count: int
    chain_dimension_conflict_count: int
    invalid_source_payload_shape_count: int
    source_identity_error_count: int
    source_revision_conflict_count: int
    source_revision_discarded_count: int
    scope_mismatch_count: int
    key_coverage_pct: Decimal | None
    product_coverage_pct: Decimal | None
    classification_row_coverage_pct: Decimal | None
    cross_cabinet_collision_count: int
    raw_order_uid_cross_cabinet_reuse_count: int
    unmatched_source_dimension_count: int
    unmatched_report_dimension_count: int
    dimension_delta_count: int
    max_dimension_delta: Decimal
    raw_logistics_total: Decimal
    order_logistics_total: Decimal
    sku_logistics_total: Decimal
    report_logistics_total: Decimal
    order_delta: Decimal
    sku_delta: Decimal
    blocking_reasons: tuple[str, ...]
    review_reasons: tuple[str, ...]
    input_hash: str


@dataclass(frozen=True)
class LogisticsAnalysisResult:
    context: LogisticsAnalysisContext
    order_rows: tuple[LogisticsOrderRow, ...]
    sku_rows: tuple[LogisticsSkuRow, ...]


@dataclass(frozen=True)
class LogisticsInputDiagnostics:
    invalid_source_payload_shape_count: int = 0
    source_identity_error_count: int = 0
    source_revision_conflict_count: int = 0
    source_revision_discarded_count: int = 0
    scope_mismatch_count: int = 0
    blocking_reasons: tuple[str, ...] = ()
    lineage_records: tuple[Mapping[str, Any], ...] = ()


def source_row_from_payload(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    client_id: str,
    wb_cabinet_id: str,
    client_company_id: str = "",
    source_row_id: str = "",
    source_hash: str = "",
    fallback_date: date,
) -> LogisticsSourceRow:
    # Kept in the signature for compatibility. v4 deliberately does not use a
    # report boundary as a substitute for a damaged source operation date.
    del fallback_date
    errors: list[str] = []
    financial_date, date_status = _parse_date(
        _raw_first(payload, "rrDate", "rr_dt", "createDate")
    )
    if date_status != "ready":
        errors.append(f"financial_date_{date_status}")
    order_date, order_date_status = _parse_date(
        _raw_first(payload, "orderDt", "order_dt"), required=False
    )
    if order_date_status == "invalid":
        errors.append("order_date_invalid")
    operation_name = _text(
        _raw_first(
            payload, "sellerOperName", "supplierOperName", "operation_type"
        )
    )
    scheme, scheme_status = normalize_logistics_scheme(
        _raw_first(payload, "deliveryMethod", "delivery_method"),
        operation_name=operation_name,
    )
    if scheme_status != "ready":
        errors.append(f"scheme_{scheme_status}")

    quantity = _parse_optional_decimal(
        payload, errors, "quantity", "quantity"
    )
    retail_amount = _parse_optional_decimal(
        payload, errors, "retail_amount", "retailAmount", "retail_amount"
    )
    delivery_service = _parse_required_decimal(
        payload,
        errors,
        "delivery_service",
        "deliveryService",
        "delivery_service",
        "delivery_rub",
    )
    delivery_amount = _parse_optional_decimal(
        payload, errors, "delivery_amount", "deliveryAmount", "delivery_amount"
    )
    return_amount = _parse_optional_decimal(
        payload, errors, "return_amount", "returnAmount", "return_amount"
    )
    rebill_logistic_cost = _parse_optional_decimal(
        payload,
        errors,
        "rebill_logistic_cost",
        "rebillLogisticCost",
        "rebill_logistic_cost",
    )

    normalized_tenant = _text(tenant_id)
    normalized_client = _text(client_id)
    normalized_cabinet = _text(wb_cabinet_id)
    normalized_company = _text(client_company_id)
    for field_name, value in (
        ("tenant_id", normalized_tenant),
        ("client_id", normalized_client),
        ("wb_cabinet_id", normalized_cabinet),
        ("client_company_id", normalized_company),
    ):
        if not value:
            errors.append(f"{field_name}_missing")

    order_uid = _text(_raw_first(payload, "orderUid", "order_uid"))
    nm_id = _text(_raw_first(payload, "nmId", "nm_id"))
    sku = _text(_raw_first(payload, "sku", "barcode"))
    if not order_uid:
        errors.append("order_uid_missing")
    if not nm_id and not sku:
        errors.append("product_missing")

    return LogisticsSourceRow(
        tenant_id=normalized_tenant,
        client_id=normalized_client,
        wb_cabinet_id=normalized_cabinet,
        client_company_id=normalized_company,
        source_row_id=_text(source_row_id),
        source_hash=_text(source_hash) or _hash_payload(payload),
        financial_date=financial_date,
        order_date=order_date,
        order_uid=order_uid,
        nm_id=nm_id,
        sku=sku,
        vendor_code=_text(_raw_first(payload, "vendorCode", "sa_name")),
        product=_text(_raw_first(payload, "title", "product")),
        scheme=scheme,
        warehouse=_text(_raw_first(payload, "officeName", "office_name")),
        destination=_text(
            _raw_first(payload, "country", "ppvzOfficeName", "ppvz_office_name")
        ),
        document_type=_text(_raw_first(payload, "docTypeName", "doc_type_name")),
        operation_name=operation_name,
        quantity=quantity,
        retail_amount=retail_amount,
        delivery_service=delivery_service,
        delivery_amount=delivery_amount,
        return_amount=return_amount,
        rebill_logistic_cost=rebill_logistic_cost,
        validation_errors=tuple(sorted(set(errors))),
    )


def logistics_chain_key(
    *,
    tenant_id: str,
    client_id: str,
    wb_cabinet_id: str,
    order_uid: str,
    product_key: str,
) -> str:
    value = "\x1f".join(
        (
            CHAIN_KEY_VERSION,
            tenant_id.strip(),
            client_id.strip(),
            wb_cabinet_id.strip(),
            order_uid.strip(),
            product_key.strip(),
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def logistics_product_ref(
    *,
    tenant_id: str,
    client_id: str,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    nm_id: str,
    sku: str,
) -> str:
    if nm_id.strip():
        identity = ("nm", tenant_id.strip(), client_id.strip(), nm_id.strip())
    elif sku.strip():
        identity = (
            "sku",
            tenant_id.strip(),
            client_id.strip(),
            wb_cabinet_id.strip(),
            client_company_id.strip(),
            scheme.strip().casefold(),
            sku.strip(),
        )
    else:
        return ""
    return "product:" + hashlib.sha256("\x1f".join(identity).encode()).hexdigest()


def classify_logistics_row(row: LogisticsSourceRow) -> LogisticsClass:
    if row.delivery_amount is None or row.return_amount is None:
        return "unclassified"
    forward = row.delivery_amount != 0
    reverse = row.return_amount != 0
    if forward and not reverse:
        return "forward"
    if reverse and not forward:
        return "reverse"
    operation = f"{row.document_type} {row.operation_name}".casefold()
    adjustment_confirmed = (row.rebill_logistic_cost or Decimal("0")) != 0 or any(
        marker in operation for marker in _ADJUSTMENT_OPERATION_MARKERS
    )
    if not forward and not reverse and adjustment_confirmed:
        return "adjustment"
    return "unclassified"


def build_logistics_analysis(
    source_rows: Sequence[LogisticsSourceRow],
    unit_rows: Sequence[UnitEconomicsSlice],
    *,
    report_period_start: date | None = None,
    report_period_end: date | None = None,
    expected_tenant_id: str = "",
    expected_client_id: str = "",
    input_diagnostics: LogisticsInputDiagnostics | None = None,
) -> LogisticsAnalysisResult:
    diagnostics = input_diagnostics or LogisticsInputDiagnostics()
    normalized_unit_rows = [_normalize_unit_slice(row) for row in unit_rows]
    effective_period_start, effective_period_end = _report_period(
        normalized_unit_rows,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
    )
    financial_unit_rows = [
        row
        for row in normalized_unit_rows
        if not isinstance(row.financial_week_start, date)
        or _week_fully_contained(
            row.financial_week_start,
            effective_period_start,
            effective_period_end,
        )
    ]
    input_hash = _input_hash(
        source_rows,
        normalized_unit_rows,
        report_period_start=effective_period_start,
        report_period_end=effective_period_end,
        input_diagnostics=diagnostics,
    )
    valid_logistics_rows = [
        row
        for row in source_rows
        if row.delivery_service is not None
        and _is_finite_decimal(row.delivery_service)
        and row.delivery_service != 0
    ]
    raw_total = sum(
        (row.delivery_service for row in valid_logistics_rows), Decimal("0")
    )
    required_errors = _required_source_errors(source_rows)
    report_required_errors = _required_report_errors(financial_unit_rows)
    invalid_rows = sum(
        not _is_financial_only_non_logistics_row(row)
        and bool(
            _effective_logistics_validation_errors(row)
            | required_errors.get(index, set())
        )
        for index, row in enumerate(source_rows)
    )
    required_error_count = sum(len(errors) for errors in required_errors.values())
    invalid_report_rows = len(report_required_errors)
    report_required_error_count = sum(
        len(errors) for errors in report_required_errors.values()
    )
    report_error_codes = {
        error
        for errors in report_required_errors.values()
        for error in errors
    }
    optional_error_count = sum(
        0
        if _is_financial_only_non_logistics_row(row)
        else len(
            _effective_logistics_validation_errors(row)
            - required_errors.get(index, set())
        )
        for index, row in enumerate(source_rows)
    )
    keyed_count = sum(bool(row.chain_key) for row in valid_logistics_rows)
    product_count = sum(bool(row.product_key) for row in valid_logistics_rows)
    collisions = _composite_key_collisions(valid_logistics_rows)
    raw_uid_reuse = _raw_order_uid_cross_cabinet_reuse(valid_logistics_rows)
    chain_dimension_conflicts = _chain_dimension_conflict_count(source_rows)
    scope_mismatches = diagnostics.scope_mismatch_count + _scope_mismatch_count(
        source_rows,
        normalized_unit_rows,
        expected_tenant_id=expected_tenant_id,
        expected_client_id=expected_client_id,
    )
    dimension_source_rows = [
        row
        for index, row in enumerate(source_rows)
        if index not in required_errors
        and row.delivery_service not in (None, Decimal("0"))
    ]
    valid_unit_rows = [
        row
        for index, row in enumerate(financial_unit_rows)
        if index not in report_required_errors
    ]
    report_dimension_totals = _logistics_control_dimension_totals(
        dimension_source_rows,
        valid_unit_rows,
        report_period_start=effective_period_start,
        report_period_end=effective_period_end,
    )
    invalid_report_control_total = sum(
        (
            row.logistics
            for index, row in enumerate(financial_unit_rows)
            if index in report_required_errors and _is_finite_decimal(row.logistics)
        ),
        Decimal("0"),
    )
    report_total = (
        sum(report_dimension_totals.values(), Decimal("0"))
        + invalid_report_control_total
    )
    reconciliation = _reconcile_dimension_totals(
        _source_dimension_totals(dimension_source_rows),
        report_dimension_totals,
    )

    blocking: list[str] = list(diagnostics.blocking_reasons)
    if required_error_count:
        blocking.append("invalid_required_source_fields")
    if report_required_error_count:
        blocking.append("invalid_required_report_fields")
    if "report_financial_date_missing" in report_error_codes:
        blocking.append("report_financial_date_missing")
    if valid_logistics_rows and keyed_count != len(valid_logistics_rows):
        blocking.append("chain_key_coverage_below_100pct")
    if valid_logistics_rows and product_count != len(valid_logistics_rows):
        blocking.append("product_key_coverage_below_100pct")
    if collisions:
        blocking.append("composite_chain_key_collision")
    if chain_dimension_conflicts:
        blocking.append("chain_dimension_conflict")
    if scope_mismatches:
        blocking.append("tenant_scope_mismatch")
    if abs(raw_total - report_total) > RECONCILIATION_TOLERANCE:
        blocking.append("raw_report_logistics_mismatch")
    if reconciliation["unmatched_source"]:
        blocking.append("unmatched_source_dimensions")
    if reconciliation["unmatched_report"]:
        blocking.append("unmatched_report_dimensions")
    if reconciliation["delta_count"]:
        blocking.append("dimension_logistics_mismatch")

    base_context = LogisticsAnalysisContext(
        data_status="blocked" if blocking else "ready",
        source_quality_status=(
            "blocked"
            if required_error_count or diagnostics.blocking_reasons or scope_mismatches
            else "partial"
            if optional_error_count
            else "ready"
        ),
        methodology_version=LOGISTICS_METHODOLOGY_VERSION,
        chain_key_version=CHAIN_KEY_VERSION,
        source_row_count=(
            len(source_rows) + diagnostics.invalid_source_payload_shape_count
        ),
        logistics_row_count=len(valid_logistics_rows),
        keyed_logistics_row_count=keyed_count,
        product_logistics_row_count=product_count,
        invalid_source_row_count=(
            invalid_rows + diagnostics.invalid_source_payload_shape_count
        ),
        required_field_error_count=required_error_count,
        invalid_report_row_count=invalid_report_rows,
        report_required_field_error_count=report_required_error_count,
        chain_dimension_conflict_count=chain_dimension_conflicts,
        invalid_source_payload_shape_count=(
            diagnostics.invalid_source_payload_shape_count
        ),
        source_identity_error_count=diagnostics.source_identity_error_count,
        source_revision_conflict_count=(
            diagnostics.source_revision_conflict_count
        ),
        source_revision_discarded_count=(
            diagnostics.source_revision_discarded_count
        ),
        scope_mismatch_count=scope_mismatches,
        key_coverage_pct=_pct(keyed_count, len(valid_logistics_rows)),
        product_coverage_pct=_pct(product_count, len(valid_logistics_rows)),
        classification_row_coverage_pct=None,
        cross_cabinet_collision_count=collisions,
        raw_order_uid_cross_cabinet_reuse_count=raw_uid_reuse,
        unmatched_source_dimension_count=reconciliation["unmatched_source"],
        unmatched_report_dimension_count=reconciliation["unmatched_report"],
        dimension_delta_count=reconciliation["delta_count"],
        max_dimension_delta=reconciliation["max_delta"],
        raw_logistics_total=raw_total,
        order_logistics_total=Decimal("0"),
        sku_logistics_total=Decimal("0"),
        report_logistics_total=report_total,
        order_delta=-raw_total,
        sku_delta=-report_total,
        blocking_reasons=tuple(dict.fromkeys(blocking)),
        review_reasons=(),
        input_hash=input_hash,
    )
    if blocking:
        return LogisticsAnalysisResult(base_context, (), ())

    order_rows = build_order_rows(
        source_rows, report_period_start=effective_period_start
    )
    sku_rows = build_sku_rows(order_rows, valid_unit_rows)
    order_total = sum((row.logistics_total for row in order_rows), Decimal("0"))
    sku_total = sum((row.logistics_total for row in sku_rows), Decimal("0"))
    post_build_blocking: list[str] = []
    if abs(order_total - raw_total) > RECONCILIATION_TOLERANCE:
        post_build_blocking.append("order_raw_logistics_mismatch")
    if abs(sku_total - order_total) > RECONCILIATION_TOLERANCE:
        post_build_blocking.append("sku_order_logistics_mismatch")
    if abs(sku_total - report_total) > RECONCILIATION_TOLERANCE:
        post_build_blocking.append("sku_report_logistics_mismatch")
    post_build_reconciliations = {
        "source_order_dimension_logistics_mismatch": _reconcile_dimension_totals(
            _source_dimension_totals(dimension_source_rows),
            _order_dimension_totals(order_rows),
        ),
        "order_sku_dimension_logistics_mismatch": _reconcile_dimension_totals(
            _order_dimension_totals(order_rows),
            _sku_dimension_totals(sku_rows),
        ),
        "sku_report_dimension_logistics_mismatch": _reconcile_dimension_totals(
            _sku_dimension_totals(sku_rows),
            report_dimension_totals,
        ),
    }
    for reason, comparison in post_build_reconciliations.items():
        if (
            comparison["unmatched_source"]
            or comparison["unmatched_report"]
            or comparison["delta_count"]
        ):
            post_build_blocking.append(reason)
    post_build_delta_count = sum(
        comparison["delta_count"]
        for comparison in post_build_reconciliations.values()
    )
    post_build_max_delta = max(
        (
            comparison["max_delta"]
            for comparison in post_build_reconciliations.values()
        ),
        default=Decimal("0"),
    )
    classified_count = sum(row.classified_row_count for row in order_rows)
    unclassified_count = len(valid_logistics_rows) - classified_count
    review_items: list[str] = []
    if unclassified_count > 0:
        review_items.append("unclassified_logistics_rows")
    if optional_error_count:
        review_items.append("invalid_optional_source_fields")
    review = tuple(review_items)
    data_status = "blocked" if post_build_blocking else "partial" if review else "ready"
    context = replace(
        base_context,
        data_status=data_status,
        classification_row_coverage_pct=_pct(
            classified_count, len(valid_logistics_rows)
        ),
        order_logistics_total=order_total,
        sku_logistics_total=sku_total,
        order_delta=order_total - raw_total,
        sku_delta=sku_total - report_total,
        dimension_delta_count=(
            reconciliation["delta_count"] + post_build_delta_count
        ),
        max_dimension_delta=max(
            reconciliation["max_delta"], post_build_max_delta
        ),
        blocking_reasons=tuple(post_build_blocking),
        review_reasons=review,
    )
    if post_build_blocking:
        return LogisticsAnalysisResult(context, (), ())
    return LogisticsAnalysisResult(context, tuple(order_rows), tuple(sku_rows))


def build_order_rows(
    source_rows: Sequence[LogisticsSourceRow],
    *,
    report_period_start: date | None = None,
) -> list[LogisticsOrderRow]:
    groups: dict[tuple[str, date, str], dict[str, Any]] = {}
    for row in source_rows:
        if row.financial_date is None or not row.chain_key:
            continue
        scheme_segment = (
            "not_applicable" if row.scheme == "not_applicable" else "fulfillment"
        )
        group_key = (row.chain_key, row.financial_date, scheme_segment)
        bucket = groups.setdefault(
            group_key,
            {
                "row": row,
                "order_dates": [],
                "warehouses": set(),
                "destinations": set(),
                "vendor_codes": set(),
                "products": set(),
                "total": Decimal("0"),
                "forward": Decimal("0"),
                "reverse": Decimal("0"),
                "adjustment": Decimal("0"),
                "unclassified": Decimal("0"),
                "sales": Decimal("0"),
                "returns": Decimal("0"),
                "net": Decimal("0"),
                "revenue": Decimal("0"),
                "hashes": [],
                "source_count": 0,
                "logistics_count": 0,
                "classified_count": 0,
                "quality_errors": set(),
            },
        )
        bucket["source_count"] += 1
        if row.order_date is not None:
            bucket["order_dates"].append(row.order_date)
        bucket["warehouses"].add(row.warehouse)
        bucket["destinations"].add(row.destination)
        for field, value in (
            ("vendor_codes", row.vendor_code),
            ("products", row.product),
        ):
            if value:
                bucket[field].add(value)
        bucket["hashes"].append(row.source_hash)
        bucket["quality_errors"].update(
            _effective_logistics_validation_errors(row)
        )
        if row.delivery_service not in (None, Decimal("0")):
            bucket["row"] = row
            category = classify_logistics_row(row)
            bucket["total"] += row.delivery_service
            bucket[category] += row.delivery_service
            bucket["logistics_count"] += 1
            if category != "unclassified":
                bucket["classified_count"] += 1
        _add_sales_measures(bucket, row)

    result: list[LogisticsOrderRow] = []
    for (chain_key, financial_date, scheme_segment), bucket in sorted(groups.items()):
        if not bucket["logistics_count"]:
            continue
        row = bucket["row"]
        week_start = financial_date - timedelta(days=financial_date.weekday())
        segment_key = hashlib.sha256(
            (
                f"{chain_key}\x1f{financial_date.isoformat()}"
                f"\x1f{scheme_segment}"
            ).encode()
        ).hexdigest()
        order_date = min(bucket["order_dates"]) if bucket["order_dates"] else None
        order_period_status = (
            "previous_report_period"
            if order_date is not None
            and report_period_start is not None
            and order_date < report_period_start
            and (
                bucket["reverse"] != 0
                or bucket["returns"] != 0
            )
            else "order_before_report_period"
            if order_date is not None
            and report_period_start is not None
            and order_date < report_period_start
            else "current_report_period"
            if order_date is not None
            else "unknown"
        )
        warehouse, warehouse_status = _single_or_mixed(bucket["warehouses"])
        destination, destination_status = _single_or_mixed(bucket["destinations"])
        classification_status = (
            "ready"
            if bucket["classified_count"] == bucket["logistics_count"]
            else "partial"
        )
        result.append(
            LogisticsOrderRow(
                chain_key=chain_key,
                chain_segment_key=segment_key,
                countable_order=scheme_segment != "not_applicable",
                tenant_id=row.tenant_id,
                client_id=row.client_id,
                wb_cabinet_id=row.wb_cabinet_id,
                client_company_id=row.client_company_id,
                financial_date=financial_date,
                financial_week_start=week_start,
                operation_date_start=financial_date,
                operation_date_end=financial_date,
                order_date=order_date,
                order_period_status=order_period_status,
                product_ref=row.product_ref,
                product_key=row.product_key,
                nm_id=row.nm_id,
                sku=row.sku,
                vendor_code=_stable_display(bucket["vendor_codes"], row.vendor_code),
                product=_stable_display(bucket["products"], row.product),
                scheme=row.scheme,
                warehouse=warehouse,
                warehouse_status=warehouse_status,
                destination=destination,
                destination_status=destination_status,
                logistics_total=bucket["total"],
                logistics_forward=bucket["forward"],
                logistics_reverse=bucket["reverse"],
                logistics_adjustment=bucket["adjustment"],
                logistics_unclassified=bucket["unclassified"],
                sales_quantity=bucket["sales"],
                return_quantity=bucket["returns"],
                net_quantity=bucket["net"],
                source_revenue=bucket["revenue"],
                source_row_count=bucket["source_count"],
                logistics_row_count=bucket["logistics_count"],
                classified_row_count=bucket["classified_count"],
                source_hash_digest=_digest_strings(bucket["hashes"]),
                classification_status=classification_status,
                coverage_status="ready",
                data_quality_status=(
                    "partial" if bucket["quality_errors"] else "ready"
                ),
            )
        )
    return result


def build_sku_rows(
    order_rows: Sequence[LogisticsOrderRow],
    unit_rows: Sequence[UnitEconomicsSlice],
) -> list[LogisticsSkuRow]:
    order_buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in order_rows:
        key = _sku_key(
            row.tenant_id,
            row.client_id,
            row.financial_week_start,
            row.wb_cabinet_id,
            row.client_company_id,
            row.scheme,
            row.product_key,
        )
        bucket = order_buckets.setdefault(key, _new_sku_bucket(row))
        bucket["total"] += row.logistics_total
        bucket["forward"] += row.logistics_forward
        bucket["reverse"] += row.logistics_reverse
        bucket["adjustment"] += row.logistics_adjustment
        bucket["unclassified"] += row.logistics_unclassified
        bucket["sales"] += row.sales_quantity
        bucket["returns"] += row.return_quantity
        bucket["source_revenue"] += row.source_revenue
        bucket["logistics_count"] += row.logistics_row_count
        bucket["classified_count"] += row.classified_row_count
        bucket["hashes"].append(row.source_hash_digest)
        if row.countable_order:
            bucket["chains"].add(row.chain_key)

    unit_buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in unit_rows:
        if (
            not row.product_key
            or row.financial_week_start is None
            or row.logistics is None
        ):
            continue
        key = _sku_key(
            row.tenant_id,
            row.client_id,
            row.financial_week_start,
            row.wb_cabinet_id,
            row.client_company_id,
            row.scheme,
            row.product_key,
        )
        bucket = unit_buckets.setdefault(
            key,
            {
                "row": row,
                "revenue": Decimal("0"),
                "profit": Decimal("0"),
                "logistics": Decimal("0"),
            },
        )
        bucket["revenue"] += row.revenue
        bucket["profit"] += row.profit_before_tax
        bucket["logistics"] += row.logistics

    result: list[LogisticsSkuRow] = []
    for key in sorted(order_buckets, key=str):
        order = order_buckets[key]
        unit = unit_buckets.get(key)
        source = order["row"]
        revenue = unit["revenue"] if unit is not None else order["source_revenue"]
        profit = unit["profit"] if unit is not None else None
        chain_count = len(order["chains"])
        sales = order["sales"]
        total = order["total"]
        flags: list[str] = []
        if order["classified_count"] != order["logistics_count"]:
            flags.append("restore_classification")
        if order["reverse"] != 0:
            flags.append("check_returns")
        if total != 0 and revenue > 0:
            flags.append("check_margin")
        if unit is None:
            flags.append("restore_profit_link")
        result.append(
            LogisticsSkuRow(
                tenant_id=key[0],
                client_id=key[1],
                financial_week_start=key[2],
                financial_week_end=key[2] + timedelta(days=6),
                wb_cabinet_id=key[3],
                client_company_id=key[4],
                scheme=key[5],
                product_ref=source.product_ref,
                product_key=key[6],
                nm_id=source.nm_id,
                sku=source.sku,
                vendor_code=source.vendor_code,
                product=source.product,
                logistics_total=total,
                logistics_forward=order["forward"],
                logistics_reverse=order["reverse"],
                logistics_adjustment=order["adjustment"],
                logistics_unclassified=order["unclassified"],
                revenue=revenue,
                profit_before_tax=profit,
                profit_without_logistics=(
                    profit + total if profit is not None else None
                ),
                profit_effect_amount=-total,
                logistics_share_pct=(total / revenue * 100 if revenue > 0 else None),
                logistics_per_order=(total / chain_count if chain_count else None),
                logistics_per_sale=(total / sales if sales > 0 else None),
                sales_quantity=sales,
                return_quantity=order["returns"],
                chain_count=chain_count,
                logistics_row_count=order["logistics_count"],
                classified_row_count=order["classified_count"],
                low_sample=chain_count < LOW_SAMPLE_THRESHOLD,
                classification_status=(
                    "ready"
                    if order["classified_count"] == order["logistics_count"]
                    else "partial"
                ),
                coverage_status="ready",
                data_quality_status=(
                    "ready" if unit is not None else "missing_profit_link"
                ),
                recommendation_flags=tuple(flags),
                source_hash_digest=_digest_strings(order["hashes"]),
            )
        )
    return result


def _new_sku_bucket(row: LogisticsOrderRow) -> dict[str, Any]:
    return {
        "row": row,
        "total": Decimal("0"),
        "forward": Decimal("0"),
        "reverse": Decimal("0"),
        "adjustment": Decimal("0"),
        "unclassified": Decimal("0"),
        "sales": Decimal("0"),
        "returns": Decimal("0"),
        "source_revenue": Decimal("0"),
        "logistics_count": 0,
        "classified_count": 0,
        "chains": set(),
        "hashes": [],
    }


def _sku_key(
    tenant_id: str,
    client_id: str,
    financial_week_start: date,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_key: str,
) -> tuple[str, str, date, str, str, str, str]:
    return (
        tenant_id.strip(),
        client_id.strip(),
        financial_week_start,
        wb_cabinet_id,
        client_company_id,
        scheme.strip().casefold(),
        product_key,
    )


def _dimension_key(
    row: (
        LogisticsSourceRow
        | UnitEconomicsSlice
        | LogisticsOrderRow
        | LogisticsSkuRow
    ),
) -> tuple[Any, ...]:
    week_start = row.week_start if isinstance(row, LogisticsSourceRow) else (
        row.financial_week_start
    )
    return (
        row.tenant_id.strip(),
        row.client_id.strip(),
        week_start,
        row.wb_cabinet_id.strip(),
        row.client_company_id.strip(),
        row.scheme.strip().casefold(),
        row.product_key,
    )


def _source_dimension_totals(
    rows: Sequence[LogisticsSourceRow],
) -> dict[tuple[Any, ...], Decimal]:
    result: dict[tuple[Any, ...], Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        if row.delivery_service is not None:
            result[_dimension_key(row)] += row.delivery_service
    return dict(result)


def _order_dimension_totals(
    rows: Sequence[LogisticsOrderRow],
) -> dict[tuple[Any, ...], Decimal]:
    return _dimension_totals(rows, "logistics_total")


def _sku_dimension_totals(
    rows: Sequence[LogisticsSkuRow],
) -> dict[tuple[Any, ...], Decimal]:
    return _dimension_totals(rows, "logistics_total")


def _report_dimension_totals(
    rows: Sequence[UnitEconomicsSlice],
) -> dict[tuple[Any, ...], Decimal]:
    return _dimension_totals(rows, "logistics")


def _logistics_control_dimension_totals(
    source_rows: Sequence[LogisticsSourceRow],
    unit_rows: Sequence[UnitEconomicsSlice],
    *,
    report_period_start: date | None,
    report_period_end: date | None,
) -> dict[tuple[Any, ...], Decimal]:
    """Build the exact-period logistics control without changing weekly P&L."""
    result: dict[tuple[Any, ...], Decimal] = defaultdict(lambda: Decimal("0"))
    result.update(_report_dimension_totals(unit_rows))
    source_totals = _source_dimension_totals(source_rows)
    for key, amount in source_totals.items():
        week_start = key[2]
        if week_start is None or not _week_fully_contained(
            week_start, report_period_start, report_period_end
        ):
            result[key] += amount
            continue
        if key[5] != "not_applicable":
            continue
        # The accepted financial report historically assigns a missing
        # deliveryMethod to FBO. The logistics mart keeps the same grand total
        # but moves an explicit logistics correction to its own neutral scheme.
        fbo_key = (*key[:5], "fbo", *key[6:])
        result[fbo_key] -= amount
        result[key] += amount
    return dict(result)


def _normalize_unit_slice(row: UnitEconomicsSlice) -> UnitEconomicsSlice:
    scheme, _status = normalize_logistics_scheme(row.scheme)
    return replace(row, scheme=scheme)


def _week_fully_contained(
    week_start: date,
    report_period_start: date | None,
    report_period_end: date | None,
) -> bool:
    if report_period_start is None or report_period_end is None:
        return True
    return (
        report_period_start <= week_start
        and week_start + timedelta(days=6) <= report_period_end
    )


def _dimension_totals(
    rows: Sequence[UnitEconomicsSlice | LogisticsOrderRow | LogisticsSkuRow],
    field: str,
) -> dict[tuple[Any, ...], Decimal]:
    result: dict[tuple[Any, ...], Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        value = getattr(row, field)
        if isinstance(value, Decimal) and value.is_finite():
            result[_dimension_key(row)] += value
    return dict(result)


def _reconcile_dimension_totals(
    source: Mapping[tuple[Any, ...], Decimal],
    report: Mapping[tuple[Any, ...], Decimal],
) -> dict[str, Any]:
    unmatched_source = 0
    unmatched_report = 0
    delta_count = 0
    max_delta = Decimal("0")
    for key in set(source) | set(report):
        source_amount = source.get(key, Decimal("0"))
        report_amount = report.get(key, Decimal("0"))
        if key not in report and source_amount != 0:
            unmatched_source += 1
        if key not in source and report_amount != 0:
            unmatched_report += 1
        delta = abs(source_amount - report_amount)
        max_delta = max(max_delta, delta)
        if delta > RECONCILIATION_TOLERANCE:
            delta_count += 1
    return {
        "unmatched_source": unmatched_source,
        "unmatched_report": unmatched_report,
        "delta_count": delta_count,
        "max_delta": max_delta,
    }


def _add_sales_measures(bucket: dict[str, Any], row: LogisticsSourceRow) -> None:
    if row.quantity is None or row.retail_amount is None:
        return
    document = row.document_type.casefold()
    quantity = abs(row.quantity)
    if "возврат" in document:
        bucket["returns"] += quantity
        bucket["net"] -= quantity
        bucket["revenue"] -= abs(row.retail_amount)
    elif "продаж" in document:
        bucket["sales"] += quantity
        bucket["net"] += quantity
        bucket["revenue"] += row.retail_amount


def _required_source_errors(
    rows: Sequence[LogisticsSourceRow],
) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for index, row in enumerate(rows):
        errors = _source_row_required_errors(row)
        if errors:
            result[index] = errors
    return result


def _source_row_required_errors(row: LogisticsSourceRow) -> set[str]:
    if _is_financial_only_non_logistics_row(row):
        return set()
    errors = _effective_logistics_validation_errors(row) & _BLOCKING_SOURCE_ERRORS
    if not row.tenant_id.strip():
        errors.add("tenant_id_missing")
    if not row.client_id.strip():
        errors.add("client_id_missing")
    if not row.wb_cabinet_id.strip():
        errors.add("wb_cabinet_id_missing")
    if not row.client_company_id.strip():
        errors.add("client_company_id_missing")
    if row.financial_date is None:
        errors.add("financial_date_missing")
    if (
        row.delivery_service != Decimal("0")
        and row.scheme not in {"fbo", "fbs", "not_applicable"}
    ):
        errors.add("scheme_invalid" if row.scheme.strip() else "scheme_missing")
    if row.delivery_service is None:
        errors.add("delivery_service_missing")
    elif not _is_finite_decimal(row.delivery_service):
        errors.add("delivery_service_invalid")
    if not row.order_uid.strip():
        errors.add("order_uid_missing")
    if not row.product_key:
        errors.add("product_missing")
    return errors


def _required_report_errors(
    rows: Sequence[UnitEconomicsSlice],
) -> dict[int, set[str]]:
    result: dict[int, set[str]] = {}
    for index, row in enumerate(rows):
        errors = _report_row_required_errors(row)
        if errors:
            result[index] = errors
    return result


def _report_row_required_errors(row: UnitEconomicsSlice) -> set[str]:
    errors = set(row.validation_errors)
    if not row.tenant_id.strip():
        errors.add("report_tenant_id_missing")
    if not row.client_id.strip():
        errors.add("report_client_id_missing")
    if row.financial_week_start is None:
        errors.add("report_financial_date_missing")
    elif not isinstance(row.financial_week_start, date):
        errors.add("report_financial_date_invalid")
    if not row.wb_cabinet_id.strip():
        errors.add("report_wb_cabinet_id_missing")
    if not row.client_company_id.strip():
        errors.add("report_client_company_id_missing")
    if row.scheme.strip().casefold() not in {"fbo", "fbs", "not_applicable"}:
        errors.add(
            "report_scheme_invalid" if row.scheme.strip() else "report_scheme_missing"
        )
    if not row.product_key:
        errors.add("report_product_missing")
    if row.logistics is None:
        errors.add("report_logistics_missing")
    elif not _is_finite_decimal(row.logistics):
        errors.add("report_logistics_invalid")
    return errors


def _chain_dimension_conflict_count(rows: Sequence[LogisticsSourceRow]) -> int:
    companies: dict[tuple[str, date], set[str]] = defaultdict(set)
    schemes: dict[tuple[str, date], set[str]] = defaultdict(set)
    for row in rows:
        if row.chain_key and row.financial_date is not None:
            key = (row.chain_key, row.financial_date)
            companies[key].add(row.client_company_id.strip())
            scheme = row.scheme.strip().casefold()
            if (
                row.delivery_service not in (None, Decimal("0"))
                and scheme != "not_applicable"
            ):
                schemes[key].add(scheme)
    return sum(
        len(companies[key]) > 1 or len(schemes[key]) > 1
        for key in set(companies) | set(schemes)
    )


def _is_financial_only_non_logistics_row(row: LogisticsSourceRow) -> bool:
    return row.delivery_service == Decimal("0") and not row.order_uid.strip()


def _effective_logistics_validation_errors(row: LogisticsSourceRow) -> set[str]:
    if _is_financial_only_non_logistics_row(row):
        return set()
    errors = set(row.validation_errors)
    if row.delivery_service == Decimal("0"):
        errors.discard("scheme_missing")
        errors.discard("scheme_invalid")
    return errors


def _composite_key_collisions(rows: Iterable[LogisticsSourceRow]) -> int:
    identities: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for row in rows:
        if row.chain_key:
            identities[row.chain_key].add(
                (
                    row.tenant_id,
                    row.client_id,
                    row.wb_cabinet_id,
                    row.order_uid,
                    row.product_key,
                )
            )
    return sum(len(values) > 1 for values in identities.values())


def _raw_order_uid_cross_cabinet_reuse(rows: Iterable[LogisticsSourceRow]) -> int:
    cabinets_by_order: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        if row.order_uid:
            cabinets_by_order[(row.tenant_id, row.client_id, row.order_uid)].add(
                row.wb_cabinet_id
            )
    return sum(len(cabinets) > 1 for cabinets in cabinets_by_order.values())


def _scope_mismatch_count(
    source_rows: Sequence[LogisticsSourceRow],
    unit_rows: Sequence[UnitEconomicsSlice],
    *,
    expected_tenant_id: str,
    expected_client_id: str,
) -> int:
    expected = (expected_tenant_id.strip(), expected_client_id.strip())
    row_scopes = [
        (row.tenant_id.strip(), row.client_id.strip())
        for row in (*source_rows, *unit_rows)
    ]
    nonempty_scopes = sorted(
        {scope for scope in row_scopes if scope[0] and scope[1]}
    )
    if not all(expected):
        if len(nonempty_scopes) <= 1:
            return 0
        expected = nonempty_scopes[0]
    return sum(scope != expected for scope in row_scopes)


def _input_hash(
    source_rows: Sequence[LogisticsSourceRow],
    unit_rows: Sequence[UnitEconomicsSlice],
    *,
    report_period_start: date | None,
    report_period_end: date | None,
    input_diagnostics: LogisticsInputDiagnostics,
) -> str:
    value = {
        "methodology": LOGISTICS_METHODOLOGY_VERSION,
        "chain": CHAIN_KEY_VERSION,
        "reportPeriodStart": _date_text(report_period_start),
        "reportPeriodEnd": _date_text(report_period_end),
        "inputDiagnostics": {
            "invalidSourcePayloadShapeCount": (
                input_diagnostics.invalid_source_payload_shape_count
            ),
            "sourceIdentityErrorCount": (
                input_diagnostics.source_identity_error_count
            ),
            "sourceRevisionConflictCount": (
                input_diagnostics.source_revision_conflict_count
            ),
            "sourceRevisionDiscardedCount": (
                input_diagnostics.source_revision_discarded_count
            ),
            "scopeMismatchCount": input_diagnostics.scope_mismatch_count,
            "blockingReasons": sorted(input_diagnostics.blocking_reasons),
            "lineage": sorted(
                (dict(item) for item in input_diagnostics.lineage_records),
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True
                ),
            ),
        },
        "source": sorted(
            (_source_hash_record(row) for row in source_rows),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        ),
        "unit": sorted(
            (_unit_hash_record(row) for row in unit_rows),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        ),
    }
    return _hash_payload(value)


def _source_hash_record(row: LogisticsSourceRow) -> dict[str, Any]:
    return {
        "tenantId": row.tenant_id.strip(),
        "clientId": row.client_id.strip(),
        "cabinetId": row.wb_cabinet_id.strip(),
        "companyId": row.client_company_id.strip(),
        "sourceRowId": row.source_row_id,
        "sourceHash": row.source_hash,
        "financialDate": _date_text(row.financial_date),
        "orderDate": _date_text(row.order_date),
        "orderUid": row.order_uid.strip(),
        "nmId": row.nm_id.strip(),
        "sku": row.sku.strip(),
        "vendorCode": row.vendor_code,
        "product": row.product,
        "scheme": row.scheme.strip().casefold(),
        "warehouse": row.warehouse,
        "destination": row.destination,
        "documentType": row.document_type,
        "operationName": row.operation_name,
        "quantity": _decimal_text(row.quantity),
        "retailAmount": _decimal_text(row.retail_amount),
        "deliveryService": _decimal_text(row.delivery_service),
        "deliveryAmount": _decimal_text(row.delivery_amount),
        "returnAmount": _decimal_text(row.return_amount),
        "rebillLogisticCost": _decimal_text(row.rebill_logistic_cost),
        "validationErrors": sorted(
            set(row.validation_errors) | _source_row_required_errors(row)
        ),
    }


def _unit_hash_record(row: UnitEconomicsSlice) -> dict[str, Any]:
    return {
        "tenantId": row.tenant_id.strip(),
        "clientId": row.client_id.strip(),
        "sourceRowId": row.source_row_id,
        "financialWeekStart": _date_text(row.financial_week_start),
        "cabinetId": row.wb_cabinet_id.strip(),
        "companyId": row.client_company_id.strip(),
        "scheme": row.scheme.strip().casefold(),
        "nmId": row.nm_id.strip(),
        "sku": row.sku.strip(),
        "vendorCode": row.vendor_code,
        "product": row.product,
        "revenue": _decimal_text(row.revenue),
        "profitBeforeTax": _decimal_text(row.profit_before_tax),
        "logistics": _decimal_text(row.logistics),
        "validationErrors": sorted(_report_row_required_errors(row)),
    }


def _report_period(
    unit_rows: Sequence[UnitEconomicsSlice],
    *,
    report_period_start: date | None,
    report_period_end: date | None,
) -> tuple[date | None, date | None]:
    dated_rows = [
        row.financial_week_start
        for row in unit_rows
        if isinstance(row.financial_week_start, date)
    ]
    if not dated_rows:
        return report_period_start, report_period_end
    return (
        report_period_start or min(dated_rows),
        report_period_end
        or max(dated_rows) + timedelta(days=6),
    )


def _single_or_mixed(values: set[str]) -> tuple[str, str]:
    if len(values) > 1:
        return "mixed", "mixed"
    if values:
        value = next(iter(values))
        return (value, "ready") if value else ("", "missing")
    return "", "missing"


def _stable_display(values: set[str], fallback: str) -> str:
    return sorted(values)[0] if values else fallback


def _parse_required_decimal(
    payload: Mapping[str, Any],
    errors: list[str],
    field_name: str,
    *names: str,
) -> Decimal | None:
    value, status = _parse_decimal(_raw_first(payload, *names), required=True)
    if status != "ready":
        errors.append(f"{field_name}_{status}")
    return value


def _parse_optional_decimal(
    payload: Mapping[str, Any],
    errors: list[str],
    field_name: str,
    *names: str,
) -> Decimal | None:
    value, status = _parse_decimal(_raw_first(payload, *names), required=False)
    if status == "invalid":
        errors.append(f"{field_name}_invalid")
    return value


def _parse_decimal(value: Any, *, required: bool) -> tuple[Decimal | None, str]:
    if value in (None, ""):
        return None, "missing" if required else "not_provided"
    try:
        parsed = Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None, "invalid"
    if not parsed.is_finite():
        return None, "invalid"
    return parsed, "ready"


def _parse_date(value: Any, *, required: bool = True) -> tuple[date | None, str]:
    if value in (None, ""):
        return None, "missing" if required else "not_provided"
    if isinstance(value, datetime):
        return value.date(), "ready"
    if isinstance(value, date):
        return value, "ready"
    text = _text(value)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text), "ready"
        if not re.fullmatch(
            (
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
                r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
            ),
            text,
        ):
            return None, "invalid"
        normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        return datetime.fromisoformat(normalized).date(), "ready"
    except ValueError:
        return None, "invalid"


def normalize_logistics_scheme(
    value: Any,
    *,
    operation_name: str = "",
) -> tuple[str, str]:
    text = _text(value).casefold()
    if not text:
        if operation_name.strip().casefold() == "коррекция логистики":
            return "not_applicable", "ready"
        return "", "missing"
    if text == "not_applicable":
        return "not_applicable", "ready"
    if text in {"склад wb", "склад вб"} or re.match(r"^(?:fbo|fbw)\b", text):
        return "fbo", "ready"
    if text == "склад продавца" or re.match(r"^(?:fbs|dbs)\b", text):
        return "fbs", "ready"
    return "", "invalid"


def _parse_scheme(value: Any) -> tuple[str, str]:
    return normalize_logistics_scheme(value)


def _digest_strings(values: Iterable[str]) -> str:
    return _hash_payload(sorted(value for value in values if value))


def _hash_payload(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        return str(value)
    if not value.is_finite():
        return f"invalid:{value}"
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _is_finite_decimal(value: Any) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(numerator) * Decimal("100") / Decimal(denominator)


def _raw_first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""
