#!/usr/bin/env python3
"""Read-only availability probe for WB logistics factor sources (F-0/F-4).

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

Режим ``--mode f4`` строже legacy F-0: он не печатает provider labels,
количество интеграций/строк, HTTP body, идентификаторы, суммы или значения
полей. В выводе остаются только булевы признаки доступности и schema gate.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, Protocol

import httpx
from sqlalchemy import select

from wb_unit_economics.web import integrations
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import TenantIntegration
from wb_unit_economics.web.settings import WebSettings

TIMEOUT = 30.0
MOSCOW = timezone(timedelta(hours=3))

F4_REQUIRED_FIELDS = {
    "measurement_penalties": {
        "nmId",
        "dimId",
        "prcOver",
        "volume",
        "width",
        "length",
        "height",
        "volumeSup",
        "widthSup",
        "lengthSup",
        "heightSup",
        "dtBonus",
        "isValid",
        "isValidDt",
        "penaltyAmount",
        "reversalAmount",
    },
    "warehouse_measurements": {
        "nmId",
        "dimId",
        "volume",
        "width",
        "length",
        "height",
        "dt",
    },
}


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any: ...


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


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def f4_endpoints(today: date, *, days: int = 31) -> list[tuple[str, str, dict]]:
    """Минимальные read-only запросы F-4 без публикации клиентского периода."""
    if days < 1 or days > 366:
        raise ValueError("F-4 probe days must be between 1 and 366")
    start_local = datetime.combine(
        today - timedelta(days=days - 1), time.min, tzinfo=MOSCOW
    )
    end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=MOSCOW)
    params = {
        "dateFrom": _utc_timestamp(start_local),
        "dateTo": _utc_timestamp(end_local - timedelta(microseconds=1)),
        "limit": 1,
        "offset": 0,
    }
    root = "https://seller-analytics-api.wildberries.ru/api/analytics/v1"
    return [
        (
            "measurement_penalties",
            f"{root}/measurement-penalties",
            dict(params),
        ),
        (
            "warehouse_measurements",
            f"{root}/warehouse-measurements",
            dict(params),
        ),
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


def load_f4_wb_keys(settings: WebSettings) -> tuple[list[str], bool]:
    """Вернуть usable check_ok keys; наружу не отдавать labels или count."""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        rows = list(
            db.scalars(
                select(TenantIntegration).where(
                    TenantIntegration.tenant_id == settings.source_refresh_tenant
                )
            )
        )
    candidates = [
        row
        for row in rows
        if str(row.provider).split(":", 1)[0] == "wb_api"
        and str(row.status) == "check_ok"
    ]
    keys: list[str] = []
    incomplete = False
    for integration in candidates:
        try:
            secret = integrations.decrypt_secret(
                settings, integration.config_payload or {}
            )
        except integrations.IntegrationSecretError:
            incomplete = True
            continue
        if secret and secret not in keys:
            keys.append(secret)
        elif not secret:
            incomplete = True
    return keys, incomplete


def classify_f4_response(name: str, response: ResponseLike) -> str:
    """Классифицировать ответ, не возвращая payload values или row count."""
    if response.status_code in {401, 403}:
        return "access_denied"
    if response.status_code == 429 or response.status_code >= 500:
        return "unavailable"
    if response.status_code != 200:
        return "schema_mismatch"
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return "schema_mismatch"
    if not isinstance(payload, dict):
        return "schema_mismatch"
    data = payload.get("data")
    if not isinstance(data, dict):
        return "schema_mismatch"
    reports = data.get("reports")
    total = data.get("total")
    if (
        not isinstance(reports, list)
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
    ):
        return "schema_mismatch"
    if not reports:
        return "confirmed_empty" if total == 0 else "schema_mismatch"
    first = reports[0]
    if (
        total < 1
        or not isinstance(first, dict)
        or not F4_REQUIRED_FIELDS[name].issubset(first)
    ):
        return "schema_mismatch"
    return "confirmed_nonempty"


def aggregate_f4_statuses(statuses: dict[str, list[str]]) -> dict:
    """Свести кабинетные статусы к безопасным booleans без cardinality."""
    endpoints_report: dict[str, dict[str, bool]] = {}
    gate = True
    for name in F4_REQUIRED_FIELDS:
        values = statuses.get(name, [])
        entry = {
            "schemaConfirmedAny": any(
                value.startswith("confirmed_") for value in values
            ),
            "confirmedEmptyPresent": "confirmed_empty" in values,
            "confirmedNonemptyPresent": "confirmed_nonempty" in values,
            "accessDeniedPresent": "access_denied" in values,
            "unavailablePresent": "unavailable" in values,
            "schemaMismatchPresent": "schema_mismatch" in values,
        }
        gate = (
            gate
            and entry["schemaConfirmedAny"]
            and not entry["schemaMismatchPresent"]
        )
        endpoints_report[name] = entry
    return {"endpoints": endpoints_report, "implementationGate": gate}


def run_f4_probe(api_keys: list[str], today: date, *, days: int = 31) -> dict:
    statuses = {name: [] for name in F4_REQUIRED_FIELDS}
    for api_key in api_keys:
        headers = {"Authorization": api_key, "Accept": "application/json"}
        with httpx.Client(
            headers=headers, timeout=TIMEOUT, follow_redirects=True
        ) as client:
            for name, url, params in f4_endpoints(today, days=days):
                try:
                    response = client.get(url, params=params)
                    status = classify_f4_response(name, response)
                except httpx.HTTPError:
                    status = "unavailable"
                statuses[name].append(status)
    return aggregate_f4_statuses(statuses)


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("legacy", "f4"),
        default="legacy",
        help="legacy F-0 matrix or privacy-restricted F-4 source gate",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=31,
        help="F-4 calendar window length (1..366, default: 31)",
    )
    args = parser.parse_args(argv)
    if args.days < 1 or args.days > 366:
        parser.error("--days must be between 1 and 366")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = WebSettings()
    today = date.today()
    if args.mode == "f4":
        api_keys, integration_access_incomplete = load_f4_wb_keys(settings)
        report: dict = {
            "mode": "f4_source_gate",
            "authorizedIntegrationPresent": bool(api_keys),
            "integrationAccessIncomplete": integration_access_incomplete,
        }
        report.update(run_f4_probe(api_keys, today, days=args.days))
        if not api_keys:
            report["implementationGate"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    report: dict = {"tenant": settings.source_refresh_tenant}
    api_key, provider, diag = load_wb_key(settings)
    report["wb_integrations"] = diag
    report["wb_integration_found"] = bool(api_key)
    report["wb_provider"] = provider
    report["results"] = run_probe(api_key, today) if api_key else {}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
