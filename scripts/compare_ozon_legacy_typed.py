#!/usr/bin/env python3
"""Compare the public Ozon diagnostics calculation on legacy and typed facts."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.source_integrity import canonical_payload_hash
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import (
    MarketplaceOperationFact,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
)
from wb_unit_economics.web.source_refresh import (
    MANDATORY_OK_STATUSES,
    OZON_TYPED_FILE_AUTHORITATIVE_TYPES,
    _iter_ozon_snapshot_row_values,
    _ozon_results_from_collection,
)

PARITY_SECTIONS = (
    "finance",
    "financeRows",
    "ozonBuyouts",
    "ozonMapping",
    "pnl",
    "ozonMart",
    "unitRows",
    "expenseReconciliation",
    "issues",
)


def _reference_mode(
    db: Any,
    collections: list[SourceRefreshCollection],
) -> tuple[str, list[SourceRefreshCollection]]:
    if not collections:
        return "unavailable", []
    file_collections: list[SourceRefreshCollection] = []
    for collection in collections:
        if collection.status not in MANDATORY_OK_STATUSES:
            return "unavailable", []
        payload = dict(collection.payload or {})
        if (payload.get("rawIntegrity") or {}).get("status") != "verified":
            return "unavailable", []
        persisted_rows = int(
            db.scalar(
                select(func.count())
                .select_from(SourceSnapshotRow)
                .where(SourceSnapshotRow.collection_id == collection.id)
            )
            or 0
        )
        if persisted_rows == collection.row_count:
            continue
        row_persistence = dict(payload.get("rowPersistence") or {})
        if (
            persisted_rows == 0
            and row_persistence.get("status") == "file_authoritative"
            and row_persistence.get("qualificationRunId")
            and _valid_file_qualification(
                db,
                collection,
                qualification_run_id=str(row_persistence["qualificationRunId"]),
            )
        ):
            file_collections.append(collection)
            continue
        return "unavailable", []
    if file_collections and len(file_collections) == len(collections):
        return "immutable_files", file_collections
    if file_collections:
        return "legacy_db_and_immutable_files", file_collections
    return "legacy_db_rows", []


def _valid_file_qualification(
    db: Any,
    collection: SourceRefreshCollection,
    *,
    qualification_run_id: str,
) -> bool:
    if qualification_run_id == collection.refresh_run_id:
        return False
    candidate = db.scalar(
        select(SourceRefreshCollection)
        .where(
            SourceRefreshCollection.refresh_run_id == qualification_run_id,
            SourceRefreshCollection.tenant_id == collection.tenant_id,
            SourceRefreshCollection.client_id == collection.client_id,
            SourceRefreshCollection.source_type == collection.source_type,
        )
        .order_by(SourceRefreshCollection.loaded_at.desc())
        .limit(1)
    )
    if (
        candidate is None
        or candidate.status not in MANDATORY_OK_STATUSES
        or candidate.refresh_run.finished_at is None
        or candidate.refresh_run.status
        not in repository.CALCULABLE_OZON_REFRESH_STATUSES
        or candidate.refresh_run.created_at >= collection.refresh_run.created_at
    ):
        return False
    payload = dict(candidate.payload or {})
    if (payload.get("rowPersistence") or {}).get("status") == "file_authoritative":
        return False
    typed_parity = dict(payload.get("typedParity") or {})
    if not (
        (payload.get("rawIntegrity") or {}).get("status") == "verified"
        and typed_parity.get("status") == "matched"
        and (typed_parity.get("diagnosticsParity") or {}).get("status")
        == "matched"
        and (typed_parity.get("persistenceParity") or {}).get("status")
        == "matched"
        and (typed_parity.get("legacyFileParity") or {}).get("status") == "matched"
        and (typed_parity.get("sourceCoverage") or {}).get("status") == "matched"
    ):
        return False
    return _seller_account_ids(payload) == _seller_account_ids(
        dict(collection.payload or {})
    )


def _seller_account_ids(payload: dict[str, Any]) -> set[str]:
    return {
        str(item.get("sellerAccountId") or "")
        for item in payload.get("results", [])
        if isinstance(item, dict) and item.get("sellerAccountId")
    }


def _insert_temporary_file_reference(
    db: Any,
    collections: list[SourceRefreshCollection],
    *,
    source_root: Path,
) -> None:
    for collection in collections:
        results, cabinet_ids = _ozon_results_from_collection(
            collection,
            source_root=source_root,
        )
        values = list(
            _iter_ozon_snapshot_row_values(
                collection,
                results,
                ozon_cabinet_ids=cabinet_ids,
            )
        )
        if len(values) != collection.row_count:
            raise ValueError("immutable file reference row count mismatch")
        for start in range(0, len(values), 1000):
            repository.add_source_snapshot_rows(
                db,
                collection,
                values[start : start + 1000],
            )


def _record_parity(
    collections: list[SourceRefreshCollection],
    *,
    artifact: dict[str, Any],
    artifact_path: Path,
) -> None:
    normalized_status = (artifact.get("normalizedRealization") or {}).get("status")
    diagnostics_status = (
        "matched"
        if artifact.get("status") == "matched" and normalized_status == "matched"
        else "mismatch"
    )
    for collection in collections:
        payload = dict(collection.payload or {})
        typed_parity = dict(payload.get("typedParity") or {})
        typed_parity["diagnosticsParity"] = {
            "status": diagnostics_status,
            "legacyDigest": artifact["legacyDigest"],
            "typedDigest": artifact["typedDigest"],
            "mismatches": artifact["mismatches"],
            "normalizedRealization": artifact.get("normalizedRealization"),
            "referenceMode": artifact.get("referenceMode"),
            "artifactPath": str(artifact_path),
        }
        checks_matched = (
            diagnostics_status == "matched"
            and collection.status in MANDATORY_OK_STATUSES
            and (payload.get("rawIntegrity") or {}).get("status") == "verified"
            and (typed_parity.get("persistenceParity") or {}).get("status")
            == "matched"
            and (typed_parity.get("legacyFileParity") or {}).get("status")
            in {"matched", "qualified_file_reference", "not_run_no_legacy_rows"}
            and (typed_parity.get("sourceCoverage") or {}).get("status") == "matched"
        )
        typed_parity["status"] = "matched" if checks_matched else "mismatch"
        if checks_matched:
            typed_parity["qualificationRunId"] = collection.refresh_run_id
        collection.payload = {**payload, "typedParity": typed_parity}


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        print("Database URL is required; parity was not run.", file=sys.stderr)
        return 2
    factory = make_session_factory(make_engine(database_url))
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, args.run_id)
        if refresh_run is None:
            print("Source refresh run was not found.", file=sys.stderr)
            return 2
        collections = list(
            db.scalars(
                select(SourceRefreshCollection).where(
                    SourceRefreshCollection.refresh_run_id == refresh_run.id,
                    SourceRefreshCollection.source_type.in_(
                        OZON_TYPED_FILE_AUTHORITATIVE_TYPES
                    ),
                )
            )
        )
        parity_limit = _parity_row_limit(
            db,
            collections,
            refresh_run_id=refresh_run.id,
            requested_limit=args.limit,
            record=args.record,
        )
        kwargs = {
            "tenant_id": refresh_run.tenant_id,
            "client_id": refresh_run.client_id,
            "limit": parity_limit,
            "preview_max_rows": parity_limit,
            "period_start": refresh_run.period_start,
            "period_end": refresh_run.period_end,
            "refresh_run_id": refresh_run.id,
        }
        reference_mode, file_reference_collections = _reference_mode(db, collections)
        normalized_realization: dict[str, Any]
        if reference_mode == "unavailable":
            legacy = {}
            normalized_realization = {"status": "reference_unavailable"}
        elif file_reference_collections:
            nested = db.begin_nested()
            try:
                _insert_temporary_file_reference(
                    db,
                    file_reference_collections,
                    source_root=Path(args.source_root),
                )
                legacy = repository.latest_ozon_diagnostics_payload(
                    db,
                    **kwargs,
                    prefer_typed=False,
                )
                normalized_realization = _normalized_realization_parity(
                    db,
                    refresh_run,
                )
            finally:
                nested.rollback()
        else:
            legacy = repository.latest_ozon_diagnostics_payload(
                db,
                **kwargs,
                prefer_typed=False,
            )
            normalized_realization = _normalized_realization_parity(
                db,
                refresh_run,
            )
        typed = repository.latest_ozon_diagnostics_payload(
            db,
            **kwargs,
            prefer_typed=True,
        )
        artifact = _parity_artifact(legacy, typed, refresh_run_id=refresh_run.id)
        artifact["referenceMode"] = reference_mode
        artifact["normalizedRealization"] = normalized_realization
        if reference_mode == "unavailable":
            artifact["status"] = "reference_unavailable"
            artifact["mismatches"] = ["reference"]
        artifact_path = Path(refresh_run.root_dir) / "parity" / "ozon-legacy-typed.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if args.record:
            if reference_mode != "unavailable":
                _record_parity(
                    collections,
                    artifact=artifact,
                    artifact_path=artifact_path,
                )
                db.commit()
            else:
                print("record_skipped=reference_unavailable")
        print(f"status={artifact['status']}")
        print(f"legacyDigest={artifact['legacyDigest']}")
        print(f"typedDigest={artifact['typedDigest']}")
        print(f"mismatches={','.join(artifact['mismatches']) or '-'}")
        print(f"artifact={artifact_path}")
        if artifact["status"] == "reference_unavailable":
            return 4
        return 0 if artifact["status"] == "matched" else 3


def _parity_row_limit(
    db: Any,
    collections: list[SourceRefreshCollection],
    *,
    refresh_run_id: str,
    requested_limit: int,
    record: bool,
) -> int:
    raw_collection_rows = sum(max(0, int(item.row_count)) for item in collections)
    if not record:
        return max(1, int(requested_limit), raw_collection_rows)
    collection_ids = [item.id for item in collections]
    legacy_rows = (
        int(
            db.scalar(
                select(func.count())
                .select_from(SourceSnapshotRow)
                .where(SourceSnapshotRow.collection_id.in_(collection_ids))
            )
            or 0
        )
        if collection_ids
        else 0
    )
    typed_rows = int(
        db.scalar(
            select(func.count())
            .select_from(MarketplaceOperationFact)
            .where(MarketplaceOperationFact.source_refresh_run_id == refresh_run_id)
        )
        or 0
    )
    return max(1, raw_collection_rows, legacy_rows, typed_rows)


def _parity_artifact(
    legacy: dict[str, Any],
    typed: dict[str, Any],
    *,
    refresh_run_id: str,
) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}
    mismatches: list[str] = []
    legacy_payload: dict[str, Any] = {}
    typed_payload: dict[str, Any] = {}
    for name in PARITY_SECTIONS:
        legacy_value = _parity_normalize(legacy.get(name))
        typed_value = _parity_normalize(typed.get(name))
        legacy_digest = canonical_payload_hash(legacy_value)
        typed_digest = canonical_payload_hash(typed_value)
        matched = legacy_digest == typed_digest
        if not matched:
            mismatches.append(name)
        sections[name] = {
            "status": "matched" if matched else "mismatch",
            "legacyDigest": legacy_digest,
            "typedDigest": typed_digest,
            "differencePaths": _difference_paths(legacy_value, typed_value),
        }
        legacy_payload[name] = legacy_value
        typed_payload[name] = typed_value
    return {
        "refreshRunId": refresh_run_id,
        "status": "matched" if not mismatches else "mismatch",
        "legacyDigest": canonical_payload_hash(legacy_payload),
        "typedDigest": canonical_payload_hash(typed_payload),
        "mismatches": mismatches,
        "sections": sections,
    }


def _parity_normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _parity_normalize(item)
            for key, item in value.items()
            if str(key) not in {"id", "rowNumber", "sourceRowId", "loadedAt"}
        }
    if isinstance(value, list):
        items = [_parity_normalize(item) for item in value]
        business_keys = {
            "offerId",
            "productId",
            "sku",
            "barcode",
            "onecItemId",
            "articleId",
            "kind",
            "documentNumber",
            "operationId",
        }
        if (
            items
            and all(isinstance(item, dict) for item in items)
            and any(business_keys.intersection(item) for item in items)
        ):
            return sorted(items, key=canonical_payload_hash)
        return items
    return value


def _difference_paths(
    legacy: Any,
    typed: Any,
    *,
    path: str = "$",
    limit: int = 100,
) -> list[str]:
    differences: list[str] = []

    def walk(left: Any, right: Any, current: str) -> None:
        if len(differences) >= limit:
            return
        if type(left) is not type(right):
            differences.append(f"{current}:type")
            return
        if isinstance(left, dict):
            keys = sorted(set(left) | set(right))
            for key in keys:
                child = f"{current}.{key}"
                if key not in left or key not in right:
                    differences.append(f"{child}:missing")
                else:
                    walk(left[key], right[key], child)
                if len(differences) >= limit:
                    return
            return
        if isinstance(left, list):
            if len(left) != len(right):
                differences.append(f"{current}:length")
            for index, (left_item, right_item) in enumerate(
                zip(left, right, strict=False)
            ):
                walk(left_item, right_item, f"{current}[{index}]")
                if len(differences) >= limit:
                    return
            return
        if left != right:
            differences.append(current)

    walk(legacy, typed, path)
    return differences


def _normalized_realization_parity(
    db: Any,
    refresh_run: SourceRefreshRun,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    kwargs = {
        "tenant_id": refresh_run.tenant_id,
        "refresh_run": refresh_run,
        "limit": None if limit is None else max(1, int(limit)),
    }
    legacy_rows = repository._ozon_realization_source_rows(
        db,
        **kwargs,
        prefer_typed=False,
    )
    typed_rows = repository._ozon_realization_source_rows(
        db,
        **kwargs,
        prefer_typed=True,
    )
    collections = list(refresh_run.collections)
    legacy_values = _normalized_realization_rows(
        legacy_rows,
        collections=collections,
        refresh_run=refresh_run,
    )
    typed_values = _normalized_realization_rows(
        typed_rows,
        collections=collections,
        refresh_run=refresh_run,
    )
    component_names = (
        "business",
        "quantity",
        "amount",
        "amountPresence",
        "period",
    )
    components = {
        name: _component_parity(legacy_values[name], typed_values[name])
        for name in component_names
    }
    legacy_digest = canonical_payload_hash(legacy_values["combined"])
    typed_digest = canonical_payload_hash(typed_values["combined"])
    return {
        "status": "matched" if legacy_digest == typed_digest else "mismatch",
        "legacyRows": len(legacy_values["combined"]),
        "typedRows": len(typed_values["combined"]),
        "legacyDigest": legacy_digest,
        "typedDigest": typed_digest,
        "components": components,
    }


def _component_parity(legacy: list[str], typed: list[str]) -> dict[str, Any]:
    legacy_digest = canonical_payload_hash(legacy)
    typed_digest = canonical_payload_hash(typed)
    return {
        "status": "matched" if legacy_digest == typed_digest else "mismatch",
        "legacyDigest": legacy_digest,
        "typedDigest": typed_digest,
        "commonRows": sum((Counter(legacy) & Counter(typed)).values()),
    }


def _normalized_realization_rows(
    rows: list[Any],
    *,
    collections: list[SourceRefreshCollection],
    refresh_run: SourceRefreshRun,
) -> dict[str, list[str]]:
    period_rows = repository._ozon_rows_matching_period(
        rows,
        collections=collections,
        source_type=repository.OZON_REALIZATION_SOURCE,
        period_start=refresh_run.period_start,
        period_end=refresh_run.period_end,
    )
    values: dict[str, list[str]] = {
        "business": [],
        "quantity": [],
        "amount": [],
        "amountPresence": [],
        "period": [],
        "combined": [],
    }
    periods = repository._ozon_source_periods(
        collections,
        repository.OZON_REALIZATION_SOURCE,
    )
    for row in period_rows:
        period = repository._ozon_row_period(
            row,
            source_type=repository.OZON_REALIZATION_SOURCE,
            periods=periods,
        )
        for item in repository._iter_ozon_realization_items(row.row_payload or {}):
            candidate = repository._ozon_mapping_candidate(row, item) or {}
            business = {
                key: value
                for key, value in candidate.items()
                if key not in {"rowNumber", "sourceRowId"}
            }
            quantity = repository._ozon_realization_quantity(item)
            amount = repository._ozon_realization_amount(item)
            quantity = quantity.quantize(Decimal("0.000001"))
            amount = (
                amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if amount is not None
                else None
            )
            period_payload = [
                value.isoformat() if value is not None else None
                for value in (period or (None, None))
            ]
            payloads = {
                "business": business,
                "quantity": quantity,
                "amount": amount,
                "amountPresence": amount is not None,
                "period": period_payload,
                "combined": {
                    "business": business,
                    "quantity": quantity,
                    "amount": amount,
                    "period": period_payload,
                },
            }
            for name, payload in payloads.items():
                values[name].append(canonical_payload_hash(payload))
    return {name: sorted(items) for name, items in values.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Ozon diagnostics calculated from legacy and typed facts."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--database-url", default="")
    parser.add_argument(
        "--limit", type=int, default=repository.OZON_PNL_MAX_SOURCE_ROWS
    )
    parser.add_argument("--source-root", default="data/source_refresh")
    parser.add_argument("--record", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
