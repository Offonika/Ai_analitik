from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from wb_unit_economics.contracts import TaxProfile, VatDeductionMode, VatMode
from wb_unit_economics.ozon_mart import (
    build_ozon_unit_economics_mart,
    combine_ozon_monthly_marts,
)


@dataclass
class SourceRow:
    row_number: int
    source_row_id: str
    row_payload: dict[str, Any]


def _resolver(onec_item_id: str = "ITEM-1"):
    def _resolve(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            **candidate,
            "status": "matched",
            "matchMethod": "test",
            "matchKey": candidate.get("offerId") or "",
            "onecItemId": onec_item_id,
            "onecName": "Товар Ozon 1C",
            "onecArticle": "OZ-1",
        }

    return _resolve


def _missing_resolver(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate,
        "status": "missing",
        "onecItemId": "",
        "onecName": "",
        "onecArticle": "",
    }


def _commissioner_row() -> SourceRow:
    return SourceRow(
        row_number=1,
        source_row_id="commissioner-1",
        row_payload={
            "Date": "2026-05-31T01:00:00",
            "Комментарий": "ОЗОН Отчет комиссионера за май",
            "Контрагент_Key": "OZON-CP",
            "Запасы": [
                {
                    "Номенклатура_Key": "ITEM-1",
                    "Количество": "2",
                    "Всего": "900",
                }
            ],
        },
    )


def _realization_row(**overrides: Any) -> SourceRow:
    payload = {
        "offer_id": "OZ-1",
        "product_id": "product-1",
        "sku": "12345",
        "barcode": "12345",
        "name": "Ozon product",
        "sale_qty": "2",
        "sale_amount": "1000",
        "commission_amount": "50",
        "services_amount": "10",
        "logistics_amount": "20",
        "storage_amount": "5",
        "other_amount": "15",
    }
    payload.update(overrides)
    return SourceRow(
        row_number=1,
        source_row_id=str(overrides.get("source_row_id") or "realization-1"),
        row_payload=payload,
    )


def test_ozon_mart_closed_month_calculates_profit_and_keeps_buyout_separate() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        buyout_reconciliation={
            "matchedWithoutReportNumber": 2,
            "buyoutAmount": "931700.04",
            "buyoutQuantity": "456",
        },
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert payload["status"] == "ready"
    assert payload["rowCount"] == 2
    assert payload["summary"] == {
        "ready": 1,
        "partialSource": 0,
        "missingMapping": 0,
        "ambiguousMapping": 0,
        "missingCost": 0,
        "missing1cCommissioner": 0,
        "buyoutPeriodOnly": 1,
        "partialExpenses": 0,
    }
    ready_row = payload["rows"][0]
    assert ready_row["qualityStatus"] == "ready"
    assert ready_row["quantity"] == 2.0
    assert ready_row["onecRevenue"] == 900.0
    assert ready_row["unitCost"] == 300.0
    assert ready_row["cogs"] == 600.0
    assert ready_row["ozonCommission"] == 50.0
    assert ready_row["ozonServices"] == 10.0
    assert ready_row["ozonPartnerServices"] is None
    assert ready_row["ozonLogistics"] == 20.0
    assert ready_row["ozonStorage"] == 5.0
    assert ready_row["ozonOtherExpenses"] == 15.0
    assert ready_row["ozonExpenses"] == 100.0
    assert ready_row["skuAttributedExpenseAmount"] == 100.0
    assert ready_row["periodUnattributedExpenseAmount"] == 0.0
    assert ready_row["expenseBasis"] == "ozon_realization_sku_fields"
    assert ready_row["expenseAttributionType"] == "sku_direct"
    assert [item["articleId"] for item in ready_row["expenseArticles"]] == [
        "commission",
        "logistics",
        "storage",
        "services",
        "other",
    ]
    assert {
        item["attributionType"] for item in ready_row["expenseArticles"]
    } == {"sku_direct"}
    assert ready_row["profit"] == 200.0
    assert ready_row["margin"] == 200 / 900
    assert [item["articleId"] for item in payload["articleRows"]] == [
        "revenue",
        "commission",
        "logistics",
        "storage",
        "services",
        "other",
        "cogs",
        "profit",
    ]

    buyout_row = payload["rows"][1]
    assert buyout_row["rowType"] == "buyout_reconciliation"
    assert buyout_row["qualityStatus"] == "buyout_period_only"
    assert buyout_row["onecRevenue"] == 931700.04
    assert buyout_row["profit"] is None
    assert payload["totals"]["quantity"] == 2.0
    assert payload["totals"]["onecRevenue"] == 900.0
    assert payload["totals"]["cogs"] == 600.0
    assert payload["totals"]["ozonExpenses"] == 100.0
    assert payload["totals"]["profit"] == 200.0
    assert payload["totals"]["profitBeforeTax"] == 200.0
    assert payload["totals"]["marginBeforeTax"] == 200 / 900
    assert payload["totals"]["profitAfterTax"] is None
    assert payload["totals"]["taxCompleteness"] == "missing_tax_profile"
    assert payload["profitAliasDeprecated"] is True


def test_ozon_mart_keeps_sku_detail_expenses_when_period_matches() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_expense_amount=Decimal("100"),
        period_expense_articles=[
            {
                "label": "Базовое вознаграждение Ozon",
                "expenseEffectAmount": 50,
                "includedInExpense": True,
            },
            {
                "label": "Логистика Ozon",
                "expenseEffectAmount": 20,
                "includedInExpense": True,
            },
            {
                "label": "Хранение Ozon",
                "expenseEffectAmount": 5,
                "includedInExpense": True,
            },
            {
                "label": "Акт выполненных работ",
                "expenseEffectAmount": 10,
                "includedInExpense": True,
            },
            {
                "label": "Прочие расходы",
                "expenseEffectAmount": 15,
                "includedInExpense": True,
            },
        ],
        period_expense_basis="ozon_mutual_settlement_expense_documents",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["expenseStatus"] == "loaded"
    assert row["expenseBasis"] == "ozon_realization_sku_fields"
    assert row["expenseAllocationBasis"] == ""
    assert row["ozonExpenses"] == 100.0
    assert row["profit"] == 200.0
    assert payload["expenseAttribution"]["status"] == "sku_direct"
    assert payload["expenseAttribution"]["skuAttributedExpenseAmount"] == 100.0
    assert payload["expenseAttribution"]["unattributedExpenseAmount"] == 0.0
    assert payload["expenseAttribution"]["allocatedUnattributedExpenseAmount"] == 0.0
    assert {item["kind"] for item in payload["articleDrilldown"]} == {"sku_direct"}


def test_ozon_mart_ignores_nested_standard_fee_and_total() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[
            _realization_row(
                commission_amount=None,
                services_amount=None,
                logistics_amount=None,
                storage_amount=None,
                other_amount=None,
                delivery_commission={
                    "standard_fee": "120",
                    "total": "999999",
                },
                return_commission={
                    "standard_fee": "20",
                    "total": "888888",
                },
            )
        ],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["expenseStatus"] == "partial_source"
    assert row["qualityStatus"] == "partial_source"
    assert row["ozonCommission"] is None
    assert row["ozonExpenses"] is None
    assert row["profit"] is None
    assert row["expenseBasis"] == ""
    assert row["expenseArticles"] == []
    assert payload["totals"]["ozonExpenses"] is None
    assert payload["totals"]["profit"] is None
    assert payload["summary"]["partialExpenses"] == 1


def test_ozon_mart_allocates_period_expenses_by_onec_revenue_share() -> None:
    def resolver(candidate: dict[str, Any]) -> dict[str, Any]:
        onec_item_id = "ITEM-2" if candidate.get("offerId") == "OZ-2" else "ITEM-1"
        return {
            **candidate,
            "status": "matched",
            "matchMethod": "test",
            "matchKey": candidate.get("offerId") or "",
            "onecItemId": onec_item_id,
            "onecName": f"Товар {onec_item_id}",
            "onecArticle": onec_item_id,
        }

    commissioner = SourceRow(
        row_number=1,
        source_row_id="commissioner-1",
        row_payload={
            "Date": "2026-05-31T01:00:00",
            "Комментарий": "ОЗОН Отчет комиссионера за май",
            "Контрагент_Key": "OZON-CP",
            "Запасы": [
                {"Номенклатура_Key": "ITEM-1", "Количество": "2", "Всего": "900"},
                {"Номенклатура_Key": "ITEM-2", "Количество": "1", "Всего": "100"},
            ],
        },
    )
    expense_overrides = {
        "commission_amount": None,
        "services_amount": None,
        "logistics_amount": None,
        "storage_amount": None,
        "other_amount": None,
    }

    payload = build_ozon_unit_economics_mart(
        realization_rows=[
            _realization_row(**expense_overrides),
            _realization_row(
                source_row_id="realization-2",
                offer_id="OZ-2",
                sku="67890",
                barcode="67890",
                sale_qty="1",
                sale_amount="100",
                **expense_overrides,
            ),
        ],
        commissioner_rows=[commissioner],
        unit_costs={"ITEM-1": Decimal("300"), "ITEM-2": Decimal("40")},
        mapping_resolver=resolver,
        period_expense_amount=Decimal("100"),
        period_expense_basis="ozon_mutual_settlement_expense_documents",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert payload["status"] == "ready"
    assert payload["summary"]["ready"] == 2
    assert payload["summary"]["partialExpenses"] == 0
    assert payload["totals"]["quantity"] == 3.0
    assert payload["totals"]["onecRevenue"] == 1000.0
    assert payload["totals"]["cogs"] == 640.0
    assert payload["totals"]["ozonExpenses"] == 100.0
    assert payload["totals"]["profitBeforeTax"] == 260.0
    assert payload["totals"]["marginBeforeTax"] == 0.26
    first, second = payload["rows"]
    assert first["expenseStatus"] == "allocated_period_expense"
    assert first["expenseBasis"] == "ozon_mutual_settlement_expense_documents"
    assert first["expenseAllocationBasis"] == "onec_revenue_share"
    assert payload["expenseAttribution"]["status"] == "allocated_period_expense"
    assert first["ozonServices"] == 90.0
    assert first["ozonExpenses"] == 90.0
    assert first["profit"] == 210.0
    assert second["ozonServices"] == 10.0
    assert second["profit"] == 50.0


def test_ozon_mart_applies_confirmed_usn_profile() -> None:
    profile = TaxProfile(
        client_id="client-1",
        organization_id="org-1",
        tax_system="УСН Доходы",
        vat_rate=Decimal("0"),
        vat_mode=VatMode.NONE,
        vat_deduction_mode=VatDeductionMode.NOT_APPLICABLE,
        revenue_tax_rate=Decimal("0.06"),
        source="Catalog_Организации",
    )
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
        tax_profile=profile,
    )

    assert payload["totals"]["profitBeforeTax"] == 200.0
    assert payload["totals"]["revenueTax"] == 54.0
    assert payload["totals"]["profitAfterTax"] == 146.0
    assert payload["totals"]["marginAfterTax"] == 146 / 900
    assert payload["totals"]["taxSystem"] == "УСН Доходы"
    assert payload["totals"]["taxProfileSource"] == "Catalog_Организации"
    assert payload["totals"]["taxCompleteness"] == "profile_complete"


def test_ozon_monthly_range_hides_profit_when_open_month_is_included() -> None:
    closed = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )
    open_month = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row(source_row_id="june-realization")],
        commissioner_rows=[],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        preview_limit=10,
    )

    combined = combine_ozon_monthly_marts([closed, open_month], preview_limit=10)

    assert combined["status"] == "partial_source"
    assert combined["totals"]["profit"] is None
    assert combined["totals"]["profitBeforeTax"] is None
    assert combined["closedPeriodTotals"]["profitBeforeTax"] == 200.0
    assert combined["excludedOpenPeriods"] == [
        {
            "periodStart": "2026-06-01",
            "periodEnd": "2026-06-30",
            "reason": "missing_1c_commissioner",
        }
    ]
    open_row = combined["rows"][1]
    assert open_row["onecRevenue"] is None
    assert open_row["cogs"] is None
    assert open_row["ozonExpenses"] is None
    assert open_row["qualityStatus"] == "missing_1c_commissioner"


def test_ozon_osno_keeps_after_tax_empty_without_confirmed_input_vat() -> None:
    profile = TaxProfile(
        client_id="client-1",
        organization_id="org-1",
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        income_tax_kind="ip_ndfl_progressive",
        source="Catalog_Организации",
    )
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
        tax_profile=profile,
    )

    assert payload["totals"]["profitBeforeTax"] == 200.0
    assert payload["totals"]["vatOutput"] == 162.3
    assert payload["totals"]["vatInput"] is None
    assert payload["totals"]["vatPayable"] is None
    assert payload["totals"]["profitBeforeIncomeTax"] is None
    assert payload["totals"]["profitAfterTax"] is None
    assert payload["totals"]["taxCompleteness"] == "input_vat_missing"


def test_ozon_osno_calculates_no_vat_pnl_with_confirmed_input_vat() -> None:
    profile = TaxProfile(
        client_id="client-1",
        organization_id="org-1",
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        income_tax_kind="ip_ndfl_progressive",
        source="Catalog_Организации",
    )
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
        tax_profile=profile,
        input_vat_by_item={"ITEM-1": Decimal("50")},
    )

    assert payload["totals"]["vatOutput"] == 162.3
    assert payload["totals"]["vatInput"] == 50.0
    assert payload["totals"]["vatPayable"] == 112.3
    assert payload["totals"]["profitBeforeIncomeTax"] == 87.7
    assert payload["totals"]["profitAfterTax"] is None
    assert payload["totals"]["taxCompleteness"] == (
        "vat_confirmed_ndfl_not_allocated"
    )


def test_sabura_april_control_and_incomplete_period_exclusions() -> None:
    # Regression input is expressed as signed monthly 1C movements.  The
    # negative movement represents a return/cost correction and must not be
    # converted to abs().
    april_movements = [
        {"quantity": Decimal("14261.051026903876"), "cost": Decimal("12769990")},
        {"quantity": Decimal("-315"), "cost": Decimal("-282556.45")},
    ]
    april_quantity = sum(
        (item["quantity"] for item in april_movements), Decimal("0")
    )
    april_cogs = sum((item["cost"] for item in april_movements), Decimal("0"))
    april_unit_cost = april_cogs / april_quantity
    commissioner = SourceRow(
        row_number=4,
        source_row_id="commissioner-4",
        row_payload={
            "Date": "2026-04-30",
            "Комментарий": "ОЗОН Отчет комиссионера",
            "Контрагент_Key": "OZON-CP",
            "Запасы": [
                {
                    "Номенклатура_Key": "ITEM-1",
                    "Количество": str(april_quantity),
                    "Всего": "26149512.63",
                }
            ],
        },
    )
    april = build_ozon_unit_economics_mart(
        realization_rows=[
            _realization_row(
                source_row_id="realization-4",
                sale_qty=str(april_quantity),
                sale_amount="26149512.63",
                commission_amount="5433950.60",
                services_amount="0",
                logistics_amount="0",
                storage_amount="0",
                other_amount="0",
            )
        ],
        commissioner_rows=[commissioner],
        unit_costs={"ITEM-1": april_unit_cost},
        reference_unit_costs={
            "ITEM-1": [Decimal("890"), Decimal("900"), Decimal("895")]
        },
        direct_1c_cost_control={
            "quantity": Decimal("14385"),
            "cogs": Decimal("12898270.07"),
        },
        mapping_resolver=_resolver(),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        preview_limit=10,
    )
    may = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row(source_row_id="may", sale_qty="5")],
        commissioner_rows=[
            SourceRow(
                row_number=5,
                source_row_id="commissioner-5",
                row_payload={
                    "Date": "2026-05-31",
                    "Комментарий": "ОЗОН Отчет комиссионера",
                    "Контрагент_Key": "OZON-CP",
                    "Запасы": [
                        {
                            "Номенклатура_Key": "ITEM-1",
                            "Количество": "5",
                            "Всего": "900",
                        }
                    ],
                },
            )
        ],
        unit_costs={},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )
    june = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row(source_row_id="june")],
        commissioner_rows=[],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        preview_limit=10,
    )
    with_june = combine_ozon_monthly_marts(
        [april, may, june],
        preview_limit=10,
    )

    money = Decimal("0.01")
    assert Decimal(str(april["totals"]["cogs"])).quantize(
        money,
        rounding=ROUND_HALF_UP,
    ) == Decimal("12487433.55")
    assert Decimal(str(april["totals"]["profitBeforeTax"])).quantize(
        money,
        rounding=ROUND_HALF_UP,
    ) == Decimal("8228128.48")
    assert round(april["costQuality"]["martAverageUnitCost"], 2) == 895.41
    assert round(april["costQuality"]["direct1cAverageUnitCost"], 2) == 896.65
    assert abs(april["costQuality"]["direct1cDeviationPct"]) < 0.0015
    assert april["costQuality"]["status"] == "complete"
    assert with_june["totals"]["profitBeforeTax"] is None
    assert Decimal(str(with_june["closedPeriodTotals"]["profitBeforeTax"])).quantize(
        money,
        rounding=ROUND_HALF_UP,
    ) == Decimal("8228128.48")
    assert with_june["excludedIncompletePeriods"] == [
        {
            "periodStart": "2026-05-01",
            "periodEnd": "2026-05-31",
            "reason": "missing_cost",
            "reasons": ["missing_cost"],
        }
    ]
    assert with_june["excludedOpenPeriods"] == [
        {
            "periodStart": "2026-06-01",
            "periodEnd": "2026-06-30",
            "reason": "missing_1c_commissioner",
        }
    ]


def test_non_material_unit_cost_outlier_warns_without_hiding_profit() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("50")},
        reference_unit_costs={"ITEM-1": [Decimal("300"), Decimal("310")]},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert payload["costQuality"]["status"] == "warning"
    assert payload["costQuality"]["anomalyCount"] == 1
    assert payload["costQuality"]["estimatedImpactAmount"] == 510.0
    assert payload["costQuality"]["materialityThresholdAmount"] == 100000.0
    assert payload["rows"][0]["costQualityStatus"] == "warning"
    assert payload["rows"][0]["costQualityReason"] == "unit_cost_outlier"
    assert payload["totals"]["profitBeforeTax"] == 700.0
    assert payload["excludedIncompletePeriods"] == []


def test_material_unit_cost_outlier_blocks_closed_month_profit() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row(sale_qty="1000", sale_amount="500000")],
        commissioner_rows=[
            SourceRow(
                row_number=1,
                source_row_id="commissioner-material",
                row_payload={
                    "Date": "2026-05-31",
                    "Комментарий": "ОЗОН Отчет комиссионера",
                    "Контрагент_Key": "OZON-CP",
                    "Запасы": [
                        {
                            "Номенклатура_Key": "ITEM-1",
                            "Количество": "1000",
                            "Всего": "500000",
                        }
                    ],
                },
            )
        ],
        unit_costs={"ITEM-1": Decimal("50")},
        reference_unit_costs={"ITEM-1": [Decimal("300"), Decimal("310")]},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert payload["costQuality"]["status"] == "blocked"
    assert payload["costQuality"]["estimatedImpactAmount"] == 255000.0
    assert payload["rows"][0]["costQualityStatus"] == "blocked"
    assert payload["totals"]["profitBeforeTax"] is None
    assert payload["excludedIncompletePeriods"][0]["reason"] == (
        "cost_quality_blocked"
    )


def test_insufficient_cost_history_warns_and_missing_cost_blocks() -> None:
    warning = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        reference_unit_costs={"ITEM-1": [Decimal("290")]},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )
    blocked = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert warning["costQuality"]["status"] == "warning"
    assert warning["rows"][0]["costQualityReason"] == "insufficient_history"
    assert warning["totals"]["profitBeforeTax"] == 200.0
    assert blocked["costQuality"]["status"] == "blocked"
    assert blocked["costQuality"]["missingCostCount"] == 1
    assert blocked["totals"]["profitBeforeTax"] is None
    assert blocked["excludedIncompletePeriods"][0]["reason"] == "missing_cost"


def test_ozon_mart_allocates_only_unattributed_period_residual() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_expense_amount=Decimal("150"),
        period_expense_articles=[
            {
                "label": "Базовое вознаграждение Ozon",
                "expenseEffectAmount": 50,
                "includedInExpense": True,
            },
            {
                "label": "Логистика Ozon",
                "expenseEffectAmount": 20,
                "includedInExpense": True,
            },
            {
                "label": "Хранение Ozon",
                "expenseEffectAmount": 5,
                "includedInExpense": True,
            },
            {
                "label": "Акт выполненных работ",
                "expenseEffectAmount": 60,
                "includedInExpense": True,
            },
            {
                "label": "Прочие расходы",
                "expenseEffectAmount": 15,
                "includedInExpense": True,
            },
        ],
        period_expense_basis="ozon_mutual_settlement_expense_documents",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["expenseStatus"] == "mixed_sku_and_period_unattributed"
    assert row["expenseBasis"] == "mixed_sku_and_period_unattributed"
    assert row["expenseAllocationBasis"] == "onec_revenue_share"
    assert row["skuAttributedExpenseAmount"] == 100.0
    assert row["periodUnattributedExpenseAmount"] == 50.0
    assert row["ozonServices"] == 60.0
    assert row["ozonExpenses"] == 150.0
    assert row["profit"] == 150.0
    assert payload["expenseAttribution"]["status"] == (
        "mixed_sku_and_period_unattributed"
    )
    assert payload["expenseAttribution"]["skuAttributedExpenseAmount"] == 100.0
    assert payload["expenseAttribution"]["unattributedExpenseAmount"] == 50.0
    assert payload["expenseAttribution"]["allocatedUnattributedExpenseAmount"] == 50.0
    assert {item["kind"] for item in payload["articleDrilldown"]} == {
        "sku_direct",
        "period_unattributed",
    }
    residual_rows = [
        item
        for item in payload["articleDrilldown"]
        if item["kind"] == "period_unattributed"
    ]
    assert residual_rows == [
        {
            **residual_rows[0],
            "articleId": "services",
            "amount": 50.0,
            "unattributedExpenseAmount": 50.0,
        }
    ]


def test_ozon_mart_allocates_service_residual_with_higher_direct_commission() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[
            _realization_row(
                commission_amount="200",
                services_amount=None,
                logistics_amount=None,
                storage_amount=None,
                other_amount=None,
            )
        ],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_expense_amount=Decimal("150"),
        period_expense_articles=[
            {
                "label": "Базовое вознаграждение Ozon",
                "expenseEffectAmount": 50,
                "includedInExpense": True,
            },
            {
                "label": "Акт выполненных работ",
                "expenseEffectAmount": 100,
                "includedInExpense": True,
            },
        ],
        period_expense_basis="ozon_mutual_settlement_expense_documents",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["expenseStatus"] == "mixed_sku_and_period_unattributed"
    assert row["ozonCommission"] == 200.0
    assert row["ozonServices"] == 100.0
    assert row["ozonExpenses"] == 300.0
    assert row["profit"] == 0.0
    assert payload["expenseAttribution"]["status"] == (
        "mixed_sku_and_period_unattributed"
    )
    assert payload["expenseAttribution"]["skuAttributedExpenseAmount"] == 200.0
    assert payload["expenseAttribution"]["unattributedExpenseAmount"] == 100.0
    assert payload["expenseAttribution"]["allocatedUnattributedExpenseAmount"] == 100.0
    assert payload["expenseAttribution"]["overAttributedExpenseAmount"] == 150.0
    assert payload["expenseAttribution"]["periodExpenseDeltaAmount"] == 0.0


def test_ozon_mart_does_not_allocate_negative_period_residual() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_expense_amount=Decimal("80"),
        period_expense_articles=[
            {
                "label": "Базовое вознаграждение Ozon",
                "expenseEffectAmount": 40,
                "includedInExpense": True,
            },
            {
                "label": "Логистика Ozon",
                "expenseEffectAmount": 15,
                "includedInExpense": True,
            },
            {
                "label": "Хранение Ozon",
                "expenseEffectAmount": 5,
                "includedInExpense": True,
            },
            {
                "label": "Акт выполненных работ",
                "expenseEffectAmount": 10,
                "includedInExpense": True,
            },
            {
                "label": "Прочие расходы",
                "expenseEffectAmount": 10,
                "includedInExpense": True,
            },
        ],
        period_expense_basis="ozon_mutual_settlement_expense_documents",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["expenseStatus"] == "loaded"
    assert row["expenseAllocationBasis"] == ""
    assert row["ozonExpenses"] == 100.0
    assert row["profit"] == 200.0
    assert payload["expenseAttribution"]["status"] == "sku_detail_above_period"
    assert payload["expenseAttribution"]["overAttributedExpenseAmount"] == 20.0
    assert payload["expenseAttribution"]["periodExpenseDeltaAmount"] == 0.0
    assert {item["kind"] for item in payload["articleDrilldown"]} == {"sku_direct"}


def test_ozon_mart_allocates_period_expenses_by_finmodel_articles() -> None:
    def resolver(candidate: dict[str, Any]) -> dict[str, Any]:
        onec_item_id = "ITEM-2" if candidate.get("offerId") == "OZ-2" else "ITEM-1"
        return {
            **candidate,
            "status": "matched",
            "matchMethod": "test",
            "matchKey": candidate.get("offerId") or "",
            "onecItemId": onec_item_id,
            "onecName": f"Товар {onec_item_id}",
            "onecArticle": onec_item_id,
        }

    commissioner = SourceRow(
        row_number=1,
        source_row_id="commissioner-1",
        row_payload={
            "Date": "2026-05-31T01:00:00",
            "Комментарий": "ОЗОН Отчет комиссионера за май",
            "Контрагент_Key": "OZON-CP",
            "Запасы": [
                {"Номенклатура_Key": "ITEM-1", "Количество": "2", "Всего": "900"},
                {"Номенклатура_Key": "ITEM-2", "Количество": "1", "Всего": "100"},
            ],
        },
    )
    expense_overrides = {
        "commission_amount": None,
        "services_amount": None,
        "logistics_amount": None,
        "storage_amount": None,
        "other_amount": None,
    }

    payload = build_ozon_unit_economics_mart(
        realization_rows=[
            _realization_row(**expense_overrides),
            _realization_row(
                source_row_id="realization-2",
                offer_id="OZ-2",
                sku="67890",
                barcode="67890",
                sale_qty="1",
                sale_amount="100",
                **expense_overrides,
            ),
        ],
        commissioner_rows=[commissioner],
        unit_costs={"ITEM-1": Decimal("300"), "ITEM-2": Decimal("40")},
        mapping_resolver=resolver,
        period_expense_amount=Decimal("100"),
        period_expense_articles=[
            {
                "label": "Базовое вознаграждение Ozon",
                "expenseEffectAmount": 20,
                "includedInExpense": True,
            },
            {
                "label": "Акт выполненных работ",
                "expenseEffectAmount": 70,
                "includedInExpense": True,
            },
            {
                "label": "Отчет о перевыставлении услуг",
                "expenseEffectAmount": 10,
                "includedInExpense": True,
            },
        ],
        period_expense_basis="ozon_mutual_settlement_expense_documents",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    first, second = payload["rows"]
    assert first["ozonCommission"] == 18.0
    assert first["ozonServices"] == 63.0
    assert first["ozonPartnerServices"] == 9.0
    assert first["ozonExpenses"] == 90.0
    assert second["ozonCommission"] == 2.0
    assert second["ozonServices"] == 7.0
    assert second["ozonPartnerServices"] == 1.0
    assert [item["articleId"] for item in first["expenseArticles"]] == [
        "commission",
        "services",
        "partner_services",
    ]
    article_effects = [
        (item["articleId"], item["effectAmount"]) for item in payload["articleRows"]
    ]
    assert article_effects == [
        ("revenue", 1000.0),
        ("commission", -20.0),
        ("services", -70.0),
        ("partner_services", -10.0),
        ("cogs", -640.0),
        ("profit", 260.0),
    ]
    assert {
        (item["articleId"], item["includedInSkuProfit"])
        for item in payload["articleDrilldown"]
    } == {
        ("commission", True),
        ("services", True),
        ("partner_services", True),
    }


def test_ozon_mart_does_not_allocate_onec_revenue_for_one_item_many_sku() -> None:
    first = _realization_row(offer_id="OZ-1", sku="12345", barcode="12345")
    second = _realization_row(
        source_row_id="realization-2",
        offer_id="OZ-2",
        sku="67890",
        barcode="67890",
    )

    payload = build_ozon_unit_economics_mart(
        realization_rows=[first, second],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert payload["summary"]["ambiguousMapping"] == 2
    for row in payload["rows"]:
        assert row["qualityStatus"] == "ambiguous_mapping"
        assert row["onecRevenue"] is None
        assert row["cogs"] is None
        assert row["profit"] is None
        assert "выручку не распределяем" in row["problemReason"]


def test_ozon_mart_groups_internal_sku_variants_by_seller_offer() -> None:
    first = _realization_row(
        offer_id="OZ-1",
        product_id="product-1",
        sku="12345",
        barcode="12345",
        sale_qty="1",
        commission_amount="50",
        services_amount="5",
        logistics_amount="0",
        storage_amount="0",
        other_amount="0",
    )
    second = _realization_row(
        source_row_id="realization-2",
        offer_id="OZ-1",
        product_id="product-variant",
        sku="67890",
        barcode="67890",
        sale_qty="1",
        commission_amount="70",
        services_amount="5",
        logistics_amount="0",
        storage_amount="0",
        other_amount="0",
    )

    payload = build_ozon_unit_economics_mart(
        realization_rows=[first, second],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    assert payload["rowCount"] == 1
    row = payload["rows"][0]
    assert row["qualityStatus"] == "ready"
    assert row["quantity"] == 2.0
    assert row["onecRevenue"] == 900.0
    assert row["cogs"] == 600.0
    assert row["ozonCommission"] == 120.0
    assert row["ozonServices"] == 10.0
    assert row["ozonExpenses"] == 130.0
    assert row["profit"] == 170.0


def test_ozon_mart_missing_mapping_does_not_calculate_cogs_or_profit() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_missing_resolver,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["qualityStatus"] == "missing_mapping"
    assert row["onecRevenue"] is None
    assert row["cogs"] is None
    assert row["profit"] is None


def test_ozon_mart_missing_expense_fields_are_partial_not_zero() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[
            SourceRow(
                row_number=1,
                source_row_id="realization-no-expenses",
                row_payload={
                    "offer_id": "OZ-1",
                    "product_id": "product-1",
                    "sku": "12345",
                    "barcode": "12345",
                    "name": "Ozon product",
                    "sale_qty": "2",
                    "sale_amount": "1000",
                },
            )
        ],
        commissioner_rows=[_commissioner_row()],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert row["expenseStatus"] == "partial_source"
    assert row["qualityStatus"] == "partial_source"
    assert row["ozonExpenses"] is None
    assert row["profit"] is None
    assert payload["totals"]["ozonExpenses"] is None
    assert payload["totals"]["profit"] is None
    assert payload["summary"]["partialExpenses"] == 1
    assert "ozon_mart_partial_expenses" in [
        item["code"] for item in payload["issues"]
    ]


def test_ozon_mart_june_without_1c_commissioner_marks_missing_commissioner() -> None:
    payload = build_ozon_unit_economics_mart(
        realization_rows=[_realization_row()],
        commissioner_rows=[],
        unit_costs={"ITEM-1": Decimal("300")},
        mapping_resolver=_resolver(),
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        preview_limit=10,
    )

    row = payload["rows"][0]
    assert payload["status"] == "partial_source"
    assert row["qualityStatus"] == "missing_1c_commissioner"
    assert row["onecRevenue"] is None
    assert row["cogs"] is None
    assert row["profit"] is None
    assert row["margin"] is None
