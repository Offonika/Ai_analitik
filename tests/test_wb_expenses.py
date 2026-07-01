from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

from wb_unit_economics.calculation import EXPENSE_STORAGE, EXPENSE_WB_PROMOTION
from wb_unit_economics.wb_expenses import (
    WbExpenseClient,
    export_wb_paid_storage_for_account,
    export_wb_promotion_stats_for_account,
    load_wb_paid_storage_allocation_bases,
    load_wb_promotion_allocation_bases,
)
from wb_unit_economics.wb_finance import WbFinanceSellerAccount


def test_paid_storage_export_and_loader_group_by_week_and_nm(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/paid_storage"):
            assert request.method == "GET"
            assert request.url.params["dateFrom"] == "2026-05-18"
            assert request.url.params["dateTo"] == "2026-05-24"
            return httpx.Response(200, json={"data": {"taskId": "task-1"}})
        if request.url.path.endswith("/tasks/task-1/status"):
            return httpx.Response(200, json={"data": {"status": "done"}})
        if request.url.path.endswith("/tasks/task-1/download"):
            return httpx.Response(
                200,
                json=[
                    {
                        "date": "2026-05-18",
                        "nmId": 101,
                        "vendorCode": "A-1",
                        "barcode": "111",
                        "warehousePrice": 10.12,
                    },
                    {
                        "date": "2026-05-24",
                        "nmId": 101,
                        "vendorCode": "A-1",
                        "barcode": "111",
                        "warehousePrice": 5,
                    },
                ],
            )
        return httpx.Response(404)

    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbExpenseClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_wb_paid_storage_for_account(
            client,
            account,
            tmp_path,
            period_start=date(2026, 5, 18),
            period_end=date(2026, 5, 24),
            status_poll_seconds=0,
            download_delay_seconds=0,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.status == "ok"
    assert result.row_count == 2
    manifest = {
        "results": [
            {
                "seller_account_id": result.seller_account_id,
                "status": result.status,
                "output_file": result.output_path.name,
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    bases = load_wb_paid_storage_allocation_bases(tmp_path, client_id="client")
    assert len(bases) == 1
    assert bases[0].expense_category == EXPENSE_STORAGE
    assert bases[0].week_start == date(2026, 5, 18)
    assert bases[0].week_end == date(2026, 5, 24)
    assert bases[0].nm_id == 101
    assert bases[0].amount == Decimal("15.12")
    assert bases[0].source_row_count == 2


def test_promotion_export_and_loader_reads_nested_nm_sums(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/adv/v1/promotion/count"):
            return httpx.Response(
                200,
                json={
                    "adverts": [
                        {
                            "status": 9,
                            "advert_list": [{"advertId": 123}, {"advertId": 456}],
                        },
                        {
                            "status": 4,
                            "advert_list": [{"advertId": 999}],
                        },
                    ]
                },
            )
        if request.url.path.endswith("/adv/v3/fullstats"):
            assert request.url.params["ids"] == "123,456"
            assert request.url.params["beginDate"] == "2026-05-18"
            assert request.url.params["endDate"] == "2026-05-24"
            return httpx.Response(
                200,
                json=[
                    {
                        "advertId": 123,
                        "days": [
                            {
                                "date": "2026-05-18T00:00:00Z",
                                "apps": [
                                    {
                                        "nms": [
                                            {"nmId": 101, "sum": 7.5},
                                            {"nmId": 202, "sum": 2},
                                        ]
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "advertId": 456,
                        "days": [
                            {
                                "date": "2026-05-19T00:00:00Z",
                                "apps": [{"nms": [{"nmId": 101, "sum": 1.5}]}],
                            }
                        ],
                    },
                ],
            )
        return httpx.Response(404)

    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbExpenseClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_wb_promotion_stats_for_account(
            client,
            account,
            tmp_path,
            period_start=date(2026, 5, 18),
            period_end=date(2026, 5, 24),
            request_delay_seconds=0,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.campaign_ids == (123, 456)
    manifest = {
        "results": [
            {
                "seller_account_id": result.seller_account_id,
                "status": result.status,
                "output_file": result.output_path.name,
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    bases = load_wb_promotion_allocation_bases(tmp_path, client_id="client")
    by_nm = {item.nm_id: item for item in bases}
    assert by_nm[101].expense_category == EXPENSE_WB_PROMOTION
    assert by_nm[101].amount == Decimal("9.00")
    assert by_nm[101].source_row_count == 2
    assert by_nm[202].amount == Decimal("2.00")


def test_promotion_fullstats_null_payload_means_no_rows() -> None:
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"null")

    client = WbExpenseClient(account, transport=httpx.MockTransport(handler))
    try:
        rows, status_code = client.fetch_promotion_fullstats(
            campaign_ids=[123],
            period_start=date(2026, 5, 18),
            period_end=date(2026, 5, 24),
        )
    finally:
        client.close()

    assert status_code == 200
    assert rows == []
