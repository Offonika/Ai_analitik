# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from wb_unit_economics.maintenance_safety import (
    BackupVerificationError,
    verify_backup_bundle,
)
from wb_unit_economics.source_integrity import RawIntegrityError, verify_raw_directory
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import (
    ReportRun,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
)

MATERIALIZED_STATUSES = frozenset({"source_loaded", "report_created", "needs_review"})
REPORT_PUBLICATION_STATUSES = frozenset({"draft", "published"})
FILE_AUTHORITATIVE_MARKETPLACE_TYPES = frozenset(
    {
        "wb_finance_detail",
        "wb_product_cards",
        "wb_sales_report_list",
    }
)
FILE_AUTHORITATIVE_OZON_TYPES = frozenset(
    {
        "ozon_finance_cash_flow",
        "ozon_realization",
        "ozon_realization_posting",
        "ozon_mutual_settlement",
        "ozon_products_buyout",
        "ozon_b2b_sales_json",
        "ozon_products_report",
    }
)


@dataclass(frozen=True)
class RunRetentionRecord:
    id: str
    tenant_id: str
    client_id: str
    mode: str
    status: str
    snapshot_set_id: str
    created_at: datetime
    finished_at: datetime | None
    new_report_run_id: str | None
    base_source_refresh_run_id: str | None
    resumed_from_run_id: str | None


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        print("Database URL is required; no rows were deleted.", file=sys.stderr)
        return 2
    if args.apply:
        if not args.backup_verification:
            print(
                "--backup-verification is required with --apply; no rows were deleted.",
                file=sys.stderr,
            )
            return 2
        try:
            verify_backup_bundle(
                Path(args.backup_verification),
                max_age_hours=args.backup_max_age_hours,
                postgres_data_path=Path(args.postgres_data_path),
                source_data_path=Path(args.source_data_path),
            )
        except BackupVerificationError as exc:
            print(
                f"Backup preflight failed; no rows were deleted: {exc}",
                file=sys.stderr,
            )
            return 2

    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    cutoff = datetime.now(UTC) - timedelta(hours=max(0, args.grace_hours))

    try:
        with session_factory() as db:
            _set_statement_timeout(db, args.statement_timeout_ms)
            records = _run_records(db)
            if args.tenant:
                records = [item for item in records if item.tenant_id == args.tenant]
            report_ids, snapshot_set_ids, source_load_run_ids = _report_lineage(db)
            protected = select_protected_run_ids(
                records,
                report_ids=report_ids,
                report_snapshot_set_ids=snapshot_set_ids,
                source_load_run_ids=source_load_run_ids,
                cutoff=cutoff,
                daily_keep=max(0, args.daily_keep),
                full_keep=max(0, args.full_keep),
                explicit_protected=set(args.protect_run),
            )
            candidates = [
                item
                for item in records
                if item.finished_at is not None and item.id not in protected
            ]
            counts = _snapshot_row_counts(db, [item.id for item in candidates])
            file_candidates = (
                _file_authoritative_collections(
                    db,
                    records=records,
                    source_root=Path(args.source_root),
                    tenant_id=args.tenant,
                    adopt_verified=args.adopt_verified_marketplace_files,
                )
                if args.file_authoritative_marketplace
                else []
            )
            candidate_run_ids = {item.id for item in candidates}
            file_candidates = [
                item
                for item in file_candidates
                if item.refresh_run_id not in candidate_run_ids
            ]
            file_counts = _snapshot_collection_row_counts(
                db,
                [item.id for item in file_candidates],
            )
    except Exception as exc:
        print(
            "Retention preflight failed; no rows were deleted: "
            f"{exc.__class__.__name__}",
            file=sys.stderr,
        )
        return 2

    candidates = [item for item in candidates if counts.get(item.id, 0) > 0]
    if args.order == "largest":
        candidates.sort(key=lambda item: (-counts[item.id], item.created_at, item.id))
    else:
        candidates.sort(key=lambda item: (item.created_at, item.id))
    if args.max_runs > 0:
        candidates = candidates[: args.max_runs]

    total_rows = sum(counts[item.id] for item in candidates)
    file_candidates = [
        item for item in file_candidates if file_counts.get(item.id, 0) > 0
    ]
    file_total_rows = sum(file_counts[item.id] for item in file_candidates)
    print(f"Runs inspected: {len(records)}")
    print(f"Protected runs: {len(protected)}")
    print(f"Delete candidates: {len(candidates)}")
    print(f"Candidate snapshot rows: {total_rows}")
    print(f"File-authoritative collections: {len(file_candidates)}")
    print(f"File-authoritative snapshot rows: {file_total_rows}")
    for item in candidates[: max(0, args.list_limit)]:
        print(
            f"- {item.id}: mode={item.mode} status={item.status} "
            f"created={item.created_at.isoformat()} rows={counts[item.id]}"
        )
    if len(candidates) > max(0, args.list_limit):
        print(f"- ... {len(candidates) - max(0, args.list_limit)} more runs omitted")

    if not args.apply:
        print("Dry run only. Re-run with --apply to delete candidate rows.")
        return 0

    if not candidates and not file_candidates:
        print("No candidate rows to delete.")
        return 0

    deleted_total = 0
    with session_factory() as db:
        _set_statement_timeout(db, args.statement_timeout_ms)
        for item in candidates:
            deleted_for_run = 0
            batch_number = 0
            while True:
                deleted_count = _delete_snapshot_row_batch(
                    db,
                    refresh_run_id=item.id,
                    batch_size=max(100, args.batch_size),
                )
                if deleted_count == 0:
                    break
                db.commit()
                batch_number += 1
                deleted_for_run += deleted_count
                deleted_total += deleted_count
                if batch_number % max(
                    1, args.progress_every
                ) == 0 or deleted_count < max(100, args.batch_size):
                    print(
                        f"  deleted {deleted_for_run}/{counts[item.id]} rows "
                        f"for {item.id}"
                    )
                if args.sleep_ms > 0:
                    time.sleep(args.sleep_ms / 1000)
            print(f"- completed {item.id}: deleted={deleted_for_run}")

        for collection in file_candidates:
            current_collection = db.get(SourceRefreshCollection, collection.id)
            if current_collection is None or not _verify_collection_files(
                current_collection,
                source_root=Path(args.source_root),
            ):
                print(
                    f"- skipped collection {collection.id}: "
                    "file verification changed before delete"
                )
                continue
            row_persistence = (current_collection.payload or {}).get(
                "rowPersistence"
            ) or {}
            if row_persistence.get("status") != "file_authoritative":
                if not args.adopt_verified_marketplace_files:
                    print(
                        f"- skipped collection {collection.id}: "
                        "file_authoritative marker is missing"
                    )
                    continue
                current_collection.payload = {
                    **(current_collection.payload or {}),
                    "rowPersistence": {
                        "status": "file_authoritative",
                        "rawFilesAuthoritative": True,
                        "verifiedAt": datetime.now(UTC).isoformat(),
                    },
                }
                db.commit()
            deleted_for_collection = 0
            while True:
                deleted_count = _delete_snapshot_collection_row_batch(
                    db,
                    collection_id=collection.id,
                    batch_size=max(100, args.batch_size),
                )
                if deleted_count == 0:
                    break
                db.commit()
                deleted_for_collection += deleted_count
                deleted_total += deleted_count
                if args.sleep_ms > 0:
                    time.sleep(args.sleep_ms / 1000)
            print(
                f"- completed collection {collection.id}: "
                f"source={collection.source_type} deleted={deleted_for_collection}"
            )

    print(f"Deleted snapshot rows: {deleted_total}")
    print("Run VACUUM (ANALYZE) separately after the maintenance window.")
    return 0


def _run_records(db: Session) -> list[RunRetentionRecord]:
    runs = list(
        db.scalars(
            select(SourceRefreshRun).order_by(SourceRefreshRun.created_at.desc())
        )
    )
    return [
        RunRetentionRecord(
            id=item.id,
            tenant_id=item.tenant_id,
            client_id=item.client_id,
            mode=item.mode,
            status=item.status,
            snapshot_set_id=item.snapshot_set_id,
            created_at=_aware(item.created_at),
            finished_at=_aware(item.finished_at) if item.finished_at else None,
            new_report_run_id=item.new_report_run_id,
            base_source_refresh_run_id=item.base_source_refresh_run_id,
            resumed_from_run_id=item.resumed_from_run_id,
        )
        for item in runs
    ]


def _report_lineage(db: Session) -> tuple[set[str], set[str], set[str]]:
    report_rows = db.execute(
        select(ReportRun.id, ReportRun.source_snapshot_set_id).where(
            ReportRun.publication_status.in_(REPORT_PUBLICATION_STATUSES)
        )
    ).all()
    report_ids = {str(item.id) for item in report_rows}
    snapshot_set_ids = {
        str(item.source_snapshot_set_id)
        for item in report_rows
        if item.source_snapshot_set_id
    }
    source_load_run_ids = {
        str(value)
        for value in db.scalars(
            select(SourceLoad.source_refresh_run_id).where(
                SourceLoad.report_run_id.in_(report_ids),
                SourceLoad.source_refresh_run_id.is_not(None),
            )
        )
        if value
    }
    return report_ids, snapshot_set_ids, source_load_run_ids


def select_protected_run_ids(
    records: list[RunRetentionRecord],
    *,
    report_ids: set[str],
    report_snapshot_set_ids: set[str],
    source_load_run_ids: set[str],
    cutoff: datetime,
    daily_keep: int,
    full_keep: int,
    explicit_protected: set[str],
) -> set[str]:
    protected = {value for value in explicit_protected if value}
    ordered = sorted(records, key=lambda item: (item.created_at, item.id), reverse=True)

    for item in ordered:
        if item.finished_at is None or item.created_at >= cutoff:
            protected.add(item.id)
        if item.id in source_load_run_ids:
            protected.add(item.id)
        if item.snapshot_set_id and item.snapshot_set_id in report_snapshot_set_ids:
            protected.add(item.id)
        if item.new_report_run_id and item.new_report_run_id in report_ids:
            protected.add(item.id)

    kept: dict[tuple[str, str, str], int] = {}
    newest_full_clients: set[tuple[str, str]] = set()
    for item in ordered:
        if item.finished_at is None or item.status not in MATERIALIZED_STATUSES:
            continue
        client_key = (item.tenant_id, item.client_id)
        if item.mode == "full" and client_key not in newest_full_clients:
            newest_full_clients.add(client_key)
            protected.add(item.id)
        limit = (
            daily_keep
            if item.mode == "daily"
            else full_keep
            if item.mode == "full"
            else 0
        )
        key = (item.tenant_id, item.client_id, item.mode)
        if limit > 0 and kept.get(key, 0) < limit:
            kept[key] = kept.get(key, 0) + 1
            protected.add(item.id)

    by_id = {item.id: item for item in records}
    pending = list(protected)
    while pending:
        item = by_id.get(pending.pop())
        if item is None:
            continue
        for dependency in (
            item.base_source_refresh_run_id,
            item.resumed_from_run_id,
        ):
            if dependency and dependency not in protected:
                protected.add(dependency)
                pending.append(dependency)
    return protected


def _snapshot_row_counts(db: Session, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    return {
        str(run_id): int(row_count)
        for run_id, row_count in db.execute(
            select(SourceSnapshotRow.refresh_run_id, func.count())
            .where(SourceSnapshotRow.refresh_run_id.in_(run_ids))
            .group_by(SourceSnapshotRow.refresh_run_id)
        )
    }


def _snapshot_collection_row_counts(
    db: Session,
    collection_ids: list[int],
) -> dict[int, int]:
    if not collection_ids:
        return {}
    return {
        int(collection_id): int(row_count)
        for collection_id, row_count in db.execute(
            select(SourceSnapshotRow.collection_id, func.count())
            .where(SourceSnapshotRow.collection_id.in_(collection_ids))
            .group_by(SourceSnapshotRow.collection_id)
        )
    }


def _file_authoritative_collections(
    db: Session,
    *,
    records: list[RunRetentionRecord],
    source_root: Path,
    tenant_id: str,
    adopt_verified: bool,
) -> list[SourceRefreshCollection]:
    finished_run_ids = {item.id for item in records if item.finished_at is not None}
    if not finished_run_ids:
        return []
    statement = select(SourceRefreshCollection).where(
        SourceRefreshCollection.refresh_run_id.in_(finished_run_ids)
    )
    if tenant_id:
        statement = statement.where(SourceRefreshCollection.tenant_id == tenant_id)
    collections = list(db.scalars(statement))
    verified: list[SourceRefreshCollection] = []
    for collection in collections:
        if not _is_marketplace_file_source(collection.source_type):
            continue
        payload = getattr(collection, "payload", None) or {}
        if collection.source_type == "wb_finance_detail":
            calculation_parity = payload.get("calculationParity") or {}
            if calculation_parity.get("status") != "matched":
                continue
        if collection.source_type in FILE_AUTHORITATIVE_OZON_TYPES:
            raw_integrity = payload.get("rawIntegrity") or {}
            typed_parity = payload.get("typedParity") or {}
            if raw_integrity.get("status") != "verified":
                continue
            if typed_parity.get("status") != "matched":
                continue
            if (typed_parity.get("diagnosticsParity") or {}).get("status") != "matched":
                continue
        row_persistence = payload.get("rowPersistence") or {}
        marked = row_persistence.get("status") == "file_authoritative"
        if not marked and not adopt_verified:
            continue
        if not _verify_collection_files(collection, source_root=source_root):
            continue
        verified.append(collection)
    return verified


def _is_marketplace_file_source(source_type: str) -> bool:
    return source_type in (
        FILE_AUTHORITATIVE_MARKETPLACE_TYPES | FILE_AUTHORITATIVE_OZON_TYPES
    )


def _verify_collection_files(
    collection: SourceRefreshCollection,
    *,
    source_root: Path,
) -> bool:
    if not collection.raw_path or not collection.snapshot_hash:
        return False
    try:
        payload = collection.payload or {}
        results = payload.get("results")
        if not isinstance(results, list):
            return False
        verify_raw_directory(
            Path(collection.raw_path),
            source_type=collection.source_type,
            source_root=source_root,
            collection_results=results,
            collection_row_count=collection.row_count,
            collection_snapshot_hash=collection.snapshot_hash,
        )
    except (OSError, RawIntegrityError, TypeError, ValueError):
        return False
    return True


def _set_statement_timeout(db: Session, timeout_ms: int) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    safe_timeout = max(1_000, int(timeout_ms))
    db.execute(text(f"SET LOCAL statement_timeout = {safe_timeout}"))


def _delete_snapshot_row_batch(
    db: Session,
    *,
    refresh_run_id: str,
    batch_size: int,
) -> int:
    if db.get_bind().dialect.name == "postgresql":
        deleted = db.execute(
            text(
                "WITH doomed AS ("
                " SELECT ctid FROM wb_unit_economics.source_snapshot_rows"
                " WHERE refresh_run_id = :refresh_run_id"
                " LIMIT :batch_size"
                ")"
                " DELETE FROM wb_unit_economics.source_snapshot_rows target"
                " USING doomed"
                " WHERE target.ctid = doomed.ctid"
                " RETURNING target.id"
            ),
            {"refresh_run_id": refresh_run_id, "batch_size": batch_size},
        )
        return len(deleted.scalars().all())

    row_ids = list(
        db.scalars(
            select(SourceSnapshotRow.id)
            .where(SourceSnapshotRow.refresh_run_id == refresh_run_id)
            .limit(batch_size)
        )
    )
    if not row_ids:
        return 0
    result = db.execute(
        delete(SourceSnapshotRow).where(SourceSnapshotRow.id.in_(row_ids))
    )
    return int(result.rowcount or 0)


def _delete_snapshot_collection_row_batch(
    db: Session,
    *,
    collection_id: int,
    batch_size: int,
) -> int:
    if db.get_bind().dialect.name == "postgresql":
        deleted = db.execute(
            text(
                "WITH doomed AS ("
                " SELECT ctid FROM wb_unit_economics.source_snapshot_rows"
                " WHERE collection_id = :collection_id"
                " LIMIT :batch_size"
                ")"
                " DELETE FROM wb_unit_economics.source_snapshot_rows target"
                " USING doomed"
                " WHERE target.ctid = doomed.ctid"
                " RETURNING target.id"
            ),
            {"collection_id": collection_id, "batch_size": batch_size},
        )
        return len(deleted.scalars().all())
    row_ids = list(
        db.scalars(
            select(SourceSnapshotRow.id)
            .where(SourceSnapshotRow.collection_id == collection_id)
            .limit(batch_size)
        )
    )
    if not row_ids:
        return 0
    result = db.execute(
        delete(SourceSnapshotRow).where(SourceSnapshotRow.id.in_(row_ids))
    )
    return int(result.rowcount or 0)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune unprotected source_refresh raw rows from PostgreSQL."
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument("--source-root", default="data/source_refresh")
    parser.add_argument("--tenant", default="")
    parser.add_argument("--daily-keep", type=int, default=3)
    parser.add_argument("--full-keep", type=int, default=2)
    parser.add_argument("--grace-hours", type=int, default=24)
    parser.add_argument("--protect-run", action="append", default=[])
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--list-limit", type=int, default=50)
    parser.add_argument("--order", choices=("oldest", "largest"), default="oldest")
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--sleep-ms", type=int, default=50)
    parser.add_argument("--progress-every", type=int, default=1)
    parser.add_argument("--statement-timeout-ms", type=int, default=300_000)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-verification", default="")
    parser.add_argument("--backup-max-age-hours", type=int, default=24)
    parser.add_argument("--postgres-data-path", default="/var/lib/postgresql")
    parser.add_argument("--source-data-path", default="/data")
    parser.add_argument("--file-authoritative-marketplace", action="store_true")
    parser.add_argument("--adopt-verified-marketplace-files", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
