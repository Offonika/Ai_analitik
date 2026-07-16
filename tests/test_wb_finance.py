from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from wb_unit_economics import wb_finance
from wb_unit_economics.contracts import SalesModel
from wb_unit_economics.wb_finance import (
    DEFAULT_FINANCE_FIELDS,
    WbFinanceClient,
    WbFinancePageResult,
    WbFinanceSellerAccount,
    WbFinanceSettings,
    build_sales_report_by_id_request,
    build_sales_report_request,
    decimal_from_value,
    export_wb_finance,
    export_wb_finance_page,
    export_wb_finance_report_id_page,
    extract_next_rrd_id,
    normalize_finance_row,
    recover_wb_finance_manifest_from_pages,
    resume_wb_finance_export,
)

TZ = ZoneInfo("Europe/Moscow")


def test_sales_report_request_uses_new_finance_endpoint_body() -> None:
    payload = build_sales_report_request(
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 17),
        rrd_id=0,
        limit=100000,
        period="daily",
        fields=["rrdId", "nmId"],
    )

    assert payload == {
        "dateFrom": "2026-04-01",
        "dateTo": "2026-06-17",
        "limit": 100000,
        "rrdId": 0,
        "period": "daily",
        "fields": ["rrdId", "nmId"],
    }


def test_default_finance_fields_keep_reconciliation_and_discount_fields() -> None:
    assert "forPay" in DEFAULT_FINANCE_FIELDS
    assert "ppvzReward" in DEFAULT_FINANCE_FIELDS
    assert "vw" in DEFAULT_FINANCE_FIELDS
    assert "vwNds" in DEFAULT_FINANCE_FIELDS
    assert "cashbackDiscount" in DEFAULT_FINANCE_FIELDS
    assert "cashbackCommissionChange" in DEFAULT_FINANCE_FIELDS
    assert "spp" in DEFAULT_FINANCE_FIELDS
    assert "sellerPromoDiscount" in DEFAULT_FINANCE_FIELDS
    assert "loyaltyDiscount" in DEFAULT_FINANCE_FIELDS
    assert "salePricePromocodeDiscountPrc" in DEFAULT_FINANCE_FIELDS


def test_default_finance_fields_include_logistics_chain_and_factor_fields() -> None:
    assert {
        "orderId",
        "orderUid",
        "srid",
        "shkId",
        "stickerId",
        "officeName",
        "ppvzOfficeName",
        "ppvzOfficeId",
        "country",
        "deliveryAmount",
        "returnAmount",
        "rebillLogisticCost",
        "dlvPrc",
        "fixTariffDateFrom",
        "fixTariffDateTo",
        "giBoxTypeName",
    }.issubset(DEFAULT_FINANCE_FIELDS)


def test_sales_report_by_id_request_uses_report_id_endpoint_body() -> None:
    payload = build_sales_report_by_id_request(
        rrd_id=0,
        limit=100000,
        fields=["rrdId", "reportId", "nmId"],
    )

    assert payload == {
        "limit": 100000,
        "rrdId": 0,
        "fields": ["rrdId", "reportId", "nmId"],
    }


def test_normalize_finance_row_maps_new_camel_case_fields() -> None:
    snapshot = normalize_finance_row(
        {
            "rrdId": 123,
            "reportId": "777",
            "reportType": 2,
            "rrDate": "2026-04-10",
            "saleDt": "2026-04-09T00:00:00Z",
            "nmId": 101,
            "vendorCode": "A-1",
            "sku": "111",
            "docTypeName": "Продажа",
            "quantity": 2,
            "retailAmount": "1000,50",
            "ppvzSalesCommission": "100.25",
            "deliveryService": "50",
            "paidStorage": "20",
            "paidAcceptance": "10",
            "penalty": "5",
            "deduction": "3",
            "additionalPayment": "2",
            "acquiringFee": "15",
            "vwNds": "4.45",
            "agencyVat": "1.55",
            "deliveryMethod": "FBS, courier",
            "currency": "RUB",
        },
        client_id="client",
        seller_account_id="WB_ACCOUNT_1",
        organization_id="ORG-1",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert snapshot.wb_document_id == "123"
    assert snapshot.wb_report_id == "777"
    assert snapshot.report_type == 2
    assert snapshot.period_start == date(2026, 4, 10)
    assert snapshot.nm_id == 101
    assert snapshot.vendor_code == "a-1"
    assert snapshot.barcode == "111"
    assert snapshot.sales_model is SalesModel.FBS
    assert snapshot.net_revenue == Decimal("1000.50")
    assert snapshot.wb_commission == Decimal("100.25")
    assert snapshot.wb_promotion == Decimal("3")
    assert snapshot.penalties_and_holdbacks == Decimal("3")
    assert snapshot.acquiring == Decimal("15")
    assert snapshot.vat_input_from_wb == Decimal("6.00")


def test_normalize_finance_row_maps_old_snake_case_names_and_returns() -> None:
    snapshot = normalize_finance_row(
        {
            "rrd_id": 456,
            "report_id": "888",
            "rr_dt": "2026-04-11",
            "nm_id": 202,
            "sa_name": "B-2",
            "barcode": "222",
            "doc_type_name": "Возврат",
            "quantity": 1,
            "retail_amount": "500",
            "ppvz_sales_commission": "50",
            "delivery_rub": "30",
            "storage_fee": "0",
            "acceptance": "0",
            "penalty": "0",
            "deduction": "0",
            "additional_payment": "0",
            "acquiring_fee": "7",
        },
        client_id="client",
        seller_account_id="WB_ACCOUNT_2",
        organization_id="ORG-2",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert snapshot.wb_report_id == "888"
    assert snapshot.quantity == Decimal("-1")
    assert snapshot.net_revenue == Decimal("-500")
    assert snapshot.wb_commission == Decimal("-50")
    assert snapshot.logistics == Decimal("30")
    assert snapshot.acquiring == Decimal("-7")
    assert snapshot.sales_model is SalesModel.FBO


def test_finance_page_export_writes_raw_payload_and_next_rrd(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(
            200,
            json=[{"rrdId": 10, "nmId": 101}, {"rrdId": 11, "nmId": 102}],
        )

    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbFinanceClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_wb_finance_page(
            client,
            account,
            tmp_path,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 17),
            rrd_id=0,
            limit=100000,
            page_index=1,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.status == "ok"
    assert result.row_count == 2
    assert result.rrd_id_next == 11
    assert result.output_path == tmp_path / "wb_account_1_finance_page_1.raw.json"
    assert result.output_path.exists()


def test_finance_export_retries_transient_read_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_page(*_args, **kwargs) -> WbFinancePageResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return WbFinancePageResult(
                seller_account_id="WB_ACCOUNT_1",
                account_name="First cabinet",
                page_index=kwargs["page_index"],
                ok=False,
                status="transport_or_schema_error",
                row_count=0,
                rrd_id_start=kwargs["rrd_id"],
                error="ReadTimeout",
            )
        output_path = tmp_path / "wb_account_1_finance_page_1.raw.json"
        output_path.write_text(json.dumps([{"rrdId": 10}]), encoding="utf-8")
        return WbFinancePageResult(
            seller_account_id="WB_ACCOUNT_1",
            account_name="First cabinet",
            page_index=kwargs["page_index"],
            ok=True,
            status="ok",
            row_count=1,
            rrd_id_start=kwargs["rrd_id"],
            rrd_id_next=10,
            output_path=output_path,
            raw_payload_hash="hash",
            status_code=200,
        )

    monkeypatch.setattr(wb_finance, "WB_PAGE_RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(wb_finance, "export_wb_finance_page", fake_page)
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    settings = WbFinanceSettings(accounts=(account,))
    results = export_wb_finance(
        settings,
        tmp_path,
        period_start=date(2026, 6, 9),
        period_end=date(2026, 6, 22),
        max_pages=1,
        request_delay_seconds=0,
        fields=["rrdId", "nmId"],
    )

    assert calls == 2
    assert results[0].ok is True
    assert results[0].status == "ok"
    assert results[0].output_path.exists()


def test_finance_export_retries_rate_limited_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_page(*_args, **kwargs) -> WbFinancePageResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return WbFinancePageResult(
                seller_account_id="WB_ACCOUNT_1",
                account_name="First cabinet",
                page_index=kwargs["page_index"],
                ok=False,
                status="rate_limited",
                row_count=0,
                rrd_id_start=kwargs["rrd_id"],
                error="HTTP 429",
                status_code=429,
            )
        output_path = tmp_path / "wb_account_1_finance_page_1.raw.json"
        output_path.write_text(json.dumps([{"rrdId": 10}]), encoding="utf-8")
        return WbFinancePageResult(
            seller_account_id="WB_ACCOUNT_1",
            account_name="First cabinet",
            page_index=kwargs["page_index"],
            ok=True,
            status="ok",
            row_count=1,
            rrd_id_start=kwargs["rrd_id"],
            rrd_id_next=None,
            output_path=output_path,
            raw_payload_hash="hash",
            status_code=200,
        )

    monkeypatch.setattr(
        wb_finance.time,
        "sleep",
        lambda seconds: sleeps.append(seconds),
    )
    monkeypatch.setattr(wb_finance, "export_wb_finance_page", fake_page)
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    settings = WbFinanceSettings(accounts=(account,))
    results = export_wb_finance(
        settings,
        tmp_path,
        period_start=date(2026, 6, 9),
        period_end=date(2026, 6, 22),
        max_pages=1,
        request_delay_seconds=13,
        fields=["rrdId", "nmId"],
    )

    assert calls == 2
    assert sleeps == [13]
    assert results[0].ok is True
    assert results[0].status == "ok"
    assert results[0].output_path.exists()


def test_finance_resume_continues_from_manifest_rrd_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "wb_account_1_finance_page_1.raw.json").write_text(
        json.dumps([{"rrdId": 10, "nmId": 1001}]),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-08T21:00:00+03:00",
                "source": "wb_finance_sales_reports_detailed",
                "period_start": "2026-03-01",
                "period_end": "2026-06-16",
                "period": "daily",
                "limit": 100000,
                "max_pages": 50,
                "request_delay_seconds": 61,
                "fields": ["rrdId", "nmId"],
                "results": [
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "account_name": "First cabinet",
                        "page_index": 1,
                        "ok": True,
                        "status": "ok",
                        "row_count": 1,
                        "status_code": 200,
                        "rrd_id_start": 0,
                        "rrd_id_next": 10,
                        "raw_payload_hash": "hash-1",
                        "output_file": "wb_account_1_finance_page_1.raw.json",
                        "error": "",
                        "wb_report_id": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fake_page(*_args, **kwargs) -> WbFinancePageResult:
        calls.append(dict(kwargs))
        output_path = tmp_path / "wb_account_1_finance_page_2.raw.json"
        output_path.write_text(
            json.dumps([{"rrdId": 20, "nmId": 1002}]),
            encoding="utf-8",
        )
        return WbFinancePageResult(
            seller_account_id="WB_ACCOUNT_1",
            account_name="First cabinet",
            page_index=kwargs["page_index"],
            ok=True,
            status="ok",
            row_count=1,
            rrd_id_start=kwargs["rrd_id"],
            rrd_id_next=20,
            output_path=output_path,
            raw_payload_hash="hash-2",
            status_code=200,
        )

    monkeypatch.setattr(wb_finance, "export_wb_finance_page", fake_page)
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    settings = WbFinanceSettings(accounts=(account,))
    results = resume_wb_finance_export(
        settings,
        tmp_path,
        max_pages=1,
        request_delay_seconds=0,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert calls == [
        {
            "period_start": date(2026, 3, 1),
            "period_end": date(2026, 6, 16),
            "rrd_id": 10,
            "limit": 100000,
            "page_index": 2,
            "period": "daily",
            "fields": ["rrdId", "nmId"],
        }
    ]
    assert [item.page_index for item in results] == [2]
    assert len(manifest["results"]) == 2
    assert manifest["results"][1]["rrd_id_start"] == 10
    assert manifest["results"][1]["rrd_id_next"] == 20
    assert manifest["resume"]["previous_result_count"] == 1
    assert list(tmp_path.glob("manifest.before-resume-*.json"))


def test_finance_export_checkpoints_each_page_before_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_page(*_args, **kwargs) -> WbFinancePageResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        output_path = tmp_path / "wb_account_1_finance_page_1.raw.json"
        output_path.write_text(json.dumps([{"rrdId": 10}]), encoding="utf-8")
        return WbFinancePageResult(
            seller_account_id="WB_ACCOUNT_1",
            account_name="First cabinet",
            page_index=kwargs["page_index"],
            ok=True,
            status="ok",
            row_count=1,
            rrd_id_start=kwargs["rrd_id"],
            rrd_id_next=10,
            output_path=output_path,
            raw_payload_hash="hash",
            status_code=200,
        )

    monkeypatch.setattr(wb_finance, "export_wb_finance_page", fake_page)
    monkeypatch.setattr(wb_finance.time, "sleep", lambda _seconds: None)
    settings = WbFinanceSettings(
        accounts=(
            WbFinanceSellerAccount(
                "WB_ACCOUNT_1", "First cabinet", "test-key"
            ),
        )
    )

    with pytest.raises(KeyboardInterrupt):
        export_wb_finance(
            settings,
            tmp_path,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            max_pages=2,
            request_delay_seconds=0,
        )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["checkpoint_status"] == "running"
    assert len(manifest["results"]) == 1
    assert manifest["results"][0]["rrd_id_next"] == 10


def test_finance_manifest_can_be_recovered_from_page_files(tmp_path: Path) -> None:
    (tmp_path / "wb_account_1_finance_page_1.raw.json").write_text(
        json.dumps([{"rrdId": 10}, {"rrdId": 11}]),
        encoding="utf-8",
    )
    (tmp_path / "wb_account_1_finance_page_2.raw.json").write_text(
        json.dumps([{"rrdId": 20}]),
        encoding="utf-8",
    )
    settings = WbFinanceSettings(
        accounts=(
            WbFinanceSellerAccount(
                "WB_ACCOUNT_1", "First cabinet", "test-key"
            ),
        )
    )

    results = recover_wb_finance_manifest_from_pages(
        settings,
        tmp_path,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    result_cursors = [
        (item.row_count, item.rrd_id_start, item.rrd_id_next)
        for item in results
    ]
    assert result_cursors == [(2, 0, 11), (1, 11, 20)]
    assert manifest["checkpoint_status"] == "recovered_interrupted"
    assert len(manifest["results"]) == 2


def test_finance_resume_skips_completed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-08T21:00:00+03:00",
                "source": "wb_finance_sales_reports_detailed",
                "period_start": "2026-03-01",
                "period_end": "2026-06-16",
                "period": "daily",
                "limit": 100000,
                "fields": ["rrdId", "nmId"],
                "results": [
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "account_name": "First cabinet",
                        "page_index": 51,
                        "ok": True,
                        "status": "no_data",
                        "row_count": 0,
                        "status_code": 204,
                        "rrd_id_start": 20,
                        "rrd_id_next": None,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_page(*_args, **_kwargs) -> WbFinancePageResult:
        raise AssertionError("completed manifest should not be resumed")

    monkeypatch.setattr(wb_finance, "export_wb_finance_page", fake_page)
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    settings = WbFinanceSettings(accounts=(account,))

    assert resume_wb_finance_export(settings, tmp_path, max_pages=1) == []
    assert not list(tmp_path.glob("manifest.before-resume-*.json"))


def test_finance_report_id_page_export_uses_report_id_path(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/sales-reports/detailed/726807272")
        assert json.loads(request.content.decode("utf-8")) == {
            "limit": 100000,
            "rrdId": 0,
            "fields": ["rrdId", "reportId"],
        }
        return httpx.Response(
            200,
            json=[{"rrdId": 10, "reportId": 726807272}],
        )

    account = WbFinanceSellerAccount("WB_ACCOUNT_2", "Sultan", "test-key")
    client = WbFinanceClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_wb_finance_report_id_page(
            client,
            account,
            tmp_path,
            report_id="726807272",
            rrd_id=0,
            limit=100000,
            page_index=1,
            fields=["rrdId", "reportId"],
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.wb_report_id == "726807272"
    assert result.rrd_id_next == 10
    assert (
        result.output_path
        == tmp_path / "wb_account_2_report_726807272_finance_page_1.raw.json"
    )
    assert result.output_path.exists()


def test_finance_page_export_stops_on_204(tmp_path: Path) -> None:
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbFinanceClient(
        account,
        transport=httpx.MockTransport(lambda _request: httpx.Response(204)),
    )
    try:
        result = export_wb_finance_page(
            client,
            account,
            tmp_path,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 17),
            rrd_id=0,
            limit=100000,
            page_index=1,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.status == "no_data"
    assert result.output_path is None


@pytest.mark.parametrize(
    ("status_code", "status"),
    [(401, "access_error"), (403, "access_error"), (429, "rate_limited")],
)
def test_finance_page_export_marks_access_and_rate_errors(
    tmp_path: Path, status_code: int, status: str
) -> None:
    account = WbFinanceSellerAccount("WB_ACCOUNT_1", "First cabinet", "test-key")
    client = WbFinanceClient(
        account,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, json={"error": "blocked"})
        ),
    )
    try:
        result = export_wb_finance_page(
            client,
            account,
            tmp_path,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 17),
            rrd_id=0,
            limit=100000,
            page_index=1,
        )
    finally:
        client.close()

    assert result.ok is False
    assert result.status == status
    assert result.status_code == status_code


def test_decimal_parsing_and_rrd_pagination_helpers() -> None:
    assert decimal_from_value("1 234,56") == Decimal("1234.56")
    assert extract_next_rrd_id([{"rrdId": "10"}, {"rrdId": "12"}]) == 12
