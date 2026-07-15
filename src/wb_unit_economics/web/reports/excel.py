from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

MONTH_CLOSE_SHEETS = (
    "Сводка закрытия",
    "Покрытие регламента",
    "ОСВ",
    "ЕНС и налоги",
    "НДС",
    "Банк",
    "Ручные операции",
    "Подтверждения",
    "Риски и дозапросы",
    "Источники и статус",
)
TAX_LOAD_SHEETS = (
    "Обзор",
    "Налоги",
    "График платежей",
    "НДС",
    "ЕНС",
    "Источники и статус",
    "Дозапросы",
)


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_mapping(sheet: Any, value: Mapping[str, Any]) -> None:
    sheet.append(["Показатель", "Значение"])
    for key, item in value.items():
        sheet.append([key, _cell(item)])


def _write_rows(sheet: Any, rows: Iterable[Mapping[str, Any]]) -> None:
    normalized = list(rows)
    if not normalized:
        sheet.append(["Нет подтвержденных данных"])
        return
    headers: list[str] = []
    for row in normalized:
        for key in row:
            if key not in headers:
                headers.append(key)
    sheet.append(headers)
    for row in normalized:
        sheet.append([_cell(row.get(key)) for key in headers])


def _style(workbook: Workbook) -> None:
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        if sheet.max_row:
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E78")
        for column in sheet.columns:
            width = min(max(len(str(cell.value or "")) for cell in column) + 2, 60)
            sheet.column_dimensions[column[0].column_letter].width = max(width, 12)


def write_scenario_excel(
    payload: Mapping[str, Any], payload_sha256: str, output_path: Path
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    report_kind = payload.get("reportKind")
    if report_kind == "month_close_control":
        for title in MONTH_CLOSE_SHEETS:
            workbook.create_sheet(title)
        summary = {
            **dict(payload.get("meta") or {}),
            "businessRecommendation": payload.get("businessRecommendation"),
            "contractVersion": payload.get("contractVersion"),
            "payloadSha256": payload_sha256,
        }
        _write_mapping(workbook["Сводка закрытия"], summary)
        _write_rows(workbook["Покрытие регламента"], payload.get("controls") or [])
        osv_sheet = workbook["ОСВ"]
        _write_mapping(osv_sheet, payload.get("osvSummary") or {})
        osv_sheet.append([])
        _write_rows(osv_sheet, payload.get("osvRows") or [])
        _write_mapping(
            workbook["ЕНС и налоги"],
            {**(payload.get("ensSummary") or {}), **(payload.get("taxSummary") or {})},
        )
        _write_mapping(workbook["НДС"], payload.get("vatSummary") or {})
        _write_mapping(workbook["Банк"], payload.get("bankSummary") or {})
        _write_mapping(
            workbook["Ручные операции"],
            payload.get("manualOperationsSummary") or {},
        )
        _write_rows(workbook["Подтверждения"], payload.get("confirmations") or [])
        _write_rows(workbook["Риски и дозапросы"], payload.get("issues") or [])
        _write_rows(
            workbook["Источники и статус"], payload.get("sourceCoverage") or []
        )
    elif report_kind == "tax_load":
        for title in TAX_LOAD_SHEETS:
            workbook.create_sheet(title)
        overview = {
            **dict(payload.get("meta") or {}),
            **dict(payload.get("taxLoadSummary") or {}),
            "businessStatus": payload.get("businessStatus"),
            "contractVersion": payload.get("contractVersion"),
            "payloadSha256": payload_sha256,
        }
        _write_mapping(workbook["Обзор"], overview)
        _write_rows(workbook["Налоги"], payload.get("taxRows") or [])
        _write_rows(
            workbook["График платежей"], payload.get("paymentSchedule") or []
        )
        _write_mapping(workbook["НДС"], payload.get("vatSummary") or {})
        _write_mapping(workbook["ЕНС"], payload.get("ensSummary") or {})
        _write_rows(
            workbook["Источники и статус"], payload.get("sourceCoverage") or []
        )
        _write_rows(workbook["Дозапросы"], payload.get("issues") or [])
    else:
        raise ValueError("unsupported scenario report kind")
    _style(workbook)
    workbook.save(output_path)
    return output_path
