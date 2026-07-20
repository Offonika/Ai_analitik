#!/usr/bin/env python3
"""Read-only availability probe for WB logistics factor sources (F-0).

Проверяет доступность внешних WB read-only источников второй/третьей очереди
логистики (тарифы, статистика склад/направление, причины возвратов) для
конкретного tenant. Ключ WB берётся ТЕМ ЖЕ путём, что и source refresh: из
`tenant_integrations` в БД, расшифровкой `integrations.decrypt_secret`.

Безопасность: скрипт печатает ТОЛЬКО агрегаты — HTTP-статус, наличие полей по
именам, длину списков. Он НИКОГДА не печатает ключ, database URL, сырые строки,
значения полей или персональные данные покупателя (`user_comment`). Только
read-only GET. Запускать на сервере через окружение сервиса, например:

    systemd-run --wait --collect --pipe \\
      --property=WorkingDirectory=/opt/shumeyko-partners-wb-unit-economics \\
      --property=EnvironmentFile=/etc/shumeiko-web-prod.env \\
      --property=Environment=PYTHONPATH=/opt/shumeyko-partners-wb-unit-economics/src \\
      /opt/shumeyko-partners-wb-unit-economics/.venv/bin/python \\
      scripts/probe_wb_logistics_factors.py

Результат — обезличенная матрица доступности для draft-спека
`docs/specs/wb-logistics-cost-factors-implementation.md` и runbook
`docs/runbooks/wb-logistics-factors-probe.md`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
from sqlalchemy import select

from wb_unit_economics.web import integrations
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import TenantIntegration
from wb_unit_economics.web.settings import WebSettings

TIMEOUT = 30.0


def endpoints(today: date) -> list[tuple[str, str, dict, str]]:
    week_ago = (today - timedelta(days=7)).isoformat()
    today_str = today.isoformat()
    return [
        ("tariffs_box", "https://common-api.wildberries.ru/api/v1/tariffs/box",
         {"date": today_str}, "Тарифы"),
        ("tariffs_pallet",
         "https://common-api.wildberries.ru/api/v1/tariffs/pallet",
         {"date": today_str}, "Тарифы"),
        ("statistics_sales",
         "https://statistics-api.wildberries.ru/api/v1/supplier/sales",
         {"dateFrom": week_ago}, "Статистика"),
        ("goods_return",
         "https://seller-analytics-api.wildberries.ru/api/v1/analytics/goods-return",
         {"dateFrom": week_ago, "dateTo": today_str}, "Аналитика"),
        ("claims", "https://returns-api.wildberries.ru/api/v1/claims",
         {"is_archive": "false"}, "Возвраты покупателями"),
    ]


INTEREST = {
    "tariffs_box": ["dtNextBox", "dtTillMax", "boxDeliveryBase",
                    "boxDeliveryCoefExpr", "warehouseName"],
    "tariffs_pallet": ["dtNextPallet", "dtTillMax", "palletDeliveryExpr",
                       "warehouseName"],
    "statistics_sales": ["warehouseName", "countryName", "oblastOkrugName",
                         "regionName", "srid"],
    "goods_return": ["reason", "status", "returnType", "srid", "nmId"],
    "claims": ["id", "claim_type", "status", "nm_id", "user_comment", "srid", "dt"],
}


def collect_key_names(obj, acc: set[str]) -> None:
    """Рекурсивно собрать ИМЕНА ключей (не значения) по всему ответу."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            acc.add(key)
            collect_key_names(value, acc)
    elif isinstance(obj, list):
        for item in obj[:50]:
            collect_key_names(item, acc)


def max_list_len(obj) -> int | None:
    """Длина самого большого списка в ответе (для оценки объёма выборки)."""
    best: int | None = None
    if isinstance(obj, list):
        best = len(obj)
        for item in obj[:50]:
            sub = max_list_len(item)
            if sub is not None and (best is None or sub > best):
                best = sub
    elif isinstance(obj, dict):
        for value in obj.values():
            sub = max_list_len(value)
            if sub is not None and (best is None or sub > best):
                best = sub
    return best


def summarize(name: str, data) -> dict:
    """Только агрегаты: тип, размер, наличие интересующих полей по именам."""
    keys: set[str] = set()
    collect_key_names(data, keys)
    fields = INTEREST.get(name, [])
    return {
        "kind": type(data).__name__,
        "max_list_len": max_list_len(data),
        "fields_present_anywhere": {field: (field in keys) for field in fields},
    }


def load_wb_key(settings: WebSettings) -> tuple[str, str, list[dict]]:
    """Ключ WB из tenant_integrations тем же путём, что и приложение."""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        rows = list(db.scalars(
            select(TenantIntegration)
            .where(TenantIntegration.tenant_id == settings.source_refresh_tenant)
        ))
    wb = [r for r in rows if str(r.provider).split(":", 1)[0] == "wb_api"]
    wb.sort(key=lambda r: (":" in str(r.provider), str(r.provider)))
    diag: list[dict] = []
    chosen_key = ""
    chosen_provider = ""
    for integ in wb:
        payload = integ.config_payload or {}
        item = {
            "provider": str(integ.provider),
            "status": str(integ.status),
            "storage": str(payload.get("storage") or ""),
            "usable": False,
        }
        try:
            secret = integrations.decrypt_secret(settings, payload)
            if secret:
                item["usable"] = True
                if not chosen_key:
                    chosen_key = secret
                    chosen_provider = str(integ.provider)
        except integrations.IntegrationSecretError as exc:
            item["decrypt_error"] = str(exc)
        diag.append(item)
    return chosen_key, chosen_provider, diag


def run_probe(api_key: str, today: date) -> dict:
    results: dict = {}
    headers = {"Authorization": api_key, "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as c:
        for name, url, params, scope in endpoints(today):
            entry: dict = {"scope": scope}
            try:
                resp = c.get(url, params=params)
                entry["http_status"] = resp.status_code
                if resp.status_code == 200:
                    try:
                        entry["summary"] = summarize(name, resp.json())
                    except Exception as exc:  # noqa: BLE001
                        entry["parse_error"] = exc.__class__.__name__
                else:
                    entry["note"] = "non_200"
            except httpx.HTTPError as exc:
                entry["error"] = exc.__class__.__name__
            results[name] = entry
    return results


def main() -> None:
    settings = WebSettings()
    today = date.today()
    report: dict = {"tenant": settings.source_refresh_tenant}
    api_key, provider, diag = load_wb_key(settings)
    report["wb_integrations"] = diag
    report["wb_integration_found"] = bool(api_key)
    report["wb_provider"] = provider
    report["results"] = run_probe(api_key, today) if api_key else {}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
