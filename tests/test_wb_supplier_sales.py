from __future__ import annotations

from datetime import date

import httpx

from wb_unit_economics.wb_supplier_sales import (
    SUPPLIER_SALES_ENDPOINT,
    WbSupplierSalesClient,
    flatten_supplier_sales,
)

_ROWS = [
    {
        "srid": "srid-1",
        "gNumber": "order-1",
        "saleID": "S123",
        "nmId": 101,
        "barcode": "111",
        "date": "2026-07-18T10:00:00",
        "lastChangeDate": "2026-07-18T12:00:00",
        "warehouseName": "Коледино",
        "countryName": "Россия",
        "oblastOkrugName": "Центральный федеральный округ",
        "regionName": "Московская",
    },
    {"srid": "srid-2", "nmId": 102},
]


def test_flatten_supplier_sales_keeps_geo_and_none_for_missing() -> None:
    rows = flatten_supplier_sales(_ROWS)

    assert len(rows) == 2
    first = rows[0]
    assert first["srid"] == "srid-1"
    assert first["warehouse_name"] == "Коледино"
    assert first["country_name"] == "Россия"
    assert first["region_name"] == "Московская"
    assert first["g_number"] == "order-1"
    # у второй строки склад/направление отсутствуют -> None, а не пусто
    assert rows[1]["warehouse_name"] is None
    assert rows[1]["region_name"] is None
    assert rows[1]["oblast_okrug_name"] is None


def test_client_fetch_supplier_sales_is_read_only_get_list() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_ROWS)

    client = WbSupplierSalesClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    rows = client.fetch_supplier_sales(date(2026, 7, 1))

    assert len(rows) == 2
    assert seen[0].method == "GET"
    assert str(seen[0].url).startswith(SUPPLIER_SALES_ENDPOINT)
    assert seen[0].url.params["dateFrom"] == "2026-07-01"
    assert seen[0].headers["Authorization"] == "test-key"


def test_client_rejects_non_list_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "object"})

    client = WbSupplierSalesClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    try:
        client.fetch_supplier_sales(date(2026, 7, 1))
    except ValueError as exc:
        assert "supplier sales" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for non-list payload")
