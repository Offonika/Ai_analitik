from __future__ import annotations

import csv
import io
import json
import zipfile
from calendar import monthrange
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import UUID

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from wb_unit_economics.contracts import (
    AdvertisingScope,
    DataQualityStatus,
    MappingStatus,
    OnecGrossProfitDocumentRow,
    OnecMarketplaceServiceRow,
    OnecUnfCostSnapshot,
    SkuMapping,
    UnitEconomicsReport,
    WbSalesReportSummaryRow,
)
from wb_unit_economics.liquidity import aggregate_liquidity_rows
from wb_unit_economics.onec_odata import extract_odata_rows
from wb_unit_economics.onec_opiu import OnecOpiuSummary

REQUIRED_SHEETS = [
    "README",
    "Дашборд",
    "Сводка",
    "Сводка по организациям",
    "Сводка по кабинетам WB",
    "Юнит экономика",
    "Ликвидность МД",
    "Товары",
    "Динамика",
    "Сводный отчет WB",
    "WB поля отчета",
    "Сверка по отчетам WB",
    "Сверка с 1С",
    "Сверка документов 1С",
    "Сверка с 1С ОПиУ",
    "Валовая прибыль 1С",
    "Сверка услуг WB",
    "Расшифровка услуг 1С",
    "Распределение расходов",
    "Товары по отчетам 1С",
    "Расходы WB",
    "Возвраты",
    "Упущенные продажи",
    "Себестоимость 1С",
    "Маппинг",
    "Ошибки данных",
    "Методика",
]

DATA_QUALITY_LABELS = {
    DataQualityStatus.RELIABLE: "ОК",
    DataQualityStatus.MISSING_COST: "Нет себестоимости 1С",
    DataQualityStatus.MISSING_MAPPING: "Нет сопоставления WB-1С",
    DataQualityStatus.AMBIGUOUS_MAPPING: "Неоднозначное сопоставление",
    DataQualityStatus.PARTIAL_SOURCE: "Неполный источник",
    DataQualityStatus.EXPENSE_WITHOUT_SKU: "Расход без SKU",
    DataQualityStatus.ACCOUNT_ORG_MISMATCH: (
        "Кабинет WB не совпадает с организацией 1С"
    ),
    DataQualityStatus.EXCLUDED: "Исключено",
    DataQualityStatus.NEEDS_REVIEW: "Себестоимость 1С требует сверки",
    DataQualityStatus.WB_DOCUMENT_MISSING: "Документ WB не найден",
    DataQualityStatus.WB_DOCUMENT_DOWNLOADED: "Документ WB загружен",
    DataQualityStatus.REPORT_TYPE_FALLBACK: "Тип отчета WB определен эвристикой",
    DataQualityStatus.PAYOUT_SOURCE_MISSING: "Нужен источник выплаты 1С",
    DataQualityStatus.OPIU_PILOT_DEFAULTS: "ОПиУ: пилотные GUID-настройки",
}

MAPPING_STATUS_LABELS = {
    MappingStatus.MATCHED: "Сопоставлено",
    MappingStatus.MISSING: "Не найдено",
    MappingStatus.AMBIGUOUS: "Неоднозначно",
    MappingStatus.EXCLUDED: "Исключено",
}

REPORT_STATUS_LABELS = {
    "final": "Финальный",
    "partial_period": "Неполный период",
}

CLIENT_VISIBLE_SHEETS = {
    "Дашборд",
    "Юнит экономика",
    "Ликвидность МД",
    "Динамика",
    "Расходы WB",
    "Возвраты",
    "Упущенные продажи",
    "Сверка документов 1С",
    "Сверка с 1С ОПиУ",
    "Ошибки данных",
    "Методика",
}

MONTH_LABELS = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

ADVERTISING_SCOPE_LABELS = {
    AdvertisingScope.EXCLUDED_FROM_MVP: "Реклама исключена из MVP",
}

ONEC_WAREHOUSE_DICTIONARY_FILES = (
    "Catalog_СтруктурныеЕдиницы.raw.json",
    "Catalog_Склады.raw.json",
    "structural_units.raw.json",
    "warehouses.raw.json",
)


def _account_label(
    seller_account_id: str,
    account_labels: Mapping[str, str] | None,
) -> str:
    if not account_labels:
        return seller_account_id
    return account_labels.get(seller_account_id, seller_account_id)


def _organization_label(
    organization_id: str,
    organization_labels: Mapping[str, str] | None,
) -> str:
    if not organization_labels:
        return organization_id
    return organization_labels.get(organization_id, organization_id)


def _sales_model_label(value: object) -> str:
    raw = getattr(value, "value", str(value)).lower()
    if raw == "fbo":
        return "Склад WB"
    if raw == "fbs":
        return "Склад продавца"
    return str(value)


def _format_date_ru(value: object) -> str:
    return value.strftime("%d.%m.%Y")


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _month_end(value: date) -> date:
    return date(value.year, value.month, monthrange(value.year, value.month)[1])


def _display_week_start(week_start: date, report_period_start: date) -> date:
    return max(week_start, report_period_start)


def _row_month_start(row: object, report_period_start: date) -> date:
    return _month_start(_display_week_start(row.week_start, report_period_start))


def _month_label(value: date, report: UnitEconomicsReport) -> str:
    label = f"{MONTH_LABELS[value.month]} {value.year}"
    if value < _month_start(report.report_period_start) or _month_end(value) > (
        report.report_period_end
    ):
        return f"{label} (неполный месяц)"
    return label


def _report_month_keys(report: UnitEconomicsReport) -> list[date]:
    result = []
    current = _month_start(report.report_period_start)
    last = _month_start(report.report_period_end)
    while current <= last:
        result.append(current)
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)
    return result


def _short_month_label(value: date) -> str:
    return MONTH_LABELS[value.month]


def _analysis_period_note(report: UnitEconomicsReport) -> str:
    month_starts = _report_month_keys(report)
    month_labels = [MONTH_LABELS[item.month].lower() for item in month_starts]
    note = f"Период анализа: {', '.join(month_labels)}"
    if _month_end(report.report_period_end) > report.report_period_end:
        note += f"; {MONTH_LABELS[report.report_period_end.month].lower()} неполный"
        note += f", по {_format_date_ru(report.report_period_end)}"
    return note


def _source_coverage_label(report: UnitEconomicsReport) -> str:
    if report.source_coverage_start is None or report.source_coverage_end is None:
        return "не зафиксировано в расчетной витрине"
    return (
        f"{report.source_coverage_start.isoformat()} - "
        f"{report.source_coverage_end.isoformat()}"
    )


def _report_readiness_status(report: UnitEconomicsReport) -> str:
    if not report.rows:
        return "failed"
    if (
        report.source_coverage_start is not None
        and report.source_coverage_start > report.report_period_start
    ) or (
        report.source_coverage_end is not None
        and report.source_coverage_end < report.report_period_end
    ):
        return "source_coverage_gap"
    if any(
        row.data_quality_status is DataQualityStatus.PARTIAL_SOURCE
        for row in report.rows
    ):
        return "partial_source"
    if _month_end(report.report_period_end) > report.report_period_end:
        return "partial_period"
    if any(
        row.data_quality_status is not DataQualityStatus.RELIABLE
        for row in report.rows
    ):
        return "needs_review"
    return "ready"


def _report_period_status_label(report: UnitEconomicsReport) -> str:
    readiness_status = _report_readiness_status(report)
    if readiness_status == "partial_period":
        return REPORT_STATUS_LABELS[readiness_status]
    return REPORT_STATUS_LABELS.get(report.status.value, report.status.value)


def _cost_name_lookup(
    cost_snapshots: Iterable[OnecUnfCostSnapshot],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for cost in cost_snapshots:
        if cost.name:
            result[(cost.organization_id, cost.onec_item_id)] = cost.name
    return result


def _cost_article_lookup(
    cost_snapshots: Iterable[OnecUnfCostSnapshot],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for cost in cost_snapshots:
        if cost.article:
            result[(cost.organization_id, cost.onec_item_id)] = cost.article
    return result


def _mapping_article_lookup(
    sku_mappings: Iterable[SkuMapping],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for mapping in sku_mappings:
        if mapping.onec_article:
            result[(mapping.organization_id, mapping.onec_item_id)] = (
                mapping.onec_article
            )
    return result


def _cost_method_lookup(
    cost_snapshots: Iterable[OnecUnfCostSnapshot],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for cost in cost_snapshots:
        result.setdefault((cost.organization_id, cost.onec_item_id), cost.cost_method)
    return result


def _product_label(row: object, cost_names: Mapping[tuple[str, str], str]) -> str:
    onec_item_id = getattr(row, "onec_item_id", None)
    organization_id = row.organization_id
    if onec_item_id:
        name = cost_names.get((organization_id, onec_item_id))
        if name:
            return name
    vendor_code = getattr(row, "vendor_code", "")
    if vendor_code:
        return vendor_code
    nm_id = getattr(row, "nm_id", None)
    if _is_real_nm_id(nm_id):
        return f"Товар WB {nm_id}"
    return "Товар не определен"


def _is_real_nm_id(nm_id: object) -> bool:
    return isinstance(nm_id, int) and nm_id > 0


def _is_client_product_row(row: object) -> bool:
    return (
        getattr(row, "onec_item_id", None) is not None
        or _is_real_nm_id(getattr(row, "nm_id", None))
        or bool((getattr(row, "vendor_code", "") or "").strip())
        or bool((getattr(row, "barcode", "") or "").strip())
    )


def _onec_article_label(
    row: object,
    cost_articles: Mapping[tuple[str, str], str],
    mapping_articles: Mapping[tuple[str, str], str],
) -> str:
    onec_item_id = getattr(row, "onec_item_id", None)
    if onec_item_id is None:
        return ""
    key = (row.organization_id, onec_item_id)
    return cost_articles.get(key) or mapping_articles.get(key) or ""


def _status_reason(
    row: object,
    cost_methods: Mapping[tuple[str, str], str],
) -> str:
    status = row.data_quality_status
    if status is DataQualityStatus.RELIABLE:
        return "Данные достаточны для расчета"
    if status is DataQualityStatus.NEEDS_REVIEW:
        if getattr(row, "tax_method", "") == "Налоговый профиль не найден":
            return "Для организации 1С не найден налоговый профиль на период строки"
        onec_item_id = getattr(row, "onec_item_id", None)
        method = (
            cost_methods.get((row.organization_id, onec_item_id), "")
            if onec_item_id
            else ""
        )
        if "provisional" in method:
            return (
                "Себестоимость взята предварительно из приходов 1С; нужна сверка "
                "с регистром продаж или утвержденной себестоимостью"
            )
        if "without_vat" in method:
            return "Себестоимость без НДС требует бухгалтерской сверки"
        if "sales_register" in method:
            return (
                "Себестоимость взята из ближайшей доступной недели 1С; "
                "нужна сверка после закрытия месяца"
            )
        return "Нужно подтвердить источник и метод себестоимости 1С"
    if status is DataQualityStatus.MISSING_MAPPING:
        return "Товар WB не сопоставлен с номенклатурой 1С"
    if status is DataQualityStatus.MISSING_COST:
        return "Для сопоставленного товара нет действующей себестоимости 1С"
    if status is DataQualityStatus.AMBIGUOUS_MAPPING:
        return "Для товара найдено несколько возможных соответствий 1С"
    if status is DataQualityStatus.EXPENSE_WITHOUT_SKU:
        return "Строка WB без реального товара; нужна проверка распределения"
    if status is DataQualityStatus.PARTIAL_SOURCE:
        return "Источник WB загружен не полностью"
    if status is DataQualityStatus.ACCOUNT_ORG_MISMATCH:
        return "Кабинет WB не совпадает с ожидаемой организацией 1С"
    if status is DataQualityStatus.EXCLUDED:
        return "Строка исключена методикой"
    if status is DataQualityStatus.WB_DOCUMENT_MISSING:
        return "Нужно загрузить первичный документ WB за период сверки"
    if status is DataQualityStatus.WB_DOCUMENT_DOWNLOADED:
        return "Документ WB доступен в локальном data-пакете; сверить hash и период"
    if status is DataQualityStatus.REPORT_TYPE_FALLBACK:
        return "Тип отчета определен по fallback-правилу; подтвердить по reportType"
    if status is DataQualityStatus.PAYOUT_SOURCE_MISSING:
        return "Не сравнивать выплату до согласования read-only источника выплаты 1С"
    if status is DataQualityStatus.OPIU_PILOT_DEFAULTS:
        return "Подтвердить GUID-настройки ОПиУ или вынести их в config"
    return "Нужна ручная проверка"


def _client_unit_rows(
    rows: Iterable[object],
    cost_names: Mapping[tuple[str, str], str],
) -> list[object]:
    return [
        row
        for row in rows
        if _is_client_product_row(row)
        and _product_label(row, cost_names) != "Товар не определен"
    ]


def build_excel_report(
    report: UnitEconomicsReport,
    output_path: str | Path,
    *,
    include_ai_summary: bool = False,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    source_notes: Iterable[str] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
    onec_gross_profit_rows: Iterable[OnecGrossProfitDocumentRow] = (),
    wb_sales_report_summary_rows: Iterable[WbSalesReportSummaryRow] = (),
    onec_marketplace_service_rows: Iterable[OnecMarketplaceServiceRow] = (),
    onec_opiu_summary: OnecOpiuSummary | None = None,
    stock_history_dir: Path | None = None,
    onec_stock_dir: Path | None = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    notes = list(source_notes)
    with xlsxwriter.Workbook(output_path) as workbook:
        formats = _formats(workbook)
        cost_rows = list(cost_snapshots)
        mapping_rows = list(sku_mappings)
        gross_profit_rows = list(onec_gross_profit_rows)
        sales_report_summary_rows = list(wb_sales_report_summary_rows)
        marketplace_service_rows = list(onec_marketplace_service_rows)
        labels = account_labels or {}
        org_labels = organization_labels or {}
        onec_document_dates = _resolved_onec_document_dates_by_package(
            report,
            gross_profit_rows,
            sales_report_summary_rows,
        )
        _write_readme(workbook, formats, report, source_notes=notes)
        _write_dashboard(
            workbook,
            formats,
            report,
            cost_snapshots=cost_rows,
            sku_mappings=mapping_rows,
            source_notes=notes,
        )
        _write_summary(workbook, formats, report)
        _write_group_summary(
            workbook,
            formats,
            report,
            "Сводка по организациям",
            "organization_id",
            organization_labels=org_labels,
        )
        _write_group_summary(
            workbook,
            formats,
            report,
            "Сводка по кабинетам WB",
            "seller_account_id",
            account_labels=labels,
        )
        _write_unit_economics(
            workbook,
            formats,
            report,
            cost_snapshots=cost_rows,
            sku_mappings=mapping_rows,
            wb_sales_report_summary_rows=sales_report_summary_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_liquidity_md(
            workbook,
            formats,
            report,
            cost_snapshots=cost_rows,
            sku_mappings=mapping_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_products(
            workbook,
            formats,
            report,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_dynamics(workbook, formats, report)
        _write_wb_sales_report_summary(
            workbook,
            formats,
            sales_report_summary_rows,
            account_labels=labels,
        )
        _write_wb_report_fields(
            workbook,
            formats,
            report.wb_sales_report_summary_rows or sales_report_summary_rows,
            account_labels=labels,
        )
        _write_report_reconciliation(
            workbook,
            formats,
            report,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_onec_report_reconciliation(
            workbook,
            formats,
            report,
            summary_rows=sales_report_summary_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_onec_document_reconciliation(
            workbook,
            formats,
            report,
            gross_profit_rows,
            summary_rows=sales_report_summary_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_onec_opiu_reconciliation(
            workbook,
            formats,
            report,
            onec_gross_profit_rows=gross_profit_rows,
            wb_sales_report_summary_rows=sales_report_summary_rows,
            onec_opiu_summary=onec_opiu_summary,
            onec_document_dates=onec_document_dates,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_onec_gross_profit_documents(
            workbook,
            formats,
            gross_profit_rows,
            organization_labels=org_labels,
        )
        _write_marketplace_service_reconciliation(
            workbook,
            formats,
            report,
            marketplace_service_rows,
            sales_report_summary_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_onec_service_breakdown(
            workbook,
            formats,
            marketplace_service_rows,
            organization_labels=org_labels,
        )
        _write_expense_allocation(
            workbook,
            formats,
            report,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_onec_report_products(
            workbook,
            formats,
            report,
            onec_document_dates=onec_document_dates,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_expenses(workbook, formats, report, account_labels=labels)
        _write_returns(
            workbook,
            formats,
            report,
            cost_snapshots=cost_rows,
            sku_mappings=mapping_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_lost_sales(
            workbook,
            formats,
            report,
            cost_snapshots=cost_rows,
            sku_mappings=mapping_rows,
            stock_history_dir=stock_history_dir,
            onec_stock_dir=onec_stock_dir,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_costs(workbook, formats, cost_rows, organization_labels=org_labels)
        _write_mappings(
            workbook,
            formats,
            mapping_rows,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_errors(
            workbook,
            formats,
            report,
            account_labels=labels,
            organization_labels=org_labels,
        )
        _write_methodology(workbook, formats, report)
        if include_ai_summary:
            _write_placeholder(
                workbook,
                formats,
                "ИИ-резюме",
                "ИИ-резюме формируется после расчетной витрины.",
            )
        _apply_client_sheet_visibility(workbook)
    return output_path


def _formats(workbook: xlsxwriter.Workbook) -> dict[str, object]:
    return {
        "header": workbook.add_format(
            {"bold": True, "bg_color": "#D9EAF7", "border": 1}
        ),
        "money": workbook.add_format({"num_format": "#,##0.00"}),
        "percent": workbook.add_format({"num_format": "0.00%"}),
        "date": workbook.add_format({"num_format": "yyyy-mm-dd"}),
        "bold": workbook.add_format({"bold": True}),
        "title": workbook.add_format({"bold": True, "font_size": 16}),
        "section": workbook.add_format({"bold": True, "font_size": 12}),
        "note": workbook.add_format({"text_wrap": True}),
        "bad": workbook.add_format({"bg_color": "#F4CCCC"}),
        "warn": workbook.add_format({"bg_color": "#FFF2CC"}),
        "good": workbook.add_format({"bg_color": "#D9EAD3"}),
    }


def _apply_client_sheet_visibility(workbook: xlsxwriter.Workbook) -> None:
    for worksheet in workbook.worksheets():
        if worksheet.name not in CLIENT_VISIBLE_SHEETS:
            worksheet.hide()
    dashboard = workbook.get_worksheet_by_name("Дашборд")
    if dashboard is not None:
        dashboard.activate()
        dashboard.set_first_sheet()


def _write_readme(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    source_notes: Iterable[str] = (),
) -> None:
    sheet = workbook.add_worksheet("README")
    rows = [
        ("Клиент", report.client_id),
        ("Период", f"{report.report_period_start} - {report.report_period_end}"),
        (
            "Период отчета",
            f"{report.report_period_start} - {report.report_period_end}",
        ),
        ("Покрытие источников", _source_coverage_label(report)),
        ("Период анализа", _analysis_period_note(report)),
        ("Статус готовности", _report_readiness_status(report)),
        ("Статус периода", _report_period_status_label(report)),
        ("Дата расчета", report.generated_at.isoformat()),
        ("Версия методики", report.methodology_version),
        ("Организации 1С", "2 организации"),
        ("Кабинеты WB", "2 кабинета"),
        ("Реклама", "excluded_from_mvp"),
        ("Налоги", "По налоговому профилю организации 1С"),
        ("Источник WB", "WB Finance / Financial Reports"),
    ]
    sheet.write_row(0, 0, ["Параметр", "Значение"], formats["header"])
    for row_idx, row in enumerate(rows, start=1):
        sheet.write_row(row_idx, 0, row)
    note_start = len(rows) + 2
    sheet.write_row(note_start, 0, ["Ограничения", "Описание"], formats["header"])
    notes = list(source_notes) or [
        "Себестоимость 1С берется из регистра Продажи; допрасходы уже включены.",
        (
            "Хранение и WB Продвижение распределяются по товарным долям "
            "детализации и приводятся к недельному финансовому отчету WB."
        ),
        (
            "Налоги рассчитываются по налоговому профилю организации 1С; "
            "фактические налоговые регистры 1С используются как сверка, "
            "а не распределяются по товарам."
        ),
        "Отдельные рекламные API исключены из первого MVP.",
    ]
    for row_idx, note in enumerate(notes, start=note_start + 1):
        sheet.write(row_idx, 0, "примечание")
        sheet.write(row_idx, 1, note)
    sheet.set_column(0, 0, 24)
    sheet.set_column(1, 1, 84)


def _write_dashboard(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    source_notes: Iterable[str] = (),
) -> None:
    sheet = workbook.add_worksheet("Дашборд")
    cost_names = _cost_name_lookup(cost_snapshots)
    rows = _client_unit_rows(report.rows, cost_names)
    totals = _totals(rows)
    status_counts = Counter(
        _data_quality_label(row.data_quality_status) for row in rows
    )
    revenue = totals["net_revenue"]
    margin_after_taxes = _safe_margin(totals["profit_after_taxes"], revenue)
    return_rate = _safe_margin(totals["return_quantity"], totals["sales_quantity"])
    reliable_label = DATA_QUALITY_LABELS[DataQualityStatus.RELIABLE]
    reliable_count = status_counts.get(reliable_label, 0)
    data_ok_share = Decimal(reliable_count) / Decimal(len(rows)) if rows else None
    product_rows = _product_summary_rows(rows, cost_names, cost_snapshots, sku_mappings)
    profitable_sku_count = sum(1 for row in product_rows if row[8] >= 0)
    loss_sku_count = sum(1 for row in product_rows if row[8] < 0)
    sheet.write(0, 0, "Дашборд юнит-экономики", formats["title"])
    sheet.write(
        0,
        3,
        (
            "Период: "
            f"{_format_date_ru(report.report_period_start)} - "
            f"{_format_date_ru(report.report_period_end)}"
        ),
        formats["bold"],
    )
    sheet.write(
        0,
        6,
        f"Статус: {_report_period_status_label(report)}",
        formats["bold"],
    )
    sheet.write(
        0,
        9,
        f"Дата расчета: {_format_date_ru(report.generated_at)}",
        formats["bold"],
    )
    sheet.write(0, 12, _analysis_period_note(report), formats["bold"])
    sheet.write(
        1,
        9,
        f"Статус готовности: {_report_readiness_status(report)}",
        formats["bold"],
    )
    sheet.write(
        1,
        12,
        f"Покрытие источников: {_source_coverage_label(report)}",
        formats["bold"],
    )
    kpi_rows = [
        ("Выручка до СПП", totals["revenue_before_spp"]),
        ("СПП", totals["spp_discount"]),
        ("% СПП", _safe_margin(totals["spp_discount"], totals["revenue_before_spp"])),
        ("Выручка после СПП", totals["revenue_after_spp"]),
        ("Продажи, шт", totals["sales_quantity"]),
        ("Возвраты, шт", totals["return_quantity"]),
        ("Чистое кол-во, шт", totals["quantity"]),
        ("Доля возвратов", return_rate),
        ("Маржинальный доход WB после налогов", totals["profit_after_taxes"]),
        ("Маржа WB после налогов", margin_after_taxes),
        ("Прибыльных SKU", profitable_sku_count),
        ("Убыточных SKU", loss_sku_count),
        ("Доля строк ОК", data_ok_share),
        ("Хранение WB", totals["storage"]),
        ("Продвижение WB", totals["wb_promotion"]),
        (
            "Строк с проверкой себестоимости",
            status_counts.get(
                DATA_QUALITY_LABELS[DataQualityStatus.NEEDS_REVIEW],
                0,
            ),
        ),
    ]
    sheet.write(1, 0, "Ключевые показатели", formats["section"])
    _write_kpi_table(sheet, formats, start_row=2, start_col=0, rows=kpi_rows)

    status_rows = [
        (status, count)
        for status, count in sorted(status_counts.items(), key=lambda item: item[0])
    ]
    sheet.write(1, 3, "Статусы данных", formats["section"])
    _write_table_block(
        sheet,
        formats,
        start_row=2,
        start_col=3,
        headers=["Статус данных", "Строк"],
        rows=status_rows,
    )
    warning_rows = _source_warning_rows(source_notes)
    if warning_rows:
        sheet.write(1, 6, "Проблемы источников", formats["section"])
        _write_table_block(
            sheet,
            formats,
            start_row=2,
            start_col=6,
            headers=["Что проверить"],
            rows=warning_rows,
        )

    monthly_rows = _month_summary_rows(rows, report)
    month_change_rows = _month_change_rows(monthly_rows)
    monthly_start = max(
        11,
        4 + len(kpi_rows),
        4 + len(status_rows),
        4 + len(warning_rows),
    )
    sheet.write(monthly_start - 1, 0, "Динамика месяц к месяцу", formats["section"])
    _write_table_block(
        sheet,
        formats,
        start_row=monthly_start,
        start_col=0,
        headers=[
            "Месяц",
            "Статус",
            "Продажи, шт",
            "Возвраты, шт",
            "% возвратов",
            "Выручка до СПП",
            "СПП",
            "% СПП",
            "Выручка после СПП",
            "Логистика",
            "Расходы WB",
            "Маржинальный доход WB после налогов",
            "Маржа WB после налогов",
        ],
        rows=monthly_rows,
        money_columns={5, 6, 8, 9, 10, 11},
        percent_columns={4, 7, 12},
    )
    month_change_start = monthly_start + len(monthly_rows) + 3
    if month_change_rows:
        sheet.write(month_change_start - 1, 0, "Изменение м/м", formats["section"])
        _write_table_block(
            sheet,
            formats,
            start_row=month_change_start,
            start_col=0,
            headers=[
                "Период",
                "Выручка после СПП, Δ",
                "Выручка после СПП, %",
                "Маржинальный доход, Δ",
                "Маржинальный доход, %",
                "Расходы WB, Δ",
                "Расходы WB, %",
            ],
            rows=month_change_rows,
            money_columns={1, 3, 5},
            percent_columns={2, 4, 6},
        )

    weekly_rows = _weekly_summary_rows(
        rows,
        report_period_start=report.report_period_start,
    )
    dashboard_weekly_rows = [(row[0], row[1], row[3], row[4]) for row in weekly_rows]
    weekly_start = (
        month_change_start + (len(month_change_rows) if month_change_rows else 0) + 4
    )
    sheet.write(weekly_start - 1, 0, "Динамика по неделям", formats["section"])
    _write_table_block(
        sheet,
        formats,
        start_row=weekly_start,
        start_col=0,
        headers=[
            "Неделя",
            "Выручка после СПП",
            "Маржинальный доход WB после налогов",
            "Маржа WB после налогов",
        ],
        rows=dashboard_weekly_rows,
        money_columns={1, 2},
        percent_columns={3},
    )
    if dashboard_weekly_rows:
        chart = workbook.add_chart({"type": "line"})
        chart.add_series(
            {
                "name": "Маржинальный доход WB после налогов",
                "categories": [
                    "Дашборд",
                    weekly_start + 1,
                    0,
                    weekly_start + len(dashboard_weekly_rows),
                    0,
                ],
                "values": [
                    "Дашборд",
                    weekly_start + 1,
                    2,
                    weekly_start + len(dashboard_weekly_rows),
                    2,
                ],
            }
        )
        chart.set_title({"name": "Динамика маржинального дохода WB"})
        chart.set_legend({"none": True})
        sheet.insert_chart(
            weekly_start - 1, 5, chart, {"x_scale": 1.2, "y_scale": 1.05}
        )

    top_profit = sorted(
        (row for row in product_rows if _is_top_profit_product_row(row)),
        key=lambda row: (
            row[8],
            row[9] if row[9] is not None else Decimal("0"),
        ),
        reverse=True,
    )[:10]
    top_loss = sorted(
        (row for row in product_rows if row[8] < 0),
        key=lambda row: (
            row[8],
            row[9] if row[9] is not None else Decimal("0"),
            -(row[5] if row[5] is not None else Decimal("0")),
        ),
    )[:20]
    products_start = weekly_start + max(len(dashboard_weekly_rows), 12) + 4
    sheet.write(
        products_start - 1,
        0,
        "Топ прибыльных товаров (себестоимость > 0)",
        formats["section"],
    )
    _write_table_block(
        sheet,
        formats,
        start_row=products_start,
        start_col=0,
        headers=[
            "Товар",
            "Артикул WB",
            "Артикул 1С",
            "Чистое кол-во",
            "Выручка после СПП",
            "Маржинальный доход WB после налогов",
            "Маржинальный доход/шт",
            "Маржа WB после налогов",
            "Статус данных",
        ],
        rows=[
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[6],
                row[8],
                row[9],
                row[10],
                row[13],
            )
            for row in top_profit
        ],
        money_columns={4, 5, 6},
        percent_columns={7},
    )
    top_loss_start_col = 10
    sheet.write(
        products_start - 1,
        top_loss_start_col,
        "Топ убыточных товаров",
        formats["section"],
    )
    _write_table_block(
        sheet,
        formats,
        start_row=products_start,
        start_col=top_loss_start_col,
        headers=[
            "Товар",
            "Артикул WB",
            "Артикул 1С",
            "Чистое кол-во",
            "Возвраты, шт",
            "% возвратов",
            "Выручка после СПП",
            "Маржинальный доход WB после налогов",
            "Маржинальный доход/шт",
            "Класс убытка",
            "Главная причина",
            "Статус данных",
        ],
        rows=[
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[8],
                row[9],
                row[12],
                row[11],
                row[13],
            )
            for row in top_loss
        ],
        money_columns={6, 7, 8},
        percent_columns={5},
    )
    sheet.set_column(0, 0, 28)
    sheet.set_column(1, 7, 16)
    sheet.set_column(6, 6, 54)
    sheet.set_column(8, 8, 28)
    sheet.set_column(9, 19, 16)
    sheet.set_column(17, 18, 26)
    _apply_dashboard_conditional_formatting(
        sheet,
        formats,
        weekly_start=weekly_start,
        weekly_count=len(dashboard_weekly_rows),
        product_start=products_start,
        product_count=len(top_profit),
        loss_count=len(top_loss),
    )


def _source_warning_rows(source_notes: Iterable[str]) -> list[tuple[str]]:
    warnings = [
        note
        for note in source_notes
        if "загружен не полностью" in note or "ошибка" in note.lower()
    ]
    return [(note,) for note in warnings[:5]]


def _apply_dashboard_conditional_formatting(
    sheet: xlsxwriter.worksheet.Worksheet,
    formats: dict[str, object],
    *,
    weekly_start: int,
    weekly_count: int,
    product_start: int,
    product_count: int,
    loss_count: int,
) -> None:
    # KPI values: profit after taxes and margin after taxes.
    sheet.conditional_format(
        3,
        1,
        3,
        1,
        {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
    )
    sheet.conditional_format(
        4,
        1,
        4,
        1,
        {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
    )
    sheet.conditional_format(
        4,
        1,
        4,
        1,
        {
            "type": "cell",
            "criteria": "between",
            "minimum": 0,
            "maximum": 0.1,
            "format": formats["warn"],
        },
    )
    sheet.conditional_format(
        4,
        1,
        4,
        1,
        {"type": "cell", "criteria": ">=", "value": 0.2, "format": formats["good"]},
    )

    # Status block.
    sheet.conditional_format(
        3,
        3,
        8,
        4,
        {
            "type": "text",
            "criteria": "containing",
            "value": "Нет",
            "format": formats["bad"],
        },
    )
    sheet.conditional_format(
        3,
        3,
        8,
        4,
        {
            "type": "text",
            "criteria": "containing",
            "value": "требует",
            "format": formats["warn"],
        },
    )

    if weekly_count:
        first = weekly_start + 1
        last = weekly_start + weekly_count
        sheet.conditional_format(
            first,
            2,
            last,
            2,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )
        sheet.conditional_format(
            first,
            3,
            last,
            3,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )
        sheet.conditional_format(
            first,
            3,
            last,
            3,
            {
                "type": "cell",
                "criteria": "between",
                "minimum": 0,
                "maximum": 0.1,
                "format": formats["warn"],
            },
        )

    if product_count:
        first = product_start + 1
        last = product_start + product_count
        sheet.conditional_format(
            first,
            5,
            last,
            6,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )
        sheet.conditional_format(
            first,
            6,
            last,
            6,
            {"type": "cell", "criteria": ">=", "value": 0.2, "format": formats["good"]},
        )

    if loss_count:
        first = product_start + 1
        last = product_start + loss_count
        sheet.conditional_format(
            first,
            15,
            last,
            16,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )


def _write_pivot_summaries(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сводные")
    cost_names = _cost_name_lookup(cost_snapshots)
    rows = _client_unit_rows(report.rows, cost_names)
    sheet.write(0, 0, "Готовые сводные таблицы", formats["title"])

    status_rows = _status_summary_rows(rows)
    _write_table_block(
        sheet,
        formats,
        start_row=2,
        start_col=0,
        headers=[
            "Статус данных",
            "Строк",
            "Выручка",
            "Себестоимость 1С",
            "Прибыль после налогов",
            "Хранение",
            "Продвижение",
        ],
        rows=status_rows,
        money_columns={2, 3, 4, 5, 6},
    )

    weekly_rows = _weekly_summary_rows(rows)
    weekly_start = 2 + len(status_rows) + 4
    _write_table_block(
        sheet,
        formats,
        start_row=weekly_start,
        start_col=0,
        headers=[
            "Неделя",
            "Выручка",
            "Себестоимость 1С",
            "Прибыль после налогов",
            "Маржа после налогов",
            "Хранение",
            "Продвижение",
        ],
        rows=weekly_rows,
        money_columns={1, 2, 3, 5, 6},
        percent_columns={4},
    )

    account_rows = _account_org_summary_rows(
        rows,
        account_labels=account_labels,
        organization_labels=organization_labels,
    )
    account_start = weekly_start + len(weekly_rows) + 4
    _write_table_block(
        sheet,
        formats,
        start_row=account_start,
        start_col=0,
        headers=[
            "Организация 1С",
            "Кабинет WB",
            "Выручка",
            "Себестоимость 1С",
            "Прибыль после налогов",
            "Маржа после налогов",
        ],
        rows=account_rows,
        money_columns={2, 3, 4},
        percent_columns={5},
    )

    product_rows = _product_summary_rows(rows, cost_names, cost_snapshots, sku_mappings)
    product_start = account_start + len(account_rows) + 4
    _write_table_block(
        sheet,
        formats,
        start_row=product_start,
        start_col=0,
        headers=[
            "Товар",
            "Артикул WB",
            "Артикул 1С",
            "Чистое кол-во",
            "Возвраты, шт",
            "% возвратов",
            "Выручка",
            "Прибыль после налогов",
            "Прибыль/шт",
            "Маржа после налогов",
            "Статус данных",
        ],
        rows=[
            (
                item[0],
                item[1],
                item[2],
                item[3],
                item[4],
                item[5],
                item[6],
                item[8],
                item[9],
                item[10],
                item[13],
            )
            for item in product_rows
        ],
        money_columns={6, 7, 8},
        percent_columns={5, 9},
    )
    sheet.set_column(0, 0, 34)
    sheet.set_column(1, 7, 18)


def _write_summary(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
) -> None:
    sheet = workbook.add_worksheet("Сводка")
    totals = _totals(report.rows)
    rows = [
        ("Выручка до СПП", totals["revenue_before_spp"]),
        ("СПП", totals["spp_discount"]),
        ("% СПП", _safe_margin(totals["spp_discount"], totals["revenue_before_spp"])),
        ("Выручка после СПП", totals["revenue_after_spp"]),
        ("Комиссия WB", totals["wb_commission"]),
        ("Логистика", totals["logistics"]),
        ("Хранение", totals["storage"]),
        ("Приемка", totals["acceptance"]),
        ("WB Продвижение", totals["wb_promotion"]),
        ("Удержания/штрафы/доплаты", totals["penalties_and_holdbacks"]),
        ("Эквайринг", totals["acquiring"]),
        ("Себестоимость 1С, включая распределенные допрасходы", totals["cogs"]),
        ("Маржинальный доход WB до налогов", totals["gross_profit"]),
        ("НДС", totals["vat_5"]),
        ("Налог с выручки", totals["usn_1"]),
        ("Маржинальный доход WB после налогов", totals["profit_after_taxes"]),
    ]
    sheet.write_row(0, 0, ["Показатель", "Значение"], formats["header"])
    for row_idx, (label, value) in enumerate(rows, start=1):
        sheet.write(row_idx, 0, label)
        if label == "% СПП" and value is not None:
            sheet.write_number(row_idx, 1, float(value), formats["percent"])
        elif value is None:
            sheet.write(row_idx, 1, "")
        else:
            sheet.write_number(row_idx, 1, float(value), formats["money"])
    _add_table(sheet, ["Показатель", "Значение"], len(rows))
    sheet.set_column(0, 0, 34)
    sheet.set_column(1, 1, 16)


def _write_group_summary(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    sheet_name: str,
    field: str,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet(sheet_name)
    grouped: dict[str, list[object]] = defaultdict(list)
    for row in report.rows:
        grouped[str(getattr(row, field))].append(row)
    sheet.write_row(
        0,
        0,
        [
            "Группа",
            "Выручка после СПП",
            "Себестоимость",
            "Маржинальный доход WB до налогов",
            "НДС",
            "Налог с выручки",
            "Маржинальный доход WB после налогов",
        ],
        formats["header"],
    )
    for row_idx, (group, rows) in enumerate(sorted(grouped.items()), start=1):
        totals = _totals(rows)
        label = (
            _account_label(group, account_labels)
            if field == "seller_account_id"
            else _organization_label(group, organization_labels)
            if field == "organization_id"
            else group
        )
        sheet.write(
            row_idx,
            0,
            label,
        )
        sheet.write_number(row_idx, 1, float(totals["net_revenue"]), formats["money"])
        sheet.write_number(row_idx, 2, float(totals["cogs"]), formats["money"])
        sheet.write_number(row_idx, 3, float(totals["gross_profit"]), formats["money"])
        sheet.write_number(row_idx, 4, float(totals["vat_5"]), formats["money"])
        sheet.write_number(row_idx, 5, float(totals["usn_1"]), formats["money"])
        sheet.write_number(
            row_idx, 6, float(totals["profit_after_taxes"]), formats["money"]
        )
    _add_table(
        sheet,
        [
            "Группа",
            "Выручка после СПП",
            "Себестоимость",
            "Маржинальный доход WB до налогов",
            "НДС",
            "Налог с выручки",
            "Маржинальный доход WB после налогов",
        ],
        len(grouped),
    )
    sheet.set_column(0, 0, 24)
    sheet.set_column(1, 6, 16)


def _write_unit_economics(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    wb_sales_report_summary_rows: list[WbSalesReportSummaryRow] | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Юнит экономика")
    headers = [
        "Неделя",
        "Документ-отчет",
        "Номер отчета WB",
        "Дата отчета WB",
        "Организация 1С",
        "Кабинет WB",
        "Товар",
        "nmId WB",
        "Артикул WB",
        "Артикул 1С",
        "Баркод",
        "Схема продажи",
        "Продажи, шт",
        "Возвраты, шт",
        "Чистое кол-во",
        "% возвратов",
        "Выручка до СПП",
        "СПП",
        "% СПП",
        "Выручка после СПП",
        "НДС",
        "Выручка без НДС",
        "Себестоимость 1С",
        "Комиссия WB",
        "Логистика WB",
        "Хранение WB",
        "Приемка WB",
        "Продвижение WB",
        "Штрафы/доплаты WB",
        "Эквайринг WB",
        "Налог с выручки",
        "Маржинальный доход WB до налогов",
        "Маржа WB до налогов",
        "Маржинальный доход WB после налогов",
        "Маржа WB после налогов",
        "Маржинальный доход WB после налогов на шт",
        "Статус данных",
        "Причина статуса",
        "Статус СПП",
        "Налоговый режим/ставка",
        "Источник налогового профиля",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    source_rows = report.rows
    cost_names = _cost_name_lookup(cost_snapshots)
    cost_articles = _cost_article_lookup(cost_snapshots)
    mapping_articles = _mapping_article_lookup(sku_mappings)
    cost_methods = _cost_method_lookup(cost_snapshots)
    report_rows = _client_unit_rows(source_rows, cost_names)
    for idx, row in enumerate(report_rows, start=1):
        sheet.write(
            idx,
            0,
            str(_display_week_start(row.week_start, report.report_period_start)),
        )
        sheet.write(idx, 1, row.document_report)
        sheet.write(idx, 2, row.wb_report_id)
        sheet.write(idx, 3, row.wb_report_date)
        sheet.write(
            idx, 4, _organization_label(row.organization_id, organization_labels)
        )
        sheet.write(idx, 5, _account_label(row.seller_account_id, account_labels))
        sheet.write(idx, 6, _product_label(row, cost_names))
        sheet.write(idx, 7, row.nm_id if _is_real_nm_id(row.nm_id) else "")
        sheet.write(idx, 8, row.vendor_code)
        sheet.write(idx, 9, _onec_article_label(row, cost_articles, mapping_articles))
        sheet.write(idx, 10, row.barcode)
        sheet.write(idx, 11, _sales_model_label(row.sales_model))
        sheet.write_number(idx, 12, float(row.sales_quantity))
        sheet.write_number(idx, 13, float(row.return_quantity))
        sheet.write_number(idx, 14, float(row.quantity))
        if row.return_rate_by_quantity is None:
            sheet.write(idx, 15, "")
        else:
            sheet.write_number(
                idx, 15, float(row.return_rate_by_quantity), formats["percent"]
            )
        sheet.write_number(idx, 16, float(row.revenue_before_spp), formats["money"])
        sheet.write_number(idx, 17, float(row.spp_discount), formats["money"])
        if row.spp_discount_rate is None:
            sheet.write(idx, 18, "")
        else:
            sheet.write_number(
                idx, 18, float(row.spp_discount_rate), formats["percent"]
            )
        sheet.write_number(idx, 19, float(row.revenue_after_spp), formats["money"])
        sheet.write_number(idx, 20, float(row.vat_5_from_revenue), formats["money"])
        sheet.write_number(idx, 21, float(row.revenue_without_vat), formats["money"])
        sheet.write_number(
            idx, 22, float(row.cogs_from_1c_with_extra_costs), formats["money"]
        )
        sheet.write_number(idx, 23, float(row.wb_commission), formats["money"])
        sheet.write_number(idx, 24, float(row.logistics), formats["money"])
        sheet.write_number(idx, 25, float(row.storage), formats["money"])
        sheet.write_number(idx, 26, float(row.acceptance), formats["money"])
        sheet.write_number(idx, 27, float(row.wb_promotion), formats["money"])
        sheet.write_number(
            idx, 28, float(row.penalties_and_holdbacks), formats["money"]
        )
        sheet.write_number(idx, 29, float(row.acquiring), formats["money"])
        sheet.write_number(idx, 30, float(row.usn_1_from_revenue), formats["money"])
        sheet.write_number(idx, 31, float(row.gross_profit), formats["money"])
        if row.margin is None:
            sheet.write(idx, 32, "")
        else:
            sheet.write_number(idx, 32, float(row.margin), formats["percent"])
        sheet.write_number(idx, 33, float(row.profit_after_taxes), formats["money"])
        if row.margin_after_taxes is None:
            sheet.write(idx, 34, "")
        else:
            sheet.write_number(
                idx, 34, float(row.margin_after_taxes), formats["percent"]
            )
        if row.profit_after_taxes_per_unit is None:
            sheet.write(idx, 35, "")
        else:
            sheet.write_number(
                idx, 35, float(row.profit_after_taxes_per_unit), formats["money"]
            )
        sheet.write(idx, 36, _data_quality_label(row.data_quality_status))
        sheet.write(idx, 37, _status_reason(row, cost_methods))
        sheet.write(idx, 38, row.spp_source_status)
        sheet.write(idx, 39, row.tax_method)
        sheet.write(idx, 40, row.tax_profile_source)
    row_count = len(report_rows)
    _add_table(sheet, headers, row_count)
    sheet.freeze_panes(1, 8)
    sheet.set_column(0, 0, 18)
    sheet.set_column(1, 1, 42)
    sheet.set_column(2, 5, 18)
    sheet.set_column(6, 6, 34)
    sheet.set_column(7, 11, 16)
    sheet.set_column(12, 35, 15)
    sheet.set_column(36, 36, 28)
    sheet.set_column(37, 40, 60)
    _apply_unit_economics_conditional_formatting(
        sheet,
        formats,
        row_count=row_count,
        headers=headers,
    )


def _write_liquidity_md(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Ликвидность МД")
    headers = [
        "Месяц",
        "Организация 1С",
        "Кабинет WB",
        "Товар",
        "nmId WB",
        "Артикул WB",
        "Артикул 1С",
        "Баркод",
        "Схема продажи",
        "Продажи, шт",
        "Возвраты, шт",
        "Чистое кол-во",
        "% возвратов",
        "Выручка после СПП",
        "Себестоимость 1С",
        "МД1 Наценка",
        "Комиссия WB",
        "МД2 после комиссии",
        "Хранение WB",
        "МД3 после хранения",
        "Логистика WB",
        "Приемка WB",
        "МД4 после логистики и приемки",
        "Продвижение WB",
        "МД5 после продвижения",
        "Штрафы/доплаты WB",
        "Эквайринг WB",
        "МД6 до налогов",
        "НДС",
        "Налог с выручки",
        "МД после налогов",
        "Маржа после налогов",
        "МД после налогов на шт",
        "Статус ликвидности",
        "Драйвер ликвидности",
        "Статус данных",
        "Причина статуса",
        "Статус СПП",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    rows = aggregate_liquidity_rows(
        _liquidity_source_rows(
            report,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_labels=account_labels,
            organization_labels=organization_labels,
        )
    )
    money_fields = {
        "revenue",
        "cost",
        "md1Markup",
        "commission",
        "md2AfterCommission",
        "storage",
        "md3AfterStorage",
        "logistics",
        "acceptance",
        "md4AfterLogisticsAcceptance",
        "promotion",
        "md5AfterPromotion",
        "penalties",
        "acquiring",
        "md6BeforeTax",
        "vat",
        "usn",
        "profit",
        "unitProfit",
    }
    percent_fields = {"returnRate", "margin"}
    columns = [
        "month",
        "organization",
        "cabinet",
        "product",
        "nmId",
        "articleWb",
        "article1c",
        "barcode",
        "scheme",
        "sales",
        "returns",
        "netQty",
        "returnRate",
        "revenue",
        "cost",
        "md1Markup",
        "commission",
        "md2AfterCommission",
        "storage",
        "md3AfterStorage",
        "logistics",
        "acceptance",
        "md4AfterLogisticsAcceptance",
        "promotion",
        "md5AfterPromotion",
        "penalties",
        "acquiring",
        "md6BeforeTax",
        "vat",
        "usn",
        "profit",
        "margin",
        "unitProfit",
        "liquidityStatus",
        "liquidityDriver",
        "status",
        "statusReason",
        "sppStatus",
    ]
    for row_idx, row in enumerate(rows, start=1):
        for col_idx, field in enumerate(columns):
            value = row.get(field)
            if value is None:
                sheet.write(row_idx, col_idx, "")
            elif field in percent_fields:
                sheet.write_number(row_idx, col_idx, float(value), formats["percent"])
            elif field in money_fields:
                sheet.write_number(row_idx, col_idx, float(value), formats["money"])
            elif isinstance(value, Decimal):
                sheet.write_number(row_idx, col_idx, float(value))
            else:
                sheet.write(row_idx, col_idx, value)
    row_count = len(rows)
    _add_table(sheet, headers, row_count)
    sheet.freeze_panes(1, 4)
    sheet.set_column(0, 2, 18)
    sheet.set_column(3, 3, 34)
    sheet.set_column(4, 8, 16)
    sheet.set_column(9, 32, 15)
    sheet.set_column(33, 35, 28)
    sheet.set_column(36, 37, 52)
    if row_count:
        profit_col = headers.index("МД после налогов")
        status_col = headers.index("Статус ликвидности")
        data_status_col = headers.index("Статус данных")
        sheet.conditional_format(
            1,
            profit_col,
            row_count,
            profit_col,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )
        sheet.conditional_format(
            1,
            profit_col,
            row_count,
            profit_col,
            {"type": "cell", "criteria": ">", "value": 0, "format": formats["good"]},
        )
        sheet.conditional_format(
            1,
            status_col,
            row_count,
            status_col,
            {
                "type": "text",
                "criteria": "containing",
                "value": "Убыточный",
                "format": formats["bad"],
            },
        )
        sheet.conditional_format(
            1,
            status_col,
            row_count,
            status_col,
            {
                "type": "text",
                "criteria": "containing",
                "value": "Нужна проверка",
                "format": formats["warn"],
            },
        )
        sheet.conditional_format(
            1,
            data_status_col,
            row_count,
            data_status_col,
            {
                "type": "text",
                "criteria": "not containing",
                "value": "ОК",
                "format": formats["warn"],
            },
        )


def _liquidity_source_rows(
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    cost_rows = list(cost_snapshots)
    mapping_rows = list(sku_mappings)
    cost_names = _cost_name_lookup(cost_rows)
    cost_articles = _cost_article_lookup(cost_rows)
    mapping_articles = _mapping_article_lookup(mapping_rows)
    cost_methods = _cost_method_lookup(cost_rows)
    result = []
    for row in _client_unit_rows(report.rows, cost_names):
        month_start = _row_month_start(row, report.report_period_start)
        result.append(
            {
                "month": _month_label(month_start, report),
                "organization": _organization_label(
                    row.organization_id, organization_labels
                ),
                "cabinet": _account_label(row.seller_account_id, account_labels),
                "product": _product_label(row, cost_names),
                "nmId": "" if row.nm_id is None else str(row.nm_id),
                "articleWb": row.vendor_code,
                "article1c": _onec_article_label(
                    row, cost_articles, mapping_articles
                ),
                "barcode": row.barcode,
                "scheme": _sales_model_label(row.sales_model),
                "sales": row.sales_quantity,
                "returns": row.return_quantity,
                "netQty": row.quantity,
                "revenue": row.net_revenue,
                "cost": row.cogs_from_1c_with_extra_costs,
                "commission": row.wb_commission,
                "storage": row.storage,
                "logistics": row.logistics,
                "acceptance": row.acceptance,
                "promotion": row.wb_promotion,
                "penalties": row.penalties_and_holdbacks,
                "acquiring": row.acquiring,
                "vat": row.vat_5_from_revenue,
                "usn": row.usn_1_from_revenue,
                "profitBeforeTax": row.gross_profit,
                "profit": row.profit_after_taxes,
                "status": _data_quality_label(row.data_quality_status),
                "statusReason": _status_reason(row, cost_methods),
                "sppStatus": row.spp_source_status,
            }
        )
    return result


def _apply_unit_economics_conditional_formatting(
    sheet: xlsxwriter.worksheet.Worksheet,
    formats: dict[str, object],
    *,
    row_count: int,
    headers: list[str],
) -> None:
    if row_count <= 0:
        return
    col = {header: index for index, header in enumerate(headers)}
    first_row = 1
    last_row = row_count
    profit_col = col["Маржинальный доход WB после налогов"]
    unit_profit_col = col["Маржинальный доход WB после налогов на шт"]
    margin_col = col["Маржа WB после налогов"]
    status_col = col["Статус данных"]
    reason_col = col["Причина статуса"]
    revenue_letter = xl_col_to_name(col["Выручка после СПП"])
    storage_letter = xl_col_to_name(col["Хранение WB"])
    promotion_letter = xl_col_to_name(col["Продвижение WB"])

    for target_col in (profit_col, unit_profit_col):
        sheet.conditional_format(
            first_row,
            target_col,
            last_row,
            target_col,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )
    sheet.conditional_format(
        first_row,
        margin_col,
        last_row,
        margin_col,
        {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
    )
    sheet.conditional_format(
        first_row,
        margin_col,
        last_row,
        margin_col,
        {
            "type": "cell",
            "criteria": "between",
            "minimum": 0,
            "maximum": 0.1,
            "format": formats["warn"],
        },
    )
    sheet.conditional_format(
        first_row,
        margin_col,
        last_row,
        margin_col,
        {
            "type": "cell",
            "criteria": ">=",
            "value": 0.2,
            "format": formats["good"],
        },
    )
    sheet.conditional_format(
        first_row,
        status_col,
        last_row,
        reason_col,
        {
            "type": "text",
            "criteria": "containing",
            "value": "Нет",
            "format": formats["bad"],
        },
    )
    sheet.conditional_format(
        first_row,
        status_col,
        last_row,
        reason_col,
        {
            "type": "text",
            "criteria": "containing",
            "value": "требует",
            "format": formats["warn"],
        },
    )
    for target_col, expense_letter in (
        (col["Хранение WB"], storage_letter),
        (col["Продвижение WB"], promotion_letter),
    ):
        sheet.conditional_format(
            first_row,
            target_col,
            last_row,
            target_col,
            {
                "type": "formula",
                "criteria": (
                    f"=AND(${revenue_letter}2<>0,"
                    f"{expense_letter}2/${revenue_letter}2>0.1)"
                ),
                "format": formats["warn"],
            },
        )


def _write_products(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Товары")
    headers = [
        "Неделя",
        "Кабинет WB",
        "Организация 1С",
        "nmId",
        "Артикул",
        "Баркод",
        "Модель",
        "Кол-во",
        "Выручка после СПП",
        "Выручка без НДС",
        "Себестоимость",
        "НДС",
        "Налог с выручки",
        "Маржинальный доход WB до налогов",
        "Маржинальный доход WB после налогов",
        "Маржа WB после налогов",
        "Маржинальный доход WB после налогов на шт",
        "Статус данных",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    for idx, row in enumerate(report.rows, start=1):
        sheet.write(idx, 0, str(row.week_start))
        sheet.write(idx, 1, _account_label(row.seller_account_id, account_labels))
        sheet.write(
            idx,
            2,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write(idx, 3, row.nm_id or "")
        sheet.write(idx, 4, row.vendor_code)
        sheet.write(idx, 5, row.barcode)
        sheet.write(idx, 6, row.sales_model.value)
        sheet.write_number(idx, 7, float(row.quantity))
        sheet.write_number(idx, 8, float(row.net_revenue), formats["money"])
        sheet.write_number(idx, 9, float(row.revenue_without_vat), formats["money"])
        sheet.write_number(
            idx, 10, float(row.cogs_from_1c_with_extra_costs), formats["money"]
        )
        sheet.write_number(idx, 11, float(row.vat_5_from_revenue), formats["money"])
        sheet.write_number(idx, 12, float(row.usn_1_from_revenue), formats["money"])
        sheet.write_number(idx, 13, float(row.gross_profit), formats["money"])
        sheet.write_number(idx, 14, float(row.profit_after_taxes), formats["money"])
        if row.margin_after_taxes is None:
            sheet.write(idx, 15, "")
        else:
            sheet.write_number(
                idx, 15, float(row.margin_after_taxes), formats["percent"]
            )
        if row.profit_after_taxes_per_unit is None:
            sheet.write(idx, 16, "")
        else:
            sheet.write_number(
                idx, 16, float(row.profit_after_taxes_per_unit), formats["money"]
            )
        sheet.write(idx, 17, _data_quality_label(row.data_quality_status))
    _add_table(sheet, headers, len(report.rows))
    sheet.set_column(0, 17, 16)


def _write_dynamics(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
) -> None:
    sheet = workbook.add_worksheet("Динамика")
    monthly_rows = _month_summary_rows(report.rows, report)
    sheet.write(0, 0, "Динамика месяц к месяцу", formats["section"])
    _write_table_block(
        sheet,
        formats,
        start_row=1,
        start_col=0,
        headers=[
            "Месяц",
            "Статус",
            "Продажи, шт",
            "Возвраты, шт",
            "% возвратов",
            "Выручка до СПП",
            "СПП",
            "% СПП",
            "Выручка после СПП",
            "Логистика",
            "Расходы WB",
            "Маржинальный доход WB после налогов",
            "Маржа WB после налогов",
        ],
        rows=monthly_rows,
        money_columns={5, 6, 8, 9, 10, 11},
        percent_columns={4, 7, 12},
    )
    month_change_rows = _month_change_rows(monthly_rows)
    month_change_start = 1 + len(monthly_rows) + 3
    if month_change_rows:
        sheet.write(month_change_start - 1, 0, "Изменение м/м", formats["section"])
        _write_table_block(
            sheet,
            formats,
            start_row=month_change_start,
            start_col=0,
            headers=[
                "Период",
                "Выручка после СПП, Δ",
                "Выручка после СПП, %",
                "Маржинальный доход, Δ",
                "Маржинальный доход, %",
                "Расходы WB, Δ",
                "Расходы WB, %",
            ],
            rows=month_change_rows,
            money_columns={1, 3, 5},
            percent_columns={2, 4, 6},
        )

    weekly_start = (
        month_change_start + (len(month_change_rows) if month_change_rows else 0) + 4
    )
    sheet.write(weekly_start - 1, 0, "Динамика по неделям", formats["section"])
    sheet.write_row(
        weekly_start,
        0,
        [
            "Неделя",
            "Выручка после СПП",
            "Маржинальный доход WB до налогов",
            "Маржинальный доход WB после налогов",
            "Неполная неделя",
        ],
        formats["header"],
    )
    weekly_rows = _weekly_summary_rows(
        report.rows,
        report_period_start=report.report_period_start,
    )
    for offset, row in enumerate(weekly_rows, start=1):
        idx = weekly_start + offset
        sheet.write(idx, 0, row[0])
        sheet.write_number(idx, 1, float(row[1]), formats["money"])
        sheet.write_number(idx, 2, float(row[2]), formats["money"])
        sheet.write_number(idx, 3, float(row[3]), formats["money"])
        sheet.write(idx, 4, "")
    _add_table_at(
        sheet,
        [
            "Неделя",
            "Выручка после СПП",
            "Маржинальный доход WB до налогов",
            "Маржинальный доход WB после налогов",
            "Неполная неделя",
        ],
        len(weekly_rows),
        start_row=weekly_start,
    )
    sheet.set_column(0, 0, 24)
    sheet.set_column(1, 18, 16)


def _write_wb_sales_report_summary(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    rows: list[WbSalesReportSummaryRow],
    *,
    account_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сводный отчет WB")
    headers = [
        "Период с",
        "Период по",
        "Дата создания WB",
        "Номер отчета WB",
        "Тип отчета",
        "Кабинет WB",
        "Продавец WB",
        "Валюта",
        "Выручка WB",
        "К перечислению",
        "Логистика",
        "Хранение",
        "Приемка",
        "WB Продвижение / удержания",
        "Штрафы",
        "Доплаты",
        "Cashback",
        "Скидка cashback",
        "Изменение комиссии cashback",
        "Банковский платеж",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    if not rows:
        sheet.write_row(1, 0, ["planned_input", "Сводный отчет WB не загружен."])
        _add_table(sheet, headers, 1)
        sheet.set_column(0, len(headers) - 1, 18)
        return
    for idx, row in enumerate(rows, start=1):
        sheet.write(idx, 0, str(row.date_from))
        sheet.write(idx, 1, str(row.date_to))
        sheet.write(idx, 2, str(row.create_date))
        sheet.write(idx, 3, row.report_id)
        sheet.write(idx, 4, _report_type_label(row.report_type))
        sheet.write(idx, 5, _account_label(row.seller_account_id, account_labels))
        sheet.write(idx, 6, row.seller_finance_name)
        sheet.write(idx, 7, row.currency)
        sheet.write_number(idx, 8, float(row.retail_amount_sum), formats["money"])
        sheet.write_number(idx, 9, float(row.for_pay_sum), formats["money"])
        sheet.write_number(idx, 10, float(row.delivery_service_sum), formats["money"])
        sheet.write_number(idx, 11, float(row.paid_storage_sum), formats["money"])
        sheet.write_number(idx, 12, float(row.paid_acceptance_sum), formats["money"])
        sheet.write_number(idx, 13, float(row.deduction_sum), formats["money"])
        sheet.write_number(idx, 14, float(row.penalty_sum), formats["money"])
        sheet.write_number(idx, 15, float(row.additional_payment_sum), formats["money"])
        sheet.write_number(idx, 16, float(row.cashback_amount_sum), formats["money"])
        sheet.write_number(idx, 17, float(row.cashback_discount_sum), formats["money"])
        sheet.write_number(
            idx,
            18,
            float(row.cashback_commission_change_sum),
            formats["money"],
        )
        sheet.write_number(idx, 19, float(row.bank_payment_sum), formats["money"])
    _add_table(sheet, headers, len(rows))
    sheet.set_column(0, len(headers) - 1, 18)


def _write_wb_report_fields(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    rows: list[WbSalesReportSummaryRow],
    *,
    account_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("WB поля отчета")
    headers = [
        "reportId",
        "reportType",
        "Источник типа",
        "Период с",
        "Период по",
        "Кабинет WB",
        "retailAmountSum",
        "cashbackDiscountSum",
        "retailAmountSum - cashbackDiscountSum",
        "forPaySum",
        "bankPaymentSum",
        "paidStorageSum",
        "deductionSum",
        "penaltySum",
        "additionalPaymentSum",
        "Статус выплаты",
    ]
    sheet.write(0, 0, "WB поля отчета", formats["title"])
    sheet.write(
        1,
        0,
        (
            "Диагностический блок из WB sales-reports/list. Он не заменяет "
            "лист Юнит экономика и не является источником выплат 1С."
        ),
        formats["note"],
    )
    start_row = 3
    sheet.write_row(start_row, 0, headers, formats["header"])
    if not rows:
        sheet.write_row(
            start_row + 1,
            0,
            ["planned_input", "Сводный отчет WB не загружен."],
        )
        _add_table_at(sheet, headers, 1, start_row=start_row)
        sheet.set_column(0, len(headers) - 1, 18)
        return
    for offset, row in enumerate(rows, start=start_row + 1):
        source = "reportType" if row.report_type is not None else "fallback"
        payout_status = DATA_QUALITY_LABELS[DataQualityStatus.PAYOUT_SOURCE_MISSING]
        sheet.write(offset, 0, row.report_id)
        sheet.write(offset, 1, _report_type_label(row.report_type))
        sheet.write(offset, 2, source)
        sheet.write(offset, 3, str(row.date_from))
        sheet.write(offset, 4, str(row.date_to))
        sheet.write(offset, 5, _account_label(row.seller_account_id, account_labels))
        sheet.write_number(offset, 6, float(row.retail_amount_sum), formats["money"])
        sheet.write_number(
            offset, 7, float(row.cashback_discount_sum), formats["money"]
        )
        sheet.write_number(
            offset,
            8,
            float(row.retail_amount_sum - row.cashback_discount_sum),
            formats["money"],
        )
        sheet.write_number(offset, 9, float(row.for_pay_sum), formats["money"])
        sheet.write_number(offset, 10, float(row.bank_payment_sum), formats["money"])
        sheet.write_number(offset, 11, float(row.paid_storage_sum), formats["money"])
        sheet.write_number(offset, 12, float(row.deduction_sum), formats["money"])
        sheet.write_number(offset, 13, float(row.penalty_sum), formats["money"])
        sheet.write_number(
            offset,
            14,
            float(row.additional_payment_sum),
            formats["money"],
        )
        sheet.write(offset, 15, payout_status)
    _add_table_at(sheet, headers, len(rows), start_row=start_row)
    sheet.freeze_panes(start_row + 1, 0)
    sheet.set_column(0, 5, 20)
    sheet.set_column(6, 14, 18)
    sheet.set_column(15, 15, 28)


def _write_report_reconciliation(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сверка по отчетам WB")
    headers = [
        "Неделя",
        "Номер отчета WB",
        "Кабинет WB",
        "Организация 1С",
        "Продажи, шт",
        "Возвраты, шт",
        "Итого, шт",
        "Выручка до СПП",
        "СПП",
        "% СПП",
        "Выручка после СПП",
        "Комиссия WB",
        "Логистика",
        "Хранение",
        "Приемка",
        "WB Продвижение",
        "Удержания/штрафы/доплаты",
        "Эквайринг",
        "Себестоимость 1С",
        "НДС",
        "Налог с выручки",
        "Маржинальный доход WB до налогов",
        "Маржа WB до налогов",
        "Маржинальный доход WB после налогов",
        "Маржа WB после налогов",
        "Статус СПП",
        "Статус данных",
        "Строк витрины",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    rows = report.report_reconciliation_rows
    for idx, row in enumerate(rows, start=1):
        sheet.write(idx, 0, str(row.week_start))
        sheet.write(idx, 1, row.wb_report_id)
        sheet.write(idx, 2, _account_label(row.seller_account_id, account_labels))
        sheet.write(
            idx,
            3,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write_number(idx, 4, float(row.sales_quantity))
        sheet.write_number(idx, 5, float(row.return_quantity))
        sheet.write_number(idx, 6, float(row.quantity))
        sheet.write_number(idx, 7, float(row.revenue_before_spp), formats["money"])
        sheet.write_number(idx, 8, float(row.spp_discount), formats["money"])
        if row.spp_discount_rate is None:
            sheet.write(idx, 9, "")
        else:
            sheet.write_number(idx, 9, float(row.spp_discount_rate), formats["percent"])
        sheet.write_number(idx, 10, float(row.revenue_after_spp), formats["money"])
        sheet.write_number(idx, 11, float(row.wb_commission), formats["money"])
        sheet.write_number(idx, 12, float(row.logistics), formats["money"])
        sheet.write_number(idx, 13, float(row.storage), formats["money"])
        sheet.write_number(idx, 14, float(row.acceptance), formats["money"])
        sheet.write_number(idx, 15, float(row.wb_promotion), formats["money"])
        sheet.write_number(
            idx, 16, float(row.penalties_and_holdbacks), formats["money"]
        )
        sheet.write_number(idx, 17, float(row.acquiring), formats["money"])
        sheet.write_number(
            idx, 18, float(row.cogs_from_1c_with_extra_costs), formats["money"]
        )
        sheet.write_number(idx, 19, float(row.vat_5_from_revenue), formats["money"])
        sheet.write_number(idx, 20, float(row.usn_1_from_revenue), formats["money"])
        sheet.write_number(idx, 21, float(row.gross_profit), formats["money"])
        if row.margin is None:
            sheet.write(idx, 22, "")
        else:
            sheet.write_number(idx, 22, float(row.margin), formats["percent"])
        sheet.write_number(idx, 23, float(row.profit_after_taxes), formats["money"])
        if row.margin_after_taxes is None:
            sheet.write(idx, 24, "")
        else:
            sheet.write_number(
                idx, 24, float(row.margin_after_taxes), formats["percent"]
            )
        sheet.write(idx, 25, row.spp_source_status)
        sheet.write(idx, 26, _data_quality_label(row.data_quality_status))
        sheet.write_number(idx, 27, row.source_row_count)
    _add_table(sheet, headers, len(rows))
    sheet.set_column(0, 3, 20)
    sheet.set_column(4, 6, 12)
    sheet.set_column(7, 24, 16)
    sheet.set_column(25, 27, 24)


def _write_onec_report_reconciliation(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    summary_rows: list[WbSalesReportSummaryRow] | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сверка с 1С")
    weekly_summaries = _weekly_summary_rows_by_type(summary_rows or [])
    headers = [
        "Дата документа 1С",
        "Период продаж",
        "Тип документа 1С",
        "Кабинет WB",
        "Организация 1С",
        "WB reportId в пакете",
        "Номер отчета WB (сводный)",
        "PDF 1. Стоимость реализовано",
        "PDF 1.1 Товар реализован",
        "PDF 1.4 Компенсация скидки",
        "PDF 8. К перечислению",
        "WB forPaySum",
        "Контроль удержаний WB (1 - банк)",
        "Дельта детализация - PDF 1",
        "Дельта логистика",
        "Дельта хранение",
        "Дельта WB Продвижение",
        "Дельта штрафы/доплаты",
        "Продажи, шт",
        "Возвраты, шт",
        "Итого, шт",
        "Реализация",
        "Возвраты",
        "Выручка до СПП",
        "СПП",
        "% СПП",
        "Выручка после СПП",
        "Комиссия WB",
        "Логистика",
        "Хранение",
        "Приемка",
        "WB Продвижение",
        "Удержания/штрафы/доплаты",
        "Эквайринг",
        "Себестоимость 1С",
        "Валовая прибыль 1С",
        "Прибыль после расходов WB",
        "Маржа после расходов WB",
        "НДС",
        "Налог с выручки",
        "Маржинальный доход WB после налогов",
        "Маржа WB после налогов",
        "Статус СПП",
        "Статус данных",
        "Строк витрины",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    rows = report.onec_report_reconciliation_rows
    for idx, row in enumerate(rows, start=1):
        matching_summaries = weekly_summaries.get(
            (row.seller_account_id, row.week_start, row.document_label),
            [],
        )
        summary_report_ids = tuple(
            summary.report_id for summary in matching_summaries if summary.report_id
        )
        summary_retail = _sum_summary_field(
            matching_summaries, "retail_amount_sum"
        )
        summary_goods = _sum_summary_goods_sold(matching_summaries)
        summary_loyalty_discount = _sum_summary_field(
            matching_summaries, "cashback_discount_sum"
        )
        summary_bank_payment = _sum_summary_field(
            matching_summaries, "bank_payment_sum"
        )
        summary_for_pay = _sum_summary_field(matching_summaries, "for_pay_sum")
        summary_delivery = _sum_summary_field(
            matching_summaries, "delivery_service_sum"
        )
        summary_storage = _sum_summary_field(
            matching_summaries, "paid_storage_sum"
        )
        summary_deduction = _sum_summary_field(
            matching_summaries, "deduction_sum"
        )
        summary_penalty_net = _sum_summary_field(
            matching_summaries, "penalty_sum"
        ) - _sum_summary_field(matching_summaries, "additional_payment_sum")
        summary_withheld_control = (
            summary_retail - summary_bank_payment if matching_summaries else None
        )
        detail_delta = (
            row.revenue_after_spp - summary_retail if matching_summaries else None
        )
        logistics_delta = (
            row.logistics - summary_delivery if matching_summaries else None
        )
        storage_delta = row.storage - summary_storage if matching_summaries else None
        promotion_delta = (
            row.wb_promotion - summary_deduction if matching_summaries else None
        )
        penalty_delta = (
            row.penalties_and_holdbacks - summary_penalty_net
            if matching_summaries
            else None
        )
        sheet.write(idx, 0, str(row.document_date))
        sheet.write(idx, 1, f"{row.week_start} - {row.week_end}")
        sheet.write(idx, 2, row.document_label)
        sheet.write(idx, 3, _account_label(row.seller_account_id, account_labels))
        sheet.write(
            idx,
            4,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write(idx, 5, ", ".join(row.wb_report_ids))
        sheet.write(idx, 6, ", ".join(summary_report_ids))
        _write_optional_money(sheet, idx, 7, summary_retail, formats["money"])
        _write_optional_money(sheet, idx, 8, summary_goods, formats["money"])
        _write_optional_money(
            sheet, idx, 9, summary_loyalty_discount, formats["money"]
        )
        _write_optional_money(sheet, idx, 10, summary_bank_payment, formats["money"])
        _write_optional_money(sheet, idx, 11, summary_for_pay, formats["money"])
        _write_optional_money(
            sheet, idx, 12, summary_withheld_control, formats["money"]
        )
        _write_optional_money(sheet, idx, 13, detail_delta, formats["money"])
        _write_optional_money(sheet, idx, 14, logistics_delta, formats["money"])
        _write_optional_money(sheet, idx, 15, storage_delta, formats["money"])
        _write_optional_money(sheet, idx, 16, promotion_delta, formats["money"])
        _write_optional_money(sheet, idx, 17, penalty_delta, formats["money"])
        sheet.write_number(idx, 18, float(row.sales_quantity))
        sheet.write_number(idx, 19, float(row.return_quantity))
        sheet.write_number(idx, 20, float(row.quantity))
        sheet.write_number(idx, 21, float(row.sales_amount), formats["money"])
        sheet.write_number(idx, 22, float(row.return_amount), formats["money"])
        sheet.write_number(idx, 23, float(row.revenue_before_spp), formats["money"])
        sheet.write_number(idx, 24, float(row.spp_discount), formats["money"])
        if row.spp_discount_rate is None:
            sheet.write(idx, 25, "")
        else:
            sheet.write_number(
                idx, 25, float(row.spp_discount_rate), formats["percent"]
            )
        sheet.write_number(idx, 26, float(row.revenue_after_spp), formats["money"])
        sheet.write_number(idx, 27, float(row.wb_commission), formats["money"])
        sheet.write_number(idx, 28, float(row.logistics), formats["money"])
        sheet.write_number(idx, 29, float(row.storage), formats["money"])
        sheet.write_number(idx, 30, float(row.acceptance), formats["money"])
        sheet.write_number(idx, 31, float(row.wb_promotion), formats["money"])
        sheet.write_number(
            idx, 32, float(row.penalties_and_holdbacks), formats["money"]
        )
        sheet.write_number(idx, 33, float(row.acquiring), formats["money"])
        sheet.write_number(
            idx, 34, float(row.cogs_from_1c_with_extra_costs), formats["money"]
        )
        onec_gross_profit = row.net_revenue - row.cogs_from_1c_with_extra_costs
        sheet.write_number(idx, 35, float(onec_gross_profit), formats["money"])
        sheet.write_number(idx, 36, float(row.gross_profit), formats["money"])
        if row.margin is None:
            sheet.write(idx, 37, "")
        else:
            sheet.write_number(idx, 37, float(row.margin), formats["percent"])
        sheet.write_number(idx, 38, float(row.vat_5_from_revenue), formats["money"])
        sheet.write_number(idx, 39, float(row.usn_1_from_revenue), formats["money"])
        sheet.write_number(idx, 40, float(row.profit_after_taxes), formats["money"])
        if row.margin_after_taxes is None:
            sheet.write(idx, 41, "")
        else:
            sheet.write_number(
                idx, 41, float(row.margin_after_taxes), formats["percent"]
            )
        sheet.write(idx, 42, row.spp_source_status)
        sheet.write(idx, 43, _data_quality_label(row.data_quality_status))
        sheet.write_number(idx, 44, row.source_row_count)
    _add_table(sheet, headers, len(rows))
    sheet.set_column(0, 6, 22)
    sheet.set_column(7, 17, 16)
    sheet.set_column(18, 20, 12)
    sheet.set_column(21, 41, 16)
    sheet.set_column(42, 44, 24)


def _write_onec_document_reconciliation(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    onec_rows: list[OnecGrossProfitDocumentRow],
    *,
    summary_rows: list[WbSalesReportSummaryRow] | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сверка документов 1С")
    headers = [
        "Статус сверки",
        "Статус выплаты",
        "Статус периода",
        "Период продаж",
        "Ожидаемая дата документа",
        "Тип документа WB/1С",
        "Кабинет WB",
        "Организация 1С",
        "Номер отчета WB (сводный)",
        "WB отчет продаж",
        "WB отчет выкупов",
        "WB reportId в пакете",
        "Документы 1С",
        "Типы документов 1С",
        "Даты документов 1С",
        "WB продажи",
        "WB возвраты",
        "WB чистое",
        "1С продажи",
        "1С возвраты",
        "1С чистое",
        "Дельта продажи",
        "Дельта возвраты",
        "Дельта чистое",
        "WB количество для 1С",
        "1С количество",
        "Дельта количество",
        "WB сумма документа",
        "1С сумма документа",
        "Дельта сумма",
        "WB выкуп: retailAmountSum",
        "WB выкуп: forPaySum",
        "WB выкуп: bankPaymentSum",
        "1С расходная накладная",
        "Δ выкуп retail",
        "Δ выкуп к перечислению",
        "Δ выкуп банк",
        "PDF 1. Стоимость реализовано",
        "PDF 1.1 Товар реализован",
        "PDF 8. К перечислению",
        "WB к перечислению (forPaySum)",
        "1С оборот взаиморасчетов",
        "Дельта к обороту 1С",
        "1С НДС",
        "Себестоимость по валовой прибыли 1С",
        "1С валовая прибыль",
        "Строк регистра 1С",
        "Комментарий",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    weekly_summaries = _weekly_summary_rows_by_type(summary_rows or [])
    onec_index = _index_onec_document_rows(onec_rows)
    matched_actual_keys: set[tuple[object, ...]] = set()
    output_rows: list[dict[str, object]] = []

    for expected in report.onec_report_reconciliation_rows:
        sales_summaries = weekly_summaries.get(
            (expected.seller_account_id, expected.week_start, "Отчет комиссионера"),
            [],
        )
        buyout_summaries = weekly_summaries.get(
            (expected.seller_account_id, expected.week_start, "Уведомление о выкупе"),
            [],
        )
        summaries = weekly_summaries.get(
            (expected.seller_account_id, expected.week_start, expected.document_label),
            [],
        )
        matched_candidates = _match_onec_document_rows(
            expected, onec_index, summaries
        )
        for actual in matched_candidates:
            matched_actual_keys.add(_onec_document_actual_key(actual))
        actuals = _document_reconciliation_actuals(matched_candidates)
        output_rows.append(
            _document_reconciliation_row(
                expected,
                actuals,
                summaries,
                report_period_end=report.report_period_end,
                sales_summaries=sales_summaries,
                buyout_summaries=buyout_summaries,
                account_labels=account_labels,
                organization_labels=organization_labels,
            )
        )

    for actual in onec_rows:
        if _onec_document_actual_key(actual) in matched_actual_keys:
            continue
        output_rows.append(
            _unmatched_onec_document_row(
                actual,
                organization_labels=organization_labels,
            )
        )

    for idx, row in enumerate(output_rows, start=1):
        sheet.write(idx, 0, str(row["status"]))
        sheet.write(idx, 1, str(row["payout_status"]))
        sheet.write(idx, 2, str(row["period_status"]))
        sheet.write(idx, 3, str(row["sales_period"]))
        sheet.write(idx, 4, str(row["expected_document_date"]))
        sheet.write(idx, 5, str(row["document_label"]))
        sheet.write(idx, 6, str(row["account_label"]))
        sheet.write(idx, 7, str(row["organization_label"]))
        sheet.write(idx, 8, str(row["summary_report_ids"]))
        sheet.write(idx, 9, str(row["weekly_sales_report_ids"]))
        sheet.write(idx, 10, str(row["weekly_buyout_report_ids"]))
        sheet.write(idx, 11, str(row["wb_report_ids"]))
        sheet.write(idx, 12, str(row["onec_document_ids"]))
        sheet.write(idx, 13, str(row["onec_document_types"]))
        sheet.write(idx, 14, str(row["onec_document_dates"]))
        _write_optional_number(sheet, idx, 15, row["expected_sales_quantity"])
        _write_optional_number(sheet, idx, 16, row["expected_return_quantity"])
        _write_optional_number(sheet, idx, 17, row["expected_net_quantity"])
        _write_optional_number(sheet, idx, 18, row["onec_sales_quantity"])
        _write_optional_number(sheet, idx, 19, row["onec_return_quantity"])
        _write_optional_number(sheet, idx, 20, row["onec_net_quantity"])
        _write_optional_number(sheet, idx, 21, row["sales_quantity_delta"])
        _write_optional_number(sheet, idx, 22, row["return_quantity_delta"])
        _write_optional_number(sheet, idx, 23, row["net_quantity_delta"])
        _write_optional_number(sheet, idx, 24, row["expected_quantity"])
        _write_optional_number(sheet, idx, 25, row["onec_quantity"])
        _write_optional_number(sheet, idx, 26, row["quantity_delta"])
        _write_optional_money(sheet, idx, 27, row["expected_amount"], formats["money"])
        _write_optional_money(sheet, idx, 28, row["onec_amount"], formats["money"])
        _write_optional_money(sheet, idx, 29, row["amount_delta"], formats["money"])
        _write_optional_money(
            sheet, idx, 30, row["buyout_retail_amount_sum"], formats["money"]
        )
        _write_optional_money(
            sheet, idx, 31, row["buyout_for_pay_sum"], formats["money"]
        )
        _write_optional_money(
            sheet, idx, 32, row["buyout_bank_payment_sum"], formats["money"]
        )
        _write_optional_money(
            sheet, idx, 33, row["onec_expense_invoice_amount"], formats["money"]
        )
        _write_optional_money(
            sheet, idx, 34, row["buyout_retail_delta"], formats["money"]
        )
        _write_optional_money(
            sheet, idx, 35, row["buyout_for_pay_delta"], formats["money"]
        )
        _write_optional_money(
            sheet, idx, 36, row["buyout_bank_delta"], formats["money"]
        )
        _write_optional_money(sheet, idx, 37, row["summary_retail"], formats["money"])
        _write_optional_money(sheet, idx, 38, row["summary_goods"], formats["money"])
        _write_optional_money(sheet, idx, 39, row["summary_bank"], formats["money"])
        _write_optional_money(
            sheet, idx, 40, row["expected_settlement"], formats["money"]
        )
        _write_optional_money(sheet, idx, 41, row["onec_settlement"], formats["money"])
        _write_optional_money(
            sheet, idx, 42, row["settlement_delta"], formats["money"]
        )
        _write_optional_money(sheet, idx, 43, row["onec_vat"], formats["money"])
        _write_optional_money(sheet, idx, 44, row["onec_cogs"], formats["money"])
        _write_optional_money(
            sheet, idx, 45, row["onec_gross_profit"], formats["money"]
        )
        _write_optional_number(sheet, idx, 46, row["onec_source_rows"])
        sheet.write(idx, 47, str(row["comment"]))

    _add_table(sheet, headers, len(output_rows))
    sheet.set_column(0, 0, 22)
    sheet.set_column(1, 2, 24)
    sheet.set_column(3, 14, 22)
    sheet.set_column(15, 46, 16)
    sheet.set_column(47, 47, 72)


def _index_onec_document_rows(
    rows: Iterable[OnecGrossProfitDocumentRow],
) -> dict[tuple[str, str, str, str], list[OnecGrossProfitDocumentRow]]:
    indexed: dict[tuple[str, str, str, str], list[OnecGrossProfitDocumentRow]] = (
        defaultdict(list)
    )
    for row in rows:
        document_label = _expected_document_label_for_onec_type(row.document_type)
        if row.external_report_id:
            indexed[
                (
                    "report_id",
                    row.organization_id,
                    document_label,
                    row.external_report_id,
                )
            ].append(row)
        indexed[
            (
                "sales_week",
                row.organization_id,
                document_label,
                _expected_sales_week_for_onec_document(row).isoformat(),
            )
        ].append(row)
    return indexed


def _match_onec_document_rows(
    expected: object,
    indexed: Mapping[tuple[str, str, str, str], list[OnecGrossProfitDocumentRow]],
    summaries: Iterable[WbSalesReportSummaryRow] = (),
) -> list[OnecGrossProfitDocumentRow]:
    exact_rows: list[OnecGrossProfitDocumentRow] = []
    seen: set[tuple[object, ...]] = set()
    exact_report_ids = [
        summary.report_id for summary in summaries if summary.report_id
    ] or list(expected.wb_report_ids)
    for report_id in exact_report_ids:
        key = (
            "report_id",
            expected.organization_id,
            expected.document_label,
            report_id,
        )
        for row in indexed.get(key, []):
            actual_key = _onec_document_actual_key(row)
            if actual_key in seen:
                continue
            exact_rows.append(row)
            seen.add(actual_key)
    if exact_rows:
        return exact_rows
    fallback_key = (
        "sales_week",
        expected.organization_id,
        expected.document_label,
        expected.week_start.isoformat(),
    )
    return list(indexed.get(fallback_key, []))


def _document_reconciliation_actuals(
    rows: list[OnecGrossProfitDocumentRow],
) -> list[OnecGrossProfitDocumentRow]:
    non_zero_document_rows = [
        row for row in rows if row.quantity != 0 or row.revenue != 0
    ]
    return non_zero_document_rows or rows


def _document_reconciliation_row(
    expected: object,
    actuals: list[OnecGrossProfitDocumentRow],
    summaries: list[WbSalesReportSummaryRow],
    *,
    report_period_end: date,
    sales_summaries: list[WbSalesReportSummaryRow],
    buyout_summaries: list[WbSalesReportSummaryRow],
    account_labels: Mapping[str, str] | None,
    organization_labels: Mapping[str, str] | None,
) -> dict[str, object]:
    expected_sales_quantity = expected.sales_quantity
    expected_return_quantity = expected.return_quantity
    expected_net_quantity = expected.quantity
    onec_sales_quantity = _sum_onec_document_field(actuals, "sales_quantity")
    onec_return_quantity = _sum_onec_document_field(actuals, "return_quantity")
    onec_net_quantity = _sum_onec_document_field(actuals, "quantity")
    is_buyout_document = expected.document_label == "Уведомление о выкупе"
    expected_quantity = _expected_onec_document_quantity(expected)
    expected_amount = _expected_onec_document_amount(expected, summaries)
    onec_quantity = onec_sales_quantity if is_buyout_document else onec_net_quantity
    onec_amount = _sum_onec_document_field(actuals, "revenue")
    expected_settlement = (
        _sum_summary_field(summaries, "for_pay_sum") if summaries else None
    )
    onec_settlement = (
        _sum_onec_document_optional_field(actuals, "settlement_total")
        if actuals
        else None
    )
    sales_quantity_delta = (
        expected_sales_quantity - onec_sales_quantity if actuals else None
    )
    return_quantity_delta = (
        expected_return_quantity - onec_return_quantity if actuals else None
    )
    net_quantity_delta = expected_net_quantity - onec_net_quantity if actuals else None
    quantity_delta = expected_quantity - onec_quantity if actuals else None
    amount_delta = expected_amount - onec_amount if actuals else None
    settlement_delta = (
        expected_settlement - onec_settlement
        if expected_settlement is not None and onec_settlement is not None
        else None
    )
    buyout_retail_amount_sum = (
        _sum_summary_field(buyout_summaries, "retail_amount_sum")
        if buyout_summaries and is_buyout_document
        else None
    )
    buyout_for_pay_sum = (
        _sum_summary_field(buyout_summaries, "for_pay_sum")
        if buyout_summaries and is_buyout_document
        else None
    )
    buyout_bank_payment_sum = (
        _sum_summary_field(buyout_summaries, "bank_payment_sum")
        if buyout_summaries and is_buyout_document
        else None
    )
    onec_expense_invoice_amount = (
        onec_amount if actuals and is_buyout_document else None
    )
    buyout_retail_delta = _optional_delta(
        buyout_retail_amount_sum, onec_expense_invoice_amount
    )
    buyout_for_pay_delta = _optional_delta(
        buyout_for_pay_sum, onec_expense_invoice_amount
    )
    buyout_bank_delta = _optional_delta(
        buyout_bank_payment_sum, onec_expense_invoice_amount
    )
    payout_status = _document_payout_status(expected_settlement)
    period_status = (
        "неполный период" if expected.week_end > report_period_end else "полный период"
    )
    status, comment = _document_reconciliation_status(
        expected,
        actuals,
        sales_quantity_delta,
        return_quantity_delta,
        net_quantity_delta,
        quantity_delta,
        amount_delta,
        expected_settlement,
        payout_status,
    )
    return {
        "status": status,
        "payout_status": payout_status,
        "period_status": period_status,
        "sales_period": f"{expected.week_start} - {expected.week_end}",
        "expected_document_date": _expected_onec_document_date(expected),
        "document_label": expected.document_label,
        "account_label": _account_label(expected.seller_account_id, account_labels),
        "organization_label": _organization_label(
            expected.organization_id, organization_labels
        ),
        "summary_report_ids": ", ".join(
            summary.report_id for summary in summaries if summary.report_id
        ),
        "weekly_sales_report_ids": _summary_report_ids(sales_summaries),
        "weekly_buyout_report_ids": _summary_report_ids(buyout_summaries),
        "wb_report_ids": ", ".join(expected.wb_report_ids),
        "onec_document_ids": ", ".join(
            _onec_document_display_label(row) for row in actuals
        ),
        "onec_document_types": ", ".join(
            sorted({row.document_type for row in actuals})
        ),
        "onec_document_dates": ", ".join(
            sorted({row.document_date.isoformat() for row in actuals})
        ),
        "expected_sales_quantity": expected_sales_quantity,
        "expected_return_quantity": expected_return_quantity,
        "expected_net_quantity": expected_net_quantity,
        "onec_sales_quantity": onec_sales_quantity if actuals else None,
        "onec_return_quantity": onec_return_quantity if actuals else None,
        "onec_net_quantity": onec_net_quantity if actuals else None,
        "sales_quantity_delta": sales_quantity_delta,
        "return_quantity_delta": return_quantity_delta,
        "net_quantity_delta": net_quantity_delta,
        "expected_quantity": expected_quantity,
        "onec_quantity": onec_quantity if actuals else None,
        "quantity_delta": quantity_delta,
        "expected_amount": expected_amount,
        "onec_amount": onec_amount if actuals else None,
        "amount_delta": amount_delta,
        "buyout_retail_amount_sum": buyout_retail_amount_sum,
        "buyout_for_pay_sum": buyout_for_pay_sum,
        "buyout_bank_payment_sum": buyout_bank_payment_sum,
        "onec_expense_invoice_amount": onec_expense_invoice_amount,
        "buyout_retail_delta": buyout_retail_delta,
        "buyout_for_pay_delta": buyout_for_pay_delta,
        "buyout_bank_delta": buyout_bank_delta,
        "summary_retail": _sum_summary_field(summaries, "retail_amount_sum")
        if summaries
        else None,
        "summary_goods": _sum_summary_goods_sold(summaries) if summaries else None,
        "summary_bank": _sum_summary_field(summaries, "bank_payment_sum")
        if summaries
        else None,
        "expected_settlement": expected_settlement,
        "onec_settlement": onec_settlement,
        "settlement_delta": settlement_delta,
        "onec_vat": _sum_onec_document_field(actuals, "vat") if actuals else None,
        "onec_cogs": _sum_onec_document_field(actuals, "cogs") if actuals else None,
        "onec_gross_profit": _sum_onec_document_field(actuals, "gross_profit")
        if actuals
        else None,
        "onec_source_rows": sum(row.source_row_count for row in actuals)
        if actuals
        else None,
        "comment": comment,
    }


def _unmatched_onec_document_row(
    actual: OnecGrossProfitDocumentRow,
    *,
    organization_labels: Mapping[str, str] | None,
) -> dict[str, object]:
    status = "Лишний документ в 1С"
    document_label = _expected_document_label_for_onec_type(actual.document_type)
    comment = "В 1С есть документ маркетплейса, но в WB-пакетах MVP он не найден."
    if _is_onec_correction_document(actual):
        status = "Корректировка 1С"
        document_label = "Корректировка 1С"
        comment = (
            "В 1С есть отрицательная приходная накладная/корректировка. "
            "Она выведена отдельно и не считается обычным лишним WB-документом."
        )
    return {
        "status": status,
        "payout_status": "Нет WB forPaySum",
        "period_status": "период 1С",
        "sales_period": (
            f"{_expected_sales_week_for_onec_document(actual)} - "
            f"{_expected_sales_week_for_onec_document(actual) + timedelta(days=6)}"
        ),
        "expected_document_date": "",
        "document_label": document_label,
        "account_label": "",
        "organization_label": _organization_label(
            actual.organization_id, organization_labels
        ),
        "summary_report_ids": "",
        "weekly_sales_report_ids": "",
        "weekly_buyout_report_ids": "",
        "wb_report_ids": "",
        "onec_document_ids": _onec_document_display_label(actual),
        "onec_document_types": actual.document_type,
        "onec_document_dates": actual.document_date.isoformat(),
        "expected_sales_quantity": None,
        "expected_return_quantity": None,
        "expected_net_quantity": None,
        "onec_sales_quantity": actual.sales_quantity,
        "onec_return_quantity": actual.return_quantity,
        "onec_net_quantity": actual.quantity,
        "sales_quantity_delta": None,
        "return_quantity_delta": None,
        "net_quantity_delta": None,
        "expected_quantity": None,
        "onec_quantity": actual.quantity,
        "quantity_delta": None,
        "expected_amount": None,
        "onec_amount": actual.revenue,
        "amount_delta": None,
        "buyout_retail_amount_sum": None,
        "buyout_for_pay_sum": None,
        "buyout_bank_payment_sum": None,
        "onec_expense_invoice_amount": None,
        "buyout_retail_delta": None,
        "buyout_for_pay_delta": None,
        "buyout_bank_delta": None,
        "summary_retail": None,
        "summary_goods": None,
        "summary_bank": None,
        "expected_settlement": None,
        "onec_settlement": actual.settlement_total,
        "settlement_delta": None,
        "onec_vat": actual.vat,
        "onec_cogs": actual.cogs,
        "onec_gross_profit": actual.gross_profit,
        "onec_source_rows": actual.source_row_count,
        "comment": comment,
    }


def _expected_onec_document_quantity(expected: object) -> Decimal:
    if expected.document_label == "Уведомление о выкупе":
        return expected.sales_quantity
    return expected.quantity


def _onec_document_display_label(row: OnecGrossProfitDocumentRow) -> str:
    number = row.document_number.strip()
    input_number = row.input_number.strip()
    parts: list[str] = []
    if number:
        parts.append(f"№ {number}")
    if input_number and input_number != number:
        parts.append(f"вх. {input_number}")
    if parts:
        return f"{row.document_type} {' / '.join(parts)}"
    if row.external_report_id:
        return f"{row.document_type} вх. {row.external_report_id}"
    if row.document_id and not _looks_like_uuid(row.document_id):
        return row.document_id
    return f"{row.document_type} от {row.document_date} (номер не загружен)"


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _expected_onec_document_amount(
    expected: object,
    summaries: list[WbSalesReportSummaryRow],
) -> Decimal:
    if expected.document_label == "Отчет комиссионера" and summaries:
        return _sum_summary_field(summaries, "retail_amount_sum")
    return expected.revenue_after_spp


def _expected_onec_document_date(expected: object) -> date:
    if expected.document_label == "Уведомление о выкупе":
        return expected.week_start
    if expected.document_label == "Отчет комиссионера":
        return expected.week_end
    return expected.document_date


def _expected_sales_week_for_onec_document(
    row: OnecGrossProfitDocumentRow,
) -> date:
    return row.week_start


def _expected_document_label_for_onec_type(document_type: str) -> str:
    normalized = document_type.replace(" ", "").lower()
    if "расходнаянакладная" in normalized:
        return "Уведомление о выкупе"
    if "отчеткомиссионера" in normalized:
        return "Отчет комиссионера"
    return document_type or "Неизвестный документ 1С"


def _is_onec_correction_document(row: OnecGrossProfitDocumentRow) -> bool:
    normalized = row.document_type.replace(" ", "").lower()
    return "приходнаянакладная" in normalized and (
        row.quantity < 0 or row.revenue < 0 or row.cogs < 0
    )


def _sum_onec_document_field(
    rows: Iterable[OnecGrossProfitDocumentRow],
    field_name: str,
) -> Decimal:
    return sum((getattr(row, field_name) for row in rows), Decimal("0"))


def _sum_onec_document_optional_field(
    rows: Iterable[OnecGrossProfitDocumentRow],
    field_name: str,
) -> Decimal | None:
    total = Decimal("0")
    found = False
    for row in rows:
        value = getattr(row, field_name)
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def _onec_document_actual_key(row: OnecGrossProfitDocumentRow) -> tuple[object, ...]:
    return (
        row.organization_id,
        row.document_id,
        row.document_type,
        row.document_date,
    )


def _document_reconciliation_status(
    expected: object,
    actuals: list[OnecGrossProfitDocumentRow],
    sales_quantity_delta: Decimal | None,
    return_quantity_delta: Decimal | None,
    net_quantity_delta: Decimal | None,
    quantity_delta: Decimal | None,
    amount_delta: Decimal | None,
    expected_settlement: Decimal | None,
    payout_status: str,
) -> tuple[str, str]:
    if not actuals:
        return (
            "Не найден в 1С",
            "Ожидаемый WB-документ не найден в регистре Продажи 1С.",
        )
    is_buyout_document = expected.document_label == "Уведомление о выкупе"
    if is_buyout_document:
        quantity_ok = sales_quantity_delta == 0
    else:
        quantity_ok = (
            sales_quantity_delta == 0
            and return_quantity_delta == 0
            and net_quantity_delta == 0
        )
    amount_required = not is_buyout_document
    amount_ok = (
        not amount_required
        or (amount_delta is not None and abs(amount_delta) <= Decimal("1.00"))
    )
    payout_comment = ""
    if expected_settlement is not None:
        payout_comment = (
            " WB 'К перечислению' показан отдельно; текущий 1С оборот "
            "взаиморасчетов не считается подтвержденной выплатой."
        )
    if quantity_ok and amount_ok:
        if is_buyout_document:
            if return_quantity_delta is not None and return_quantity_delta != 0:
                return (
                    "Документ найден",
                    "Расходная накладная 1С по уведомлению о выкупе найдена. "
                    "Количество продаж WB совпало с расходной накладной 1С. "
                    "Возвраты WB из выкупного отчета показаны справочно: в "
                    "текущем источнике 1С они не проходят минусом в этой же "
                    "расходной накладной и не считаются ошибкой загрузки "
                    "документа. Сумма расходной накладной 1С соответствует "
                    "бумажному уведомлению о выкупе нетто после удержаний; "
                    "WB retail, forPaySum и bankPaymentSum показаны отдельно "
                    "только для диагностики."
                    f"{payout_comment}",
                )
            return (
                "OK",
                "Документ выкупа найден; диагностическое количество из "
                "WB-детализации совпало с расходной накладной 1С. "
                "Сумма расходной накладной 1С соответствует бумажному "
                "уведомлению о выкупе нетто после удержаний; WB retail, "
                "forPaySum и bankPaymentSum показаны отдельно только для "
                "диагностики."
                f"{payout_comment}",
            )
        return (
            "OK",
            "Документ, количество и сумма совпали с 1С "
            f"в пределах 1 рубля.{payout_comment}",
        )
    if (
        not quantity_ok
        and amount_ok
        and expected.document_label == "Отчет комиссионера"
    ):
        return (
            "Проверить товарные строки",
            "Сумма отчета комиссионера совпала с контрольной строкой WB "
            "retailAmountSum из sales-reports/list. Осталась разница только "
            "по товарным строкам/возвратам; проверить детализацию загрузки "
            "номенклатуры в 1С."
            f"{payout_comment}",
        )
    issues = []
    if not quantity_ok:
        issues.append("количество")
    if not amount_ok:
        issues.append("сумму")
    comment = f"Проверить {' и '.join(issues)} загрузки документа в 1С."
    if payout_status == "Нужен источник выплаты 1С":
        comment += (
            " Для контроля выплаты нужен отдельный подтвержденный read-only "
            "источник 1С; оборот взаиморасчетов выводится справочно."
        )
    if is_buyout_document:
        comment += (
            " Для выкупов количество расходной накладной сверяется с WB "
            "продажами, а WB возвраты выводятся справочно. Сумма расходной "
            "накладной 1С является бумажным "
            "нетто-уведомлением после удержаний; WB retail, forPaySum и "
            "bankPaymentSum показаны отдельно только для диагностики."
        )
    return "Проверить " + " и ".join(issues), comment


def _document_payout_status(expected_settlement: Decimal | None) -> str:
    if expected_settlement is None:
        return "Нет WB forPaySum"
    return "Нужен источник выплаты 1С"


def _write_onec_opiu_reconciliation(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    onec_gross_profit_rows: Iterable[OnecGrossProfitDocumentRow] = (),
    wb_sales_report_summary_rows: Iterable[WbSalesReportSummaryRow] = (),
    onec_opiu_summary: OnecOpiuSummary | None = None,
    onec_document_dates: Mapping[tuple[str, str, date, str], date] | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сверка с 1С ОПиУ")
    gross_profit_rows = list(onec_gross_profit_rows)
    gross_profit_totals = _onec_gross_profit_totals_by_document_period(
        gross_profit_rows,
        period_start=report.report_period_start,
        period_end=report.report_period_end,
    )
    totals = _totals(report.rows)
    wb_expenses = _wb_expenses(totals)
    headers = ["Показатель", "WB-витрина", "1С РВБ/ОПиУ", "Дельта", "Комментарий"]
    rwb_breakdown_comment = "Расшифровка общего блока РВБ."
    onec = onec_opiu_summary
    rows: list[tuple[str, object, object, object, str]] = [
        (
            "Выручка до СПП",
            totals["revenue_before_spp"],
            None,
            None,
            "Не сравниваем с ОПиУ: выручка 1С включает не только Wildberries.",
        ),
        (
            "СПП",
            totals["spp_discount"],
            None,
            None,
            _combined_spp_status(report.rows),
        ),
        (
            "% СПП",
            _safe_margin(totals["spp_discount"], totals["revenue_before_spp"]),
            None,
            None,
            "Доля СПП от выручки до СПП.",
        ),
        (
            "Выручка после СПП",
            totals["revenue_after_spp"],
            gross_profit_totals["revenue"],
            _reconciliation_delta(
                totals["revenue_after_spp"], gross_profit_totals["revenue"]
            ),
            "Сверяем только документы РВБ из отчета Валовая прибыль 1С.",
        ),
        (
            "Себестоимость РВБ",
            totals["cogs"],
            gross_profit_totals["cogs"],
            _reconciliation_delta(totals["cogs"], gross_profit_totals["cogs"]),
            "Сверяем только документы РВБ из отчета Валовая прибыль 1С.",
        ),
        (
            "Валовая прибыль РВБ",
            totals["revenue_after_spp"] - totals["cogs"],
            gross_profit_totals["gross_profit"],
            _reconciliation_delta(
                totals["revenue_after_spp"] - totals["cogs"],
                gross_profit_totals["gross_profit"],
            ),
            "Контроль до расходов маркетплейса, налогов и управленческого ОПиУ.",
        ),
        (
            "НДС",
            totals["vat_5"],
            None,
            None,
            "WB-оценка НДС; ОПиУ НДС не сравниваем без фильтра только по WB.",
        ),
        (
            "Выручка без НДС",
            totals["revenue_after_spp"] - totals["vat_5"],
            None,
            None,
            "WB-выручка без НДС; общую ОПиУ-выручку сюда не подставляем.",
        ),
        (
            "Расходы РВБ общий блок",
            wb_expenses,
            onec.value("rwb_total") if onec else None,
            _reconciliation_delta(
                wb_expenses, onec.value("rwb_total") if onec else None
            ),
            "Для сверки сначала сравниваем общий блок РВБ, затем классификацию статей.",
        ),
        (
            "РВБ: комиссия",
            totals["wb_commission"],
            onec.value("rwb_commission") if onec else None,
            _reconciliation_delta(
                totals["wb_commission"],
                onec.value("rwb_commission") if onec else None,
            ),
            rwb_breakdown_comment,
        ),
        (
            "РВБ: логистика",
            totals["logistics"],
            onec.value("rwb_logistics") if onec else None,
            _reconciliation_delta(
                totals["logistics"], onec.value("rwb_logistics") if onec else None
            ),
            rwb_breakdown_comment,
        ),
        (
            "РВБ: ПВЗ",
            None,
            onec.value("rwb_pvz") if onec else None,
            None,
            "Отдельная статья 1С/ОПиУ; в WB-витрине сверяется в общем блоке РВБ.",
        ),
        (
            "РВБ: хранение",
            totals["storage"],
            None,
            None,
            "В текущем ОПиУ 1С эта статья может быть в классификации РВБ/ПВЗ.",
        ),
        (
            "РВБ: приемка",
            totals["acceptance"],
            None,
            None,
            "В текущем ОПиУ 1С отдельная приемка не выделена подтвержденной строкой.",
        ),
        (
            "РВБ: продвижение/удержания",
            totals["wb_promotion"],
            onec.value("rwb_promotion") if onec else None,
            _reconciliation_delta(
                totals["wb_promotion"],
                onec.value("rwb_promotion") if onec else None,
            ),
            rwb_breakdown_comment,
        ),
        (
            "РВБ: утилизация",
            None,
            onec.value("rwb_utilization") if onec else None,
            None,
            "Отдельная статья 1С/ОПиУ; в WB-витрине сверяется в общем блоке РВБ.",
        ),
        (
            "РВБ: штрафы/доплаты",
            totals["penalties_and_holdbacks"],
            onec.value("rwb_fines") if onec else None,
            _reconciliation_delta(
                totals["penalties_and_holdbacks"],
                onec.value("rwb_fines") if onec else None,
            ),
            rwb_breakdown_comment,
        ),
        (
            "РВБ: подписка Джем",
            None,
            onec.value("rwb_subscription") if onec else None,
            None,
            "Отдельная статья 1С/ОПиУ; в WB-витрине сверяется в общем блоке РВБ.",
        ),
        (
            "РВБ: эквайринг",
            totals["acquiring"],
            onec.value("rwb_acquiring") if onec else None,
            _reconciliation_delta(
                totals["acquiring"], onec.value("rwb_acquiring") if onec else None
            ),
            rwb_breakdown_comment,
        ),
        (
            "Маржинальный доход WB после налогов",
            totals["profit_after_taxes"],
            None,
            None,
            (
                "Это не полная чистая прибыль бизнеса, а товарная экономика WB "
                "после НДС/УСН."
            ),
        ),
    ]
    sheet.write(0, 0, "Сверка с 1С ОПиУ", formats["title"])
    sheet.write(
        1,
        0,
        (
            "Себестоимость в WB-расчете берется из регистра Продажи 1С. "
            "Основная сверка ниже сравнивает ее с отчетом Валовая прибыль 1С "
            "по месяцу даты документа. Общая выручка и общая себестоимость ОПиУ "
            "не используются в товарной сверке, чтобы не смешивать РВБ с полным "
            "управленческим контуром."
        ),
        formats["note"],
    )
    if onec and onec.config_status == "pilot_defaults":
        sheet.write(
            2,
            0,
            (
                "Статус настроек ОПиУ: "
                f"{DATA_QUALITY_LABELS[DataQualityStatus.OPIU_PILOT_DEFAULTS]}."
            ),
            formats["note"],
        )
    elif onec:
        sheet.write(
            2,
            0,
            f"Статус настроек ОПиУ: configured ({onec.config_source_label}).",
            formats["note"],
        )
    detail_start = _write_onec_opiu_monthly_reconciliation(
        sheet,
        formats,
        report,
        onec_gross_profit_rows=gross_profit_rows,
        wb_sales_report_summary_rows=wb_sales_report_summary_rows,
        onec_opiu_summary=onec,
        onec_document_dates=onec_document_dates,
        start_row=4,
    )
    sheet.write(
        detail_start - 1,
        0,
        "Справочно: РВБ по валовой прибыли 1С и статьи РВБ из ОПиУ",
        formats["section"],
    )
    sheet.write_row(detail_start, 0, headers, formats["header"])
    for offset, (label, wb_value, onec_value, delta, comment) in enumerate(
        rows, start=detail_start + 1
    ):
        sheet.write(offset, 0, label)
        _write_reconciliation_value(sheet, formats, offset, 1, wb_value, label)
        _write_reconciliation_value(sheet, formats, offset, 2, onec_value, label)
        _write_reconciliation_value(sheet, formats, offset, 3, delta, label)
        sheet.write(offset, 4, comment)
    _add_table_at(sheet, headers, len(rows), start_row=detail_start)
    sheet.set_column(0, 0, 38)
    sheet.set_column(1, 7, 18)
    sheet.set_column(4, 4, 72)


def _write_reconciliation_value(
    sheet: xlsxwriter.worksheet.Worksheet,
    formats: dict[str, object],
    row_idx: int,
    col_idx: int,
    value: object,
    label: str,
) -> None:
    if value is None:
        sheet.write(row_idx, col_idx, "")
    elif isinstance(value, Decimal) and label.strip().startswith("%"):
        sheet.write_number(row_idx, col_idx, float(value), formats["percent"])
    elif isinstance(value, Decimal | int | float):
        sheet.write_number(row_idx, col_idx, float(value), formats["money"])
    else:
        sheet.write(row_idx, col_idx, str(value))


def _reconciliation_delta(
    wb_value: Decimal | None,
    onec_value: Decimal | None,
) -> Decimal | None:
    if wb_value is None or onec_value is None:
        return None
    return wb_value - onec_value


def _reconciliation_delta_rate(
    delta: Decimal | None,
    base_value: Decimal | None,
) -> Decimal | None:
    if delta is None or base_value in (None, Decimal("0")):
        return None
    return (delta / base_value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _onec_gross_profit_cogs_by_document_month(
    rows: Iterable[OnecGrossProfitDocumentRow],
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Decimal]:
    cogs_by_month: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        if period_start <= row.document_date <= period_end:
            cogs_by_month[row.document_date.strftime("%Y-%m")] += row.cogs
    return dict(cogs_by_month)


def _wb_onec_report_product_totals_by_document_month(
    rows: Iterable[object],
    *,
    period_start: date,
    period_end: date,
    onec_document_dates: Mapping[tuple[str, str, date, str], date] | None = None,
) -> dict[str, dict[str, Decimal]]:
    totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"quantity": Decimal("0"), "cogs": Decimal("0")}
    )
    for row in rows:
        document_date = _resolved_onec_document_date(row, onec_document_dates)
        if period_start <= document_date <= period_end:
            month = document_date.strftime("%Y-%m")
            totals[month]["quantity"] += getattr(row, "quantity", Decimal("0"))
            totals[month]["cogs"] += getattr(
                row, "cogs_from_1c_with_extra_costs", Decimal("0")
            )
    return dict(totals)


def _matched_onec_gross_profit_totals_by_document_month(
    report: UnitEconomicsReport,
    rows: Iterable[OnecGrossProfitDocumentRow],
    summary_rows: Iterable[WbSalesReportSummaryRow],
    *,
    period_start: date,
    period_end: date,
) -> dict[str, dict[str, Decimal]]:
    totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"quantity": Decimal("0"), "cogs": Decimal("0")}
    )
    indexed = _index_onec_document_rows(rows)
    weekly_summaries = _weekly_summary_rows_by_type(summary_rows)
    seen: set[tuple[object, ...]] = set()
    for expected in report.onec_report_reconciliation_rows:
        summaries = weekly_summaries.get(
            (
                expected.seller_account_id,
                expected.week_start,
                expected.document_label,
            ),
            [],
        )
        matched = _document_reconciliation_actuals(
            _match_onec_document_rows(expected, indexed, summaries)
        )
        for actual in matched:
            actual_key = _onec_document_actual_key(actual)
            if actual_key in seen:
                continue
            if actual.document_date < period_start or actual.document_date > period_end:
                continue
            seen.add(actual_key)
            month = actual.document_date.strftime("%Y-%m")
            totals[month]["quantity"] += actual.quantity
            totals[month]["cogs"] += actual.cogs
    return dict(totals)


def _resolved_onec_document_dates_by_package(
    report: UnitEconomicsReport,
    rows: Iterable[OnecGrossProfitDocumentRow],
    summary_rows: Iterable[WbSalesReportSummaryRow],
) -> dict[tuple[str, str, date, str], date]:
    indexed = _index_onec_document_rows(rows)
    weekly_summaries = _weekly_summary_rows_by_type(summary_rows)
    document_dates: dict[tuple[str, str, date, str], date] = {}
    for expected in report.onec_report_reconciliation_rows:
        summaries = weekly_summaries.get(
            (
                expected.seller_account_id,
                expected.week_start,
                expected.document_label,
            ),
            [],
        )
        actuals = _document_reconciliation_actuals(
            _match_onec_document_rows(expected, indexed, summaries)
        )
        actual_dates = sorted({actual.document_date for actual in actuals})
        if len(actual_dates) == 1:
            document_dates[_report_package_key(expected)] = actual_dates[0]
    return document_dates


def _resolved_onec_document_date(
    row: object,
    onec_document_dates: Mapping[tuple[str, str, date, str], date] | None,
) -> date:
    if onec_document_dates:
        document_date = onec_document_dates.get(_report_package_key(row))
        if document_date is not None:
            return document_date
    return _expected_onec_document_date(row)


def _report_package_key(row: object) -> tuple[str, str, date, str]:
    return (
        row.seller_account_id,
        row.organization_id,
        row.week_start,
        row.document_label,
    )


def _onec_gross_profit_totals_by_document_period(
    rows: Iterable[OnecGrossProfitDocumentRow],
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Decimal]:
    totals = {
        "quantity": Decimal("0"),
        "revenue": Decimal("0"),
        "cogs": Decimal("0"),
        "gross_profit": Decimal("0"),
    }
    for row in rows:
        if period_start <= row.document_date <= period_end:
            totals["quantity"] += row.quantity
            totals["revenue"] += row.revenue
            totals["cogs"] += row.cogs
            totals["gross_profit"] += row.gross_profit
    return totals


def _write_onec_opiu_monthly_reconciliation(
    sheet: xlsxwriter.worksheet.Worksheet,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    onec_gross_profit_rows: Iterable[OnecGrossProfitDocumentRow],
    wb_sales_report_summary_rows: Iterable[WbSalesReportSummaryRow],
    onec_opiu_summary: OnecOpiuSummary | None,
    onec_document_dates: Mapping[tuple[str, str, date, str], date] | None,
    start_row: int,
) -> int:
    headers = [
        "Месяц",
        "WB количество",
        "1С количество",
        "Дельта количества",
        "Себестоимость 1С в WB-расчете",
        "Себестоимость по валовой прибыли 1С",
        "Дельта себестоимости",
        "% дельты себестоимости",
        "WB расходы МП",
        "1С расходы МП",
        "Дельта расходов МП",
        "% дельты расходов МП",
        "Комментарий",
    ]
    rows: list[tuple[object, ...]] = []
    total_wb_quantity = Decimal("0")
    total_onec_quantity = Decimal("0")
    total_wb_cogs = Decimal("0")
    total_onec_cogs = Decimal("0")
    total_wb_expenses = Decimal("0")
    total_onec_expenses = Decimal("0")
    wb_by_month = _wb_onec_report_product_totals_by_document_month(
        report.onec_report_product_rows,
        period_start=report.report_period_start,
        period_end=report.report_period_end,
        onec_document_dates=onec_document_dates,
    )
    onec_by_month = _matched_onec_gross_profit_totals_by_document_month(
        report,
        onec_gross_profit_rows,
        wb_sales_report_summary_rows,
        period_start=report.report_period_start,
        period_end=report.report_period_end,
    )
    grouped: dict[date, list[object]] = defaultdict(list)
    for row in report.rows:
        grouped[_row_month_start(row, report.report_period_start)].append(row)
    for month, month_rows in sorted(grouped.items()):
        totals = _totals(month_rows)
        month_key = month.strftime("%Y-%m")
        onec_month = (
            onec_opiu_summary.monthly_values.get(month_key, {})
            if onec_opiu_summary
            else {}
        )
        wb_document_totals = wb_by_month.get(month_key, {})
        onec_document_totals = onec_by_month.get(month_key, {})
        wb_quantity = wb_document_totals.get("quantity", Decimal("0"))
        onec_quantity = onec_document_totals.get("quantity")
        quantity_delta = _reconciliation_delta(wb_quantity, onec_quantity)
        wb_cogs = wb_document_totals.get("cogs", Decimal("0"))
        onec_cogs = onec_document_totals.get("cogs")
        wb_expenses = _wb_expenses(totals)
        onec_expenses = onec_month.get("rwb_total")
        cogs_delta = _reconciliation_delta(wb_cogs, onec_cogs)
        expenses_delta = _reconciliation_delta(wb_expenses, onec_expenses)
        total_wb_quantity += wb_quantity
        if onec_quantity is not None:
            total_onec_quantity += onec_quantity
        total_wb_cogs += wb_cogs
        total_wb_expenses += wb_expenses
        if onec_cogs is not None:
            total_onec_cogs += onec_cogs
        if onec_expenses is not None:
            total_onec_expenses += onec_expenses
        rows.append(
            (
                _month_label(month, report),
                wb_quantity,
                onec_quantity,
                quantity_delta,
                wb_cogs,
                onec_cogs,
                cogs_delta,
                _reconciliation_delta_rate(cogs_delta, onec_cogs),
                wb_expenses,
                onec_expenses,
                expenses_delta,
                _reconciliation_delta_rate(expenses_delta, onec_expenses),
                (
                    "Себестоимость и количество сверяются в одинаковой выборке "
                    "РВБ по дате документа 1С; расходы МП сверяются с ОПиУ."
                ),
            )
        )
    total_quantity_delta = _reconciliation_delta(total_wb_quantity, total_onec_quantity)
    total_cogs_delta = _reconciliation_delta(total_wb_cogs, total_onec_cogs)
    total_expenses_delta = _reconciliation_delta(
        total_wb_expenses,
        total_onec_expenses,
    )
    rows.append(
        (
            "Итого",
            total_wb_quantity,
            total_onec_quantity if onec_by_month else None,
            total_quantity_delta if onec_by_month else None,
            total_wb_cogs,
            total_onec_cogs if onec_by_month else None,
            total_cogs_delta if onec_by_month else None,
            _reconciliation_delta_rate(total_cogs_delta, total_onec_cogs)
            if onec_by_month
            else None,
            total_wb_expenses,
            total_onec_expenses if onec_opiu_summary else None,
            total_expenses_delta if onec_opiu_summary else None,
            _reconciliation_delta_rate(total_expenses_delta, total_onec_expenses)
            if onec_opiu_summary
            else None,
            "Итог по одинаковой выборке РВБ; ОПиУ показан только для расходов МП.",
        )
    )
    sheet.write(
        start_row - 1,
        0,
        "Главная сверка по месяцам: количество, себестоимость 1С и расходы МП",
        formats["section"],
    )
    _write_table_block(
        sheet,
        formats,
        start_row=start_row,
        start_col=0,
        headers=headers,
        rows=rows,
        money_columns={4, 5, 6, 8, 9, 10},
        percent_columns={7, 11},
    )
    return start_row + len(rows) + 3


def _combined_spp_status(rows: Iterable[object]) -> str:
    statuses = {
        getattr(row, "spp_source_status", "СПП не передается текущим источником")
        for row in rows
    }
    if any("cashbackDiscountSum" in status for status in statuses):
        return "СПП взят из WB sales-reports/list cashbackDiscountSum."
    return "СПП не передается текущим источником."


def _write_onec_report_products(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    onec_document_dates: Mapping[tuple[str, str, date, str], date] | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Товары по отчетам 1С")
    headers = [
        "Дата документа 1С",
        "Период продаж",
        "Тип документа 1С",
        "Кабинет WB",
        "Организация 1С",
        "nmId",
        "Артикул",
        "Баркод",
        "Номенклатура 1С",
        "Модель",
        "WB reportId в пакете",
        "Продажи, шт",
        "Возвраты, шт",
        "Итого, шт",
        "Реализация",
        "Возвраты",
        "Выручка нетто",
        "Комиссия WB",
        "Логистика",
        "Хранение",
        "Приемка",
        "WB Продвижение",
        "Удержания/штрафы/доплаты",
        "Эквайринг",
        "Себестоимость 1С",
        "Валовая прибыль 1С",
        "Прибыль после расходов WB",
        "Маржа после расходов WB",
        "Прибыль после расходов WB на шт",
        "НДС",
        "Налог с выручки",
        "Прибыль после налогов",
        "Маржа после налогов",
        "Прибыль после налогов на шт",
        "Статус данных",
        "Строк витрины",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    rows = report.onec_report_product_rows
    for idx, row in enumerate(rows, start=1):
        sheet.write(idx, 0, str(_resolved_onec_document_date(row, onec_document_dates)))
        sheet.write(idx, 1, f"{row.week_start} - {row.week_end}")
        sheet.write(idx, 2, row.document_label)
        sheet.write(idx, 3, _account_label(row.seller_account_id, account_labels))
        sheet.write(
            idx,
            4,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write(idx, 5, row.nm_id or "")
        sheet.write(idx, 6, row.vendor_code)
        sheet.write(idx, 7, row.barcode)
        sheet.write(idx, 8, row.onec_item_id or "")
        sheet.write(idx, 9, row.sales_model.value)
        sheet.write(idx, 10, ", ".join(row.wb_report_ids))
        sheet.write_number(idx, 11, float(row.sales_quantity))
        sheet.write_number(idx, 12, float(row.return_quantity))
        sheet.write_number(idx, 13, float(row.quantity))
        sheet.write_number(idx, 14, float(row.sales_amount), formats["money"])
        sheet.write_number(idx, 15, float(row.return_amount), formats["money"])
        sheet.write_number(idx, 16, float(row.net_revenue), formats["money"])
        sheet.write_number(idx, 17, float(row.wb_commission), formats["money"])
        sheet.write_number(idx, 18, float(row.logistics), formats["money"])
        sheet.write_number(idx, 19, float(row.storage), formats["money"])
        sheet.write_number(idx, 20, float(row.acceptance), formats["money"])
        sheet.write_number(idx, 21, float(row.wb_promotion), formats["money"])
        sheet.write_number(
            idx, 22, float(row.penalties_and_holdbacks), formats["money"]
        )
        sheet.write_number(idx, 23, float(row.acquiring), formats["money"])
        sheet.write_number(
            idx, 24, float(row.cogs_from_1c_with_extra_costs), formats["money"]
        )
        onec_gross_profit = row.net_revenue - row.cogs_from_1c_with_extra_costs
        sheet.write_number(idx, 25, float(onec_gross_profit), formats["money"])
        sheet.write_number(idx, 26, float(row.gross_profit), formats["money"])
        if row.margin is None:
            sheet.write(idx, 27, "")
        else:
            sheet.write_number(idx, 27, float(row.margin), formats["percent"])
        if row.profit_per_unit is None:
            sheet.write(idx, 28, "")
        else:
            sheet.write_number(idx, 28, float(row.profit_per_unit), formats["money"])
        sheet.write_number(idx, 29, float(row.vat_5_from_revenue), formats["money"])
        sheet.write_number(idx, 30, float(row.usn_1_from_revenue), formats["money"])
        sheet.write_number(idx, 31, float(row.profit_after_taxes), formats["money"])
        if row.margin_after_taxes is None:
            sheet.write(idx, 32, "")
        else:
            sheet.write_number(
                idx, 32, float(row.margin_after_taxes), formats["percent"]
            )
        if row.profit_after_taxes_per_unit is None:
            sheet.write(idx, 33, "")
        else:
            sheet.write_number(
                idx, 33, float(row.profit_after_taxes_per_unit), formats["money"]
            )
        sheet.write(idx, 34, _data_quality_label(row.data_quality_status))
        sheet.write_number(idx, 35, row.source_row_count)
    _add_table(sheet, headers, len(rows))
    sheet.set_column(0, 10, 20)
    sheet.set_column(11, 13, 12)
    sheet.set_column(14, 33, 16)
    sheet.set_column(34, 35, 20)


def _write_onec_gross_profit_documents(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    rows: list[OnecGrossProfitDocumentRow],
    *,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Валовая прибыль 1С")
    headers = [
        "Неделя",
        "Дата документа",
        "Организация 1С",
        "Контрагент 1С",
        "Тип документа",
        "Документ 1С",
        "Количество",
        "Выручка 1С",
        "НДС",
        "Себестоимость 1С",
        "Валовая прибыль 1С",
        "Строк регистра",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    for idx, row in enumerate(rows, start=1):
        sheet.write(idx, 0, str(row.week_start))
        sheet.write(idx, 1, str(row.document_date))
        sheet.write(
            idx,
            2,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write(idx, 3, row.counterparty_id)
        sheet.write(idx, 4, row.document_type)
        sheet.write(idx, 5, row.document_id)
        sheet.write_number(idx, 6, float(row.quantity))
        sheet.write_number(idx, 7, float(row.revenue), formats["money"])
        sheet.write_number(idx, 8, float(row.vat), formats["money"])
        sheet.write_number(idx, 9, float(row.cogs), formats["money"])
        sheet.write_number(idx, 10, float(row.gross_profit), formats["money"])
        sheet.write_number(idx, 11, row.source_row_count)
    _add_table(sheet, headers, len(rows))
    sheet.set_column(0, 5, 22)
    sheet.set_column(6, 11, 16)


def _write_marketplace_service_reconciliation(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    service_rows: list[OnecMarketplaceServiceRow],
    summary_rows: list[WbSalesReportSummaryRow],
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Сверка услуг WB")
    check_headers = [
        "Неделя",
        "Организация / кабинет",
        "Проверка",
        "1С УПД",
        "WB детализация",
        "WB сводный отчет",
        "Разница 1С - детализация",
        "Разница 1С - сводный",
        "Комментарий",
    ]
    headers = [
        "Неделя",
        "Организация / кабинет",
        "Статья",
        "1С УПД",
        "WB детализация",
        "WB сводный отчет",
        "Разница 1С - детализация",
        "Разница 1С - сводный",
        "Комментарий",
    ]
    onec_totals: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    detail_totals: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    summary_totals: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for row in service_rows:
        key = (
            str(row.week_start),
            _organization_label(row.organization_id, organization_labels),
            row.service_category,
        )
        onec_totals[key] += row.total
    for row in report.onec_report_reconciliation_rows:
        label = _account_label(row.seller_account_id, account_labels)
        week = str(row.week_start)
        _add_category_amount(
            detail_totals, week, label, "Комиссия WB", row.wb_commission
        )
        _add_category_amount(detail_totals, week, label, "Логистика", row.logistics)
        _add_category_amount(detail_totals, week, label, "Хранение", row.storage)
        _add_category_amount(detail_totals, week, label, "Приемка", row.acceptance)
        _add_category_amount(
            detail_totals, week, label, "WB Продвижение", row.wb_promotion
        )
        _add_category_amount(
            detail_totals,
            week,
            label,
            "Штрафы/доплаты",
            row.penalties_and_holdbacks,
        )
        _add_category_amount(detail_totals, week, label, "Эквайринг", row.acquiring)
    for row in summary_rows:
        label = _account_label(row.seller_account_id, account_labels)
        week = str(row.date_from)
        _add_category_amount(
            summary_totals, week, label, "Логистика", row.delivery_service_sum
        )
        _add_category_amount(
            summary_totals, week, label, "Хранение", row.paid_storage_sum
        )
        _add_category_amount(
            summary_totals, week, label, "Приемка", row.paid_acceptance_sum
        )
        _add_category_amount(
            summary_totals, week, label, "WB Продвижение", row.deduction_sum
        )
        _add_category_amount(
            summary_totals,
            week,
            label,
            "Штрафы/доплаты",
            row.penalty_sum - row.additional_payment_sum,
        )

    check_rows = _service_check_rows(onec_totals, detail_totals, summary_totals)
    sheet.write(0, 0, "Контрольный блок сверки услуг", formats["bold"])
    sheet.write_row(1, 0, check_headers, formats["header"])
    if check_rows:
        for idx, row in enumerate(check_rows, start=2):
            sheet.write(idx, 0, row["week"])
            sheet.write(idx, 1, row["label"])
            sheet.write(idx, 2, row["check"])
            sheet.write_number(idx, 3, float(row["onec"]), formats["money"])
            sheet.write_number(idx, 4, float(row["detail"]), formats["money"])
            summary_value = row["summary"]
            if summary_value is None:
                sheet.write(idx, 5, "")
                sheet.write(idx, 7, "")
            else:
                sheet.write_number(idx, 5, float(summary_value), formats["money"])
                sheet.write_number(
                    idx, 7, float(row["onec"] - summary_value), formats["money"]
                )
            sheet.write_number(
                idx, 6, float(row["onec"] - row["detail"]), formats["money"]
            )
            sheet.write(idx, 8, row["comment"])
    else:
        sheet.write_row(2, 0, ["planned_input", "Сверочные строки не загружены."])
    detail_header_row = max(len(check_rows), 1) + 4
    sheet.write(detail_header_row - 1, 0, "Детализация по статьям", formats["bold"])
    sheet.write_row(detail_header_row, 0, headers, formats["header"])

    keys = sorted(set(onec_totals) | set(detail_totals) | set(summary_totals))
    if not keys:
        sheet.write_row(
            detail_header_row + 1,
            0,
            ["planned_input", "Сверочные строки не загружены."],
        )
        _add_table_at(sheet, headers, 1, start_row=detail_header_row)
        sheet.set_column(0, len(headers) - 1, 22)
        return
    for idx, key in enumerate(keys, start=detail_header_row + 1):
        onec_value = onec_totals.get(key, Decimal("0"))
        detail_value = detail_totals.get(key, Decimal("0"))
        summary_value = summary_totals.get(key)
        sheet.write(idx, 0, key[0])
        sheet.write(idx, 1, key[1])
        sheet.write(idx, 2, key[2])
        sheet.write_number(idx, 3, float(onec_value), formats["money"])
        sheet.write_number(idx, 4, float(detail_value), formats["money"])
        if summary_value is None:
            sheet.write(idx, 5, "")
            sheet.write(idx, 7, "")
        else:
            sheet.write_number(idx, 5, float(summary_value), formats["money"])
            sheet.write_number(
                idx, 7, float(onec_value - summary_value), formats["money"]
            )
        sheet.write_number(idx, 6, float(onec_value - detail_value), formats["money"])
        sheet.write(idx, 8, _service_reconciliation_comment(key[2], summary_value))
    _add_table_at(sheet, headers, len(keys), start_row=detail_header_row)
    sheet.set_column(0, len(headers) - 1, 22)


def _write_onec_service_breakdown(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    service_rows: list[OnecMarketplaceServiceRow],
    *,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Расшифровка услуг 1С")
    headers = [
        "Неделя",
        "Организация 1С",
        "Контрагент 1С",
        "Дата УПД",
        "Номер УПД",
        "Входящий номер",
        "Дата входящего",
        "Комментарий документа",
        "Услуга",
        "Категория",
        "Сумма",
        "НДС",
        "Итого",
        "Сумма включает НДС",
        "НДС включать в стоимость",
        "Расходы включать в себестоимость",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    for idx, row in enumerate(service_rows, start=1):
        sheet.write(idx, 0, str(row.week_start))
        sheet.write(
            idx,
            1,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write(idx, 2, row.counterparty_id)
        sheet.write(idx, 3, str(row.document_date))
        sheet.write(idx, 4, row.document_number)
        sheet.write(idx, 5, row.input_number)
        sheet.write(idx, 6, str(row.input_date) if row.input_date else "")
        sheet.write(idx, 7, row.document_comment)
        sheet.write(idx, 8, row.service_name)
        sheet.write(idx, 9, row.service_category)
        sheet.write_number(idx, 10, float(row.amount), formats["money"])
        sheet.write_number(idx, 11, float(row.vat), formats["money"])
        sheet.write_number(idx, 12, float(row.total), formats["money"])
        sheet.write(idx, 13, _yes_no(row.amount_includes_vat))
        sheet.write(idx, 14, _yes_no(row.vat_included_in_cost))
        sheet.write(idx, 15, _yes_no(row.include_expenses_in_cost))
    if not service_rows:
        sheet.write_row(1, 0, ["planned_input", "УПД услуг 1С не загружены."])
    _add_table(sheet, headers, len(service_rows) or 1)
    sheet.set_column(0, 2, 22)
    sheet.set_column(3, 6, 16)
    sheet.set_column(7, 9, 30)
    sheet.set_column(10, 15, 18)


def _write_expense_allocation(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Распределение расходов")
    headers = [
        "Неделя",
        "Период по",
        "Тип отчета",
        "Недельный отчет WB",
        "Кабинет WB",
        "Организация 1С",
        "Статья",
        "nmId",
        "Артикул WB",
        "Баркод",
        "Номенклатура 1С",
        "База API по товару",
        "База распределения товара",
        "Сумма API по неделе",
        "Сумма фин. отчета WB",
        "Коэффициент",
        "Распределено",
        "Метод",
        "Статус",
        "Строк детализации",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    rows = report.expense_allocation_rows
    if not rows:
        sheet.write_row(
            1,
            0,
            ["planned_input", "Расходы для распределения не загружены."],
        )
        _add_table(sheet, headers, 1)
        sheet.set_column(0, len(headers) - 1, 20)
        return
    for idx, row in enumerate(rows, start=1):
        sheet.write(idx, 0, str(row.week_start))
        sheet.write(idx, 1, str(row.week_end))
        sheet.write(idx, 2, row.document_label)
        sheet.write(idx, 3, ", ".join(row.wb_report_ids) or "Нет свода WB")
        sheet.write(idx, 4, _account_label(row.seller_account_id, account_labels))
        sheet.write(
            idx,
            5,
            _organization_label(row.organization_id, organization_labels),
        )
        sheet.write(idx, 6, row.expense_category)
        sheet.write(idx, 7, row.nm_id or "")
        sheet.write(idx, 8, row.vendor_code)
        sheet.write(idx, 9, row.barcode)
        sheet.write(idx, 10, row.onec_item_id or "")
        sheet.write_number(idx, 11, float(row.api_base_amount), formats["money"])
        sheet.write_number(
            idx, 12, float(row.distribution_base_amount), formats["money"]
        )
        sheet.write_number(idx, 13, float(row.api_total_amount), formats["money"])
        if row.control_amount is None:
            sheet.write(idx, 14, "")
        else:
            sheet.write_number(idx, 14, float(row.control_amount), formats["money"])
        if row.scaling_coefficient is None:
            sheet.write(idx, 15, "")
        else:
            sheet.write_number(idx, 15, float(row.scaling_coefficient))
        sheet.write_number(idx, 16, float(row.allocated_amount), formats["money"])
        sheet.write(idx, 17, row.distribution_method)
        sheet.write(idx, 18, row.allocation_status)
        sheet.write_number(idx, 19, row.source_row_count)
    _add_table(sheet, headers, len(rows))
    sheet.set_column(0, 6, 20)
    sheet.set_column(7, 10, 18)
    sheet.set_column(11, 16, 18)
    sheet.set_column(17, 18, 36)
    sheet.set_column(19, 19, 16)


def _write_expenses(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Расходы WB")
    cost_names: dict[tuple[str, str], str] = {}
    client_rows = _client_unit_rows(report.rows, cost_names)
    structure_rows = _expense_structure_rows(client_rows, report)
    month_headers = [_short_month_label(month) for month in _report_month_keys(report)]
    change_headers = [
        f"{current} к {previous}"
        for previous, current in zip(month_headers, month_headers[1:], strict=False)
    ]
    structure_headers = [
        "Статья",
        "Сумма",
        "% от выручки",
        *month_headers,
        *change_headers,
    ]
    sheet.write(0, 0, "Структура расходов", formats["section"])
    _write_table_block(
        sheet,
        formats,
        start_row=1,
        start_col=0,
        headers=structure_headers,
        rows=structure_rows,
        money_columns=set(range(1, len(structure_headers))) - {2},
        percent_columns={2},
    )
    detail_start = 1 + len(structure_rows) + 4
    sheet.write(detail_start - 1, 0, "Детализация по строкам", formats["section"])
    headers = [
        "Неделя",
        "Кабинет WB",
        "Комиссия",
        "Логистика",
        "Хранение",
        "Приемка",
        "WB Продвижение",
        "Удержания/штрафы/доплаты",
        "Эквайринг",
        "Расходы WB",
        "% от выручки",
        "Реклама",
    ]
    sheet.write_row(detail_start, 0, headers, formats["header"])
    for offset, row in enumerate(client_rows, start=1):
        idx = detail_start + offset
        sheet.write(
            idx,
            0,
            str(_display_week_start(row.week_start, report.report_period_start)),
        )
        sheet.write(idx, 1, _account_label(row.seller_account_id, account_labels))
        sheet.write_number(idx, 2, float(row.wb_commission), formats["money"])
        sheet.write_number(idx, 3, float(row.logistics), formats["money"])
        sheet.write_number(idx, 4, float(row.storage), formats["money"])
        sheet.write_number(idx, 5, float(row.acceptance), formats["money"])
        sheet.write_number(idx, 6, float(row.wb_promotion), formats["money"])
        sheet.write_number(idx, 7, float(row.penalties_and_holdbacks), formats["money"])
        sheet.write_number(idx, 8, float(row.acquiring), formats["money"])
        row_expenses = (
            row.wb_commission
            + row.logistics
            + row.storage
            + row.acceptance
            + row.wb_promotion
            + row.penalties_and_holdbacks
            + row.acquiring
        )
        sheet.write_number(idx, 9, float(row_expenses), formats["money"])
        expense_share = _safe_margin(row_expenses, row.net_revenue)
        if expense_share is None:
            sheet.write(idx, 10, "")
        else:
            sheet.write_number(idx, 10, float(expense_share), formats["percent"])
        sheet.write(idx, 11, _advertising_scope_label(row.advertising_scope))
    _add_table_at(sheet, headers, len(client_rows), start_row=detail_start)
    sheet.set_column(0, 11, 18)


def _write_returns(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Возвраты")
    headers = [
        "Неделя",
        "Организация 1С",
        "Кабинет WB",
        "Товар",
        "nmId WB",
        "Артикул WB",
        "Артикул 1С",
        "Баркод",
        "Продажи, шт",
        "Возвраты, шт",
        "% возвратов",
        "Сумма возвратов",
        "Маржинальный доход WB после налогов",
        "Маржинальный доход WB после налогов на шт",
        "Статус данных",
        "Главная причина",
        "Причина возврата",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    cost_names = _cost_name_lookup(cost_snapshots)
    cost_articles = _cost_article_lookup(cost_snapshots)
    mapping_articles = _mapping_article_lookup(sku_mappings)
    return_rows = [
        row
        for row in _client_unit_rows(report.rows, cost_names)
        if row.return_quantity > 0
    ]
    return_rows = sorted(
        return_rows,
        key=lambda row: (
            row.profit_after_taxes,
            row.profit_after_taxes_per_unit
            if row.profit_after_taxes_per_unit is not None
            else Decimal("0"),
            -row.return_quantity,
        ),
    )
    for idx, row in enumerate(return_rows, start=1):
        sheet.write(idx, 0, str(row.week_start))
        sheet.write(
            idx, 1, _organization_label(row.organization_id, organization_labels)
        )
        sheet.write(idx, 2, _account_label(row.seller_account_id, account_labels))
        sheet.write(idx, 3, _product_label(row, cost_names))
        sheet.write(idx, 4, row.nm_id if _is_real_nm_id(row.nm_id) else "")
        sheet.write(idx, 5, row.vendor_code)
        sheet.write(idx, 6, _onec_article_label(row, cost_articles, mapping_articles))
        sheet.write(idx, 7, row.barcode)
        sheet.write_number(idx, 8, float(row.sales_quantity))
        sheet.write_number(idx, 9, float(row.return_quantity))
        if row.return_rate_by_quantity is None:
            sheet.write(idx, 10, "")
        else:
            sheet.write_number(
                idx, 10, float(row.return_rate_by_quantity), formats["percent"]
            )
        sheet.write_number(idx, 11, float(row.return_amount), formats["money"])
        sheet.write_number(idx, 12, float(row.profit_after_taxes), formats["money"])
        if row.profit_after_taxes_per_unit is None:
            sheet.write(idx, 13, "")
        else:
            sheet.write_number(
                idx, 13, float(row.profit_after_taxes_per_unit), formats["money"]
            )
        sheet.write(idx, 14, _data_quality_label(row.data_quality_status))
        sheet.write(idx, 15, _loss_reason(row))
        sheet.write(
            idx,
            16,
            "Причина возврата не передается текущими источниками",
        )
    _add_table(sheet, headers, len(return_rows))
    sheet.freeze_panes(1, 4)
    sheet.set_column(0, 2, 18)
    sheet.set_column(3, 3, 34)
    sheet.set_column(4, 10, 16)
    sheet.set_column(11, 13, 18)
    sheet.set_column(14, 16, 34)


def _write_lost_sales(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    stock_history_dir: Path | None = None,
    onec_stock_dir: Path | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Упущенные продажи")
    cost_names = _cost_name_lookup(cost_snapshots)
    cost_articles = _cost_article_lookup(cost_snapshots)
    mapping_articles = _mapping_article_lookup(sku_mappings)
    stock_history = _load_stock_history(stock_history_dir, report)
    onec_stock = _load_onec_stock_by_warehouse(
        onec_stock_dir,
        sku_mappings=sku_mappings,
    )
    rows = _lost_sales_rows(
        report,
        cost_names=cost_names,
        cost_articles=cost_articles,
        mapping_articles=mapping_articles,
        sku_mappings=sku_mappings,
        stock_history=stock_history,
        onec_stock=onec_stock,
        account_labels=account_labels,
    )

    sheet.write(0, 0, "Упущенные продажи: предварительная оценка", formats["title"])
    sheet.set_row(1, 18)
    sheet.set_row(2, 18)
    sheet.write(
        1,
        0,
        (
            "Методика: дни с нулевым остатком WB * среднедневные продажи "
            "в дни наличия * средняя выручка/прибыль на проданную единицу. "
            "Остаток 1С по складам показывает, есть ли товар у продавца для "
            "перемещения на WB. "
            "Это управленческий рейтинг для проверки пополнения, а не "
            "финальный прогноз спроса."
        ),
    )
    sheet.write(
        2,
        0,
        (
            "Ограничение: расчет строится по stockType=wb и требует сверки с "
            "1С остатками комиссионера, если товар числится у комиссионера, "
            "но отсутствует на складах WB."
        ),
    )

    kpi_rows = [
        ("Источник WB stock-history", stock_history.get("source_label", "")),
        (
            "Период stock-history",
            (
                f"{stock_history.get('period_start', '')} - "
                f"{stock_history.get('period_end', '')}"
            ).strip(" -"),
        ),
        ("Строк CSV", stock_history.get("csv_rows", 0)),
        ("Дневных колонок", stock_history.get("date_columns", 0)),
        ("Источник 1С остатков", onec_stock.get("source_label", "")),
        ("Строк 1С остатков", onec_stock.get("row_count", 0)),
        ("Товаров с днями без остатка", sum(1 for row in rows if row[7] > 0)),
    ]
    _write_kpi_table(sheet, formats, start_row=4, start_col=0, rows=kpi_rows)

    headers = [
        "Кабинет WB",
        "Товар",
        "nmId WB",
        "Артикул WB",
        "Артикул 1С",
        "Баркод",
        "Дней в периоде",
        "Дней без остатка WB",
        "Дней критического остатка",
        "Остаток 1С на складах, шт",
        "Склады 1С с остатком",
        "Продажи, шт",
        "Среднедневные продажи в дни наличия",
        "Потенциально упущено, шт",
        "Потенциально упущенная выручка",
        "Потенциально упущенная прибыль",
        "Прибыль/продажа после налогов",
        "Вывод",
        "Статус источника",
    ]
    table_start = 13
    _write_table_block(
        sheet,
        formats,
        start_row=table_start,
        start_col=0,
        headers=headers,
        rows=rows,
        money_columns={14, 15, 16},
    )
    if not rows:
        sheet.write(
            table_start + 1,
            0,
            "Нет данных для предварительной оценки: stock-history WB не найден.",
            formats["warn"],
        )
    if rows:
        first = table_start + 1
        last = table_start + len(rows)
        sheet.conditional_format(
            first,
            15,
            last,
            15,
            {"type": "cell", "criteria": ">", "value": 0, "format": formats["good"]},
        )
        sheet.conditional_format(
            first,
            15,
            last,
            15,
            {"type": "cell", "criteria": "<", "value": 0, "format": formats["bad"]},
        )
        sheet.conditional_format(
            first,
            7,
            last,
            7,
            {"type": "cell", "criteria": ">", "value": 0, "format": formats["warn"]},
        )
    sheet.freeze_panes(table_start + 1, 2)
    sheet.set_column(0, 0, 20)
    sheet.set_column(1, 1, 38)
    sheet.set_column(2, 5, 16)
    sheet.set_column(6, 12, 18)
    sheet.set_column(13, 16, 20)
    sheet.set_column(17, 18, 34)


def _load_stock_history(
    stock_history_dir: Path | None,
    report: UnitEconomicsReport,
) -> dict[str, object]:
    if stock_history_dir is None:
        return {
            "status": "not_loaded",
            "source_label": "WB stock-history не передан в сборку Excel",
            "products": {},
        }
    manifest_path = stock_history_dir / "manifest.json"
    if not manifest_path.exists():
        return {
            "status": "not_loaded",
            "source_label": f"manifest.json не найден: {stock_history_dir}",
            "products": {},
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    products: dict[tuple[str, int | None, str], dict[str, object]] = {}
    csv_rows = 0
    date_columns_count = 0
    for item in manifest.get("results", []):
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        seller_account_id = str(item.get("seller_account_id") or "")
        output_file = str(item.get("output_file") or "")
        if not seller_account_id or not output_file:
            continue
        zip_path = stock_history_dir / output_file
        if not zip_path.exists():
            continue
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                text = archive.read(name).decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                if not reader.fieldnames:
                    continue
                date_headers = [
                    header
                    for header in reader.fieldnames
                    if _parse_stock_history_date(header) is not None
                ]
                date_columns_count = max(date_columns_count, len(date_headers))
                for csv_row in reader:
                    csv_rows += 1
                    nm_id = _int_or_none(csv_row.get("NmID"))
                    vendor_code = str(csv_row.get("VendorCode") or "").strip()
                    key = _stock_product_key(seller_account_id, nm_id, vendor_code)
                    bucket = products.setdefault(
                        key,
                        {
                            "seller_account_id": seller_account_id,
                            "nm_id": nm_id,
                            "vendor_code": vendor_code,
                            "name": str(csv_row.get("Name") or "").strip(),
                            "stock_by_date": defaultdict(Decimal),
                        },
                    )
                    stock_by_date = bucket["stock_by_date"]
                    if not isinstance(stock_by_date, defaultdict):
                        continue
                    for header in date_headers:
                        current_date = _parse_stock_history_date(header)
                        if current_date is None:
                            continue
                        if not (
                            report.report_period_start
                            <= current_date
                            <= report.report_period_end
                        ):
                            continue
                        stock_by_date[current_date] += _decimal_from_stock_cell(
                            csv_row.get(header)
                        )
    return {
        "status": "ok" if products else "empty",
        "source_label": f"WB STOCK_HISTORY_DAILY_CSV: {stock_history_dir.name}",
        "path": str(stock_history_dir),
        "period_start": manifest.get("period_start"),
        "period_end": manifest.get("period_end"),
        "csv_rows": csv_rows,
        "date_columns": date_columns_count,
        "products": products,
    }


def _load_onec_stock_by_warehouse(
    onec_stock_dir: Path | None,
    *,
    sku_mappings: Iterable[SkuMapping] = (),
) -> dict[str, object]:
    if onec_stock_dir is None:
        return {
            "source_label": "1С остатки не переданы в сборку Excel",
            "row_count": 0,
            "products": {},
        }
    manifest_path = onec_stock_dir / "manifest.json"
    if not manifest_path.exists():
        return {
            "source_label": f"manifest.json не найден: {onec_stock_dir}",
            "row_count": 0,
            "products": {},
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_label = f"1С stock_by_warehouse не найден: {onec_stock_dir.name}"
    row_count = 0
    for item in manifest.get("results", []):
        if (
            isinstance(item, dict)
            and item.get("sample_id") == "stock_by_warehouse"
            and item.get("ok") is True
        ):
            source_label = f"1С stock_by_warehouse: {onec_stock_dir.name}"
            row_count = int(item.get("row_count") or 0)
            break
    products: dict[tuple[str, ...], dict[str, object]] = {}
    warehouse_names = _load_onec_warehouse_names(onec_stock_dir)
    raw_path = onec_stock_dir / "stock_by_warehouse.raw.json"
    if raw_path.exists():
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for row in extract_odata_rows(payload):
                if isinstance(row, Mapping):
                    _add_onec_stock_record(products, row, warehouse_names)
    _add_onec_stock_aliases(products, sku_mappings)
    return {
        "source_label": source_label,
        "row_count": row_count,
        "products": products,
    }


def _add_onec_stock_record(
    products: dict[tuple[str, ...], dict[str, object]],
    row: Mapping[str, object],
    warehouse_names: Mapping[str, str],
) -> None:
    record_set = row.get("RecordSet")
    if isinstance(record_set, list):
        parent = {key: value for key, value in row.items() if key != "RecordSet"}
        for record in record_set:
            if isinstance(record, Mapping):
                merged = dict(parent)
                merged.update(record)
                _add_onec_stock_record(products, merged, warehouse_names)
        return

    if not _truthy_1c(row.get("Active"), default=True):
        return
    quantity = _decimal_from_stock_cell(row.get("Количество"))
    if quantity <= 0:
        return
    organization_id = _text_value(row.get("Организация_Key"))
    onec_item_id = _text_value(row.get("Номенклатура_Key"))
    characteristic = _text_value(row.get("Характеристика_Key"))
    if not organization_id or not onec_item_id:
        return

    warehouse = _onec_warehouse_label(row, warehouse_names)
    keys = [("item", organization_id, onec_item_id, characteristic)]
    if characteristic:
        keys.append(("item", organization_id, onec_item_id, ""))
    article = _normalize_stock_code(row.get("Артикул") or row.get("article"))
    barcode = _text_value(row.get("Штрихкод") or row.get("barcode"))
    if article:
        keys.append(("article", organization_id, article))
    if barcode:
        keys.append(("barcode", organization_id, barcode))
    for key in keys:
        bucket = products.setdefault(
            key,
            {"quantity": Decimal("0"), "warehouses": defaultdict(Decimal)},
        )
        bucket["quantity"] = _decimal_from_stock_cell(bucket.get("quantity")) + quantity
        warehouses = bucket.get("warehouses")
        if isinstance(warehouses, defaultdict):
            warehouses[warehouse] += quantity


def _add_onec_stock_aliases(
    products: dict[tuple[str, ...], dict[str, object]],
    sku_mappings: Iterable[SkuMapping],
) -> None:
    for mapping in sku_mappings:
        if not mapping.organization_id or not mapping.onec_item_id:
            continue
        item_key = (
            "item",
            mapping.organization_id,
            mapping.onec_item_id,
            mapping.onec_characteristic or "",
        )
        bucket = products.get(item_key) or products.get(
            ("item", mapping.organization_id, mapping.onec_item_id, "")
        )
        if bucket is None:
            continue
        article = _normalize_stock_code(mapping.onec_article)
        barcode = _text_value(mapping.barcode)
        if article:
            products.setdefault(("article", mapping.organization_id, article), bucket)
        if barcode:
            products.setdefault(("barcode", mapping.organization_id, barcode), bucket)


def _mapping_by_product_lookup(
    sku_mappings: Iterable[SkuMapping],
) -> dict[tuple[str, int | None, str], SkuMapping]:
    result: dict[tuple[str, int | None, str], SkuMapping] = {}
    for mapping in sku_mappings:
        key = _stock_product_key(
            mapping.seller_account_id,
            mapping.nm_id,
            mapping.vendor_code,
        )
        result.setdefault(key, mapping)
    return result


def _find_onec_stock_product(
    products: Mapping[object, object],
    row: object,
    *,
    cost_articles: Mapping[tuple[str, str], str],
    mapping_articles: Mapping[tuple[str, str], str],
    mapping_by_product: Mapping[tuple[str, int | None, str], SkuMapping],
) -> Mapping[str, object] | None:
    organization_id = getattr(row, "organization_id", "")
    onec_item_id = getattr(row, "onec_item_id", None) or ""
    keys: list[tuple[str, ...]] = []
    if onec_item_id:
        mapping = mapping_by_product.get(
            _stock_product_key(
                getattr(row, "seller_account_id", ""),
                getattr(row, "nm_id", None),
                getattr(row, "vendor_code", ""),
            )
        )
        characteristic = mapping.onec_characteristic if mapping else ""
        keys.append(("item", organization_id, str(onec_item_id), characteristic))
        keys.append(("item", organization_id, str(onec_item_id), ""))
        article = cost_articles.get((organization_id, str(onec_item_id))) or (
            mapping_articles.get((organization_id, str(onec_item_id))) or ""
        )
        if article:
            keys.append(("article", organization_id, _normalize_stock_code(article)))
    barcode = _text_value(getattr(row, "barcode", ""))
    if barcode:
        keys.append(("barcode", organization_id, barcode))
    vendor_code = _normalize_stock_code(getattr(row, "vendor_code", ""))
    if vendor_code:
        keys.append(("article", organization_id, vendor_code))

    for key in keys:
        candidate = products.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _warehouse_summary(warehouses: object) -> str:
    if not isinstance(warehouses, Mapping):
        return ""
    parts = [
        f"{name}: {_format_quantity(quantity)}"
        for name, quantity in sorted(warehouses.items(), key=lambda item: str(item[0]))
        if _decimal_from_stock_cell(quantity) > 0
    ]
    return "; ".join(parts[:5])


def _load_onec_warehouse_names(onec_stock_dir: Path) -> dict[str, str]:
    candidates = _onec_warehouse_dictionary_candidates(onec_stock_dir)
    result: dict[str, str] = {}
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for row in extract_odata_rows(payload):
            if not isinstance(row, Mapping):
                continue
            warehouse_id = _first_text_value(
                row,
                (
                    "Ref_Key",
                    "Ссылка_Key",
                    "Склад_Key",
                    "СтруктурнаяЕдиница_Key",
                    "Warehouse_Key",
                    "warehouse_id",
                ),
            )
            warehouse_name = _first_text_value(
                row,
                (
                    "Description",
                    "Наименование",
                    "НаименованиеПолное",
                    "Name",
                    "name",
                ),
            )
            if warehouse_id and warehouse_name:
                result.setdefault(warehouse_id, warehouse_name)
    return result


def _onec_warehouse_dictionary_candidates(onec_stock_dir: Path) -> list[Path]:
    candidates: dict[Path, float] = {}
    direct_dirs = [onec_stock_dir, onec_stock_dir.parent]
    for directory in direct_dirs:
        for file_name in ONEC_WAREHOUSE_DICTIONARY_FILES:
            path = directory / file_name
            if path.exists():
                candidates[path] = path.stat().st_mtime

    data_root = onec_stock_dir
    for parent in (onec_stock_dir, *onec_stock_dir.parents):
        if parent.name == "data":
            data_root = parent
            break
    for base_name in ("onec_samples", "onec_gross_profit_samples"):
        base = data_root / base_name
        if not base.exists():
            continue
        for file_name in ONEC_WAREHOUSE_DICTIONARY_FILES:
            for path in base.glob(f"*/{file_name}"):
                if path.exists():
                    candidates[path] = path.stat().st_mtime

    return [
        path
        for path, _mtime in sorted(
            candidates.items(),
            key=lambda item: (item[1], str(item[0])),
            reverse=True,
        )
    ]


def _onec_warehouse_label(
    row: Mapping[str, object],
    warehouse_names: Mapping[str, str],
) -> str:
    for key in ("Склад", "Warehouse", "warehouse"):
        value = _text_value(row.get(key))
        if value and not _looks_like_uuid(value):
            return value
        if value and value in warehouse_names:
            return warehouse_names[value]

    for key in (
        "Склад",
        "Склад_Key",
        "СтруктурнаяЕдиница_Key",
        "Warehouse",
        "Warehouse_Key",
        "warehouse",
        "warehouse_id",
    ):
        value = _text_value(row.get(key))
        if value:
            mapped = warehouse_names.get(value)
            if mapped:
                return mapped
            return value
    return "Склад 1С не указан"


def _first_text_value(row: Mapping[str, object], keys: Iterable[str]) -> str:
    for key in keys:
        value = _text_value(row.get(key))
        if value:
            return value
    return ""


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _truthy_1c(value: object, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "ложь"}


def _text_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _format_quantity(value: object) -> str:
    quantity = _decimal_from_stock_cell(value)
    if quantity == quantity.to_integral_value():
        return str(int(quantity))
    return str(quantity.normalize())


def _lost_sales_rows(
    report: UnitEconomicsReport,
    *,
    cost_names: Mapping[tuple[str, str], str],
    cost_articles: Mapping[tuple[str, str], str],
    mapping_articles: Mapping[tuple[str, str], str],
    sku_mappings: Iterable[SkuMapping],
    stock_history: Mapping[str, object],
    onec_stock: Mapping[str, object],
    account_labels: Mapping[str, str] | None,
) -> list[tuple[object, ...]]:
    products = stock_history.get("products")
    if not isinstance(products, dict) or not products:
        return []
    onec_stock_products = onec_stock.get("products")
    if not isinstance(onec_stock_products, Mapping):
        onec_stock_products = {}
    mapping_by_product = _mapping_by_product_lookup(sku_mappings)
    grouped: dict[tuple[str, int | None, str], list[object]] = defaultdict(list)
    for row in _client_unit_rows(report.rows, cost_names):
        key = _stock_product_key(row.seller_account_id, row.nm_id, row.vendor_code)
        grouped[key].append(row)

    period_days = (report.report_period_end - report.report_period_start).days + 1
    result: list[tuple[object, ...]] = []
    for key, unit_rows in grouped.items():
        stock_product = _find_stock_product(products, key)
        if stock_product is None:
            continue
        stock_by_date = stock_product.get("stock_by_date", {})
        if not isinstance(stock_by_date, Mapping):
            continue
        stock_dates = [
            date.fromordinal(day)
            for day in range(
                report.report_period_start.toordinal(),
                report.report_period_end.toordinal() + 1,
            )
        ]
        stock_values = [stock_by_date.get(item, Decimal("0")) for item in stock_dates]
        zero_stock_days = sum(1 for value in stock_values if value <= 0)
        totals = _totals(unit_rows)
        sales_quantity = totals["sales_quantity"]
        net_revenue = totals["net_revenue"]
        profit_after_taxes = totals["profit_after_taxes"]
        in_stock_days = max(0, len(stock_values) - zero_stock_days)
        avg_daily_sales_in_stock = (
            sales_quantity / Decimal(in_stock_days)
            if in_stock_days > 0 and sales_quantity > 0
            else None
        )
        avg_daily_sales = avg_daily_sales_in_stock or (
            sales_quantity / Decimal(period_days)
            if period_days > 0 and sales_quantity > 0
            else Decimal("0")
        )
        critical_stock_days = sum(
            1
            for value in stock_values
            if avg_daily_sales > 0 and Decimal("0") < value <= avg_daily_sales
        )
        lost_units = (
            avg_daily_sales * Decimal(zero_stock_days)
            if sales_quantity > 0 and zero_stock_days > 0
            else Decimal("0")
        )
        revenue_per_sale = _safe_margin(net_revenue, sales_quantity) or Decimal("0")
        profit_per_sale = _safe_margin(profit_after_taxes, sales_quantity) or Decimal(
            "0"
        )
        lost_revenue = lost_units * revenue_per_sale
        lost_profit = lost_units * profit_per_sale
        first = unit_rows[0]
        own_stock = _find_onec_stock_product(
            onec_stock_products,
            first,
            cost_articles=cost_articles,
            mapping_articles=mapping_articles,
            mapping_by_product=mapping_by_product,
        )
        onec_stock_quantity = (
            own_stock.get("quantity", Decimal("0"))
            if isinstance(own_stock, Mapping)
            else Decimal("0")
        )
        onec_stock_warehouses = (
            _warehouse_summary(own_stock.get("warehouses", {}))
            if isinstance(own_stock, Mapping)
            else ""
        )
        result.append(
            (
                _account_label(first.seller_account_id, account_labels),
                _product_label(first, cost_names),
                first.nm_id if _is_real_nm_id(first.nm_id) else "",
                first.vendor_code,
                _onec_article_label(first, cost_articles, mapping_articles),
                first.barcode,
                period_days,
                zero_stock_days,
                critical_stock_days,
                onec_stock_quantity,
                onec_stock_warehouses,
                sales_quantity,
                avg_daily_sales,
                lost_units,
                lost_revenue,
                lost_profit,
                profit_per_sale,
                _lost_sales_conclusion(
                    zero_stock_days=zero_stock_days,
                    sales_quantity=sales_quantity,
                    lost_profit=lost_profit,
                    onec_stock_quantity=onec_stock_quantity,
                ),
                _lost_sales_source_status(onec_stock_quantity),
            )
        )
    return sorted(
        (row for row in result if row[7] > 0 or row[8] > 0),
        key=lambda row: (row[15], row[14], row[13]),
        reverse=True,
    )


def _stock_product_key(
    seller_account_id: str,
    nm_id: object,
    vendor_code: object,
) -> tuple[str, int | None, str]:
    return (
        seller_account_id,
        nm_id if isinstance(nm_id, int) and nm_id > 0 else None,
        _normalize_stock_code(vendor_code),
    )


def _find_stock_product(
    products: Mapping[object, object],
    key: tuple[str, int | None, str],
) -> Mapping[str, object] | None:
    direct = products.get(key)
    if isinstance(direct, Mapping):
        return direct
    seller_account_id, nm_id, vendor_code = key
    for candidate_key, candidate in products.items():
        if not isinstance(candidate_key, tuple) or not isinstance(candidate, Mapping):
            continue
        candidate_seller, candidate_nm, candidate_vendor = candidate_key
        if candidate_seller != seller_account_id:
            continue
        if nm_id is not None and candidate_nm == nm_id:
            return candidate
        if vendor_code and candidate_vendor == vendor_code:
            return candidate
    return None


def _normalize_stock_code(value: object) -> str:
    return str(value or "").strip().lower()


def _parse_stock_history_date(value: object) -> date | None:
    parts = str(value or "").split(".")
    if len(parts) != 3:
        return None
    try:
        day, month, year = (int(part) for part in parts)
        return date(year, month, day)
    except ValueError:
        return None


def _int_or_none(value: object) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _decimal_from_stock_cell(value: object) -> Decimal:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except Exception:
        return Decimal("0")


def _lost_sales_conclusion(
    *,
    zero_stock_days: int,
    sales_quantity: Decimal,
    lost_profit: Decimal,
    onec_stock_quantity: Decimal = Decimal("0"),
) -> str:
    if zero_stock_days <= 0:
        return "Остаток был в наличии"
    if sales_quantity <= 0:
        return "Нет продаж для оценки спроса"
    if onec_stock_quantity > 0 and lost_profit > 0:
        return "Переместить собственный остаток на WB"
    if lost_profit > 0:
        return "Проверить пополнение на WB"
    if lost_profit < 0:
        return "Не пополнять без исправления экономики"
    return "Проверить спрос и остатки"


def _lost_sales_source_status(onec_stock_quantity: Decimal) -> str:
    if onec_stock_quantity > 0:
        return "Предварительно: WB stock-history + продажи периода + 1С остатки"
    return "Предварительно: WB stock-history + продажи периода"


def _write_costs(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    costs: list[OnecUnfCostSnapshot],
    *,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Себестоимость 1С")
    headers = [
        "Организация 1С",
        "Номенклатура 1С",
        "Артикул 1С",
        "Баркод",
        "Наименование",
        "Характеристика",
        "Себестоимость",
        "Допрасходы отдельно",
        "Валюта",
        "Метод",
        "Действует с",
        "Источник",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    for idx, cost in enumerate(costs, start=1):
        sheet.write(
            idx,
            0,
            _organization_label(cost.organization_id, organization_labels),
        )
        sheet.write(idx, 1, cost.onec_item_id)
        sheet.write(idx, 2, cost.article)
        sheet.write(idx, 3, cost.barcode)
        sheet.write(idx, 4, cost.name)
        sheet.write(idx, 5, cost.characteristic)
        sheet.write_number(idx, 6, float(cost.cost_value), formats["money"])
        sheet.write_number(idx, 7, float(cost.extra_costs_value), formats["money"])
        sheet.write(idx, 8, cost.cost_currency)
        sheet.write(idx, 9, cost.cost_method)
        sheet.write(idx, 10, str(cost.effective_from))
        sheet.write(idx, 11, cost.source_document)
    if not costs:
        sheet.write_row(1, 0, ["planned_input", "Себестоимость 1С не загружена."])
    _add_table(sheet, headers, len(costs) or 1)
    sheet.set_column(0, 11, 18)


def _write_mappings(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    mappings: list[SkuMapping],
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Маппинг")
    headers = [
        "Кабинет WB",
        "Организация 1С",
        "nmId",
        "Артикул WB",
        "Баркод",
        "Номенклатура 1С",
        "Артикул 1С",
        "Характеристика 1С",
        "Метод",
        "Уверенность",
        "Статус",
        "Комментарий",
    ]
    sheet.write_row(0, 0, headers, formats["header"])
    for idx, mapping in enumerate(mappings, start=1):
        sheet.write(idx, 0, _account_label(mapping.seller_account_id, account_labels))
        sheet.write(
            idx,
            1,
            _organization_label(mapping.organization_id, organization_labels),
        )
        sheet.write(idx, 2, mapping.nm_id or "")
        sheet.write(idx, 3, mapping.vendor_code)
        sheet.write(idx, 4, mapping.barcode)
        sheet.write(idx, 5, mapping.onec_item_id)
        sheet.write(idx, 6, mapping.onec_article)
        sheet.write(idx, 7, mapping.onec_characteristic)
        sheet.write(idx, 8, mapping.match_method)
        sheet.write_number(idx, 9, float(mapping.confidence))
        sheet.write(idx, 10, _mapping_status_label(mapping.status))
        sheet.write(idx, 11, mapping.comment)
    if not mappings:
        sheet.write_row(1, 0, ["planned_input", "Маппинг WB <-> 1С не загружен."])
    _add_table(sheet, headers, len(mappings) or 1)
    sheet.set_column(0, 11, 18)


def _write_errors(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> None:
    sheet = workbook.add_worksheet("Ошибки данных")
    sheet.write_row(
        0,
        0,
        ["Неделя", "Кабинет WB", "Организация 1С", "nmId", "Артикул", "Статус"],
        formats["header"],
    )
    row_idx = 1
    for row in report.rows:
        if row.data_quality_status != DataQualityStatus.RELIABLE:
            sheet.write(
                row_idx,
                0,
                str(_display_week_start(row.week_start, report.report_period_start)),
            )
            sheet.write(
                row_idx, 1, _account_label(row.seller_account_id, account_labels)
            )
            sheet.write(
                row_idx,
                2,
                _organization_label(row.organization_id, organization_labels),
            )
            sheet.write(row_idx, 3, row.nm_id or "")
            sheet.write(row_idx, 4, row.vendor_code)
            sheet.write(row_idx, 5, _data_quality_label(row.data_quality_status))
            row_idx += 1
    _add_table(
        sheet,
        ["Неделя", "Кабинет WB", "Организация 1С", "nmId", "Артикул", "Статус"],
        row_idx - 1,
    )
    sheet.set_column(0, 5, 20)


def _write_methodology(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    report: UnitEconomicsReport,
) -> None:
    sheet = workbook.add_worksheet("Методика")
    rows = [
        ("Версия", report.methodology_version),
        (
            "Формула",
            "net_revenue - wb_commission - logistics - storage - acceptance - "
            "wb_promotion - penalties_and_holdbacks - acquiring - "
            "cogs_from_1c_with_extra_costs = прибыль до налогов; "
            "маржинальный доход WB после налогов = прибыль до налогов - "
            "НДС - налог с выручки",
        ),
        (
            "СПП",
            "СПП берется только из подтвержденного поля WB sales-reports/list "
            "cashbackDiscountSum. Выручка после СПП является контрольной строкой "
            "внутри WB-методики; с общей выручкой 1С/ОПиУ ее не сравниваем, "
            "если в ОПиУ есть продажи не только Wildberries.",
        ),
        (
            "Прибыль",
            "Текущий расчет не называется чистой прибылью бизнеса: это "
            "маржинальный доход WB после налогов по товарной юнит-экономике.",
        ),
        ("НДС", "НДС считается по налоговому профилю организации 1С."),
        (
            "Налог с выручки",
            "Налог с выручки считается по налоговому профилю организации 1С.",
        ),
        (
            "Сверка налогов",
            "Строки 1С/ОПиУ НДС с продаж и УСН используются как контрольные "
            "суммы; товарное распределение идет по выручке.",
        ),
        (
            "Себестоимость 1С",
            "Основной источник - AccumulationRegister_Продажи, поле Себестоимость.",
        ),
        (
            "Допрасходы",
            "Распределенные допрасходы уже включены в себестоимость 1С; "
            "отдельно не прибавляются.",
        ),
        ("Возвраты", "Относятся к периоду WB Finance"),
        (
            "Упущенные продажи",
            "Предварительно рассчитываются по WB stock-history: дни без остатка, "
            "среднедневные продажи, упущенная выручка и упущенная прибыль. "
            "Перед решениями требуется сверка с 1С остатками комиссионера.",
        ),
        ("Недели", "Понедельник-воскресенье, Europe/Moscow"),
        (
            "WB Продвижение",
            "Включается отдельной статьей из deduction/deductionSum; "
            "сверяется с 1С УПД и приводится к недельному фин. отчету WB.",
        ),
        (
            "Распределение хранения",
            "Финальная сумма по неделе берется из paidStorageSum недельного "
            "отчета WB; товарные доли берутся из детализации/API хранения.",
        ),
        (
            "Распределение WB Продвижения",
            "Финальная сумма по неделе берется из deductionSum недельного "
            "отчета WB; товарные доли берутся из детализации/API рекламы.",
        ),
        ("Реклама", "Отдельные рекламные API исключены из MVP"),
    ]
    sheet.write_row(0, 0, ["Параметр", "Значение"], formats["header"])
    for idx, row in enumerate(rows, start=1):
        sheet.write_row(idx, 0, row)
    _add_table(sheet, ["Параметр", "Значение"], len(rows))
    sheet.set_column(0, 0, 18)
    sheet.set_column(1, 1, 90)


def _write_placeholder(
    workbook: xlsxwriter.Workbook,
    formats: dict[str, object],
    sheet_name: str,
    message: str,
) -> None:
    sheet = workbook.add_worksheet(sheet_name)
    sheet.write_row(0, 0, ["Статус", "Описание"], formats["header"])
    sheet.write_row(1, 0, ["Планируется", message])
    _add_table(sheet, ["Статус", "Описание"], 1)
    sheet.set_column(0, 1, 36)


def _totals(rows: Iterable[object]) -> dict[str, Decimal]:
    totals = {
        "sales_quantity": Decimal("0"),
        "return_quantity": Decimal("0"),
        "quantity": Decimal("0"),
        "return_amount": Decimal("0"),
        "revenue_before_spp": Decimal("0"),
        "spp_discount": Decimal("0"),
        "revenue_after_spp": Decimal("0"),
        "net_revenue": Decimal("0"),
        "wb_commission": Decimal("0"),
        "logistics": Decimal("0"),
        "storage": Decimal("0"),
        "acceptance": Decimal("0"),
        "wb_promotion": Decimal("0"),
        "penalties_and_holdbacks": Decimal("0"),
        "acquiring": Decimal("0"),
        "cogs": Decimal("0"),
        "gross_profit": Decimal("0"),
        "vat_5": Decimal("0"),
        "usn_1": Decimal("0"),
        "profit_after_taxes": Decimal("0"),
    }
    for row in rows:
        totals["sales_quantity"] += getattr(row, "sales_quantity", Decimal("0"))
        totals["return_quantity"] += getattr(row, "return_quantity", Decimal("0"))
        totals["quantity"] += row.quantity
        totals["return_amount"] += getattr(row, "return_amount", Decimal("0"))
        totals["revenue_before_spp"] += getattr(
            row,
            "revenue_before_spp",
            row.net_revenue,
        )
        totals["spp_discount"] += getattr(row, "spp_discount", Decimal("0"))
        totals["revenue_after_spp"] += getattr(
            row,
            "revenue_after_spp",
            row.net_revenue,
        )
        totals["net_revenue"] += row.net_revenue
        totals["wb_commission"] += row.wb_commission
        totals["logistics"] += row.logistics
        totals["storage"] += row.storage
        totals["acceptance"] += row.acceptance
        totals["wb_promotion"] += row.wb_promotion
        totals["penalties_and_holdbacks"] += row.penalties_and_holdbacks
        totals["acquiring"] += row.acquiring
        totals["cogs"] += row.cogs_from_1c_with_extra_costs
        totals["gross_profit"] += row.gross_profit
        totals["vat_5"] += getattr(row, "vat_5_from_revenue", Decimal("0"))
        totals["usn_1"] += getattr(row, "usn_1_from_revenue", Decimal("0"))
        totals["profit_after_taxes"] += getattr(row, "profit_after_taxes", Decimal("0"))
    return totals


def _safe_margin(profit: Decimal, revenue: Decimal) -> Decimal | None:
    if revenue == 0:
        return None
    return profit / revenue


def _loss_reason(row_or_totals: object) -> str:
    if isinstance(row_or_totals, Mapping):
        status = row_or_totals.get("data_quality_status", DataQualityStatus.RELIABLE)
    else:
        status = getattr(
            row_or_totals, "data_quality_status", DataQualityStatus.RELIABLE
        )
    if status is not DataQualityStatus.RELIABLE:
        return "Нужна проверка данных"

    profit = getattr(row_or_totals, "profit_after_taxes", None)
    if profit is None and isinstance(row_or_totals, Mapping):
        profit = row_or_totals["profit_after_taxes"]
    if profit is None or profit >= 0:
        return ""

    if isinstance(row_or_totals, Mapping):
        candidates = {
            "Высокая себестоимость": row_or_totals["cogs"],
            "Высокая комиссия WB": abs(row_or_totals["wb_commission"]),
            "Высокая логистика WB": abs(row_or_totals["logistics"]),
            "Высокое хранение WB": abs(row_or_totals["storage"]),
            "Высокое продвижение WB": abs(row_or_totals["wb_promotion"]),
            "Штрафы или удержания WB": abs(row_or_totals["penalties_and_holdbacks"]),
            "Высокий эквайринг WB": abs(row_or_totals["acquiring"]),
            "Налоги": row_or_totals["vat_5"] + row_or_totals["usn_1"],
            "Возвраты": row_or_totals["return_amount"],
        }
    else:
        candidates = {
            "Высокая себестоимость": row_or_totals.cogs_from_1c_with_extra_costs,
            "Высокая комиссия WB": abs(row_or_totals.wb_commission),
            "Высокая логистика WB": abs(row_or_totals.logistics),
            "Высокое хранение WB": abs(row_or_totals.storage),
            "Высокое продвижение WB": abs(row_or_totals.wb_promotion),
            "Штрафы или удержания WB": abs(row_or_totals.penalties_and_holdbacks),
            "Высокий эквайринг WB": abs(row_or_totals.acquiring),
            "Налоги": (
                row_or_totals.vat_5_from_revenue + row_or_totals.usn_1_from_revenue
            ),
            "Возвраты": getattr(row_or_totals, "return_amount", Decimal("0")),
        }

    reason, amount = max(candidates.items(), key=lambda item: item[1])
    if amount <= 0:
        return "Низкая цена продажи"
    return reason


def _loss_classification(row_or_totals: object) -> str:
    if isinstance(row_or_totals, Mapping):
        status = row_or_totals.get("data_quality_status", DataQualityStatus.RELIABLE)
    else:
        status = getattr(
            row_or_totals, "data_quality_status", DataQualityStatus.RELIABLE
        )
    if status is not DataQualityStatus.RELIABLE:
        return "Нужна проверка данных"

    reason = _loss_reason(row_or_totals)
    if not reason:
        return ""
    if reason in {"Высокая себестоимость", "Низкая цена продажи"}:
        return "Высокая закупка / недостаточная наценка"
    if reason in {"Высокая логистика WB", "Высокое хранение WB", "Возвраты"}:
        return "Возвраты + логистика"
    return "Прочие расходы"


def _write_kpi_table(
    sheet: xlsxwriter.worksheet.Worksheet,
    formats: dict[str, object],
    *,
    start_row: int,
    start_col: int,
    rows: list[tuple[str, object]],
) -> None:
    headers = ["Показатель", "Значение"]
    sheet.write_row(start_row, start_col, headers, formats["header"])
    for offset, (label, value) in enumerate(rows, start=1):
        row_idx = start_row + offset
        sheet.write(row_idx, start_col, label)
        if isinstance(value, Decimal):
            if "Маржа" in label or "Доля" in label or "%" in label:
                sheet.write_number(
                    row_idx,
                    start_col + 1,
                    float(value),
                    formats["percent"],
                )
            elif "шт" in label or "SKU" in label or "Строк" in label:
                sheet.write_number(row_idx, start_col + 1, float(value))
            else:
                sheet.write_number(
                    row_idx,
                    start_col + 1,
                    float(value),
                    formats["money"],
                )
        elif isinstance(value, int):
            sheet.write_number(row_idx, start_col + 1, value)
        elif value is None:
            sheet.write(row_idx, start_col + 1, "")
        else:
            sheet.write(row_idx, start_col + 1, str(value))
    _add_table_at(
        sheet,
        headers,
        len(rows),
        start_row=start_row,
        start_col=start_col,
    )


def _write_table_block(
    sheet: xlsxwriter.worksheet.Worksheet,
    formats: dict[str, object],
    *,
    start_row: int,
    start_col: int,
    headers: list[str],
    rows: list[tuple[object, ...]],
    money_columns: set[int] | None = None,
    percent_columns: set[int] | None = None,
) -> None:
    money_columns = money_columns or set()
    percent_columns = percent_columns or set()
    sheet.write_row(start_row, start_col, headers, formats["header"])
    for row_offset, row_values in enumerate(rows, start=1):
        row_idx = start_row + row_offset
        for col_offset, value in enumerate(row_values):
            col_idx = start_col + col_offset
            if value is None:
                sheet.write(row_idx, col_idx, "")
            elif col_offset in percent_columns and isinstance(value, Decimal):
                sheet.write_number(row_idx, col_idx, float(value), formats["percent"])
            elif col_offset in money_columns and isinstance(value, (Decimal, int)):
                sheet.write_number(row_idx, col_idx, float(value), formats["money"])
            elif isinstance(value, int):
                sheet.write_number(row_idx, col_idx, value)
            elif isinstance(value, Decimal):
                sheet.write_number(row_idx, col_idx, float(value))
            else:
                sheet.write(row_idx, col_idx, str(value))
    _add_table_at(
        sheet,
        headers,
        len(rows),
        start_row=start_row,
        start_col=start_col,
    )


def _weekly_summary_rows(
    rows: Iterable[object],
    *,
    report_period_start: date | None = None,
) -> list[tuple[object, ...]]:
    grouped: dict[str, list[object]] = defaultdict(list)
    for row in rows:
        week_start = (
            _display_week_start(row.week_start, report_period_start)
            if report_period_start is not None
            else row.week_start
        )
        grouped[str(week_start)].append(row)
    result: list[tuple[object, ...]] = []
    for week, week_rows in sorted(grouped.items()):
        totals = _totals(week_rows)
        margin = _safe_margin(
            totals["profit_after_taxes"],
            totals["net_revenue"],
        )
        result.append(
            (
                week,
                totals["net_revenue"],
                totals["cogs"],
                totals["profit_after_taxes"],
                margin,
                totals["storage"],
                totals["wb_promotion"],
            )
        )
    return result


def _month_summary_rows(
    rows: Iterable[object],
    report: UnitEconomicsReport,
) -> list[tuple[object, ...]]:
    grouped: dict[date, list[object]] = defaultdict(list)
    for row in rows:
        grouped[_row_month_start(row, report.report_period_start)].append(row)
    result: list[tuple[object, ...]] = []
    for month, month_rows in sorted(grouped.items()):
        totals = _totals(month_rows)
        wb_expenses = _wb_expenses(totals)
        result.append(
            (
                _month_label(month, report),
                (
                    "неполный месяц"
                    if _month_end(month) > report.report_period_end
                    or month < _month_start(report.report_period_start)
                    else "полный месяц"
                ),
                totals["sales_quantity"],
                totals["return_quantity"],
                _safe_margin(totals["return_quantity"], totals["sales_quantity"]),
                totals["revenue_before_spp"],
                totals["spp_discount"],
                _safe_margin(totals["spp_discount"], totals["revenue_before_spp"]),
                totals["revenue_after_spp"],
                totals["logistics"],
                wb_expenses,
                totals["profit_after_taxes"],
                _safe_margin(totals["profit_after_taxes"], totals["revenue_after_spp"]),
            )
        )
    return result


def _month_change_rows(
    monthly_rows: list[tuple[object, ...]],
) -> list[tuple[object, ...]]:
    result: list[tuple[object, ...]] = []
    for previous, current in zip(monthly_rows, monthly_rows[1:], strict=False):
        period = f"{current[0]} к {previous[0]}"
        revenue_delta = current[8] - previous[8]
        profit_delta = current[11] - previous[11]
        expense_delta = current[10] - previous[10]
        result.append(
            (
                period,
                revenue_delta,
                _safe_margin(revenue_delta, previous[8]),
                profit_delta,
                _safe_margin(profit_delta, previous[11]),
                expense_delta,
                _safe_margin(expense_delta, previous[10]),
            )
        )
    return result


def _wb_expenses(totals: Mapping[str, Decimal]) -> Decimal:
    return (
        totals["wb_commission"]
        + totals["logistics"]
        + totals["storage"]
        + totals["acceptance"]
        + totals["wb_promotion"]
        + totals["penalties_and_holdbacks"]
        + totals["acquiring"]
    )


def _expense_structure_rows(
    rows: Iterable[object],
    report: UnitEconomicsReport,
) -> list[tuple[object, ...]]:
    source_rows = list(rows)
    totals = _totals(source_rows)
    revenue = totals["revenue_after_spp"]
    month_keys = _report_month_keys(report)
    grouped: dict[date, list[object]] = defaultdict(list)
    for row in source_rows:
        grouped[_row_month_start(row, report.report_period_start)].append(row)

    articles = [
        ("Расходы РВБ общий блок", "__wb_expenses__"),
        ("Себестоимость 1С", "cogs"),
        ("Комиссия WB", "wb_commission"),
        ("Логистика WB", "logistics"),
        ("Хранение WB", "storage"),
        ("Приемка WB", "acceptance"),
        ("WB Продвижение", "wb_promotion"),
        ("Штрафы/удержания WB", "penalties_and_holdbacks"),
        ("Эквайринг WB", "acquiring"),
        ("Налог с выручки", "usn_1"),
    ]
    result: list[tuple[object, ...]] = []
    for label, key in articles:
        if key == "__wb_expenses__":
            month_values = [
                _wb_expenses(_totals(grouped[month])) for month in month_keys
            ]
            total = _wb_expenses(totals)
        else:
            month_values = [
                _totals(grouped[month]).get(key, Decimal("0")) for month in month_keys
            ]
            total = totals.get(key, Decimal("0"))
        changes = [
            current - previous
            for previous, current in zip(month_values, month_values[1:], strict=False)
        ]
        result.append(
            (
                label,
                total,
                _safe_margin(total, revenue),
                *month_values,
                *changes,
            )
        )
    return result


def _status_summary_rows(rows: Iterable[object]) -> list[tuple[object, ...]]:
    grouped: dict[str, list[object]] = defaultdict(list)
    for row in rows:
        grouped[_data_quality_label(row.data_quality_status)].append(row)
    result: list[tuple[object, ...]] = []
    for status, status_rows in sorted(grouped.items()):
        totals = _totals(status_rows)
        result.append(
            (
                status,
                len(status_rows),
                totals["net_revenue"],
                totals["cogs"],
                totals["profit_after_taxes"],
                totals["storage"],
                totals["wb_promotion"],
            )
        )
    return result


def _account_org_summary_rows(
    rows: Iterable[object],
    *,
    account_labels: Mapping[str, str] | None,
    organization_labels: Mapping[str, str] | None,
) -> list[tuple[object, ...]]:
    grouped: dict[tuple[str, str], list[object]] = defaultdict(list)
    for row in rows:
        grouped[(row.organization_id, row.seller_account_id)].append(row)
    result: list[tuple[object, ...]] = []
    for (organization_id, seller_account_id), group_rows in sorted(grouped.items()):
        totals = _totals(group_rows)
        result.append(
            (
                _organization_label(organization_id, organization_labels),
                _account_label(seller_account_id, account_labels),
                totals["net_revenue"],
                totals["cogs"],
                totals["profit_after_taxes"],
                _safe_margin(totals["profit_after_taxes"], totals["net_revenue"]),
            )
        )
    return result


def _product_summary_rows(
    rows: Iterable[object],
    cost_names: Mapping[tuple[str, str], str],
    cost_snapshots: Iterable[OnecUnfCostSnapshot],
    sku_mappings: Iterable[SkuMapping],
) -> list[tuple[object, ...]]:
    cost_articles = _cost_article_lookup(cost_snapshots)
    mapping_articles = _mapping_article_lookup(sku_mappings)
    grouped: dict[tuple[str, str, str], list[object]] = defaultdict(list)
    for row in rows:
        label = _product_label(row, cost_names)
        onec_article = _onec_article_label(row, cost_articles, mapping_articles)
        grouped[(label, row.vendor_code, onec_article)].append(row)
    result: list[tuple[object, ...]] = []
    for (label, wb_article, onec_article), product_rows in sorted(grouped.items()):
        totals = _totals(product_rows)
        worst_status = DataQualityStatus.RELIABLE
        for row in product_rows:
            if row.data_quality_status is not DataQualityStatus.RELIABLE:
                worst_status = row.data_quality_status
                break
        status = _data_quality_label(worst_status)
        profit_per_unit = _safe_margin(totals["profit_after_taxes"], totals["quantity"])
        return_rate = _safe_margin(totals["return_quantity"], totals["sales_quantity"])
        reason_totals = {
            **totals,
            "data_quality_status": worst_status,
        }
        result.append(
            (
                label,
                wb_article,
                onec_article,
                totals["quantity"],
                totals["return_quantity"],
                return_rate,
                totals["net_revenue"],
                totals["storage"],
                totals["profit_after_taxes"],
                profit_per_unit,
                _safe_margin(totals["profit_after_taxes"], totals["net_revenue"]),
                _loss_reason(reason_totals),
                _loss_classification(reason_totals),
                status,
                totals["cogs"],
            )
        )
    return sorted(result, key=lambda row: row[6], reverse=True)


def _is_top_profit_product_row(row: tuple[object, ...]) -> bool:
    profit = row[8]
    profit_per_unit = row[9]
    status = row[13]
    cogs = row[14]
    allowed_statuses = {
        DATA_QUALITY_LABELS[DataQualityStatus.RELIABLE],
        DATA_QUALITY_LABELS[DataQualityStatus.NEEDS_REVIEW],
        DATA_QUALITY_LABELS[DataQualityStatus.REPORT_TYPE_FALLBACK],
    }
    return (
        status in allowed_statuses
        and isinstance(cogs, Decimal)
        and cogs > 0
        and isinstance(profit, Decimal)
        and profit > 0
        and isinstance(profit_per_unit, Decimal)
        and profit_per_unit > 0
    )


def _add_table(
    sheet: xlsxwriter.worksheet.Worksheet,
    headers: list[str],
    data_row_count: int,
) -> None:
    _add_table_at(sheet, headers, data_row_count, start_row=0)


def _add_table_at(
    sheet: xlsxwriter.worksheet.Worksheet,
    headers: list[str],
    data_row_count: int,
    *,
    start_row: int,
    start_col: int = 0,
) -> None:
    if data_row_count <= 0:
        sheet.autofilter(
            start_row,
            start_col,
            start_row,
            start_col + len(headers) - 1,
        )
        return
    sheet.add_table(
        start_row,
        start_col,
        start_row + data_row_count,
        start_col + len(headers) - 1,
        {
            "style": "Table Style Medium 2",
            "columns": [{"header": header} for header in headers],
        },
    )


def _add_category_amount(
    totals: dict[tuple[str, str, str], Decimal],
    week: str,
    label: str,
    category: str,
    amount: Decimal,
) -> None:
    totals[(week, label, category)] += amount


def _service_check_rows(
    onec_totals: Mapping[tuple[str, str, str], Decimal],
    detail_totals: Mapping[tuple[str, str, str], Decimal],
    summary_totals: Mapping[tuple[str, str, str], Decimal],
) -> list[dict[str, object]]:
    checks = [
        (
            "WB Продвижение",
            ("WB Продвижение",),
            "Сверяется отдельной статьей.",
        ),
        (
            "Штрафы/доплаты",
            ("Штрафы/доплаты",),
            "Сверяется отдельной статьей.",
        ),
        (
            "Комиссия + Логистика + Хранение + Эквайринг",
            ("Комиссия WB", "Логистика", "Хранение", "Эквайринг"),
            (
                "1С может относить часть WB-услуг в комиссионное "
                "вознаграждение, поэтому блок сверяется суммарно."
            ),
        ),
    ]
    week_labels = sorted(
        {(week, label) for week, label, _category in onec_totals}
        | {(week, label) for week, label, _category in detail_totals}
        | {(week, label) for week, label, _category in summary_totals}
    )
    rows: list[dict[str, object]] = []
    for week, label in week_labels:
        for check_label, categories, comment in checks:
            summary = _sum_optional_categories(summary_totals, week, label, categories)
            check_comment = comment
            if summary is None and len(categories) > 1:
                check_comment = (
                    f"{comment} В недельном списке WB нет прямых колонок "
                    "комиссии и эквайринга."
                )
            rows.append(
                {
                    "week": week,
                    "label": label,
                    "check": check_label,
                    "onec": _sum_categories(onec_totals, week, label, categories),
                    "detail": _sum_categories(detail_totals, week, label, categories),
                    "summary": summary,
                    "comment": check_comment,
                }
            )
    return rows


def _sum_categories(
    totals: Mapping[tuple[str, str, str], Decimal],
    week: str,
    label: str,
    categories: tuple[str, ...],
) -> Decimal:
    return sum(
        (totals.get((week, label, category), Decimal("0")) for category in categories),
        Decimal("0"),
    )


def _sum_optional_categories(
    totals: Mapping[tuple[str, str, str], Decimal],
    week: str,
    label: str,
    categories: tuple[str, ...],
) -> Decimal | None:
    if any((week, label, category) not in totals for category in categories):
        return None
    return _sum_categories(totals, week, label, categories)


def _service_reconciliation_comment(
    category: str,
    summary_value: Decimal | None,
) -> str:
    if category in {"Комиссия WB", "Эквайринг"} and summary_value is None:
        return "В недельном списке WB нет прямой сопоставимой колонки"
    if summary_value is None:
        return "Нет строки в недельном сводном отчете WB"
    return ""


def _report_type_label(report_type: int | None) -> str:
    if report_type == 1:
        return "Отчет комиссионера"
    if report_type == 2:
        return "Уведомление о выкупе"
    if report_type is None:
        return ""
    return str(report_type)


def _weekly_summary_rows_by_type(
    rows: Iterable[WbSalesReportSummaryRow],
) -> dict[tuple[str, date, str], list[WbSalesReportSummaryRow]]:
    grouped: dict[tuple[str, date, str], list[WbSalesReportSummaryRow]] = defaultdict(
        list
    )
    for row in rows:
        label = _report_type_label(row.report_type)
        if not label:
            continue
        grouped[(row.seller_account_id, row.date_from, label)].append(row)
    return grouped


def _sum_summary_field(
    rows: Iterable[WbSalesReportSummaryRow],
    field_name: str,
) -> Decimal:
    return sum((getattr(row, field_name) for row in rows), Decimal("0"))


def _summary_report_ids(rows: Iterable[WbSalesReportSummaryRow]) -> str:
    return ", ".join(row.report_id for row in rows if row.report_id)


def _optional_delta(
    left: Decimal | None,
    right: Decimal | None,
) -> Decimal | None:
    if left is None or right is None:
        return None
    return left - right


def _sum_summary_goods_sold(rows: Iterable[WbSalesReportSummaryRow]) -> Decimal:
    return sum(
        (row.retail_amount_sum - row.cashback_discount_sum for row in rows),
        Decimal("0"),
    )


def _write_optional_money(
    sheet: xlsxwriter.worksheet.Worksheet,
    row: int,
    col: int,
    value: Decimal | None,
    fmt: object,
) -> None:
    if value is None:
        sheet.write(row, col, "")
        return
    sheet.write_number(row, col, float(value), fmt)


def _write_optional_number(
    sheet: xlsxwriter.worksheet.Worksheet,
    row: int,
    col: int,
    value: Decimal | int | None,
) -> None:
    if value is None:
        sheet.write(row, col, "")
        return
    sheet.write_number(row, col, float(value))


def _weekly_report_ids_by_type(
    rows: Iterable[WbSalesReportSummaryRow],
) -> dict[tuple[str, object, str], tuple[str, ...]]:
    grouped: dict[tuple[str, object, str], list[str]] = defaultdict(list)
    for row in rows:
        label = _report_type_label(row.report_type)
        if not row.report_id or not label:
            continue
        grouped[(row.seller_account_id, row.date_from, label)].append(row.report_id)
    return {key: tuple(values) for key, values in grouped.items()}


def _report_id_document_label(report_id: str) -> str:
    if report_id.isdigit() and len(report_id) >= 16 and report_id.endswith("1"):
        return "Уведомление о выкупе"
    if report_id:
        return "Отчет комиссионера"
    return "Без номера"


def _data_quality_label(status: DataQualityStatus) -> str:
    return DATA_QUALITY_LABELS.get(status, status.value)


def _mapping_status_label(status: MappingStatus) -> str:
    return MAPPING_STATUS_LABELS.get(status, status.value)


def _advertising_scope_label(status: AdvertisingScope) -> str:
    return ADVERTISING_SCOPE_LABELS.get(status, status.value)


def _yes_no(value: bool) -> str:
    return "Да" if value else "Нет"
