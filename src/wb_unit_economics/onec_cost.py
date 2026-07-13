from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from wb_unit_economics.contracts import (
    InputVatPolicy,
    OnecGrossProfitDocumentRow,
    OnecUnfCostSnapshot,
)
from wb_unit_economics.mapping import load_onec_rows
from wb_unit_economics.onec_odata import extract_odata_rows, raw_payload_hash

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PROVISIONAL_COST_METHOD = "provisional_fixed_receipt_sum_needs_review"
RECEIPT_RECORD_TYPES = {"receipt", "приход"}
SALES_REGISTER_COST_METHODS = {
    "Себестоимость": "sales_register_weighted_average_allocated_extra_costs",
    "СебестоимостьБезНДС": (
        "sales_register_weighted_average_without_vat_reconciliation_needs_review"
    ),
}

DocumentMetadata = dict[str, Decimal | str]


def week_bounds(value: date) -> tuple[date, date]:
    week_start = value - timedelta(days=value.weekday())
    return week_start, week_start + timedelta(days=6)


def load_provisional_cost_snapshots(
    sample_dir: Path,
    *,
    client_id: str,
    amount_field: str = "Сумма",
    loaded_at: datetime | None = None,
) -> list[OnecUnfCostSnapshot]:
    stock_payload = _read_json_object(sample_dir / "stock_movements.raw.json")
    stock_rows = [
        item for item in extract_odata_rows(stock_payload) if isinstance(item, dict)
    ]
    return extract_provisional_cost_snapshots(
        client_id=client_id,
        stock_rows=stock_rows,
        barcode_rows=load_onec_rows(sample_dir, "barcodes"),
        nomenclature_rows=load_onec_rows(sample_dir, "nomenclature"),
        amount_field=amount_field,
        loaded_at=loaded_at,
    )


def load_sales_register_cost_snapshots(
    sample_dir: Path,
    *,
    client_id: str,
    reference_dir: Path | None = None,
    amount_field: str = "Себестоимость",
    loaded_at: datetime | None = None,
    marketplace_counterparties_only: bool = False,
    input_vat_policies: Iterable[InputVatPolicy] = (),
    confirmed_input_vat_org_ids: set[str] | None = None,
) -> list[OnecUnfCostSnapshot]:
    sales_rows = load_sales_register_rows(sample_dir)
    reference_dir = reference_dir or sample_dir
    return extract_sales_register_cost_snapshots(
        client_id=client_id,
        sales_rows=sales_rows,
        barcode_rows=_safe_load_onec_rows(reference_dir, "barcodes"),
        nomenclature_rows=_safe_load_onec_rows(reference_dir, "nomenclature"),
        amount_field=amount_field,
        loaded_at=loaded_at,
        marketplace_counterparties_only=marketplace_counterparties_only,
        input_vat_policies=input_vat_policies,
        confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
    )


def load_sales_register_rows(sample_dir: Path) -> list[dict[str, Any]]:
    sales_payload = _read_json_object(sample_dir / "sales_register.raw.json")
    return [
        item for item in extract_odata_rows(sales_payload) if isinstance(item, dict)
    ]


def load_marketplace_settlement_totals(
    sample_dir: Path,
) -> dict[tuple[str, str, str, str], Decimal]:
    rows: list[dict[str, Any]] = []
    for sample_id in ("customer_settlements", "supplier_settlements"):
        path = sample_dir / f"{sample_id}.raw.json"
        if not path.exists():
            continue
        payload = _read_json_object(path)
        rows.extend(
            item for item in extract_odata_rows(payload) if isinstance(item, dict)
        )
    return extract_marketplace_settlement_totals(rows)


def load_marketplace_document_metadata(
    sample_dir: Path,
) -> dict[tuple[str, str], DocumentMetadata]:
    rows_by_type: list[tuple[str, dict[str, Any]]] = []
    for sample_id, document_type in (
        ("commissioner_reports", "ОтчетКомиссионера"),
        ("expense_invoices", "РасходнаяНакладная"),
    ):
        path = sample_dir / f"{sample_id}.raw.json"
        if not path.exists():
            continue
        payload = _read_json_object(path)
        rows_by_type.extend(
            (document_type, item)
            for item in extract_odata_rows(payload)
            if isinstance(item, dict)
        )
    return extract_marketplace_document_metadata(rows_by_type)


def extract_marketplace_document_metadata(
    rows_by_type: Iterable[tuple[str, Mapping[str, Any]]],
) -> dict[tuple[str, str], DocumentMetadata]:
    result: dict[tuple[str, str], DocumentMetadata] = {}
    for document_type, row in rows_by_type:
        document_id = _text(row.get("Ref_Key"))
        if not document_id:
            continue
        external_report_id = _external_report_id_from_document(document_type, row)
        document_total = decimal_from_value(row.get("СуммаДокумента"))
        result[(document_id, document_type)] = {
            "external_report_id": external_report_id,
            "document_number": _text(row.get("Number") or row.get("Номер")),
            "input_number": _text(row.get("НомерВходящегоДокумента")),
            "document_total": document_total,
        }
    return result


def extract_marketplace_settlement_totals(
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str, str, str], Decimal]:
    receipt_totals: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    fallback_totals: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    for record in flatten_stock_record_sets(settlement_rows):
        if not _parse_bool(record.get("Active"), default=True):
            continue
        organization_id = _text(record.get("Организация_Key"))
        counterparty_id = _text(record.get("Контрагент_Key"))
        document_id = _text(record.get("Документ") or record.get("Recorder"))
        document_type = _document_type_label(
            _text(record.get("Документ_Type") or record.get("Recorder_Type"))
        )
        if not organization_id or not counterparty_id or not document_id:
            continue
        key = (organization_id, counterparty_id, document_id, document_type)
        amount = decimal_from_value(record.get("Сумма"))
        fallback_totals[key] += amount
        if _text(record.get("RecordType")).lower() == "receipt":
            receipt_totals[key] += amount
    return {
        key: receipt_totals.get(key, fallback_total)
        for key, fallback_total in fallback_totals.items()
    }


def attach_settlement_totals_to_documents(
    rows: Iterable[OnecGrossProfitDocumentRow],
    settlement_totals: Mapping[tuple[str, str, str, str], Decimal],
) -> list[OnecGrossProfitDocumentRow]:
    result: list[OnecGrossProfitDocumentRow] = []
    for row in rows:
        total = settlement_totals.get(
            (
                row.organization_id,
                row.counterparty_id,
                row.document_id,
                row.document_type,
            )
        )
        if total is None:
            result.append(row)
            continue
        result.append(row.model_copy(update={"settlement_total": total}))
    return result


def attach_document_metadata_to_documents(
    rows: Iterable[OnecGrossProfitDocumentRow],
    document_metadata: Mapping[tuple[str, str], Mapping[str, Decimal | str]],
) -> list[OnecGrossProfitDocumentRow]:
    result: list[OnecGrossProfitDocumentRow] = []
    for row in rows:
        metadata = document_metadata.get((row.document_id, row.document_type))
        if not metadata:
            result.append(row)
            continue
        update: dict[str, Decimal | str] = {}
        for field_name in ("external_report_id", "document_number", "input_number"):
            value = _text(metadata.get(field_name))
            if value:
                update[field_name] = value
        result.append(row.model_copy(update=update) if update else row)
    return result


def flatten_stock_record_sets(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        record_set = _record_set_rows(row.get("RecordSet"))
        for record in record_set:
            flat = {
                "Recorder": row.get("Recorder", ""),
                "Recorder_Type": row.get("Recorder_Type", ""),
            }
            flat.update(record)
            records.append(flat)
    return records


def extract_provisional_cost_snapshots(
    *,
    client_id: str,
    stock_rows: Iterable[Mapping[str, Any]],
    barcode_rows: Iterable[Mapping[str, Any]] = (),
    nomenclature_rows: Iterable[Mapping[str, Any]] = (),
    amount_field: str = "Сумма",
    loaded_at: datetime | None = None,
) -> list[OnecUnfCostSnapshot]:
    loaded_at = loaded_at or datetime.now(tz=MOSCOW_TZ)
    barcode_index = _barcode_index(barcode_rows)
    nomenclature = _nomenclature_index(nomenclature_rows)
    snapshots: list[OnecUnfCostSnapshot] = []
    for record in flatten_stock_record_sets(stock_rows):
        if not _is_fixed_receipt(record):
            continue
        quantity = decimal_from_value(record.get("Количество"))
        if quantity == 0:
            continue
        amount = decimal_from_value(record.get(amount_field))
        cost_value = amount / quantity
        item_id = _text(record.get("Номенклатура_Key"))
        organization_id = _text(record.get("Организация_Key"))
        if not item_id or not organization_id:
            continue
        characteristic = _text(record.get("Характеристика_Key"))
        article, name = nomenclature.get(item_id, ("", ""))
        snapshots.append(
            OnecUnfCostSnapshot(
                client_id=client_id,
                organization_id=organization_id,
                loaded_at=loaded_at,
                onec_item_id=item_id,
                article=article or item_id,
                barcode=_barcode_for(barcode_index, item_id, characteristic),
                name=name,
                characteristic=characteristic,
                cost_value=cost_value,
                extra_costs_value=Decimal("0"),
                cost_currency="RUB",
                cost_method=PROVISIONAL_COST_METHOD,
                effective_from=_parse_date(record.get("Period")) or loaded_at.date(),
                source_document=_text(record.get("Recorder")),
                raw_payload_hash=raw_payload_hash(record),
            )
        )
    return snapshots


def extract_sales_register_cost_snapshots(
    *,
    client_id: str,
    sales_rows: Iterable[Mapping[str, Any]],
    barcode_rows: Iterable[Mapping[str, Any]] = (),
    nomenclature_rows: Iterable[Mapping[str, Any]] = (),
    amount_field: str = "Себестоимость",
    loaded_at: datetime | None = None,
    marketplace_counterparties_only: bool = False,
    input_vat_policies: Iterable[InputVatPolicy] = (),
    confirmed_input_vat_org_ids: set[str] | None = None,
) -> list[OnecUnfCostSnapshot]:
    loaded_at = loaded_at or datetime.now(tz=MOSCOW_TZ)
    cost_method = _sales_register_cost_method(amount_field)
    barcode_index = _barcode_index(barcode_rows)
    nomenclature = _nomenclature_index(nomenclature_rows)
    policies = list(input_vat_policies)
    confirmed_org_ids = confirmed_input_vat_org_ids or set()
    records = flatten_stock_record_sets(sales_rows)
    if marketplace_counterparties_only:
        records = _filter_marketplace_sales_cost_records(records)
    document_groups: dict[
        tuple[str, str, str, date, date, str, str], dict[str, Any]
    ] = {}
    for record in records:
        if not _parse_bool(record.get("Active"), default=True):
            continue
        period = _parse_date(record.get("Period")) or loaded_at.date()
        week_start, week_end = week_bounds(period)
        quantity = decimal_from_value(record.get("Количество"))
        amount = decimal_from_value(record.get(amount_field))
        including_raw = record.get("Себестоимость")
        excluding_raw = record.get("СебестоимостьБезНДС")
        including_amount = (
            decimal_from_value(including_raw) if including_raw is not None else None
        )
        excluding_amount = (
            decimal_from_value(excluding_raw) if excluding_raw is not None else None
        )
        if (
            quantity == 0
            and amount == 0
            and (including_amount is None or including_amount == 0)
            and (excluding_amount is None or excluding_amount == 0)
        ):
            continue
        item_id = _text(record.get("Номенклатура_Key"))
        organization_id = _text(record.get("Организация_Key"))
        if not item_id or not organization_id:
            continue
        document_id = _text(record.get("Документ") or record.get("Recorder"))
        if not document_id:
            continue
        document_kind = _sales_cost_document_kind(record)
        key = (
            organization_id,
            item_id,
            "",
            week_start,
            week_end,
            document_id,
            document_kind,
        )
        group = document_groups.setdefault(
            key,
            {
                "quantity": Decimal("0"),
                "amount": Decimal("0"),
                "cost_including_vat": Decimal("0"),
                "cost_excluding_vat": Decimal("0"),
                "cost_including_vat_complete": True,
                "cost_excluding_vat_complete": True,
                "row_hashes": [],
            },
        )
        group["quantity"] += abs(quantity)
        group["amount"] += abs(amount)
        if including_raw is None:
            group["cost_including_vat_complete"] = False
        else:
            group["cost_including_vat"] += abs(including_amount or Decimal("0"))
        if excluding_raw is None:
            group["cost_excluding_vat_complete"] = False
        else:
            group["cost_excluding_vat"] += abs(excluding_amount or Decimal("0"))
        group["row_hashes"].append(raw_payload_hash(record))

    groups: dict[tuple[str, str, str, date, date, str], dict[str, Any]] = {}
    for (
        organization_id,
        item_id,
        characteristic,
        week_start,
        week_end,
        document_id,
        document_kind,
    ), document_group in document_groups.items():
        quantity = document_group["quantity"]
        if quantity == 0:
            continue
        key = (
            organization_id,
            item_id,
            characteristic,
            week_start,
            week_end,
            document_kind,
        )
        group = groups.setdefault(
            key,
            {
                "quantity": Decimal("0"),
                "amount": Decimal("0"),
                "cost_including_vat": Decimal("0"),
                "cost_excluding_vat": Decimal("0"),
                "cost_including_vat_complete": True,
                "cost_excluding_vat_complete": True,
                "document_ids": [],
                "row_hashes": [],
            },
        )
        group["quantity"] += quantity
        group["amount"] += document_group["amount"]
        group["cost_including_vat"] += document_group["cost_including_vat"]
        group["cost_excluding_vat"] += document_group["cost_excluding_vat"]
        group["cost_including_vat_complete"] = bool(
            group["cost_including_vat_complete"]
            and document_group["cost_including_vat_complete"]
        )
        group["cost_excluding_vat_complete"] = bool(
            group["cost_excluding_vat_complete"]
            and document_group["cost_excluding_vat_complete"]
        )
        group["document_ids"].append(document_id)
        group["row_hashes"].extend(document_group["row_hashes"])

    snapshots: list[OnecUnfCostSnapshot] = []
    for (
        organization_id,
        item_id,
        characteristic,
        week_start,
        week_end,
        document_kind,
    ) in sorted(groups):
        group = groups[
            (
                organization_id,
                item_id,
                characteristic,
                week_start,
                week_end,
                document_kind,
            )
        ]
        quantity = group["quantity"]
        if quantity == 0:
            continue
        input_vat_value: Decimal | None = None
        input_vat_source = ""
        policy = _input_vat_policy_for(
            policies,
            organization_id=organization_id,
            calculation_date=week_end,
        )
        actual_confirmed = organization_id in confirmed_org_ids
        difference_available = bool(
            group["cost_including_vat_complete"]
            and group["cost_excluding_vat_complete"]
        )
        difference = group["cost_including_vat"] - group["cost_excluding_vat"]
        if difference_available and difference >= Decimal("-0.01"):
            if actual_confirmed:
                input_vat_value = max(difference, Decimal("0")) / quantity
                input_vat_source = "onec_purchase_book_confirmed_cost_difference"
            elif policy is not None and policy.mode == "management_assumption":
                input_vat_value = max(difference, Decimal("0")) / quantity
                input_vat_source = "management_assumption:sales_cost_difference"
        article, name = nomenclature.get(item_id, ("", ""))
        snapshots.append(
            OnecUnfCostSnapshot(
                client_id=client_id,
                organization_id=organization_id,
                loaded_at=loaded_at,
                onec_item_id=item_id,
                article=article or item_id,
                barcode=_barcode_for(barcode_index, item_id, characteristic),
                name=name,
                characteristic=characteristic,
                cost_value=group["amount"] / quantity,
                extra_costs_value=Decimal("0"),
                input_vat_value=input_vat_value,
                input_vat_source=input_vat_source,
                cost_currency="RUB",
                cost_method=cost_method,
                effective_from=week_start,
                effective_to=week_end,
                source_document_kind=document_kind,
                source_document=(
                    "AccumulationRegister_Продажи "
                    f"{week_start.isoformat()}..{week_end.isoformat()}"
                    + (f" · {document_kind}" if document_kind else "")
                ),
                raw_payload_hash=raw_payload_hash(
                    {
                        "amount_field": amount_field,
                        "key": [
                            organization_id,
                            item_id,
                            characteristic,
                            week_start.isoformat(),
                            week_end.isoformat(),
                            document_kind,
                        ],
                        "document_ids": group["document_ids"],
                        "row_hashes": group["row_hashes"],
                    }
                ),
            )
        )
    return snapshots


def _input_vat_policy_for(
    policies: Iterable[InputVatPolicy],
    *,
    organization_id: str,
    calculation_date: date,
) -> InputVatPolicy | None:
    candidates = [
        item
        for item in policies
        if item.organization_id == organization_id
        and item.is_effective_for(calculation_date)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.valid_from)


def extract_gross_profit_document_rows(
    *,
    client_id: str,
    sales_rows: Iterable[Mapping[str, Any]],
    marketplace_counterparties_only: bool = True,
) -> list[OnecGrossProfitDocumentRow]:
    records = flatten_stock_record_sets(sales_rows)
    if marketplace_counterparties_only:
        records = _filter_marketplace_counterparties(records)
    groups: dict[tuple[str, str, str, str, date, date, date], dict[str, Any]] = {}
    for record in records:
        if not _parse_bool(record.get("Active"), default=True):
            continue
        document_date = _parse_date(record.get("Period"))
        if document_date is None:
            continue
        week_start, week_end = week_bounds(document_date)
        organization_id = _text(record.get("Организация_Key"))
        counterparty_id = _text(record.get("Контрагент_Key"))
        document_id = _text(record.get("Документ") or record.get("Recorder"))
        document_type = _document_type_label(
            _text(record.get("Документ_Type") or record.get("Recorder_Type"))
        )
        if not organization_id or not counterparty_id or not document_id:
            continue
        key = (
            organization_id,
            counterparty_id,
            document_id,
            document_type,
            document_date,
            week_start,
            week_end,
        )
        group = groups.setdefault(
            key,
            {
                "sales_quantity": Decimal("0"),
                "return_quantity": Decimal("0"),
                "quantity": Decimal("0"),
                "revenue": Decimal("0"),
                "vat": Decimal("0"),
                "cogs": Decimal("0"),
                "cogs_without_vat": Decimal("0"),
                "settlement_total": None,
                "rows": 0,
            },
        )
        quantity = decimal_from_value(record.get("Количество"))
        if quantity > 0:
            group["sales_quantity"] += quantity
        elif quantity < 0:
            group["return_quantity"] += abs(quantity)
        group["quantity"] += quantity
        group["revenue"] += decimal_from_value(record.get("Сумма"))
        group["vat"] += decimal_from_value(record.get("СуммаНДС"))
        group["cogs"] += decimal_from_value(record.get("Себестоимость"))
        group["cogs_without_vat"] += decimal_from_value(
            record.get("СебестоимостьБезНДС")
        )
        settlement_total = _settlement_total_from_record(record)
        if settlement_total is not None and group["settlement_total"] is None:
            group["settlement_total"] = settlement_total
        group["rows"] += 1

    result: list[OnecGrossProfitDocumentRow] = []
    for key, group in sorted(groups.items()):
        (
            organization_id,
            counterparty_id,
            document_id,
            document_type,
            document_date,
            week_start,
            week_end,
        ) = key
        if group["quantity"] == 0 and group["revenue"] == 0 and group["cogs"] == 0:
            continue
        result.append(
            OnecGrossProfitDocumentRow(
                client_id=client_id,
                organization_id=organization_id,
                counterparty_id=counterparty_id,
                document_id=document_id,
                document_type=document_type,
                document_date=document_date,
                week_start=week_start,
                week_end=week_end,
                sales_quantity=group["sales_quantity"],
                return_quantity=group["return_quantity"],
                quantity=group["quantity"],
                revenue=group["revenue"],
                vat=group["vat"],
                cogs=group["cogs"],
                cogs_without_vat=group["cogs_without_vat"],
                gross_profit=group["revenue"] - group["cogs"],
                settlement_total=group["settlement_total"],
                source_row_count=int(group["rows"]),
            )
        )
    return result


def _settlement_total_from_record(record: Mapping[str, Any]) -> Decimal | None:
    for field_name in (
        "ИтогоВзаиморасчетов",
        "Итого взаиморасчетов",
        "ИтогоВзаиморасчетовСумма",
        "СуммаВзаиморасчетов",
        "ВзаиморасчетыСумма",
    ):
        value = record.get(field_name)
        if value not in (None, ""):
            return decimal_from_value(value)
    return None


def _external_report_id_from_document(
    document_type: str,
    row: Mapping[str, Any],
) -> str:
    if "ОтчетКомиссионера" in document_type:
        report_id = _digits_only(row.get("НомерВходящегоДокумента"))
        if report_id:
            return report_id
    return _report_id_from_text(
        " ".join(
            _text(row.get(field_name))
            for field_name in (
                "Комментарий",
                "ОснованиеПечати",
                "Содержание",
                "НомерВходящегоДокумента",
            )
        )
    )


def _report_id_from_text(value: str) -> str:
    text = value.replace("\xa0", " ")
    patterns = (
        r"(?:№|N|No)\s*([0-9][0-9\s]{5,})",
        r"отчет[^\d]{0,40}([0-9][0-9\s]{5,})",
        r"выкуп[^\d]{0,40}([0-9][0-9\s]{5,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        report_id = _digits_only(match.group(1))
        if report_id:
            return report_id
    return ""


def _digits_only(value: object) -> str:
    return re.sub(r"\D+", "", _text(value))


def decimal_from_value(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def _record_set_rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
    return []


def _is_fixed_receipt(record: Mapping[str, Any]) -> bool:
    if not _parse_bool(record.get("Active"), default=True):
        return False
    record_type = _text(record.get("RecordType")).lower()
    return record_type in RECEIPT_RECORD_TYPES and _parse_bool(
        record.get("ФиксированнаяСтоимость"), default=False
    )


def _sales_register_cost_method(amount_field: str) -> str:
    try:
        return SALES_REGISTER_COST_METHODS[amount_field]
    except KeyError as exc:
        raise ValueError(
            "Unsupported sales cost amount field: "
            f"{amount_field}. Expected one of: "
            f"{', '.join(sorted(SALES_REGISTER_COST_METHODS))}"
        ) from exc


def _filter_marketplace_counterparties(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    marketplace_keys = {
        (_text(record.get("Организация_Key")), _text(record.get("Контрагент_Key")))
        for record in records
        if "отчеткомиссионера"
        in _text(record.get("Документ_Type") or record.get("Recorder_Type")).lower()
    }
    if not marketplace_keys:
        return records
    return [
        record
        for record in records
        if (
            _text(record.get("Организация_Key")),
            _text(record.get("Контрагент_Key")),
        )
        in marketplace_keys
    ]


def _filter_marketplace_sales_cost_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if _sales_cost_document_kind(record)
    ]


def _sales_cost_document_kind(record: Mapping[str, Any]) -> str:
    normalized = _record_document_type(record).replace(" ", "").casefold()
    if "отчеткомиссионера" in normalized:
        return "commissioner_report"
    if "расходнаянакладная" in normalized:
        return "buyout_notice"
    return ""


def _record_document_type(record: Mapping[str, Any]) -> str:
    return _text(record.get("Документ_Type") or record.get("Recorder_Type"))


def _document_type_label(value: str) -> str:
    return value.removeprefix("StandardODATA.Document_").replace("_", " ")


def _barcode_index(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    by_item_characteristic: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_item: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        item_id = _text(row.get("Номенклатура_Key"))
        barcode = _text(row.get("Штрихкод"))
        if not item_id or not barcode:
            continue
        characteristic = _text(row.get("Характеристика_Key"))
        by_item_characteristic[(item_id, characteristic)].add(barcode)
        by_item[(item_id, "")].add(barcode)
    result: dict[tuple[str, str], list[str]] = {}
    for key, values in by_item_characteristic.items():
        result[key] = sorted(values)
    for key, values in by_item.items():
        result.setdefault(key, sorted(values))
    return result


def _barcode_for(
    index: Mapping[tuple[str, str], list[str]],
    item_id: str,
    characteristic: str,
) -> str:
    barcodes = index.get((item_id, characteristic)) or index.get((item_id, "")) or []
    return barcodes[0] if len(barcodes) == 1 else ""


def _nomenclature_index(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        item_id = _text(row.get("Ref_Key"))
        if not item_id:
            continue
        result[item_id] = (
            _text(row.get("Артикул")),
            _text(row.get("Description") or row.get("НаименованиеПолное")),
        )
    return result


def _parse_bool(value: object, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "ложь"}


def _parse_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _safe_load_onec_rows(path: Path, name: str) -> list[dict[str, Any]]:
    try:
        return load_onec_rows(path, name)
    except FileNotFoundError:
        return []
