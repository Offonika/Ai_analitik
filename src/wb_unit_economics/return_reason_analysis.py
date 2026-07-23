"""Deterministic F-5 return-reason mart built on Finance return chains.

Finance remains authoritative for the return fact and its monetary effect.
Goods-return contributes a confirmed reason only after an exact scoped link;
claims contributes only safe boolean presence. Missing or inaccessible source
coverage stays explicit and never becomes a report-level blocker.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from wb_unit_economics.logistics_analysis import (
    LogisticsOrderRow,
    LogisticsSourceRow,
)
from wb_unit_economics.wb_finance import raw_payload_hash
from wb_unit_economics.wb_goods_return import (
    RETURN_REASON_METHODOLOGY_VERSION,
    GoodsReturnLinkResult,
    GoodsReturnLinkRow,
    GoodsReturnSourceRow,
    build_goods_return_links,
)
from wb_unit_economics.wb_return_claims import (
    ClaimLinkResult,
    ClaimLinkRow,
    ClaimSourceRow,
    build_return_claim_links,
)

ReturnReasonDataStatus = Literal["ready", "partial", "blocked"]

__all__ = [
    "ReturnReasonAnalysisContext",
    "ReturnReasonAnalysisResult",
    "ReturnReasonMartRow",
    "build_return_reason_analysis",
]


@dataclass(frozen=True)
class ReturnReasonMartRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    client_company_id: str
    scheme: str
    chain_key: str
    event_date: date
    product_ref: str
    product: str
    vendor_code: str
    reason_category: str | None
    reason_source: str
    evidence_type: str
    match_status: str
    claim_available: bool | None
    has_user_comment: bool | None
    goods_return_source_hash_digest: str
    claims_source_hash_digest: str
    row_hash: str

    @property
    def row_uid(self) -> str:
        grain = "\x1f".join(
            (
                self.tenant_id,
                self.client_id,
                self.wb_cabinet_id,
                self.client_company_id,
                self.scheme,
                self.chain_key,
                self.product_ref,
            )
        )
        return hashlib.sha256(grain.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReturnReasonAnalysisContext:
    methodology_version: str
    data_status: ReturnReasonDataStatus
    input_hash: str
    goods_return_source_status: str
    claims_source_status: str
    goods_return_snapshot_hash: str
    claims_snapshot_hash: str
    goods_return_coverage_start: date | None
    goods_return_coverage_end: date | None
    claims_coverage_start: date | None
    claims_coverage_end: date | None
    finance_return_chain_count: int
    return_reason_row_count: int
    goods_return_source_row_count: int
    goods_return_matched_chain_count: int
    goods_return_reason_available_count: int
    goods_return_source_unmatched_count: int
    goods_return_finance_unmatched_count: int
    claims_source_row_count: int
    claims_matched_chain_count: int
    claims_source_unmatched_count: int
    claims_finance_unmatched_count: int
    blocking_reasons: tuple[str, ...]
    review_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReturnReasonAnalysisResult:
    context: ReturnReasonAnalysisContext
    rows: tuple[ReturnReasonMartRow, ...]


@dataclass(frozen=True)
class _ReturnChain:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    client_company_id: str
    scheme: str
    chain_key: str
    event_date: date
    product_ref: str
    product: str
    vendor_code: str


def _inside_window(
    value: date,
    start: date | None,
    end: date | None,
) -> bool:
    if start is None or end is None:
        return False
    return start <= value <= end


def _return_chains(order_rows: Sequence[LogisticsOrderRow]) -> tuple[_ReturnChain, ...]:
    grouped: dict[
        tuple[str, str, str, str, str, str, str],
        list[LogisticsOrderRow],
    ] = defaultdict(list)
    for row in order_rows:
        if not row.chain_key:
            continue
        if row.return_quantity == 0 and row.logistics_reverse == 0:
            continue
        grouped[
            (
                row.tenant_id,
                row.client_id,
                row.wb_cabinet_id,
                row.client_company_id,
                row.scheme,
                row.chain_key,
                row.product_ref,
            )
        ].append(row)

    chains: list[_ReturnChain] = []
    for key, rows in sorted(grouped.items()):
        # A chain can contain several Finance return segments. The report grain
        # is one row per chain, so the last confirmed return date is used as the
        # stable display/filter date without duplicating the return fact.
        event_date = max(row.financial_date for row in rows)
        representative = sorted(
            rows,
            key=lambda row: (
                row.financial_date,
                row.operation_date_end,
                row.source_hash_digest,
            ),
        )[-1]
        chains.append(
            _ReturnChain(
                tenant_id=key[0],
                client_id=key[1],
                wb_cabinet_id=key[2],
                client_company_id=key[3],
                scheme=key[4],
                chain_key=key[5],
                product_ref=key[6],
                event_date=event_date,
                product=representative.product,
                vendor_code=representative.vendor_code,
            )
        )
    return tuple(chains)


def _one_goods_link(
    rows: Sequence[GoodsReturnLinkRow],
) -> GoodsReturnLinkRow | None:
    linked = [row for row in rows if row.chain_key]
    if len(linked) != 1:
        return None
    return linked[0]


def _one_claim_link(rows: Sequence[ClaimLinkRow]) -> ClaimLinkRow | None:
    linked = [row for row in rows if row.chain_key and row.claim_available]
    if len(linked) != 1:
        return None
    return linked[0]


def _source_status(
    *,
    blocking_reasons: Sequence[str],
    review_reasons: Sequence[str],
    source_row_count: int,
    explicit_status: str = "",
) -> str:
    if blocking_reasons:
        return "blocked"
    if explicit_status:
        return explicit_status
    if source_row_count == 0:
        return "unavailable"
    if review_reasons:
        return "partial"
    return "ready"


def _row_hash_payload(
    *,
    chain: _ReturnChain,
    reason_category: str | None,
    reason_source: str,
    evidence_type: str,
    match_status: str,
    claim_available: bool | None,
    has_user_comment: bool | None,
    goods_digest: str,
    claims_digest: str,
) -> dict[str, object]:
    return {
        "tenantId": chain.tenant_id,
        "clientId": chain.client_id,
        "wbCabinetId": chain.wb_cabinet_id,
        "clientCompanyId": chain.client_company_id,
        "scheme": chain.scheme,
        "chainKey": chain.chain_key,
        "eventDate": chain.event_date.isoformat(),
        "productRef": chain.product_ref,
        "product": chain.product,
        "vendorCode": chain.vendor_code,
        "reasonCategory": reason_category,
        "reasonSource": reason_source,
        "evidenceType": evidence_type,
        "matchStatus": match_status,
        "claimAvailable": claim_available,
        "hasUserComment": has_user_comment,
        "goodsReturnSourceHashDigest": goods_digest,
        "claimsSourceHashDigest": claims_digest,
    }


def build_return_reason_analysis(
    finance_rows: Sequence[LogisticsSourceRow],
    order_rows: Sequence[LogisticsOrderRow],
    goods_return_rows: Sequence[GoodsReturnSourceRow],
    claim_rows: Sequence[ClaimSourceRow],
    *,
    goods_return_snapshot_hash: str = "",
    claims_snapshot_hash: str = "",
    goods_return_coverage_start: date | None = None,
    goods_return_coverage_end: date | None = None,
    claims_coverage_start: date | None = None,
    claims_coverage_end: date | None = None,
    claims_source_status: str = "unavailable",
    blocking_reasons: Sequence[str] = (),
    review_reasons: Sequence[str] = (),
    goods_return_blocking_reasons: Sequence[str] = (),
    goods_return_review_reasons: Sequence[str] = (),
    claims_blocking_reasons: Sequence[str] = (),
    claims_review_reasons: Sequence[str] = (),
) -> ReturnReasonAnalysisResult:
    """Build one safe mart row per canonical Finance return chain."""

    goods_links: GoodsReturnLinkResult = build_goods_return_links(
        finance_rows,
        order_rows,
        goods_return_rows,
        source_coverage_start=goods_return_coverage_start,
        source_coverage_end=goods_return_coverage_end,
    )
    claim_links: ClaimLinkResult = build_return_claim_links(
        finance_rows,
        order_rows,
        claim_rows,
        source_coverage_start=claims_coverage_start,
        source_coverage_end=claims_coverage_end,
    )
    all_blocking = tuple(
        dict.fromkeys(
            (
                *blocking_reasons,
                *goods_return_blocking_reasons,
                *claims_blocking_reasons,
            )
        )
    )
    all_review = tuple(
        dict.fromkeys(
            (
                *review_reasons,
                *goods_return_review_reasons,
                *claims_review_reasons,
            )
        )
    )
    goods_status = _source_status(
        blocking_reasons=goods_return_blocking_reasons,
        review_reasons=goods_return_review_reasons,
        source_row_count=len(goods_return_rows),
    )
    claims_status = _source_status(
        blocking_reasons=claims_blocking_reasons,
        review_reasons=claims_review_reasons,
        source_row_count=len(claim_rows),
        explicit_status=claims_source_status,
    )
    chains = _return_chains(order_rows)
    if all_blocking:
        rows: tuple[ReturnReasonMartRow, ...] = ()
    else:
        goods_by_chain: dict[str, list[GoodsReturnLinkRow]] = defaultdict(list)
        for row in goods_links.rows:
            if row.chain_key:
                goods_by_chain[row.chain_key].append(row)
        claims_by_chain: dict[str, list[ClaimLinkRow]] = defaultdict(list)
        for row in claim_links.rows:
            if row.chain_key:
                claims_by_chain[row.chain_key].append(row)

        built_rows: list[ReturnReasonMartRow] = []
        for chain in chains:
            goods_link = _one_goods_link(goods_by_chain.get(chain.chain_key, ()))
            goods_inside_window = _inside_window(
                chain.event_date,
                goods_return_coverage_start,
                goods_return_coverage_end,
            )
            if goods_link is not None:
                reason_category = goods_link.reason
                reason_source = (
                    "goods_return"
                    if goods_link.evidence_type == "fact"
                    else "unavailable"
                )
                evidence_type = goods_link.evidence_type
                match_status = goods_link.coverage_status
                goods_digest = goods_link.source_hash_digest
            elif not goods_inside_window:
                reason_category = None
                reason_source = "unavailable"
                evidence_type = "data_unavailable"
                match_status = "outside_source_window"
                goods_digest = ""
            elif goods_status in {"unavailable", "blocked"}:
                reason_category = None
                reason_source = "unavailable"
                evidence_type = "data_unavailable"
                match_status = "source_unavailable"
                goods_digest = ""
            else:
                reason_category = None
                reason_source = "unavailable"
                evidence_type = "data_unavailable"
                match_status = "unmatched_source"
                goods_digest = ""

            claim_link = _one_claim_link(claims_by_chain.get(chain.chain_key, ()))
            claims_inside_window = _inside_window(
                chain.event_date,
                claims_coverage_start,
                claims_coverage_end,
            )
            if claim_link is not None:
                claim_available: bool | None = True
                has_user_comment: bool | None = claim_link.has_user_comment
                claims_digest = claim_link.source_hash_digest
            elif (
                claims_inside_window
                and claims_status in {"confirmed_empty", "confirmed_nonempty"}
            ):
                claim_available = False
                has_user_comment = False
                claims_digest = ""
            else:
                claim_available = None
                has_user_comment = None
                claims_digest = ""

            row_hash = raw_payload_hash(
                _row_hash_payload(
                    chain=chain,
                    reason_category=reason_category,
                    reason_source=reason_source,
                    evidence_type=evidence_type,
                    match_status=match_status,
                    claim_available=claim_available,
                    has_user_comment=has_user_comment,
                    goods_digest=goods_digest,
                    claims_digest=claims_digest,
                )
            )
            built_rows.append(
                ReturnReasonMartRow(
                    tenant_id=chain.tenant_id,
                    client_id=chain.client_id,
                    wb_cabinet_id=chain.wb_cabinet_id,
                    client_company_id=chain.client_company_id,
                    scheme=chain.scheme,
                    chain_key=chain.chain_key,
                    event_date=chain.event_date,
                    product_ref=chain.product_ref,
                    product=chain.product,
                    vendor_code=chain.vendor_code,
                    reason_category=reason_category,
                    reason_source=reason_source,
                    evidence_type=evidence_type,
                    match_status=match_status,
                    claim_available=claim_available,
                    has_user_comment=has_user_comment,
                    goods_return_source_hash_digest=goods_digest,
                    claims_source_hash_digest=claims_digest,
                    row_hash=row_hash,
                )
            )
        rows = tuple(
            sorted(
                built_rows,
                key=lambda row: (
                    row.event_date,
                    row.wb_cabinet_id,
                    row.product_ref,
                    row.chain_key,
                ),
            )
        )

    unavailable_reason_count = sum(
        row.evidence_type != "fact" for row in rows
    )
    data_status: ReturnReasonDataStatus
    if all_blocking:
        data_status = "blocked"
    elif all_review or unavailable_reason_count:
        data_status = "partial"
    else:
        data_status = "ready"
    input_hash = raw_payload_hash(
        {
            "methodologyVersion": RETURN_REASON_METHODOLOGY_VERSION,
            "goodsReturnInputHash": goods_links.input_hash,
            "claimsInputHash": claim_links.input_hash,
            "goodsReturnSnapshotHash": goods_return_snapshot_hash,
            "claimsSnapshotHash": claims_snapshot_hash,
            "goodsReturnSourceStatus": goods_status,
            "claimsSourceStatus": claims_status,
            "blockingReasons": sorted(all_blocking),
            "reviewReasons": sorted(all_review),
            "rowHashes": [row.row_hash for row in rows],
        }
    )
    context = ReturnReasonAnalysisContext(
        methodology_version=RETURN_REASON_METHODOLOGY_VERSION,
        data_status=data_status,
        input_hash=input_hash,
        goods_return_source_status=goods_status,
        claims_source_status=claims_status,
        goods_return_snapshot_hash=goods_return_snapshot_hash,
        claims_snapshot_hash=claims_snapshot_hash,
        goods_return_coverage_start=goods_return_coverage_start,
        goods_return_coverage_end=goods_return_coverage_end,
        claims_coverage_start=claims_coverage_start,
        claims_coverage_end=claims_coverage_end,
        finance_return_chain_count=len(chains),
        return_reason_row_count=len(rows),
        goods_return_source_row_count=goods_links.source_row_count,
        goods_return_matched_chain_count=goods_links.matched_chain_count,
        goods_return_reason_available_count=goods_links.reason_available_count,
        goods_return_source_unmatched_count=goods_links.source_unmatched_count,
        goods_return_finance_unmatched_count=goods_links.finance_unmatched_count,
        claims_source_row_count=claim_links.source_row_count,
        claims_matched_chain_count=claim_links.matched_chain_count,
        claims_source_unmatched_count=claim_links.source_unmatched_count,
        claims_finance_unmatched_count=claim_links.finance_unmatched_count,
        blocking_reasons=all_blocking,
        review_reasons=all_review,
    )
    return ReturnReasonAnalysisResult(context=context, rows=rows)
