from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from wb_unit_economics.wb_finance import (
    WbFinanceSellerAccount,
    WbFinanceSettings,
    raw_payload_hash,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
WAREHOUSE_REMAINS_ENDPOINT = (
    "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains"
)
WAREHOUSE_REMAINS_STATUS_ENDPOINT = (
    WAREHOUSE_REMAINS_ENDPOINT + "/tasks/{task_id}/status"
)
WAREHOUSE_REMAINS_DOWNLOAD_ENDPOINT = (
    WAREHOUSE_REMAINS_ENDPOINT + "/tasks/{task_id}/download"
)
SELLER_ANALYTICS_DOWNLOADS_ENDPOINT = (
    "https://seller-analytics-api.wildberries.ru/api/v2/nm-report/downloads"
)
SELLER_ANALYTICS_DOWNLOAD_FILE_ENDPOINT = (
    SELLER_ANALYTICS_DOWNLOADS_ENDPOINT + "/file/{download_id}"
)
STOCK_HISTORY_DAILY_REPORT_TYPE = "STOCK_HISTORY_DAILY_CSV"


@dataclass(frozen=True)
class WbStockExportResult:
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
    report_id: str = ""


class WbWarehouseRemainsClient:
    """Read-only client for WB warehouse remains report."""

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

    def __enter__(self) -> WbWarehouseRemainsClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def create_warehouse_remains_task(
        self,
        *,
        locale: str = "ru",
        group_by_brand: bool = False,
        group_by_subject: bool = False,
        group_by_sa: bool = True,
        group_by_nm: bool = True,
        group_by_barcode: bool = True,
        group_by_size: bool = True,
        filter_pics: int = 0,
        filter_volume: int = 0,
    ) -> tuple[str, int]:
        response = self._client.get(
            WAREHOUSE_REMAINS_ENDPOINT,
            params={
                "locale": locale,
                "groupByBrand": str(group_by_brand).lower(),
                "groupBySubject": str(group_by_subject).lower(),
                "groupBySa": str(group_by_sa).lower(),
                "groupByNm": str(group_by_nm).lower(),
                "groupByBarcode": str(group_by_barcode).lower(),
                "groupBySize": str(group_by_size).lower(),
                "filterPics": filter_pics,
                "filterVolume": filter_volume,
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB warehouse remains task payload")
        task_id = _text(_first(data.get("data") or {}, "taskId", "task_id", "id"))
        if not task_id:
            raise ValueError("WB warehouse remains response has no taskId")
        return task_id, response.status_code

    def fetch_warehouse_remains_status(self, task_id: str) -> tuple[str, int]:
        response = self._client.get(
            WAREHOUSE_REMAINS_STATUS_ENDPOINT.format(task_id=task_id)
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB warehouse remains status payload")
        status = _text(_first(data.get("data") or data, "status"))
        return status, response.status_code

    def download_warehouse_remains(
        self,
        task_id: str,
    ) -> tuple[list[dict[str, Any]], int]:
        response = self._client.get(
            WAREHOUSE_REMAINS_DOWNLOAD_ENDPOINT.format(task_id=task_id)
        )
        if response.status_code == 204:
            return [], response.status_code
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected WB warehouse remains download payload")
        return [item for item in data if isinstance(item, dict)], response.status_code

    def create_stock_history_daily_report(
        self,
        *,
        report_id: str,
        period_start: date,
        period_end: date,
        stock_type: str = "wb",
        timezone: str = "Europe/Moscow",
    ) -> int:
        response = self._client.post(
            SELLER_ANALYTICS_DOWNLOADS_ENDPOINT,
            json={
                "id": report_id,
                "reportType": STOCK_HISTORY_DAILY_REPORT_TYPE,
                "userReportName": (
                    "WB daily stock history "
                    f"{period_start.isoformat()} {period_end.isoformat()}"
                ),
                "params": {
                    "nmIDs": [],
                    "currentPeriod": {
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                    },
                    "stockType": stock_type,
                    "timezone": timezone,
                    "skipDeletedNm": False,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB stock history create payload")
        return response.status_code

    def fetch_download_status(self, report_id: str) -> tuple[str, int]:
        response = self._client.get(
            SELLER_ANALYTICS_DOWNLOADS_ENDPOINT,
            params={"filter[downloadIds]": report_id},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB stock history status payload")
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ValueError("Unexpected WB stock history status data")
        for row in rows:
            if isinstance(row, dict) and _text(row.get("id")) == report_id:
                return _text(row.get("status")), response.status_code
        return "", response.status_code

    def download_stock_history_daily_report(
        self,
        report_id: str,
    ) -> tuple[bytes, int]:
        response = self._client.get(
            SELLER_ANALYTICS_DOWNLOAD_FILE_ENDPOINT.format(download_id=report_id)
        )
        response.raise_for_status()
        return response.content, response.status_code


def export_wb_warehouse_remains(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    status_poll_seconds: float = 5.0,
    max_status_checks: int = 24,
    download_delay_seconds: float = 61.0,
    locale: str = "ru",
) -> list[WbStockExportResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbStockExportResult] = []
    for account in settings.accounts:
        with WbWarehouseRemainsClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            result = export_wb_warehouse_remains_for_account(
                client,
                account,
                output_dir,
                status_poll_seconds=status_poll_seconds,
                max_status_checks=max_status_checks,
                download_delay_seconds=download_delay_seconds,
                locale=locale,
            )
            results.append(result)
    _write_stock_manifest(
        output_dir / "manifest.json",
        results,
        locale=locale,
        params={
            "status_poll_seconds": status_poll_seconds,
            "max_status_checks": max_status_checks,
            "download_delay_seconds": download_delay_seconds,
            "group_by_sa": True,
            "group_by_nm": True,
            "group_by_barcode": True,
            "group_by_size": True,
        },
    )
    return results


def export_wb_warehouse_remains_for_account(
    client: WbWarehouseRemainsClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    status_poll_seconds: float = 5.0,
    max_status_checks: int = 24,
    download_delay_seconds: float = 61.0,
    locale: str = "ru",
) -> WbStockExportResult:
    try:
        task_id, status_code = client.create_warehouse_remains_task(locale=locale)
        status = ""
        for check_index in range(max_status_checks):
            if check_index > 0:
                time.sleep(status_poll_seconds)
            status, status_code = client.fetch_warehouse_remains_status(task_id)
            if status.lower() in {"done", "ready", "success", "completed"}:
                break
            if status.lower() in {"error", "failed", "canceled", "cancelled"}:
                return _stock_error_result(
                    account,
                    status="task_failed",
                    status_code=status_code,
                    error=f"task status={status}",
                    task_id=task_id,
                )
        else:
            return _stock_error_result(
                account,
                status="task_timeout",
                status_code=status_code,
                error=f"task status={status or 'unknown'}",
                task_id=task_id,
            )
        time.sleep(download_delay_seconds)
        rows, status_code = client.download_warehouse_remains(task_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return _stock_error_result(
            account,
            status=_status_from_http(status_code),
            status_code=status_code,
            error=f"HTTP {status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _stock_error_result(
            account,
            status="transport_or_schema_error",
            error=exc.__class__.__name__,
        )

    if status_code == 204:
        return WbStockExportResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            source="wb_warehouse_remains",
            ok=True,
            status="no_data",
            row_count=0,
            status_code=status_code,
            task_id=task_id,
        )

    payload_hash = raw_payload_hash(rows)
    output_path = (
        output_dir
        / f"{account.seller_account_id.lower()}_warehouse_remains.raw.json"
    )
    _write_json_list(output_path, rows)
    return WbStockExportResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        source="wb_warehouse_remains",
        ok=True,
        status="ok",
        row_count=len(rows),
        output_path=output_path,
        status_code=status_code,
        raw_payload_hash=payload_hash,
        task_id=task_id,
    )


def export_wb_stock_history_daily(
    settings: WbFinanceSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    stock_type: str = "wb",
    status_poll_seconds: float = 20.0,
    max_status_checks: int = 30,
    timezone: str = "Europe/Moscow",
) -> list[WbStockExportResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbStockExportResult] = []
    for account in settings.accounts:
        with WbWarehouseRemainsClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            result = export_wb_stock_history_daily_for_account(
                client,
                account,
                output_dir,
                period_start=period_start,
                period_end=period_end,
                stock_type=stock_type,
                status_poll_seconds=status_poll_seconds,
                max_status_checks=max_status_checks,
                timezone=timezone,
            )
            results.append(result)
    _write_stock_history_manifest(
        output_dir / "manifest.json",
        results,
        period_start=period_start,
        period_end=period_end,
        stock_type=stock_type,
        timezone=timezone,
        params={
            "status_poll_seconds": status_poll_seconds,
            "max_status_checks": max_status_checks,
        },
    )
    return results


def export_wb_stock_history_daily_for_account(
    client: WbWarehouseRemainsClient,
    account: WbFinanceSellerAccount,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    stock_type: str = "wb",
    status_poll_seconds: float = 20.0,
    max_status_checks: int = 30,
    timezone: str = "Europe/Moscow",
) -> WbStockExportResult:
    report_id = str(uuid4())
    try:
        status_code = client.create_stock_history_daily_report(
            report_id=report_id,
            period_start=period_start,
            period_end=period_end,
            stock_type=stock_type,
            timezone=timezone,
        )
        status = ""
        for check_index in range(max_status_checks):
            if check_index > 0:
                time.sleep(status_poll_seconds)
            status, status_code = client.fetch_download_status(report_id)
            normalized = status.lower()
            if normalized in {"success", "done", "ready", "completed"}:
                break
            if normalized in {"failed", "error", "canceled", "cancelled"}:
                return _stock_error_result(
                    account,
                    status="task_failed",
                    status_code=status_code,
                    error=f"task status={status}",
                    report_id=report_id,
                )
        else:
            return _stock_error_result(
                account,
                status="task_timeout",
                status_code=status_code,
                error=f"task status={status or 'unknown'}",
                report_id=report_id,
            )
        payload, status_code = client.download_stock_history_daily_report(report_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return _stock_error_result(
            account,
            status=_status_from_http(status_code),
            status_code=status_code,
            error=f"HTTP {status_code}",
            report_id=report_id,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return _stock_error_result(
            account,
            status="transport_or_schema_error",
            error=exc.__class__.__name__,
            report_id=report_id,
        )

    payload_hash = raw_payload_hash(payload.hex())
    output_path = output_dir / (
        f"{account.seller_account_id.lower()}_stock_history_daily"
        f"_{period_start.isoformat()}_{period_end.isoformat()}.zip"
    )
    output_path.write_bytes(payload)
    return WbStockExportResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        source="wb_stock_history_daily_csv",
        ok=True,
        status="ok",
        row_count=0,
        output_path=output_path,
        status_code=status_code,
        raw_payload_hash=payload_hash,
        report_id=report_id,
    )


def _stock_error_result(
    account: WbFinanceSellerAccount,
    *,
    status: str,
    status_code: int | None = None,
    error: str = "",
    task_id: str = "",
    report_id: str = "",
) -> WbStockExportResult:
    return WbStockExportResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        source="wb_warehouse_remains",
        ok=False,
        status=status,
        row_count=0,
        status_code=status_code,
        error=error,
        task_id=task_id,
        report_id=report_id,
    )


def _write_stock_manifest(
    path: Path,
    results: list[WbStockExportResult],
    *,
    locale: str,
    params: Mapping[str, Any],
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "wb_warehouse_remains",
        "endpoint": WAREHOUSE_REMAINS_ENDPOINT,
        "status_endpoint": WAREHOUSE_REMAINS_STATUS_ENDPOINT,
        "download_endpoint": WAREHOUSE_REMAINS_DOWNLOAD_ENDPOINT,
        "read_boundary": "read-only GET WB warehouse remains report",
        "snapshot_type": "current_stock_snapshot",
        "locale": locale,
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
                "report_id": item.report_id,
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def _write_stock_history_manifest(
    path: Path,
    results: list[WbStockExportResult],
    *,
    period_start: date,
    period_end: date,
    stock_type: str,
    timezone: str,
    params: Mapping[str, Any],
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "wb_stock_history_daily_csv",
        "endpoint": SELLER_ANALYTICS_DOWNLOADS_ENDPOINT,
        "download_endpoint": SELLER_ANALYTICS_DOWNLOAD_FILE_ENDPOINT,
        "read_boundary": "read-only POST/GET Seller Analytics CSV stock history",
        "snapshot_type": "historical_daily_stock_zip_csv",
        "report_type": STOCK_HISTORY_DAILY_REPORT_TYPE,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "stock_type": stock_type,
        "timezone": timezone,
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
                "report_id": item.report_id,
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
