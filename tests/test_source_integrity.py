from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wb_unit_economics.source_integrity import (
    canonical_payload_hash,
    verify_raw_directory,
)


def test_ozon_report_integrity_counts_downloaded_rows_not_control_responses(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "source" / "ozon_products_report"
    raw_path.mkdir(parents=True)
    files = {
        "create.raw.json": ({"result": {"code": "report"}}, 1),
        "info.raw.json": ({"result": {"status": "success"}}, 1),
        "report_file.raw.csv": (b"sku\n1\n2\n", 2),
    }
    results = []
    for index, (name, (content, row_count)) in enumerate(files.items(), 1):
        path = raw_path / name
        if isinstance(content, bytes):
            path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
        else:
            path.write_text(json.dumps(content), encoding="utf-8")
            digest = hashlib.sha256(
                json.dumps(
                    content,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
        endpoint = (
            "report_file"
            if "file" in name
            else "/v1/report/info"
            if "info" in name
            else "/v1/report/products/create"
        )
        results.append(
            {
                "sellerAccountId": "seller",
                "pageIndex": index,
                "rowCount": row_count,
                "statusCode": 200,
                "sourceEndpoint": endpoint,
                "rawPayloadHash": digest,
                "outputFile": name,
            }
        )
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )

    verified = verify_raw_directory(
        raw_path,
        source_type="ozon_products_report",
        source_root=tmp_path / "source",
        collection_results=results,
        collection_row_count=2,
        collection_snapshot_hash=canonical_payload_hash(results),
    )

    assert verified.row_count == 2
    assert verified.file_count == 3
