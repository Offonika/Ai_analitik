from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

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


def test_restore_ozon_rows_uses_shared_csv_tsv_and_xlsx_parser(
    tmp_path: Path,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["operation_id", "amount"])
    sheet.append(["op-xlsx", 30])
    xlsx = BytesIO()
    workbook.save(xlsx)
    workbook.close()
    fixtures = {
        ".csv": b"operation_id;amount\nop-csv;10\n",
        ".tsv": b"operation_id\tamount\nop-tsv\t20\n",
        ".xlsx": xlsx.getvalue(),
    }

    for suffix, content in fixtures.items():
        raw_path = tmp_path / "source_refresh" / suffix.removeprefix(".")
        raw_path.mkdir(parents=True)
        output_path = raw_path / f"report.raw{suffix}"
        output_path.write_bytes(content)
        file_hash = hashlib.sha256(content).hexdigest()
        results = [
            {
                "sourceType": "ozon_mutual_settlement_file",
                "sellerAccountId": "seller",
                "wbCabinetId": "cabinet",
                "pageIndex": 1,
                "rowCount": 1,
                "rawPayloadHash": file_hash,
                "rawContentSha256": file_hash,
                "outputFile": output_path.name,
                "sourceEndpoint": "report_file",
            }
        ]
        (raw_path / "manifest.json").write_text(
            json.dumps({"results": results}),
            encoding="utf-8",
        )
        collection = SimpleNamespace(
            raw_path=str(raw_path),
            source_type="ozon_mutual_settlement",
            row_count=1,
            snapshot_hash=canonical_payload_hash(results),
            payload={"results": results},
            loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
        )

        rows = _verified_collection_rows(
            collection,
            source_root=tmp_path / "source_refresh",
        )

        assert len(rows) == 1
        assert rows[0]["source_row_id"].startswith("op-")


def test_restore_ozon_report_skips_create_and_info_responses(tmp_path: Path) -> None:
    source_root = tmp_path / "source_refresh"
    raw_path = source_root / "report"
    raw_path.mkdir(parents=True)
    fixtures = [
        (
            "create.raw.json",
            {"result": {"code": "report-code"}},
            "/v1/report/products/create",
        ),
        (
            "info.raw.json",
            {"result": {"status": "success", "file": "report.json"}},
            "/v1/report/info",
        ),
        (
            "file.raw.json",
            {"rows": [{"operation_id": "op-1", "amount": 10}]},
            "report_file",
        ),
    ]
    results = []
    for index, (name, payload, endpoint) in enumerate(fixtures, 1):
        output_path = raw_path / name
        content = json.dumps(payload).encode("utf-8")
        output_path.write_bytes(content)
        content_hash = hashlib.sha256(content).hexdigest()
        results.append(
            {
                "sourceType": "ozon_products_report",
                "sellerAccountId": "seller",
                "wbCabinetId": "cabinet",
                "pageIndex": index,
                "rowCount": 1,
                "rawPayloadHash": canonical_payload_hash(payload),
                "rawContentSha256": content_hash,
                "outputFile": name,
                "sourceEndpoint": endpoint,
            }
        )
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = SimpleNamespace(
        raw_path=str(raw_path),
        source_type="ozon_products_report",
        row_count=1,
        snapshot_hash=canonical_payload_hash(results),
        payload={"results": results},
        loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    rows = _verified_collection_rows(collection, source_root=source_root)

    assert len(rows) == 1
    assert rows[0]["source_row_id"] == "op-1"


def test_restore_ozon_report_skips_create_without_info_response(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_refresh"
    raw_path = source_root / "report"
    raw_path.mkdir(parents=True)
    output_path = raw_path / "create.raw.json"
    payload = {"result": {"code": "report-code"}}
    content = json.dumps(payload).encode("utf-8")
    output_path.write_bytes(content)
    content_hash = hashlib.sha256(content).hexdigest()
    results = [
        {
            "sourceType": "ozon_products_report",
            "sellerAccountId": "seller",
            "wbCabinetId": "cabinet",
            "pageIndex": 1,
            "rowCount": 0,
            "rawPayloadHash": canonical_payload_hash(payload),
            "rawContentSha256": content_hash,
            "outputFile": output_path.name,
            "sourceEndpoint": "/v1/report/products/create",
        }
    ]
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = SimpleNamespace(
        raw_path=str(raw_path),
        source_type="ozon_products_report",
        row_count=0,
        snapshot_hash=canonical_payload_hash(results),
        payload={"results": results},
        loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
    )

    rows = _verified_collection_rows(collection, source_root=source_root)

    assert rows == []
