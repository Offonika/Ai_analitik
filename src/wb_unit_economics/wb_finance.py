from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from wb_unit_economics.contracts import (
    AccountOrgMapping,
    SalesModel,
    WbApiSnapshot,
    WbSalesReportSummaryRow,
)
from wb_unit_economics.source_integrity import verify_raw_directory

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
FINANCE_DETAILED_ENDPOINT = (
    "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed"
)
FINANCE_DETAILED_BY_REPORT_ENDPOINT = FINANCE_DETAILED_ENDPOINT + "/{report_id}"
FINANCE_REPORT_LIST_ENDPOINT = (
    "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/list"
)
DEFAULT_FINANCE_FIELDS = (
    "reportId",
    "dateFrom",
    "dateTo",
    "createDate",
    "currency",
    "reportType",
    "rrdId",
    "dlvPrc",
    "fixTariffDateFrom",
    "fixTariffDateTo",
    "rrDate",
    "saleDt",
    "orderDt",
    "shkId",
    "nmId",
    "vendorCode",
    "title",
    "sku",
    "docTypeName",
    "sellerOperName",
    "quantity",
    "retailPrice",
    "retailAmount",
    "salePercent",
    "commissionPercent",
    "officeName",
    "ppvzOfficeName",
    "ppvzOfficeId",
    "country",
    "retailPriceWithDisc",
    "deliveryAmount",
    "returnAmount",
    "ppvzSalesCommission",
    "forPay",
    "ppvzReward",
    "deliveryService",
    "giBoxTypeName",
    "productDiscountForReport",
    "sellerPromo",
    "spp",
    "kvwBase",
    "kvw",
    "paidStorage",
    "paidAcceptance",
    "penalty",
    "bonusTypeName",
    "additionalPayment",
    "rebillLogisticCost",
    "deduction",
    "acquiringFee",
    "acquiringPercent",
    "paymentProcessing",
    "acquiringBank",
    "vw",
    "vwNds",
    "cashbackAmount",
    "cashbackDiscount",
    "cashbackCommissionChange",
    "paymentSchedule",
    "deliveryMethod",
    "sellerPromoId",
    "sellerPromoDiscount",
    "loyaltyId",
    "loyaltyDiscount",
    "uuidPromocode",
    "salePricePromocodeDiscountPrc",
    "articleSubstitution",
    "salePriceAffiliatedDiscountPrc",
    "agencyVat",
    "salePriceWholesaleDiscountPrc",
    "orderId",
    "stickerId",
    "trbxId",
    "orderUid",
    "srid",
)
TRANSIENT_WB_TRANSPORT_ERRORS = {
    "ConnectError",
    "ConnectTimeout",
    "NetworkError",
    "PoolTimeout",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "TimeoutException",
    "WriteError",
    "WriteTimeout",
}
WB_PAGE_RETRY_ATTEMPTS = 2
WB_PAGE_RETRY_BACKOFF_SECONDS = 5.0


@dataclass(frozen=True)
class WbFinanceSellerAccount:
    seller_account_id: str
    account_name: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class WbFinanceSettings:
    accounts: tuple[WbFinanceSellerAccount, ...]
    timeout_seconds: float = 45.0

    @classmethod
    def from_env_file(
        cls,
        env_file: Path = Path(".env"),
        *,
        max_accounts: int = 10,
    ) -> WbFinanceSettings:
        values = _load_env_values(env_file)
        values.update(os.environ)
        accounts: list[WbFinanceSellerAccount] = []
        for index in range(1, max_accounts + 1):
            api_key = values.get(f"WB_ACCOUNT_{index}_API_KEY", "").strip()
            if not api_key:
                continue
            seller_account_id = f"WB_ACCOUNT_{index}"
            account_name = values.get(f"WB_ACCOUNT_{index}_NAME", "").strip()
            accounts.append(
                WbFinanceSellerAccount(
                    seller_account_id=seller_account_id,
                    account_name=account_name or seller_account_id,
                    api_key=api_key,
                )
            )
        if not accounts:
            raise WbFinanceConfigError("No WB_ACCOUNT_*_API_KEY variables configured")

        timeout_value = values.get("WB_TIMEOUT_SECONDS", "").strip()
        return cls(
            accounts=tuple(accounts),
            timeout_seconds=float(timeout_value) if timeout_value else 45.0,
        )


@dataclass(frozen=True)
class WbFinancePageResult:
    seller_account_id: str
    account_name: str
    page_index: int
    ok: bool
    status: str
    row_count: int
    rrd_id_start: int
    rrd_id_next: int | None = None
    raw_payload_hash: str = ""
    output_path: Path | None = None
    status_code: int | None = None
    error: str = ""
    wb_report_id: str = ""


@dataclass(frozen=True)
class WbSalesReportListPageResult:
    seller_account_id: str
    account_name: str
    page_index: int
    ok: bool
    status: str
    row_count: int
    offset: int
    raw_payload_hash: str = ""
    output_path: Path | None = None
    status_code: int | None = None
    error: str = ""


class WbFinanceConfigError(ValueError):
    pass


class WbFinanceClient:
    """Read-only client for WB sales report details by period."""

    def __init__(
        self,
        account: WbFinanceSellerAccount,
        *,
        timeout_seconds: float = 45.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            headers={
                "Authorization": account.api_key,
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WbFinanceClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_sales_report_page(
        self,
        *,
        period_start: date,
        period_end: date,
        rrd_id: int,
        limit: int,
        period: str = "daily",
        fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
    ) -> tuple[list[dict[str, Any]], int]:
        payload = build_sales_report_request(
            period_start=period_start,
            period_end=period_end,
            rrd_id=rrd_id,
            limit=limit,
            period=period,
            fields=fields,
        )
        response = self._client.post(FINANCE_DETAILED_ENDPOINT, json=payload)
        if response.status_code == 204:
            return [], response.status_code
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected WB finance payload")
        return [item for item in data if isinstance(item, dict)], response.status_code

    def fetch_sales_report_by_id_page(
        self,
        *,
        report_id: str,
        rrd_id: int,
        limit: int,
        fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
    ) -> tuple[list[dict[str, Any]], int]:
        payload = build_sales_report_by_id_request(
            rrd_id=rrd_id,
            limit=limit,
            fields=fields,
        )
        response = self._client.post(
            FINANCE_DETAILED_BY_REPORT_ENDPOINT.format(report_id=report_id),
            json=payload,
        )
        if response.status_code == 204:
            return [], response.status_code
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected WB finance payload")
        return [item for item in data if isinstance(item, dict)], response.status_code

    def fetch_sales_report_list_page(
        self,
        *,
        period_start: date,
        period_end: date,
        limit: int,
        offset: int,
        period: str = "weekly",
    ) -> tuple[list[dict[str, Any]], int]:
        payload = build_sales_report_list_request(
            period_start=period_start,
            period_end=period_end,
            limit=limit,
            offset=offset,
            period=period,
        )
        response = self._client.post(FINANCE_REPORT_LIST_ENDPOINT, json=payload)
        if response.status_code == 204:
            return [], response.status_code
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected WB finance report list payload")
        return [item for item in data if isinstance(item, dict)], response.status_code


def build_sales_report_request(
    *,
    period_start: date,
    period_end: date,
    rrd_id: int,
    limit: int,
    period: str = "daily",
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> dict[str, Any]:
    if limit > 100000:
        raise ValueError("WB finance limit must be <= 100000")
    return {
        "dateFrom": period_start.isoformat(),
        "dateTo": period_end.isoformat(),
        "limit": limit,
        "rrdId": rrd_id,
        "period": period,
        "fields": list(fields),
    }


def build_sales_report_by_id_request(
    *,
    rrd_id: int,
    limit: int,
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> dict[str, Any]:
    if limit > 100000:
        raise ValueError("WB finance limit must be <= 100000")
    return {
        "limit": limit,
        "rrdId": rrd_id,
        "fields": list(fields),
    }


def build_sales_report_list_request(
    *,
    period_start: date,
    period_end: date,
    limit: int = 1000,
    offset: int = 0,
    period: str = "weekly",
) -> dict[str, Any]:
    if limit > 1000:
        raise ValueError("WB sales report list limit must be <= 1000")
    return {
        "dateFrom": period_start.isoformat(),
        "dateTo": period_end.isoformat(),
        "limit": limit,
        "offset": offset,
        "period": period,
    }


def export_wb_finance(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    limit: int = 100000,
    max_pages: int = 50,
    request_delay_seconds: float = 61.0,
    period: str = "daily",
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> list[WbFinancePageResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbFinancePageResult] = []
    for account in settings.accounts:
        with WbFinanceClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            rrd_id = 0
            for page_index in range(1, max_pages + 1):
                result = _retry_transient_page(
                    lambda account=account,
                    rrd_id=rrd_id,
                    page_index=page_index: (
                        export_wb_finance_page(
                            client,
                            account,
                            output_dir,
                            period_start=period_start,
                            period_end=period_end,
                            rrd_id=rrd_id,
                            limit=limit,
                            page_index=page_index,
                            period=period,
                            fields=fields,
                        )
                    ),
                    rate_limit_backoff_seconds=request_delay_seconds,
                )
                results.append(result)
                _write_manifest(
                    output_dir / "manifest.json",
                    results,
                    period_start=period_start,
                    period_end=period_end,
                    limit=limit,
                    max_pages=max_pages,
                    period=period,
                    request_delay_seconds=request_delay_seconds,
                    fields=fields,
                    extra={"checkpoint_status": "running"},
                )
                if not result.ok or result.status == "no_data":
                    break
                if result.rrd_id_next is None or result.rrd_id_next == rrd_id:
                    break
                rrd_id = result.rrd_id_next
                time.sleep(request_delay_seconds)
    _write_manifest(
        output_dir / "manifest.json",
        results,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        max_pages=max_pages,
        period=period,
        request_delay_seconds=request_delay_seconds,
        fields=fields,
    )
    return results


def recover_wb_finance_manifest_from_pages(
    settings: WbFinanceSettings,
    export_dir: Path,
    *,
    period_start: date,
    period_end: date,
    limit: int = 100000,
    max_pages: int = 50,
    request_delay_seconds: float = 61.0,
    period: str = "daily",
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> list[WbFinancePageResult]:
    """Recover an interrupted manifest from immutable WB page files."""

    account_by_file_prefix = {
        account.seller_account_id.casefold(): account for account in settings.accounts
    }
    grouped_paths: dict[str, list[tuple[int, Path]]] = {}
    for path in export_dir.glob("*_finance_page_*.raw.json"):
        stem = path.name.removesuffix(".raw.json")
        try:
            account_prefix, page_text = stem.rsplit("_finance_page_", 1)
            page_index = int(page_text)
        except (ValueError, TypeError):
            continue
        grouped_paths.setdefault(account_prefix.casefold(), []).append(
            (page_index, path)
        )
    if not grouped_paths:
        raise ValueError("WB finance page files were not found")

    results: list[WbFinancePageResult] = []
    for account_prefix, page_items in sorted(grouped_paths.items()):
        account = account_by_file_prefix.get(account_prefix)
        if account is None:
            raise ValueError("WB finance page account is not configured")
        previous_rrd_id = 0
        expected_page_index = 1
        for page_index, path in sorted(page_items):
            if page_index != expected_page_index:
                raise ValueError("WB finance page sequence has a gap")
            row_count = 0
            last_row: dict[str, Any] | None = None
            for row in _iter_json_list_objects(path):
                row_count += 1
                last_row = row
            next_rrd_id = (
                _int_or_none(_first(last_row or {}, "rrdId", "rrd_id"))
                if last_row is not None
                else None
            )
            results.append(
                WbFinancePageResult(
                    seller_account_id=account.seller_account_id,
                    account_name=account.account_name,
                    page_index=page_index,
                    ok=True,
                    status="ok" if row_count else "no_data",
                    row_count=row_count,
                    rrd_id_start=previous_rrd_id,
                    rrd_id_next=next_rrd_id,
                    raw_payload_hash=_file_sha256(path),
                    output_path=path,
                    status_code=200 if row_count else 204,
                )
            )
            if next_rrd_id is not None:
                previous_rrd_id = next_rrd_id
            expected_page_index += 1
    _write_manifest(
        export_dir / "manifest.json",
        results,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        max_pages=max_pages,
        period=period,
        request_delay_seconds=request_delay_seconds,
        fields=fields,
        extra={
            "checkpoint_status": "recovered_interrupted",
            "recovered_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        },
    )
    return results


def resume_wb_finance_export(
    settings: WbFinanceSettings,
    export_dir: Path,
    *,
    max_pages: int = 50,
    request_delay_seconds: float = 61.0,
    fields: Iterable[str] | None = None,
) -> list[WbFinancePageResult]:
    manifest_path = export_dir / "manifest.json"
    manifest = _read_json_object(manifest_path)
    period_start = _parse_date(manifest.get("period_start"))
    period_end = _parse_date(manifest.get("period_end"))
    if period_start is None or period_end is None:
        raise ValueError("WB finance manifest has no valid period_start/period_end")
    limit = _int_or_none(manifest.get("limit")) or 100000
    period = _text(manifest.get("period")) or "daily"
    manifest_fields = manifest.get("fields")
    resolved_fields = (
        list(fields)
        if fields is not None
        else list(manifest_fields)
        if isinstance(manifest_fields, list)
        else list(DEFAULT_FINANCE_FIELDS)
    )
    previous_results = _finance_page_results_from_manifest(manifest, export_dir)
    new_results: list[WbFinancePageResult] = []
    manifest_backed_up = False
    for account in settings.accounts:
        resume_point = _finance_resume_point(manifest, account.seller_account_id)
        if resume_point is None:
            continue
        rrd_id, page_index = resume_point
        with WbFinanceClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            for _ in range(max_pages):
                result = _retry_transient_page(
                    lambda account=account,
                    rrd_id=rrd_id,
                    page_index=page_index: (
                        export_wb_finance_page(
                            client,
                            account,
                            export_dir,
                            period_start=period_start,
                            period_end=period_end,
                            rrd_id=rrd_id,
                            limit=limit,
                            page_index=page_index,
                            period=period,
                            fields=resolved_fields,
                        )
                    ),
                    rate_limit_backoff_seconds=request_delay_seconds,
                )
                if not manifest_backed_up:
                    _backup_manifest(manifest_path)
                    manifest_backed_up = True
                new_results.append(result)
                _write_manifest(
                    manifest_path,
                    [*previous_results, *new_results],
                    period_start=period_start,
                    period_end=period_end,
                    limit=limit,
                    max_pages=max_pages,
                    period=period,
                    request_delay_seconds=request_delay_seconds,
                    fields=resolved_fields,
                    extra={
                        "checkpoint_status": "running",
                        "resume": {
                            "previous_generated_at": manifest.get("generated_at"),
                            "previous_result_count": len(previous_results),
                            "new_result_count": len(new_results),
                            "resumed_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
                        },
                    },
                )
                if not result.ok or result.status == "no_data":
                    break
                if result.rrd_id_next is None or result.rrd_id_next == rrd_id:
                    break
                rrd_id = result.rrd_id_next
                page_index += 1
                time.sleep(request_delay_seconds)
    if not new_results:
        return []
    _write_manifest(
        manifest_path,
        [*previous_results, *new_results],
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        max_pages=max_pages,
        period=period,
        request_delay_seconds=request_delay_seconds,
        fields=resolved_fields,
        extra={
            "resume": {
                "previous_generated_at": manifest.get("generated_at"),
                "previous_result_count": len(previous_results),
                "new_result_count": len(new_results),
                "resumed_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
            }
        },
    )
    return new_results


def load_wb_finance_export_results(export_dir: Path) -> list[WbFinancePageResult]:
    manifest = _read_json_object(export_dir / "manifest.json")
    return _finance_page_results_from_manifest(manifest, export_dir)


def wb_finance_export_is_complete(
    results: Iterable[WbFinancePageResult],
    settings: WbFinanceSettings,
) -> bool:
    latest_by_account: dict[str, WbFinancePageResult] = {}
    for item in results:
        previous = latest_by_account.get(item.seller_account_id)
        if previous is None or item.page_index > previous.page_index:
            latest_by_account[item.seller_account_id] = item
    return bool(settings.accounts) and all(
        latest_by_account.get(account.seller_account_id) is not None
        and latest_by_account[account.seller_account_id].status == "no_data"
        for account in settings.accounts
    )


def export_wb_finance_by_report_ids(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    report_ids: Iterable[str],
    limit: int = 100000,
    max_pages: int = 50,
    request_delay_seconds: float = 61.0,
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> list[WbFinancePageResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_report_ids = [str(report_id).strip() for report_id in report_ids]
    normalized_report_ids = [
        report_id for report_id in normalized_report_ids if report_id
    ]
    results: list[WbFinancePageResult] = []
    for account in settings.accounts:
        with WbFinanceClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            for report_index, report_id in enumerate(normalized_report_ids, start=1):
                rrd_id = 0
                for page_index in range(1, max_pages + 1):
                    result = _retry_transient_page(
                        lambda account=account,
                        report_id=report_id,
                        rrd_id=rrd_id,
                        page_index=page_index: export_wb_finance_report_id_page(
                            client,
                            account,
                            output_dir,
                            report_id=report_id,
                            rrd_id=rrd_id,
                            limit=limit,
                            page_index=page_index,
                            fields=fields,
                        ),
                        rate_limit_backoff_seconds=request_delay_seconds,
                    )
                    results.append(result)
                    if not result.ok or result.status == "no_data":
                        break
                    if result.rrd_id_next is None or result.rrd_id_next == rrd_id:
                        break
                    rrd_id = result.rrd_id_next
                    time.sleep(request_delay_seconds)
                if report_index < len(normalized_report_ids):
                    time.sleep(request_delay_seconds)
    _write_report_id_manifest(
        output_dir / "manifest.json",
        results,
        report_ids=normalized_report_ids,
        limit=limit,
        max_pages=max_pages,
        request_delay_seconds=request_delay_seconds,
        fields=fields,
    )
    return results


def export_wb_sales_report_list(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    limit: int = 1000,
    max_pages: int = 10,
    request_delay_seconds: float = 61.0,
    period: str = "weekly",
) -> list[WbSalesReportListPageResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbSalesReportListPageResult] = []
    for account in settings.accounts:
        with WbFinanceClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            offset = 0
            for page_index in range(1, max_pages + 1):
                result = _retry_transient_page(
                    lambda account=account,
                    offset=offset,
                    page_index=page_index: (
                        export_wb_sales_report_list_page(
                            client,
                            account,
                            output_dir,
                            period_start=period_start,
                            period_end=period_end,
                            limit=limit,
                            offset=offset,
                            page_index=page_index,
                            period=period,
                        )
                    ),
                    rate_limit_backoff_seconds=request_delay_seconds,
                )
                results.append(result)
                if not result.ok or result.status == "no_data":
                    break
                if result.row_count < limit:
                    break
                offset += result.row_count
                time.sleep(request_delay_seconds)
    _write_sales_report_list_manifest(
        output_dir / "manifest.json",
        results,
        period_start=period_start,
        period_end=period_end,
        limit=limit,
        max_pages=max_pages,
        period=period,
        request_delay_seconds=request_delay_seconds,
    )
    return results


def _retry_transient_page(
    fetch_page,
    *,
    rate_limit_backoff_seconds: float | None = None,
):
    result = fetch_page()
    for attempt in range(WB_PAGE_RETRY_ATTEMPTS):
        if not _is_retryable_page_result(result):
            return result
        time.sleep(
            _page_retry_backoff_seconds(
                result,
                attempt=attempt,
                rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            )
        )
        result = fetch_page()
    return result


def _is_retryable_page_result(
    result: WbFinancePageResult | WbSalesReportListPageResult,
) -> bool:
    return result.status == "rate_limited" or _is_transient_transport_result(result)


def _page_retry_backoff_seconds(
    result: WbFinancePageResult | WbSalesReportListPageResult,
    *,
    attempt: int,
    rate_limit_backoff_seconds: float | None,
) -> float:
    if result.status == "rate_limited" and rate_limit_backoff_seconds is not None:
        return max(0.0, float(rate_limit_backoff_seconds))
    return WB_PAGE_RETRY_BACKOFF_SECONDS * (attempt + 1)


def _is_transient_transport_result(
    result: WbFinancePageResult | WbSalesReportListPageResult,
) -> bool:
    return (
        result.status == "transport_or_schema_error"
        and result.error in TRANSIENT_WB_TRANSPORT_ERRORS
    )


def export_wb_finance_report_id_page(
    client: WbFinanceClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    report_id: str,
    rrd_id: int,
    limit: int,
    page_index: int,
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> WbFinancePageResult:
    try:
        rows, status_code = client.fetch_sales_report_by_id_page(
            report_id=report_id,
            rrd_id=rrd_id,
            limit=limit,
            fields=fields,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        status = _status_from_http(status_code)
        return WbFinancePageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=False,
            status=status,
            row_count=0,
            rrd_id_start=rrd_id,
            status_code=status_code,
            error=f"HTTP {status_code}",
            wb_report_id=report_id,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return WbFinancePageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=False,
            status="transport_or_schema_error",
            row_count=0,
            rrd_id_start=rrd_id,
            error=exc.__class__.__name__,
            wb_report_id=report_id,
        )

    if status_code == 204:
        return WbFinancePageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=True,
            status="no_data",
            row_count=0,
            rrd_id_start=rrd_id,
            status_code=status_code,
            wb_report_id=report_id,
        )

    payload_hash = raw_payload_hash(rows)
    output_path = output_dir / (
        f"{account.seller_account_id.lower()}_report_{report_id}"
        f"_finance_page_{page_index}.raw.json"
    )
    _write_json_list(output_path, rows)
    return WbFinancePageResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        page_index=page_index,
        ok=True,
        status="ok",
        row_count=len(rows),
        rrd_id_start=rrd_id,
        rrd_id_next=extract_next_rrd_id(rows),
        raw_payload_hash=payload_hash,
        output_path=output_path,
        status_code=status_code,
        wb_report_id=report_id,
    )


def export_wb_finance_page(
    client: WbFinanceClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    rrd_id: int,
    limit: int,
    page_index: int,
    period: str = "daily",
    fields: Iterable[str] = DEFAULT_FINANCE_FIELDS,
) -> WbFinancePageResult:
    try:
        rows, status_code = client.fetch_sales_report_page(
            period_start=period_start,
            period_end=period_end,
            rrd_id=rrd_id,
            limit=limit,
            period=period,
            fields=fields,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        status = _status_from_http(status_code)
        return WbFinancePageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=False,
            status=status,
            row_count=0,
            rrd_id_start=rrd_id,
            status_code=status_code,
            error=f"HTTP {status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return WbFinancePageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=False,
            status="transport_or_schema_error",
            row_count=0,
            rrd_id_start=rrd_id,
            error=exc.__class__.__name__,
        )

    if status_code == 204:
        return WbFinancePageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=True,
            status="no_data",
            row_count=0,
            rrd_id_start=rrd_id,
            status_code=status_code,
        )

    payload_hash = raw_payload_hash(rows)
    output_path = output_dir / (
        f"{account.seller_account_id.lower()}_finance_page_{page_index}.raw.json"
    )
    _write_json_list(output_path, rows)
    return WbFinancePageResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        page_index=page_index,
        ok=True,
        status="ok",
        row_count=len(rows),
        rrd_id_start=rrd_id,
        rrd_id_next=extract_next_rrd_id(rows),
        raw_payload_hash=payload_hash,
        output_path=output_path,
        status_code=status_code,
    )


def export_wb_sales_report_list_page(
    client: WbFinanceClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    limit: int,
    offset: int,
    page_index: int,
    period: str = "weekly",
) -> WbSalesReportListPageResult:
    try:
        rows, status_code = client.fetch_sales_report_list_page(
            period_start=period_start,
            period_end=period_end,
            limit=limit,
            offset=offset,
            period=period,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return WbSalesReportListPageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=False,
            status=_status_from_http(status_code),
            row_count=0,
            offset=offset,
            status_code=status_code,
            error=f"HTTP {status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return WbSalesReportListPageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=False,
            status="transport_or_schema_error",
            row_count=0,
            offset=offset,
            error=exc.__class__.__name__,
        )

    if status_code == 204:
        return WbSalesReportListPageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            page_index=page_index,
            ok=True,
            status="no_data",
            row_count=0,
            offset=offset,
            status_code=status_code,
        )

    payload_hash = raw_payload_hash(rows)
    output_path = output_dir / (
        f"{account.seller_account_id.lower()}_sales_report_list_page_{page_index}.raw.json"
    )
    _write_json_list(output_path, rows)
    return WbSalesReportListPageResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        page_index=page_index,
        ok=True,
        status="ok",
        row_count=len(rows),
        offset=offset,
        raw_payload_hash=payload_hash,
        output_path=output_path,
        status_code=status_code,
    )


def normalize_finance_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    client_id: str,
    seller_account_id: str,
    organization_id: str,
    period_start: date,
    period_end: date,
    loaded_at: datetime,
    is_partial_source: bool = False,
) -> list[WbApiSnapshot]:
    return [
        normalize_finance_row(
            row,
            client_id=client_id,
            seller_account_id=seller_account_id,
            organization_id=organization_id,
            period_start=period_start,
            period_end=period_end,
            loaded_at=loaded_at,
            is_partial_source=is_partial_source,
        )
        for row in rows
    ]


def normalize_finance_row(
    row: Mapping[str, Any],
    *,
    client_id: str,
    seller_account_id: str,
    organization_id: str,
    period_start: date,
    period_end: date,
    loaded_at: datetime,
    is_partial_source: bool = False,
) -> WbApiSnapshot:
    doc_type = _text(_first(row, "docTypeName", "doc_type_name"))
    operation = doc_type or _text(
        _first(row, "sellerOperName", "supplierOperName", "supplier_oper_name")
    )
    is_return = _is_return_operation(operation)
    row_date = _date_from_row(row) or period_start
    row_hash = raw_payload_hash(row)
    penalty = decimal_from_value(_first(row, "penalty"))
    deduction = decimal_from_value(_first(row, "deduction"))
    additional = decimal_from_value(
        _first(row, "additionalPayment", "additional_payment")
    )
    vat_input_from_wb = signed_decimal(
        decimal_from_value(_first(row, "vwNds", "vw_nds"))
        + decimal_from_value(_first(row, "agencyVat", "agency_vat")),
        is_return=is_return,
    )
    return WbApiSnapshot(
        client_id=client_id,
        seller_account_id=seller_account_id,
        organization_id=organization_id,
        period_start=row_date,
        period_end=row_date if period_start <= row_date <= period_end else period_end,
        source_endpoint=FINANCE_DETAILED_ENDPOINT,
        loaded_at=loaded_at,
        wb_document_id=_document_id(row, row_hash),
        wb_report_id=_report_id(row),
        report_type=_int_or_none(_first(row, "reportType", "report_type")),
        nm_id=_int_or_none(_first(row, "nmId", "nm_id")),
        vendor_code=_text(_first(row, "vendorCode", "sa_name")).lower(),
        barcode=_text(_first(row, "sku", "barcode")),
        sales_model=_sales_model(row),
        operation_type=operation,
        quantity=signed_decimal(_first(row, "quantity"), is_return=is_return),
        net_revenue=signed_decimal(
            _first(row, "retailAmount", "retail_amount"),
            is_return=is_return,
        ),
        wb_commission=signed_decimal(
            _first(row, "ppvzSalesCommission", "ppvz_sales_commission"),
            is_return=is_return,
        ),
        logistics=decimal_from_value(_first(row, "deliveryService", "delivery_rub")),
        storage=decimal_from_value(_first(row, "paidStorage", "storage_fee")),
        acceptance=decimal_from_value(_first(row, "paidAcceptance", "acceptance")),
        wb_promotion=deduction,
        penalties_and_holdbacks=penalty - additional,
        acquiring=signed_decimal(
            _first(row, "acquiringFee", "acquiring_fee"),
            is_return=is_return,
        ),
        vat_input_from_wb=vat_input_from_wb,
        currency=_text(_first(row, "currency")) or "RUB",
        raw_payload_hash=row_hash,
        original_sale_date=_parse_date(_first(row, "saleDt", "sale_dt")),
        is_partial_source=is_partial_source,
    )


def load_wb_finance_snapshots(
    export_dir: Path,
    *,
    client_id: str,
    account_org_mapping: Iterable[AccountOrgMapping],
) -> list[WbApiSnapshot]:
    return list(
        iter_wb_finance_snapshots(
            export_dir,
            client_id=client_id,
            account_org_mapping=account_org_mapping,
        )
    )


def iter_wb_finance_snapshots(
    export_dir: Path,
    *,
    client_id: str,
    account_org_mapping: Iterable[AccountOrgMapping],
) -> Iterator[WbApiSnapshot]:
    verify_raw_directory(export_dir, source_type="wb_finance_detail")
    manifest_path = export_dir / "manifest.json"
    manifest = _read_json_object(manifest_path)
    loaded_at = _parse_datetime(manifest.get("generated_at")) or datetime.now(
        tz=MOSCOW_TZ
    )
    period_start = _parse_date(manifest.get("period_start")) or date(2026, 4, 1)
    period_end = _parse_date(manifest.get("period_end")) or date(2026, 6, 30)
    account_to_org = {
        item.seller_account_id: item.organization_id for item in account_org_mapping
    }
    for result in manifest.get("results", []):
        if not isinstance(result, dict) or result.get("status") != "ok":
            continue
        seller_account_id = _text(result.get("seller_account_id"))
        output_file = _text(result.get("output_file"))
        if not seller_account_id or not output_file:
            continue
        is_partial_source = not _manifest_complete_for_account(
            manifest, seller_account_id
        )
        for row in _iter_json_list_objects(export_dir / output_file):
            yield normalize_finance_row(
                row,
                client_id=client_id,
                seller_account_id=seller_account_id,
                organization_id=account_to_org.get(seller_account_id, ""),
                period_start=period_start,
                period_end=period_end,
                loaded_at=loaded_at,
                is_partial_source=is_partial_source,
            )


def load_wb_sales_report_summary_rows(
    export_dir: Path,
    *,
    client_id: str,
) -> list[WbSalesReportSummaryRow]:
    verify_raw_directory(export_dir, source_type="wb_sales_report_list")
    manifest = _read_json_object(export_dir / "manifest.json")
    rows: list[WbSalesReportSummaryRow] = []
    for result in manifest.get("results", []):
        if not isinstance(result, dict):
            continue
        status = _text(result.get("status"))
        status_code = _int_or_none(result.get("status_code"))
        if status not in {"", "ok"} and status_code != 200:
            continue
        if status_code is not None and status_code != 200:
            continue
        seller_account_id = _text(result.get("seller_account_id"))
        account_name = _text(result.get("account_name")) or seller_account_id
        output_file = _text(result.get("output_file"))
        if not seller_account_id or not output_file:
            continue
        for source_row in _read_json_list(export_dir / output_file):
            rows.append(
                normalize_sales_report_summary_row(
                    source_row,
                    client_id=client_id,
                    seller_account_id=seller_account_id,
                    account_name=account_name,
                )
            )
    return rows


def normalize_sales_report_summary_row(
    row: Mapping[str, Any],
    *,
    client_id: str,
    seller_account_id: str,
    account_name: str,
) -> WbSalesReportSummaryRow:
    row_hash = raw_payload_hash(row)
    return WbSalesReportSummaryRow(
        client_id=client_id,
        seller_account_id=seller_account_id,
        account_name=account_name,
        report_id=_text(_first(row, "reportId", "report_id")),
        seller_finance_name=_text(_first(row, "sellerFinanceName")),
        date_from=_parse_date(_first(row, "dateFrom")) or date.min,
        date_to=_parse_date(_first(row, "dateTo")) or date.min,
        create_date=_parse_date(_first(row, "createDate")) or date.min,
        currency=_text(_first(row, "currency")) or "RUB",
        report_type=_int_or_none(_first(row, "reportType")),
        retail_amount_sum=decimal_from_value(_first(row, "retailAmountSum")),
        for_pay_sum=decimal_from_value(_first(row, "forPaySum")),
        delivery_service_sum=decimal_from_value(_first(row, "deliveryServiceSum")),
        paid_storage_sum=decimal_from_value(_first(row, "paidStorageSum")),
        paid_acceptance_sum=decimal_from_value(_first(row, "paidAcceptanceSum")),
        deduction_sum=decimal_from_value(_first(row, "deductionSum")),
        penalty_sum=decimal_from_value(_first(row, "penaltySum")),
        additional_payment_sum=decimal_from_value(
            _first(row, "additionalPaymentSum")
        ),
        cashback_amount_sum=decimal_from_value(_first(row, "cashbackAmountSum")),
        cashback_discount_sum=decimal_from_value(_first(row, "cashbackDiscountSum")),
        cashback_commission_change_sum=decimal_from_value(
            _first(row, "cashbackCommissionChangeSum")
        ),
        bank_payment_sum=decimal_from_value(_first(row, "bankPaymentSum")),
        raw_payload_hash=row_hash,
    )


def extract_next_rrd_id(rows: list[Mapping[str, Any]]) -> int | None:
    if not rows:
        return None
    return _int_or_none(_first(rows[-1], "rrdId", "rrd_id"))


def decimal_from_value(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def signed_decimal(value: object, *, is_return: bool) -> Decimal:
    result = decimal_from_value(value)
    if is_return and result > 0:
        return -result
    return result


def raw_payload_hash(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _finance_page_results_from_manifest(
    manifest: Mapping[str, Any],
    export_dir: Path,
) -> list[WbFinancePageResult]:
    results: list[WbFinancePageResult] = []
    for item in manifest.get("results", []):
        if not isinstance(item, dict):
            continue
        output_file = _text(item.get("output_file"))
        results.append(
            WbFinancePageResult(
                seller_account_id=_text(item.get("seller_account_id")),
                account_name=_text(item.get("account_name")),
                page_index=_int_or_none(item.get("page_index")) or 0,
                ok=item.get("ok") is True,
                status=_text(item.get("status")),
                row_count=_int_or_none(item.get("row_count")) or 0,
                rrd_id_start=_int_or_none(item.get("rrd_id_start")) or 0,
                rrd_id_next=_int_or_none(item.get("rrd_id_next")),
                raw_payload_hash=_text(item.get("raw_payload_hash")),
                output_path=export_dir / output_file if output_file else None,
                status_code=_int_or_none(item.get("status_code")),
                error=_text(item.get("error")),
                wb_report_id=_text(item.get("wb_report_id")),
            )
        )
    return results


def _finance_resume_point(
    manifest: Mapping[str, Any],
    seller_account_id: str,
) -> tuple[int, int] | None:
    results = [
        item
        for item in manifest.get("results", [])
        if isinstance(item, dict)
        and _text(item.get("seller_account_id")) == seller_account_id
    ]
    if not results:
        return 0, 1
    last = results[-1]
    status = _text(last.get("status"))
    page_index = _int_or_none(last.get("page_index")) or len(results)
    rrd_id_start = _int_or_none(last.get("rrd_id_start")) or 0
    rrd_id_next = _int_or_none(last.get("rrd_id_next"))
    if status == "no_data":
        return None
    if status == "ok" and rrd_id_next is not None and rrd_id_next != rrd_id_start:
        return rrd_id_next, page_index + 1
    if status in {"rate_limited", "transport_or_schema_error"}:
        return rrd_id_start, max(1, page_index)
    return None


def _backup_manifest(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now(tz=MOSCOW_TZ).strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.before-resume-{stamp}{path.suffix}")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _write_manifest(
    path: Path,
    results: list[WbFinancePageResult],
    *,
    period_start: date,
    period_end: date,
    limit: int,
    max_pages: int,
    period: str,
    request_delay_seconds: float,
    fields: Iterable[str],
    extra: Mapping[str, Any] | None = None,
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "wb_finance_sales_reports_detailed",
        "endpoint": FINANCE_DETAILED_ENDPOINT,
        "read_boundary": "read-only POST financial report details",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period": period,
        "limit": limit,
        "max_pages": max_pages,
        "request_delay_seconds": request_delay_seconds,
        "fields": list(fields),
        "results": [
            {
                "seller_account_id": item.seller_account_id,
                "account_name": item.account_name,
                "page_index": item.page_index,
                "ok": item.ok,
                "status": item.status,
                "row_count": item.row_count,
                "status_code": item.status_code,
                "rrd_id_start": item.rrd_id_start,
                "rrd_id_next": item.rrd_id_next,
                "raw_payload_hash": item.raw_payload_hash,
                "output_file": item.output_path.name if item.output_path else None,
                "error": item.error,
                "wb_report_id": item.wb_report_id,
            }
            for item in results
        ],
    }
    if extra:
        manifest.update(extra)
    _write_json(path, manifest)


def _write_report_id_manifest(
    path: Path,
    results: list[WbFinancePageResult],
    *,
    report_ids: Iterable[str],
    limit: int,
    max_pages: int,
    request_delay_seconds: float,
    fields: Iterable[str],
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "wb_finance_sales_reports_detailed_by_report_id",
        "endpoint": FINANCE_DETAILED_BY_REPORT_ENDPOINT,
        "read_boundary": "read-only POST financial report details by reportId",
        "report_ids": list(report_ids),
        "limit": limit,
        "max_pages": max_pages,
        "request_delay_seconds": request_delay_seconds,
        "fields": list(fields),
        "results": [
            {
                "seller_account_id": item.seller_account_id,
                "account_name": item.account_name,
                "wb_report_id": item.wb_report_id,
                "page_index": item.page_index,
                "ok": item.ok,
                "status": item.status,
                "row_count": item.row_count,
                "status_code": item.status_code,
                "rrd_id_start": item.rrd_id_start,
                "rrd_id_next": item.rrd_id_next,
                "raw_payload_hash": item.raw_payload_hash,
                "output_file": item.output_path.name if item.output_path else None,
                "error": item.error,
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def _write_sales_report_list_manifest(
    path: Path,
    results: list[WbSalesReportListPageResult],
    *,
    period_start: date,
    period_end: date,
    limit: int,
    max_pages: int,
    period: str,
    request_delay_seconds: float,
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "wb_sales_reports_list",
        "endpoint": FINANCE_REPORT_LIST_ENDPOINT,
        "read_boundary": "read-only POST financial sales report list",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period": period,
        "limit": limit,
        "max_pages": max_pages,
        "request_delay_seconds": request_delay_seconds,
        "results": [
            {
                "seller_account_id": item.seller_account_id,
                "account_name": item.account_name,
                "page_index": item.page_index,
                "ok": item.ok,
                "status": item.status,
                "row_count": item.row_count,
                "status_code": item.status_code,
                "offset": item.offset,
                "raw_payload_hash": item.raw_payload_hash,
                "output_file": item.output_path.name if item.output_path else None,
                "error": item.error,
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def _status_from_http(status_code: int) -> str:
    if status_code in {401, 403}:
        return "access_error"
    if status_code == 429:
        return "rate_limited"
    return "http_error"


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _is_return_operation(value: str) -> bool:
    lowered = value.strip().lower()
    return "возврат" in lowered or "return" in lowered


def _sales_model(row: Mapping[str, Any]) -> SalesModel:
    delivery_method = _text(_first(row, "deliveryMethod", "delivery_method")).upper()
    if "FBS" in delivery_method or "DBS" in delivery_method or row.get("srvDbs"):
        return SalesModel.FBS
    return SalesModel.FBO


def _date_from_row(row: Mapping[str, Any]) -> date | None:
    return _parse_date(_first(row, "rrDate", "rr_dt", "saleDt", "sale_dt"))


def _parse_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _parse_datetime(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    return datetime.fromisoformat(text)


def _document_id(row: Mapping[str, Any], row_hash: str) -> str:
    for key in ("rrdId", "rrd_id", "srid", "reportId", "realizationreport_id"):
        value = _text(row.get(key))
        if value:
            return value
    return row_hash


def _report_id(row: Mapping[str, Any]) -> str:
    return _text(
        _first(
            row,
            "reportId",
            "report_id",
            "realizationReportId",
            "realizationreport_id",
        )
    )


def _manifest_complete_for_account(
    manifest: Mapping[str, Any],
    account_id: str,
) -> bool:
    results = [
        item
        for item in manifest.get("results", [])
        if isinstance(item, dict) and item.get("seller_account_id") == account_id
    ]
    return bool(results) and results[-1].get("status") == "no_data"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_json_list(path: Path, payload: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list: {path}")
    return [item for item in data if isinstance(item, dict)]


def _iter_json_list_objects(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    buffer = ""
    pos = 0
    seen_array_start = False
    with path.open("r", encoding="utf-8") as handle:
        while True:
            chunk = handle.read(chunk_size)
            eof = chunk == ""
            buffer += chunk
            while True:
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if not seen_array_start:
                    if pos >= len(buffer):
                        break
                    if buffer[pos] != "[":
                        raise ValueError(f"Expected JSON list: {path}")
                    seen_array_start = True
                    pos += 1
                    continue
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if pos >= len(buffer):
                    break
                if buffer[pos] == "]":
                    return
                if buffer[pos] == ",":
                    pos += 1
                    continue
                try:
                    item, next_pos = decoder.raw_decode(buffer, pos)
                except json.JSONDecodeError:
                    if eof:
                        raise
                    break
                if isinstance(item, dict):
                    yield item
                pos = next_pos
            if eof:
                if seen_array_start:
                    raise ValueError(f"Unterminated JSON list: {path}")
                raise ValueError(f"Empty JSON file: {path}")
            if pos > chunk_size:
                buffer = buffer[pos:]
                pos = 0


def _load_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values
