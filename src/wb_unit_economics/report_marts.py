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
    OnecGrossProfitDocumentRow,
    OnecMarketplaceServiceRow,
    OnecUnfCostSnapshot,
    SkuMapping,
    UnitEconomicsReport,
    WbSalesReportSummaryRow,
)
from wb_unit_economics.excel import (
    REPORT_STATUS_LABELS,
    _account_label,
    _analysis_period_note,
    _apply_accounting_period_dates,
    _client_unit_rows,
    _cost_article_lookup,
    _cost_method_lookup,
    _cost_name_lookup,
    _data_quality_label,
    _document_reconciliation_actuals,
    _document_reconciliation_row,
    _index_onec_document_rows,
    _load_onec_stock_by_warehouse,
    _load_stock_history,
    _lost_sales_rows,
    _mapping_article_lookup,
    _match_onec_document_rows,
    _matched_onec_gross_profit_totals_by_document_month,
    _month_label,
    _onec_article_label,
    _onec_document_actual_key,
    _product_label,
    _row_month_start,
    _safe_margin,
    _sales_model_label,
    _status_reason,
    _unmatched_onec_document_row,
    _weekly_summary_rows_by_type,
)
from wb_unit_economics.liquidity import aggregate_liquidity_rows, liquidity_rows_payload
from wb_unit_economics.onec_opiu import OnecOpiuSummary
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
    lostSalesCoverage: dict[str, Any] = field(default_factory=dict)
    reconciliation: list[dict[str, Any]] = field(default_factory=list)
    reconciliationMonthly: list[dict[str, Any]] = field(default_factory=list)
    marketplaceServiceRows: list[dict[str, Any]] = field(default_factory=list)
    documentReconciliation: list[dict[str, Any]] = field(default_factory=list)
    taxInputReconciliation: list[dict[str, Any]] = field(default_factory=list)
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
            "lostSalesCoverage": self.lostSalesCoverage,
            "reconciliation": self.reconciliation,
            "reconciliationMonthly": self.reconciliationMonthly,
            "marketplaceServiceRows": self.marketplaceServiceRows,
            "documentReconciliation": self.documentReconciliation,
            "taxInputReconciliation": self.taxInputReconciliation,
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
    onec_gross_profit_rows: Iterable[OnecGrossProfitDocumentRow] = (),
    onec_marketplace_service_rows: Iterable[OnecMarketplaceServiceRow] = (),
    wb_sales_report_summary_rows: Iterable[WbSalesReportSummaryRow] = (),
    onec_opiu_summary: OnecOpiuSummary | None = None,
    source_run_id: str = "",
    client_name: str = "Шумейко и Партнеры",
    source_label: str = "DB report marts",
) -> ReportMarts:
    cost_rows = list(cost_snapshots)
    mapping_rows = list(sku_mappings)
    onec_gross_rows = list(onec_gross_profit_rows)
    onec_service_rows = list(onec_marketplace_service_rows)
    wb_summary_rows = list(wb_sales_report_summary_rows)
    _apply_accounting_period_dates(report, onec_gross_rows, wb_summary_rows)
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
        onec_gross_profit_rows=onec_gross_rows,
        wb_sales_report_summary_rows=wb_summary_rows,
        account_labels=account_labels,
        organization_labels=organization_labels,
    )
    tax_input_reconciliation = tax_input_reconciliation_mart(
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
    lost_sales_coverage = lost_sales_coverage_mart(
        report,
        stock_history_dir=stock_history_dir,
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
        "marketplaceExpenseContextVersion": "marketplace-expense-reconciliation-v1",
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
        monthly=monthly_payload(
            unit_rows,
            period_start=report.report_period_start,
            period_end=report.report_period_end,
        ),
        expenses=expense_payload(unit_rows),
        unitRows=unit_rows,
        liquidityRows=liquidity_rows,
        returns=returns_payload(unit_rows, RETURN_REASON_LIMITATION),
        lostSales=lost_sales,
        lostSalesCoverage=lost_sales_coverage,
        reconciliation=[],
        reconciliationMonthly=reconciliation_monthly_mart(
            report,
            onec_gross_profit_rows=onec_gross_rows,
            wb_sales_report_summary_rows=wb_summary_rows,
            onec_opiu_summary=onec_opiu_summary,
            source_run_id=source_run_id,
        ),
        marketplaceServiceRows=marketplace_service_rows_mart(
            report,
            onec_service_rows,
            account_labels=account_labels,
            organization_labels=organization_labels,
        ),
        documentReconciliation=document_reconciliation,
        taxInputReconciliation=tax_input_reconciliation,
    )


def marketplace_expense_control_group(category: str) -> str:
    normalized = category.strip().casefold()
    if "продвиж" in normalized:
        return "promotion"
    if any(marker in normalized for marker in ("штраф", "пен", "доплат")):
        return "penalties"
    return "core_services"


def marketplace_service_rows_mart(
    report: UnitEconomicsReport,
    rows: Iterable[OnecMarketplaceServiceRow],
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    accounts_by_organization: dict[str, set[str]] = {}
    for report_row in report.rows:
        accounts_by_organization.setdefault(report_row.organization_id, set()).add(
            report_row.seller_account_id
        )
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        accounts = sorted(accounts_by_organization.get(row.organization_id, set()))
        seller_account_id = accounts[0] if len(accounts) == 1 else ""
        match_status = row.match_status
        if len(accounts) > 1:
            match_status = "ambiguous_cabinet_allocation"
        elif not accounts:
            match_status = "missing_cabinet_mapping"
        control_group = marketplace_expense_control_group(row.service_category)
        recognition_date = (
            row.input_date or row.document_date
            if control_group == "penalties"
            else row.week_end
        )
        result.append(
            {
                "id": f"marketplace-service-{index}-{row.source_row_hash[:16]}",
                "clientId": row.client_id,
                "sellerAccountId": seller_account_id,
                "cabinet": (
                    _account_label(seller_account_id, account_labels)
                    if seller_account_id
                    else ""
                ),
                "organizationId": row.organization_id,
                "organization": _organization_label(
                    row.organization_id, organization_labels
                ),
                "counterpartyId": row.counterparty_id,
                "periodStart": row.week_start.isoformat(),
                "periodEnd": row.week_end.isoformat(),
                "recognitionDate": recognition_date.isoformat(),
                "documentDate": row.document_date.isoformat(),
                "inputDate": row.input_date.isoformat() if row.input_date else "",
                "documentId": row.document_id,
                "documentNumber": row.document_number,
                "inputNumber": row.input_number,
                "documentComment": row.document_comment,
                "serviceCategory": row.service_category,
                "controlGroup": control_group,
                "serviceName": row.service_name,
                "amountWithoutVat": _number(row.amount),
                "vat": _number(row.vat),
                "amountWithVat": _number(row.total),
                "sourceKind": row.source_kind,
                "matchStatus": match_status,
                "sourceRowHash": row.source_row_hash,
            }
        )
    return result


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
        pnl_revenue = (
            row.revenue_without_vat
            if row.pnl_vat_mode == "without_vat_for_osno"
            else row.net_revenue
        )
        after_cost = pnl_revenue - row.cogs_from_1c_with_extra_costs
        after_commission = after_cost - row.wb_commission
        after_logistics = after_commission - row.logistics
        after_storage = after_logistics - row.storage
        after_acceptance = after_storage - row.acceptance
        after_promotion = after_acceptance - row.wb_promotion
        after_penalties = after_promotion - row.penalties_and_holdbacks
        before_vat_adjustment = after_penalties - row.acquiring
        pnl_vat_adjustment = row.gross_profit - before_vat_adjustment
        included_taxes = row.gross_profit - row.profit_after_taxes
        result.append(
            {
                "id": f"unit-{index}",
                "week": row.week_start.isoformat(),
                "accountingPeriodDate": (
                    row.accounting_period_date.isoformat()
                    if row.accounting_period_date
                    else ""
                ),
                "accountingPeriodSource": row.accounting_period_source,
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
                "vatOutput": _number(row.vat_output),
                "vatInput": _number(row.vat_input),
                "vatInputFromWb": _number(row.vat_input_from_wb),
                "vatInputFrom1c": _number(row.vat_input_from_1c),
                "vatInputFromImportScenario": _number(
                    row.vat_input_from_import_scenario
                ),
                "vatInputFromWbScenario": _number(row.vat_input_from_wb_scenario),
                "vatInputDifference": _number(row.vat_input_difference),
                "vatInputCompleteness": row.vat_input_completeness,
                "inputVatMode": row.input_vat_mode,
                "vatInputConfirmed": row.vat_input_confirmed,
                "vatPayable": _number(row.vat_payable),
                "revenueWithoutVat": _number(row.revenue_without_vat),
                "pnlRevenue": _number(pnl_revenue),
                "cost": _number(row.cogs_from_1c_with_extra_costs),
                "afterCost": _number(after_cost),
                "unitCost": _nullable_number(row.unit_cost),
                "costMethod": row.cost_method,
                "costMatchStatus": row.cost_match_status,
                "costSourceKind": row.cost_source_kind,
                "costSourcePeriodStart": (
                    row.cost_source_period_start.isoformat()
                    if row.cost_source_period_start
                    else ""
                ),
                "costSourcePeriodEnd": (
                    row.cost_source_period_end.isoformat()
                    if row.cost_source_period_end
                    else ""
                ),
                "costSourceDocument": row.cost_source_document,
                "commission": _number(row.wb_commission),
                "afterCommission": _number(after_commission),
                "logistics": _number(row.logistics),
                "afterLogistics": _number(after_logistics),
                "storage": _number(row.storage),
                "afterStorage": _number(after_storage),
                "acceptance": _number(row.acceptance),
                "afterAcceptance": _number(after_acceptance),
                "promotion": _number(row.wb_promotion),
                "afterPromotion": _number(after_promotion),
                "penalties": _number(row.penalties_and_holdbacks),
                "afterPenalties": _number(after_penalties),
                "acquiring": _number(row.acquiring),
                "beforeVatAdjustment": _number(before_vat_adjustment),
                "pnlVatAdjustment": _number(pnl_vat_adjustment),
                "usn": _number(row.usn_1_from_revenue),
                "incomeTaxKind": row.income_tax_kind,
                "incomeTaxBase": _number(row.income_tax_base),
                "incomeTax": _number(row.income_tax),
                "incomeTaxIncluded": row.income_tax_included,
                "profitBeforeTax": _number(row.gross_profit),
                "includedTaxes": _number(included_taxes),
                "profit": _number(row.profit_after_taxes),
                "margin": _nullable_number(row.margin_after_taxes),
                "unitProfit": _nullable_number(row.profit_after_taxes_per_unit),
                "taxMethod": row.tax_method,
                "taxProfileSource": row.tax_profile_source,
                "taxCompleteness": row.tax_completeness,
                "pnlVatMode": row.pnl_vat_mode,
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
                "lostContributionMargin": _number(row[15]),
                "lostProfit": _number(row[15]),
                "preventedLoss": (
                    _number(abs(Decimal(str(row[13])) * Decimal(str(row[16]))))
                    if Decimal(str(row[16])) < 0
                    else 0.0
                ),
                "profitPerSale": _number(row[16]),
                "estimateType": (
                    "prevented_loss" if Decimal(str(row[16])) < 0 else "lost_margin"
                ),
                "note": row[17],
                "sourceStatus": row[18],
                "calculationContext": row[19],
            }
        )
    return result


def lost_sales_coverage_mart(
    report: UnitEconomicsReport,
    *,
    stock_history_dir: Path | None,
    account_labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    coverage = _load_stock_history(stock_history_dir, report)
    accounts = []
    for item in coverage.get("accounts", []):
        if not isinstance(item, Mapping):
            continue
        seller_account_id = str(item.get("seller_account_id") or "")
        accounts.append(
            {
                "sellerAccountId": seller_account_id,
                "cabinet": _account_label(seller_account_id, account_labels),
                "status": str(item.get("status") or "incomplete"),
                "coveredDays": int(item.get("covered_days") or 0),
                "totalDays": int(item.get("total_days") or 0),
                "calculated": bool(item.get("calculated")),
                "providerWindowCalculated": bool(
                    item.get("provider_window_calculated")
                ),
                "fullCoverage": bool(item.get("full_coverage")),
                "calculationPeriodStart": item.get("calculation_period_start"),
                "calculationPeriodEnd": item.get("calculation_period_end"),
                "extrapolated": False,
            }
        )
    return {
        "status": str(coverage.get("status") or "not_loaded"),
        "calculated": bool(coverage.get("calculated")),
        "providerWindowCalculated": bool(
            coverage.get("provider_window_calculated")
        ),
        "fullCoverage": bool(coverage.get("full_coverage")),
        "coveredDays": int(coverage.get("covered_days") or 0),
        "totalDays": int(coverage.get("total_days") or 0),
        "calculationPeriodStart": coverage.get("calculation_period_start"),
        "calculationPeriodEnd": coverage.get("calculation_period_end"),
        "calculationContextVersion": "lost-sales-filter-v1",
        "extrapolated": False,
        "message": str(coverage.get("message") or coverage.get("source_label") or ""),
        "accounts": accounts,
    }


def reconciliation_monthly_mart(
    report: UnitEconomicsReport,
    *,
    onec_gross_profit_rows: Iterable[OnecGrossProfitDocumentRow] = (),
    wb_sales_report_summary_rows: Iterable[WbSalesReportSummaryRow] = (),
    onec_opiu_summary: OnecOpiuSummary | None = None,
    source_run_id: str = "",
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Decimal | bool]] = {}
    for row in report.rows:
        label = _month_label(_row_month_start(row, report.report_period_start), report)
        bucket = buckets.setdefault(
            label,
            {
                "wb_quantity": Decimal("0"),
                "wb_cogs": Decimal("0"),
                "wb_mp_expenses": Decimal("0"),
                "onec_quantity": Decimal("0"),
                "onec_cogs": Decimal("0"),
                "onec_mp_expenses": Decimal("0"),
                "onec_matched_documents_available": False,
                "onec_opiu_available": False,
            },
        )
        bucket["wb_quantity"] += row.quantity
        bucket["wb_cogs"] += row.cogs_from_1c_with_extra_costs
        bucket["wb_mp_expenses"] += (
            row.revenue_without_vat
            - row.gross_profit
            - row.cogs_from_1c_with_extra_costs
        )

    matched_by_month = _matched_onec_gross_profit_totals_by_document_month(
        report,
        onec_gross_profit_rows,
        wb_sales_report_summary_rows,
        period_start=report.report_period_start,
        period_end=report.report_period_end,
    )
    for month_key, values in matched_by_month.items():
        month = date.fromisoformat(f"{month_key}-01")
        label = _month_label(month, report)
        bucket = buckets.setdefault(label, _empty_monthly_reconciliation_bucket())
        bucket["onec_quantity"] += Decimal(values["quantity"])
        bucket["onec_cogs"] += Decimal(values["cogs"])
        bucket["onec_matched_documents_available"] = True

    monthly_opiu_values = (
        onec_opiu_summary.monthly_values if onec_opiu_summary else {}
    )
    for month_key, values in monthly_opiu_values.items():
        month = date.fromisoformat(f"{month_key}-01")
        label = _month_label(month, report)
        bucket = buckets.setdefault(label, _empty_monthly_reconciliation_bucket())
        bucket["onec_mp_expenses"] += Decimal(values.get("rwb_total", Decimal("0")))
        bucket["onec_opiu_available"] = True

    result = []
    for month, values in buckets.items():
        onec_quantity = (
            Decimal(values["onec_quantity"])
            if values["onec_matched_documents_available"]
            else None
        )
        onec_cogs = (
            Decimal(values["onec_cogs"])
            if values["onec_matched_documents_available"]
            else None
        )
        onec_mp_expenses = (
            Decimal(values["onec_mp_expenses"])
            if values["onec_opiu_available"]
            else None
        )
        quantity_delta = (
            onec_quantity - Decimal(values["wb_quantity"])
            if onec_quantity is not None
            else None
        )
        cogs_delta = (
            onec_cogs - Decimal(values["wb_cogs"]) if onec_cogs is not None else None
        )
        mp_expenses_delta = (
            onec_mp_expenses - Decimal(values["wb_mp_expenses"])
            if onec_mp_expenses is not None
            else None
        )
        status = _monthly_reconciliation_status(
            quantity_delta,
            cogs_delta,
            mp_expenses_delta,
        )
        result.append(
            {
                "month": month,
                "wb_quantity": _number(values["wb_quantity"]),
                "onec_quantity": _nullable_number(onec_quantity),
                "quantity_delta": _nullable_number(quantity_delta),
                "wb_cogs": _number(values["wb_cogs"]),
                "onec_cogs": _nullable_number(onec_cogs),
                "cogs_delta": _nullable_number(cogs_delta),
                "wb_mp_expenses": _number(values["wb_mp_expenses"]),
                "onec_mp_expenses": _nullable_number(onec_mp_expenses),
                "mp_expenses_delta": _nullable_number(mp_expenses_delta),
                "status": status,
                "wbBasis": "accounting_period_date; P&L без НДС",
                "onecBasis": (
                    "сопоставленные WB-документы 1С; расходы МП по ОПиУ"
                ),
                "sourceRunId": source_run_id,
                "comment": _monthly_reconciliation_comment(status),
            }
        )
    return sorted(result, key=lambda item: item["month"])


def _empty_monthly_reconciliation_bucket() -> dict[str, Decimal | bool]:
    return {
        "wb_quantity": Decimal("0"),
        "wb_cogs": Decimal("0"),
        "wb_mp_expenses": Decimal("0"),
        "onec_quantity": Decimal("0"),
        "onec_cogs": Decimal("0"),
        "onec_mp_expenses": Decimal("0"),
        "onec_matched_documents_available": False,
        "onec_opiu_available": False,
    }


def _monthly_reconciliation_status(*deltas: Decimal | None) -> str:
    if any(value is None for value in deltas):
        return "Нет источника 1С"
    if all(abs(value or Decimal("0")) <= Decimal("1") for value in deltas):
        return "Сходится"
    return "Расхождение"


def _monthly_reconciliation_comment(status: str) -> str:
    if status == "Сходится":
        return "Независимые суммы WB и 1С сходятся в пределах 1 ₽."
    if status == "Нет источника 1С":
        return "Отсутствующий источник оставлен пустым и не подменен нулем."
    return (
        "Требуется документальная расшифровка дельты; "
        "взаимозачет недель не закрывает сверку."
    )


def document_reconciliation_mart(
    report: UnitEconomicsReport,
    *,
    onec_gross_profit_rows: Iterable[OnecGrossProfitDocumentRow] = (),
    wb_sales_report_summary_rows: Iterable[WbSalesReportSummaryRow] = (),
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    onec_rows = list(onec_gross_profit_rows)
    weekly_summaries = _weekly_summary_rows_by_type(wb_sales_report_summary_rows)
    onec_index = _index_onec_document_rows(onec_rows)
    matched_actual_keys: set[tuple[object, ...]] = set()
    result: list[dict[str, Any]] = []
    for index, row in enumerate(report.onec_report_reconciliation_rows, start=1):
        sales_summaries = weekly_summaries.get(
            (row.seller_account_id, row.week_start, "Отчет комиссионера"),
            [],
        )
        buyout_summaries = weekly_summaries.get(
            (row.seller_account_id, row.week_start, "Уведомление о выкупе"),
            [],
        )
        summaries = weekly_summaries.get(
            (row.seller_account_id, row.week_start, row.document_label),
            [],
        )
        matched_candidates = _match_onec_document_rows(row, onec_index, summaries)
        actuals = _document_reconciliation_actuals(matched_candidates)
        for actual in actuals:
            matched_actual_keys.add(_onec_document_actual_key(actual))
        reconciled = _document_reconciliation_row(
            row,
            actuals,
            summaries,
            report_period_end=report.report_period_end,
            sales_summaries=sales_summaries,
            buyout_summaries=buyout_summaries,
            account_labels=account_labels,
            organization_labels=organization_labels,
        )
        result.append(
            _document_reconciliation_payload(
                index,
                reconciled,
                document_report=_document_report_label(
                    row.document_label,
                    row.week_start,
                    row.week_end,
                    row.document_date,
                ),
            )
        )
    for actual in onec_rows:
        if _onec_document_actual_key(actual) in matched_actual_keys:
            continue
        if not (
            report.report_period_start
            <= actual.document_date
            <= report.report_period_end
        ):
            continue
        unmatched = _unmatched_onec_document_row(
            actual,
            organization_labels=organization_labels,
        )
        result.append(
            _document_reconciliation_payload(
                len(result) + 1,
                unmatched,
                document_report=str(unmatched["document_label"]),
            )
        )
    return result


def _document_reconciliation_payload(
    index: int,
    row: Mapping[str, object],
    *,
    document_report: str,
) -> dict[str, Any]:
    sales_period = str(row["sales_period"])
    period_parts = sales_period.split(" - ", maxsplit=1)
    sales_period_start = period_parts[0] if period_parts else ""
    sales_period_end = period_parts[1] if len(period_parts) > 1 else ""
    expected_document_date = row["expected_document_date"]
    return {
        "id": f"document-reconciliation-{index}",
        "status": str(row["status"]),
        "payoutStatus": str(row["payout_status"]),
        "periodStatus": str(row["period_status"]),
        "documentReport": document_report,
        "salesPeriod": sales_period,
        "salesPeriodStart": sales_period_start,
        "salesPeriodEnd": sales_period_end,
        "expectedDocumentDate": (
            expected_document_date.isoformat()
            if isinstance(expected_document_date, date)
            else str(expected_document_date)
        ),
        "documentType": str(row["document_label"]),
        "cabinet": str(row["account_label"]),
        "organization": str(row["organization_label"]),
        "summaryReportId": str(row["summary_report_ids"]),
        "weeklySalesReportId": str(row["weekly_sales_report_ids"]),
        "weeklyBuyoutReportId": str(row["weekly_buyout_report_ids"]),
        "wbReportIds": str(row["wb_report_ids"]),
        "onecDocuments": str(row["onec_document_ids"]),
        "onecDocumentTypes": str(row["onec_document_types"]),
        "onecDocumentDates": str(row["onec_document_dates"]),
        "wbSalesQuantity": _nullable_number(row["expected_sales_quantity"]),
        "wbReturnQuantity": _nullable_number(row["expected_return_quantity"]),
        "wbNetQuantity": _nullable_number(row["expected_net_quantity"]),
        "onecSalesQuantity": _nullable_number(row["onec_sales_quantity"]),
        "onecReturnQuantity": _nullable_number(row["onec_return_quantity"]),
        "onecNetQuantity": _nullable_number(row["onec_net_quantity"]),
        "salesQuantityDelta": _nullable_number(row["sales_quantity_delta"]),
        "returnQuantityDelta": _nullable_number(row["return_quantity_delta"]),
        "netQuantityDelta": _nullable_number(row["net_quantity_delta"]),
        "wbQuantity": _nullable_number(row["expected_quantity"]),
        "onecQuantity": _nullable_number(row["onec_quantity"]),
        "quantityDelta": _nullable_number(row["quantity_delta"]),
        "wbAmount": _nullable_number(row["expected_amount"]),
        "onecAmount": _nullable_number(row["onec_amount"]),
        "amountDelta": _nullable_number(row["amount_delta"]),
        "buyoutRetailAmountSum": _nullable_number(row["buyout_retail_amount_sum"]),
        "buyoutForPaySum": _nullable_number(row["buyout_for_pay_sum"]),
        "buyoutBankPaymentSum": _nullable_number(row["buyout_bank_payment_sum"]),
        "onecExpenseInvoiceAmount": _nullable_number(
            row["onec_expense_invoice_amount"]
        ),
        "buyoutRetailDelta": _nullable_number(row["buyout_retail_delta"]),
        "buyoutForPayDelta": _nullable_number(row["buyout_for_pay_delta"]),
        "buyoutBankDelta": _nullable_number(row["buyout_bank_delta"]),
        "pdfBankPayment": _nullable_number(row["summary_bank"]),
        "wbForPaySum": _nullable_number(row["expected_settlement"]),
        "onecSettlementTotal": _nullable_number(row["onec_settlement"]),
        "settlementDelta": _nullable_number(row["settlement_delta"]),
        "onecVat": _nullable_number(row["onec_vat"]),
        "onecCogs": _nullable_number(row["onec_cogs"]),
        "onecCogsWithoutVat": _nullable_number(row["onec_cogs_without_vat"]),
        "onecGrossProfit": _nullable_number(row["onec_gross_profit"]),
        "onecSourceRows": row["onec_source_rows"],
        "comment": str(row["comment"]),
    }


def tax_input_reconciliation_mart(
    report: UnitEconomicsReport,
    *,
    account_labels: Mapping[str, str] | None = None,
    organization_labels: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[date, str, str], dict[str, Any]] = {}
    for row in report.rows:
        key = (row.week_start, row.seller_account_id, row.organization_id)
        bucket = buckets.setdefault(
            key,
            {
                "week": row.week_start.isoformat(),
                "weekEnd": row.week_end.isoformat(),
                "cabinet": _account_label(row.seller_account_id, account_labels),
                "organization": _organization_label(
                    row.organization_id, organization_labels
                ),
                "vatInputFromWb": Decimal("0"),
                "vatInputFromWbCharges": Decimal("0"),
                "vatInputFromWbReversals": Decimal("0"),
                "vatInputFrom1c": Decimal("0"),
                "vatInputFrom1cCharges": Decimal("0"),
                "vatInputFrom1cReversals": Decimal("0"),
                "sourceRowCount": 0,
                "statuses": set(),
            },
        )
        wb_value = row.vat_input_from_wb
        onec_value = row.vat_input_from_1c
        bucket["vatInputFromWb"] += wb_value
        bucket["vatInputFrom1c"] += onec_value
        bucket["sourceRowCount"] += 1
        if row.vat_input_completeness:
            bucket["statuses"].add(row.vat_input_completeness)
    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        wb_net = bucket["vatInputFromWb"]
        onec_net = bucket["vatInputFrom1c"]
        bucket["vatInputFromWbCharges"] = max(wb_net, Decimal("0"))
        bucket["vatInputFromWbReversals"] = min(wb_net, Decimal("0"))
        bucket["vatInputFrom1cCharges"] = max(onec_net, Decimal("0"))
        bucket["vatInputFrom1cReversals"] = min(onec_net, Decimal("0"))
        onec_has_documents = bool(
            bucket["vatInputFrom1cCharges"] or bucket["vatInputFrom1cReversals"]
        )
        statuses = bucket.pop("statuses")
        bucket.update(
            {
                "vatInputFromWb": _number(wb_net),
                "vatInputFromWbCharges": _number(bucket["vatInputFromWbCharges"]),
                "vatInputFromWbReversals": _number(
                    bucket["vatInputFromWbReversals"]
                ),
                "vatInputFrom1c": _number(onec_net),
                "vatInputFrom1cCharges": _number(bucket["vatInputFrom1cCharges"]),
                "vatInputFrom1cReversals": _number(
                    bucket["vatInputFrom1cReversals"]
                ),
                "vatInputDifference": _number(onec_net - wb_net),
                "vatInputCompleteness": (
                    _worst_vat_reconciliation_status(statuses)
                    if onec_has_documents
                    else "missing"
                ),
                "wbEvidenceStatus": "confirmed" if wb_net else "missing",
                "onecEvidenceStatus": (
                    "confirmed" if onec_has_documents else "missing"
                ),
                "vatDeductionMode": "unknown",
                "wbSource": "WB weekly realization report",
                "onecSource": (
                    "1C confirming documents" if onec_has_documents else "missing"
                ),
            }
        )
        result.append(bucket)
    result.sort(
        key=lambda item: (abs(float(item["vatInputDifference"])), item["week"]),
        reverse=True,
    )
    for index, item in enumerate(result, start=1):
        item["id"] = f"tax-input-reconciliation-{index}"
    return result


def _worst_vat_reconciliation_status(statuses: set[str]) -> str:
    priority = {"mismatch": 30, "partial": 20, "missing": 10, "confirmed": 0}
    if not statuses:
        return "missing"
    return max(statuses, key=lambda status: priority.get(status, 0))


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
    if _is_penalty_only_row(row):
        return (
            "Штрафной инцидент без продаж",
            "Штраф WB при отсутствии продаж, возвратов и товарной себестоимости",
        )
    if row.data_quality_status is not DataQualityStatus.RELIABLE:
        return "Нужна проверка данных", status
    profit = row.profit_after_taxes
    if profit >= 0:
        return "Прибыльный / нейтральный", "Маржинальный доход не отрицательный"
    return_rate = _safe_margin(row.return_quantity, row.sales_quantity) or Decimal("0")
    tax_factor = row.usn_1_from_revenue
    if getattr(row, "pnl_vat_mode", "") != "without_vat_for_osno":
        tax_factor += row.vat_5_from_revenue
    factors = {
        "Высокая себестоимость": row.cogs_from_1c_with_extra_costs,
        "Высокая логистика WB": row.logistics,
        "Высокая комиссия WB": row.wb_commission,
        "Высокое хранение WB": row.storage,
        "WB Продвижение": row.wb_promotion,
        "Штрафы/удержания WB": row.penalties_and_holdbacks,
        "Эквайринг WB": row.acquiring,
        "Налоги": tax_factor,
    }
    if return_rate >= Decimal("0.18"):
        factors["Возвраты + логистика"] = abs(row.return_amount) + row.logistics
    driver = max(factors.items(), key=lambda item: item[1])[0]
    if driver == "Высокая себестоимость":
        return "Высокая закупка / недостаточная наценка", driver
    if driver == "Возвраты + логистика":
        return "Возвраты + логистика", driver
    return "Прочие расходы", driver


def _is_penalty_only_row(row: object) -> bool:
    return (
        row.sales_quantity == 0
        and row.return_quantity == 0
        and row.quantity == 0
        and row.net_revenue == 0
        and row.cogs_from_1c_with_extra_costs == 0
        and row.wb_commission == 0
        and row.logistics == 0
        and row.storage == 0
        and row.acceptance == 0
        and row.wb_promotion == 0
        and row.acquiring == 0
        and row.penalties_and_holdbacks != 0
    )


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
