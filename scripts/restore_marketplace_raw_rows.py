#!/usr/bin/env python3
"""Restore marketplace source_snapshot_rows from verified immutable files."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.source_integrity import (
    RawIntegrityError,
    canonical_payload_hash,
    verify_raw_directory,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshCollection, SourceSnapshotRow

SUPPORTED_TYPES = {
    "wb_finance_detail",
    "wb_sales_report_list",
    "wb_product_cards",
    "ozon_finance_cash_flow",
    "ozon_realization",
    "ozon_realization_posting",
    "ozon_mutual_settlement",
    "ozon_products_buyout",
    "ozon_b2b_sales_json",
    "ozon_products_report",
}


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        print("Database URL is required; no rows were restored.", file=sys.stderr)
        return 2
    if args.apply and args.raw_db_mode != "legacy":
        print(
            "SOURCE_REFRESH_RAW_DB_MODE=legacy is required with --apply; "
            "no rows were restored.",
            file=sys.stderr,
        )
        return 2
    session_factory = make_session_factory(make_engine(database_url))
    with session_factory() as db:
        statement = select(SourceRefreshCollection).where(
            SourceRefreshCollection.refresh_run_id == args.run_id
        )
        if args.collection_id:
            statement = statement.where(
                SourceRefreshCollection.id == args.collection_id
            )
        collections = list(db.scalars(statement.order_by(SourceRefreshCollection.id)))
        if not collections:
            print("No matching collections; no rows were restored.", file=sys.stderr)
            return 2
        plans: list[tuple[SourceRefreshCollection, list[dict[str, Any]], int]] = []
        for collection in collections:
            if collection.source_type not in SUPPORTED_TYPES:
                if args.collection_id:
                    print(
                        f"Unsupported collection source: {collection.source_type}",
                        file=sys.stderr,
                    )
                    return 2
                continue
            try:
                rows = _verified_collection_rows(
                    collection,
                    source_root=Path(args.source_root),
                )
            except (OSError, RawIntegrityError, TypeError, ValueError) as exc:
                print(
                    f"Collection {collection.id} failed integrity: {exc}",
                    file=sys.stderr,
                )
                return 2
            existing = {
                int(row.row_number): row
                for row in db.scalars(
                    select(SourceSnapshotRow).where(
                        SourceSnapshotRow.collection_id == collection.id
                    )
                )
            }
            missing: list[dict[str, Any]] = []
            for row in rows:
                current = existing.get(int(row["row_number"]))
                if current is None:
                    missing.append(row)
                    continue
                if (
                    current.raw_payload_hash != row["raw_payload_hash"]
                    or current.row_payload != row["row_payload"]
                ):
                    raise ValueError(
                        f"collection {collection.id} has conflicting restored row"
                    )
            plans.append((collection, missing, len(rows) - len(missing)))

        for collection, missing, existing_count in plans:
            print(
                f"collection={collection.id} source={collection.source_type} "
                f"existing={existing_count} restore={len(missing)}"
            )
        if not args.apply:
            print("Dry run only. Re-run with --apply in legacy mode.")
            return 0
        restored = 0
        for collection, missing, _existing_count in plans:
            for start in range(0, len(missing), max(100, args.batch_size)):
                restored += repository.add_source_snapshot_rows(
                    db,
                    collection,
                    missing[start : start + max(100, args.batch_size)],
                )
        db.commit()
    print(f"Restored rows: {restored}")
    return 0


def _verified_collection_rows(
    collection: SourceRefreshCollection,
    *,
    source_root: Path,
) -> list[dict[str, Any]]:
    payload = collection.payload or {}
    results = payload.get("results")
    if not isinstance(results, list):
        raise RawIntegrityError("collection results are missing")
    verify_raw_directory(
        Path(collection.raw_path),
        source_type=collection.source_type,
        source_root=source_root,
        collection_results=results,
        collection_row_count=collection.row_count,
        collection_snapshot_hash=collection.snapshot_hash,
    )
    rows: list[dict[str, Any]] = []
    row_number = 1
    for result in results:
        if not isinstance(result, dict):
            raise RawIntegrityError("collection result is invalid")
        output_name = _result_text(result, "outputFile", "output_file")
        if collection.source_type == "wb_product_cards":
            output_name = _result_text(
                result,
                "flatOutputFile",
                "flat_output_file",
            )
        if not output_name:
            continue
        source_rows = _json_rows(Path(collection.raw_path) / output_name)
        cabinet_id = _result_text(result, "wbCabinetId", "wb_cabinet_id")
        seller_id = _result_text(
            result,
            "sellerAccountId",
            "seller_account_id",
        )
        page_index = _result_int(result, "pageIndex", "page_index")
        source_endpoint = _result_text(result, "sourceEndpoint", "source_endpoint")
        for local_index, source_row in enumerate(source_rows, 1):
            row_payload = dict(source_row)
            if collection.source_type == "wb_product_cards":
                row_payload.update(
                    {
                        "marketplace": "wb",
                        "seller_account_id": seller_id,
                        "source_page_index": page_index,
                        "source_output_file": output_name,
                    }
                )
            elif collection.source_type.startswith("ozon_"):
                row_payload.update(
                    {
                        "marketplace": "ozon",
                        "seller_account_id": seller_id,
                        "source_endpoint": source_endpoint,
                        "source_page_index": page_index,
                        "source_output_file": output_name,
                    }
                )
            source_row_id = _source_row_id(
                row_payload,
                source_type=collection.source_type,
                page_index=page_index,
                local_index=local_index,
            )
            rows.append(
                {
                    "row_number": row_number,
                    "raw_payload_hash": canonical_payload_hash(row_payload),
                    "row_payload": row_payload,
                    "source_row_id": source_row_id,
                    "wb_cabinet_id": cabinet_id,
                    "loaded_at": collection.loaded_at,
                }
            )
            row_number += 1
    if len(rows) != collection.row_count:
        raise RawIntegrityError("reconstructed row count differs from collection")
    return rows


def _json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "items", "result", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    raise RawIntegrityError("raw payload has no rows")


def _source_row_id(
    row: dict[str, Any],
    *,
    source_type: str,
    page_index: int,
    local_index: int,
) -> str:
    keys = (
        ("rrdId", "srid", "orderUid")
        if source_type == "wb_finance_detail"
        else ("reportId",)
        if source_type == "wb_sales_report_list"
        else (
            "id",
            "operation_id",
            "posting_number",
            "product_id",
            "offer_id",
            "sku",
            "nm_id",
            "barcode",
            "vendor_code",
        )
    )
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:240]
    if source_type.startswith("wb_"):
        return f"{page_index}:{local_index}"[:240]
    return f"{source_type}:{page_index}:{local_index}"[:240]


def _result_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _result_int(item: dict[str, Any], *keys: str) -> int:
    value = _result_text(item, *keys)
    return int(value) if value else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--source-root", default="data/source_refresh")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--collection-id", type=int)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument(
        "--raw-db-mode",
        default=os.getenv("SHUMEYKO_SOURCE_REFRESH_RAW_DB_MODE", ""),
        choices=("", "legacy", "files_only"),
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
