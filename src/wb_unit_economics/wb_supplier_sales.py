"""Read-only WB supplier/sales connector: склад отгрузки и направление (F-3).

Отчёт продаж WB (`GET statistics-api /api/v1/supplier/sales`) содержит на уровне
продажи склад отгрузки (`warehouseName`) и направление доставки
(`countryName`/`oblastOkrugName`/`regionName`) со связкой по `srid`/заказу. Это
источник склад/маршруты второй очереди (F-3).

Коннектор только читает (`GET`, отбор по `dateFrom`, хранение WB ~90 дней) и
нормализует строки в плоский слой. Пропущенные поля остаются `None` — отсутствие
склада или направления остаётся явным, а не подменяется пустым значением.
Направление не выводится как факт при отсутствии поля (см. draft-спек
`docs/specs/wb-logistics-cost-factors-implementation.md`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from wb_unit_economics.wb_finance import raw_payload_hash


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

SUPPLIER_SALES_ENDPOINT = (
    "https://statistics-api.wildberries.ru/api/v1/supplier/sales"
)

__all__ = [
    "SUPPLIER_SALES_ENDPOINT",
    "WbSupplierSalesClient",
    "flatten_supplier_sales",
    "raw_payload_hash",
]


@dataclass(frozen=True)
class WbSupplierSalesClient:
    """Read-only client for WB supplier sales report (warehouse + direction)."""

    api_key: str
    timeout_seconds: float = 60.0
    _transport: httpx.BaseTransport | None = None

    def fetch_supplier_sales(
        self, date_from: date, *, flag: int = 0
    ) -> list[dict[str, Any]]:
        with httpx.Client(
            headers={"Authorization": self.api_key, "Accept": "application/json"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = client.get(
                SUPPLIER_SALES_ENDPOINT,
                params={"dateFrom": date_from.isoformat(), "flag": flag},
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected WB supplier sales payload")
        return [row for row in data if isinstance(row, dict)]


def flatten_supplier_sales(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Плоские строки продаж со складом и направлением; `None` без подстановки."""
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "srid": row.get("srid"),
                "g_number": row.get("gNumber"),
                "sale_id": row.get("saleID"),
                "nm_id": row.get("nmId"),
                "barcode": row.get("barcode"),
                "sale_date": row.get("date"),
                "last_change_date": row.get("lastChangeDate"),
                "warehouse_name": row.get("warehouseName"),
                "country_name": row.get("countryName"),
                "oblast_okrug_name": row.get("oblastOkrugName"),
                "region_name": row.get("regionName"),
            }
        )
    return result


@dataclass(frozen=True)
class WbSupplierSalesExportResult:
    ok: bool
    row_count: int = 0
    raw_output_path: Path | None = None
    flat_output_path: Path | None = None
    raw_payload_hash: str = ""
    error: str = ""


def export_wb_supplier_sales(
    client: WbSupplierSalesClient,
    output_dir: Path,
    *,
    date_from: date,
) -> WbSupplierSalesExportResult:
    """Read-only снимок продаж со складом/направлением: raw + flat."""
    try:
        raw_rows = client.fetch_supplier_sales(date_from)
    except (httpx.HTTPError, ValueError) as exc:
        return WbSupplierSalesExportResult(ok=False, error=exc.__class__.__name__)
    rows = flatten_supplier_sales(raw_rows)
    stamp = date_from.isoformat()
    raw_path = output_dir / f"wb_supplier_sales_{stamp}.raw.json"
    flat_path = output_dir / f"wb_supplier_sales_{stamp}.flat.json"
    _write_json(raw_path, raw_rows)
    _write_json(flat_path, rows)
    return WbSupplierSalesExportResult(
        ok=True,
        row_count=len(rows),
        raw_output_path=raw_path,
        flat_output_path=flat_path,
        raw_payload_hash=raw_payload_hash(raw_rows),
    )
