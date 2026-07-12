from decimal import Decimal

import pytest

from wb_unit_economics.input_vat_overlay import overlay_management_input_vat_rows


def _source_row(*, row_id: str, cost: str, revenue: str) -> dict[str, object]:
    return {
        "id": row_id,
        "week": "2026-03-01",
        "nmId": "100",
        "articleWb": "A",
        "scheme": "FBO",
        "cost": Decimal(cost),
        "revenue": Decimal(revenue),
        "revenueWithoutVat": Decimal(revenue) / Decimal("1.22"),
        "profitBeforeTax": Decimal("10"),
        "vatOutput": Decimal("22"),
        "commission": Decimal("10"),
        "logistics": Decimal("1"),
        "storage": Decimal("0"),
        "acceptance": Decimal("0"),
        "promotion": Decimal("0"),
        "acquiring": Decimal("0"),
    }


def _scenario_row(**values: object) -> dict[str, object]:
    return {
        "week": "2026-03-01",
        "nmId": "100",
        "articleWb": "A",
        "scheme": "FBO",
        "vatInputFromImportScenario": Decimal("12.34"),
        "vatInputFromWbScenario": Decimal("4.56"),
        "vatInput": Decimal("16.00"),
        "vatInputFromWb": Decimal("1.00"),
        "vatInputFrom1c": Decimal("0"),
        "vatInputCompleteness": "management_assumption",
        "inputVatMode": "management_assumption",
        **values,
    }


def test_overlay_preserves_pnl_and_reconciles_scenario_to_cent() -> None:
    rows = [
        _source_row(row_id="one", cost="30", revenue="70"),
        _source_row(row_id="two", cost="70", revenue="30"),
    ]
    immutable = [
        (row["revenue"], row["revenueWithoutVat"], row["cost"], row["profitBeforeTax"])
        for row in rows
    ]

    result = overlay_management_input_vat_rows(rows, [_scenario_row()])

    assert [
        (row["revenue"], row["revenueWithoutVat"], row["cost"], row["profitBeforeTax"])
        for row in rows
    ] == immutable
    assert sum(row["vatInput"] for row in rows) == Decimal("16.00")
    assert sum(row["vatInputFromImportScenario"] for row in rows) == Decimal(
        "12.34"
    )
    assert sum(row["vatInputFromWbScenario"] for row in rows) == Decimal("4.56")
    assert all(row["inputVatMode"] == "management_assumption" for row in rows)
    assert all(row["vatInputConfirmed"] is False for row in rows)
    assert result["grainCount"] == 1


def test_overlay_keeps_true_partial_status() -> None:
    rows = [_source_row(row_id="one", cost="30", revenue="70")]

    overlay_management_input_vat_rows(
        rows,
        [_scenario_row(vatInputCompleteness="partial", vatInput=Decimal("0"))],
    )

    assert rows[0]["vatInputCompleteness"] == "partial"
    assert rows[0]["vatPayable"] == Decimal("22.00")


def test_overlay_rejects_incompatible_grain() -> None:
    rows = [_source_row(row_id="one", cost="30", revenue="70")]
    scenario = _scenario_row(nmId="other")

    with pytest.raises(ValueError, match="overlay grain mismatch"):
        overlay_management_input_vat_rows(rows, [scenario])
