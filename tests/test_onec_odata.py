from __future__ import annotations

import json
from pathlib import Path

import httpx

from scripts.export_onec_odata_samples import _select_collections
from wb_unit_economics.onec_odata import (
    DEFAULT_SAMPLE_COLLECTIONS,
    GROSS_PROFIT_SAMPLE_COLLECTIONS,
    OnecODataClient,
    OnecODataSettings,
    export_collection_sample,
    extract_odata_rows,
)


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


def test_gross_profit_collections_are_explicit_only() -> None:
    default_ids = {item.sample_id for item in DEFAULT_SAMPLE_COLLECTIONS}
    gross_profit_ids = {item.sample_id for item in GROSS_PROFIT_SAMPLE_COLLECTIONS}

    assert "sales_register" not in default_ids
    assert "sales_register" in gross_profit_ids
    assert _select_collections(["sales_register"])[0].collection_name == (
        "AccumulationRegister_Продажи"
    )
