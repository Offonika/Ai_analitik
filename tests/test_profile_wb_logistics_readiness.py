from __future__ import annotations

import json
from pathlib import Path

from scripts.profile_wb_logistics_readiness import (
    discover_finance_files,
    profile_finance_files,
)


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_profile_reports_safe_order_key_and_direction_coverage(tmp_path: Path) -> None:
    source = tmp_path / "daily-test" / "wb_finance"
    path = source / "wb_account_1_finance_page_1.raw.json"
    _write_rows(
        path,
        [
            {
                "rrdId": 1,
                "orderUid": "order-1",
                "srid": "srid-1",
                "nmId": 101,
                "deliveryService": "10",
                "deliveryAmount": 1,
                "returnAmount": 0,
                "officeName": "Склад",
                "dlvPrc": 1.2,
            },
            {
                "rrdId": 2,
                "orderUid": "order-1",
                "srid": "srid-1",
                "nmId": 101,
                "deliveryService": "20",
                "deliveryAmount": 0,
                "returnAmount": 1,
            },
            {
                "rrdId": 3,
                "srid": "srid-2",
                "nmId": 202,
                "deliveryService": 0,
                "deliveryAmount": 0,
                "returnAmount": 0,
            },
            {
                "rrdId": 4,
                "nmId": 303,
                "deliveryService": "5",
                "deliveryAmount": "bad",
                "returnAmount": 0,
            },
        ],
    )

    paths = discover_finance_files(tmp_path / "daily-test")
    profile = profile_finance_files(paths)

    assert paths == [path]
    assert profile["rowCount"] == 4
    assert profile["logisticsRowCount"] == 3
    assert profile["orderChain"] == {
        "candidateFallbackOrder": [
            "orderUid",
            "srid",
            "orderId",
            "shkId",
            "stickerId",
        ],
        "rowCoveragePct": 75.0,
        "logisticsRowCoveragePct": 66.67,
        "distinctChainCount": 2,
        "multirowChainCount": 1,
        "multirowChainPct": 50.0,
        "conflictingProductChainCount": 0,
        "keyProfiles": {
            "orderUid": {
                "rowCoveragePct": 50.0,
                "logisticsRowCoveragePct": 66.67,
                "distinctChainCount": 1,
                "multirowChainCount": 1,
                "multirowChainPct": 100.0,
                "conflictingProductChainCount": 0,
            },
            "srid": {
                "rowCoveragePct": 75.0,
                "logisticsRowCoveragePct": 66.67,
                "distinctChainCount": 2,
                "multirowChainCount": 1,
                "multirowChainPct": 50.0,
                "conflictingProductChainCount": 0,
            },
            "orderId": {
                "rowCoveragePct": 0.0,
                "logisticsRowCoveragePct": 0.0,
                "distinctChainCount": 0,
                "multirowChainCount": 0,
                "multirowChainPct": None,
                "conflictingProductChainCount": 0,
            },
            "shkId": {
                "rowCoveragePct": 0.0,
                "logisticsRowCoveragePct": 0.0,
                "distinctChainCount": 0,
                "multirowChainCount": 0,
                "multirowChainPct": None,
                "conflictingProductChainCount": 0,
            },
            "stickerId": {
                "rowCoveragePct": 0.0,
                "logisticsRowCoveragePct": 0.0,
                "distinctChainCount": 0,
                "multirowChainCount": 0,
                "multirowChainPct": None,
                "conflictingProductChainCount": 0,
            },
        },
    }
    assert profile["directionSignalsOnLogisticsRows"] == {
        "forward_only": {"count": 1, "pct": 33.33},
        "reverse_only": {"count": 1, "pct": 33.33},
        "both": {"count": 0, "pct": 0.0},
        "none": {"count": 1, "pct": 33.33},
    }
    assert profile["fieldCoverage"]["dlvPrc"] == {
        "presentPct": 25.0,
        "nonEmptyPct": 25.0,
        "presentOnLogisticsRowsPct": 33.33,
        "nonEmptyOnLogisticsRowsPct": 33.33,
    }
    assert profile["numericValidity"]["deliveryAmount"] == {
        "invalidCount": 1,
        "invalidPct": 25.0,
    }


def test_profile_does_not_return_raw_identifiers_or_monetary_totals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "wb_finance" / "wb_account_1_finance_page_1.raw.json"
    _write_rows(
        path,
        [
            {
                "orderUid": "private-order-id",
                "vendorCode": "private-article",
                "title": "private-title",
                "deliveryService": "123.45",
            }
        ],
    )

    serialized = json.dumps(profile_finance_files([path]), ensure_ascii=False)

    assert "private-order-id" not in serialized
    assert "private-article" not in serialized
    assert "private-title" not in serialized
    assert "123.45" not in serialized


def test_profile_links_same_account_chain_across_pages(tmp_path: Path) -> None:
    source = tmp_path / "wb_finance"
    first = source / "wb_account_1_finance_page_1.raw.json"
    second = source / "wb_account_1_finance_page_2.raw.json"
    _write_rows(
        first,
        [{"orderUid": "same-order", "nmId": 101, "deliveryService": 10}],
    )
    _write_rows(
        second,
        [{"orderUid": "same-order", "nmId": 202, "deliveryService": 20}],
    )

    profile = profile_finance_files([first, second])

    assert profile["orderChain"]["distinctChainCount"] == 1
    assert profile["orderChain"]["multirowChainCount"] == 1
    assert profile["orderChain"]["conflictingProductChainCount"] == 1
