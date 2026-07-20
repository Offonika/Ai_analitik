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

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from wb_unit_economics.wb_finance import raw_payload_hash

TARIFFS_BOX_ENDPOINT = "https://common-api.wildberries.ru/api/v1/tariffs/box"
TARIFFS_PALLET_ENDPOINT = "https://common-api.wildberries.ru/api/v1/tariffs/pallet"

__all__ = [
    "TARIFFS_BOX_ENDPOINT",
    "TARIFFS_PALLET_ENDPOINT",
    "WbTariffsClient",
    "flatten_box_tariffs",
    "flatten_pallet_tariffs",
    "raw_payload_hash",
]


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
                "box_storage_base": warehouse.get("boxStorageBase"),
                "box_storage_liter": warehouse.get("boxStorageLiter"),
                "box_storage_coef_expr": warehouse.get("boxStorageCoefExpr"),
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
                "pallet_storage_expr": warehouse.get("palletStorageExpr"),
                "pallet_storage_value_expr": warehouse.get(
                    "palletStorageValueExpr"
                ),
            }
        )
    return rows
