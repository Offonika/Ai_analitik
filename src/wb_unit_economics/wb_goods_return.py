"""Read-only WB goods-return connector (return reasons, seller side).

Отдельный read-only источник причин возврата товара продавцу
(`GET analytics/goods-return`). Он описывает возврат/перемещение товара
продавцу и содержит `reason`, но это НЕ универсальная причина каждого
финансового возврата и НЕ комментарий покупателя (`claims.user_comment`) —
источники раздельны и не сливаются (см. draft-спек
`docs/specs/wb-logistics-return-reasons-implementation.md`).

Коннектор только читает (`GET`, окно до 31 дня, лимит 1 запрос/мин) и
нормализует строки в плоский слой со связью по `srid`/заказу. Пропущенные поля
остаются `None` — отсутствие причины остаётся явным, а не подменяется пустой
строкой или гипотезой. Сумма и факт возврата берутся из Finance (первая
очередь), здесь не считаются.
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

GOODS_RETURN_ENDPOINT = (
    "https://seller-analytics-api.wildberries.ru/api/v1/analytics/goods-return"
)
MAX_WINDOW_DAYS = 31

__all__ = [
    "GOODS_RETURN_ENDPOINT",
    "MAX_WINDOW_DAYS",
    "WbGoodsReturnClient",
    "flatten_goods_return",
    "raw_payload_hash",
]


@dataclass(frozen=True)
class WbGoodsReturnClient:
    """Read-only client for WB goods-return analytics report."""

    api_key: str
    timeout_seconds: float = 30.0
    _transport: httpx.BaseTransport | None = None

    def fetch_goods_return(
        self, date_from: date, date_to: date
    ) -> dict[str, Any]:
        if (date_to - date_from).days > MAX_WINDOW_DAYS:
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
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB goods-return payload")
        return data


def _report_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Найти список строк отчёта независимо от обёртки (`report`/`data`)."""
    for candidate in (
        payload.get("report"),
        payload.get("data"),
        payload.get("goodsReturns"),
    ):
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []


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
    row_count: int = 0
    raw_output_path: Path | None = None
    flat_output_path: Path | None = None
    raw_payload_hash: str = ""
    error: str = ""


def export_wb_goods_return(
    client: WbGoodsReturnClient,
    output_dir: Path,
    *,
    date_from: date,
    date_to: date,
) -> WbGoodsReturnExportResult:
    """Read-only снимок причин возврата за окно до 31 дня: raw + flat."""
    try:
        payload = client.fetch_goods_return(date_from, date_to)
    except (httpx.HTTPError, ValueError) as exc:
        return WbGoodsReturnExportResult(ok=False, error=exc.__class__.__name__)
    rows = flatten_goods_return(payload)
    stamp = f"{date_from.isoformat()}_{date_to.isoformat()}"
    raw_path = output_dir / f"wb_goods_return_{stamp}.raw.json"
    flat_path = output_dir / f"wb_goods_return_{stamp}.flat.json"
    _write_json(raw_path, payload)
    _write_json(flat_path, rows)
    return WbGoodsReturnExportResult(
        ok=True,
        row_count=len(rows),
        raw_output_path=raw_path,
        flat_output_path=flat_path,
        raw_payload_hash=raw_payload_hash(payload),
    )
