from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from wb_unit_economics.wb_goods_return import (
    GOODS_RETURN_ENDPOINT,
    WbGoodsReturnClient,
    export_wb_goods_return,
    flatten_goods_return,
)

_PAYLOAD = {
    "report": [
        {
            "srid": "srid-1",
            "orderId": "order-1",
            "nmId": 101,
            "barcode": "111",
            "reason": "Цвет",
            "status": "В пути в ПВЗ",
            "returnType": "Возврат заблокированного товара",
        },
        {"srid": "srid-2", "nmId": 102},
    ]
}


def test_flatten_goods_return_keeps_reason_and_none_for_missing() -> None:
    rows = flatten_goods_return(_PAYLOAD)

    assert len(rows) == 2
    assert rows[0]["srid"] == "srid-1"
    assert rows[0]["reason"] == "Цвет"
    assert rows[0]["return_type"] == "Возврат заблокированного товара"
    # отсутствующая причина остаётся None, а не пустой строкой
    assert rows[1]["srid"] == "srid-2"
    assert rows[1]["reason"] is None
    assert rows[1]["order_id"] is None


def test_flatten_goods_return_empty_without_rows() -> None:
    assert flatten_goods_return({}) == []
    assert flatten_goods_return({"report": {}}) == []


def test_client_fetch_is_read_only_get_with_window() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_PAYLOAD)

    client = WbGoodsReturnClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    payload = client.fetch_goods_return(date(2026, 7, 1), date(2026, 7, 20))

    assert payload == _PAYLOAD
    assert seen[0].method == "GET"
    assert str(seen[0].url).startswith(GOODS_RETURN_ENDPOINT)
    assert seen[0].url.params["dateFrom"] == "2026-07-01"
    assert seen[0].url.params["dateTo"] == "2026-07-20"
    assert seen[0].headers["Authorization"] == "test-key"


def test_client_rejects_window_over_31_days() -> None:
    client = WbGoodsReturnClient(api_key="test-key")
    with pytest.raises(ValueError, match="31 days"):
        client.fetch_goods_return(date(2026, 6, 1), date(2026, 7, 20))


def test_export_wb_goods_return_writes_raw_and_flat(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_PAYLOAD)

    client = WbGoodsReturnClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    result = export_wb_goods_return(
        client, tmp_path, date_from=date(2026, 7, 1), date_to=date(2026, 7, 20)
    )

    assert result.ok is True
    assert result.row_count == 2
    assert result.flat_output_path is not None and result.flat_output_path.exists()
    flat = json.loads(result.flat_output_path.read_text(encoding="utf-8"))
    assert flat[0]["reason"] == "Цвет"
