"""Read-only WB goods-return connector (return reasons, seller side).

Отдельный read-only источник причин возврата товара продавцу
(`GET analytics/goods-return`). Он описывает возврат/перемещение товара
продавцу и содержит `reason`, но это НЕ универсальная причина каждого
финансового возврата и НЕ комментарий покупателя (`claims.user_comment`) —
источники раздельны и не сливаются (см. accepted spec
`docs/specs/wb-logistics-return-reasons-implementation.md`).

Коннектор только читает (`GET`, окно до 31 дня, лимит 1 запрос/мин) и
нормализует строки в плоский слой. Разрешённая связь с Finance — только exact
`goods-return.srid → Finance.srid` в tenant/client/cabinet/nm scope после
зарегистрированного verified snapshot и с разрешением в одну canonical return
chain; `orderId`, cross-field `srid → orderUid` или товар не являются fallback.
Пропущенные поля остаются `None` — отсутствие причины остаётся явным, а не
подменяется пустой строкой или гипотезой. Сумма и факт возврата берутся из
Finance (первая очередь), здесь не считаются.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import httpx

from wb_unit_economics.wb_finance import raw_payload_hash


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


GOODS_RETURN_ENDPOINT = (
    "https://seller-analytics-api.wildberries.ru/api/v1/analytics/goods-return"
)
MAX_WINDOW_DAYS = 31
RETURN_REASON_METHODOLOGY_VERSION = "wb-logistics-return-reasons-v1"

__all__ = [
    "GOODS_RETURN_ENDPOINT",
    "MAX_WINDOW_DAYS",
    "RETURN_REASON_METHODOLOGY_VERSION",
    "GoodsReturnLinkResult",
    "GoodsReturnLinkRow",
    "GoodsReturnSourceRow",
    "WbGoodsReturnClient",
    "WbGoodsReturnExportResult",
    "build_goods_return_links",
    "flatten_goods_return",
    "normalize_goods_return_source_row",
    "raw_payload_hash",
]


@dataclass(frozen=True)
class WbGoodsReturnClient:
    """Read-only client for WB goods-return analytics report."""

    api_key: str
    timeout_seconds: float = 30.0
    _transport: httpx.BaseTransport | None = None

    def fetch_goods_return(self, date_from: date, date_to: date) -> dict[str, Any]:
        if date_to < date_from or (date_to - date_from).days + 1 > MAX_WINDOW_DAYS:
            raise ValueError("goods-return window must not exceed 31 days")
        with httpx.Client(
            headers={"Authorization": self.api_key, "Accept": "application/json"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = client.get(
                GOODS_RETURN_ENDPOINT,
                params={
                    "dateFrom": date_from.isoformat(),
                    "dateTo": date_to.isoformat(),
                },
            )
        response.raise_for_status()
        data = response.json()
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("report"), list)
            or any(not isinstance(row, dict) for row in data["report"])
        ):
            raise ValueError("Unexpected WB goods-return payload")
        return data


def _report_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Прочитать только принятую provider envelope `report`."""
    candidate = payload.get("report")
    if not isinstance(candidate, list):
        return []
    return [row for row in candidate if isinstance(row, dict)]


def flatten_goods_return(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Плоские строки причин возврата продавцу; `None` без подстановки пустого."""
    rows: list[dict[str, Any]] = []
    for item in _report_rows(payload):
        rows.append(
            {
                "srid": item.get("srid"),
                "order_id": item.get("orderId"),
                "nm_id": item.get("nmId"),
                "barcode": item.get("barcode"),
                "reason": item.get("reason"),
                "status": item.get("status"),
                "return_type": item.get("returnType"),
            }
        )
    return rows


@dataclass(frozen=True)
class WbGoodsReturnExportResult:
    ok: bool
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


def export_wb_goods_return(
    client: WbGoodsReturnClient,
    output_dir: Path,
    *,
    date_from: date,
    date_to: date,
    seller_account_id: str = "",
    account_name: str = "",
    file_prefix: str = "",
) -> WbGoodsReturnExportResult:
    """Read-only снимок причин возврата за окно до 31 дня: raw + flat."""
    try:
        payload = client.fetch_goods_return(date_from, date_to)
    except httpx.HTTPStatusError as exc:
        return WbGoodsReturnExportResult(
            ok=False,
            seller_account_id=seller_account_id,
            account_name=account_name,
            coverage_start=date_from,
            coverage_end=date_to,
            status_code=exc.response.status_code,
            error=exc.__class__.__name__,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return WbGoodsReturnExportResult(
            ok=False,
            seller_account_id=seller_account_id,
            account_name=account_name,
            coverage_start=date_from,
            coverage_end=date_to,
            error=exc.__class__.__name__,
        )
    rows = flatten_goods_return(payload)
    stamp = f"{date_from.isoformat()}_{date_to.isoformat()}"
    prefix = f"{file_prefix}_" if file_prefix else ""
    raw_path = output_dir / f"{prefix}wb_goods_return_{stamp}.raw.json"
    flat_path = output_dir / f"{prefix}wb_goods_return_{stamp}.flat.json"
    _write_json(raw_path, payload)
    _write_json(flat_path, rows)
    return WbGoodsReturnExportResult(
        ok=True,
        seller_account_id=seller_account_id,
        account_name=account_name,
        row_count=len(rows),
        raw_output_path=raw_path,
        flat_output_path=flat_path,
        raw_payload_hash=raw_payload_hash(payload),
        flat_payload_hash=raw_payload_hash(rows),
        coverage_start=date_from,
        coverage_end=date_to,
        status_code=200,
    )


GoodsReturnCoverageStatus = Literal[
    "ready",
    "reason_unavailable",
    "unmatched_finance",
    "conflicting_source",
    "conflicting_finance",
    "invalid_source_identity",
]


@dataclass(frozen=True)
class GoodsReturnSourceRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    srid: str
    order_id: str
    nm_id: str
    barcode: str
    reason: str | None
    provider_status: str | None
    return_type: str | None
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

    @property
    def source_fact(self) -> tuple[str, str | None, str | None, str | None]:
        return (
            self.order_id,
            self.reason,
            self.provider_status,
            self.return_type,
        )


@dataclass(frozen=True)
class GoodsReturnLinkRow:
    tenant_id: str
    client_id: str
    wb_cabinet_id: str
    nm_id: str
    chain_key: str
    reason: str | None
    provider_status: str | None
    return_type: str | None
    evidence_type: str
    coverage_status: GoodsReturnCoverageStatus
    source_hash_digest: str


@dataclass(frozen=True)
class GoodsReturnLinkResult:
    rows: tuple[GoodsReturnLinkRow, ...]
    methodology_version: str
    input_hash: str
    source_row_count: int
    matched_chain_count: int
    reason_available_count: int
    source_unmatched_count: int
    finance_unmatched_count: int
    conflicting_source_count: int
    conflicting_finance_count: int
    invalid_source_count: int


def _required_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _optional_text(value: Any, field: str, errors: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{field}_invalid")
        return None
    return value.strip() or None


def normalize_goods_return_source_row(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    client_id: str,
    wb_cabinet_id: str,
) -> GoodsReturnSourceRow:
    """Normalize one registered flat row without guessing missing identity."""

    errors: list[str] = []
    normalized_tenant = _required_text(tenant_id)
    normalized_client = _required_text(client_id)
    normalized_cabinet = _required_text(wb_cabinet_id)
    srid = _required_text(payload.get("srid"))
    nm_id = _required_text(payload.get("nm_id"))
    for field, value in (
        ("tenant_id", normalized_tenant),
        ("client_id", normalized_client),
        ("wb_cabinet_id", normalized_cabinet),
        ("srid", srid),
        ("nm_id", nm_id),
    ):
        if not value:
            errors.append(f"{field}_missing")
    order_id = _required_text(payload.get("order_id"))
    barcode = _required_text(payload.get("barcode"))
    reason = _optional_text(payload.get("reason"), "reason", errors)
    provider_status = _optional_text(payload.get("status"), "provider_status", errors)
    return_type = _optional_text(payload.get("return_type"), "return_type", errors)
    canonical = {
        "tenant_id": normalized_tenant,
        "client_id": normalized_client,
        "wb_cabinet_id": normalized_cabinet,
        "srid": srid,
        "order_id": order_id,
        "nm_id": nm_id,
        "barcode": barcode,
        "reason": reason,
        "provider_status": provider_status,
        "return_type": return_type,
    }
    return GoodsReturnSourceRow(
        tenant_id=normalized_tenant,
        client_id=normalized_client,
        wb_cabinet_id=normalized_cabinet,
        srid=srid,
        order_id=order_id,
        nm_id=nm_id,
        barcode=barcode,
        reason=reason,
        provider_status=provider_status,
        return_type=return_type,
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


def build_goods_return_links(
    finance_rows: Sequence[Any],
    order_rows: Sequence[Any],
    source_rows: Sequence[GoodsReturnSourceRow],
    *,
    source_coverage_start: date | None,
    source_coverage_end: date | None,
) -> GoodsReturnLinkResult:
    """Link goods-return facts to one canonical Finance return chain."""

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
        chain_key = str(getattr(row, "chain_key", "")).strip()
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

    valid_groups: dict[tuple[str, str, str, str, str], list[GoodsReturnSourceRow]] = (
        defaultdict(list)
    )
    rows: list[GoodsReturnLinkRow] = []
    invalid_count = 0
    for source in source_rows:
        if source.identity_key is None:
            invalid_count += 1
            rows.append(
                GoodsReturnLinkRow(
                    tenant_id=source.tenant_id,
                    client_id=source.client_id,
                    wb_cabinet_id=source.wb_cabinet_id,
                    nm_id=source.nm_id,
                    chain_key="",
                    reason=None,
                    provider_status=None,
                    return_type=None,
                    evidence_type="data_unavailable",
                    coverage_status="invalid_source_identity",
                    source_hash_digest=_digest_hashes([source.source_hash]),
                )
            )
            continue
        valid_groups[source.identity_key].append(source)

    linked_candidates: dict[
        str,
        list[
            tuple[
                tuple[str, str, str, str, str],
                list[GoodsReturnSourceRow],
            ]
        ],
    ] = defaultdict(list)
    conflicting_finance = 0
    source_unmatched = 0
    for key, group in sorted(valid_groups.items()):
        chains = finance_map.get(key, set())
        source = group[0]
        facts = {item.source_fact for item in group}
        digest = _digest_hashes([item.source_hash for item in group])
        if len(facts) > 1:
            rows.append(
                GoodsReturnLinkRow(
                    tenant_id=source.tenant_id,
                    client_id=source.client_id,
                    wb_cabinet_id=source.wb_cabinet_id,
                    nm_id=source.nm_id,
                    chain_key=next(iter(chains)) if len(chains) == 1 else "",
                    reason=None,
                    provider_status=None,
                    return_type=None,
                    evidence_type="data_unavailable",
                    coverage_status="conflicting_source",
                    source_hash_digest=digest,
                )
            )
            continue
        if not chains:
            source_unmatched += 1
            rows.append(
                GoodsReturnLinkRow(
                    tenant_id=source.tenant_id,
                    client_id=source.client_id,
                    wb_cabinet_id=source.wb_cabinet_id,
                    nm_id=source.nm_id,
                    chain_key="",
                    reason=source.reason,
                    provider_status=source.provider_status,
                    return_type=source.return_type,
                    evidence_type="data_unavailable",
                    coverage_status="unmatched_finance",
                    source_hash_digest=digest,
                )
            )
            continue
        if len(chains) > 1:
            conflicting_finance += 1
            rows.append(
                GoodsReturnLinkRow(
                    tenant_id=source.tenant_id,
                    client_id=source.client_id,
                    wb_cabinet_id=source.wb_cabinet_id,
                    nm_id=source.nm_id,
                    chain_key="",
                    reason=None,
                    provider_status=None,
                    return_type=None,
                    evidence_type="data_unavailable",
                    coverage_status="conflicting_finance",
                    source_hash_digest=digest,
                )
            )
            continue
        linked_candidates[next(iter(chains))].append((key, group))

    successful_source_keys: set[tuple[str, str, str, str, str]] = set()
    for chain_key, candidates in sorted(linked_candidates.items()):
        source_rows_for_chain = [row for _key, group in candidates for row in group]
        source = source_rows_for_chain[0]
        facts = {item.source_fact for item in source_rows_for_chain}
        digest = _digest_hashes([item.source_hash for item in source_rows_for_chain])
        if len(facts) > 1:
            rows.append(
                GoodsReturnLinkRow(
                    tenant_id=source.tenant_id,
                    client_id=source.client_id,
                    wb_cabinet_id=source.wb_cabinet_id,
                    nm_id=source.nm_id,
                    chain_key=chain_key,
                    reason=None,
                    provider_status=None,
                    return_type=None,
                    evidence_type="data_unavailable",
                    coverage_status="conflicting_source",
                    source_hash_digest=digest,
                )
            )
            continue
        for key, _group in candidates:
            successful_source_keys.add(key)
        coverage_status: GoodsReturnCoverageStatus = (
            "ready" if source.reason is not None else "reason_unavailable"
        )
        rows.append(
            GoodsReturnLinkRow(
                tenant_id=source.tenant_id,
                client_id=source.client_id,
                wb_cabinet_id=source.wb_cabinet_id,
                nm_id=source.nm_id,
                chain_key=chain_key,
                reason=source.reason,
                provider_status=source.provider_status,
                return_type=source.return_type,
                evidence_type=(
                    "fact" if source.reason is not None else "data_unavailable"
                ),
                coverage_status=coverage_status,
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
    result_input_hash = raw_payload_hash(
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
                    "reason": row.reason,
                    "providerStatus": row.provider_status,
                    "returnType": row.return_type,
                    "evidenceType": row.evidence_type,
                    "coverageStatus": row.coverage_status,
                    "sourceHashDigest": row.source_hash_digest,
                }
                for row in ordered
            ],
        }
    )
    return GoodsReturnLinkResult(
        rows=ordered,
        methodology_version=RETURN_REASON_METHODOLOGY_VERSION,
        input_hash=result_input_hash,
        source_row_count=len(source_rows),
        matched_chain_count=sum(
            row.coverage_status in {"ready", "reason_unavailable"} for row in ordered
        ),
        reason_available_count=sum(row.coverage_status == "ready" for row in ordered),
        source_unmatched_count=source_unmatched,
        finance_unmatched_count=len(set(finance_map) - successful_source_keys),
        conflicting_source_count=sum(
            row.coverage_status == "conflicting_source" for row in ordered
        ),
        conflicting_finance_count=conflicting_finance,
        invalid_source_count=invalid_count,
    )
