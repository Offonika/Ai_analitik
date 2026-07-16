from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

LOGISTICS_METHODOLOGY_VERSION = "wb-logistics-v1"
CHAIN_KEY_VERSION = "wb-order-product-v1"
RECONCILIATION_TOLERANCE = Decimal("0.01")
LOW_SAMPLE_THRESHOLD = 10

LogisticsClass = Literal["forward", "reverse", "adjustment", "unclassified"]

_ADJUSTMENT_OPERATION_MARKERS = (
    "перерасчет",
    "перерасчёт",
    "корректиров",
    "возмещени",
)


@dataclass(frozen=True)
class LogisticsSourceRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    client_company_id: str
    source_row_id: str
    source_hash: str
    financial_date: date
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
    quantity: Decimal
    retail_amount: Decimal
    delivery_service: Decimal
    delivery_amount: Decimal
    return_amount: Decimal
    rebill_logistic_cost: Decimal

    @property
    def product_key(self) -> str:
        if self.nm_id:
            return f"nm:{self.nm_id}"
        if self.sku:
            return f"sku:{self.sku}"
        return ""

    @property
    def week_start(self) -> date:
        return self.financial_date - timedelta(days=self.financial_date.weekday())

    @property
    def chain_key(self) -> str:
        if not self.order_uid or not self.product_key:
            return ""
        return logistics_chain_key(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            wb_cabinet_id=self.wb_cabinet_id,
            order_uid=self.order_uid,
            product_key=self.product_key,
        )


@dataclass(frozen=True)
class UnitEconomicsSlice:
    financial_week_start: date
    wb_cabinet_id: str
    client_company_id: str
    scheme: str
    nm_id: str
    sku: str
    vendor_code: str
    product: str
    revenue: Decimal
    profit_before_tax: Decimal
    logistics: Decimal

    @property
    def product_key(self) -> str:
        if self.nm_id:
            return f"nm:{self.nm_id}"
        if self.sku:
            return f"sku:{self.sku}"
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
    financial_week_start: date
    operation_date_start: date
    operation_date_end: date
    order_date: date | None
    product_key: str
    nm_id: str
    sku: str
    vendor_code: str
    product: str
    scheme: str
    warehouse: str
    destination: str
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
    financial_week_start: date
    wb_cabinet_id: str
    client_company_id: str
    scheme: str
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
    methodology_version: str
    chain_key_version: str
    source_row_count: int
    logistics_row_count: int
    keyed_logistics_row_count: int
    product_logistics_row_count: int
    key_coverage_pct: Decimal | None
    product_coverage_pct: Decimal | None
    classification_row_coverage_pct: Decimal | None
    cross_cabinet_collision_count: int
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
    return LogisticsSourceRow(
        tenant_id=tenant_id,
        client_id=client_id,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        source_row_id=source_row_id,
        source_hash=source_hash or _hash_payload(payload),
        financial_date=(
            _date_value(_first(payload, "rrDate", "rr_dt", "createDate"))
            or fallback_date
        ),
        order_date=_date_value(_first(payload, "orderDt", "order_dt")),
        order_uid=_text(_first(payload, "orderUid", "order_uid")),
        nm_id=_text(_first(payload, "nmId", "nm_id")),
        sku=_text(_first(payload, "sku", "barcode")),
        vendor_code=_text(_first(payload, "vendorCode", "sa_name")),
        product=_text(_first(payload, "title", "product")),
        scheme=_scheme(_first(payload, "deliveryMethod", "delivery_method")),
        warehouse=_text(_first(payload, "officeName", "office_name")),
        destination=_text(
            _first(payload, "country", "ppvzOfficeName", "ppvz_office_name")
        ),
        document_type=_text(_first(payload, "docTypeName", "doc_type_name")),
        operation_name=_text(
            _first(payload, "sellerOperName", "supplierOperName", "operation_type")
        ),
        quantity=_decimal(_first(payload, "quantity")),
        retail_amount=_decimal(_first(payload, "retailAmount", "retail_amount")),
        delivery_service=_decimal(
            _first(payload, "deliveryService", "delivery_service", "delivery_rub")
        ),
        delivery_amount=_decimal(_first(payload, "deliveryAmount", "delivery_amount")),
        return_amount=_decimal(_first(payload, "returnAmount", "return_amount")),
        rebill_logistic_cost=_decimal(
            _first(payload, "rebillLogisticCost", "rebill_logistic_cost")
        ),
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


def classify_logistics_row(row: LogisticsSourceRow) -> LogisticsClass:
    forward = row.delivery_amount != 0
    reverse = row.return_amount != 0
    if forward and not reverse:
        return "forward"
    if reverse and not forward:
        return "reverse"
    operation = f"{row.document_type} {row.operation_name}".casefold()
    adjustment_confirmed = row.rebill_logistic_cost != 0 or any(
        marker in operation for marker in _ADJUSTMENT_OPERATION_MARKERS
    )
    if not forward and not reverse and adjustment_confirmed:
        return "adjustment"
    return "unclassified"


def build_logistics_analysis(
    source_rows: Sequence[LogisticsSourceRow],
    unit_rows: Sequence[UnitEconomicsSlice],
) -> LogisticsAnalysisResult:
    logistics_rows = [row for row in source_rows if row.delivery_service != 0]
    raw_total = sum((row.delivery_service for row in logistics_rows), Decimal("0"))
    report_total = sum((row.logistics for row in unit_rows), Decimal("0"))
    keyed_count = sum(bool(row.chain_key) for row in logistics_rows)
    product_count = sum(bool(row.product_key) for row in logistics_rows)
    collisions = _cross_cabinet_collisions(logistics_rows)
    blocking: list[str] = []
    if logistics_rows and keyed_count != len(logistics_rows):
        blocking.append("chain_key_coverage_below_100pct")
    if logistics_rows and product_count != len(logistics_rows):
        blocking.append("product_key_coverage_below_100pct")
    if collisions:
        blocking.append("cross_cabinet_order_uid_collision")
    if abs(raw_total - report_total) > RECONCILIATION_TOLERANCE:
        blocking.append("raw_report_logistics_mismatch")

    input_hash = _input_hash(source_rows, unit_rows)
    base_context = LogisticsAnalysisContext(
        data_status="blocked" if blocking else "ready",
        methodology_version=LOGISTICS_METHODOLOGY_VERSION,
        chain_key_version=CHAIN_KEY_VERSION,
        source_row_count=len(source_rows),
        logistics_row_count=len(logistics_rows),
        keyed_logistics_row_count=keyed_count,
        product_logistics_row_count=product_count,
        key_coverage_pct=_pct(keyed_count, len(logistics_rows)),
        product_coverage_pct=_pct(product_count, len(logistics_rows)),
        classification_row_coverage_pct=None,
        cross_cabinet_collision_count=collisions,
        raw_logistics_total=raw_total,
        order_logistics_total=Decimal("0"),
        sku_logistics_total=Decimal("0"),
        report_logistics_total=report_total,
        order_delta=-raw_total,
        sku_delta=-report_total,
        blocking_reasons=tuple(blocking),
        review_reasons=(),
        input_hash=input_hash,
    )
    if blocking:
        return LogisticsAnalysisResult(base_context, (), ())

    order_rows = build_order_rows(source_rows)
    sku_rows = build_sku_rows(order_rows, unit_rows)
    order_total = sum((row.logistics_total for row in order_rows), Decimal("0"))
    sku_total = sum((row.logistics_total for row in sku_rows), Decimal("0"))
    post_build_blocking: list[str] = []
    if abs(order_total - raw_total) > RECONCILIATION_TOLERANCE:
        post_build_blocking.append("order_raw_logistics_mismatch")
    if abs(sku_total - order_total) > RECONCILIATION_TOLERANCE:
        post_build_blocking.append("sku_order_logistics_mismatch")
    if abs(sku_total - report_total) > RECONCILIATION_TOLERANCE:
        post_build_blocking.append("sku_report_logistics_mismatch")
    classified_count = sum(row.classified_row_count for row in order_rows)
    unclassified_count = len(logistics_rows) - classified_count
    review = ("unclassified_logistics_rows",) if unclassified_count > 0 else ()
    data_status = "blocked" if post_build_blocking else "partial" if review else "ready"
    context = replace(
        base_context,
        data_status=data_status,
        classification_row_coverage_pct=_pct(classified_count, len(logistics_rows)),
        order_logistics_total=order_total,
        sku_logistics_total=sku_total,
        order_delta=order_total - raw_total,
        sku_delta=sku_total - report_total,
        blocking_reasons=tuple(post_build_blocking),
        review_reasons=review,
    )
    if post_build_blocking:
        return LogisticsAnalysisResult(context, (), ())
    return LogisticsAnalysisResult(context, tuple(order_rows), tuple(sku_rows))


def build_order_rows(
    source_rows: Sequence[LogisticsSourceRow],
) -> list[LogisticsOrderRow]:
    groups: dict[tuple[str, date], dict[str, Any]] = {}
    for row in source_rows:
        chain_key = row.chain_key
        countable = bool(chain_key)
        if not countable:
            if row.delivery_service == 0:
                continue
            chain_key = hashlib.sha256(
                (
                    f"{CHAIN_KEY_VERSION}\x1funlinked\x1f{row.tenant_id}\x1f"
                    f"{row.client_id}\x1f{row.wb_cabinet_id}\x1f{row.source_hash}"
                ).encode()
            ).hexdigest()
        group_key = (chain_key, row.week_start)
        bucket = groups.setdefault(
            group_key,
            {
                "chain_key": chain_key,
                "countable": countable,
                "row": row,
                "operation_dates": [],
                "order_dates": [],
                "logistics_total": Decimal("0"),
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
            },
        )
        bucket["source_count"] += 1
        bucket["operation_dates"].append(row.financial_date)
        if row.order_date is not None:
            bucket["order_dates"].append(row.order_date)
        bucket["hashes"].append(row.source_hash)
        if row.delivery_service != 0:
            category = classify_logistics_row(row)
            bucket["logistics_total"] += row.delivery_service
            bucket[category] += row.delivery_service
            bucket["logistics_count"] += 1
            if category != "unclassified":
                bucket["classified_count"] += 1
        _add_sales_measures(bucket, row)

    result: list[LogisticsOrderRow] = []
    for (chain_key, week_start), bucket in sorted(groups.items()):
        row = bucket["row"]
        source_hash_digest = _digest_strings(bucket["hashes"])
        segment_key = hashlib.sha256(
            f"{chain_key}\x1f{week_start.isoformat()}".encode()
        ).hexdigest()
        classification_status = (
            "ready"
            if bucket["classified_count"] == bucket["logistics_count"]
            else "partial"
        )
        coverage_status = "ready" if bucket["countable"] else "missing_chain_key"
        data_quality_status = "ready" if bucket["countable"] else "missing_chain_key"
        result.append(
            LogisticsOrderRow(
                chain_key=chain_key,
                chain_segment_key=segment_key,
                countable_order=bucket["countable"],
                tenant_id=row.tenant_id,
                client_id=row.client_id,
                wb_cabinet_id=row.wb_cabinet_id,
                client_company_id=row.client_company_id,
                financial_week_start=week_start,
                operation_date_start=min(bucket["operation_dates"]),
                operation_date_end=max(bucket["operation_dates"]),
                order_date=(
                    min(bucket["order_dates"]) if bucket["order_dates"] else None
                ),
                product_key=row.product_key,
                nm_id=row.nm_id,
                sku=row.sku,
                vendor_code=row.vendor_code,
                product=row.product,
                scheme=row.scheme,
                warehouse=row.warehouse,
                destination=row.destination,
                logistics_total=bucket["logistics_total"],
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
                source_hash_digest=source_hash_digest,
                classification_status=classification_status,
                coverage_status=coverage_status,
                data_quality_status=data_quality_status,
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
        if not row.product_key:
            continue
        key = _sku_key(
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
    for key in sorted(set(order_buckets) | set(unit_buckets), key=str):
        order = order_buckets.get(key)
        unit = unit_buckets.get(key)
        if order is None:
            assert unit is not None
            source = unit["row"]
            order = _empty_sku_bucket(source)
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
                financial_week_start=key[0],
                wb_cabinet_id=key[1],
                client_company_id=key[2],
                scheme=key[3],
                product_key=key[4],
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
                coverage_status=("ready" if chain_count else "missing_chain_key"),
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


def _empty_sku_bucket(row: UnitEconomicsSlice) -> dict[str, Any]:
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
    financial_week_start: date,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_key: str,
) -> tuple[date, str, str, str, str]:
    return (
        financial_week_start,
        wb_cabinet_id,
        client_company_id,
        _scheme(scheme),
        product_key,
    )


def _add_sales_measures(bucket: dict[str, Any], row: LogisticsSourceRow) -> None:
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


def _cross_cabinet_collisions(rows: Iterable[LogisticsSourceRow]) -> int:
    cabinets_by_order: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        if row.order_uid:
            cabinets_by_order[(row.tenant_id, row.client_id, row.order_uid)].add(
                row.wb_cabinet_id
            )
    return sum(len(cabinets) > 1 for cabinets in cabinets_by_order.values())


def _input_hash(
    source_rows: Sequence[LogisticsSourceRow],
    unit_rows: Sequence[UnitEconomicsSlice],
) -> str:
    value = {
        "methodology": LOGISTICS_METHODOLOGY_VERSION,
        "chain": CHAIN_KEY_VERSION,
        "source": sorted(
            (
                row.tenant_id,
                row.client_id,
                row.wb_cabinet_id,
                row.source_hash,
            )
            for row in source_rows
        ),
        "unit": sorted(
            (
                row.financial_week_start.isoformat(),
                row.wb_cabinet_id,
                row.client_company_id,
                row.scheme,
                row.product_key,
                str(row.revenue),
                str(row.profit_before_tax),
                str(row.logistics),
            )
            for row in unit_rows
        ),
    }
    return _hash_payload(value)


def _digest_strings(values: Iterable[str]) -> str:
    return _hash_payload(sorted(value for value in values if value))


def _hash_payload(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pct(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return Decimal(numerator) * Decimal("100") / Decimal(denominator)


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _scheme(value: Any) -> str:
    text = _text(value).casefold()
    return "fbs" if "fbs" in text else "fbo"
