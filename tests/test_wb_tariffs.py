from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from wb_unit_economics.wb_tariffs import (
    TARIFFS_BOX_ENDPOINT,
    WbTariffsClient,
    export_wb_tariffs,
    flatten_box_tariffs,
    flatten_pallet_tariffs,
)

_BOX_PAYLOAD = {
    "response": {
        "data": {
            "dtNextBox": "2026-07-21",
            "dtTillMax": "2026-08-01",
            "warehouseList": [
                {
                    "warehouseName": "Коледино",
                    "boxDeliveryBase": "48",
                    "boxDeliveryLiter": "12",
                    "boxDeliveryCoefExpr": "125",
                    "boxStorageBase": "0,1",
                    "boxStorageCoefExpr": "115",
                },
                {"warehouseName": "Электросталь"},
            ],
        }
    }
}

_PALLET_PAYLOAD = {
    "data": {
        "dtNextPallet": "2026-07-21",
        "dtTillMax": "2026-08-01",
        "warehouseList": [
            {
                "warehouseName": "Коледино",
                "palletDeliveryExpr": "200",
                "palletStorageExpr": "50",
            }
        ],
    }
}


def test_flatten_box_tariffs_keeps_period_and_none_for_missing() -> None:
    rows = flatten_box_tariffs(_BOX_PAYLOAD, date(2026, 7, 19))

    assert len(rows) == 2
    first = rows[0]
    assert first["requested_date"] == "2026-07-19"
    assert first["warehouse_name"] == "Коледино"
    assert first["dt_next_box"] == "2026-07-21"
    assert first["dt_till_max"] == "2026-08-01"
    assert first["box_delivery_coef_expr"] == "125"
    assert first["box_storage_base"] == "0,1"
    # у второго склада коэффициенты отсутствуют -> None, а не 0
    assert rows[1]["warehouse_name"] == "Электросталь"
    assert rows[1]["box_delivery_base"] is None
    assert rows[1]["box_delivery_coef_expr"] is None
    # период действия наследуется на все склады
    assert rows[1]["dt_next_box"] == "2026-07-21"


def test_flatten_pallet_tariffs_handles_flat_data_nesting() -> None:
    rows = flatten_pallet_tariffs(_PALLET_PAYLOAD, date(2026, 7, 19))

    assert len(rows) == 1
    assert rows[0]["pallet_delivery_expr"] == "200"
    assert rows[0]["dt_next_pallet"] == "2026-07-21"
    assert rows[0]["pallet_storage_value_expr"] is None


def test_flatten_box_tariffs_returns_empty_without_warehouse_list() -> None:
    assert flatten_box_tariffs({}, date(2026, 7, 19)) == []
    assert flatten_box_tariffs({"response": {"data": {}}}, date(2026, 7, 19)) == []


def test_client_fetch_box_tariffs_is_read_only_get_with_date() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_BOX_PAYLOAD)

    client = WbTariffsClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    payload = client.fetch_box_tariffs(date(2026, 7, 19))

    assert payload == _BOX_PAYLOAD
    assert seen[0].method == "GET"
    assert str(seen[0].url).startswith(TARIFFS_BOX_ENDPOINT)
    assert seen[0].url.params["date"] == "2026-07-19"
    assert seen[0].headers["Authorization"] == "test-key"


def test_export_wb_tariffs_writes_raw_and_flat(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _BOX_PAYLOAD if "box" in str(request.url) else _PALLET_PAYLOAD
        return httpx.Response(200, json=payload)

    client = WbTariffsClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    result = export_wb_tariffs(client, tmp_path, target_date=date(2026, 7, 19))

    assert result.ok is True
    assert result.box_row_count == 2
    assert result.pallet_row_count == 1
    assert result.raw_output_path is not None and result.raw_output_path.exists()
    assert result.flat_output_path is not None and result.flat_output_path.exists()
    flat = json.loads(result.flat_output_path.read_text(encoding="utf-8"))
    assert flat["box"][0]["dt_next_box"] == "2026-07-21"


def test_export_wb_tariffs_reports_error_without_writing(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = WbTariffsClient(
        api_key="bad", _transport=httpx.MockTransport(handler)
    )
    result = export_wb_tariffs(client, tmp_path, target_date=date(2026, 7, 19))

    assert result.ok is False
    assert result.error
    assert list(tmp_path.iterdir()) == []
