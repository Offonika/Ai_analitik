from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO, TextIOBase
from pathlib import Path
from typing import Any

from wb_unit_economics.contracts import (
    AccountOrgMapping,
    MappingStatus,
    OnecUnfCostSnapshot,
    SalesModel,
    SkuMapping,
    WbApiSnapshot,
)
from wb_unit_economics.wb_finance import (
    normalize_finance_row,
    raw_payload_hash,
)

POSTGRES_SCHEMA = "wb_unit_economics"
PAGES_TABLE = f"{POSTGRES_SCHEMA}.wb_finance_snapshot_pages"
PAGES_STAGE = "wb_finance_snapshot_pages_stage"
DETAIL_TABLE = f"{POSTGRES_SCHEMA}.wb_finance_detail_raw"
DETAIL_STAGE = "wb_finance_detail_raw_stage"
MAPPING_TABLE = f"{POSTGRES_SCHEMA}.sku_mapping_snapshot"
MAPPING_STAGE = "sku_mapping_snapshot_stage"
COST_TABLE = f"{POSTGRES_SCHEMA}.onec_cost_snapshot"
COST_STAGE = "onec_cost_snapshot_stage"

PAGE_COLUMNS = (
    "snapshot_id",
    "client_id",
    "seller_account_id",
    "account_name",
    "page_index",
    "ok",
    "status",
    "row_count",
    "status_code",
    "rrd_id_start",
    "rrd_id_next",
    "raw_payload_hash",
    "output_file",
    "error",
    "manifest_payload",
    "generated_at",
    "period_start",
    "period_end",
    "report_period",
    "endpoint",
    "source",
    "request_delay_seconds",
)

DETAIL_COLUMNS = (
    "snapshot_id",
    "client_id",
    "seller_account_id",
    "account_name",
    "organization_id",
    "source_endpoint",
    "source_file",
    "page_index",
    "row_number",
    "loaded_at",
    "manifest_period_start",
    "manifest_period_end",
    "report_period",
    "row_date",
    "week_start",
    "week_end",
    "is_partial_source",
    "raw_payload_hash",
    "row_payload",
    "wb_document_id",
    "report_id",
    "rrd_id",
    "rr_date",
    "sale_dt",
    "order_dt",
    "create_date",
    "date_from",
    "date_to",
    "order_uid",
    "order_id",
    "shk_id",
    "sticker_id",
    "trbx_id",
    "nm_id",
    "vendor_code",
    "title",
    "sku",
    "doc_type_name",
    "seller_oper_name",
    "delivery_method",
    "office_name",
    "ppvz_office_name",
    "ppvz_office_id",
    "country",
    "gi_box_type_name",
    "dlv_prc",
    "fix_tariff_date_from",
    "fix_tariff_date_to",
    "sales_model",
    "operation_type",
    "quantity",
    "signed_quantity",
    "retail_amount",
    "net_revenue",
    "ppvz_sales_commission",
    "wb_commission",
    "delivery_service",
    "delivery_amount",
    "return_amount",
    "rebill_logistic_cost",
    "logistics",
    "paid_storage",
    "storage",
    "paid_acceptance",
    "acceptance",
    "penalty",
    "additional_payment",
    "deduction",
    "penalties_and_holdbacks",
    "acquiring_fee",
    "acquiring",
    "currency",
    "srid",
)

MAPPING_COLUMNS = (
    "snapshot_id",
    "mapping_key",
    "client_id",
    "seller_account_id",
    "organization_id",
    "nm_id",
    "vendor_code",
    "barcode",
    "onec_item_id",
    "onec_article",
    "onec_characteristic",
    "match_method",
    "confidence",
    "status",
    "comment",
    "updated_by",
    "updated_at",
)

COST_COLUMNS = (
    "snapshot_id",
    "cost_key",
    "client_id",
    "organization_id",
    "loaded_at",
    "onec_item_id",
    "article",
    "barcode",
    "name",
    "characteristic",
    "cost_value",
    "extra_costs_value",
    "cost_currency",
    "cost_method",
    "effective_from",
    "effective_to",
    "source_document",
    "raw_payload_hash",
)


@dataclass(frozen=True)
class PostgresTarget:
    database: str
    host: str = ""
    port: int | None = None
    user: str = ""
    psql_bin: str = "psql"


@dataclass(frozen=True)
class WbFinancePostgresSummary:
    snapshot_id: str
    page_count: int
    raw_row_count: int
    seller_accounts: tuple[str, ...]


@dataclass(frozen=True)
class CalculationInputsPostgresSummary:
    snapshot_id: str
    sku_mapping_count: int
    cost_snapshot_count: int


def load_wb_finance_export_to_postgres(
    export_dir: Path,
    *,
    client_id: str,
    account_org_mapping: Iterable[AccountOrgMapping],
    target: PostgresTarget,
    schema_path: Path,
    snapshot_id: str | None = None,
) -> WbFinancePostgresSummary:
    export_dir = Path(export_dir)
    snapshot = snapshot_id or export_dir.name
    manifest = _read_manifest(export_dir)
    page_rows = list(
        iter_wb_finance_page_records(
            export_dir,
            client_id=client_id,
            snapshot_id=snapshot,
        )
    )
    detail_rows = iter_wb_finance_detail_records(
        export_dir,
        client_id=client_id,
        account_org_mapping=account_org_mapping,
        snapshot_id=snapshot,
    )
    _run_psql(target, schema_path.read_text(encoding="utf-8"))
    _copy_into_table(
        target,
        table=PAGES_TABLE,
        stage_table=PAGES_STAGE,
        columns=PAGE_COLUMNS,
        rows=page_rows,
        conflict_sql="""
        ON CONFLICT (snapshot_id, seller_account_id, page_index) DO UPDATE SET
            account_name = EXCLUDED.account_name,
            ok = EXCLUDED.ok,
            status = EXCLUDED.status,
            row_count = EXCLUDED.row_count,
            status_code = EXCLUDED.status_code,
            rrd_id_start = EXCLUDED.rrd_id_start,
            rrd_id_next = EXCLUDED.rrd_id_next,
            raw_payload_hash = EXCLUDED.raw_payload_hash,
            output_file = EXCLUDED.output_file,
            error = EXCLUDED.error,
            manifest_payload = EXCLUDED.manifest_payload,
            generated_at = EXCLUDED.generated_at,
            period_start = EXCLUDED.period_start,
            period_end = EXCLUDED.period_end,
            report_period = EXCLUDED.report_period,
            endpoint = EXCLUDED.endpoint,
            source = EXCLUDED.source,
            request_delay_seconds = EXCLUDED.request_delay_seconds,
            loaded_at = now()
        """,
    )
    raw_count = _copy_into_table(
        target,
        table=DETAIL_TABLE,
        stage_table=DETAIL_STAGE,
        columns=DETAIL_COLUMNS,
        rows=detail_rows,
        conflict_sql="""
        ON CONFLICT (
            snapshot_id, seller_account_id, source_file, row_number, raw_payload_hash
        ) DO NOTHING
        """,
    )
    accounts = tuple(
        sorted(
            {
                str(row.get("seller_account_id"))
                for row in manifest.get("results", [])
                if isinstance(row, dict) and row.get("seller_account_id")
            }
        )
    )
    return WbFinancePostgresSummary(
        snapshot_id=snapshot,
        page_count=len(page_rows),
        raw_row_count=raw_count,
        seller_accounts=accounts,
    )


def load_wb_finance_snapshots_from_postgres(
    *,
    target: PostgresTarget,
    client_id: str,
    snapshot_id: str | None = None,
    seller_account_id: str | None = None,
) -> list[WbApiSnapshot]:
    filters = ["client_id = " + _sql_literal(client_id)]
    if snapshot_id:
        filters.append("snapshot_id = " + _sql_literal(snapshot_id))
    if seller_account_id:
        filters.append("seller_account_id = " + _sql_literal(seller_account_id))
    where_sql = " AND ".join(filters)
    rows = _query_psql_csv(
        target,
        f"""
        SELECT
            client_id,
            seller_account_id,
            organization_id,
            row_date,
            source_endpoint,
            loaded_at,
            wb_document_id,
            report_id AS wb_report_id,
            nm_id,
            vendor_code,
            sku AS barcode,
            sales_model,
            operation_type,
            signed_quantity AS quantity,
            net_revenue,
            wb_commission,
            logistics,
            storage,
            acceptance,
            deduction,
            penalty,
            additional_payment,
            penalties_and_holdbacks,
            acquiring,
            currency,
            raw_payload_hash,
            row_payload,
            sale_dt,
            is_partial_source
        FROM {DETAIL_TABLE}
        WHERE {where_sql}
        ORDER BY snapshot_id, seller_account_id, source_file, row_number
        """,
    )
    return [wb_finance_db_row_to_snapshot(row) for row in rows]


def load_sku_mappings_to_postgres(
    mappings: Iterable[SkuMapping],
    *,
    target: PostgresTarget,
    schema_path: Path,
    snapshot_id: str,
    replace_snapshot: bool = False,
) -> int:
    rows = list(iter_sku_mapping_records(mappings, snapshot_id=snapshot_id))
    _run_psql(target, schema_path.read_text(encoding="utf-8"))
    if replace_snapshot:
        _run_psql(
            target,
            f"DELETE FROM {MAPPING_TABLE} "
            f"WHERE snapshot_id = {_sql_literal(snapshot_id)};",
        )
    return _copy_into_table(
        target,
        table=MAPPING_TABLE,
        stage_table=MAPPING_STAGE,
        columns=MAPPING_COLUMNS,
        rows=rows,
        conflict_sql="""
        ON CONFLICT (snapshot_id, mapping_key) DO UPDATE SET
            client_id = EXCLUDED.client_id,
            seller_account_id = EXCLUDED.seller_account_id,
            organization_id = EXCLUDED.organization_id,
            nm_id = EXCLUDED.nm_id,
            vendor_code = EXCLUDED.vendor_code,
            barcode = EXCLUDED.barcode,
            onec_item_id = EXCLUDED.onec_item_id,
            onec_article = EXCLUDED.onec_article,
            onec_characteristic = EXCLUDED.onec_characteristic,
            match_method = EXCLUDED.match_method,
            confidence = EXCLUDED.confidence,
            status = EXCLUDED.status,
            comment = EXCLUDED.comment,
            updated_by = EXCLUDED.updated_by,
            updated_at = EXCLUDED.updated_at,
            loaded_at = now()
        """,
    )


def load_cost_snapshots_to_postgres(
    cost_snapshots: Iterable[OnecUnfCostSnapshot],
    *,
    target: PostgresTarget,
    schema_path: Path,
    snapshot_id: str,
    replace_snapshot: bool = False,
) -> int:
    rows = list(iter_cost_snapshot_records(cost_snapshots, snapshot_id=snapshot_id))
    _run_psql(target, schema_path.read_text(encoding="utf-8"))
    if replace_snapshot:
        _run_psql(
            target,
            f"DELETE FROM {COST_TABLE} "
            f"WHERE snapshot_id = {_sql_literal(snapshot_id)};",
        )
    return _copy_into_table(
        target,
        table=COST_TABLE,
        stage_table=COST_STAGE,
        columns=COST_COLUMNS,
        rows=rows,
        conflict_sql="""
        ON CONFLICT (snapshot_id, cost_key) DO UPDATE SET
            client_id = EXCLUDED.client_id,
            organization_id = EXCLUDED.organization_id,
            loaded_at = EXCLUDED.loaded_at,
            onec_item_id = EXCLUDED.onec_item_id,
            article = EXCLUDED.article,
            barcode = EXCLUDED.barcode,
            name = EXCLUDED.name,
            characteristic = EXCLUDED.characteristic,
            cost_value = EXCLUDED.cost_value,
            extra_costs_value = EXCLUDED.extra_costs_value,
            cost_currency = EXCLUDED.cost_currency,
            cost_method = EXCLUDED.cost_method,
            effective_from = EXCLUDED.effective_from,
            effective_to = EXCLUDED.effective_to,
            source_document = EXCLUDED.source_document,
            raw_payload_hash = EXCLUDED.raw_payload_hash,
            inserted_at = now()
        """,
    )


def load_sku_mappings_from_postgres(
    *,
    target: PostgresTarget,
    client_id: str,
    snapshot_id: str | None = None,
) -> list[SkuMapping]:
    filters = ["client_id = " + _sql_literal(client_id)]
    if snapshot_id:
        filters.append("snapshot_id = " + _sql_literal(snapshot_id))
    rows = _query_psql_csv(
        target,
        f"""
        SELECT
            client_id,
            seller_account_id,
            organization_id,
            nm_id,
            vendor_code,
            barcode,
            onec_item_id,
            onec_article,
            onec_characteristic,
            match_method,
            confidence,
            status,
            comment,
            updated_by,
            updated_at
        FROM {MAPPING_TABLE}
        WHERE {" AND ".join(filters)}
        ORDER BY snapshot_id, seller_account_id, nm_id NULLS LAST, vendor_code, barcode
        """,
    )
    return [sku_mapping_db_row_to_contract(row) for row in rows]


def load_cost_snapshots_from_postgres(
    *,
    target: PostgresTarget,
    client_id: str,
    snapshot_id: str | None = None,
) -> list[OnecUnfCostSnapshot]:
    filters = ["client_id = " + _sql_literal(client_id)]
    if snapshot_id:
        filters.append("snapshot_id = " + _sql_literal(snapshot_id))
    rows = _query_psql_csv(
        target,
        f"""
        SELECT
            client_id,
            organization_id,
            loaded_at,
            onec_item_id,
            article,
            barcode,
            name,
            characteristic,
            cost_value,
            extra_costs_value,
            cost_currency,
            cost_method,
            effective_from,
            effective_to,
            source_document,
            raw_payload_hash
        FROM {COST_TABLE}
        WHERE {" AND ".join(filters)}
        ORDER BY
            snapshot_id,
            organization_id,
            onec_item_id,
            characteristic,
            effective_from
        """,
    )
    return [cost_snapshot_db_row_to_contract(row) for row in rows]


def wb_finance_db_row_to_snapshot(row: Mapping[str, object]) -> WbApiSnapshot:
    row_date = _required_date(row.get("row_date"))
    sale_dt = _parse_datetime(row.get("sale_dt"))
    nm_id = _int_or_none(row.get("nm_id"))
    raw_payload = _row_payload(row.get("row_payload"))
    is_return = _text(row.get("operation_type")).strip().lower() in {
        "return",
        "возврат",
    }
    vat_input_from_wb = _signed_decimal(
        _decimal(_first(raw_payload, "vwNds", "vw_nds"))
        + _decimal(_first(raw_payload, "agencyVat", "agency_vat")),
        is_return=is_return,
    )
    return WbApiSnapshot(
        client_id=_required_text(row.get("client_id")),
        seller_account_id=_required_text(row.get("seller_account_id")),
        organization_id=_required_text(row.get("organization_id")),
        period_start=row_date,
        period_end=row_date,
        source_endpoint=_required_text(row.get("source_endpoint")),
        loaded_at=_required_datetime(row.get("loaded_at")),
        wb_document_id=_required_text(row.get("wb_document_id")),
        wb_report_id=_text(row.get("wb_report_id")),
        nm_id=nm_id,
        vendor_code=_text(row.get("vendor_code")),
        barcode=_text(row.get("barcode")),
        sales_model=SalesModel(_required_text(row.get("sales_model"))),
        operation_type=_text(row.get("operation_type")),
        quantity=_decimal(row.get("quantity")),
        net_revenue=_decimal(row.get("net_revenue")),
        wb_commission=_decimal(row.get("wb_commission")),
        logistics=_decimal(row.get("logistics")),
        storage=_decimal(row.get("storage")),
        acceptance=_decimal(row.get("acceptance")),
        wb_promotion=_decimal(row.get("deduction")),
        penalties_and_holdbacks=(
            _decimal(row.get("penalty")) - _decimal(row.get("additional_payment"))
        ),
        acquiring=_decimal(row.get("acquiring")),
        vat_input_from_wb=vat_input_from_wb,
        currency=_text(row.get("currency")) or "RUB",
        raw_payload_hash=_required_text(row.get("raw_payload_hash")),
        original_sale_date=sale_dt.date() if sale_dt else None,
        is_partial_source=_bool(row.get("is_partial_source")),
    )


def iter_sku_mapping_records(
    mappings: Iterable[SkuMapping],
    *,
    snapshot_id: str,
) -> Iterable[dict[str, object]]:
    for mapping in mappings:
        yield {
            "snapshot_id": snapshot_id,
            "mapping_key": _sku_mapping_key(mapping),
            "client_id": mapping.client_id,
            "seller_account_id": mapping.seller_account_id,
            "organization_id": mapping.organization_id,
            "nm_id": mapping.nm_id,
            "vendor_code": mapping.vendor_code,
            "barcode": mapping.barcode,
            "onec_item_id": mapping.onec_item_id,
            "onec_article": mapping.onec_article,
            "onec_characteristic": mapping.onec_characteristic,
            "match_method": mapping.match_method,
            "confidence": mapping.confidence,
            "status": mapping.status.value,
            "comment": mapping.comment,
            "updated_by": mapping.updated_by,
            "updated_at": mapping.updated_at,
        }


def sku_mapping_db_row_to_contract(row: Mapping[str, object]) -> SkuMapping:
    return SkuMapping(
        client_id=_required_text(row.get("client_id")),
        seller_account_id=_required_text(row.get("seller_account_id")),
        organization_id=_text(row.get("organization_id")),
        nm_id=_int_or_none(row.get("nm_id")),
        vendor_code=_text(row.get("vendor_code")),
        barcode=_text(row.get("barcode")),
        onec_item_id=_text(row.get("onec_item_id")),
        onec_article=_text(row.get("onec_article")),
        onec_characteristic=_text(row.get("onec_characteristic")),
        match_method=_required_text(row.get("match_method")),
        confidence=_decimal(row.get("confidence")),
        status=MappingStatus(_required_text(row.get("status"))),
        comment=_text(row.get("comment")),
        updated_by=_required_text(row.get("updated_by")),
        updated_at=_required_datetime(row.get("updated_at")),
    )


def iter_cost_snapshot_records(
    cost_snapshots: Iterable[OnecUnfCostSnapshot],
    *,
    snapshot_id: str,
) -> Iterable[dict[str, object]]:
    for cost in cost_snapshots:
        yield {
            "snapshot_id": snapshot_id,
            "cost_key": _cost_snapshot_key(cost),
            "client_id": cost.client_id,
            "organization_id": cost.organization_id,
            "loaded_at": cost.loaded_at,
            "onec_item_id": cost.onec_item_id,
            "article": cost.article,
            "barcode": cost.barcode,
            "name": cost.name,
            "characteristic": cost.characteristic,
            "cost_value": cost.cost_value,
            "extra_costs_value": cost.extra_costs_value,
            "cost_currency": cost.cost_currency,
            "cost_method": cost.cost_method,
            "effective_from": cost.effective_from,
            "effective_to": cost.effective_to,
            "source_document": cost.source_document,
            "raw_payload_hash": cost.raw_payload_hash,
        }


def cost_snapshot_db_row_to_contract(
    row: Mapping[str, object],
) -> OnecUnfCostSnapshot:
    return OnecUnfCostSnapshot(
        client_id=_required_text(row.get("client_id")),
        organization_id=_required_text(row.get("organization_id")),
        loaded_at=_required_datetime(row.get("loaded_at")),
        onec_item_id=_required_text(row.get("onec_item_id")),
        article=_text(row.get("article")),
        barcode=_text(row.get("barcode")),
        name=_text(row.get("name")),
        characteristic=_text(row.get("characteristic")),
        cost_value=_decimal(row.get("cost_value")),
        extra_costs_value=_decimal(row.get("extra_costs_value")),
        cost_currency=_text(row.get("cost_currency")) or "RUB",
        cost_method=_required_text(row.get("cost_method")),
        effective_from=_required_date(row.get("effective_from")),
        effective_to=_parse_date(row.get("effective_to")),
        source_document=_required_text(row.get("source_document")),
        raw_payload_hash=_required_text(row.get("raw_payload_hash")),
    )


def iter_wb_finance_page_records(
    export_dir: Path,
    *,
    client_id: str,
    snapshot_id: str,
) -> Iterable[dict[str, object]]:
    manifest = _read_manifest(export_dir)
    generated_at = _parse_datetime(manifest.get("generated_at")) or datetime.now()
    period_start = _parse_date(manifest.get("period_start")) or date(2026, 4, 1)
    period_end = _parse_date(manifest.get("period_end")) or date(2026, 6, 30)
    for row in manifest.get("results", []):
        if not isinstance(row, dict):
            continue
        yield {
            "snapshot_id": snapshot_id,
            "client_id": client_id,
            "seller_account_id": str(row.get("seller_account_id") or ""),
            "account_name": str(row.get("account_name") or ""),
            "page_index": row.get("page_index"),
            "ok": bool(row.get("ok")),
            "status": str(row.get("status") or ""),
            "row_count": row.get("row_count") or 0,
            "status_code": row.get("status_code"),
            "rrd_id_start": row.get("rrd_id_start"),
            "rrd_id_next": row.get("rrd_id_next"),
            "raw_payload_hash": str(row.get("raw_payload_hash") or ""),
            "output_file": row.get("output_file"),
            "error": str(row.get("error") or ""),
            "manifest_payload": _json(row),
            "generated_at": generated_at,
            "period_start": period_start,
            "period_end": period_end,
            "report_period": str(manifest.get("period") or ""),
            "endpoint": str(manifest.get("endpoint") or ""),
            "source": str(manifest.get("source") or ""),
            "request_delay_seconds": manifest.get("request_delay_seconds"),
        }


def iter_wb_finance_detail_records(
    export_dir: Path,
    *,
    client_id: str,
    account_org_mapping: Iterable[AccountOrgMapping],
    snapshot_id: str,
) -> Iterable[dict[str, object]]:
    manifest = _read_manifest(export_dir)
    account_to_org = {
        item.seller_account_id: item.organization_id for item in account_org_mapping
    }
    loaded_at = _parse_datetime(manifest.get("generated_at")) or datetime.now()
    period_start = _parse_date(manifest.get("period_start")) or date(2026, 4, 1)
    period_end = _parse_date(manifest.get("period_end")) or date(2026, 6, 30)
    report_period = str(manifest.get("period") or "")
    source_endpoint = str(manifest.get("endpoint") or "")
    for page in manifest.get("results", []):
        if not isinstance(page, dict) or page.get("status") != "ok":
            continue
        seller_account_id = str(page.get("seller_account_id") or "")
        account_name = str(page.get("account_name") or "")
        source_file = str(page.get("output_file") or "")
        if not seller_account_id or not source_file:
            continue
        rows = _read_json_list(export_dir / source_file)
        is_partial_source = not _manifest_complete_for_account(
            manifest,
            seller_account_id,
        )
        for row_number, row in enumerate(rows, start=1):
            row_hash = raw_payload_hash(row)
            normalized = normalize_finance_row(
                row,
                client_id=client_id,
                seller_account_id=seller_account_id,
                organization_id=account_to_org.get(seller_account_id, ""),
                period_start=period_start,
                period_end=period_end,
                loaded_at=loaded_at,
                is_partial_source=is_partial_source,
            )
            row_date = normalized.period_start
            week_start = row_date - timedelta(days=row_date.weekday())
            week_end = week_start + timedelta(days=6)
            yield {
                "snapshot_id": snapshot_id,
                "client_id": client_id,
                "seller_account_id": seller_account_id,
                "account_name": account_name,
                "organization_id": normalized.organization_id,
                "source_endpoint": source_endpoint,
                "source_file": source_file,
                "page_index": page.get("page_index"),
                "row_number": row_number,
                "loaded_at": loaded_at,
                "manifest_period_start": period_start,
                "manifest_period_end": period_end,
                "report_period": report_period,
                "row_date": row_date,
                "week_start": week_start,
                "week_end": week_end,
                "is_partial_source": normalized.is_partial_source,
                "raw_payload_hash": row_hash,
                "row_payload": _json(row),
                "wb_document_id": normalized.wb_document_id,
                "report_id": _text(_first(row, "reportId", "report_id")),
                "rrd_id": _int_or_none(_first(row, "rrdId", "rrd_id")),
                "rr_date": _parse_date(_first(row, "rrDate", "rr_dt")),
                "sale_dt": _parse_datetime(_first(row, "saleDt", "sale_dt")),
                "order_dt": _parse_datetime(_first(row, "orderDt", "order_dt")),
                "create_date": _parse_date(_first(row, "createDate", "create_date")),
                "date_from": _parse_date(_first(row, "dateFrom", "date_from")),
                "date_to": _parse_date(_first(row, "dateTo", "date_to")),
                "order_uid": _text(_first(row, "orderUid", "order_uid")),
                "order_id": _text(_first(row, "orderId", "order_id")),
                "shk_id": _text(_first(row, "shkId", "shk_id")),
                "sticker_id": _text(_first(row, "stickerId", "sticker_id")),
                "trbx_id": _text(_first(row, "trbxId", "trbx_id")),
                "nm_id": normalized.nm_id,
                "vendor_code": normalized.vendor_code,
                "title": _text(_first(row, "title")),
                "sku": normalized.barcode,
                "doc_type_name": _text(_first(row, "docTypeName", "doc_type_name")),
                "seller_oper_name": _text(
                    _first(row, "sellerOperName", "supplierOperName")
                ),
                "delivery_method": _text(
                    _first(row, "deliveryMethod", "delivery_method")
                ),
                "office_name": _text(_first(row, "officeName", "office_name")),
                "ppvz_office_name": _text(
                    _first(row, "ppvzOfficeName", "ppvz_office_name")
                ),
                "ppvz_office_id": _text(
                    _first(row, "ppvzOfficeId", "ppvz_office_id")
                ),
                "country": _text(_first(row, "country")),
                "gi_box_type_name": _text(
                    _first(row, "giBoxTypeName", "gi_box_type_name")
                ),
                "dlv_prc": _decimal(_first(row, "dlvPrc", "dlv_prc")),
                "fix_tariff_date_from": _parse_date(
                    _first(row, "fixTariffDateFrom", "fix_tariff_date_from")
                ),
                "fix_tariff_date_to": _parse_date(
                    _first(row, "fixTariffDateTo", "fix_tariff_date_to")
                ),
                "sales_model": normalized.sales_model.value,
                "operation_type": normalized.operation_type,
                "quantity": _decimal(_first(row, "quantity")),
                "signed_quantity": normalized.quantity,
                "retail_amount": _decimal(_first(row, "retailAmount")),
                "net_revenue": normalized.net_revenue,
                "ppvz_sales_commission": _decimal(
                    _first(row, "ppvzSalesCommission")
                ),
                "wb_commission": normalized.wb_commission,
                "delivery_service": _decimal(_first(row, "deliveryService")),
                "delivery_amount": _decimal(_first(row, "deliveryAmount")),
                "return_amount": _decimal(_first(row, "returnAmount")),
                "rebill_logistic_cost": _decimal(
                    _first(row, "rebillLogisticCost", "rebill_logistic_cost")
                ),
                "logistics": normalized.logistics,
                "paid_storage": _decimal(_first(row, "paidStorage")),
                "storage": normalized.storage,
                "paid_acceptance": _decimal(_first(row, "paidAcceptance")),
                "acceptance": normalized.acceptance,
                "penalty": _decimal(_first(row, "penalty")),
                "additional_payment": _decimal(
                    _first(row, "additionalPayment", "additional_payment")
                ),
                "deduction": _decimal(_first(row, "deduction")),
                "penalties_and_holdbacks": normalized.penalties_and_holdbacks,
                "acquiring_fee": _decimal(_first(row, "acquiringFee")),
                "acquiring": normalized.acquiring,
                "currency": normalized.currency,
                "srid": _text(_first(row, "srid")),
            }


def write_copy_payload(
    stream: TextIOBase,
    *,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> int:
    stream.write(
        f"COPY {table} ({', '.join(columns)}) FROM STDIN "
        "WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N');\n"
    )
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    row_count = 0
    for row in rows:
        writer.writerow([_copy_value(row.get(column)) for column in columns])
        row_count += 1
    stream.write("\\.\n")
    return row_count


def build_psql_args(target: PostgresTarget) -> list[str]:
    args = [target.psql_bin, "-v", "ON_ERROR_STOP=1", "-d", target.database]
    if target.host:
        args.extend(["-h", target.host])
    if target.port is not None:
        args.extend(["-p", str(target.port)])
    if target.user:
        args.extend(["-U", target.user])
    return args


def _copy_into_table(
    target: PostgresTarget,
    *,
    table: str,
    stage_table: str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    conflict_sql: str,
) -> int:
    process = subprocess.Popen(
        build_psql_args(target),
        stdin=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    with process.stdin:
        process.stdin.write("BEGIN;\n")
        column_sql = ", ".join(columns)
        process.stdin.write(
            f"CREATE TEMP TABLE {stage_table} AS "
            f"SELECT {column_sql} FROM {table} WITH NO DATA;\n"
        )
        row_count = write_copy_payload(
            process.stdin,
            table=stage_table,
            columns=columns,
            rows=rows,
        )
        process.stdin.write(
            f"""
            INSERT INTO {table} ({column_sql})
            SELECT {column_sql} FROM {stage_table}
            {conflict_sql};
            COMMIT;
            """
        )
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, build_psql_args(target))
    return row_count


def _run_psql(target: PostgresTarget, sql: str) -> None:
    subprocess.run(
        build_psql_args(target),
        input=sql,
        text=True,
        check=True,
    )


def _query_psql_csv(
    target: PostgresTarget,
    sql: str,
) -> list[dict[str, str]]:
    copy_sql = (
        "COPY ("
        + sql.strip().rstrip(";")
        + ") TO STDOUT WITH (FORMAT csv, HEADER true);"
    )
    result = subprocess.run(
        [*build_psql_args(target), "-X", "-q", "-c", copy_sql],
        text=True,
        capture_output=True,
        check=True,
    )
    return list(csv.DictReader(StringIO(result.stdout)))


def _read_manifest(export_dir: Path) -> dict[str, Any]:
    return _read_json_object(export_dir / "manifest.json")


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list: {path}")
    return [item for item in data if isinstance(item, dict)]


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _copy_value(value: object) -> object:
    if value is None:
        return r"\N"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, dict | list):
        return _json(value)
    return value


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"t", "true", "1", "yes"}


def _decimal(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value).replace(" ", "").replace(",", "."))


def _signed_decimal(value: object, *, is_return: bool) -> Decimal:
    result = _decimal(value)
    if is_return and result > 0:
        return -result
    return result


def _row_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _required_text(value: object) -> str:
    result = _text(value)
    if not result:
        raise ValueError("Expected non-empty text value")
    return result


def _required_date(value: object) -> date:
    result = _parse_date(value)
    if result is None:
        raise ValueError("Expected date value")
    return result


def _required_datetime(value: object) -> datetime:
    result = _parse_datetime(value)
    if result is None:
        raise ValueError("Expected datetime value")
    return result


def _parse_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _parse_datetime(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        parsed_date = _parse_date(text)
        if parsed_date is None:
            return None
        return datetime.combine(parsed_date, datetime.min.time())


def _manifest_complete_for_account(
    manifest: Mapping[str, Any],
    account_id: str,
) -> bool:
    results = [
        item
        for item in manifest.get("results", [])
        if isinstance(item, dict) and item.get("seller_account_id") == account_id
    ]
    return bool(results) and results[-1].get("status") == "no_data"


def _sku_mapping_key(mapping: SkuMapping) -> str:
    return raw_payload_hash(
        {
            "client_id": mapping.client_id,
            "seller_account_id": mapping.seller_account_id,
            "nm_id": mapping.nm_id,
            "vendor_code": mapping.vendor_code,
            "barcode": mapping.barcode,
            "match_method": mapping.match_method,
        }
    )


def _cost_snapshot_key(cost: OnecUnfCostSnapshot) -> str:
    return raw_payload_hash(
        {
            "client_id": cost.client_id,
            "organization_id": cost.organization_id,
            "onec_item_id": cost.onec_item_id,
            "characteristic": cost.characteristic,
            "cost_method": cost.cost_method,
            "effective_from": cost.effective_from.isoformat(),
            "effective_to": cost.effective_to.isoformat()
            if cost.effective_to is not None
            else None,
            "source_document": cost.source_document,
        }
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def default_postgres_target(
    *,
    database: str,
    host: str = "",
    port: int | None = None,
    user: str = "",
) -> PostgresTarget:
    env_port = os.environ.get("PGPORT")
    return PostgresTarget(
        database=database,
        host=host or os.environ.get("PGHOST", ""),
        port=port if port is not None else int(env_port) if env_port else 55433,
        user=user or os.environ.get("PGUSER", ""),
    )


def print_summary(summary: WbFinancePostgresSummary) -> None:
    print(f"Snapshot: {summary.snapshot_id}")
    print(f"Manifest pages: {summary.page_count}")
    print(f"Raw detail rows streamed: {summary.raw_row_count}")
    print(f"Seller accounts: {', '.join(summary.seller_accounts)}")


def exit_with_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 1
