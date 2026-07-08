from __future__ import annotations

import json
from datetime import date
from io import BytesIO

import httpx
from openpyxl import Workbook

import wb_unit_economics.ozon as ozon_module
from wb_unit_economics.ozon import (
    OzonSettings,
    export_ozon_b2b_sales_json,
    export_ozon_cash_flow,
    export_ozon_mutual_settlement,
    export_ozon_products_buyout,
    export_ozon_products_report,
    export_ozon_realization,
    export_ozon_realization_posting,
    ozon_settings_from_secret,
)


def test_ozon_settings_from_secret_accepts_json_and_key_value() -> None:
    settings = ozon_settings_from_secret(
        '{"clientId":"client-1","apiKey":"api-key-1","sellerAccountId":"ozon-1"}'
    )
    assert len(settings.accounts) == 1
    assert settings.accounts[0].seller_account_id == "ozon-1"
    assert settings.accounts[0].client_id == "client-1"
    assert settings.accounts[0].api_key == "api-key-1"

    kv_settings = ozon_settings_from_secret(
        "clientId=client-2;apiKey=api-key-2",
        default_seller_account_id="ozon-primary",
    )
    assert kv_settings.accounts[0].seller_account_id == "OZON_PRIMARY"


def test_export_ozon_cash_flow_writes_raw_snapshot_without_secrets(tmp_path) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url.path == "/v1/finance/cash-flow-statement/list"
        assert request.headers["Client-Id"] == "client-secret"
        assert request.headers["Api-Key"] == "api-secret"
        return httpx.Response(
            200,
            json={
                "result": {
                    "items": [
                        {
                            "id": "op-1",
                            "offer_id": "A-1",
                            "price": "1000",
                        }
                    ]
                }
            },
        )

    results = export_ozon_cash_flow(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        page_size=100,
        max_pages=1,
        transport=httpx.MockTransport(handler),
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].row_count == 1
    assert requests == [
        {
            "page": 1,
            "page_size": 100,
            "date": {
                "from": "2026-06-01T00:00:00Z",
                "to": "2026-06-30T23:59:59Z",
            },
            "with_details": True,
        }
    ]

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "ozon_finance_cash_flow"
    assert manifest["sourceEndpoint"] == "/v1/finance/cash-flow-statement/list"
    assert manifest["results"][0]["rowCount"] == 1

    saved_text = "\n".join(
        path.read_text(encoding="utf-8") for path in tmp_path.iterdir()
    )
    assert "client-secret" not in saved_text
    assert "api-secret" not in saved_text
    assert "A-1" in saved_text


def test_export_ozon_cash_flow_flattens_detail_periods(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/finance/cash-flow-statement/list"
        return httpx.Response(
            200,
            json={
                "result": {
                    "details": [
                        {
                            "period": {
                                "begin": "2026-04-01T00:00:00Z",
                                "end": "2026-04-05T00:00:00Z",
                            },
                            "services": {"total": "-150"},
                        },
                        {
                            "period": {
                                "begin": "2026-04-06T00:00:00Z",
                                "end": "2026-04-12T00:00:00Z",
                            },
                            "return": {"total": "-25"},
                        },
                    ]
                }
            },
        )

    results = export_ozon_cash_flow(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        max_pages=1,
        transport=httpx.MockTransport(handler),
    )

    assert results[0].row_count == 2
    saved = json.loads(next(tmp_path.glob("*.raw.json")).read_text(encoding="utf-8"))
    assert len(saved["result"]["details"]) == 2


def test_export_ozon_realization_uses_month_and_year_payload(tmp_path) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url.path == "/v2/finance/realization"
        return httpx.Response(
            200,
            json={
                "result": {
                    "rows": [
                        {
                            "item": {"offer_id": "A-1", "sku": 12345},
                            "delivery_commission": {"quantity": 2, "amount": 1000},
                        }
                    ]
                }
            },
        )

    results = export_ozon_realization(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 4, 30),
        transport=httpx.MockTransport(handler),
    )

    assert requests == [{"month": 3, "year": 2026}, {"month": 4, "year": 2026}]
    assert [item.row_count for item in results] == [1, 1]


def test_export_ozon_realization_treats_missing_month_report_as_empty(
    tmp_path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"month": 7, "year": 2026}
        return httpx.Response(404, json={"message": "Report was not found"})

    results = export_ozon_realization(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 5),
        transport=httpx.MockTransport(handler),
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].status == "empty_expected"
    assert results[0].row_count == 0
    assert results[0].error == "Report was not found"


def test_export_ozon_realization_posting_uses_month_year_and_page_payload(
    tmp_path,
) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url.path == "/v1/finance/realization/posting"
        if requests[-1]["page"] == 1:
            return httpx.Response(
                200,
                json={
                    "result": {
                        "rows": [
                            {
                                "posting_number": "posting-1",
                                "offer_id": "A-1",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"result": {"rows": []}})

    results = export_ozon_realization_posting(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        max_pages=2,
        transport=httpx.MockTransport(handler),
    )

    assert requests == [
        {"month": 5, "year": 2026, "page": 1},
        {"month": 5, "year": 2026, "page": 2},
    ]
    assert [item.row_count for item in results] == [1, 0]
    assert results[0].source_endpoint == "/v1/finance/realization/posting"


def test_export_ozon_realization_posting_skips_duplicate_pages(tmp_path) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "result": {
                    "rows": [
                        {
                            "posting_number": "posting-1",
                            "offer_id": "A-1",
                        }
                    ]
                }
            },
        )

    results = export_ozon_realization_posting(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        max_pages=3,
        transport=httpx.MockTransport(handler),
    )

    assert requests == [
        {"month": 5, "year": 2026, "page": 1},
        {"month": 5, "year": 2026, "page": 2},
    ]
    assert [item.row_count for item in results] == [1]


def test_export_ozon_extra_period_reports_use_date_range_payload(tmp_path) -> None:
    requests: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        return httpx.Response(
            200,
            json={"result": {"items": [{"id": f"{request.url.path}:1"}]}},
        )

    settings = ozon_settings_from_secret(
        '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
    )
    buyout = export_ozon_products_buyout(
        settings,
        tmp_path / "buyout",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        transport=httpx.MockTransport(handler),
    )
    b2b = export_ozon_b2b_sales_json(
        settings,
        tmp_path / "b2b",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        transport=httpx.MockTransport(handler),
    )

    assert requests == [
        (
            "/v1/finance/products/buyout",
            {
                "date_from": "2026-05-01",
                "date_to": "2026-05-31",
            },
        ),
        (
            "/v1/finance/document-b2b-sales/json",
            {"date": "2026-05"},
        ),
    ]
    assert [item.row_count for item in buyout] == [1]
    assert [item.row_count for item in b2b] == [1]


def test_export_ozon_products_buyout_counts_product_rows(tmp_path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "products": [
                    {"posting_number": "posting-1", "quantity": 1},
                    {"posting_number": "posting-2", "quantity": 2},
                ]
            },
        )

    settings = ozon_settings_from_secret(
        '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
    )
    result = export_ozon_products_buyout(
        settings,
        tmp_path / "buyout-products",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        transport=httpx.MockTransport(handler),
    )

    assert [item.row_count for item in result] == [2]


def test_export_ozon_products_report_polls_report_info(
    tmp_path,
    monkeypatch,
) -> None:
    seen_paths: list[str] = []
    info_calls = 0
    monkeypatch.setattr(ozon_module.time, "sleep", lambda _seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal info_calls
        seen_paths.append(request.url.path)
        if request.url.path == "/v1/report/products/create":
            return httpx.Response(200, json={"result": {"code": "report-code-1"}})
        if request.url.path == "/v1/report/info":
            info_calls += 1
            assert json.loads(request.content) == {"code": "report-code-1"}
            if info_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "result": {
                            "code": "report-code-1",
                            "status": "waiting",
                            "file": "",
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "result": {
                        "code": "report-code-1",
                        "status": "success",
                        "file": "https://example.test/report.csv",
                    }
                },
            )
        if request.url.path == "/report.csv":
            return httpx.Response(
                200,
                text="offer_id;product_id;sku;barcode\nA-1;product-1;12345;BAR-1\n",
                headers={"content-type": "text/csv; charset=utf-8"},
            )
        raise AssertionError(request.url.path)

    settings = OzonSettings(
        accounts=ozon_settings_from_secret(
            '{"clientId":"client-1","apiKey":"api-key-1","sellerAccountId":"ozon-1"}'
        ).accounts,
        base_url="https://api-seller.ozon.ru",
    )
    results = export_ozon_products_report(
        settings,
        tmp_path,
        transport=httpx.MockTransport(handler),
    )

    assert seen_paths == [
        "/v1/report/products/create",
        "/v1/report/info",
        "/v1/report/info",
        "/report.csv",
    ]
    assert [item.source_type for item in results] == [
        "ozon_products_report",
        "ozon_products_report_info",
        "ozon_products_report_info",
        "ozon_products_report_file",
    ]
    assert results[0].report_code == "report-code-1"
    assert results[1].row_count == 1
    assert results[2].row_count == 1
    assert results[3].row_count == 1


def test_export_ozon_mutual_settlement_polls_monthly_report_info(
    tmp_path,
    monkeypatch,
) -> None:
    seen: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(ozon_module.time, "sleep", lambda _seconds: None)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["operation_type", "amount"])
    sheet.append(["MarketplaceServiceCostPerClick", -100])
    xlsx = BytesIO()
    workbook.save(xlsx)
    workbook.close()

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.url.path, body))
        if request.url.path == "/v1/finance/mutual-settlement":
            return httpx.Response(200, json={"result": {"code": "mutual-code-1"}})
        if request.url.path == "/v1/report/info":
            assert body == {"code": "mutual-code-1"}
            return httpx.Response(
                200,
                json={
                    "result": {
                        "code": "mutual-code-1",
                        "status": "success",
                        "file": "https://example.test/mutual.csv",
                    }
                },
            )
        if request.url.path == "/mutual.csv":
            return httpx.Response(
                200,
                content=xlsx.getvalue(),
                headers={
                    "content-type": (
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    )
                },
            )
        raise AssertionError(request.url.path)

    settings = OzonSettings(
        accounts=ozon_settings_from_secret(
            '{"clientId":"client-1","apiKey":"api-key-1","sellerAccountId":"ozon-1"}'
        ).accounts,
        base_url="https://api-seller.ozon.ru",
    )
    results = export_ozon_mutual_settlement(
        settings,
        tmp_path,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        transport=httpx.MockTransport(handler),
    )

    assert seen == [
        ("/v1/finance/mutual-settlement", {"date": "2026-04"}),
        ("/v1/report/info", {"code": "mutual-code-1"}),
        ("/mutual.csv", None),
    ]
    assert [item.source_type for item in results] == [
        "ozon_mutual_settlement",
        "ozon_mutual_settlement_info",
        "ozon_mutual_settlement_file",
    ]
    assert results[0].source_endpoint == "/v1/finance/mutual-settlement"
    assert results[2].row_count == 1
    assert (tmp_path / "ozon-1_ozon_mutual_settlement_2026-04_file.raw.xlsx").exists()


def test_export_ozon_mutual_settlement_treats_missing_month_as_empty(
    tmp_path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/finance/mutual-settlement"
        return httpx.Response(
            404,
            json={
                "message": (
                    "service.CreateMutualSettlementReport: "
                    "finance document not found"
                )
            },
        )

    results = export_ozon_mutual_settlement(
        ozon_settings_from_secret(
            '{"clientId":"client-secret","apiKey":"api-secret","sellerAccountId":"ozon-1"}'
        ),
        tmp_path,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 6),
        transport=httpx.MockTransport(handler),
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].status == "empty_expected"
    assert results[0].row_count == 0
