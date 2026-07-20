#!/usr/bin/env python3
"""Verify saved Ozon files and atomically materialize typed/current facts."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.ozon import OzonPageResult
from wb_unit_economics.source_integrity import RawIntegrityError, verify_raw_directory
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshCollection, SourceRefreshRun
from wb_unit_economics.web.source_refresh import (
    MANDATORY_OK_STATUSES,
    OZON_TYPED_FILE_AUTHORITATIVE_TYPES,
    _materialize_ozon_typed_collection,
    _ozon_daily_facts_for_run,
)


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        print("Database URL is required; no facts were changed.", file=sys.stderr)
        return 2
    factory = make_session_factory(make_engine(database_url))
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, args.run_id)
        if refresh_run is None:
            print("Source refresh run was not found.", file=sys.stderr)
            return 2
        collections = list(
            db.scalars(
                select(SourceRefreshCollection)
                .where(
                    SourceRefreshCollection.refresh_run_id == refresh_run.id,
                    SourceRefreshCollection.source_type.in_(
                        OZON_TYPED_FILE_AUTHORITATIVE_TYPES
                    ),
                )
                .order_by(SourceRefreshCollection.id)
            )
        )
        if not collections:
            print("No supported Ozon collections were found.", file=sys.stderr)
            return 2
        preflight_error = _promotion_preflight_error(refresh_run, collections)
        if preflight_error:
            print(f"Promotion preflight failed: {preflight_error}", file=sys.stderr)
            return 3

        verified: list[
            tuple[SourceRefreshCollection, list[OzonPageResult], dict[str, str]]
        ] = []
        try:
            for collection in collections:
                results, cabinet_ids = _verified_results(
                    collection,
                    source_root=Path(args.source_root),
                )
                verified.append((collection, results, cabinet_ids))
                print(
                    f"collection={collection.id} source={collection.source_type} "
                    f"rows={collection.row_count} files=verified"
                )
        except (OSError, RawIntegrityError, TypeError, ValueError) as exc:
            db.rollback()
            print(f"Integrity verification failed: {exc}", file=sys.stderr)
            return 3

        if not args.apply:
            print("Dry run only. Re-run with --apply to materialize typed facts.")
            return 0

        try:
            all_cabinet_ids: dict[str, str] = {}
            for collection, results, cabinet_ids in verified:
                all_cabinet_ids.update(cabinet_ids)
                raw_integrity = verify_raw_directory(
                    Path(collection.raw_path),
                    source_type=collection.source_type,
                    source_root=Path(args.source_root),
                    collection_results=(collection.payload or {}).get("results"),
                    collection_row_count=collection.row_count,
                    collection_snapshot_hash=collection.snapshot_hash,
                )
                collection.payload = {
                    **(collection.payload or {}),
                    "rawIntegrity": raw_integrity.as_payload(),
                }
                _materialize_ozon_typed_collection(
                    db,
                    refresh_run,
                    collection,
                    results,
                    ozon_cabinet_ids=cabinet_ids,
                )
                parity = ((collection.payload or {}).get("typedParity") or {}).get(
                    "status"
                )
                if parity != "pending_diagnostics":
                    raise ValueError(
                        f"typed parity mismatch for {collection.source_type}"
                    )
            daily_count = repository.replace_marketplace_finance_daily_facts(
                db,
                refresh_run,
                _ozon_daily_facts_for_run(db, refresh_run),
                marketplace="ozon",
                cabinet_ids=all_cabinet_ids,
            )
            for collection, _results, _cabinet_ids in verified:
                collection.payload = {
                    **(collection.payload or {}),
                    "operationFacts": {
                        **((collection.payload or {}).get("operationFacts") or {}),
                        "dailyRowCount": daily_count,
                        "promotionScope": "all_ozon_sources",
                    },
                }
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Typed materialization rolled back: {exc}", file=sys.stderr)
            return 4

        for collection, _results, _cabinet_ids in verified:
            print(
                f"source={collection.source_type} "
                f"typedParity={collection.payload['typedParity']['status']} "
                f"facts={collection.payload['operationFacts']['rowCount']}"
            )
    return 0


def _promotion_preflight_error(
    refresh_run: SourceRefreshRun,
    collections: list[SourceRefreshCollection],
) -> str:
    if refresh_run.dry_run:
        return "dry_run_is_not_promotable"
    if refresh_run.finished_at is None:
        return "refresh_run_is_not_finished"
    if refresh_run.status not in repository.CALCULABLE_OZON_REFRESH_STATUSES:
        return f"refresh_run_status_{refresh_run.status}_is_not_promotable"
    invalid_sources = sorted(
        item.source_type
        for item in collections
        if item.status not in MANDATORY_OK_STATUSES
    )
    if invalid_sources:
        return "source_collection_not_promotable:" + ",".join(invalid_sources)
    return ""


def _verified_results(
    collection: SourceRefreshCollection,
    *,
    source_root: Path,
) -> tuple[list[OzonPageResult], dict[str, str]]:
    payload = collection.payload or {}
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise RawIntegrityError("collection results are missing")
    verify_raw_directory(
        Path(collection.raw_path),
        source_type=collection.source_type,
        source_root=source_root,
        collection_results=raw_results,
        collection_row_count=collection.row_count,
        collection_snapshot_hash=collection.snapshot_hash,
    )
    results: list[OzonPageResult] = []
    cabinet_ids: dict[str, str] = {}
    raw_dir = Path(collection.raw_path)
    for item in raw_results:
        if not isinstance(item, dict):
            raise RawIntegrityError("collection result is invalid")
        seller = str(item.get("sellerAccountId") or "")
        cabinet = str(item.get("wbCabinetId") or "")
        if seller:
            cabinet_ids[seller] = cabinet
        output_name = str(item.get("outputFile") or "")
        source_endpoint = str(item.get("sourceEndpoint") or "")
        source_type = str(item.get("sourceType") or "") or _result_source_type(
            collection.source_type,
            source_endpoint=source_endpoint,
        )
        results.append(
            OzonPageResult(
                source_type=source_type,
                seller_account_id=seller,
                account_name=str(item.get("accountName") or ""),
                page_index=int(item.get("pageIndex") or 0),
                ok=bool(item.get("ok")),
                status=str(item.get("sourceStatus") or item.get("status") or ""),
                row_count=int(item.get("rowCount") or 0),
                raw_payload_hash=str(item.get("rawPayloadHash") or ""),
                raw_content_sha256=str(item.get("rawContentSha256") or ""),
                output_path=(raw_dir / output_name) if output_name else None,
                status_code=(
                    int(item["statusCode"])
                    if item.get("statusCode") is not None
                    else None
                ),
                error=str(item.get("error") or ""),
                report_code=str(item.get("reportCode") or ""),
                report_status=str(item.get("reportStatus") or ""),
                page_limit_exhausted=bool(item.get("pageLimitExhausted")),
                source_endpoint=source_endpoint,
            )
        )
    return results, cabinet_ids


def _result_source_type(base: str, *, source_endpoint: str) -> str:
    if source_endpoint == "/v1/report/info":
        return f"{base}_info"
    if source_endpoint == "report_file":
        return f"{base}_file"
    return base


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify immutable Ozon files and atomically rebuild typed/current facts."
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", default="/data/shumeyko/source_refresh")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
