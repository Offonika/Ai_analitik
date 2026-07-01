from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from wb_unit_economics.calculation import (
    EXPENSE_STORAGE,
    EXPENSE_WB_PROMOTION,
    week_bounds,
)
from wb_unit_economics.contracts import WbExpenseAllocationBase
from wb_unit_economics.wb_finance import (
    WbFinanceSellerAccount,
    WbFinanceSettings,
    decimal_from_value,
    raw_payload_hash,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PAID_STORAGE_ENDPOINT = "https://seller-analytics-api.wildberries.ru/api/v1/paid_storage"
PAID_STORAGE_STATUS_ENDPOINT = PAID_STORAGE_ENDPOINT + "/tasks/{task_id}/status"
PAID_STORAGE_DOWNLOAD_ENDPOINT = PAID_STORAGE_ENDPOINT + "/tasks/{task_id}/download"
PROMOTION_COUNT_ENDPOINT = "https://advert-api.wildberries.ru/adv/v1/promotion/count"
PROMOTION_FULLSTATS_ENDPOINT = "https://advert-api.wildberries.ru/adv/v3/fullstats"
PROMOTION_STATUSES = (7, 9, 11)


@dataclass(frozen=True)
class WbExpenseExportResult:
    seller_account_id: str
    account_name: str
    source: str
    ok: bool
    status: str
    row_count: int
    output_path: Path | None = None
    status_code: int | None = None
    error: str = ""
    raw_payload_hash: str = ""
    task_id: str = ""
    campaign_ids: tuple[int, ...] = ()


class WbExpenseClient:
    """Read-only client for WB storage and campaign expense allocation bases."""

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

    def __enter__(self) -> WbExpenseClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def create_paid_storage_task(
        self,
        *,
        period_start: date,
        period_end: date,
    ) -> tuple[str, int]:
        response = self._client.get(
            PAID_STORAGE_ENDPOINT,
            params={
                "dateFrom": period_start.isoformat(),
                "dateTo": period_end.isoformat(),
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB paid storage task payload")
        task_id = _text(_first(data.get("data") or {}, "taskId", "task_id", "id"))
        if not task_id:
            raise ValueError("WB paid storage response has no taskId")
        return task_id, response.status_code

    def fetch_paid_storage_status(self, task_id: str) -> tuple[str, int]:
        response = self._client.get(
            PAID_STORAGE_STATUS_ENDPOINT.format(task_id=task_id)
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB paid storage status payload")
        status = _text(_first(data.get("data") or data, "status"))
        return status, response.status_code

    def download_paid_storage(self, task_id: str) -> tuple[list[dict[str, Any]], int]:
        response = self._client.get(
            PAID_STORAGE_DOWNLOAD_ENDPOINT.format(task_id=task_id)
        )
        if response.status_code == 204:
            return [], response.status_code
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected WB paid storage download payload")
        return [item for item in data if isinstance(item, dict)], response.status_code

    def fetch_promotion_count(self) -> tuple[dict[str, Any], int]:
        response = self._client.get(PROMOTION_COUNT_ENDPOINT)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB promotion count payload")
        return data, response.status_code

    def fetch_promotion_fullstats(
        self,
        *,
        campaign_ids: Iterable[int],
        period_start: date,
        period_end: date,
    ) -> tuple[list[dict[str, Any]], int]:
        ids = ",".join(str(campaign_id) for campaign_id in campaign_ids)
        response = self._client.get(
            PROMOTION_FULLSTATS_ENDPOINT,
            params={
                "ids": ids,
                "beginDate": period_start.isoformat(),
                "endDate": period_end.isoformat(),
            },
        )
        if response.status_code == 204:
            return [], response.status_code
        response.raise_for_status()
        data = response.json()
        if data is None:
            return [], response.status_code
        if not isinstance(data, list):
            raise ValueError("Unexpected WB promotion fullstats payload")
        return [item for item in data if isinstance(item, dict)], response.status_code


def export_wb_paid_storage(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    status_poll_seconds: float = 5.0,
    max_status_checks: int = 24,
    download_delay_seconds: float = 61.0,
    chunk_days: int | None = None,
) -> list[WbExpenseExportResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbExpenseExportResult] = []
    chunks = list(_period_chunks(period_start, period_end, chunk_days=chunk_days))
    for account in settings.accounts:
        with WbExpenseClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            for chunk_start, chunk_end in chunks:
                result = export_wb_paid_storage_for_account(
                    client,
                    account,
                    output_dir,
                    period_start=chunk_start,
                    period_end=chunk_end,
                    status_poll_seconds=status_poll_seconds,
                    max_status_checks=max_status_checks,
                    download_delay_seconds=download_delay_seconds,
                    output_file_suffix=(
                        f"_{chunk_start.isoformat()}_{chunk_end.isoformat()}"
                    ),
                )
                results.append(result)
    _write_expense_manifest(
        output_dir / "manifest.json",
        results,
        source="wb_paid_storage",
        endpoint=PAID_STORAGE_ENDPOINT,
        read_boundary="read-only GET paid storage allocation base",
        period_start=period_start,
        period_end=period_end,
        params={
            "status_poll_seconds": status_poll_seconds,
            "max_status_checks": max_status_checks,
            "download_delay_seconds": download_delay_seconds,
            "chunk_days": chunk_days,
        },
    )
    return results


def export_wb_paid_storage_for_account(
    client: WbExpenseClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    status_poll_seconds: float = 5.0,
    max_status_checks: int = 24,
    download_delay_seconds: float = 61.0,
    output_file_suffix: str = "",
) -> WbExpenseExportResult:
    try:
        task_id, status_code = client.create_paid_storage_task(
            period_start=period_start,
            period_end=period_end,
        )
        status = ""
        for check_index in range(max_status_checks):
            if check_index > 0:
                time.sleep(status_poll_seconds)
            status, status_code = client.fetch_paid_storage_status(task_id)
            if status.lower() in {"done", "ready", "success", "completed"}:
                break
            if status.lower() in {"error", "failed", "canceled", "cancelled"}:
                return WbExpenseExportResult(
                    seller_account_id=account.seller_account_id,
                    account_name=account.account_name,
                    source="wb_paid_storage",
                    ok=False,
                    status="task_failed",
                    row_count=0,
                    status_code=status_code,
                    error=f"task status={status}",
                    task_id=task_id,
                )
        else:
            return WbExpenseExportResult(
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                source="wb_paid_storage",
                ok=False,
                status="task_timeout",
                row_count=0,
                status_code=status_code,
                error=f"task status={status or 'unknown'}",
                task_id=task_id,
            )
        time.sleep(download_delay_seconds)
        rows, status_code = client.download_paid_storage(task_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return _expense_error_result(
            account,
            source="wb_paid_storage",
            status=_status_from_http(status_code),
            status_code=status_code,
            error=f"HTTP {status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _expense_error_result(
            account,
            source="wb_paid_storage",
            status="transport_or_schema_error",
            error=exc.__class__.__name__,
        )

    if status_code == 204:
        return WbExpenseExportResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            source="wb_paid_storage",
            ok=True,
            status="no_data",
            row_count=0,
            status_code=status_code,
            task_id=task_id,
        )

    payload_hash = raw_payload_hash(rows)
    output_path = output_dir / (
        f"{account.seller_account_id.lower()}_paid_storage"
        f"{output_file_suffix}.raw.json"
    )
    _write_json_list(output_path, rows)
    return WbExpenseExportResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        source="wb_paid_storage",
        ok=True,
        status="ok",
        row_count=len(rows),
        output_path=output_path,
        status_code=status_code,
        raw_payload_hash=payload_hash,
        task_id=task_id,
    )


def _period_chunks(
    period_start: date,
    period_end: date,
    *,
    chunk_days: int | None,
) -> Iterable[tuple[date, date]]:
    if chunk_days is None:
        yield period_start, period_end
        return
    if chunk_days < 1:
        raise ValueError("chunk_days must be positive")
    current_start = period_start
    while current_start <= period_end:
        current_end = min(current_start + timedelta(days=chunk_days - 1), period_end)
        yield current_start, current_end
        current_start = current_end + timedelta(days=1)


def export_wb_promotion_stats(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    statuses: Iterable[int] = PROMOTION_STATUSES,
    batch_size: int = 50,
    request_delay_seconds: float = 20.0,
    chunk_days: int | None = None,
    chunk_delay_seconds: float = 70.0,
    retry_attempts: int = 0,
    retry_delay_seconds: float = 70.0,
) -> list[WbExpenseExportResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbExpenseExportResult] = []
    status_values = tuple(int(status) for status in statuses)
    chunks = list(_period_chunks(period_start, period_end, chunk_days=chunk_days))
    for account in settings.accounts:
        with WbExpenseClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            for chunk_index, (chunk_start, chunk_end) in enumerate(chunks):
                if chunk_index > 0 and chunk_delay_seconds > 0:
                    time.sleep(chunk_delay_seconds)
                output_file_suffix = (
                    f"_{chunk_start.isoformat()}_{chunk_end.isoformat()}"
                )
                result = export_wb_promotion_stats_for_account(
                    client,
                    account,
                    output_dir,
                    period_start=chunk_start,
                    period_end=chunk_end,
                    statuses=status_values,
                    batch_size=batch_size,
                    request_delay_seconds=request_delay_seconds,
                    output_file_suffix=output_file_suffix,
                )
                for _attempt in range(retry_attempts):
                    if result.ok or result.status not in {
                        "http_error",
                        "rate_limited",
                        "transport_or_schema_error",
                    }:
                        break
                    if retry_delay_seconds > 0:
                        time.sleep(retry_delay_seconds)
                    result = export_wb_promotion_stats_for_account(
                        client,
                        account,
                        output_dir,
                        period_start=chunk_start,
                        period_end=chunk_end,
                        statuses=status_values,
                        batch_size=batch_size,
                        request_delay_seconds=request_delay_seconds,
                        output_file_suffix=output_file_suffix,
                    )
                results.append(result)
    _write_expense_manifest(
        output_dir / "manifest.json",
        results,
        source="wb_promotion_stats",
        endpoint=PROMOTION_FULLSTATS_ENDPOINT,
        read_boundary="read-only GET campaign statistics allocation base",
        period_start=period_start,
        period_end=period_end,
        params={
            "statuses": list(status_values),
            "batch_size": batch_size,
            "request_delay_seconds": request_delay_seconds,
            "chunk_days": chunk_days,
            "chunk_delay_seconds": chunk_delay_seconds,
            "retry_attempts": retry_attempts,
            "retry_delay_seconds": retry_delay_seconds,
        },
    )
    return results


def export_wb_promotion_stats_for_account(
    client: WbExpenseClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    statuses: Iterable[int] = PROMOTION_STATUSES,
    batch_size: int = 50,
    request_delay_seconds: float = 20.0,
    output_file_suffix: str = "",
) -> WbExpenseExportResult:
    try:
        count_payload, status_code = client.fetch_promotion_count()
        campaign_ids = tuple(
            sorted(_campaign_ids_from_count(count_payload, statuses=statuses))
        )
        if not campaign_ids:
            return WbExpenseExportResult(
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                source="wb_promotion_stats",
                ok=True,
                status="no_campaigns",
                row_count=0,
                status_code=status_code,
                campaign_ids=(),
            )
        rows: list[dict[str, Any]] = []
        batches = [
            campaign_ids[index : index + batch_size]
            for index in range(0, len(campaign_ids), batch_size)
        ]
        for batch_index, batch in enumerate(batches):
            if batch_index > 0:
                time.sleep(request_delay_seconds)
            batch_rows, status_code = client.fetch_promotion_fullstats(
                campaign_ids=batch,
                period_start=period_start,
                period_end=period_end,
            )
            rows.extend(batch_rows)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return _expense_error_result(
            account,
            source="wb_promotion_stats",
            status=_status_from_http(status_code),
            status_code=status_code,
            error=f"HTTP {status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _expense_error_result(
            account,
            source="wb_promotion_stats",
            status="transport_or_schema_error",
            error=exc.__class__.__name__,
        )

    payload_hash = raw_payload_hash(rows)
    output_path = output_dir / (
        f"{account.seller_account_id.lower()}_promotion_fullstats"
        f"{output_file_suffix}.raw.json"
    )
    _write_json_list(output_path, rows)
    return WbExpenseExportResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        source="wb_promotion_stats",
        ok=True,
        status="ok",
        row_count=len(rows),
        output_path=output_path,
        status_code=status_code,
        raw_payload_hash=payload_hash,
        campaign_ids=campaign_ids,
    )


def load_wb_expense_allocation_bases(
    *,
    client_id: str,
    paid_storage_dir: Path | None = None,
    promotion_stats_dir: Path | None = None,
) -> list[WbExpenseAllocationBase]:
    rows: list[WbExpenseAllocationBase] = []
    if paid_storage_dir is not None and (paid_storage_dir / "manifest.json").exists():
        rows.extend(
            load_wb_paid_storage_allocation_bases(
                paid_storage_dir,
                client_id=client_id,
            )
        )
    if (
        promotion_stats_dir is not None
        and (promotion_stats_dir / "manifest.json").exists()
    ):
        rows.extend(
            load_wb_promotion_allocation_bases(
                promotion_stats_dir,
                client_id=client_id,
            )
        )
    return rows


def load_wb_paid_storage_allocation_bases(
    export_dir: Path,
    *,
    client_id: str,
) -> list[WbExpenseAllocationBase]:
    manifest = _read_json_object(export_dir / "manifest.json")
    loaded_rows: list[tuple[str, Mapping[str, Any]]] = []
    for result in manifest.get("results", []):
        if not isinstance(result, dict) or result.get("status") != "ok":
            continue
        seller_account_id = _text(result.get("seller_account_id"))
        output_file = _text(result.get("output_file"))
        if not seller_account_id or not output_file:
            continue
        for row in _read_json_list(export_dir / output_file):
            loaded_rows.append((seller_account_id, row))
    return _group_storage_rows(client_id=client_id, rows=loaded_rows)


def load_wb_promotion_allocation_bases(
    export_dir: Path,
    *,
    client_id: str,
) -> list[WbExpenseAllocationBase]:
    manifest = _read_json_object(export_dir / "manifest.json")
    loaded_rows: list[tuple[str, Mapping[str, Any]]] = []
    for result in manifest.get("results", []):
        if not isinstance(result, dict) or result.get("status") != "ok":
            continue
        seller_account_id = _text(result.get("seller_account_id"))
        output_file = _text(result.get("output_file"))
        if not seller_account_id or not output_file:
            continue
        for row in _read_json_list(export_dir / output_file):
            loaded_rows.append((seller_account_id, row))
    return _group_promotion_rows(client_id=client_id, rows=loaded_rows)


def _group_storage_rows(
    *,
    client_id: str,
    rows: list[tuple[str, Mapping[str, Any]]],
) -> list[WbExpenseAllocationBase]:
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for seller_account_id, row in rows:
        row_date = _parse_date(_first(row, "date", "dt"))
        nm_id = _int_or_none(_first(row, "nmId", "nmID", "nm_id"))
        if row_date is None or nm_id is None:
            continue
        week_start, week_end = week_bounds(row_date)
        vendor_code = _text(_first(row, "vendorCode", "sa")).lower()
        barcode = _text(_first(row, "barcode", "sku"))
        amount = decimal_from_value(
            _first(
                row,
                "warehousePrice",
                "warehouse_price",
                "storageFee",
                "storage_fee",
                "sum",
                "amount",
            )
        )
        key = (
            seller_account_id,
            week_start,
            week_end,
            nm_id,
            vendor_code,
            barcode,
        )
        if key not in grouped:
            grouped[key] = {
                "amount": Decimal("0"),
                "hashes": [],
                "source_row_count": 0,
            }
        grouped[key]["amount"] += amount
        grouped[key]["hashes"].append(raw_payload_hash(row))
        grouped[key]["source_row_count"] += 1
    return [
        WbExpenseAllocationBase(
            client_id=client_id,
            seller_account_id=seller_account_id,
            week_start=week_start,
            week_end=week_end,
            expense_category=EXPENSE_STORAGE,
            nm_id=nm_id,
            vendor_code=vendor_code,
            barcode=barcode,
            amount=money_value(bucket["amount"]),
            source_endpoint=PAID_STORAGE_DOWNLOAD_ENDPOINT,
            source_row_count=int(bucket["source_row_count"]),
            raw_payload_hashes=tuple(sorted(set(bucket["hashes"]))),
        )
        for (
            seller_account_id,
            week_start,
            week_end,
            nm_id,
            vendor_code,
            barcode,
        ), bucket in grouped.items()
    ]


def _group_promotion_rows(
    *,
    client_id: str,
    rows: list[tuple[str, Mapping[str, Any]]],
) -> list[WbExpenseAllocationBase]:
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for seller_account_id, row in rows:
        advert_id = _int_or_none(_first(row, "advertId", "advert_id"))
        for day in _iter_dicts(row.get("days")):
            day_date = _parse_date(_first(day, "date"))
            if day_date is None:
                continue
            week_start, week_end = week_bounds(day_date)
            for app in _iter_dicts(day.get("apps")):
                for nm_row in _iter_dicts(app.get("nms")):
                    nm_id = _int_or_none(_first(nm_row, "nmId", "nm", "nm_id"))
                    if nm_id is None:
                        continue
                    amount = decimal_from_value(_first(nm_row, "sum", "amount"))
                    key = (seller_account_id, week_start, week_end, nm_id)
                    if key not in grouped:
                        grouped[key] = {
                            "amount": Decimal("0"),
                            "hashes": [],
                            "source_row_count": 0,
                        }
                    grouped[key]["amount"] += amount
                    grouped[key]["hashes"].append(
                        raw_payload_hash(
                            {
                                "advertId": advert_id,
                                "date": day_date.isoformat(),
                                "nm": nm_row,
                            }
                        )
                    )
                    grouped[key]["source_row_count"] += 1
    return [
        WbExpenseAllocationBase(
            client_id=client_id,
            seller_account_id=seller_account_id,
            week_start=week_start,
            week_end=week_end,
            expense_category=EXPENSE_WB_PROMOTION,
            nm_id=nm_id,
            amount=money_value(bucket["amount"]),
            source_endpoint=PROMOTION_FULLSTATS_ENDPOINT,
            source_row_count=int(bucket["source_row_count"]),
            raw_payload_hashes=tuple(sorted(set(bucket["hashes"]))),
        )
        for (seller_account_id, week_start, week_end, nm_id), bucket in grouped.items()
    ]


def _campaign_ids_from_count(
    payload: Mapping[str, Any],
    *,
    statuses: Iterable[int],
) -> set[int]:
    allowed_statuses = {int(status) for status in statuses}
    campaign_ids: set[int] = set()
    for group in _iter_dicts(payload.get("adverts")):
        group_status = _int_or_none(group.get("status"))
        if group_status not in allowed_statuses:
            continue
        for item in _iter_dicts(group.get("advert_list")):
            advert_id = _int_or_none(_first(item, "advertId", "id"))
            if advert_id is not None:
                campaign_ids.add(advert_id)
    return campaign_ids


def _expense_error_result(
    account: WbFinanceSellerAccount,
    *,
    source: str,
    status: str,
    status_code: int | None = None,
    error: str = "",
) -> WbExpenseExportResult:
    return WbExpenseExportResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        source=source,
        ok=False,
        status=status,
        row_count=0,
        status_code=status_code,
        error=error,
    )


def _write_expense_manifest(
    path: Path,
    results: list[WbExpenseExportResult],
    *,
    source: str,
    endpoint: str,
    read_boundary: str,
    period_start: date,
    period_end: date,
    params: Mapping[str, Any],
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": source,
        "endpoint": endpoint,
        "read_boundary": read_boundary,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        **params,
        "results": [
            {
                "seller_account_id": item.seller_account_id,
                "account_name": item.account_name,
                "source": item.source,
                "ok": item.ok,
                "status": item.status,
                "row_count": item.row_count,
                "status_code": item.status_code,
                "raw_payload_hash": item.raw_payload_hash,
                "output_file": item.output_path.name if item.output_path else None,
                "error": item.error,
                "task_id": item.task_id,
                "campaign_ids": list(item.campaign_ids),
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def money_value(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _status_from_http(status_code: int) -> str:
    if status_code in {401, 403}:
        return "access_error"
    if status_code == 429:
        return "rate_limited"
    return "http_error"


def _first(row: object, *keys: str) -> Any:
    if not isinstance(row, Mapping):
        return None
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


def _parse_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _iter_dicts(value: object) -> Iterable[dict[str, Any]]:
    if not isinstance(value, list):
        return ()
    return (item for item in value if isinstance(item, dict))


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
