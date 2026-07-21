"""Read-only WB tariffs connector (box/pallet) for logistics factors (F-2).

Тарифы WB отдаются по складам с периодом действия (`dtNextBox`/`dtTillMax`).
Коннектор только читает (`GET`) и нормализует ответ в плоские строки: склад,
коэффициенты доставки/хранения и границы периода. Пропущенные поля остаются
`None` — пустой тариф это явный признак недоступности, а не ноль. Денежные
значения сохраняются как факт исходной строки без приведения типов; десятичная
нормализация выполняется отдельным расчётным слоем.

Официальные периоды действия (`dtNextBox`/`dtNextPallet`/`dtTillMax`) позволяют
объяснять только тот период, к которому относится тариф; исторический расход
нельзя объяснять текущим тарифом (см. draft-спек второй очереди
`docs/specs/wb-logistics-cost-factors-implementation.md`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from wb_unit_economics.wb_finance import raw_payload_hash

TARIFFS_BOX_ENDPOINT = "https://common-api.wildberries.ru/api/v1/tariffs/box"
TARIFFS_PALLET_ENDPOINT = "https://common-api.wildberries.ru/api/v1/tariffs/pallet"

__all__ = [
    "TARIFFS_BOX_ENDPOINT",
    "TARIFFS_PALLET_ENDPOINT",
    "WbTariffsClient",
    "WbTariffsExportResult",
    "build_tariff_snapshot_dates",
    "export_wb_tariffs",
    "flatten_box_tariffs",
    "flatten_pallet_tariffs",
    "raw_payload_hash",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class WbTariffsClient:
    """Read-only client for WB box/pallet tariffs.

    Тариф запрашивается на конкретную дату; WB отдаёт действующие и архивные
    ставки. Клиент не выполняет write-операций.
    """

    api_key: str
    timeout_seconds: float = 30.0
    _transport: httpx.BaseTransport | None = None

    def _get(self, url: str, target_date: date) -> dict[str, Any]:
        with httpx.Client(
            headers={"Authorization": self.api_key, "Accept": "application/json"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = client.get(url, params={"date": target_date.isoformat()})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB tariffs payload")
        return data

    def fetch_box_tariffs(self, target_date: date) -> dict[str, Any]:
        return self._get(TARIFFS_BOX_ENDPOINT, target_date)

    def fetch_pallet_tariffs(self, target_date: date) -> dict[str, Any]:
        return self._get(TARIFFS_PALLET_ENDPOINT, target_date)


def _tariffs_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Найти блок `data` c периодом и `warehouseList` независимо от вложенности."""
    for candidate in (
        payload.get("response", {}).get("data")
        if isinstance(payload.get("response"), dict)
        else None,
        payload.get("data"),
        payload,
    ):
        if isinstance(candidate, dict) and isinstance(
            candidate.get("warehouseList"), list
        ):
            return candidate
    return {}


def _warehouses(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("warehouseList")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def flatten_box_tariffs(
    payload: dict[str, Any], requested_date: date
) -> list[dict[str, Any]]:
    """Плоские строки box-тарифа по складам с периодом действия."""
    data = _tariffs_data(payload)
    dt_next = data.get("dtNextBox")
    dt_till_max = data.get("dtTillMax")
    rows: list[dict[str, Any]] = []
    for warehouse in _warehouses(data):
        rows.append(
            {
                "requested_date": requested_date.isoformat(),
                "warehouse_name": warehouse.get("warehouseName"),
                "dt_next_box": dt_next,
                "dt_till_max": dt_till_max,
                "box_delivery_base": warehouse.get("boxDeliveryBase"),
                "box_delivery_liter": warehouse.get("boxDeliveryLiter"),
                "box_delivery_coef_expr": warehouse.get("boxDeliveryCoefExpr"),
                "box_delivery_marketplace_base": warehouse.get(
                    "boxDeliveryMarketplaceBase"
                ),
                "box_delivery_marketplace_liter": warehouse.get(
                    "boxDeliveryMarketplaceLiter"
                ),
                "box_delivery_marketplace_coef_expr": warehouse.get(
                    "boxDeliveryMarketplaceCoefExpr"
                ),
                "box_storage_base": warehouse.get("boxStorageBase"),
                "box_storage_liter": warehouse.get("boxStorageLiter"),
                "box_storage_coef_expr": warehouse.get("boxStorageCoefExpr"),
                "geo_name": warehouse.get("geoName"),
            }
        )
    return rows


def flatten_pallet_tariffs(
    payload: dict[str, Any], requested_date: date
) -> list[dict[str, Any]]:
    """Плоские строки pallet-тарифа по складам с периодом действия."""
    data = _tariffs_data(payload)
    dt_next = data.get("dtNextPallet")
    dt_till_max = data.get("dtTillMax")
    rows: list[dict[str, Any]] = []
    for warehouse in _warehouses(data):
        rows.append(
            {
                "requested_date": requested_date.isoformat(),
                "warehouse_name": warehouse.get("warehouseName"),
                "dt_next_pallet": dt_next,
                "dt_till_max": dt_till_max,
                "pallet_delivery_expr": warehouse.get("palletDeliveryExpr"),
                "pallet_delivery_value_base": warehouse.get(
                    "palletDeliveryValueBase"
                ),
                "pallet_delivery_value_liter": warehouse.get(
                    "palletDeliveryValueLiter"
                ),
                "pallet_storage_expr": warehouse.get("palletStorageExpr"),
                "pallet_storage_value_expr": warehouse.get(
                    "palletStorageValueExpr"
                ),
            }
        )
    return rows


@dataclass(frozen=True)
class WbTariffsExportResult:
    ok: bool
    seller_account_id: str = ""
    target_date: date | None = None
    box_row_count: int = 0
    pallet_row_count: int = 0
    raw_output_path: Path | None = None
    flat_output_path: Path | None = None
    raw_payload_hash: str = ""
    flat_payload_hash: str = ""
    status_code: int | None = None
    error: str = ""


def build_tariff_snapshot_dates(
    period_start: date,
    period_end: date,
    *,
    factor_snapshot_date: date,
) -> tuple[date, ...]:
    """Return calendar-week starts plus the explicit current snapshot date."""

    if period_end < period_start:
        raise ValueError("period_end must not be before period_start")
    current = period_start - timedelta(days=period_start.weekday())
    values: set[date] = {factor_snapshot_date}
    while current <= period_end:
        values.add(current)
        current += timedelta(days=7)
    return tuple(sorted(values))


def export_wb_tariffs(
    client: WbTariffsClient,
    output_dir: Path,
    *,
    target_date: date,
    seller_account_id: str = "",
    file_prefix: str = "",
) -> WbTariffsExportResult:
    """Read-only снимок тарифов box/pallet: raw + flat в ``output_dir``."""
    try:
        box_payload = client.fetch_box_tariffs(target_date)
        pallet_payload = client.fetch_pallet_tariffs(target_date)
    except (httpx.HTTPError, ValueError) as exc:
        status_code = (
            exc.response.status_code
            if isinstance(exc, httpx.HTTPStatusError)
            else None
        )
        return WbTariffsExportResult(
            ok=False,
            seller_account_id=seller_account_id,
            target_date=target_date,
            status_code=status_code,
            error=exc.__class__.__name__,
        )
    box_rows = flatten_box_tariffs(box_payload, target_date)
    pallet_rows = flatten_pallet_tariffs(pallet_payload, target_date)
    raw = {
        "date": target_date.isoformat(),
        "box": box_payload,
        "pallet": pallet_payload,
    }
    flat = {"box": box_rows, "pallet": pallet_rows}
    prefix = f"{file_prefix}_" if file_prefix else ""
    raw_path = output_dir / (
        f"{prefix}wb_tariffs_{target_date.isoformat()}.raw.json"
    )
    flat_path = output_dir / (
        f"{prefix}wb_tariffs_{target_date.isoformat()}.flat.json"
    )
    _write_json(raw_path, raw)
    _write_json(flat_path, flat)
    return WbTariffsExportResult(
        ok=True,
        seller_account_id=seller_account_id,
        target_date=target_date,
        box_row_count=len(box_rows),
        pallet_row_count=len(pallet_rows),
        raw_output_path=raw_path,
        flat_output_path=flat_path,
        raw_payload_hash=raw_payload_hash(raw),
        flat_payload_hash=raw_payload_hash(flat),
        status_code=200,
    )
