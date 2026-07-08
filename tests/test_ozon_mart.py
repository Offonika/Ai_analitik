from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from wb_unit_economics.ozon_mart import build_ozon_unit_economics_mart


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
    assert [item["articleId"] for item in ready_row["expenseArticles"]] == [
        "commission",
        "logistics",
        "storage",
        "services",
        "other",
    ]
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
    assert payload["totals"] == {
        "quantity": 2.0,
        "onecRevenue": 900.0,
        "cogs": 600.0,
        "ozonExpenses": 100.0,
        "profit": 200.0,
        "margin": 200 / 900,
    }


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
    assert payload["totals"] == {
        "quantity": 3.0,
        "onecRevenue": 1000.0,
        "cogs": 640.0,
        "ozonExpenses": 100.0,
        "profit": 260.0,
        "margin": 0.26,
    }
    first, second = payload["rows"]
    assert first["expenseStatus"] == "allocated_period_expense"
    assert first["expenseBasis"] == "ozon_mutual_settlement_expense_documents"
    assert first["expenseAllocationBasis"] == "onec_revenue_share"
    assert first["ozonServices"] == 90.0
    assert first["ozonExpenses"] == 90.0
    assert first["profit"] == 210.0
    assert second["ozonServices"] == 10.0
    assert second["profit"] == 50.0


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
                "label": "Отчет о реализации",
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
