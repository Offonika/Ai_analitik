from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from scripts.export_onec_odata_samples import _select_collections
from wb_unit_economics.onec_odata import (
    ACCOUNTING_REPORT_SAMPLE_COLLECTIONS,
    DEFAULT_SAMPLE_COLLECTIONS,
    GROSS_PROFIT_SAMPLE_COLLECTIONS,
    INPUT_VAT_SAMPLE_COLLECTIONS,
    SERVICE_SAMPLE_COLLECTIONS,
    TAX_PROFILE_SAMPLE_COLLECTIONS,
    OnecODataClient,
    OnecODataSettings,
    OnecSampleCollection,
    check_onec_odata_metadata,
    export_collection_sample,
    export_onec_accounting_recordtype_balances,
    extract_odata_rows,
    raw_payload_hash,
)

VALID_EDMX = b"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema xmlns="http://schemas.microsoft.com/ado/2009/11/edm">
      <EntityContainer Name="StandardODATA" />
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def test_env_settings_accepts_documented_aliases(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    password_key = "ONEC_ODATA_PASSWORD"
    env_file.write_text(
        "\n".join(
            [
                "ONEC_ODATA_BASE_URL=https://onec.example/odata/standard.odata",
                "ONEC_ODATA_USERNAME=readonly",
                f"{password_key}=secret",
                "ONEC_ODATA_VERIFY_SSL=false",
                "ONEC_ODATA_TIMEOUT_SECONDS=7",
            ]
        ),
        encoding="utf-8",
    )

    settings = OnecODataSettings.from_env_file(env_file)

    assert settings.timeout_seconds == 7
    assert settings.verify_ssl is False


def test_metadata_check_requires_valid_edmx() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=VALID_EDMX,
            headers={"content-type": "application/xml"},
        )

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )

    result = check_onec_odata_metadata(
        settings,
        transport=httpx.MockTransport(handler),
    )

    assert result.ok is True
    assert result.status_code == 200
    assert requests[0].url.path.endswith("/$metadata")


@pytest.mark.parametrize(
    ("status_code", "body", "expected_error"),
    [
        (404, b'{"error":"not found"}', "HTTP 404"),
        (200, b"<html>1C shell</html>", "invalid_metadata_edmx"),
        (200, b"not xml", "invalid_metadata_xml"),
    ],
)
def test_metadata_check_rejects_unavailable_or_fake_metadata(
    status_code: int,
    body: bytes,
    expected_error: str,
) -> None:
    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )

    result = check_onec_odata_metadata(
        settings,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, content=body)
        ),
    )

    assert result.ok is False
    assert result.status_code == status_code
    assert result.error == expected_error


def test_extract_odata_rows_supports_v3_and_v4_payloads() -> None:
    assert extract_odata_rows({"d": {"results": [{"Ref_Key": "1"}]}}) == [
        {"Ref_Key": "1"}
    ]
    assert extract_odata_rows({"value": [{"Ref_Key": "2"}]}) == [{"Ref_Key": "2"}]


def test_collection_sample_export_writes_raw_payload(tmp_path: Path) -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json={"d": {"results": [{"Ref_Key": "item-1"}]}})

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            DEFAULT_SAMPLE_COLLECTIONS[0],
            tmp_path,
            top=3,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.row_count == 1
    assert result.output_path == tmp_path / "nomenclature.raw.json"
    assert result.output_path.exists()
    assert requested[0].method == "GET"
    assert requested[0].url.params["$top"] == "3"
    assert requested[0].url.params["$format"] == "json"


def test_collection_sample_export_retries_transient_timeout(tmp_path: Path) -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if len(requested) == 1:
            raise httpx.ReadTimeout("temporary 1C timeout", request=request)
        return httpx.Response(200, json={"value": [{"Ref_Key": "item-1"}]})

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            DEFAULT_SAMPLE_COLLECTIONS[0],
            tmp_path,
            top=3,
            retry_attempts=1,
            retry_delay_seconds=0,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.row_count == 1
    assert len(requested) == 2


def test_collection_sample_export_does_not_retry_not_found(tmp_path: Path) -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(404, json={"error": "not found"})

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            DEFAULT_SAMPLE_COLLECTIONS[0],
            tmp_path,
            top=3,
            retry_attempts=2,
            retry_delay_seconds=0,
        )
    finally:
        client.close()

    assert result.ok is False
    assert result.status_code == 404
    assert len(requested) == 1


def test_collection_sample_export_retries_transient_server_error(
    tmp_path: Path,
) -> None:
    requested: list[httpx.Request] = []
    collection = next(
        item
        for item in GROSS_PROFIT_SAMPLE_COLLECTIONS
        if item.sample_id == "commissioner_reports"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if len(requested) == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(200, json={"value": [{"Ref_Key": "report-1"}]})

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            collection,
            tmp_path,
            top=5000,
            max_pages=2,
            retry_attempts=1,
            retry_delay_seconds=0,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
    finally:
        client.close()

    assert result.ok is True
    assert len(requested) == 2
    assert [request.url.params["$top"] for request in requested] == ["5", "5"]


def test_collection_sample_export_supports_skip_pagination(tmp_path: Path) -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        skip = request.url.params.get("$skip", "0")
        if skip == "0":
            return httpx.Response(
                200,
                json={"value": [{"Ref_Key": "item-1"}, {"Ref_Key": "item-2"}]},
            )
        return httpx.Response(200, json={"value": [{"Ref_Key": "item-3"}]})

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            DEFAULT_SAMPLE_COLLECTIONS[0],
            tmp_path,
            top=2,
            max_pages=3,
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.row_count == 3
    assert result.page_count == 2
    assert requested[0].url.params["$top"] == "2"
    assert "$skip" not in requested[0].url.params
    assert requested[1].url.params["$skip"] == "2"
    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert extract_odata_rows(payload) == [
        {"Ref_Key": "item-1"},
        {"Ref_Key": "item-2"},
        {"Ref_Key": "item-3"},
    ]


def test_heavy_document_filters_posted_locally_and_reduces_batch_on_timeout(
    tmp_path: Path,
) -> None:
    requested: list[httpx.Request] = []
    collection = next(
        item
        for item in GROSS_PROFIT_SAMPLE_COLLECTIONS
        if item.sample_id == "commissioner_reports"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.url.params["$top"] == "5":
            raise httpx.ReadTimeout("heavy page", request=request)
        if request.url.params.get("$skip") == "1":
            return httpx.Response(200, json={"value": []})
        return httpx.Response(200, json={"value": [{"Ref_Key": "report-1"}]})

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            collection,
            tmp_path,
            top=5000,
            max_pages=2,
            retry_attempts=3,
            retry_delay_seconds=0,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.effective_page_size == 1
    assert [request.url.params["$top"] for request in requested] == ["5", "1", "1"]
    assert requested[-1].url.params["$orderby"] == "Date asc,Ref_Key asc"
    assert requested[-1].url.params["$filter"] == "Posted eq true"
    assert requested[-1].url.params["$select"] == ",".join(collection.select_fields)
    manifest = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
    assert manifest["period_filter_mode"] == "local_document_date"
    assert manifest["detail_mode"] == "financial_tables"
    assert result.detail_mode == "financial_tables"
    assert "Запасы" in collection.select_fields
    assert "ЗапасыВозвраты" in collection.select_fields
    assert "Организация_Key" in collection.select_fields


def test_stock_movements_filters_nested_period_locally(tmp_path: Path) -> None:
    collection = next(
        item
        for item in DEFAULT_SAMPLE_COLLECTIONS
        if item.sample_id == "stock_movements"
    )
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={"value": [{"Recorder": "rec-1", "RecordSet": []}]},
        )

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            collection,
            tmp_path,
            top=5000,
            max_pages=2,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
    finally:
        client.close()

    assert result.ok is True
    assert collection.page_size == 25
    assert "$filter" not in requested[0].url.params
    assert requested[0].url.params["$orderby"] == "Recorder asc"
    manifest = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
    assert manifest["period_filter_mode"] == "nested_recordset_local"


def test_collection_resume_reuses_verified_pages_without_duplicates(
    tmp_path: Path,
) -> None:
    collection = OnecSampleCollection(
        sample_id="resume_test",
        collection_name="AccumulationRegister_Test",
        purpose="resume",
        period_field="Period",
        page_size=2,
        min_page_size=1,
        order_by="Period asc",
    )
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    def first_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$skip", "0") == "0":
            return httpx.Response(
                200,
                json={"value": [{"id": "1"}, {"id": "2"}]},
            )
        raise httpx.ReadTimeout("interrupted", request=request)

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    first_client = OnecODataClient(
        settings, transport=httpx.MockTransport(first_handler)
    )
    try:
        first_result = export_collection_sample(
            first_client,
            collection,
            first_dir,
            top=2,
            max_pages=3,
            retry_attempts=0,
            retry_delay_seconds=0,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            source_identity="onec-a",
        )
    finally:
        first_client.close()

    assert first_result.status == "partial_source"
    assert first_result.row_count == 2
    assert first_result.page_count == 1
    assert first_result.output_path is None

    requested: list[httpx.Request] = []

    def second_handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json={"value": [{"id": "3"}]})

    second_client = OnecODataClient(
        settings, transport=httpx.MockTransport(second_handler)
    )
    try:
        resumed = export_collection_sample(
            second_client,
            collection,
            second_dir,
            top=2,
            max_pages=3,
            retry_attempts=0,
            retry_delay_seconds=0,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            resume_from_dir=first_dir,
            source_identity="onec-a",
        )
    finally:
        second_client.close()

    assert resumed.ok is True
    assert resumed.reused_page_count == 1
    assert resumed.row_count == 3
    assert requested[0].url.params["$skip"] == "2"
    payload = json.loads(resumed.output_path.read_text(encoding="utf-8"))
    assert extract_odata_rows(payload) == [{"id": "1"}, {"id": "2"}, {"id": "3"}]


def test_collection_resume_reuses_completed_checkpoint_without_network(
    tmp_path: Path,
) -> None:
    collection = OnecSampleCollection(
        sample_id="completed_resume",
        collection_name="Catalog_Completed",
        purpose="resume",
        page_size=2,
        min_page_size=1,
    )
    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    first_client = OnecODataClient(
        settings,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"value": [{"id": "1"}]})
        ),
    )
    try:
        first = export_collection_sample(
            first_client,
            collection,
            tmp_path / "first",
            top=2,
            max_pages=2,
            source_identity="onec-a",
        )
    finally:
        first_client.close()
    assert first.ok is True
    manifest = json.loads(first.checkpoint_path.read_text(encoding="utf-8"))
    manifest["query_contract_hash"] = raw_payload_hash(
        {
            "collection_name": collection.collection_name,
            "params": manifest["request_params"],
            "source_identity": "onec-a",
            "period_start": "",
            "period_end": "",
            "period_filter_mode": collection.period_filter_mode,
            "detail_mode": collection.detail_mode,
        }
    )
    first.checkpoint_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    def must_not_fetch(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("completed checkpoint must not call 1C again")

    second_client = OnecODataClient(
        settings, transport=httpx.MockTransport(must_not_fetch)
    )
    try:
        resumed = export_collection_sample(
            second_client,
            collection,
            tmp_path / "second",
            top=2,
            max_pages=2,
            resume_from_dir=tmp_path / "first",
            source_identity="onec-a",
        )
    finally:
        second_client.close()

    assert resumed.ok is True
    assert resumed.reused_page_count == 1
    assert resumed.row_count == 1


def test_collection_resume_max_pages_is_new_page_budget(tmp_path: Path) -> None:
    collection = OnecSampleCollection(
        sample_id="page_budget",
        collection_name="Catalog_PageBudget",
        purpose="resume",
        page_size=1,
        min_page_size=1,
    )
    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )
    first_client = OnecODataClient(
        settings,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"value": [{"id": "1"}]})
        ),
    )
    try:
        first = export_collection_sample(
            first_client,
            collection,
            tmp_path / "first",
            top=1,
            max_pages=1,
        )
    finally:
        first_client.close()
    assert first.status == "partial_source"

    requested: list[httpx.Request] = []

    def next_page(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json={"value": [{"id": "2"}]})

    second_client = OnecODataClient(settings, transport=httpx.MockTransport(next_page))
    try:
        second = export_collection_sample(
            second_client,
            collection,
            tmp_path / "second",
            top=1,
            max_pages=1,
            resume_from_dir=tmp_path / "first",
        )
    finally:
        second_client.close()

    assert second.status == "partial_source"
    assert second.reused_page_count == 1
    assert second.page_count == 2
    assert second.row_count == 2
    assert requested[0].url.params["$skip"] == "1"


def test_collection_resume_rejects_corrupted_page(tmp_path: Path) -> None:
    collection = OnecSampleCollection(
        sample_id="resume_corrupt",
        collection_name="Catalog_Test",
        purpose="resume",
        page_size=1,
        min_page_size=1,
    )
    first_dir = tmp_path / "first"
    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )

    def interrupted(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("$skip", "0") == "0":
            return httpx.Response(200, json={"value": [{"id": "old"}]})
        raise httpx.ReadTimeout("interrupted", request=request)

    client = OnecODataClient(settings, transport=httpx.MockTransport(interrupted))
    try:
        result = export_collection_sample(
            client,
            collection,
            first_dir,
            top=1,
            max_pages=2,
            retry_attempts=0,
            retry_delay_seconds=0,
        )
    finally:
        client.close()
    assert result.status == "partial_source"
    page = first_dir / collection.sample_id / "page_000001.raw.json"
    page.write_text('{"value":[{"id":"tampered"}]}', encoding="utf-8")

    requested: list[httpx.Request] = []

    def fresh(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, json={"value": []})

    client = OnecODataClient(settings, transport=httpx.MockTransport(fresh))
    try:
        restarted = export_collection_sample(
            client,
            collection,
            tmp_path / "second",
            top=1,
            max_pages=2,
            retry_attempts=0,
            retry_delay_seconds=0,
            resume_from_dir=first_dir,
        )
    finally:
        client.close()

    assert restarted.ok is True
    assert restarted.reused_page_count == 0
    assert "$skip" not in requested[0].url.params


def test_gross_profit_collections_are_explicit_only() -> None:
    default_ids = {item.sample_id for item in DEFAULT_SAMPLE_COLLECTIONS}
    gross_profit_ids = {item.sample_id for item in GROSS_PROFIT_SAMPLE_COLLECTIONS}

    assert "sales_register" not in default_ids
    assert "sales_register" in gross_profit_ids
    assert _select_collections(["sales_register"])[0].collection_name == (
        "AccumulationRegister_Продажи"
    )


def test_tax_profile_collections_are_read_only_and_selectable() -> None:
    by_id = {item.sample_id: item for item in TAX_PROFILE_SAMPLE_COLLECTIONS}

    assert {
        "tax_system_settings",
        "vat_settings",
        "tax_kinds",
        "tax_accruals",
        "tax_accrual_lines",
        "vat_sales_book",
        "vat_purchase_book",
        "kudir",
        "tax_registrations",
    } <= set(by_id)
    assert by_id["tax_system_settings"].period_filter_mode == "none"
    assert "СтавкаНалога" in by_id["tax_system_settings"].select_fields
    assert (
        "СтавкаНалогообложенияПриУСН"
        in by_id["vat_settings"].select_fields
    )
    assert "Сумма" not in by_id["tax_accrual_lines"].select_fields
    assert {
        "Покупатель_Key",
        "СуммаБезНДС",
        "НДС",
        "НомерСчетаФактурыНаАванс",
        "ДатаСчетаФактурыНаАванс",
        "ЗаписьДополнительногоЛиста",
        "Исправление",
    } <= set(by_id["vat_sales_book"].select_fields)
    assert {
        "Поставщик_Key",
        "СуммаБезНДС",
        "НДС",
        "НомерСчетаФактуры",
        "ДатаСчетаФактуры",
        "ЗаписьДополнительногоЛиста",
    } <= set(by_id["vat_purchase_book"].select_fields)
    assert _select_collections(["vat_sales_book"])[0] == by_id["vat_sales_book"]


def test_input_vat_collections_are_read_only_and_selectable() -> None:
    by_id = {item.sample_id: item for item in INPUT_VAT_SAMPLE_COLLECTIONS}

    assert {
        "import_expenses",
        "vat_presented",
        "vat_deduction_documents",
        "vat_payment_confirmations",
    } == set(by_id)
    assert "Запасы" in by_id["import_expenses"].select_fields
    assert "Разделы" in by_id["import_expenses"].select_fields
    assert by_id["vat_presented"].period_field == ""
    assert _select_collections(["import_expenses"])[0] == by_id["import_expenses"]


def test_incoming_invoice_collection_loads_operation_for_expense_classification(
) -> None:
    collection = next(
        item
        for item in SERVICE_SAMPLE_COLLECTIONS
        if item.sample_id == "incoming_invoices"
    )

    assert collection.collection_name == "Document_ПриходнаяНакладная"
    assert "ВидОперации" in collection.select_fields


def test_accounting_recordtype_fallback_aggregates_by_organization(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    pages = {
        0: [
            {
                "Period": "2026-04-30T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-1",
                "AccountDr_Key": "ACC-51",
                "Сумма": "100",
            },
            {
                "Period": "2026-05-10T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-1",
                "AccountDr_Key": "ACC-51",
                "Сумма": "50",
            },
            {
                "Period": "2026-05-20T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-1",
                "AccountCr_Key": "ACC-51",
                "Сумма": "20",
            },
        ],
        3: [
            {
                "Period": "2026-05-21T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-2",
                "AccountDr_Key": "ACC-51",
                "Сумма": "10",
            },
            {
                "Period": "2026-05-22T12:00:00",
                "Active": False,
                "Организация_Key": "ORG-2",
                "AccountDr_Key": "ACC-51",
                "Сумма": "777",
            },
            {
                "Period": "2026-05-31T12:00:00",
                "Active": True,
                "Организация_Key": "",
                "AccountDr_Key": "ACC-51",
                "Сумма": "1",
            },
        ],
        6: [
            {
                "Period": "2026-06-02T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-1",
                "AccountDr_Key": "ACC-51",
                "Сумма": "999",
            },
            {
                "Period": "2026-06-03T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-2",
                "AccountDr_Key": "ACC-51",
                "Сумма": "888",
            },
            {
                "Period": "2026-06-04T12:00:00",
                "Active": True,
                "Организация_Key": "ORG-2",
                "AccountDr_Key": "ACC-51",
                "Сумма": "7777",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        skip = int(request.url.params.get("$skip", "0"))
        return httpx.Response(200, json={"value": pages.get(skip, [])})

    result = export_onec_accounting_recordtype_balances(
        OnecODataSettings(
            base_url="https://onec.example/odata/standard.odata",
            username="readonly",
            password="test-only",
        ),
        tmp_path,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        page_size=3,
        max_pages=10,
        transport=httpx.MockTransport(handler),
    )

    assert result.ok is True
    assert result.status == "loaded"
    assert result.page_count == 3
    assert result.checkpoint_path is not None
    assert result.checkpoint_path.is_file()
    assert all("$filter" not in request.url.params for request in requests)
    assert all(
        request.url.params["$orderby"]
        == "Period asc,Recorder asc,LineNumber asc"
        for request in requests
    )
    assert all(
        request.url.params["$select"]
        == (
            "Period,Recorder,LineNumber,Active,Организация_Key,"
            "AccountDr_Key,AccountCr_Key,Сумма"
        )
        for request in requests
    )
    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    by_org = {row["Organization_Key"]: row for row in payload["value"]}
    assert by_org["ORG-1"] == {
        "Organization_Key": "ORG-1",
        "Account_Key": "ACC-51",
        "OpeningDebit": "100",
        "OpeningCredit": "0",
        "DebitTurnover": "50",
        "CreditTurnover": "20",
        "ClosingDebit": "130",
        "ClosingCredit": "0",
    }
    assert by_org["ORG-2"]["ClosingDebit"] == "10"


def test_accounting_report_collections_do_not_require_server_period_filters() -> None:
    accounting = {
        item.sample_id: item for item in ACCOUNTING_REPORT_SAMPLE_COLLECTIONS
    }

    assert accounting["accounting_register_records"].period_field == ""
    assert accounting["accounting_taxes"].period_field == ""
    assert accounting["accounting_taxes"].page_size == 5000
    assert accounting["accounting_bank_out"].period_field == ""
    assert accounting["accounting_counterparties"].collection_name == (
        "Catalog_Контрагенты"
    )
    assert accounting["accounting_counterparties"].select_fields == (
        "Ref_Key",
        "Description",
        "DeletionMark",
    )
    assert accounting["nomenclature"].collection_name == "Catalog_Номенклатура"
    assert accounting["supplier_receipts"].collection_name == (
        "Document_ПоступлениеТоваровУслуг"
    )
    assert accounting["supplier_receipt_expenses"].collection_name == (
        "Document_ПоступлениеТоваровУслуг_Услуги"
    )


def test_local_accounting_period_stops_after_selected_window(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    pages = {
        0: {
            "value": [
                {"Period": "2026-04-30T12:00:00"},
                {"Period": "2026-05-31T12:00:00"},
            ]
        },
        2: {
            "value": [
                {"Period": "2026-06-01T12:00:00"},
                {"Period": "2026-06-02T12:00:00"},
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        skip = int(request.url.params.get("$skip", "0"))
        return httpx.Response(200, json=pages.get(skip, {"value": []}))

    settings = OnecODataSettings(
        base_url="https://onec.example/odata/standard.odata",
        username="readonly",
        password="test-only",
    )
    collection = OnecSampleCollection(
        sample_id="accounting_taxes",
        collection_name="AccumulationRegister_РасчетыПоНалогам_RecordType",
        purpose="test",
        period_filter_mode="local_accounting_period",
        page_size=2,
    )
    client = OnecODataClient(settings, transport=httpx.MockTransport(handler))
    try:
        result = export_collection_sample(
            client,
            collection,
            tmp_path,
            top=2,
            max_pages=10,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.page_count == 2
    assert result.row_count == 1
    assert len(requests) == 2
    assert all("$filter" not in request.url.params for request in requests)
    assert all(
        request.url.params["$orderby"]
        == "Period asc,Recorder asc,LineNumber asc"
        for request in requests
    )
    output = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert output["value"] == [{"Period": "2026-05-31T12:00:00"}]
