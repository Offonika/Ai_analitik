from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from tests.fixtures import (
    CLIENT_ID,
    account_org_mapping,
    cost_snapshots,
    sku_mappings,
    wb_snapshots,
)
from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.contracts import (
    OnecGrossProfitDocumentRow,
    OnecMarketplaceServiceRow,
)
from wb_unit_economics.report_marts import build_report_marts


def _complete_stock_history_csv(
    *,
    zero_date: date,
    start: date = date(2026, 3, 1),
    end: date = date(2026, 6, 17),
) -> str:
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    headers = ",".join(item.strftime("%d.%m.%Y") for item in dates)
    values = ",".join("0" if item == zero_date else "3" for item in dates)
    return f"NmID,VendorCode,Name,{headers}\n101,A-1,Product 1,{values}\n"


def _write_stock_history_dir(
    root,
    *,
    csv_text: str,
    period_start: str = "2026-03-01",
    period_end: str = "2026-06-17",
) -> None:
    root.mkdir()
    with ZipFile(root / "stock_history.zip", "w") as archive:
        archive.writestr("stock.csv", csv_text)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "period_start": period_start,
                "period_end": period_end,
                "stock_type": "wb",
                "results": [
                    {
                        "status": "ok",
                        "seller_account_id": account,
                        "output_file": "stock_history.zip",
                    }
                    for account in ("WB_ACCOUNT_1", "WB_ACCOUNT_2")
                ],
            }
        ),
        encoding="utf-8",
    )


def test_report_marts_do_not_turn_missing_stock_dates_into_zero_days(tmp_path) -> None:
    stock_history_dir = tmp_path / "partial_stock_history"
    _write_stock_history_dir(
        stock_history_dir,
        csv_text=(
            "NmID,VendorCode,Name,01.03.2026,02.03.2026\n"
            "101,A-1,Product 1,3,0\n"
        ),
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        stock_history_dir=stock_history_dir,
    ).to_dashboard_payload()

    assert payload["lostSales"] == []
    assert payload["lostSalesCoverage"]["calculated"] is False
    assert payload["lostSalesCoverage"]["coveredDays"] == 2
    assert payload["lostSalesCoverage"]["totalDays"] == 109


def test_report_marts_calculate_only_common_provider_stock_window(tmp_path) -> None:
    stock_history_dir = tmp_path / "provider_window_stock_history"
    _write_stock_history_dir(
        stock_history_dir,
        period_start="2026-04-10",
        csv_text=_complete_stock_history_csv(
            start=date(2026, 4, 10),
            end=date(2026, 6, 17),
            zero_date=date(2026, 4, 11),
        ),
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        stock_history_dir=stock_history_dir,
    ).to_dashboard_payload()

    coverage = payload["lostSalesCoverage"]
    assert coverage["calculated"] is True
    assert coverage["providerWindowCalculated"] is True
    assert coverage["fullCoverage"] is False
    assert coverage["coveredDays"] == 69
    assert coverage["totalDays"] == 109
    assert coverage["calculationPeriodStart"] == "2026-04-10"
    assert coverage["calculationPeriodEnd"] == "2026-06-17"
    assert coverage["extrapolated"] is False
    assert "Рассчитано за доступный период" in coverage["message"]
    assert payload["lostSales"]
    context = payload["lostSales"][0]["calculationContext"]
    assert context["version"] == "lost-sales-filter-v1"
    assert context["providerPeriodStart"] == "2026-04-10"
    assert context["providerPeriodEnd"] == "2026-06-17"
    assert set(context["stockByDate"]) == {
        item.isoformat()
        for item in (
            date(2026, 4, 10) + timedelta(days=offset) for offset in range(69)
        )
    }
    assert context["financePeriods"]
    assert all(
        isinstance(item["salesQuantity"], str)
        and isinstance(item["netRevenue"], str)
        and isinstance(item["contributionMargin"], str)
        for item in context["financePeriods"]
    )


def test_report_marts_separate_negative_margin_as_prevented_loss(tmp_path) -> None:
    stock_history_dir = tmp_path / "complete_stock_history"
    _write_stock_history_dir(
        stock_history_dir,
        csv_text=_complete_stock_history_csv(zero_date=date(2026, 3, 2)),
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )
    negative_rows = [
        row.model_copy(
            update={
                "gross_profit": Decimal("-100"),
                "profit_after_taxes": Decimal("-100"),
            }
        )
        if row.seller_account_id == "WB_ACCOUNT_1" and row.nm_id == 101
        else row
        for row in report.rows
    ]
    report = report.model_copy(update={"rows": negative_rows})

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        stock_history_dir=stock_history_dir,
    ).to_dashboard_payload()
    item = next(row for row in payload["lostSales"] if row["nmId"] == "101")

    assert item["estimateType"] == "prevented_loss"
    assert item["lostContributionMargin"] == 0
    assert item["lostProfit"] == 0
    assert item["preventedLoss"] > 0
    assert "Не пополнять" in item["note"]


def test_report_marts_build_without_excel_and_preserve_quality_statuses(
    tmp_path,
) -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
    ).to_dashboard_payload()

    assert payload["unitRows"]
    assert payload["unitRows"][0]["taxMethod"]
    assert payload["unitRows"][0]["taxProfileSource"] == "legacy-default"
    assert "vatInputFromWb" in payload["unitRows"][0]
    assert "vatInputFrom1c" in payload["unitRows"][0]
    assert "vatInputDifference" in payload["unitRows"][0]
    assert "vatInputCompleteness" in payload["unitRows"][0]
    unit_row = payload["unitRows"][0]
    assert unit_row["afterCost"] == unit_row["pnlRevenue"] - unit_row["cost"]
    assert unit_row["afterCommission"] == (
        unit_row["afterCost"] - unit_row["commission"]
    )
    assert unit_row["profitBeforeTax"] == (
        unit_row["beforeVatAdjustment"] + unit_row["pnlVatAdjustment"]
    )
    assert unit_row["profit"] == (
        unit_row["profitBeforeTax"] - unit_row["includedTaxes"]
    )
    assert payload["taxInputReconciliation"]
    assert "vatInputCompleteness" in payload["taxInputReconciliation"][0]
    assert payload["liquidityRows"]
    assert payload["options"]["liquidityStatuses"]
    assert payload["meta"]["lineageType"] == "db_first_report_marts"
    assert payload["meta"]["reportPeriod"] == "01.03.2026 - 17.06.2026"
    assert payload["meta"]["sourceCoverage"] == "06.04.2026 - 03.05.2026"
    assert payload["readiness"]["status"] == "source_coverage_gap"
    assert any(
        item["code"] == "source_coverage_gap"
        for item in payload["readiness"]["reviewReasons"]
    )
    review_rows = [
        row
        for row in payload["unitRows"]
        if row["status"]
        in {"Нет себестоимости 1С", "Неоднозначное сопоставление", "Неполный источник"}
    ]
    assert review_rows
    assert all(row["lossClass"] == "Нужна проверка данных" for row in review_rows)
    review_liquidity_rows = [
        row for row in payload["liquidityRows"] if row["status"] != "ОК"
    ]
    assert review_liquidity_rows
    assert all(
        row["liquidityStatus"] == "Нужна проверка данных"
        for row in review_liquidity_rows
    )


def test_document_reconciliation_uses_loaded_onec_documents() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )
    expected = next(
        row
        for row in report.onec_report_reconciliation_rows
        if row.document_label == "Отчет комиссионера"
    )
    actual = OnecGrossProfitDocumentRow(
        client_id=CLIENT_ID,
        organization_id=expected.organization_id,
        counterparty_id="WB",
        document_id="onec-document-1",
        document_type="ОтчетКомиссионера",
        document_number="1",
        document_date=expected.document_date,
        week_start=expected.week_start,
        week_end=expected.week_end,
        sales_quantity=expected.sales_quantity,
        return_quantity=expected.return_quantity,
        quantity=expected.quantity,
        revenue=expected.revenue_after_spp,
        vat=Decimal("0"),
        cogs=expected.cogs_from_1c_with_extra_costs,
        gross_profit=expected.gross_profit,
        external_report_id=expected.wb_report_ids[0],
        source_row_count=1,
    )
    outside_date = report.report_period_start - timedelta(days=1)
    outside_week_start = outside_date - timedelta(days=outside_date.weekday())
    outside = actual.model_copy(
        update={
            "document_id": "onec-document-outside-period",
            "document_number": "OUTSIDE-PERIOD",
            "document_date": outside_date,
            "week_start": outside_week_start,
            "week_end": outside_week_start + timedelta(days=6),
            "external_report_id": "",
        }
    )
    inside_date = report.report_period_start + timedelta(days=1)
    inside_week_start = inside_date - timedelta(days=inside_date.weekday())
    inside_unmatched = outside.model_copy(
        update={
            "organization_id": "onec-unmatched-organization",
            "document_id": "onec-document-inside-period",
            "document_number": "INSIDE-PERIOD",
            "document_date": inside_date,
            "week_start": inside_week_start,
            "week_end": inside_week_start + timedelta(days=6),
        }
    )

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        onec_gross_profit_rows=[actual, outside, inside_unmatched],
    ).to_dashboard_payload()
    row = next(
        item
        for item in payload["documentReconciliation"]
        if item["documentType"] == "Отчет комиссионера"
        and item["onecDocuments"]
    )

    assert row["status"] == "OK"
    assert row["onecQuantity"] == float(expected.quantity)
    assert row["quantityDelta"] == 0.0
    assert row["amountDelta"] == 0.0
    assert not any(
        "OUTSIDE-PERIOD" in item["onecDocuments"]
        for item in payload["documentReconciliation"]
    )
    assert any(
        item["status"] == "Лишний документ в 1С"
        and "INSIDE-PERIOD" in item["onecDocuments"]
        for item in payload["documentReconciliation"]
    )


def test_document_reconciliation_keeps_month_end_cost_adjustment_separate() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )
    expected = next(
        row
        for row in report.onec_report_reconciliation_rows
        if row.document_label == "Отчет комиссионера"
    )
    actual = OnecGrossProfitDocumentRow(
        client_id=CLIENT_ID,
        organization_id=expected.organization_id,
        counterparty_id="WB",
        document_id="onec-document-1",
        document_type="ОтчетКомиссионера",
        document_date=expected.document_date,
        week_start=expected.week_start,
        week_end=expected.week_end,
        sales_quantity=expected.sales_quantity,
        return_quantity=expected.return_quantity,
        quantity=expected.quantity,
        revenue=expected.revenue_after_spp,
        vat=Decimal("0"),
        cogs=Decimal("500"),
        cogs_without_vat=Decimal("500"),
        gross_profit=expected.revenue_after_spp - Decimal("500"),
        external_report_id=expected.wb_report_ids[0],
        source_row_count=1,
    )
    adjustment = actual.model_copy(
        update={
            "document_date": date(2026, 4, 30),
            "week_start": date(2026, 4, 27),
            "week_end": date(2026, 5, 3),
            "sales_quantity": Decimal("0"),
            "return_quantity": Decimal("0"),
            "quantity": Decimal("0"),
            "revenue": Decimal("0"),
            "cogs": Decimal("-20"),
            "cogs_without_vat": Decimal("-20"),
            "gross_profit": Decimal("20"),
        }
    )

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        onec_gross_profit_rows=[actual, adjustment],
    ).to_dashboard_payload()

    adjustment_row = next(
        item
        for item in payload["documentReconciliation"]
        if item["documentType"] == "Корректировка себестоимости 1С"
    )
    assert adjustment_row["onecDocumentDates"] == "2026-04-30"
    assert adjustment_row["onecCogs"] == -20.0
    assert adjustment_row["onecQuantity"] == 0.0


def test_report_marts_assign_cross_month_week_to_onec_document_month() -> None:
    snapshot = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 4, 27),
            "period_end": date(2026, 4, 27),
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 5, 4, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 5, 4),
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 5, 31),
    )
    expected = next(
        row
        for row in report.onec_report_reconciliation_rows
        if row.document_label == "Отчет комиссионера"
    )
    actual = OnecGrossProfitDocumentRow(
        client_id=CLIENT_ID,
        organization_id=expected.organization_id,
        counterparty_id="WB",
        document_id="onec-boundary-document",
        document_type="ОтчетКомиссионера",
        document_date=date(2026, 4, 30),
        week_start=expected.week_start,
        week_end=expected.week_end,
        sales_quantity=expected.sales_quantity,
        return_quantity=expected.return_quantity,
        quantity=expected.quantity,
        revenue=expected.revenue_after_spp,
        vat=Decimal("0"),
        cogs=expected.cogs_from_1c_with_extra_costs,
        gross_profit=expected.gross_profit,
        external_report_id=expected.wb_report_ids[0],
        source_row_count=1,
    )

    payload = build_report_marts(
        report,
        onec_gross_profit_rows=[actual],
    ).to_dashboard_payload()

    assert payload["unitRows"][0]["month"] == "Апрель 2026"
    assert payload["unitRows"][0]["accountingPeriodDate"] == "2026-04-30"
    assert payload["unitRows"][0]["accountingPeriodSource"] == "onec_document_date"
    assert payload["unitRows"][0]["documentReport"].endswith("закрытие 30.04.2026")


def test_report_marts_assign_march_april_week_to_april() -> None:
    snapshot = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 3, 30),
            "period_end": date(2026, 3, 30),
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 4, 6, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 4, 6),
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 4, 30),
    )

    payload = build_report_marts(report).to_dashboard_payload()

    assert payload["unitRows"][0]["month"] == "Апрель 2026"
    assert payload["unitRows"][0]["accountingPeriodSource"] == (
        "wb_week_end_fallback"
    )
    assert payload["unitRows"][0]["documentReport"].endswith("закрытие 05.04.2026")


def test_monthly_reconciliation_uses_independent_onec_sources_and_nulls() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )
    missing = build_report_marts(report).to_dashboard_payload()
    april_missing = next(
        item
        for item in missing["reconciliationMonthly"]
        if item["month"].startswith("Апрель")
    )
    assert april_missing["onec_quantity"] is None
    assert april_missing["quantity_delta"] is None
    assert april_missing["status"] == "Нет источника 1С"

    onec_sales = OnecGrossProfitDocumentRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="onec-sale-april",
        document_type="Приходная накладная",
        document_date=date(2026, 4, 12),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        quantity=Decimal("91"),
        revenue=Decimal("107114068.45"),
        vat=Decimal("0"),
        cogs=Decimal("40854333.46"),
        cogs_without_vat=Decimal("33491253.63"),
        gross_profit=Decimal("66259734.99"),
        source_row_count=1,
    )
    onec_service = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="onec-service-april",
        document_number="S-1",
        document_date=date(2026, 4, 12),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Комиссия WB",
        service_name="Комиссия WB",
        amount=Decimal("1000"),
        vat=Decimal("220"),
        total=Decimal("1220"),
        source_row_hash="onec-service-april-hash",
    )
    reconciled = build_report_marts(
        report,
        onec_gross_profit_rows=[onec_sales],
        onec_marketplace_service_rows=[onec_service],
        source_run_id="refresh-independent",
    ).to_dashboard_payload()
    april = next(
        item
        for item in reconciled["reconciliationMonthly"]
        if item["month"].startswith("Апрель")
    )
    assert april["onec_quantity"] == 91.0
    assert april["onec_cogs"] == 33491253.63
    assert april["onec_mp_expenses"] == 1000.0
    assert april["quantity_delta"] != 0
    assert april["status"] == "Расхождение"
    assert april["sourceRunId"] == "refresh-independent"


def test_penalty_only_row_is_not_classified_as_product_margin_loss() -> None:
    penalty = wb_snapshots()[0].model_copy(
        update={
            "quantity": Decimal("0"),
            "net_revenue": Decimal("0"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "wb_promotion": Decimal("0"),
            "penalties_and_holdbacks": Decimal("500"),
            "acquiring": Decimal("0"),
            "raw_payload_hash": "penalty-only-mart",
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[penalty],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    payload = build_report_marts(report).to_dashboard_payload()

    assert payload["unitRows"][0]["lossClass"] == "Штрафной инцидент без продаж"
    assert (
        payload["liquidityRows"][0]["liquidityStatus"] == "Штрафной инцидент без продаж"
    )


def test_report_marts_lost_sales_include_onec_stock_and_warehouse_names(
    tmp_path,
) -> None:
    stock_history_dir = tmp_path / "wb_stock_history"
    stock_history_dir.mkdir()
    with ZipFile(stock_history_dir / "stock_history.zip", "w") as archive:
        archive.writestr(
            "stock.csv",
            _complete_stock_history_csv(zero_date=date(2026, 3, 2)),
        )
    (stock_history_dir / "manifest.json").write_text(
        json.dumps(
            {
                "period_start": "2026-03-01",
                    "period_end": "2026-06-17",
                    "stock_type": "wb",
                "results": [
                        {
                            "status": "ok",
                            "seller_account_id": "WB_ACCOUNT_1",
                            "output_file": "stock_history.zip",
                        },
                        {
                            "status": "ok",
                            "seller_account_id": "WB_ACCOUNT_2",
                            "output_file": "stock_history.zip",
                        },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    onec_stock_dir = tmp_path / "onec_stock"
    onec_stock_dir.mkdir()
    (onec_stock_dir / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "sample_id": "stock_by_warehouse",
                        "ok": True,
                        "row_count": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (onec_stock_dir / "stock_by_warehouse.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "RecordSet": [
                            {
                                "Active": True,
                                "Номенклатура_Key": "ONEC-1",
                                "Организация_Key": "1C_ORG_1",
                                "Характеристика_Key": "CHAR-1",
                                "Склад_Key": "WAREHOUSE-1",
                                "Количество": "7",
                            }
                        ]
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (onec_stock_dir / "Catalog_СтруктурныеЕдиницы.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "WAREHOUSE-1",
                        "Description": "Собственный склад",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    payload = build_report_marts(
        report,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        stock_history_dir=stock_history_dir,
        onec_stock_dir=onec_stock_dir,
    ).to_dashboard_payload()

    assert payload["lostSales"]
    assert payload["lostSales"][0]["onecStock"] == 7.0
    assert payload["lostSales"][0]["onecWarehouses"] == "Собственный склад: 7"
