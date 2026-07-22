from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from wb_unit_economics.wb_goods_return import (
    GOODS_RETURN_ENDPOINT,
    WbGoodsReturnClient,
    build_goods_return_links,
    export_wb_goods_return,
    flatten_goods_return,
    normalize_goods_return_source_row,
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


def test_client_accepts_exactly_31_calendar_days_and_requires_report_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["dateFrom"] == "2026-07-01":
            return httpx.Response(200, json={"report": []})
        return httpx.Response(200, json={"data": []})

    client = WbGoodsReturnClient(
        api_key="test-key", _transport=httpx.MockTransport(handler)
    )
    assert client.fetch_goods_return(date(2026, 7, 1), date(2026, 7, 31)) == {
        "report": []
    }
    with pytest.raises(ValueError, match="Unexpected"):
        client.fetch_goods_return(date(2026, 7, 2), date(2026, 7, 31))


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
    assert result.flat_payload_hash
    assert result.coverage_start == date(2026, 7, 1)
    assert result.coverage_end == date(2026, 7, 20)
    assert result.flat_output_path is not None and result.flat_output_path.exists()
    flat = json.loads(result.flat_output_path.read_text(encoding="utf-8"))
    assert flat[0]["reason"] == "Цвет"


def _source_row(
    *,
    srid: object = "srid-1",
    nm_id: object = "101",
    reason: object = "Не подошёл цвет",
    cabinet_id: str = "cabinet-a",
):
    return normalize_goods_return_source_row(
        {
            "srid": srid,
            "order_id": "assembly-1",
            "nm_id": nm_id,
            "barcode": "barcode-1",
            "reason": reason,
            "status": "returned",
            "return_type": "seller_return",
        },
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id=cabinet_id,
    )


def _finance_row(
    *,
    chain_key: str = "chain-a",
    finance_srid: str = "srid-1",
    order_uid: str = "different-order-uid",
    nm_id: str = "101",
    cabinet_id: str = "cabinet-a",
):
    return SimpleNamespace(
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id=cabinet_id,
        nm_id=nm_id,
        finance_srid=finance_srid,
        order_uid=order_uid,
        chain_key=chain_key,
    )


def _return_chain(
    *,
    chain_key: str = "chain-a",
    financial_date: date = date(2026, 7, 20),
):
    return SimpleNamespace(
        chain_key=chain_key,
        financial_date=financial_date,
        return_quantity=1,
        logistics_reverse=0,
    )


def test_goods_return_link_uses_finance_srid_and_one_canonical_return_chain() -> None:
    result = build_goods_return_links(
        [_finance_row()],
        [_return_chain()],
        [_source_row()],
        source_coverage_start=date(2026, 7, 1),
        source_coverage_end=date(2026, 7, 31),
    )

    assert result.matched_chain_count == 1
    assert result.reason_available_count == 1
    assert result.finance_unmatched_count == 0
    assert result.methodology_version == "wb-logistics-return-reasons-v1"
    assert len(result.input_hash) == 64
    assert result.rows[0].chain_key == "chain-a"
    assert result.rows[0].coverage_status == "ready"
    assert result.rows[0].evidence_type == "fact"


def test_goods_return_link_rejects_cross_field_scope_and_chain_ambiguity() -> None:
    cross_field = build_goods_return_links(
        [_finance_row(finance_srid="finance-srid", order_uid="srid-1")],
        [_return_chain()],
        [_source_row()],
        source_coverage_start=date(2026, 7, 1),
        source_coverage_end=date(2026, 7, 31),
    )
    assert cross_field.rows[0].coverage_status == "unmatched_finance"

    ambiguous = build_goods_return_links(
        [
            _finance_row(chain_key="chain-a"),
            _finance_row(chain_key="chain-b"),
        ],
        [_return_chain(chain_key="chain-a"), _return_chain(chain_key="chain-b")],
        [_source_row()],
        source_coverage_start=date(2026, 7, 1),
        source_coverage_end=date(2026, 7, 31),
    )
    assert ambiguous.rows[0].coverage_status == "conflicting_finance"
    assert ambiguous.conflicting_finance_count == 1

    other_scope = build_goods_return_links(
        [_finance_row(cabinet_id="cabinet-b")],
        [_return_chain()],
        [_source_row(cabinet_id="cabinet-a")],
        source_coverage_start=date(2026, 7, 1),
        source_coverage_end=date(2026, 7, 31),
    )
    assert other_scope.rows[0].coverage_status == "unmatched_finance"


def test_goods_return_link_marks_invalid_identity_and_source_conflict() -> None:
    invalid = build_goods_return_links(
        [_finance_row()],
        [_return_chain()],
        [_source_row(nm_id=True)],
        source_coverage_start=date(2026, 7, 1),
        source_coverage_end=date(2026, 7, 31),
    )
    assert invalid.invalid_source_count == 1
    assert invalid.rows[0].coverage_status == "invalid_source_identity"

    conflict = build_goods_return_links(
        [_finance_row()],
        [_return_chain()],
        [_source_row(reason="Причина A"), _source_row(reason="Причина B")],
        source_coverage_start=date(2026, 7, 1),
        source_coverage_end=date(2026, 7, 31),
    )
    assert conflict.conflicting_source_count == 1
    assert conflict.rows[0].coverage_status == "conflicting_source"
