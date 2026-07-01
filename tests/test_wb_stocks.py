from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from wb_unit_economics.wb_finance import WbFinanceSellerAccount
from wb_unit_economics.wb_stocks import (
    STOCK_HISTORY_DAILY_REPORT_TYPE,
    WbWarehouseRemainsClient,
    export_wb_stock_history_daily_for_account,
    export_wb_warehouse_remains_for_account,
)


def test_warehouse_remains_export_writes_current_stock_snapshot(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/warehouse_remains"):
            assert request.method == "GET"
            assert request.url.params["groupBySa"] == "true"
            assert request.url.params["groupByNm"] == "true"
            assert request.url.params["groupByBarcode"] == "true"
            return httpx.Response(200, json={"data": {"taskId": "task-1"}})
        if request.url.path.endswith("/tasks/task-1/status"):
            return httpx.Response(200, json={"data": {"status": "done"}})
        if request.url.path.endswith("/tasks/task-1/download"):
            return httpx.Response(
                200,
                json=[
                    {
                        "brand": "Brand",
                        "subjectName": "Панамы",
                        "vendorCode": "A-1",
                        "nmId": 101,
                        "barcode": "111",
                        "techSize": "0",
                        "warehouses": [
                            {"warehouseName": "Коледино", "quantity": 7},
                            {
                                "warehouseName": "Всего находится на складах",
                                "quantity": 7,
                            },
                        ],
                    }
                ],
            )
        return httpx.Response(404)

    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbWarehouseRemainsClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_wb_warehouse_remains_for_account(
            client,
            account,
            tmp_path,
            status_poll_seconds=0,
            download_delay_seconds=0,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.status == "ok"
    assert result.row_count == 1
    assert result.output_path is not None
    assert result.output_path.name == "wb_account_1_warehouse_remains.raw.json"
    assert result.output_path.read_text(encoding="utf-8").count("Коледино") == 1


def test_stock_history_daily_export_writes_zip(tmp_path: Path) -> None:
    report_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v2/nm-report/downloads"):
            if request.method == "POST":
                payload = json.loads(request.read())
                assert payload["reportType"] == STOCK_HISTORY_DAILY_REPORT_TYPE
                assert payload["params"]["stockType"] == "wb"
                report_id = payload["id"]
                report_ids.append(report_id)
                return httpx.Response(
                    200,
                    json={"data": "Началось формирование файла/отчета"},
                )
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": report_ids[0],
                            "status": "SUCCESS",
                            "name": "Stock history",
                        }
                    ]
                },
            )
        if request.url.path.endswith(f"/file/{report_ids[0]}"):
            return httpx.Response(200, content=b"PK\x03\x04fake zip")
        return httpx.Response(404)

    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbWarehouseRemainsClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_wb_stock_history_daily_for_account(
            client,
            account,
            tmp_path,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 17),
            status_poll_seconds=0,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.status == "ok"
    assert result.report_id == report_ids[0]
    assert result.output_path is not None
    assert result.output_path.suffix == ".zip"
    assert result.output_path.read_bytes().startswith(b"PK")
