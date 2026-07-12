from __future__ import annotations

from scripts.compare_ozon_legacy_typed import PARITY_SECTIONS, _parity_artifact


def _payload(rows: list[dict[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {name: {} for name in PARITY_SECTIONS}
    payload["ozonMart"] = {
        "totals": {"profit": 100.0},
        "rows": rows,
    }
    return payload


def test_ozon_parity_compares_rows_by_business_grain_not_sql_order() -> None:
    legacy = _payload(
        [
            {"id": "legacy-1", "rowNumber": 1, "offerId": "A", "amount": 10},
            {"id": "legacy-2", "rowNumber": 2, "offerId": "B", "amount": 20},
        ]
    )
    typed = _payload(
        [
            {"id": "typed-2", "rowNumber": 900, "offerId": "B", "amount": 20},
            {"id": "typed-1", "rowNumber": 800, "offerId": "A", "amount": 10},
        ]
    )

    artifact = _parity_artifact(legacy, typed, refresh_run_id="run")

    assert artifact["status"] == "matched"
    assert artifact["mismatches"] == []


def test_ozon_parity_detects_financial_difference() -> None:
    legacy = _payload([{"offerId": "A", "amount": 10}])
    typed = _payload([{"offerId": "A", "amount": 9.99}])

    artifact = _parity_artifact(legacy, typed, refresh_run_id="run")

    assert artifact["status"] == "mismatch"
    assert artifact["mismatches"] == ["ozonMart"]
