from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.restore_marketplace_raw_rows import _verified_collection_rows
from wb_unit_economics.source_integrity import (
    RawIntegrityError,
    canonical_payload_hash,
)


def test_restore_rows_are_reconstructed_from_verified_files(tmp_path: Path) -> None:
    source_root = tmp_path / "source_refresh"
    raw_path = source_root / "run" / "wb_finance"
    raw_path.mkdir(parents=True)
    source_rows = [{"rrdId": 42, "retailAmount": "100"}]
    output_path = raw_path / "page.raw.json"
    output_path.write_text(json.dumps(source_rows), encoding="utf-8")
    file_hash = canonical_payload_hash(source_rows)
    manifest_results = [
        {
            "seller_account_id": "seller",
            "page_index": 1,
            "row_count": 1,
            "raw_payload_hash": file_hash,
            "output_file": output_path.name,
        }
    ]
    collection_results = [
        {
            "sellerAccountId": "seller",
            "wbCabinetId": "cabinet",
            "pageIndex": 1,
            "rowCount": 1,
            "rawPayloadHash": file_hash,
            "outputFile": output_path.name,
        }
    ]
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": manifest_results}),
        encoding="utf-8",
    )
    collection = SimpleNamespace(
        raw_path=str(raw_path),
        source_type="wb_finance_detail",
        row_count=1,
        snapshot_hash=canonical_payload_hash(collection_results),
        payload={"results": collection_results},
        loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    rows = _verified_collection_rows(collection, source_root=source_root)

    assert len(rows) == 1
    assert rows[0]["source_row_id"] == "42"
    assert rows[0]["wb_cabinet_id"] == "cabinet"
    assert rows[0]["row_payload"] == source_rows[0]


def test_restore_blocks_modified_raw_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source_refresh"
    raw_path = source_root / "run" / "wb_finance"
    raw_path.mkdir(parents=True)
    output_path = raw_path / "page.raw.json"
    output_path.write_text("[]", encoding="utf-8")
    results = [
        {
            "row_count": 1,
            "raw_payload_hash": "a" * 64,
            "output_file": output_path.name,
        }
    ]
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = SimpleNamespace(
        raw_path=str(raw_path),
        source_type="wb_finance_detail",
        row_count=1,
        snapshot_hash=canonical_payload_hash(results),
        payload={"results": results},
        loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    with pytest.raises(RawIntegrityError, match="hash"):
        _verified_collection_rows(collection, source_root=source_root)
