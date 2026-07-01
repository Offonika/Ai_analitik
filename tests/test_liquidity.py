from __future__ import annotations

from decimal import Decimal

from wb_unit_economics.liquidity import aggregate_liquidity_rows, liquidity_rows_payload


def test_liquidity_rows_group_by_product_month_and_include_acceptance() -> None:
    rows = [
        {
            "month": "Май 2026",
            "organization": "Организация",
            "cabinet": "Кабинет",
            "product": "Товар",
            "nmId": "101",
            "articleWb": "WB-1",
            "article1c": "1C-1",
            "barcode": "111",
            "scheme": "FBO",
            "sales": 2,
            "returns": 0,
            "netQty": 2,
            "revenue": 1000,
            "cost": 200,
            "commission": 100,
            "storage": 50,
            "logistics": 300,
            "acceptance": 25,
            "promotion": 20,
            "penalties": 10,
            "acquiring": 15,
            "vat": 40,
            "usn": 10,
            "status": "ОК",
            "statusReason": "",
            "sppStatus": "СПП из WB sales-reports/list cashbackDiscountSum",
        },
        {
            "month": "Май 2026",
            "organization": "Организация",
            "cabinet": "Кабинет",
            "product": "Товар",
            "nmId": "101",
            "articleWb": "WB-1",
            "article1c": "1C-1",
            "barcode": "111",
            "scheme": "FBO",
            "sales": 1,
            "returns": 1,
            "netQty": 0,
            "revenue": 500,
            "cost": 100,
            "commission": 50,
            "storage": 25,
            "logistics": 150,
            "acceptance": 5,
            "promotion": 10,
            "penalties": 0,
            "acquiring": 5,
            "vat": 20,
            "usn": 5,
            "status": "ОК",
            "statusReason": "",
            "sppStatus": "СПП из WB sales-reports/list cashbackDiscountSum",
        },
    ]

    [row] = aggregate_liquidity_rows(rows)

    assert row["sales"] == Decimal("3")
    assert row["returns"] == Decimal("1")
    assert row["md4AfterLogisticsAcceptance"] == Decimal("495")
    assert row["md6BeforeTax"] == Decimal("435")
    assert row["profit"] == Decimal("360")
    assert row["returnRate"] == Decimal("0.3333333333333333333333333333")
    assert row["liquidityStatus"] == "Прибыльный до 500 руб. в месяц"
    assert row["status"] == "ОК"


def test_liquidity_status_detects_tax_loss_after_positive_md6() -> None:
    [row] = aggregate_liquidity_rows(
        [
            {
                "month": "Май 2026",
                "organization": "Организация",
                "cabinet": "Кабинет",
                "product": "Товар",
                "articleWb": "WB-1",
                "article1c": "1C-1",
                "barcode": "111",
                "scheme": "FBO",
                "sales": 1,
                "netQty": 1,
                "revenue": 100,
                "cost": 50,
                "commission": 10,
                "storage": 5,
                "logistics": 5,
                "acceptance": 0,
                "promotion": 5,
                "penalties": 0,
                "acquiring": 5,
                "vat": 20,
                "usn": 5,
                "status": "ОК",
            }
        ]
    )

    assert row["md6BeforeTax"] == Decimal("20")
    assert row["profit"] == Decimal("-5")
    assert row["liquidityStatus"] == "Нулевая маржинальность"

    [loss_row] = aggregate_liquidity_rows(
        [
            {
                **rows_like(row),
                "vat": 21,
                "usn": 5,
            }
        ]
    )
    assert loss_row["md6BeforeTax"] == Decimal("20")
    assert loss_row["profit"] == Decimal("-6")
    assert loss_row["liquidityStatus"] == "Убыточный: налоги"


def test_liquidity_rows_keep_data_quality_visible_and_avoid_zero_division() -> None:
    [row] = aggregate_liquidity_rows(
        [
            {
                "month": "Май 2026",
                "organization": "Организация",
                "cabinet": "Кабинет",
                "product": "Товар",
                "articleWb": "WB-1",
                "article1c": "1C-1",
                "barcode": "111",
                "scheme": "FBO",
                "sales": 0,
                "returns": 0,
                "netQty": 0,
                "revenue": 0,
                "storage": 10,
                "status": "Нет себестоимости 1С",
                "statusReason": "Для сопоставленного товара нет себестоимости",
            }
        ]
    )

    assert row["returnRate"] is None
    assert row["unitProfit"] is None
    assert row["liquidityStatus"] == "Нужна проверка данных"
    assert row["status"] == "Нет себестоимости 1С"
    assert row["statusReason"] == "Для сопоставленного товара нет себестоимости"
    assert liquidity_rows_payload([row])[0]["profit"] == -10.0


def rows_like(row: dict[str, object]) -> dict[str, object]:
    return {
        "month": row["month"],
        "organization": row["organization"],
        "cabinet": row["cabinet"],
        "product": row["product"],
        "articleWb": row["articleWb"],
        "article1c": row["article1c"],
        "barcode": row["barcode"],
        "scheme": row["scheme"],
        "sales": 1,
        "netQty": 1,
        "revenue": 100,
        "cost": 50,
        "commission": 10,
        "storage": 5,
        "logistics": 5,
        "acceptance": 0,
        "promotion": 5,
        "penalties": 0,
        "acquiring": 5,
        "status": "ОК",
    }
