from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

EXPORT_SHEETS = {
    "unitRows": "Юнит экономика",
    "liquidityRows": "Ликвидность МД",
    "monthly": "Динамика",
    "expenses": "Расходы WB",
    "returns": "Возвраты",
    "lostSales": "Упущенные продажи",
    "documentReconciliation": "Сверка документов 1С",
    "reconciliationMonthly": "Сверка с 1С ОПиУ",
}

OZON_EXPORT_SHEETS = {
    "ozonSummaryRows": "Сводная Ozon",
    "ozonUnitRows": "Юнит экономика Ozon",
    "ozonServiceChargeRows": "Начисления услуг Ozon",
    "ozonArticleSkuRows": "Статьи по SKU",
    "ozonReconciliationRows": "Сверка Ozon 1C",
}

SHEET_COLUMNS: dict[str, list[str]] = {
    "unitRows": [
        "week",
        "month",
        "documentReport",
        "wbReportId",
        "wbReportDate",
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
        "revenueBeforeSpp",
        "spp",
        "sppRate",
        "revenue",
        "vat",
        "revenueWithoutVat",
        "cost",
        "commission",
        "logistics",
        "storage",
        "acceptance",
        "promotion",
        "penalties",
        "acquiring",
        "usn",
        "profitBeforeTax",
        "profit",
        "margin",
        "unitProfit",
        "taxMethod",
        "taxProfileSource",
        "status",
        "statusReason",
        "sppStatus",
        "lossClass",
        "lossDriver",
    ],
    "liquidityRows": [
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
    ],
    "monthly": [
        "month",
        "status",
        "sales",
        "returns",
        "return_rate",
        "revenue",
        "profit",
        "margin",
    ],
    "expenses": ["expense", "amount", "share"],
    "returns": [
        "week",
        "month",
        "organization",
        "cabinet",
        "product",
        "nmId",
        "articleWb",
        "article1c",
        "barcode",
        "sales",
        "returns",
        "returnRate",
        "returnAmount",
        "profit",
        "status",
        "driver",
        "returnReason",
    ],
    "lostSales": [
        "cabinet",
        "product",
        "nmId",
        "articleWb",
        "article1c",
        "barcode",
        "periodDays",
        "zeroStockDays",
        "criticalStockDays",
        "onecStock",
        "onecWarehouses",
        "sales",
        "avgDailySales",
        "lostUnits",
        "lostRevenue",
        "lostProfit",
        "profitPerSale",
        "note",
        "sourceStatus",
    ],
    "documentReconciliation": [
        "status",
        "payoutStatus",
        "periodStatus",
        "documentReport",
        "salesPeriod",
        "expectedDocumentDate",
        "documentType",
        "cabinet",
        "organization",
        "summaryReportId",
        "weeklySalesReportId",
        "weeklyBuyoutReportId",
        "wbReportIds",
        "onecDocuments",
        "onecDocumentTypes",
        "onecDocumentDates",
        "wbSalesQuantity",
        "wbReturnQuantity",
        "wbNetQuantity",
        "onecSalesQuantity",
        "onecReturnQuantity",
        "onecNetQuantity",
        "salesQuantityDelta",
        "returnQuantityDelta",
        "netQuantityDelta",
        "wbQuantity",
        "onecQuantity",
        "quantityDelta",
        "wbAmount",
        "onecAmount",
        "amountDelta",
        "buyoutRetailAmountSum",
        "buyoutForPaySum",
        "buyoutBankPaymentSum",
        "onecExpenseInvoiceAmount",
        "buyoutRetailDelta",
        "buyoutForPayDelta",
        "buyoutBankDelta",
        "pdfBankPayment",
        "wbForPaySum",
        "onecSettlementTotal",
        "settlementDelta",
        "onecSourceRows",
        "comment",
    ],
    "reconciliationMonthly": [
        "month",
        "wb_quantity",
        "onec_quantity",
        "quantity_delta",
        "wb_cogs",
        "onec_cogs",
        "cogs_delta",
        "wb_mp_expenses",
        "onec_mp_expenses",
        "mp_expenses_delta",
        "comment",
    ],
    "ozonSummaryRows": [
        "articleId",
        "label",
        "group",
        "amount",
        "effectAmount",
        "share",
        "sourceLabels",
        "status",
        "actionText",
    ],
    "ozonUnitRows": [
        "periodStart",
        "periodEnd",
        "offerId",
        "productId",
        "sku",
        "barcode",
        "productName",
        "quantity",
        "onecRevenue",
        "cogs",
        "ozonCommission",
        "ozonServices",
        "ozonPartnerServices",
        "ozonLogistics",
        "ozonStorage",
        "ozonOtherExpenses",
        "ozonExpenses",
        "profit",
        "margin",
        "onecItemId",
        "onecName",
        "qualityStatus",
        "expenseStatus",
        "problemReason",
        "actionText",
    ],
    "ozonServiceChargeRows": [
        "articleId",
        "label",
        "sourceLabel",
        "offerId",
        "sku",
        "productName",
        "onecName",
        "amount",
        "effectAmount",
        "allocationShare",
        "basis",
        "status",
        "note",
    ],
    "ozonArticleSkuRows": [
        "articleId",
        "label",
        "offerId",
        "sku",
        "barcode",
        "productName",
        "onecName",
        "amount",
        "effectAmount",
        "allocationShare",
        "includedInSkuProfit",
        "basis",
        "status",
    ],
    "ozonReconciliationRows": [
        "kind",
        "label",
        "parentLabel",
        "ozonAmount",
        "onecAmount",
        "deltaAmount",
        "includedInExpense",
        "note",
    ],
}

COLUMN_LABELS = {
    "week": "Неделя",
    "month": "Месяц",
    "status": "Статус",
    "documentReport": "Документ-отчет",
    "wbReportId": "Номер отчета WB",
    "wbReportDate": "Дата отчета WB",
    "organization": "Организация 1С",
    "cabinet": "Кабинет WB",
    "product": "Товар",
    "nmId": "nmId WB",
    "articleWb": "Артикул WB",
    "article1c": "Артикул 1С",
    "barcode": "Баркод",
    "scheme": "Схема продажи",
    "sales": "Продажи, шт",
    "returns": "Возвраты, шт",
    "netQty": "Чистое кол-во",
    "returnRate": "% возвратов",
    "return_rate": "% возвратов",
    "revenueBeforeSpp": "Выручка до СПП",
    "spp": "СПП",
    "sppRate": "% СПП",
    "revenue": "Выручка после СПП",
    "vat": "НДС",
    "revenueWithoutVat": "Выручка без НДС",
    "cost": "Себестоимость 1С",
    "md1Markup": "МД1 Наценка",
    "commission": "Комиссия WB",
    "md2AfterCommission": "МД2 после комиссии",
    "logistics": "Логистика WB",
    "storage": "Хранение WB",
    "md3AfterStorage": "МД3 после хранения",
    "acceptance": "Приемка WB",
    "md4AfterLogisticsAcceptance": "МД4 после логистики и приемки",
    "promotion": "Продвижение WB",
    "md5AfterPromotion": "МД5 после продвижения",
    "penalties": "Штрафы/доплаты WB",
    "acquiring": "Эквайринг WB",
    "md6BeforeTax": "МД6 до налогов",
    "usn": "Налог с выручки",
    "profitBeforeTax": "Прибыль до налогов",
    "profit": "Маржинальный доход WB после налогов",
    "margin": "Маржа после налогов",
    "unitProfit": "МД после налогов на шт",
    "taxMethod": "Налоговый режим/ставка",
    "taxProfileSource": "Источник налогового профиля",
    "statusReason": "Причина статуса",
    "sppStatus": "Статус СПП",
    "lossClass": "Класс убытка",
    "lossDriver": "Драйвер убытка",
    "liquidityStatus": "Статус ликвидности",
    "liquidityDriver": "Драйвер ликвидности",
    "expense": "Статья расходов",
    "amount": "Сумма",
    "share": "Доля от выручки",
    "returnAmount": "Сумма возвратов",
    "driver": "Драйвер",
    "returnReason": "Причина возврата",
    "periodDays": "Дни в периоде",
    "zeroStockDays": "Дни без остатка WB",
    "criticalStockDays": "Дни критического остатка",
    "onecStock": "Остаток 1С на складах",
    "onecWarehouses": "Склады 1С с остатком",
    "avgDailySales": "Среднедневные продажи",
    "lostUnits": "Потенциально упущенные штуки",
    "lostRevenue": "Потенциально упущенная выручка",
    "lostProfit": "Потенциально упущенная прибыль",
    "profitPerSale": "Прибыль на продажу",
    "note": "Управленческий вывод",
    "sourceStatus": "Статус источника",
    "payoutStatus": "Статус выплаты",
    "periodStatus": "Статус периода",
    "salesPeriod": "Период продаж",
    "expectedDocumentDate": "Ожидаемая дата документа",
    "documentType": "Тип документа",
    "summaryReportId": "Номер сводного отчета",
    "weeklySalesReportId": "Номер недельного отчета продаж",
    "weeklyBuyoutReportId": "Номер недельного отчета выкупов",
    "wbReportIds": "Номера отчетов WB",
    "onecDocuments": "Документы 1С",
    "onecDocumentTypes": "Типы документов 1С",
    "onecDocumentDates": "Даты документов 1С",
    "wbSalesQuantity": "Продажи WB, шт",
    "wbReturnQuantity": "Возвраты WB, шт",
    "wbNetQuantity": "Чистое кол-во WB",
    "onecSalesQuantity": "Продажи 1С, шт",
    "onecReturnQuantity": "Возвраты 1С, шт",
    "onecNetQuantity": "Чистое кол-во 1С",
    "salesQuantityDelta": "Отклонение продаж, шт",
    "returnQuantityDelta": "Отклонение возвратов, шт",
    "netQuantityDelta": "Отклонение чистого кол-ва",
    "wbQuantity": "Количество WB",
    "onecQuantity": "Количество 1С",
    "quantityDelta": "Отклонение количества",
    "wbAmount": "Сумма WB",
    "onecAmount": "Сумма 1С",
    "amountDelta": "Отклонение суммы",
    "buyoutRetailAmountSum": "Выкупы WB: розничная сумма",
    "buyoutForPaySum": "Выкупы WB: к перечислению",
    "buyoutBankPaymentSum": "Выкупы WB: банковский платеж",
    "onecExpenseInvoiceAmount": "Акт 1С по услугам",
    "buyoutRetailDelta": "Отклонение розничной суммы выкупов",
    "buyoutForPayDelta": "Отклонение к перечислению",
    "buyoutBankDelta": "Отклонение банковского платежа",
    "pdfBankPayment": "Банковский платеж из PDF",
    "wbForPaySum": "WB к перечислению",
    "onecSettlementTotal": "Взаиморасчеты 1С",
    "settlementDelta": "Отклонение взаиморасчетов",
    "onecSourceRows": "Строки источника 1С",
    "comment": "Комментарий",
    "wb_quantity": "Количество WB",
    "onec_quantity": "Количество 1С",
    "quantity_delta": "Отклонение количества",
    "wb_cogs": "Себестоимость WB",
    "onec_cogs": "Себестоимость 1С",
    "cogs_delta": "Отклонение себестоимости",
    "wb_mp_expenses": "Расходы WB",
    "onec_mp_expenses": "Расходы 1С",
    "mp_expenses_delta": "Отклонение расходов",
    "articleId": "Код статьи",
    "label": "Статья",
    "group": "Группа",
    "effectAmount": "Влияние на прибыль",
    "sourceLabels": "Источники",
    "actionText": "Действие",
    "periodStart": "Начало периода",
    "periodEnd": "Конец периода",
    "offerId": "Offer ID",
    "productId": "Product ID",
    "sku": "Ozon SKU",
    "productName": "Товар Ozon",
    "quantity": "Количество",
    "onecRevenue": "Выручка 1С",
    "cogs": "Себестоимость 1С",
    "ozonCommission": "Комиссия Ozon",
    "ozonServices": "Услуги Ozon",
    "ozonPartnerServices": "Услуги партнеров / перевыставление",
    "ozonLogistics": "Логистика Ozon",
    "ozonStorage": "Хранение / размещение Ozon",
    "ozonOtherExpenses": "Прочие расходы Ozon",
    "ozonExpenses": "Расходы Ozon",
    "onecItemId": "Ключ номенклатуры 1С",
    "onecName": "Номенклатура 1С",
    "qualityStatus": "Статус расчета",
    "expenseStatus": "Статус расходов",
    "problemReason": "Причина статуса",
    "sourceLabel": "Источник",
    "allocationShare": "Доля распределения",
    "basis": "База расчета",
    "includedInSkuProfit": "Включено в прибыль SKU",
    "kind": "Тип строки",
    "parentLabel": "Связанная строка",
    "ozonAmount": "Ozon API",
    "deltaAmount": "Дельта",
    "includedInExpense": "Входит в расходы",
}

SHEET_COLUMN_LABELS = {
    ("liquidityRows", "profit"): "МД после налогов",
    ("liquidityRows", "status"): "Статус данных",
    ("monthly", "status"): "Статус месяца",
    ("monthly", "profit"): "Маржинальный доход WB после налогов",
    ("returns", "status"): "Статус данных",
    ("documentReconciliation", "status"): "Статус сверки",
    ("ozonReconciliationRows", "onecAmount"): "1C контроль",
}

STATUS_LABELS = {
    "": "",
    "ok": "ОК",
    "OK": "ОК",
    "ready": "Готово",
    "needs_review": "Нужна проверка",
    "partial_source": "Неполный источник",
    "partial_period": "Неполный период",
    "source_coverage_gap": "Недостаточное покрытие источников",
    "blocked": "Заблокировано",
    "blocked_low_disk": "Заблокировано: мало места на диске",
    "failed": "Ошибка",
    "needs_configuration": "Нужна настройка",
    "no_data": "Нет данных",
    "missing_source": "Нет источника",
    "missing_stock_history": "Нет истории остатков WB",
    "transport_or_schema_error": "Ошибка транспорта или схемы",
    "task_failed": "Задача завершилась ошибкой",
    "task_timeout": "Истекло время ожидания задачи",
    "db_first_report_marts": "DB-first витрины отчета",
}

STATUS_FIELDS = {
    "status",
    "sourceStatus",
    "payoutStatus",
    "periodStatus",
}

PERCENT_FIELDS = {"returnRate", "return_rate", "sppRate", "margin", "share"}
MONEY_FIELDS = {
    "revenueBeforeSpp",
    "spp",
    "revenue",
    "vat",
    "revenueWithoutVat",
    "cost",
    "md1Markup",
    "commission",
    "md2AfterCommission",
    "logistics",
    "storage",
    "md3AfterStorage",
    "acceptance",
    "md4AfterLogisticsAcceptance",
    "promotion",
    "md5AfterPromotion",
    "penalties",
    "acquiring",
    "md6BeforeTax",
    "usn",
    "profitBeforeTax",
    "profit",
    "unitProfit",
    "amount",
    "returnAmount",
    "lostRevenue",
    "lostProfit",
    "profitPerSale",
    "wbAmount",
    "onecAmount",
    "amountDelta",
    "buyoutRetailAmountSum",
    "buyoutForPaySum",
    "buyoutBankPaymentSum",
    "onecExpenseInvoiceAmount",
    "buyoutRetailDelta",
    "buyoutForPayDelta",
    "buyoutBankDelta",
    "pdfBankPayment",
    "wbForPaySum",
    "onecSettlementTotal",
    "settlementDelta",
    "wb_cogs",
    "onec_cogs",
    "cogs_delta",
    "wb_mp_expenses",
    "onec_mp_expenses",
    "mp_expenses_delta",
    "effectAmount",
    "onecRevenue",
    "cogs",
    "ozonCommission",
    "ozonServices",
    "ozonPartnerServices",
    "ozonLogistics",
    "ozonStorage",
    "ozonOtherExpenses",
    "ozonExpenses",
    "ozonAmount",
    "deltaAmount",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path, status: str = "ready") -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "hash": file_sha256(path) if path.exists() else "",
        "byte_size": path.stat().st_size if path.exists() else 0,
        "status": status,
    }


def write_excel_from_marts(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    readme = workbook.active
    readme.title = "README"
    _write_readme(readme, summary)
    for key, sheet_name in EXPORT_SHEETS.items():
        _write_rows_sheet(
            workbook.create_sheet(sheet_name),
            summary.get(key, []),
            sheet_key=key,
        )
    _write_methodology(workbook.create_sheet("Методика"), summary)
    workbook.save(output_path)
    return output_path


def write_ozon_diagnostics_excel(
    diagnostics: dict[str, Any],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    first_sheet = workbook.active
    first_sheet.title = OZON_EXPORT_SHEETS["ozonSummaryRows"]
    _write_rows_sheet(
        first_sheet,
        _ozon_summary_rows(diagnostics),
        sheet_key="ozonSummaryRows",
    )
    for key, sheet_name in list(OZON_EXPORT_SHEETS.items())[1:]:
        _write_rows_sheet(
            workbook.create_sheet(sheet_name),
            _ozon_export_rows(diagnostics, key),
            sheet_key=key,
        )
    _write_ozon_methodology(workbook.create_sheet("Методика"), diagnostics)
    workbook.save(output_path)
    return output_path


def _ozon_export_rows(diagnostics: dict[str, Any], key: str) -> list[dict[str, Any]]:
    mart = diagnostics.get("ozonMart") or {}
    if key == "ozonUnitRows":
        return [dict(item) for item in _safe_rows(mart.get("rows"))]
    if key == "ozonServiceChargeRows":
        return [
            dict(item)
            for item in _safe_rows(mart.get("articleDrilldown"))
            if item.get("includedInSkuProfit")
        ]
    if key == "ozonArticleSkuRows":
        return [
            dict(item)
            for item in _safe_rows(mart.get("articleDrilldown"))
            if item.get("kind") == "sku_allocation"
        ]
    if key == "ozonReconciliationRows":
        return [
            dict(item)
            for item in _safe_rows(
                (diagnostics.get("expenseReconciliation") or {}).get("articleRows")
            )
        ]
    return []


def _ozon_summary_rows(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    mart = diagnostics.get("ozonMart") or {}
    totals = mart.get("totals") or {}
    revenue = _number_or_none(totals.get("onecRevenue"))
    expense_status = str(
        (diagnostics.get("expenseReconciliation") or {}).get("status") or ""
    )
    rows: list[dict[str, Any]] = []
    for item in _safe_rows(mart.get("articleRows")):
        effect = _number_or_none(item.get("effectAmount"))
        group = str(item.get("group") or "")
        needs_review = (
            expense_status
            and expense_status != "matched"
            and group not in {"revenue", "cogs", "result"}
        )
        rows.append(
            {
                "articleId": item.get("articleId"),
                "label": item.get("label"),
                "group": group,
                "amount": item.get("amount"),
                "effectAmount": item.get("effectAmount"),
                "share": abs(effect) / revenue
                if effect is not None and revenue and revenue > 0
                else None,
                "sourceLabels": item.get("sourceLabels") or [],
                "status": "needs_review" if needs_review else "ready",
                "actionText": (
                    "Сверить строку в листе «Сверка Ozon 1C»."
                    if needs_review
                    else "Действие не требуется."
                ),
            }
        )
    if not rows:
        rows.append(
            {
                "articleId": "status",
                "label": "Ozon diagnostics",
                "group": "status",
                "status": diagnostics.get("status") or "not_started",
                "actionText": diagnostics.get("message") or "",
            }
        )
    return rows


def _write_ozon_methodology(sheet: Any, diagnostics: dict[str, Any]) -> None:
    latest = diagnostics.get("latestRun") or {}
    rows = [
        ("Правило", "Значение"),
        ("Назначение", "Staff-only Excel для проверки Ozon unit economics"),
        (
            "Публикация",
            "Не создает ReportRun и не заменяет клиентский WB Excel MVP",
        ),
        ("Выручка", "1C отчет комиссионера / регистр продаж Ozon"),
        ("Себестоимость", "1C cost index по сопоставленной номенклатуре"),
        ("Расходы Ozon", "Mutual settlement; cash-flow только контроль"),
        (
            "1C без пары в Ozon",
            "Показывается в сверке и не распределяется в прибыль SKU",
        ),
        ("Источник данных", latest.get("snapshotSetId") or ""),
        ("Статус", diagnostics.get("status") or ""),
        ("Сообщение", diagnostics.get("message") or ""),
    ]
    for index, row in enumerate(rows, start=1):
        sheet.cell(index, 1, row[0])
        sheet.cell(index, 2, row[1])
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 90


def _safe_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _number_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def write_csv_marts(summary: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for key in (
        "unitRows",
        "lostSales",
        "reconciliationMonthly",
        "documentReconciliation",
    ):
        path = output_dir / f"{key}.csv"
        _write_csv(path, summary.get(key, []))
        paths.append(path)
    readme_path = output_dir / "README.md"
    readme_path.write_text(build_markdown_summary(summary), encoding="utf-8")
    paths.append(readme_path)
    return paths


def write_html_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = summary.get("meta", {})
    rows = summary.get("unitRows", [])
    lost = summary.get("lostSales", [])
    body = [
        '<!doctype html><html lang="ru"><meta charset="utf-8">',
        "<title>DB-first report marts</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;color:#1f2933}"
        "table{border-collapse:collapse;width:100%;margin:16px 0}"
        "th,td{border:1px solid #d9e2ec;padding:6px;font-size:12px}"
        "th{background:#edf4fb;text-align:left}</style>",
        f"<h1>{_html(meta.get('title', 'DB-first report marts'))}</h1>",
        f"<p>{_html(meta.get('client', ''))} · {_html(meta.get('period', ''))}</p>",
        f"<p><strong>Период отчета:</strong> "
        f"{_html(meta.get('reportPeriod', meta.get('period', '')))}</p>",
        f"<p><strong>Покрытие источников:</strong> "
        f"{_html(meta.get('sourceCoverage', ''))}</p>",
        f"<p><strong>Статус готовности:</strong> "
        f"{_html(_readiness_label(summary))}</p>",
        _html_table("KPI", _kpi_rows(rows)),
        _html_table("Упущенные продажи", lost[:50]),
        "</html>",
    ]
    output_path.write_text("\n".join(body), encoding="utf-8")
    return output_path


def write_markdown_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_markdown_summary(summary), encoding="utf-8")
    return output_path


def write_docx_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = summary.get("meta", {})
    doc = Document()
    doc.add_heading(str(meta.get("title") or "DB-first report marts"), level=1)
    doc.add_paragraph(f"{meta.get('client', '')} · {meta.get('period', '')}")
    doc.add_paragraph(
        f"Период отчета: {meta.get('reportPeriod', meta.get('period', ''))}"
    )
    doc.add_paragraph(f"Покрытие источников: {meta.get('sourceCoverage', '')}")
    doc.add_paragraph(f"Статус готовности: {_readiness_label(summary)}")
    doc.add_heading("KPI", level=2)
    for row in _kpi_rows(summary.get("unitRows", [])):
        doc.add_paragraph(f"{row['metric']}: {row['value']}")
    doc.add_heading("Упущенные продажи", level=2)
    for row in summary.get("lostSales", [])[:20]:
        doc.add_paragraph(
            f"{row.get('product', '')}: {row.get('lostRevenue', 0)} руб., "
            f"1С остаток {row.get('onecStock', 0)}"
        )
    doc.save(output_path)
    return output_path


def convert_docx_to_pdf(docx_path: Path) -> tuple[Path | None, str, str]:
    converter = shutil.which("libreoffice") or shutil.which("soffice")
    if converter is None:
        return None, "unavailable", "LibreOffice/soffice не найден."
    output_dir = docx_path.parent
    expected = docx_path.with_suffix(".pdf")
    try:
        result = subprocess.run(
            [
                converter,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "failed", str(exc)
    if result.returncode != 0 or not expected.exists():
        return None, "failed", "DOCX создан, PDF не сформирован."
    return expected, "ready", "PDF сформирован."


def build_markdown_summary(summary: dict[str, Any]) -> str:
    meta = summary.get("meta", {})
    lines = [
        f"# {meta.get('title', 'DB-first report marts')}",
        "",
        f"- Клиент: {meta.get('client', '')}",
        f"- Период: {meta.get('period', '')}",
        f"- Период отчета: {meta.get('reportPeriod', meta.get('period', ''))}",
        f"- Покрытие источников: {meta.get('sourceCoverage', '')}",
        f"- Статус готовности: {_readiness_label(summary)}",
        f"- Методика: {meta.get('methodologyVersion', '')}",
        f"- Lineage: {meta.get('lineageType', '')}",
        "",
        "## KPI",
    ]
    for row in _kpi_rows(summary.get("unitRows", [])):
        lines.append(f"- {row['metric']}: {row['value']}")
    lines.extend(["", "## Упущенные продажи"])
    for row in summary.get("lostSales", [])[:20]:
        lines.append(
            f"- {row.get('product', '')}: lostRevenue={row.get('lostRevenue', 0)}, "
            f"onecStock={row.get('onecStock', 0)}"
        )
    return "\n".join(lines) + "\n"


def _write_readme(sheet: Any, summary: dict[str, Any]) -> None:
    meta = summary.get("meta", {})
    rows = [
        ("Источник", _localized_source(meta.get("source", "DB report marts"))),
        ("Клиент", meta.get("client", "")),
        ("Период", meta.get("period", "")),
        ("Период отчета", meta.get("reportPeriod", meta.get("period", ""))),
        ("Покрытие источников", meta.get("sourceCoverage", "")),
        ("Статус готовности", _readiness_label(summary)),
        ("Версия методики", meta.get("methodologyVersion", "")),
        ("Происхождение данных", _localized_status(meta.get("lineageType", ""))),
        ("Строк юнит-экономики", len(summary.get("unitRows", []))),
        ("Строк упущенных продаж", len(summary.get("lostSales", []))),
    ]
    for index, row in enumerate(rows, start=1):
        sheet.cell(index, 1, row[0])
        sheet.cell(index, 2, row[1])
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 80


def _write_rows_sheet(
    sheet: Any, rows: list[dict[str, Any]], *, sheet_key: str
) -> None:
    headers = _sheet_headers(sheet_key, rows)
    if not headers:
        sheet.cell(1, 1, "Нет строк")
        return
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for column, field in enumerate(headers, start=1):
        cell = sheet.cell(1, column, _column_label(sheet_key, field))
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for row_index, row in enumerate(rows, start=2):
        for column, field in enumerate(headers, start=1):
            cell = sheet.cell(row_index, column, _localized_cell_value(field, row))
            if field in PERCENT_FIELDS and cell.value not in (None, ""):
                cell.number_format = "0.00%"
            elif field in MONEY_FIELDS and cell.value not in (None, ""):
                cell.number_format = '#,##0.00" ₽"'
    for column in range(1, len(headers) + 1):
        sheet.column_dimensions[sheet.cell(1, column).column_letter].width = 18
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def _write_methodology(sheet: Any, summary: dict[str, Any]) -> None:
    rows = [
        ("Правило", "Значение"),
        ("Источник правды", "Опубликованная расчетная БД"),
        ("Excel", "Только экспорт из расчетных витрин отчета"),
        ("Web-кабинет", "Читает опубликованный report_id из БД"),
        ("Исходные снимки", "Не публикуются через клиентское API"),
        (
            "Происхождение данных",
            _localized_status(summary.get("meta", {}).get("lineageType", "")),
        ),
    ]
    for index, row in enumerate(rows, start=1):
        sheet.cell(index, 1, row[0])
        sheet.cell(index, 2, row[1])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    headers = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _readiness_label(summary: dict[str, Any]) -> str:
    readiness = summary.get("readiness", {})
    status = _localized_status(readiness.get("status", "")).strip()
    label = str(readiness.get("label") or "").strip()
    if status and label:
        if status == label:
            return status
        return f"{status} ({label})"
    return status or label


def _sheet_headers(sheet_key: str, rows: list[dict[str, Any]]) -> list[str]:
    if sheet_key in SHEET_COLUMNS:
        return SHEET_COLUMNS[sheet_key]
    return sorted({key for row in rows for key in row})


def _column_label(sheet_key: str, field: str) -> str:
    return SHEET_COLUMN_LABELS.get((sheet_key, field), COLUMN_LABELS.get(field, field))


def _localized_cell_value(field: str, row: dict[str, Any]) -> Any:
    value = row.get(field)
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return str(value)
    if field in STATUS_FIELDS:
        return _localized_status(value)
    return value


def _localized_status(value: object) -> str:
    text = str(value or "").strip()
    return STATUS_LABELS.get(text, text)


def _localized_source(value: object) -> str:
    text = str(value or "").strip()
    if text == "DB report marts":
        return "Расчетные витрины отчета"
    return _localized_status(text)


def _kpi_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    revenue = sum(float(row.get("revenue") or 0) for row in rows)
    profit = sum(float(row.get("profit") or 0) for row in rows)
    sales = sum(float(row.get("sales") or 0) for row in rows)
    returns = sum(float(row.get("returns") or 0) for row in rows)
    margin = profit / revenue if revenue else None
    return [
        {"metric": "Строк отчета", "value": len(rows)},
        {"metric": "Выручка", "value": round(revenue, 2)},
        {"metric": "Прибыль", "value": round(profit, 2)},
        {"metric": "Маржа", "value": round(margin, 4) if margin is not None else ""},
        {"metric": "Продажи, шт", "value": round(sales, 2)},
        {"metric": "Возвраты, шт", "value": round(returns, 2)},
    ]


def _html_table(title: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"<h2>{_html(title)}</h2><p>Нет строк</p>"
    headers = sorted({key for row in rows for key in row})
    header_html = "".join(f"<th>{_html(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(f"<td>{_html(row.get(header, ''))}</td>" for header in headers)
            + "</tr>"
        )
    return (
        f"<h2>{_html(title)}</h2><table><thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _html(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
