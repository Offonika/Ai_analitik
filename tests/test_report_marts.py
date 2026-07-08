from __future__ import annotations

import json
from datetime import date, datetime
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
from wb_unit_economics.report_marts import build_report_marts


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
        row
        for row in payload["liquidityRows"]
        if row["status"] != "ОК"
    ]
    assert review_liquidity_rows
    assert all(
        row["liquidityStatus"] == "Нужна проверка данных"
        for row in review_liquidity_rows
    )


def test_report_marts_lost_sales_include_onec_stock_and_warehouse_names(
    tmp_path,
) -> None:
    stock_history_dir = tmp_path / "wb_stock_history"
    stock_history_dir.mkdir()
    with ZipFile(stock_history_dir / "stock_history.zip", "w") as archive:
        archive.writestr(
            "stock.csv",
            ("NmID,VendorCode,Name,01.03.2026,02.03.2026\n101,A-1,Product 1,3,0\n"),
        )
    (stock_history_dir / "manifest.json").write_text(
        json.dumps(
            {
                "period_start": "2026-03-01",
                "period_end": "2026-06-17",
                "results": [
                    {
                        "status": "ok",
                        "seller_account_id": "WB_ACCOUNT_1",
                        "output_file": "stock_history.zip",
                    }
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
