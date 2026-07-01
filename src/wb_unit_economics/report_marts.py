from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from wb_unit_economics.contracts import (
    DataQualityStatus,
    OnecUnfCostSnapshot,
    SkuMapping,
    UnitEconomicsReport,
)
from wb_unit_economics.excel import (
    REPORT_STATUS_LABELS,
    _account_label,
    _analysis_period_note,
    _client_unit_rows,
    _cost_article_lookup,
    _cost_method_lookup,
    _cost_name_lookup,
    _data_quality_label,
    _load_onec_stock_by_warehouse,
    _load_stock_history,
    _lost_sales_rows,
    _mapping_article_lookup,
    _month_label,
    _onec_article_label,
    _product_label,
    _row_month_start,
    _safe_margin,
    _sales_model_label,
    _status_reason,
)
from wb_unit_economics.liquidity import aggregate_liquidity_rows, liquidity_rows_payload
from wb_unit_economics.web.repository import (
    expense_payload,
    monthly_payload,
    options_payload,
    returns_payload,
)

RETURN_REASON_LIMITATION = "Причина возврата не передается текущими источниками"


@dataclass(frozen=True)
class ReportMarts:
    meta: dict[str, Any]
    options: dict[str, Any]
    monthly: list[dict[str, Any]]
    expenses: list[dict[str, Any]]
    unitRows: list[dict[str, Any]]
    liquidityRows: list[dict[str, Any]]
    returns: list[dict[str, Any]]
    lostSales: list[dict[str, Any]]
    reconciliation: list[dict[str, Any]] = field(default_factory=list)
    reconciliationMonthly: list[dict[str, Any]] = field(default_factory=list)
    documentReconciliation: list[dict[str, Any]] = field(default_factory=list)
    readiness: dict[str, Any] = field(default_factory=dict)

    def to_dashboard_payload(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "readiness": self.readiness,
            "options": self.options,
            "monthly": self.monthly,
            "expenses": self.expenses,
            "unitRows": self.unitRows,
            "liquidityRows": self.liquidityRows,
            "returns": self.returns,
            "lostSales": self.lostSales,
            "reconciliation": self.reconciliation,
            "reconciliationMonthly": self.reconciliationMonthly,
            "documentReconciliation": self.documentReconciliation,
        }


def build_report_marts(
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    stock_history_dir: Path | None = None,
    onec_stock_dir: Path | None = None,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
    client_name: str = "Шумейко и Партнеры",
    source_label: str = "DB report marts",
) -> ReportMarts:
    cost_rows = list(cost_snapshots)
    mapping_rows = list(sku_mappings)
    unit_rows = unit_rows_mart(
        report,
        cost_snapshots=cost_rows,
        sku_mappings=mapping_rows,
        account_labels=account_labels,
        organization_labels=organization_labels,
    )
    liquidity_rows = liquidity_rows_payload(aggregate_liquidity_rows(unit_rows))
    document_reconciliation = document_reconciliation_mart(
        report,
        account_labels=account_labels,
        organization_labels=organization_labels,
    )
    lost_sales = lost_sales_mart(
        report,
        cost_snapshots=cost_rows,
        sku_mappings=mapping_rows,
        stock_history_dir=stock_history_dir,
        onec_stock_dir=onec_stock_dir,
        account_labels=account_labels,
    )
    meta = {
        "title": "Кабинет юнит-экономики WB",
        "client": client_name,
        "period": _period_label(report.report_period_start, report.report_period_end),
        "reportPeriod": _period_label(
            report.report_period_start, report.report_period_end
        ),
        "periodText": _analysis_period_note(report).removeprefix("Период анализа: "),
        "periodStatus": REPORT_STATUS_LABELS.get(
            report.status.value, report.status.value
        ),
        "sourceCoverage": _source_coverage_label(report),
        "sourceCoverageStart": (
            report.source_coverage_start.isoformat()
            if report.source_coverage_start
            else ""
        ),
        "sourceCoverageEnd": (
            report.source_coverage_end.isoformat() if report.source_coverage_end else ""
        ),
        "methodologyVersion": report.methodology_version,
        "generatedAt": report.generated_at.strftime("%d.%m.%Y %H:%M"),
        "sourceWorkbook": "",
        "source": source_label,
        "lineageType": "db_first_report_marts",
        "returnReasonLimitation": RETURN_REASON_LIMITATION,
    }
    options = options_payload(
        unit_rows,
        liquidity_rows=liquidity_rows,
        document_reconciliation=document_reconciliation,
    )
    return ReportMarts(
        meta=meta,
        readiness=readiness_mart(unit_rows, report=report),
        options=options,
        monthly=monthly_payload(unit_rows),
        expenses=expense_payload(unit_rows),
        unitRows=unit_rows,
        liquidityRows=liquidity_rows,
        returns=returns_payload(unit_rows, RETURN_REASON_LIMITATION),
        lostSales=lost_sales,
        reconciliation=[],
        reconciliationMonthly=reconciliation_monthly_mart(report),
        documentReconciliation=document_reconciliation,
    )


def unit_rows_mart(
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    cost_names = _cost_name_lookup(cost_snapshots)
    cost_articles = _cost_article_lookup(cost_snapshots)
    mapping_articles = _mapping_article_lookup(sku_mappings)
    cost_methods = _cost_method_lookup(cost_snapshots)
    result: list[dict[str, Any]] = []
    for index, row in enumerate(_client_unit_rows(report.rows, cost_names), start=1):
        month_start = _row_month_start(row, report.report_period_start)
        status = _data_quality_label(row.data_quality_status)
        loss_class, loss_driver = _loss_details(row, status)
        result.append(
            {
                "id": f"unit-{index}",
                "week": row.week_start.isoformat(),
                "month": _month_label(month_start, report),
                "documentReport": row.document_report,
                "wbReportId": row.wb_report_id,
                "wbReportDate": row.wb_report_date,
                "organization": _organization_label(
                    row.organization_id, organization_labels
                ),
                "cabinet": _account_label(row.seller_account_id, account_labels),
                "product": _product_label(row, cost_names),
                "nmId": "" if row.nm_id is None else str(row.nm_id),
                "articleWb": row.vendor_code,
                "article1c": _onec_article_label(row, cost_articles, mapping_articles),
                "barcode": row.barcode,
                "scheme": _sales_model_label(row.sales_model),
                "sales": _number(row.sales_quantity),
                "returns": _number(row.return_quantity),
                "netQty": _number(row.quantity),
                "returnRate": _ratio(row.return_quantity, row.sales_quantity),
                "revenueBeforeSpp": _number(row.revenue_before_spp),
                "spp": _number(row.spp_discount),
                "sppRate": _nullable_number(row.spp_discount_rate),
                "revenue": _number(row.net_revenue),
                "vat": _number(row.vat_5_from_revenue),
                "revenueWithoutVat": _number(row.revenue_without_vat),
                "cost": _number(row.cogs_from_1c_with_extra_costs),
                "commission": _number(row.wb_commission),
                "logistics": _number(row.logistics),
                "storage": _number(row.storage),
                "acceptance": _number(row.acceptance),
                "promotion": _number(row.wb_promotion),
                "penalties": _number(row.penalties_and_holdbacks),
                "acquiring": _number(row.acquiring),
                "usn": _number(row.usn_1_from_revenue),
                "profitBeforeTax": _number(row.gross_profit),
                "profit": _number(row.profit_after_taxes),
                "margin": _nullable_number(row.margin_after_taxes),
                "unitProfit": _nullable_number(row.profit_after_taxes_per_unit),
                "status": status,
                "statusReason": _status_reason(row, cost_methods),
                "sppStatus": row.spp_source_status,
                "lossClass": loss_class,
                "lossDriver": loss_driver,
                "sourceSnapshotHashes": list(row.source_snapshot_hashes),
            }
        )
    return result


def lost_sales_mart(
    report: UnitEconomicsReport,
    *,
    cost_snapshots: Iterable[OnecUnfCostSnapshot] = (),
    sku_mappings: Iterable[SkuMapping] = (),
    stock_history_dir: Path | None = None,
    onec_stock_dir: Path | None = None,
    account_labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    cost_rows = list(cost_snapshots)
    mapping_rows = list(sku_mappings)
    cost_names = _cost_name_lookup(cost_rows)
    cost_articles = _cost_article_lookup(cost_rows)
    mapping_articles = _mapping_article_lookup(mapping_rows)
    stock_history = _load_stock_history(stock_history_dir, report)
    onec_stock = _load_onec_stock_by_warehouse(
        onec_stock_dir,
        sku_mappings=mapping_rows,
    )
    rows = _lost_sales_rows(
        report,
        cost_names=cost_names,
        cost_articles=cost_articles,
        mapping_articles=mapping_articles,
        sku_mappings=mapping_rows,
        stock_history=stock_history,
        onec_stock=onec_stock,
        account_labels=account_labels,
    )
    result = []
    for index, row in enumerate(rows, start=1):
        result.append(
            {
                "id": f"lost-{index}",
                "cabinet": row[0],
                "product": row[1],
                "nmId": "" if row[2] is None else str(row[2]),
                "articleWb": row[3],
                "article1c": row[4],
                "barcode": row[5],
                "periodDays": _number(row[6]),
                "zeroStockDays": _number(row[7]),
                "criticalStockDays": _number(row[8]),
                "onecStock": _number(row[9]),
                "onecWarehouses": row[10],
                "sales": _number(row[11]),
                "avgDailySales": _number(row[12]),
                "lostUnits": _number(row[13]),
                "lostRevenue": _number(row[14]),
                "lostProfit": _number(row[15]),
                "profitPerSale": _number(row[16]),
                "note": row[17],
                "sourceStatus": row[18],
            }
        )
    return result


def reconciliation_monthly_mart(report: UnitEconomicsReport) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Decimal]] = {}
    for row in report.report_reconciliation_rows:
        label = _month_label(_row_month_start(row, report.report_period_start), report)
        bucket = buckets.setdefault(
            label,
            {
                "wb_quantity": Decimal("0"),
                "onec_quantity": Decimal("0"),
                "quantity_delta": Decimal("0"),
                "wb_cogs": Decimal("0"),
                "onec_cogs": Decimal("0"),
                "cogs_delta": Decimal("0"),
                "wb_mp_expenses": Decimal("0"),
                "onec_mp_expenses": Decimal("0"),
                "mp_expenses_delta": Decimal("0"),
            },
        )
        bucket["wb_quantity"] += row.quantity
        bucket["onec_quantity"] += row.quantity
        bucket["wb_cogs"] += row.cogs_from_1c_with_extra_costs
        bucket["onec_cogs"] += row.cogs_from_1c_with_extra_costs
        wb_expenses = (
            row.wb_commission
            + row.logistics
            + row.storage
            + row.acceptance
            + row.wb_promotion
            + row.penalties_and_holdbacks
            + row.acquiring
        )
        bucket["wb_mp_expenses"] += wb_expenses
        bucket["onec_mp_expenses"] += wb_expenses
    result = []
    for month, values in buckets.items():
        result.append(
            {
                "month": month,
                "wb_quantity": _number(values["wb_quantity"]),
                "onec_quantity": _number(values["onec_quantity"]),
                "quantity_delta": _number(values["quantity_delta"]),
                "wb_cogs": _number(values["wb_cogs"]),
                "onec_cogs": _number(values["onec_cogs"]),
                "cogs_delta": _number(values["cogs_delta"]),
                "wb_mp_expenses": _number(values["wb_mp_expenses"]),
                "onec_mp_expenses": _number(values["onec_mp_expenses"]),
                "mp_expenses_delta": _number(values["mp_expenses_delta"]),
                "comment": (
                    "DB-first контрольная витрина; детальная сверка 1С ОПиУ "
                    "добавляется отдельным источником."
                ),
            }
        )
    return result


def document_reconciliation_mart(
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    result = []
    for index, row in enumerate(report.onec_report_reconciliation_rows, start=1):
        result.append(
            {
                "id": f"document-reconciliation-{index}",
                "status": _data_quality_label(row.data_quality_status),
                "payoutStatus": "",
                "periodStatus": _period_status(row.week_end, report.report_period_end),
                "documentReport": _document_report_label(
                    row.document_label,
                    row.week_start,
                    row.week_end,
                    row.document_date,
                ),
                "salesPeriod": (
                    f"{row.week_start.isoformat()} - {row.week_end.isoformat()}"
                ),
                "salesPeriodStart": row.week_start.isoformat(),
                "salesPeriodEnd": row.week_end.isoformat(),
                "expectedDocumentDate": row.document_date.isoformat(),
                "documentType": row.document_label,
                "cabinet": _account_label(row.seller_account_id, account_labels),
                "organization": _organization_label(
                    row.organization_id, organization_labels
                ),
                "summaryReportId": "",
                "weeklySalesReportId": "",
                "weeklyBuyoutReportId": "",
                "wbReportIds": ", ".join(row.wb_report_ids),
                "onecDocuments": "",
                "onecDocumentTypes": "",
                "onecDocumentDates": "",
                "wbSalesQuantity": _number(row.sales_quantity),
                "wbReturnQuantity": _number(row.return_quantity),
                "wbNetQuantity": _number(row.quantity),
                "onecSalesQuantity": None,
                "onecReturnQuantity": None,
                "onecNetQuantity": None,
                "salesQuantityDelta": None,
                "returnQuantityDelta": None,
                "netQuantityDelta": None,
                "wbQuantity": _number(row.quantity),
                "onecQuantity": None,
                "quantityDelta": None,
                "wbAmount": _number(row.revenue_after_spp),
                "onecAmount": None,
                "amountDelta": None,
                "buyoutRetailAmountSum": None,
                "buyoutForPaySum": None,
                "buyoutBankPaymentSum": None,
                "onecExpenseInvoiceAmount": None,
                "buyoutRetailDelta": None,
                "buyoutForPayDelta": None,
                "buyoutBankDelta": None,
                "pdfBankPayment": None,
                "wbForPaySum": None,
                "onecSettlementTotal": None,
                "settlementDelta": None,
                "onecSourceRows": None,
                "comment": (
                    "Ожидаемый документ из расчетной витрины; факт 1С "
                    "сверяется отдельным source layer."
                ),
            }
        )
    return result


def readiness_mart(
    unit_rows: list[dict[str, Any]],
    *,
    report: UnitEconomicsReport | None = None,
) -> dict[str, Any]:
    problem_statuses = {
        "Нет себестоимости 1С",
        "Нет сопоставления WB-1С",
        "Неоднозначное сопоставление",
        "Неполный источник",
    }
    problem_rows = [
        row for row in unit_rows if str(row.get("status") or "") in problem_statuses
    ]
    coverage_gap = _source_coverage_gap(report)
    partial_source = any(
        str(row.get("status") or "") == "Неполный источник" for row in unit_rows
    )
    partial_period = _partial_report_period(report)
    if coverage_gap:
        status = "source_coverage_gap"
    elif partial_source:
        status = "partial_source"
    elif partial_period:
        status = "partial_period"
    elif not problem_rows and unit_rows:
        status = "ready"
    else:
        status = "needs_review"
    review_reasons = []
    if problem_rows:
        review_reasons.append(
            {
                "code": "data_quality_review",
                "message": "Есть строки, которые нельзя считать reliable без проверки.",
                "count": len(problem_rows),
            }
        )
    if partial_source:
        review_reasons.append(
            {
                "code": "partial_source",
                "message": "Есть строки с неполными источниками данных.",
            }
        )
    if partial_period:
        review_reasons.append(
            {
                "code": "partial_period",
                "message": "Период отчета помечен как неполный.",
            }
        )
    if coverage_gap:
        review_reasons.append(
            {
                "code": "source_coverage_gap",
                "message": (
                    "Покрытие источников не закрывает выбранный период отчета."
                ),
            }
        )
    return {
        "status": status,
        "score": 100 if status == "ready" else 80,
        "blockingReasons": [],
        "reviewReasons": review_reasons,
    }


def _partial_report_period(report: UnitEconomicsReport | None) -> bool:
    if report is None:
        return False
    _, last_day = monthrange(
        report.report_period_end.year,
        report.report_period_end.month,
    )
    return report.report_period_end.day < last_day


def _loss_details(row: object, status: str) -> tuple[str, str]:
    if row.data_quality_status is not DataQualityStatus.RELIABLE:
        return "Нужна проверка данных", status
    profit = row.profit_after_taxes
    if profit >= 0:
        return "Прибыльный / нейтральный", "Маржинальный доход не отрицательный"
    return_rate = _safe_margin(row.return_quantity, row.sales_quantity) or Decimal("0")
    factors = {
        "Высокая себестоимость": row.cogs_from_1c_with_extra_costs,
        "Высокая логистика WB": row.logistics,
        "Высокая комиссия WB": row.wb_commission,
        "Высокое хранение WB": row.storage,
        "WB Продвижение": row.wb_promotion,
        "Штрафы/удержания WB": row.penalties_and_holdbacks,
        "Эквайринг WB": row.acquiring,
        "Налоги": row.vat_5_from_revenue + row.usn_1_from_revenue,
    }
    if return_rate >= Decimal("0.18"):
        factors["Возвраты + логистика"] = abs(row.return_amount) + row.logistics
    driver = max(factors.items(), key=lambda item: item[1])[0]
    if driver == "Высокая себестоимость":
        return "Высокая закупка / недостаточная наценка", driver
    if driver == "Возвраты + логистика":
        return "Возвраты + логистика", driver
    return "Прочие расходы", driver


def _period_label(start: date, end: date) -> str:
    return f"{start:%d.%m.%Y} - {end:%d.%m.%Y}"


def _source_coverage_label(report: UnitEconomicsReport) -> str:
    if report.source_coverage_start is None or report.source_coverage_end is None:
        return ""
    return _period_label(report.source_coverage_start, report.source_coverage_end)


def _source_coverage_gap(report: UnitEconomicsReport | None) -> bool:
    if report is None:
        return False
    if report.source_coverage_start is None or report.source_coverage_end is None:
        return True
    return (
        report.source_coverage_start > report.report_period_start
        or report.source_coverage_end < report.report_period_end
    )


def _document_report_label(
    document_label: str,
    week_start: date,
    week_end: date,
    document_date: date,
) -> str:
    return (
        f"{document_label} · {week_start:%d.%m.%Y}-{week_end:%d.%m.%Y} · "
        f"закрытие {document_date:%d.%m.%Y}"
    )


def _period_status(week_end: date, report_end: date) -> str:
    return "неполный период" if week_end > report_end else "полный период"


def _organization_label(
    organization_id: str,
    organization_labels: Mapping[str, str] | None,
) -> str:
    return (organization_labels or {}).get(organization_id, organization_id)


def _number(value: object) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _nullable_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    value = _safe_margin(numerator, denominator)
    return None if value is None else float(value)
