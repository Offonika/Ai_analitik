from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
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

TAX_LOAD_FIELD_LABELS = {
    "reportId": "ID отчёта",
    "tenantId": "ID контура",
    "clientId": "ID клиента",
    "reportKind": "Вид отчёта",
    "organizationId": "ID организации 1С",
    "periodStart": "Начало отчётного периода",
    "periodEnd": "Окончание отчётного периода",
    "methodologyVersion": "Версия методики",
    "generatedAt": "Дата формирования",
    "publicationStatus": "Статус публикации",
    "sourceRefreshRunId": "ID загрузки источников",
    "sourceSnapshotSetId": "ID набора снимков",
    "evidenceSha256": "SHA-256 подтверждающих данных",
    "metricKind": "Показатель",
    "numeratorKind": "Состав числителя",
    "numeratorValue": "Уплаченные собственные налоги",
    "denominatorKind": "Состав знаменателя ФНС",
    "denominatorValue": "Официальный доходный знаменатель",
    "fnsTaxBurdenRatio": "Налоговая нагрузка по методике ФНС, %",
    "calculationPeriodKind": "Период расчёта",
    "methodologyStatus": "Статус методики",
    "comparisonStatus": "Статус сравнения",
    "benchmarkYear": "Год ориентира",
    "benchmarkValue": "Значение ориентира, %",
    "usnIncomeDenominatorKind": "Состав знаменателя УСН",
    "usnIncomeValue": "Доход УСН без НДС",
    "usnIncomeTaxBurden": "Управленческая нагрузка УСН, %",
    "usnIncomeStatus": "Статус показателя УСН",
    "businessStatus": "Статус отчёта",
    "contractVersion": "Версия контракта",
    "payloadSha256": "SHA-256 отчёта",
    "taxCode": "Код налога",
    "taxName": "Налог",
    "periodKind": "Период",
    "taxBase": "Налоговая база",
    "accrued": "Начислено",
    "paid": "Уплачено",
    "balance": "Сальдо",
    "dueDate": "Срок уплаты",
    "valueStatus": "Статус значения",
    "evidenceStatus": "Статус подтверждения",
    "sourceKind": "Источник",
    "issueCode": "Код замечания",
    "paymentKind": "Вид платежа",
    "includedInFnsTaxBurden": "Включён в нагрузку ФНС",
    "exclusionReason": "Причина исключения",
    "amount": "Сумма",
    "confirmationStatus": "Статус подтверждения",
    "status": "Статус",
    "outputVat": "Начисленный НДС",
    "inputVat": "Входящий НДС",
    "payableVat": "НДС к уплате",
    "asOfDate": "Дата состояния",
    "snapshotId": "ID снимка",
    "code": "Код замечания",
    "severity": "Важность",
    "section": "Раздел",
    "message": "Что найдено",
    "nextAction": "Что сделать",
}

TAX_LOAD_VALUE_LABELS = {
    "tax_load": "Налоговая нагрузка",
    "accountant_review_required": "Нужна проверка бухгалтера",
    "preliminary": "Предварительный",
    "confirmed": "Подтверждено",
    "loaded": "Загружено",
    "ready": "Готово",
    "complete": "Завершено",
    "missing": "Нет данных",
    "partial": "Загружено частично",
    "partial_source": "Источник неполный",
    "empty_expected": "Ожидаемо нет данных",
    "source_gap": "Недостаточно данных",
    "informational": "Справочно",
    "warning": "Нужно проверить",
    "error": "Ошибка",
    "critical": "Критично",
    "draft": "Черновик",
    "published": "Опубликован",
    "management_reference": "Управленческий ориентир",
    "pending_methodology_confirmation": "Ожидает подтверждения методики",
    "preliminary_ytd": "Предварительно, с начала года",
    "ytd": "С начала года",
    "year_to_date": "С начала года",
    "month": "За месяц",
    "monthly": "За месяц",
    "report_month": "За месяц",
    "fns_tax_risk": "Налоговая нагрузка по методике ФНС",
    "paid_taxes_excluding_agents_and_insurance_contributions": (
        "Фактически уплаченные собственные налоги без агентских платежей "
        "и страховых взносов"
    ),
    "financial_result_income_excluding_participation_income": (
        "Доход по отчёту о финансовых результатах без доходов от участия"
    ),
    "usn_income_receipts_excluding_vat": "Доход УСН из поступлений без НДС",
    "own_tax": "Собственный налог",
    "agent_ndfl": "НДФЛ налогового агента",
    "agent_profit_tax_dividends": "Налог налогового агента с дивидендов",
    "insurance_contribution": "Страховые взносы",
    "unclassified": "Не классифицировано",
    "agent_payment": "Агентский платёж",
}

TAX_LOAD_SOURCE_LABELS = {
    "onec_tax": "Налоговый учёт 1С",
    "onec_osv": "ОСВ 1С",
    "onec_bank": "Банк в 1С",
    "onec_accounting_bank_in": "Банковские поступления 1С",
    "onec_accounting_bank_out": "Банковские списания 1С",
    "onec_accounting_chart": "План счетов 1С",
    "onec_accounting_ens": "Единый налоговый счёт 1С",
    "onec_accounting_ens_sanctions": "Санкции по ЕНС в 1С",
    "onec_accounting_manual_operations": "Ручные операции 1С",
    "onec_accounting_month_close_docs": "Документы закрытия месяца 1С",
    "onec_accounting_purchase_corrections": "Корректировки приобретений 1С",
    "onec_accounting_register_corrections": "Корректировки регистров 1С",
    "onec_accounting_sales_corrections": "Корректировки продаж 1С",
    "onec_accounting_taxes": "Расчёты по налогам 1С",
    "onec_accounting_taxes_on_ens": "Платежи по налогам на ЕНС в 1С",
    "onec_kudir": "Книга учёта доходов и расходов 1С",
    "onec_official_financial_results": "Отчёт о финансовых результатах 1С",
    "onec_organizations": "Организации 1С",
    "onec_tax_accrual_lines": "Строки начислений налогов 1С",
    "onec_tax_accruals": "Начисления налогов 1С",
    "onec_tax_kinds": "Виды налогов 1С",
    "onec_tax_registrations": "Налоговые регистрации 1С",
    "onec_tax_register": "Налоговый регистр 1С",
    "onec_tax_special_regime_notifications": (
        "Уведомления по специальным налоговым режимам 1С"
    ),
    "onec_vat_books": "Книги НДС 1С",
    "onec_vat_purchase_book": "Книга покупок 1С",
    "onec_vat_sales_book": "Книга продаж 1С",
    "accountant_confirmation": "Подтверждение бухгалтера",
}

TAX_LOAD_DATE_FIELDS = {
    "periodStart",
    "periodEnd",
    "generatedAt",
    "dueDate",
    "asOfDate",
}
TAX_LOAD_ENUM_FIELDS = {
    "reportKind",
    "publicationStatus",
    "businessStatus",
    "metricKind",
    "numeratorKind",
    "denominatorKind",
    "calculationPeriodKind",
    "methodologyStatus",
    "comparisonStatus",
    "usnIncomeDenominatorKind",
    "usnIncomeStatus",
    "periodKind",
    "valueStatus",
    "evidenceStatus",
    "paymentKind",
    "exclusionReason",
    "confirmationStatus",
    "status",
    "severity",
}


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


def _tax_load_field_label(key: str) -> str:
    try:
        return TAX_LOAD_FIELD_LABELS[key]
    except KeyError as exc:
        raise ValueError(f"tax-load Excel label is missing for field {key!r}") from exc


def _tax_load_date(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return value
    if "T" in value or " " in value:
        return parsed.strftime("%d.%m.%Y %H:%M")
    return parsed.strftime("%d.%m.%Y")


def _tax_load_cell(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if key in TAX_LOAD_DATE_FIELDS:
        return _tax_load_date(value)
    if key == "sourceKind":
        normalized = str(value).strip().casefold()
        if normalized in TAX_LOAD_SOURCE_LABELS:
            return TAX_LOAD_SOURCE_LABELS[normalized]
        return "Источник 1С" if normalized.startswith("onec_") else "Источник отчёта"
    if key in TAX_LOAD_ENUM_FIELDS:
        normalized = str(value).strip().casefold()
        return TAX_LOAD_VALUE_LABELS.get(normalized, "Не определено")
    return _cell(value)


def _write_tax_load_mapping(sheet: Any, value: Mapping[str, Any]) -> None:
    sheet.append(["Показатель", "Значение"])
    for key, item in value.items():
        sheet.append([_tax_load_field_label(key), _tax_load_cell(key, item)])


def _write_tax_load_rows(
    sheet: Any, rows: Iterable[Mapping[str, Any]]
) -> None:
    normalized = list(rows)
    if not normalized:
        sheet.append(["Нет подтверждённых данных"])
        return
    headers: list[str] = []
    for row in normalized:
        for key in row:
            if key not in headers:
                headers.append(key)
    sheet.append([_tax_load_field_label(key) for key in headers])
    for row in normalized:
        sheet.append([_tax_load_cell(key, row.get(key)) for key in headers])


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
        _write_tax_load_mapping(workbook["Обзор"], overview)
        _write_tax_load_rows(workbook["Налоги"], payload.get("taxRows") or [])
        _write_tax_load_rows(
            workbook["График платежей"], payload.get("paymentSchedule") or []
        )
        _write_tax_load_mapping(workbook["НДС"], payload.get("vatSummary") or {})
        _write_tax_load_mapping(workbook["ЕНС"], payload.get("ensSummary") or {})
        _write_tax_load_rows(
            workbook["Источники и статус"], payload.get("sourceCoverage") or []
        )
        _write_tax_load_rows(workbook["Дозапросы"], payload.get("issues") or [])
    else:
        raise ValueError("unsupported scenario report kind")
    _style(workbook)
    workbook.save(output_path)
    return output_path
