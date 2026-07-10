from __future__ import annotations

import csv
import hashlib
import re
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from wb_unit_economics.contracts import MappingStatus, OzonSkuMapping, SkuMapping
from wb_unit_economics.web import security
from wb_unit_economics.web.models import (
    Marketplace1cCurrentMapping,
    Marketplace1cMappingCandidate,
    Marketplace1cMappingDecision,
    MarketplaceMappingItem,
    OnecMappingItem,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
    User,
)

MARKETPLACE_SOURCE_TYPES = {"wb_product_cards", "ozon_products_report"}
ONEC_SOURCE_TYPES = {"onec_nomenclature", "onec_barcodes"}
MAPPING_REVIEW_STATUSES = {"missing", "ambiguous", "needs_review"}
ACTIVE_CANDIDATE_STATUSES = {"active", "manual"}


class MappingServiceError(ValueError):
    status_code = 400


class MappingNotFoundError(MappingServiceError):
    status_code = 404


class MappingConflictError(MappingServiceError):
    status_code = 409


class MappingValidationError(MappingServiceError):
    status_code = 422


def rebuild_candidates(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    user: User | None = None,
    refresh_run_id: str | None = None,
) -> dict[str, Any]:
    refresh_run = _source_refresh_run(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        refresh_run_id=refresh_run_id,
    )
    if refresh_run is None:
        return {
            "status": "missing_sources",
            "message": "source refresh snapshot is missing",
            "sources": {},
            "items": 0,
            "onecItems": 0,
            "candidates": 0,
        }

    db.execute(
        delete(Marketplace1cMappingCandidate).where(
            Marketplace1cMappingCandidate.tenant_id == tenant_id,
            Marketplace1cMappingCandidate.client_id == client_id,
            Marketplace1cMappingCandidate.source == "auto",
        )
    )
    db.flush()

    onec_items = _upsert_onec_items(db, refresh_run)
    marketplace_items = _upsert_marketplace_items(db, refresh_run)
    archived_count = _archive_stale_marketplace_items(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        active_items=marketplace_items,
    )
    candidate_items = _candidate_build_marketplace_items(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
    )
    candidate_count = _build_auto_candidates(db, candidate_items, onec_items)
    _refresh_item_statuses(db, tenant_id=tenant_id, client_id=client_id)
    _add_decision(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        item_id="",
        action="rebuild_candidates",
        user=user,
        payload={
            "refreshRunId": refresh_run.id,
            "marketplaceItems": len(marketplace_items),
            "candidateMarketplaceItems": len(candidate_items),
            "onecItems": len(onec_items),
            "candidates": candidate_count,
            "archivedItems": archived_count,
        },
    )
    return {
        "status": "rebuilt",
        "refreshRunId": refresh_run.id,
        "sources": _source_counts(db, refresh_run),
        "items": len(marketplace_items),
        "candidateItems": len(candidate_items),
        "onecItems": len(onec_items),
        "candidates": candidate_count,
        "archivedItems": archived_count,
    }


def list_mapping_items(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    marketplace: str = "",
    status: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    conditions = [
        MarketplaceMappingItem.tenant_id == tenant_id,
        MarketplaceMappingItem.client_id == client_id,
    ]
    if marketplace:
        conditions.append(MarketplaceMappingItem.marketplace == marketplace)
    if status == "review":
        conditions.append(MarketplaceMappingItem.status.in_(MAPPING_REVIEW_STATUSES))
    elif status:
        conditions.append(MarketplaceMappingItem.status == status)
    else:
        conditions.append(MarketplaceMappingItem.status != "archived")
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                MarketplaceMappingItem.title.ilike(pattern),
                MarketplaceMappingItem.vendor_code.ilike(pattern),
                MarketplaceMappingItem.barcode.ilike(pattern),
                MarketplaceMappingItem.nm_id.ilike(pattern),
                MarketplaceMappingItem.product_id.ilike(pattern),
                MarketplaceMappingItem.offer_id.ilike(pattern),
            )
        )
    total = db.scalar(
        select(func.count()).select_from(MarketplaceMappingItem).where(*conditions)
    )
    rows = list(
        db.scalars(
            select(MarketplaceMappingItem)
            .where(*conditions)
            .order_by(
                MarketplaceMappingItem.status,
                MarketplaceMappingItem.marketplace,
                MarketplaceMappingItem.title,
                MarketplaceMappingItem.id,
            )
            .limit(max(1, min(int(limit), 500)))
            .offset(max(0, int(offset)))
        )
    )
    current_by_item = _current_by_item(db, [item.id for item in rows])
    onec_by_id = _onec_by_id(
        db,
        [
            item.onec_mapping_item_id
            for item in current_by_item.values()
            if item.onec_mapping_item_id
        ],
    )
    return {
        "items": [
            _marketplace_item_payload(
                item,
                current=current_by_item.get(item.id),
                onec=onec_by_id.get(
                    current_by_item[item.id].onec_mapping_item_id
                    if item.id in current_by_item
                    else ""
                ),
            )
            for item in rows
        ],
        "total": int(total or 0),
        "limit": max(1, min(int(limit), 500)),
        "offset": max(0, int(offset)),
    }


def mapping_candidates_payload(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
) -> dict[str, Any]:
    item = _require_item(db, tenant_id=tenant_id, client_id=client_id, item_id=item_id)
    candidates = list(
        db.scalars(
            select(Marketplace1cMappingCandidate)
            .where(
                Marketplace1cMappingCandidate.item_id == item.id,
                Marketplace1cMappingCandidate.status.in_(
                    ["active", "manual", "rejected"]
                ),
            )
            .order_by(
                Marketplace1cMappingCandidate.status,
                Marketplace1cMappingCandidate.confidence.desc(),
                Marketplace1cMappingCandidate.method,
                Marketplace1cMappingCandidate.id,
            )
        )
    )
    onec_by_id = _onec_by_id(
        db, [candidate.onec_mapping_item_id for candidate in candidates]
    )
    current = db.scalar(
        select(Marketplace1cCurrentMapping).where(
            Marketplace1cCurrentMapping.item_id == item.id,
            Marketplace1cCurrentMapping.revoked_at.is_(None),
        )
    )
    current_onec = (
        _onec_by_id(db, [current.onec_mapping_item_id]).get(
            current.onec_mapping_item_id
        )
        if current and current.onec_mapping_item_id
        else None
    )
    return {
        "item": _marketplace_item_payload(item, current=current, onec=current_onec),
        "candidates": [
            _candidate_payload(
                candidate, onec_by_id.get(candidate.onec_mapping_item_id)
            )
            for candidate in _dedupe_candidates_for_payload(candidates, onec_by_id)
        ],
    }


def search_onec_items(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    query: str,
    limit: int = 20,
) -> dict[str, Any]:
    query = query.strip()
    conditions = [
        OnecMappingItem.tenant_id == tenant_id,
        OnecMappingItem.client_id == client_id,
    ]
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(
                OnecMappingItem.onec_item_id.ilike(pattern),
                OnecMappingItem.onec_article.ilike(pattern),
                OnecMappingItem.name.ilike(pattern),
                OnecMappingItem.barcode.ilike(pattern),
            )
        )
    rows = list(
        db.scalars(
            select(OnecMappingItem)
            .where(*conditions)
            .order_by(
                OnecMappingItem.name, OnecMappingItem.onec_article, OnecMappingItem.id
            )
            .limit(max(1, min(int(limit), 100)))
        )
    )
    return {"items": [_onec_payload(item) for item in rows]}


def accept_mapping(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
    user: User,
    candidate_id: str = "",
    onec_mapping_item_id: str = "",
    reason: str = "",
) -> dict[str, Any]:
    item = _require_item(db, tenant_id=tenant_id, client_id=client_id, item_id=item_id)
    current = _active_current(db, item.id)
    if current is not None:
        raise MappingConflictError("already_mapped")
    candidate = None
    if candidate_id:
        candidate = _require_candidate(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            item_id=item.id,
            candidate_id=candidate_id,
        )
        if candidate.status not in ACTIVE_CANDIDATE_STATUSES:
            raise MappingConflictError("candidate_is_not_active")
        onec_mapping_item_id = candidate.onec_mapping_item_id
        method = candidate.method
        confidence = candidate.confidence
    else:
        method = "manual_search"
        confidence = Decimal("1")
    onec = _require_onec(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        onec_mapping_item_id=onec_mapping_item_id,
    )
    now = security.utcnow()
    mapping = Marketplace1cCurrentMapping(
        id=_new_id("mp1c_current"),
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        candidate_id=candidate.id if candidate else None,
        onec_mapping_item_id=onec.id,
        status=MappingStatus.MATCHED.value,
        match_method=method,
        confidence=confidence,
        comment=reason.strip()[:2000],
        updated_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(mapping)
    item.status = MappingStatus.MATCHED.value
    item.updated_at = now
    db.flush()
    decision = _add_decision(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        action="accept",
        user=user,
        candidate_id=candidate.id if candidate else None,
        onec_mapping_item_id=onec.id,
        new_mapping_id=mapping.id,
        reason=reason,
    )
    return {
        "item": _marketplace_item_payload(item, current=mapping, onec=onec),
        "decision": _decision_payload(decision),
    }


def reject_candidate(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
    user: User,
    candidate_id: str,
    reason: str = "",
) -> dict[str, Any]:
    item = _require_item(db, tenant_id=tenant_id, client_id=client_id, item_id=item_id)
    candidate = _require_candidate(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        candidate_id=candidate_id,
    )
    candidate.status = "rejected"
    candidate.rejected_reason = reason.strip()[:2000]
    candidate.updated_at = security.utcnow()
    _refresh_one_item_status(db, item)
    decision = _add_decision(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        action="reject",
        user=user,
        candidate_id=candidate.id,
        onec_mapping_item_id=candidate.onec_mapping_item_id,
        reason=reason,
    )
    return {
        "item": _marketplace_item_payload(item),
        "decision": _decision_payload(decision),
    }


def revoke_mapping(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
    user: User,
    reason: str,
) -> dict[str, Any]:
    if not reason.strip():
        raise MappingValidationError("reason_required")
    item = _require_item(db, tenant_id=tenant_id, client_id=client_id, item_id=item_id)
    current = _active_current(db, item.id)
    if current is None:
        raise MappingNotFoundError("current_mapping_not_found")
    previous_mapping_id = current.id
    onec_mapping_item_id = current.onec_mapping_item_id
    db.delete(current)
    _refresh_one_item_status(db, item)
    decision = _add_decision(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        action="revoke",
        user=user,
        previous_mapping_id=previous_mapping_id,
        onec_mapping_item_id=onec_mapping_item_id,
        reason=reason,
    )
    return {
        "item": _marketplace_item_payload(item),
        "decision": _decision_payload(decision),
    }


def exclude_item(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
    user: User,
    reason: str,
) -> dict[str, Any]:
    if not reason.strip():
        raise MappingValidationError("reason_required")
    item = _require_item(db, tenant_id=tenant_id, client_id=client_id, item_id=item_id)
    if _active_current(db, item.id) is not None:
        raise MappingConflictError("already_mapped")
    now = security.utcnow()
    mapping = Marketplace1cCurrentMapping(
        id=_new_id("mp1c_current"),
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        candidate_id=None,
        onec_mapping_item_id=None,
        status=MappingStatus.EXCLUDED.value,
        match_method="manual_exclude",
        confidence=Decimal("1"),
        comment=reason.strip()[:2000],
        updated_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(mapping)
    item.status = MappingStatus.EXCLUDED.value
    item.updated_at = now
    db.flush()
    decision = _add_decision(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item.id,
        action="exclude",
        user=user,
        new_mapping_id=mapping.id,
        reason=reason,
    )
    return {
        "item": _marketplace_item_payload(item, current=mapping),
        "decision": _decision_payload(decision),
    }


def mapping_history_payload(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
) -> dict[str, Any]:
    item = _require_item(db, tenant_id=tenant_id, client_id=client_id, item_id=item_id)
    decisions = list(
        db.scalars(
            select(Marketplace1cMappingDecision)
            .where(Marketplace1cMappingDecision.item_id == item.id)
            .order_by(
                Marketplace1cMappingDecision.created_at.desc(),
                Marketplace1cMappingDecision.id.desc(),
            )
        )
    )
    return {
        "item": _marketplace_item_payload(item),
        "items": [_decision_payload(item) for item in decisions],
    }


def export_sku_mapping(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(MarketplaceMappingItem)
            .where(
                MarketplaceMappingItem.tenant_id == tenant_id,
                MarketplaceMappingItem.client_id == client_id,
                MarketplaceMappingItem.status != "archived",
            )
            .order_by(MarketplaceMappingItem.marketplace, MarketplaceMappingItem.id)
        )
    )
    current_by_item = _current_by_item(db, [item.id for item in items])
    onec_by_id = _onec_by_id(
        db,
        [
            current.onec_mapping_item_id
            for current in current_by_item.values()
            if current.onec_mapping_item_id
        ],
    )
    wb_rows: list[dict[str, Any]] = []
    ozon_rows: list[dict[str, Any]] = []
    updated_at = security.utcnow()
    for item in items:
        current = current_by_item.get(item.id)
        onec = (
            onec_by_id.get(current.onec_mapping_item_id)
            if current and current.onec_mapping_item_id
            else None
        )
        status = _export_status(item, current)
        common = {
            "client_id": client_id,
            "seller_account_id": item.seller_account_id,
            "organization_id": item.organization_id,
            "barcode": item.barcode,
            "onec_item_id": onec.onec_item_id if onec else "",
            "onec_article": onec.onec_article if onec else "",
            "onec_characteristic": onec.onec_characteristic if onec else "",
            "match_method": current.match_method if current else "",
            "confidence": current.confidence if current else Decimal("0"),
            "status": status,
            "comment": _export_comment(item, current),
            "updated_by": "mapping_service",
            "updated_at": updated_at,
        }
        if item.marketplace == "wb":
            wb_rows.append(
                SkuMapping(
                    **common,
                    nm_id=_int_or_none(item.nm_id),
                    vendor_code=item.vendor_code,
                ).model_dump(mode="json")
            )
        elif item.marketplace == "ozon":
            ozon_rows.append(
                OzonSkuMapping(
                    **common,
                    product_id=item.product_id,
                    ozon_sku=item.ozon_sku,
                    offer_id=item.offer_id,
                ).model_dump(mode="json")
            )
    return {
        "status": "exported",
        "clientId": client_id,
        "skuMappingRows": wb_rows,
        "ozonMappingRows": ozon_rows,
        "summary": {
            "wbRows": len(wb_rows),
            "ozonRows": len(ozon_rows),
            "matched": sum(
                1 for row in [*wb_rows, *ozon_rows] if row["status"] == "matched"
            ),
            "missing": sum(
                1 for row in [*wb_rows, *ozon_rows] if row["status"] == "missing"
            ),
            "ambiguous": sum(
                1 for row in [*wb_rows, *ozon_rows] if row["status"] == "ambiguous"
            ),
            "excluded": sum(
                1 for row in [*wb_rows, *ozon_rows] if row["status"] == "excluded"
            ),
        },
    }


def inspect_mapping_service(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    stale_after_days: int,
) -> tuple[str, str, int, str, dict[str, Any]]:
    items = list(
        db.scalars(
            select(MarketplaceMappingItem).where(
                MarketplaceMappingItem.tenant_id == tenant_id,
                MarketplaceMappingItem.client_id == client_id,
                MarketplaceMappingItem.status != "archived",
            )
        )
    )
    if not items:
        return (
            "needs_review",
            "",
            0,
            "mapping_service_empty",
            {"itemCount": 0, "staleAfterDays": stale_after_days},
        )
    newest = max(_aware_datetime(item.updated_at) for item in items)
    age_days = max(0, (security.utcnow() - newest).days)
    current_count = int(
        db.scalar(
            select(func.count())
            .select_from(Marketplace1cCurrentMapping)
            .where(
                Marketplace1cCurrentMapping.tenant_id == tenant_id,
                Marketplace1cCurrentMapping.client_id == client_id,
                Marketplace1cCurrentMapping.revoked_at.is_(None),
            )
        )
        or 0
    )
    review_count = sum(1 for item in items if item.status in MAPPING_REVIEW_STATUSES)
    payload = {
        "itemCount": len(items),
        "currentMappingCount": current_count,
        "reviewCount": review_count,
        "newestUpdatedAt": newest.isoformat(),
        "ageDays": age_days,
        "staleAfterDays": stale_after_days,
    }
    status = "stale" if age_days > stale_after_days else "loaded"
    if review_count:
        status = "needs_review" if status == "loaded" else status
    digest = hashlib.sha256(
        "|".join(
            f"{item.id}:{item.status}:{item.updated_at.isoformat()}" for item in items
        ).encode("utf-8")
    ).hexdigest()
    return status, digest, len(items), "", payload


def import_mapping_file(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    path: Path,
    user: User | None,
) -> dict[str, Any]:
    rows = _read_mapping_upload_rows(path)
    imported = 0
    accepted = 0
    already_mapped = 0
    conflicts = 0
    skipped = 0
    for row in rows:
        item = _find_marketplace_item_for_upload(db, tenant_id, client_id, row)
        onec = _find_onec_item_for_upload(db, tenant_id, client_id, row)
        if item is None or onec is None:
            skipped += 1
            continue
        candidate = _upsert_candidate(
            db,
            item,
            onec,
            method="imported_mapping_file",
            confidence=Decimal("0.8"),
            source="imported",
            evidence={"fileName": path.name},
        )
        imported += 1
        status, _mapping = _apply_imported_current_mapping(
            db,
            item=item,
            onec=onec,
            candidate=candidate,
            user=user,
            comment=f"сопоставлено из файла {path.name}",
        )
        if status == "accepted":
            accepted += 1
        elif status == "already_mapped":
            already_mapped += 1
        elif status == "conflict":
            conflicts += 1
    if imported or accepted or already_mapped or conflicts:
        _refresh_item_statuses(db, tenant_id=tenant_id, client_id=client_id)
        _add_decision(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            item_id="",
            action="import_mapping_file",
            user=user,
            payload={
                "fileName": path.name,
                "imported": imported,
                "accepted": accepted,
                "alreadyMapped": already_mapped,
                "conflicts": conflicts,
                "skipped": skipped,
            },
        )
    return {
        "status": "parsed",
        "imported": imported,
        "accepted": accepted,
        "alreadyMapped": already_mapped,
        "conflicts": conflicts,
        "skipped": skipped,
    }


def import_mapping_directory(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    mapping_dir: Path,
    user: User | None,
) -> dict[str, Any]:
    if not mapping_dir.exists():
        return {
            "status": "missing",
            "files": 0,
            "imported": 0,
            "accepted": 0,
            "alreadyMapped": 0,
            "conflicts": 0,
            "skipped": 0,
        }
    totals = {
        "files": 0,
        "imported": 0,
        "accepted": 0,
        "alreadyMapped": 0,
        "conflicts": 0,
        "skipped": 0,
    }
    for path in sorted(item for item in mapping_dir.rglob("*") if item.is_file()):
        if path.suffix.casefold() not in {".txt", ".tsv", ".csv"}:
            continue
        result = import_mapping_file(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            path=path,
            user=user,
        )
        totals["files"] += 1
        for key in ("imported", "accepted", "alreadyMapped", "conflicts", "skipped"):
            totals[key] += int(result.get(key) or 0)
    return {"status": "parsed", **totals}


def _source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    refresh_run_id: str | None,
) -> SourceRefreshRun | None:
    if refresh_run_id:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        if (
            refresh_run is None
            or refresh_run.tenant_id != tenant_id
            or refresh_run.client_id != client_id
        ):
            raise MappingNotFoundError("source_refresh_run_not_found")
        return refresh_run
    return db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.tenant_id == tenant_id,
            SourceRefreshRun.client_id == client_id,
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )


def _upsert_onec_items(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> list[OnecMappingItem]:
    rows = _source_rows_for_types(db, refresh_run, ONEC_SOURCE_TYPES)
    nomenclature: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.source_type != "onec_nomenclature":
            continue
        payload = row.row_payload or {}
        onec_item_id = _first_text(payload, "Ref_Key", "RefKey", "id", "Code", "Код")
        if not onec_item_id:
            continue
        nomenclature[_lookup_key(onec_item_id)] = {
            "onec_item_id": onec_item_id,
            "onec_article": _first_text(payload, "Артикул", "article", "vendorCode"),
            "name": _first_text(
                payload, "Description", "Наименование", "НаименованиеПолное", "name"
            ),
            "onec_characteristic": _first_text(
                payload, "Характеристика", "characteristic"
            ),
            "source_row_id": row.source_row_id,
            "source_snapshot_hash": row.raw_payload_hash,
        }
    result: list[OnecMappingItem] = []
    for item in nomenclature.values():
        result.append(
            _upsert_onec_item(
                db,
                tenant_id=refresh_run.tenant_id,
                client_id=refresh_run.client_id,
                source_key=f"onec:{item['onec_item_id']}:",
                source_type="onec_nomenclature",
                barcode="",
                **item,
            )
        )
    for row in rows:
        if row.source_type != "onec_barcodes":
            continue
        payload = row.row_payload or {}
        barcode = _first_text(payload, "Штрихкод", "barcode", "Barcode", "Баркод")
        item_ref = _first_text(
            payload,
            "Номенклатура_Key",
            "Номенклатура",
            "Owner_Key",
            "Ref_Key",
        )
        if not barcode and not item_ref:
            continue
        base = nomenclature.get(_lookup_key(item_ref), {})
        onec_item_id = base.get("onec_item_id") or item_ref
        result.append(
            _upsert_onec_item(
                db,
                tenant_id=refresh_run.tenant_id,
                client_id=refresh_run.client_id,
                source_key=f"onec:{onec_item_id}:{barcode}",
                source_type="onec_barcodes",
                onec_item_id=onec_item_id,
                onec_article=base.get("onec_article", ""),
                onec_characteristic=base.get("onec_characteristic", ""),
                name=base.get("name", ""),
                barcode=barcode,
                source_row_id=row.source_row_id,
                source_snapshot_hash=row.raw_payload_hash,
            )
        )
    return _unique_onec_items(result)


def _upsert_marketplace_items(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> list[MarketplaceMappingItem]:
    rows = _source_rows_for_types(db, refresh_run, MARKETPLACE_SOURCE_TYPES)
    items: list[MarketplaceMappingItem] = []
    for row in rows:
        payload = row.row_payload or {}
        if row.source_type == "wb_product_cards":
            item = _upsert_marketplace_item(
                db,
                refresh_run=refresh_run,
                row=row,
                marketplace="wb",
                source_item_key=(
                    "wb:"
                    f"{_first_text(payload, 'seller_account_id', 'sellerAccountId')}:"
                    f"{_first_text(payload, 'nm_id', 'nmID', 'nmId')}:"
                    f"{_first_text(payload, 'vendor_code', 'vendorCode')}:"
                    f"{_first_text(payload, 'barcode', 'sku')}"
                ),
                seller_account_id=_first_text(
                    payload, "seller_account_id", "sellerAccountId"
                ),
                product_id="",
                nm_id=_first_text(payload, "nm_id", "nmID", "nmId"),
                ozon_sku="",
                offer_id="",
                vendor_code=_first_text(payload, "vendor_code", "vendorCode"),
                barcode=_first_text(payload, "barcode", "sku"),
                title=_first_text(payload, "title", "name", "productName"),
            )
        else:
            product_id = _first_text(
                payload,
                "product_id",
                "productId",
                "id",
                "Ozon Product ID",
                "ID товара",
                "Идентификатор товара",
            )
            ozon_sku = _first_text(
                payload, "ozon_sku", "sku", "fbo_sku", "fbs_sku", "SKU"
            )
            offer_id = _first_text(
                payload,
                "offer_id",
                "offerId",
                "Артикул",
                "Артикул продавца",
                "Артикул Seller",
            )
            barcode = _first_text(
                payload,
                "barcode",
                "barcode_value",
                "Штрихкод",
                "barcodes",
                "Штрихкод (Серийный номер / EAN)",
            )
            vendor_code = _first_text(
                payload,
                "vendor_code",
                "vendorCode",
                "offer_id",
                "offerId",
                "Артикул",
            )
            title = _first_text(
                payload,
                "name",
                "productName",
                "Наименование",
                "Название товара",
                "title",
            )
            if not any((product_id, ozon_sku, offer_id, barcode, vendor_code, title)):
                continue
            item = _upsert_marketplace_item(
                db,
                refresh_run=refresh_run,
                row=row,
                marketplace="ozon",
                source_item_key=(
                    "ozon:"
                    f"{_first_text(payload, 'seller_account_id', 'sellerAccountId')}:"
                    f"{product_id}:{ozon_sku}:{offer_id}:{barcode}"
                ),
                seller_account_id=_first_text(
                    payload, "seller_account_id", "sellerAccountId"
                ),
                product_id=product_id,
                nm_id="",
                ozon_sku=ozon_sku,
                offer_id=offer_id,
                vendor_code=vendor_code,
                barcode=barcode,
                title=title,
            )
        items.append(item)
    return items


def _source_rows_for_types(
    db: Session,
    refresh_run: SourceRefreshRun,
    source_types: set[str],
) -> list[SourceSnapshotRow]:
    collection_ids = select(SourceRefreshCollection.id).where(
        SourceRefreshCollection.refresh_run_id == refresh_run.id,
        SourceRefreshCollection.source_type.in_(source_types),
    )
    return list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.collection_id.in_(collection_ids),
            )
        )
    )


def _archive_stale_marketplace_items(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    active_items: list[MarketplaceMappingItem],
) -> int:
    active_ids = {item.id for item in active_items}
    marketplaces = {item.marketplace for item in active_items}
    if not marketplaces:
        return 0
    conditions = [
        MarketplaceMappingItem.tenant_id == tenant_id,
        MarketplaceMappingItem.client_id == client_id,
        MarketplaceMappingItem.marketplace.in_(marketplaces),
        MarketplaceMappingItem.status != "archived",
    ]
    if active_ids:
        conditions.append(MarketplaceMappingItem.id.not_in(active_ids))
    current_item_ids = set(
        db.scalars(
            select(Marketplace1cCurrentMapping.item_id).where(
                Marketplace1cCurrentMapping.tenant_id == tenant_id,
                Marketplace1cCurrentMapping.client_id == client_id,
                Marketplace1cCurrentMapping.revoked_at.is_(None),
            )
        )
    )
    stale_items = [
        item
        for item in db.scalars(select(MarketplaceMappingItem).where(*conditions))
        if item.id not in current_item_ids
        and not _marketplace_item_has_business_key(item)
    ]
    now = security.utcnow()
    for item in stale_items:
        item.status = "archived"
        item.updated_at = now
    if stale_items:
        db.flush()
    return len(stale_items)


def _candidate_build_marketplace_items(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
) -> list[MarketplaceMappingItem]:
    return list(
        db.scalars(
            select(MarketplaceMappingItem).where(
                MarketplaceMappingItem.tenant_id == tenant_id,
                MarketplaceMappingItem.client_id == client_id,
                MarketplaceMappingItem.status != "archived",
            )
        )
    )


def _marketplace_item_has_business_key(item: MarketplaceMappingItem) -> bool:
    if item.marketplace == "ozon":
        return any((item.product_id, item.barcode, item.title))
    return any(
        (
            item.product_id,
            item.nm_id,
            item.ozon_sku,
            item.offer_id,
            item.vendor_code,
            item.barcode,
            item.title,
        )
    )


def _build_auto_candidates(
    db: Session,
    marketplace_items: list[MarketplaceMappingItem],
    onec_items: list[OnecMappingItem],
) -> int:
    by_barcode: dict[str, list[OnecMappingItem]] = defaultdict(list)
    by_article: dict[str, list[OnecMappingItem]] = defaultdict(list)
    by_article_normalized: dict[str, list[OnecMappingItem]] = defaultdict(list)
    for item in onec_items:
        if item.barcode:
            by_barcode[_lookup_key(item.barcode)].append(item)
        if item.onec_article:
            by_article[_lookup_key(item.onec_article)].append(item)
            by_article_normalized[_normalized_article(item.onec_article)].append(item)
    count = 0
    for item in marketplace_items:
        attempts = [
            ("barcode", item.barcode, by_barcode, Decimal("1")),
            ("vendor_article", item.vendor_code, by_article, Decimal("0.85")),
            (
                "normalized_vendor_article",
                _normalized_article(item.vendor_code),
                by_article_normalized,
                Decimal("0.7"),
            ),
        ]
        best_by_onec: dict[
            str, tuple[OnecMappingItem, str, Decimal, dict[str, Any]]
        ] = {}
        for method, raw_value, index, confidence in attempts:
            key = (
                _normalized_article(raw_value)
                if method == "normalized_vendor_article"
                else _lookup_key(raw_value)
            )
            if not key:
                continue
            matches = _dedupe_onec_matches(index.get(key, []))
            if not matches:
                continue
            final_confidence = confidence if len(matches) == 1 else Decimal("0.5")
            for onec in matches:
                evidence = {
                    "value": str(raw_value or ""),
                    "matchCount": len(matches),
                }
                onec_key = onec.onec_item_id or onec.id
                existing = best_by_onec.get(onec_key)
                if existing is None or final_confidence > existing[2]:
                    best_by_onec[onec_key] = (
                        onec,
                        method,
                        final_confidence,
                        evidence,
                    )
        for onec, method, confidence, evidence in best_by_onec.values():
            _upsert_candidate(
                db,
                item,
                onec,
                method=method,
                confidence=confidence,
                source="auto",
                evidence=evidence,
            )
            count += 1
    return count


def _upsert_onec_item(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    source_key: str,
    source_type: str,
    onec_item_id: str,
    onec_article: str,
    onec_characteristic: str = "",
    name: str = "",
    barcode: str = "",
    source_row_id: str = "",
    source_snapshot_hash: str = "",
) -> OnecMappingItem:
    now = security.utcnow()
    item = db.scalar(
        select(OnecMappingItem).where(
            OnecMappingItem.client_id == client_id,
            OnecMappingItem.source_item_key == source_key,
        )
    )
    if item is None:
        item = OnecMappingItem(
            id=_new_id("onec_mapping_item"),
            tenant_id=tenant_id,
            client_id=client_id,
            source_item_key=source_key[:300],
            created_at=now,
            updated_at=now,
        )
        db.add(item)
    item.onec_item_id = onec_item_id[:240]
    item.onec_article = onec_article[:240]
    item.onec_characteristic = onec_characteristic[:240]
    item.name = name[:500]
    item.barcode = barcode[:240]
    item.source_type = source_type[:120]
    item.source_row_id = source_row_id[:240]
    item.source_snapshot_hash = source_snapshot_hash[:160]
    item.updated_at = now
    db.flush()
    return item


def _upsert_marketplace_item(
    db: Session,
    *,
    refresh_run: SourceRefreshRun,
    row: SourceSnapshotRow,
    marketplace: str,
    source_item_key: str,
    seller_account_id: str,
    product_id: str,
    nm_id: str,
    ozon_sku: str,
    offer_id: str,
    vendor_code: str,
    barcode: str,
    title: str,
) -> MarketplaceMappingItem:
    now = security.utcnow()
    source_item_key = re.sub(r"\s+", " ", source_item_key.strip())[:500]
    item = db.scalar(
        select(MarketplaceMappingItem).where(
            MarketplaceMappingItem.client_id == refresh_run.client_id,
            MarketplaceMappingItem.marketplace == marketplace,
            MarketplaceMappingItem.source_item_key == source_item_key,
        )
    )
    if item is None:
        item = MarketplaceMappingItem(
            id=_new_id("mp_mapping_item"),
            tenant_id=refresh_run.tenant_id,
            client_id=refresh_run.client_id,
            marketplace=marketplace,
            source_item_key=source_item_key,
            status="missing",
            created_at=now,
            updated_at=now,
        )
        db.add(item)
    item.seller_account_id = seller_account_id[:240]
    item.wb_cabinet_id = row.wb_cabinet_id[:240]
    item.product_id = product_id[:240]
    item.nm_id = nm_id[:80]
    item.ozon_sku = ozon_sku[:240]
    item.offer_id = offer_id[:240]
    item.vendor_code = vendor_code[:240]
    item.barcode = barcode[:240]
    item.title = title[:500]
    item.source_type = row.source_type[:120]
    item.source_row_id = row.source_row_id[:240]
    item.source_snapshot_hash = row.raw_payload_hash[:160]
    item.updated_at = now
    db.flush()
    return item


def _upsert_candidate(
    db: Session,
    item: MarketplaceMappingItem,
    onec: OnecMappingItem,
    *,
    method: str,
    confidence: Decimal,
    source: str,
    evidence: dict[str, Any],
) -> Marketplace1cMappingCandidate:
    now = security.utcnow()
    candidate_key = f"{source}:{method}:{onec.id}"
    candidate = db.scalar(
        select(Marketplace1cMappingCandidate).where(
            Marketplace1cMappingCandidate.item_id == item.id,
            Marketplace1cMappingCandidate.candidate_key == candidate_key,
        )
    )
    if candidate is None:
        candidate = Marketplace1cMappingCandidate(
            id=_new_id("mp1c_candidate"),
            tenant_id=item.tenant_id,
            client_id=item.client_id,
            item_id=item.id,
            onec_mapping_item_id=onec.id,
            candidate_key=candidate_key[:500],
            created_at=now,
            updated_at=now,
        )
        db.add(candidate)
    candidate.method = method[:120]
    candidate.source = source[:80]
    candidate.confidence = confidence
    candidate.status = "active" if candidate.status != "rejected" else candidate.status
    candidate.evidence = evidence
    candidate.updated_at = now
    db.flush()
    return candidate


def _refresh_item_statuses(db: Session, *, tenant_id: str, client_id: str) -> None:
    for item in db.scalars(
        select(MarketplaceMappingItem).where(
            MarketplaceMappingItem.tenant_id == tenant_id,
            MarketplaceMappingItem.client_id == client_id,
            MarketplaceMappingItem.status != "archived",
        )
    ):
        _refresh_one_item_status(db, item)


def _refresh_one_item_status(db: Session, item: MarketplaceMappingItem) -> None:
    if item.status == "archived":
        return
    current = _active_current(db, item.id)
    active_onec_count = _active_candidate_onec_count(db, item.id)
    item.candidate_count = active_onec_count
    if current is not None:
        item.status = current.status
    else:
        item.status = (
            "ambiguous"
            if active_onec_count > 1
            else "needs_review"
            if active_onec_count == 1
            else "missing"
        )
    item.updated_at = security.utcnow()
    db.flush()


def _active_candidate_onec_count(db: Session, item_id: str) -> int:
    rows = db.execute(
        select(
            OnecMappingItem.onec_item_id,
            Marketplace1cMappingCandidate.onec_mapping_item_id,
        )
        .join(
            OnecMappingItem,
            OnecMappingItem.id == Marketplace1cMappingCandidate.onec_mapping_item_id,
        )
        .where(
            Marketplace1cMappingCandidate.item_id == item_id,
            Marketplace1cMappingCandidate.status.in_(list(ACTIVE_CANDIDATE_STATUSES)),
        )
    )
    return len({onec_item_id or row_id for onec_item_id, row_id in rows})


def _dedupe_candidates_for_payload(
    candidates: list[Marketplace1cMappingCandidate],
    onec_by_id: dict[str, OnecMappingItem],
) -> list[Marketplace1cMappingCandidate]:
    def rank(candidate: Marketplace1cMappingCandidate) -> tuple[int, int, Decimal]:
        status_rank = 1 if candidate.status in ACTIVE_CANDIDATE_STATUSES else 0
        source_rank = 1 if candidate.source == "imported" else 0
        return status_rank, source_rank, candidate.confidence

    best_by_onec: dict[str, Marketplace1cMappingCandidate] = {}
    for candidate in candidates:
        onec = onec_by_id.get(candidate.onec_mapping_item_id)
        key = (
            onec.onec_item_id
            if onec and onec.onec_item_id
            else candidate.onec_mapping_item_id
        )
        existing = best_by_onec.get(key)
        if existing is None or rank(candidate) > rank(existing):
            best_by_onec[key] = candidate
    return sorted(
        best_by_onec.values(),
        key=lambda item: (
            item.status,
            -float(item.confidence),
            item.method,
            item.id,
        ),
    )


def _apply_imported_current_mapping(
    db: Session,
    *,
    item: MarketplaceMappingItem,
    onec: OnecMappingItem,
    candidate: Marketplace1cMappingCandidate,
    user: User | None,
    comment: str,
) -> tuple[str, Marketplace1cCurrentMapping | None]:
    current = _active_current(db, item.id)
    if current is not None:
        if (
            current.status == MappingStatus.MATCHED.value
            and current.onec_mapping_item_id == onec.id
        ):
            return "already_mapped", current
        return "conflict", current
    now = security.utcnow()
    mapping = Marketplace1cCurrentMapping(
        id=_new_id("mp1c_current"),
        tenant_id=item.tenant_id,
        client_id=item.client_id,
        item_id=item.id,
        candidate_id=candidate.id,
        onec_mapping_item_id=onec.id,
        status=MappingStatus.MATCHED.value,
        match_method="imported_mapping_file",
        confidence=Decimal("1"),
        comment=comment[:2000],
        updated_by_user_id=user.id if user else None,
        created_at=now,
        updated_at=now,
    )
    db.add(mapping)
    item.status = MappingStatus.MATCHED.value
    item.updated_at = now
    db.flush()
    _add_decision(
        db,
        tenant_id=item.tenant_id,
        client_id=item.client_id,
        item_id=item.id,
        action="accept",
        user=user,
        candidate_id=candidate.id,
        onec_mapping_item_id=onec.id,
        new_mapping_id=mapping.id,
        reason=comment,
        payload={"source": "mapping_file_import"},
    )
    return "accepted", mapping


def _require_item(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
) -> MarketplaceMappingItem:
    item = db.get(MarketplaceMappingItem, item_id)
    if item is None or item.tenant_id != tenant_id or item.client_id != client_id:
        raise MappingNotFoundError("mapping_item_not_found")
    return item


def _require_candidate(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
    candidate_id: str,
) -> Marketplace1cMappingCandidate:
    candidate = db.get(Marketplace1cMappingCandidate, candidate_id)
    if (
        candidate is None
        or candidate.tenant_id != tenant_id
        or candidate.client_id != client_id
        or candidate.item_id != item_id
    ):
        raise MappingNotFoundError("mapping_candidate_not_found")
    return candidate


def _require_onec(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    onec_mapping_item_id: str,
) -> OnecMappingItem:
    item = db.get(OnecMappingItem, onec_mapping_item_id)
    if item is None or item.tenant_id != tenant_id or item.client_id != client_id:
        raise MappingNotFoundError("onec_mapping_item_not_found")
    return item


def _active_current(db: Session, item_id: str) -> Marketplace1cCurrentMapping | None:
    return db.scalar(
        select(Marketplace1cCurrentMapping).where(
            Marketplace1cCurrentMapping.item_id == item_id,
            Marketplace1cCurrentMapping.revoked_at.is_(None),
        )
    )


def _add_decision(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    item_id: str,
    action: str,
    user: User | None,
    candidate_id: str | None = None,
    onec_mapping_item_id: str | None = None,
    previous_mapping_id: str = "",
    new_mapping_id: str = "",
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> Marketplace1cMappingDecision:
    decision = Marketplace1cMappingDecision(
        id=_new_id("mp1c_decision"),
        tenant_id=tenant_id,
        client_id=client_id,
        item_id=item_id,
        candidate_id=candidate_id,
        onec_mapping_item_id=onec_mapping_item_id,
        previous_mapping_id=previous_mapping_id[:120],
        new_mapping_id=new_mapping_id[:120],
        action=action[:80],
        reason=reason.strip()[:2000],
        payload=payload or {},
        user_id=user.id if user else None,
        created_at=security.utcnow(),
    )
    db.add(decision)
    db.flush()
    return decision


def _source_counts(db: Session, refresh_run: SourceRefreshRun) -> dict[str, int]:
    rows = db.execute(
        select(SourceSnapshotRow.source_type, func.count())
        .where(SourceSnapshotRow.refresh_run_id == refresh_run.id)
        .group_by(SourceSnapshotRow.source_type)
    )
    return {str(source_type): int(count) for source_type, count in rows}


def _marketplace_item_payload(
    item: MarketplaceMappingItem,
    *,
    current: Marketplace1cCurrentMapping | None = None,
    onec: OnecMappingItem | None = None,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "tenantId": item.tenant_id,
        "clientId": item.client_id,
        "marketplace": item.marketplace,
        "sellerAccountId": item.seller_account_id,
        "productId": item.product_id,
        "nmId": item.nm_id,
        "ozonSku": item.ozon_sku,
        "offerId": item.offer_id,
        "vendorCode": item.vendor_code,
        "barcode": item.barcode,
        "title": item.title,
        "status": item.status,
        "candidateCount": item.candidate_count,
        "sourceType": item.source_type,
        "updatedAt": item.updated_at.isoformat(),
        "currentMapping": _current_payload(current, onec) if current else None,
    }


def _candidate_payload(
    candidate: Marketplace1cMappingCandidate,
    onec: OnecMappingItem | None,
) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "itemId": candidate.item_id,
        "method": candidate.method,
        "source": candidate.source,
        "confidence": float(candidate.confidence),
        "status": candidate.status,
        "evidence": candidate.evidence or {},
        "rejectedReason": candidate.rejected_reason,
        "onecItem": _onec_payload(onec) if onec else None,
        "createdAt": candidate.created_at.isoformat(),
        "updatedAt": candidate.updated_at.isoformat(),
    }


def _current_payload(
    current: Marketplace1cCurrentMapping,
    onec: OnecMappingItem | None,
) -> dict[str, Any]:
    return {
        "id": current.id,
        "status": current.status,
        "matchMethod": current.match_method,
        "confidence": float(current.confidence),
        "comment": current.comment,
        "updatedByUserId": current.updated_by_user_id,
        "onecItem": _onec_payload(onec) if onec else None,
        "updatedAt": current.updated_at.isoformat(),
    }


def _onec_payload(item: OnecMappingItem | None) -> dict[str, Any]:
    if item is None:
        return {}
    return {
        "id": item.id,
        "onecItemId": item.onec_item_id,
        "onecArticle": item.onec_article,
        "onecCharacteristic": item.onec_characteristic,
        "name": item.name,
        "barcode": item.barcode,
        "sourceType": item.source_type,
        "updatedAt": item.updated_at.isoformat(),
    }


def _decision_payload(item: Marketplace1cMappingDecision) -> dict[str, Any]:
    return {
        "id": item.id,
        "itemId": item.item_id,
        "candidateId": item.candidate_id,
        "onecMappingItemId": item.onec_mapping_item_id,
        "previousMappingId": item.previous_mapping_id,
        "newMappingId": item.new_mapping_id,
        "action": item.action,
        "reason": item.reason,
        "payload": item.payload or {},
        "userId": item.user_id,
        "createdAt": item.created_at.isoformat(),
    }


def _current_by_item(
    db: Session,
    item_ids: list[str],
) -> dict[str, Marketplace1cCurrentMapping]:
    if not item_ids:
        return {}
    return {
        item.item_id: item
        for item in db.scalars(
            select(Marketplace1cCurrentMapping).where(
                Marketplace1cCurrentMapping.item_id.in_(item_ids),
                Marketplace1cCurrentMapping.revoked_at.is_(None),
            )
        )
    }


def _onec_by_id(db: Session, ids: list[str | None]) -> dict[str, OnecMappingItem]:
    clean_ids = [item for item in ids if item]
    if not clean_ids:
        return {}
    return {
        item.id: item
        for item in db.scalars(
            select(OnecMappingItem).where(OnecMappingItem.id.in_(clean_ids))
        )
    }


def _export_status(
    item: MarketplaceMappingItem,
    current: Marketplace1cCurrentMapping | None,
) -> MappingStatus:
    if current and current.status == MappingStatus.MATCHED.value:
        return MappingStatus.MATCHED
    if current and current.status == MappingStatus.EXCLUDED.value:
        return MappingStatus.EXCLUDED
    if item.status == "ambiguous":
        return MappingStatus.AMBIGUOUS
    if item.status == MappingStatus.EXCLUDED.value:
        return MappingStatus.EXCLUDED
    return MappingStatus.MISSING


def _export_comment(
    item: MarketplaceMappingItem,
    current: Marketplace1cCurrentMapping | None,
) -> str:
    if current and current.comment:
        return current.comment
    if item.status == "needs_review":
        return "есть кандидат, требуется ручное подтверждение"
    if item.status == "ambiguous":
        return "несколько кандидатов, требуется ручной выбор"
    if item.status == "missing":
        return "кандидаты 1С не найдены"
    return ""


def _read_mapping_upload_rows(path: Path) -> list[dict[str, str]]:
    try:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    lines = content.splitlines()
    header = next((line for line in lines if line.strip()), "")
    header_counts = {
        delimiter: header.count(delimiter) for delimiter in ("\t", ";", ",")
    }
    delimiter = max(header_counts, key=header_counts.get)
    if header_counts[delimiter] <= 0:
        sample = content[:4096]
        delimiter = "\t" if sample.count("\t") >= sample.count(";") else ";"
        if sample.count(",") > sample.count(delimiter):
            delimiter = ","
    reader = csv.DictReader(content.splitlines(), delimiter=delimiter)
    if not reader.fieldnames:
        return []
    return [
        {str(key or ""): str(value or "") for key, value in row.items()}
        for row in reader
    ]


def _find_marketplace_item_for_upload(
    db: Session,
    tenant_id: str,
    client_id: str,
    row: dict[str, str],
) -> MarketplaceMappingItem | None:
    values = {
        "nm": _first_mapping_field(row, "nm_id", "nmId", "nmID", "НМ", "Артикул WB"),
        "product": _first_mapping_field(
            row,
            "product_id",
            "productId",
            "ozon_product_id",
            "Ozon product id",
            "Ozon Product ID",
            "ID товара",
        ),
        "offer": _first_mapping_field(
            row,
            "offer_id",
            "offerId",
            "Артикул Ozon",
            "Артикул продавца",
            "Артикул Seller",
        ),
        "vendor": _first_mapping_field(
            row,
            "vendor_code",
            "vendorCode",
            "Артикул",
            "Артикул поставщика",
        ),
        "sku": _first_mapping_field(row, "sku", "SKU", "ozon_sku", "Ozon SKU"),
        "barcode": _first_mapping_field(
            row,
            "barcode",
            "barcodes",
            "Штрихкод",
            "Баркод",
            "Штрихкод (Серийный номер / EAN)",
        ),
        "name": _first_mapping_field(
            row,
            "ozon_name",
            "product_name",
            "productName",
            "Номенклатура Ozon",
            "НоменклатураOzon",
            "Название товара",
            "Товар WB",
        ),
    }
    conditions = [
        MarketplaceMappingItem.tenant_id == tenant_id,
        MarketplaceMappingItem.client_id == client_id,
    ]
    variants = []
    if values["nm"]:
        variants.append(MarketplaceMappingItem.nm_id == values["nm"])
    if values["product"]:
        variants.append(MarketplaceMappingItem.product_id == values["product"])
    if values["offer"]:
        variants.append(MarketplaceMappingItem.offer_id == values["offer"])
    if values["sku"]:
        variants.append(MarketplaceMappingItem.ozon_sku == values["sku"])
    if values["barcode"]:
        variants.append(MarketplaceMappingItem.barcode == values["barcode"])
    if values["vendor"]:
        variants.append(MarketplaceMappingItem.vendor_code == values["vendor"])
    if values["name"]:
        variants.append(MarketplaceMappingItem.title == values["name"])
    if not variants:
        return None
    return db.scalar(select(MarketplaceMappingItem).where(*conditions, or_(*variants)))


def _find_onec_item_for_upload(
    db: Session,
    tenant_id: str,
    client_id: str,
    row: dict[str, str],
) -> OnecMappingItem | None:
    values = {
        "id": _first_mapping_field(
            row,
            "onec_item_id",
            "onecItemId",
            "1C id",
            "Ref_Key",
            "Номенклатура_Key",
        ),
        "code": _first_mapping_field(row, "onec_code", "onecCode", "Код", "Code"),
        "article": _first_mapping_field(
            row,
            "onec_article",
            "onecArticle",
            "Артикул 1С",
            "Артикул1С",
            "Артикул",
        ),
        "name": _first_mapping_field(
            row,
            "onec_name",
            "onecName",
            "Номенклатура",
            "Номенклатура 1C",
            "Номенклатура 1С",
            "Наименование 1С",
        ),
        "barcode": _first_mapping_field(row, "onec_barcode", "Штрихкод 1С"),
    }
    conditions = [
        OnecMappingItem.tenant_id == tenant_id,
        OnecMappingItem.client_id == client_id,
    ]
    variants = []
    if values["id"]:
        variants.append(OnecMappingItem.onec_item_id == values["id"])
    if values["code"]:
        variants.append(OnecMappingItem.onec_item_id == values["code"])
    if values["article"]:
        variants.append(OnecMappingItem.onec_article == values["article"])
    if values["barcode"]:
        variants.append(OnecMappingItem.barcode == values["barcode"])
    if values["name"]:
        variants.append(OnecMappingItem.name == values["name"])
    if not variants:
        return None
    return db.scalar(select(OnecMappingItem).where(*conditions, or_(*variants)))


def _first_mapping_field(row: dict[str, str], *keys: str) -> str:
    normalized = {_name_key(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_name_key(key), "")
        if value.strip():
            return value.strip()
    return ""


def _unique_onec_items(items: list[OnecMappingItem]) -> list[OnecMappingItem]:
    result = []
    seen = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def _dedupe_onec_matches(items: list[OnecMappingItem]) -> list[OnecMappingItem]:
    result = []
    seen = set()
    for item in items:
        key = item.onec_item_id or item.id
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            value = next((item for item in value if item), "")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _lookup_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().casefold())


def _name_key(value: Any) -> str:
    return re.sub(r"[\s_:-]+", "", str(value or "").strip().casefold())


def _normalized_article(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-я]+", "", str(value or "").strip().casefold())


def _int_or_none(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(Decimal(text))
    except Exception:
        return None


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=security.UTC)
    return value


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
