from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from wb_unit_economics.contracts import OnecMarketplaceServiceRow
from wb_unit_economics.wb_finance import raw_payload_hash


def load_onec_marketplace_service_rows(
    export_dir: Path,
    *,
    client_id: str,
    reference_dir: Path | None = None,
    sales_register_dir: Path | None = None,
) -> list[OnecMarketplaceServiceRow]:
    receipts = _read_odata_rows(export_dir / "supplier_receipts.raw.json")
    expense_rows = _read_odata_rows(export_dir / "supplier_receipt_expenses.raw.json")
    nomenclature_names = _nomenclature_names(reference_dir) if reference_dir else {}
    marketplace_pairs = (
        _marketplace_pairs_from_sales_register(sales_register_dir)
        if sales_register_dir
        else set()
    )
    receipts_by_key = {
        _text(row.get("Ref_Key")): row
        for row in receipts
        if _text(row.get("Ref_Key"))
        and _is_posted(row)
        and not bool(row.get("DeletionMark"))
    }

    result: list[OnecMarketplaceServiceRow] = []
    for expense in expense_rows:
        receipt = receipts_by_key.get(_text(expense.get("Ref_Key")))
        if receipt is None:
            continue
        pair = (
            _text(receipt.get("Организация_Key")),
            _text(receipt.get("Контрагент_Key")),
        )
        if marketplace_pairs and pair not in marketplace_pairs:
            continue
        document_date = _required_date(receipt.get("Date"))
        week_start, week_end = _service_week_bounds(document_date)
        service_name = _service_name(expense, nomenclature_names)
        amount = _decimal(expense.get("Сумма"))
        vat = _decimal(expense.get("СуммаНДС"))
        total = _decimal(expense.get("Всего")) or amount
        result.append(
            OnecMarketplaceServiceRow(
                client_id=client_id,
                organization_id=pair[0],
                counterparty_id=pair[1],
                document_id=_text(receipt.get("Ref_Key")),
                document_number=_text(receipt.get("Number")),
                input_number=_text(receipt.get("НомерВходящегоДокумента")),
                document_comment=_text(receipt.get("Комментарий")),
                document_date=document_date,
                input_date=_date_or_none(receipt.get("ДатаВходящегоДокумента")),
                week_start=week_start,
                week_end=week_end,
                service_category=classify_marketplace_service(service_name),
                service_name=service_name,
                amount=amount,
                vat=vat,
                total=total,
                amount_includes_vat=bool(receipt.get("СуммаВключаетНДС")),
                vat_included_in_cost=bool(receipt.get("НДСВключатьВСтоимость")),
                include_expenses_in_cost=bool(
                    receipt.get("ВключатьРасходыВСебестоимость")
                ),
                source_row_hash=raw_payload_hash(
                    {
                        "receipt": receipt.get("Ref_Key"),
                        "line": expense.get("LineNumber"),
                        "payload": expense,
                    }
                ),
            )
        )
    return sorted(
        result,
        key=lambda row: (
            row.week_start,
            row.organization_id,
            row.document_date,
            row.document_number,
            row.service_category,
            row.service_name,
        ),
    )


def classify_marketplace_service(service_name: str) -> str:
    text = service_name.lower()
    if "продвиж" in text:
        return "WB Продвижение"
    if "эквайр" in text or "организац" in text and "платеж" in text:
        return "Эквайринг"
    if "комис" in text:
        return "Комиссия WB"
    if "штраф" in text or "пен" in text:
        return "Штрафы/доплаты"
    if any(word in text for word in ("достав", "перевоз", "пвз", "выдач", "возврат")):
        return "Логистика"
    if "хран" in text:
        return "Хранение"
    if "прием" in text or "приём" in text:
        return "Приемка"
    return "Прочие услуги WB"


def _service_name(
    expense: Mapping[str, Any],
    nomenclature_names: Mapping[str, str],
) -> str:
    content = _text(expense.get("Содержание"))
    if content:
        return content
    nomenclature_key = _text(expense.get("Номенклатура_Key"))
    return nomenclature_names.get(nomenclature_key, nomenclature_key)


def _service_week_bounds(document_date: date) -> tuple[date, date]:
    if document_date.weekday() == 6:
        week_start = document_date - timedelta(days=6)
    else:
        previous_week_anchor = document_date - timedelta(days=7)
        week_start = previous_week_anchor - timedelta(
            days=previous_week_anchor.weekday()
        )
    return week_start, week_start + timedelta(days=6)


def _marketplace_pairs_from_sales_register(path: Path | None) -> set[tuple[str, str]]:
    if path is None:
        return set()
    pairs: set[tuple[str, str]] = set()
    for row in _read_odata_rows(path / "sales_register.raw.json"):
        recorder_type = _text(row.get("Recorder_Type"))
        if "ОтчетКомиссионера" not in recorder_type:
            continue
        for record in _record_rows(row):
            organization_id = _text(record.get("Организация_Key"))
            counterparty_id = _text(
                record.get("Покупатель_Key") or record.get("Контрагент_Key")
            )
            if organization_id and counterparty_id:
                pairs.add((organization_id, counterparty_id))
    return pairs


def _record_rows(row: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    recordset = row.get("RecordSet")
    if isinstance(recordset, list):
        for item in recordset:
            if isinstance(item, dict):
                yield item
    else:
        yield row


def _nomenclature_names(reference_dir: Path) -> dict[str, str]:
    rows = _read_odata_rows(reference_dir / "nomenclature.raw.json")
    result: dict[str, str] = {}
    for row in rows:
        key = _text(row.get("Ref_Key"))
        name = _text(row.get("Description") or row.get("НаименованиеПолное"))
        if key and name:
            result[key] = name
    return result


def _read_odata_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("value") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"Expected list or OData value list: {path}")
    return [row for row in rows if isinstance(row, dict)]


def _is_posted(row: Mapping[str, Any]) -> bool:
    posted = row.get("Posted")
    return posted is True or _text(posted).lower() == "true"


def _required_date(value: object) -> date:
    parsed = _date_or_none(value)
    if parsed is None:
        raise ValueError(f"Expected 1C date, got {value!r}")
    return parsed


def _date_or_none(value: object) -> date | None:
    text = _text(value)
    if not text or text.startswith("0001-01-01"):
        return None
    return datetime.fromisoformat(text[:19]).date()


def _decimal(value: object) -> Decimal:
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


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
