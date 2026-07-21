"""Read-only WB Analytics measurements and dimension-retention connector (F-4).

The connector reads only the official ``measurement-penalties`` and
``warehouse-measurements`` reports. Raw payloads retain provider evidence;
flat rows deliberately omit ``photoUrls`` and ``subjectName``. Missing values
remain missing and are normalized by the deterministic mart layer.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from wb_unit_economics.wb_finance import raw_payload_hash

MEASUREMENT_PENALTIES_ENDPOINT = (
    "https://seller-analytics-api.wildberries.ru/api/analytics/v1/"
    "measurement-penalties"
)
WAREHOUSE_MEASUREMENTS_ENDPOINT = (
    "https://seller-analytics-api.wildberries.ru/api/analytics/v1/"
    "warehouse-measurements"
)
MEASUREMENT_PAGE_LIMIT = 1000
MEASUREMENT_PAGE_DELAY_SECONDS = 60.0

__all__ = [
    "MEASUREMENT_PENALTIES_ENDPOINT",
    "WAREHOUSE_MEASUREMENTS_ENDPOINT",
    "WbMeasurementExportResult",
    "WbMeasurementsClient",
    "export_wb_measurement_penalties",
    "export_wb_warehouse_measurements",
    "flatten_measurement_penalties",
    "flatten_warehouse_measurements",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("WB measurements timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WbMeasurementPayload:
    rows: list[dict[str, Any]]
    provider_total: int


@dataclass(frozen=True)
class WbMeasurementsClient:
    api_key: str
    timeout_seconds: float = 60.0
    page_limit: int = MEASUREMENT_PAGE_LIMIT
    page_delay_seconds: float = MEASUREMENT_PAGE_DELAY_SECONDS
    _transport: httpx.BaseTransport | None = None
    _sleep: Callable[[float], None] = time.sleep

    def _fetch_all(
        self,
        endpoint: str,
        *,
        date_from: datetime,
        date_to: datetime,
    ) -> WbMeasurementPayload:
        if self.page_limit < 1 or self.page_limit > MEASUREMENT_PAGE_LIMIT:
            raise ValueError("WB measurements page limit must be between 1 and 1000")
        rows: list[dict[str, Any]] = []
        expected_total: int | None = None
        offset = 0
        with httpx.Client(
            headers={"Authorization": self.api_key, "Accept": "application/json"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            while True:
                response = client.get(
                    endpoint,
                    params={
                        "dateFrom": _timestamp(date_from),
                        "dateTo": _timestamp(date_to),
                        "limit": self.page_limit,
                        "offset": offset,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                page, provider_total = _measurement_page(payload)
                if expected_total is None:
                    expected_total = provider_total
                elif provider_total != expected_total:
                    raise ValueError(
                        "WB measurements provider total changed during paging"
                    )
                if not page:
                    if len(rows) != provider_total:
                        raise ValueError(
                            "WB measurements pagination ended before provider total"
                        )
                    break
                rows.extend(page)
                if len(rows) > provider_total:
                    raise ValueError("WB measurements rows exceed provider total")
                if len(rows) == provider_total:
                    break
                offset += len(page)
                self._sleep(self.page_delay_seconds)
        return WbMeasurementPayload(
            rows=rows,
            provider_total=expected_total if expected_total is not None else 0,
        )

    def fetch_measurement_penalties(
        self, *, date_from: datetime, date_to: datetime
    ) -> WbMeasurementPayload:
        return self._fetch_all(
            MEASUREMENT_PENALTIES_ENDPOINT,
            date_from=date_from,
            date_to=date_to,
        )

    def fetch_warehouse_measurements(
        self, *, date_from: datetime, date_to: datetime
    ) -> WbMeasurementPayload:
        return self._fetch_all(
            WAREHOUSE_MEASUREMENTS_ENDPOINT,
            date_from=date_from,
            date_to=date_to,
        )


def _measurement_page(payload: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("Unexpected WB measurements payload")
    reports = payload["data"].get("reports")
    total = payload["data"].get("total")
    if (
        not isinstance(reports, list)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
    ):
        raise ValueError("Unexpected WB measurements envelope")
    if any(not isinstance(row, dict) for row in reports):
        raise ValueError("Unexpected WB measurements row")
    return list(reports), total


def flatten_measurement_penalties(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "nm_id": row.get("nmId"),
            "dim_id": row.get("dimId"),
            "prc_over": row.get("prcOver"),
            "volume": row.get("volume"),
            "width": row.get("width"),
            "length": row.get("length"),
            "height": row.get("height"),
            "volume_sup": row.get("volumeSup"),
            "width_sup": row.get("widthSup"),
            "length_sup": row.get("lengthSup"),
            "height_sup": row.get("heightSup"),
            "dt_bonus": row.get("dtBonus"),
            "is_valid": row.get("isValid"),
            "is_valid_dt": row.get("isValidDt"),
            "penalty_amount": row.get("penaltyAmount"),
            "reversal_amount": row.get("reversalAmount"),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def flatten_warehouse_measurements(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "nm_id": row.get("nmId"),
            "dim_id": row.get("dimId"),
            "volume": row.get("volume"),
            "width": row.get("width"),
            "length": row.get("length"),
            "height": row.get("height"),
            "dt": row.get("dt"),
        }
        for row in rows
        if isinstance(row, dict)
    ]


@dataclass(frozen=True)
class WbMeasurementExportResult:
    ok: bool
    source_type: str
    seller_account_id: str = ""
    account_name: str = ""
    row_count: int = 0
    provider_total: int | None = None
    raw_output_path: Path | None = None
    flat_output_path: Path | None = None
    raw_payload_hash: str = ""
    flat_payload_hash: str = ""
    status_code: int | None = None
    error: str = ""


def _export_measurements(
    *,
    client: WbMeasurementsClient,
    output_dir: Path,
    source_type: str,
    date_from: datetime,
    date_to: datetime,
    seller_account_id: str,
    account_name: str,
    file_prefix: str,
) -> WbMeasurementExportResult:
    fetch = (
        client.fetch_measurement_penalties
        if source_type == "wb_measurement_penalties"
        else client.fetch_warehouse_measurements
    )
    flatten = (
        flatten_measurement_penalties
        if source_type == "wb_measurement_penalties"
        else flatten_warehouse_measurements
    )
    try:
        payload = fetch(date_from=date_from, date_to=date_to)
    except httpx.HTTPStatusError as exc:
        return WbMeasurementExportResult(
            ok=False,
            source_type=source_type,
            seller_account_id=seller_account_id,
            account_name=account_name,
            status_code=exc.response.status_code,
            error=exc.__class__.__name__,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return WbMeasurementExportResult(
            ok=False,
            source_type=source_type,
            seller_account_id=seller_account_id,
            account_name=account_name,
            error=exc.__class__.__name__,
        )
    raw = {
        "dateFrom": _timestamp(date_from),
        "dateTo": _timestamp(date_to),
        "reports": payload.rows,
        "total": payload.provider_total,
    }
    flat = flatten(payload.rows)
    prefix = f"{file_prefix}_" if file_prefix else ""
    stem = source_type.removeprefix("wb_")
    raw_path = output_dir / f"{prefix}{stem}.raw.json"
    flat_path = output_dir / f"{prefix}{stem}.flat.json"
    _write_json(raw_path, raw)
    _write_json(flat_path, flat)
    return WbMeasurementExportResult(
        ok=True,
        source_type=source_type,
        seller_account_id=seller_account_id,
        account_name=account_name,
        row_count=len(flat),
        provider_total=payload.provider_total,
        raw_output_path=raw_path,
        flat_output_path=flat_path,
        raw_payload_hash=raw_payload_hash(raw),
        flat_payload_hash=raw_payload_hash(flat),
        status_code=200,
    )


def export_wb_measurement_penalties(
    client: WbMeasurementsClient,
    output_dir: Path,
    *,
    date_from: datetime,
    date_to: datetime,
    seller_account_id: str = "",
    account_name: str = "",
    file_prefix: str = "",
) -> WbMeasurementExportResult:
    return _export_measurements(
        client=client,
        output_dir=output_dir,
        source_type="wb_measurement_penalties",
        date_from=date_from,
        date_to=date_to,
        seller_account_id=seller_account_id,
        account_name=account_name,
        file_prefix=file_prefix,
    )


def export_wb_warehouse_measurements(
    client: WbMeasurementsClient,
    output_dir: Path,
    *,
    date_from: datetime,
    date_to: datetime,
    seller_account_id: str = "",
    account_name: str = "",
    file_prefix: str = "",
) -> WbMeasurementExportResult:
    return _export_measurements(
        client=client,
        output_dir=output_dir,
        source_type="wb_warehouse_measurements",
        date_from=date_from,
        date_to=date_to,
        seller_account_id=seller_account_id,
        account_name=account_name,
        file_prefix=file_prefix,
    )
