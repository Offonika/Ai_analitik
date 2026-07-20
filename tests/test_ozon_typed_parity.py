from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.compare_ozon_legacy_typed import (
    PARITY_SECTIONS,
    _parity_artifact,
    _parity_row_limit,
    _record_parity,
)
from scripts.materialize_ozon_typed_facts import _promotion_preflight_error


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


def test_recorded_ozon_parity_requires_integrity_coverage_and_staging() -> None:
    collection = SimpleNamespace(
        refresh_run_id="run",
        status="loaded",
        payload={
            "rawIntegrity": {"status": "verified"},
            "typedParity": {
                "persistenceParity": {"status": "matched"},
                "legacyFileParity": {"status": "matched"},
                "sourceCoverage": {"status": "matched"},
            },
        },
    )
    artifact = {
        "status": "matched",
        "legacyDigest": "legacy",
        "typedDigest": "typed",
        "mismatches": [],
        "referenceMode": "legacy_db_rows",
        "normalizedRealization": {"status": "matched"},
    }

    _record_parity([collection], artifact=artifact, artifact_path=Path("parity.json"))

    assert collection.payload["typedParity"]["status"] == "matched"
    assert collection.payload["typedParity"]["qualificationRunId"] == "run"

    collection.payload["rawIntegrity"]["status"] = "mismatch"
    _record_parity([collection], artifact=artifact, artifact_path=Path("parity.json"))
    assert collection.payload["typedParity"]["status"] == "mismatch"

    collection.payload["rawIntegrity"]["status"] = "verified"
    collection.status = "partial_source"
    _record_parity([collection], artifact=artifact, artifact_path=Path("parity.json"))
    assert collection.payload["typedParity"]["status"] == "mismatch"


def test_standalone_materialize_rejects_partial_or_unfinished_run() -> None:
    collection = SimpleNamespace(
        source_type="ozon_realization",
        status="partial_source",
    )
    finished_run = SimpleNamespace(
        dry_run=False,
        finished_at=object(),
        status="needs_review",
    )
    running_run = SimpleNamespace(
        dry_run=False,
        finished_at=None,
        status="running",
    )

    assert _promotion_preflight_error(finished_run, [collection]) == (
        "source_collection_not_promotable:ozon_realization"
    )
    assert _promotion_preflight_error(running_run, [collection]) == (
        "refresh_run_is_not_finished"
    )


def test_record_parity_limit_covers_expanded_typed_facts() -> None:
    class Counts:
        def __init__(self) -> None:
            self.values = iter((50_000, 75_001))

        def scalar(self, _statement: object) -> int:
            return next(self.values)

    collections = [SimpleNamespace(id=1, row_count=50_000)]

    assert (
        _parity_row_limit(
            Counts(),
            collections,
            refresh_run_id="run",
            requested_limit=50_000,
            record=True,
        )
        == 75_001
    )
