"""Read-only WB buyer-return claims connector and safe exact linker.

The provider payload can contain buyer comments, claim IDs, device metadata and
media. Those values are retained only in the protected raw snapshot. The flat
projection contains the exact Finance join keys and two booleans; it never
contains the comment text or another claim identifier.

An empty or inaccessible claims scope is a source state, not a report blocker.
When later snapshots contain compatible rows, the exact same-name
``claims.srid -> Finance.srid`` link activates automatically inside the full
tenant/client/cabinet/nm scope.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from wb_unit_economics.wb_finance import raw_payload_hash
from wb_unit_economics.wb_goods_return import RETURN_REASON_METHODOLOGY_VERSION

RETURN_CLAIMS_ENDPOINT = "https://returns-api.wildberries.ru/api/v1/claims"
RETURN_CLAIMS_PAGE_LIMIT = 200
RETURN_CLAIMS_MAX_PAGES = 100
RETURN_CLAIMS_WINDOW_DAYS = 14
RETURN_CLAIMS_REQUEST_INTERVAL_SECONDS = 3.1

ClaimsSliceState = Literal[
    "confirmed_empty",
    "confirmed_nonempty",
    "access_denied",
    "paid_scope_required",
    "unavailable",
    "schema_mismatch",
    "pagination_mismatch",
]
ClaimsSourceState = Literal[
    "confirmed_empty",
    "confirmed_nonempty",
    "access_denied",
    "paid_scope_required",
    "unavailable",
    "schema_mismatch",
    "pagination_mismatch",
    "partial",
]
ClaimCoverageStatus = Literal[
    "ready",
    "unmatched_finance",
    "conflicting_finance",
    "invalid_source_identity",
]

__all__ = [
    "RETURN_CLAIMS_ENDPOINT",
    "RETURN_CLAIMS_MAX_PAGES",
    "RETURN_CLAIMS_PAGE_LIMIT",
    "RETURN_CLAIMS_REQUEST_INTERVAL_SECONDS",
    "RETURN_CLAIMS_WINDOW_DAYS",
    "ClaimLinkResult",
    "ClaimLinkRow",
    "ClaimSourceRow",
    "ClaimsPaginationError",
    "ClaimsSchemaError",
    "WbReturnClaimsClient",
    "WbReturnClaimsExportResult",
    "build_return_claim_links",
    "claims_source_state_message",
    "export_wb_return_claims",
    "flatten_return_claims",
    "normalize_claim_source_row",
]


class ClaimsSchemaError(ValueError):
    """The provider response does not match the accepted read-only envelope."""


class ClaimsPaginationError(ValueError):
    """The complete provider-total pagination could not be reconciled."""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _required_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


@dataclass
class WbReturnClaimsClient:
    """GET-only client with complete active/archive provider-total pagination."""

    api_key: str
    timeout_seconds: float = 30.0
    page_limit: int = RETURN_CLAIMS_PAGE_LIMIT
    max_pages: int = RETURN_CLAIMS_MAX_PAGES
    request_interval_seconds: float = RETURN_CLAIMS_REQUEST_INTERVAL_SECONDS
    _transport: httpx.BaseTransport | None = None
    _sleep: Callable[[float], None] = time.sleep
    _monotonic: Callable[[], float] = time.monotonic
    _last_request_at: float | None = field(default=None, init=False, repr=False)

    def _pace(self) -> None:
        if self._last_request_at is not None:
            remaining = self.request_interval_seconds - (
                self._monotonic() - self._last_request_at
            )
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._monotonic()

    def fetch_claims(self, *, is_archive: bool) -> dict[str, Any]:
        """Fetch one complete source slice or fail closed without partial rows."""

        if not 1 <= self.page_limit <= RETURN_CLAIMS_PAGE_LIMIT:
            raise ValueError("claims page_limit must be between 1 and 200")
        if self.max_pages < 1:
            raise ValueError("claims max_pages must be positive")

        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        offset = 0
        with httpx.Client(
            headers={"Authorization": self.api_key, "Accept": "application/json"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            for _page_index in range(self.max_pages):
                self._pace()
                response = client.get(
                    RETURN_CLAIMS_ENDPOINT,
                    params={
                        "is_archive": is_archive,
                        "limit": self.page_limit,
                        "offset": offset,
                    },
                )
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise ClaimsSchemaError("claims response is not JSON") from exc
                page, total = _validated_claims_page(payload)
                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise ClaimsPaginationError("claims provider total changed")
                if not page:
                    if len(collected) != expected_total:
                        raise ClaimsPaginationError(
                            "claims pagination ended before provider total"
                        )
                    return {"claims": collected, "total": expected_total}
                for row in page:
                    claim_id = _required_text(row.get("id"))
                    if not claim_id:
                        raise ClaimsSchemaError("claims row is missing id")
                    if claim_id in seen_ids:
                        raise ClaimsPaginationError("duplicate claim id")
                    seen_ids.add(claim_id)
                    collected.append(row)
                if len(collected) > expected_total:
                    raise ClaimsPaginationError("claims rows exceed provider total")
                if len(collected) == expected_total:
                    return {"claims": collected, "total": expected_total}
                offset += len(page)
        raise ClaimsPaginationError("claims pagination exceeded bounded page cap")


def _validated_claims_page(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, Mapping):
        raise ClaimsSchemaError("claims response must be an object")
    claims = payload.get("claims")
    total = payload.get("total")
    if (
        not isinstance(claims, list)
        or isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or any(not isinstance(row, dict) for row in claims)
    ):
        raise ClaimsSchemaError("unexpected claims envelope")
    return claims, total


def flatten_return_claims(
    payload: Mapping[str, Any],
    *,
    is_archive: bool,
) -> list[dict[str, Any]]:
    """Return the PII-free projection used by DB/file selectors and linkers."""

    claims = payload.get("claims")
    if not isinstance(claims, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in claims:
        if not isinstance(item, Mapping):
            continue
        comment = item.get("user_comment")
        rows.append(
            {
                "srid": item.get("srid"),
                "nm_id": item.get("nm_id"),
                "is_archive": is_archive,
                "has_user_comment": isinstance(comment, str) and bool(comment.strip()),
            }
        )
    return rows


def _http_source_state(status_code: int | None) -> ClaimsSliceState:
    if status_code in {401, 403}:
        return "access_denied"
    if status_code == 402:
        return "paid_scope_required"
    return "unavailable"


def _combined_source_state(
    active: ClaimsSliceState,
    archive: ClaimsSliceState,
) -> ClaimsSourceState:
    if active == archive:
        return active
    successful = {"confirmed_empty", "confirmed_nonempty"}
    if active in successful and archive in successful:
        return (
            "confirmed_nonempty"
            if "confirmed_nonempty" in {active, archive}
            else "confirmed_empty"
        )
    return "partial"


def claims_source_state_message(state: str) -> str:
    """Stable reader-facing marker without provider values or counts."""

    if state == "confirmed_empty":
        return "Заявок за доступное окно нет"
    if state in {"access_denied", "paid_scope_required"}:
        return "Источник заявок недоступен"
    if state == "confirmed_nonempty":
        return "Заявки за доступное окно получены"
    return "Данные заявок временно недоступны"


@dataclass(frozen=True)
class WbReturnClaimsExportResult:
    ok: bool
    source_state: ClaimsSourceState
    active_state: ClaimsSliceState
    archive_state: ClaimsSliceState
    seller_account_id: str = ""
    account_name: str = ""
    row_count: int = 0
    raw_output_path: Path | None = None
    flat_output_path: Path | None = None
    raw_payload_hash: str = ""
    flat_payload_hash: str = ""
    coverage_start: date | None = None
    coverage_end: date | None = None
    status_code: int | None = None
    error: str = ""


def _fetch_claim_slice(
    client: WbReturnClaimsClient,
    *,
    is_archive: bool,
) -> tuple[ClaimsSliceState, dict[str, Any] | None, int | None, str]:
    try:
        payload = client.fetch_claims(is_archive=is_archive)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return (
            _http_source_state(status_code),
            None,
            status_code,
            exc.__class__.__name__,
        )
    except ClaimsSchemaError as exc:
        return "schema_mismatch", None, None, exc.__class__.__name__
    except ClaimsPaginationError as exc:
        return "pagination_mismatch", None, None, exc.__class__.__name__
    except httpx.HTTPError as exc:
        return "unavailable", None, None, exc.__class__.__name__
    claims = payload["claims"]
    return (
        "confirmed_nonempty" if claims else "confirmed_empty",
        payload,
        200,
        "",
    )


def export_wb_return_claims(
    client: WbReturnClaimsClient,
    output_dir: Path,
    *,
    as_of: date,
    seller_account_id: str = "",
    account_name: str = "",
    file_prefix: str = "",
) -> WbReturnClaimsExportResult:
    """Collect active+archive raw and a strictly safe flat projection."""

    active_state, active, active_code, active_error = _fetch_claim_slice(
        client, is_archive=False
    )
    if active_state in {
        "access_denied",
        "paid_scope_required",
        "unavailable",
    }:
        archive_state, archive, archive_code, archive_error = (
            active_state,
            None,
            active_code,
            active_error,
        )
    else:
        archive_state, archive, archive_code, archive_error = _fetch_claim_slice(
            client, is_archive=True
        )
    source_state = _combined_source_state(active_state, archive_state)
    coverage_start = as_of - timedelta(days=RETURN_CLAIMS_WINDOW_DAYS - 1)
    complete = active is not None and archive is not None
    status_code = next(
        (code for code in (active_code, archive_code) if code not in {None, 200}),
        200 if complete else None,
    )
    error = active_error or archive_error
    if not complete:
        return WbReturnClaimsExportResult(
            ok=False,
            source_state=source_state,
            active_state=active_state,
            archive_state=archive_state,
            seller_account_id=seller_account_id,
            account_name=account_name,
            coverage_start=coverage_start,
            coverage_end=as_of,
            status_code=status_code,
            error=error,
        )

    active_ids = {
        _required_text(row.get("id"))
        for row in active["claims"]
        if isinstance(row, Mapping)
    }
    archive_ids = {
        _required_text(row.get("id"))
        for row in archive["claims"]
        if isinstance(row, Mapping)
    }
    if active_ids.intersection(archive_ids):
        return WbReturnClaimsExportResult(
            ok=False,
            source_state="pagination_mismatch",
            active_state=active_state,
            archive_state=archive_state,
            seller_account_id=seller_account_id,
            account_name=account_name,
            coverage_start=coverage_start,
            coverage_end=as_of,
            status_code=200,
            error="ClaimsPaginationError",
        )

    raw_payload = {"active": active, "archive": archive}
    flat_rows = [
        *flatten_return_claims(active, is_archive=False),
        *flatten_return_claims(archive, is_archive=True),
    ]
    stamp = as_of.isoformat()
    prefix = f"{file_prefix}_" if file_prefix else ""
    raw_path = output_dir / f"{prefix}wb_return_claims_{stamp}.raw.json"
    flat_path = output_dir / f"{prefix}wb_return_claims_{stamp}.flat.json"
    _write_json(raw_path, raw_payload)
    _write_json(flat_path, flat_rows)
    return WbReturnClaimsExportResult(
        ok=True,
        source_state=source_state,
        active_state=active_state,
        archive_state=archive_state,
        seller_account_id=seller_account_id,
        account_name=account_name,
        row_count=len(flat_rows),
        raw_output_path=raw_path,
        flat_output_path=flat_path,
        raw_payload_hash=raw_payload_hash(raw_payload),
        flat_payload_hash=raw_payload_hash(flat_rows),
        coverage_start=coverage_start,
        coverage_end=as_of,
        status_code=200,
    )


@dataclass(frozen=True)
class ClaimSourceRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    srid: str
    nm_id: str
    is_archive: bool
    has_user_comment: bool
    source_hash: str
    validation_errors: tuple[str, ...] = ()

    @property
    def identity_key(self) -> tuple[str, str, str, str, str] | None:
        if self.validation_errors:
            return None
        return (
            self.tenant_id,
            self.client_id,
            self.wb_cabinet_id,
            self.nm_id,
            self.srid,
        )


@dataclass(frozen=True)
class ClaimLinkRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    nm_id: str
    chain_key: str
    claim_available: bool
    has_user_comment: bool
    evidence_type: str
    coverage_status: ClaimCoverageStatus
    source_hash_digest: str


@dataclass(frozen=True)
class ClaimLinkResult:
    rows: tuple[ClaimLinkRow, ...]
    methodology_version: str
    input_hash: str
    source_row_count: int
    matched_chain_count: int
    source_unmatched_count: int
    finance_unmatched_count: int
    conflicting_finance_count: int
    invalid_source_count: int


def normalize_claim_source_row(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    client_id: str,
    wb_cabinet_id: str,
) -> ClaimSourceRow:
    """Normalize a safe flat row; raw comments and IDs are never accepted."""

    forbidden = {
        "id",
        "user_comment",
        "wb_comment",
        "origin_id_info",
        "photos",
        "photo",
        "videos",
        "video",
        "actions",
    }
    errors = [f"{field}_forbidden" for field in sorted(forbidden.intersection(payload))]
    normalized_tenant = _required_text(tenant_id)
    normalized_client = _required_text(client_id)
    normalized_cabinet = _required_text(wb_cabinet_id)
    srid = _required_text(payload.get("srid"))
    nm_id = _required_text(payload.get("nm_id"))
    for field_name, value in (
        ("tenant_id", normalized_tenant),
        ("client_id", normalized_client),
        ("wb_cabinet_id", normalized_cabinet),
        ("srid", srid),
        ("nm_id", nm_id),
    ):
        if not value:
            errors.append(f"{field_name}_missing")
    is_archive = payload.get("is_archive")
    has_user_comment = payload.get("has_user_comment")
    if not isinstance(is_archive, bool):
        errors.append("is_archive_invalid")
        is_archive = False
    if not isinstance(has_user_comment, bool):
        errors.append("has_user_comment_invalid")
        has_user_comment = False
    canonical = {
        "tenant_id": normalized_tenant,
        "client_id": normalized_client,
        "wb_cabinet_id": normalized_cabinet,
        "srid": srid,
        "nm_id": nm_id,
        "is_archive": is_archive,
        "has_user_comment": has_user_comment,
    }
    return ClaimSourceRow(
        tenant_id=normalized_tenant,
        client_id=normalized_client,
        wb_cabinet_id=normalized_cabinet,
        srid=srid,
        nm_id=nm_id,
        is_archive=is_archive,
        has_user_comment=has_user_comment,
        source_hash=raw_payload_hash(canonical),
        validation_errors=tuple(sorted(set(errors))),
    )


def _digest_hashes(values: Sequence[str]) -> str:
    return hashlib.sha256("\x1f".join(sorted(set(values))).encode()).hexdigest()


def _in_coverage(value: Any, start: date | None, end: date | None) -> bool:
    if not isinstance(value, date):
        return False
    if start is not None and value < start:
        return False
    return not (end is not None and value > end)


def build_return_claim_links(
    finance_rows: Sequence[Any],
    order_rows: Sequence[Any],
    source_rows: Sequence[ClaimSourceRow],
    *,
    source_coverage_start: date | None,
    source_coverage_end: date | None,
) -> ClaimLinkResult:
    """Link safe claim presence only through exact scoped same-name keys."""

    return_chains = {
        str(row.chain_key)
        for row in order_rows
        if str(getattr(row, "chain_key", "")).strip()
        and _in_coverage(
            getattr(row, "financial_date", None),
            source_coverage_start,
            source_coverage_end,
        )
        and (
            getattr(row, "return_quantity", 0) != 0
            or getattr(row, "logistics_reverse", 0) != 0
        )
    }
    finance_map: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    for row in finance_rows:
        chain_key = _required_text(getattr(row, "chain_key", ""))
        srid = _required_text(getattr(row, "finance_srid", ""))
        nm_id = _required_text(getattr(row, "nm_id", ""))
        if not chain_key or chain_key not in return_chains or not srid or not nm_id:
            continue
        key = (
            _required_text(getattr(row, "tenant_id", "")),
            _required_text(getattr(row, "client_id", "")),
            _required_text(getattr(row, "wb_cabinet_id", "")),
            nm_id,
            srid,
        )
        if all(key):
            finance_map[key].add(chain_key)

    grouped: dict[tuple[str, str, str, str, str], list[ClaimSourceRow]] = defaultdict(
        list
    )
    rows: list[ClaimLinkRow] = []
    invalid_count = 0
    for source in source_rows:
        if source.identity_key is None:
            invalid_count += 1
            rows.append(
                ClaimLinkRow(
                    tenant_id=source.tenant_id,
                    client_id=source.client_id,
                    wb_cabinet_id=source.wb_cabinet_id,
                    nm_id=source.nm_id,
                    chain_key="",
                    claim_available=False,
                    has_user_comment=False,
                    evidence_type="data_unavailable",
                    coverage_status="invalid_source_identity",
                    source_hash_digest=_digest_hashes([source.source_hash]),
                )
            )
            continue
        grouped[source.identity_key].append(source)

    matched_chains: set[str] = set()
    source_unmatched = 0
    conflicting_finance = 0
    for key, group in sorted(grouped.items()):
        chains = finance_map.get(key, set())
        first = group[0]
        digest = _digest_hashes([item.source_hash for item in group])
        if not chains:
            source_unmatched += 1
            status: ClaimCoverageStatus = "unmatched_finance"
            chain_key = ""
        elif len(chains) > 1:
            conflicting_finance += 1
            status = "conflicting_finance"
            chain_key = ""
        else:
            status = "ready"
            chain_key = next(iter(chains))
            matched_chains.add(chain_key)
        ready = status == "ready"
        rows.append(
            ClaimLinkRow(
                tenant_id=first.tenant_id,
                client_id=first.client_id,
                wb_cabinet_id=first.wb_cabinet_id,
                nm_id=first.nm_id,
                chain_key=chain_key,
                claim_available=ready,
                has_user_comment=(
                    any(item.has_user_comment for item in group) if ready else False
                ),
                evidence_type="fact" if ready else "data_unavailable",
                coverage_status=status,
                source_hash_digest=digest,
            )
        )

    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.tenant_id,
                row.client_id,
                row.wb_cabinet_id,
                row.nm_id,
                row.chain_key,
                row.coverage_status,
                row.source_hash_digest,
            ),
        )
    )
    input_hash = raw_payload_hash(
        {
            "methodologyVersion": RETURN_REASON_METHODOLOGY_VERSION,
            "sourceCoverageStart": (
                source_coverage_start.isoformat() if source_coverage_start else None
            ),
            "sourceCoverageEnd": (
                source_coverage_end.isoformat() if source_coverage_end else None
            ),
            "financeIdentityHashes": sorted(
                raw_payload_hash(
                    {
                        "scope": list(key[:4]),
                        "financeSrid": key[4],
                        "chains": sorted(chains),
                    }
                )
                for key, chains in finance_map.items()
            ),
            "rows": [
                {
                    "tenantId": row.tenant_id,
                    "clientId": row.client_id,
                    "wbCabinetId": row.wb_cabinet_id,
                    "nmId": row.nm_id,
                    "chainKey": row.chain_key,
                    "claimAvailable": row.claim_available,
                    "hasUserComment": row.has_user_comment,
                    "evidenceType": row.evidence_type,
                    "coverageStatus": row.coverage_status,
                    "sourceHashDigest": row.source_hash_digest,
                }
                for row in ordered
            ],
        }
    )
    return ClaimLinkResult(
        rows=ordered,
        methodology_version=RETURN_REASON_METHODOLOGY_VERSION,
        input_hash=input_hash,
        source_row_count=len(source_rows),
        matched_chain_count=len(matched_chains),
        source_unmatched_count=source_unmatched,
        finance_unmatched_count=len(return_chains - matched_chains),
        conflicting_finance_count=conflicting_finance,
        invalid_source_count=invalid_count,
    )
