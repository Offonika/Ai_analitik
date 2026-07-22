#!/usr/bin/env python3
"""Read-only availability probe for WB logistics factors (F-0/F-4/R-0/R-0I).

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
      --property=Environment=PYTHONPATH=.:./src \\
      /opt/shumeyko-partners-wb-unit-economics/.venv/bin/python \\
      scripts/probe_wb_logistics_factors.py

Результат — обезличенная матрица доступности для draft-спека
`docs/specs/wb-logistics-cost-factors-implementation.md` и runbook
`docs/runbooks/wb-logistics-factors-probe.md`.

Режимы ``--mode f4``, ``--mode r0`` и ``--mode r0-identity`` строже legacy
F-0: они не печатают provider labels, количество интеграций/строк, HTTP body,
идентификаторы, суммы или значения полей. В выводе остаются только булевы
признаки доступности, schema gate и identity gate.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, NamedTuple, Protocol

import httpx
from sqlalchemy import or_, select

from wb_unit_economics.logistics_analysis import (
    LogisticsSourceRow,
    logistics_chain_key,
)
from wb_unit_economics.web import integrations
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import (
    ReportLogisticsAnalysisContext,
    ReportLogisticsOrderRow,
    ReportRun,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    TenantIntegration,
    WbCabinet,
)
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    _select_logistics_source_rows,
    wb_finance_settings_from_secret,
)

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

R0_REQUIRED_FIELDS = {
    "goods_return": {"reason", "status", "returnType", "srid", "nmId"},
    "claims_active": {"id", "nm_id", "user_comment", "srid", "dt"},
    "claims_archive": {"id", "nm_id", "user_comment", "srid", "dt"},
}

R0_IDENTITY_SOURCE_FIELDS = (
    "goodsReturnSrid",
    "goodsReturnOrderId",
    "claimsSrid",
)
R0_IDENTITY_FINANCE_FIELDS = (
    "financeOrderUid",
    "financeSrid",
    "financeOrderId",
)
R0_IDENTITY_CANDIDATES = {
    "goodsReturnSridToFinanceOrderUid": (
        "goodsReturnSrid",
        "financeOrderUid",
        "baseline",
    ),
    "goodsReturnSridToFinanceSrid": (
        "goodsReturnSrid",
        "financeSrid",
        "same_name",
    ),
    "goodsReturnOrderIdToFinanceOrderId": (
        "goodsReturnOrderId",
        "financeOrderId",
        "same_name",
    ),
    "claimsSridToFinanceOrderUid": (
        "claimsSrid",
        "financeOrderUid",
        "baseline",
    ),
    "claimsSridToFinanceSrid": (
        "claimsSrid",
        "financeSrid",
        "same_name",
    ),
}


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any: ...


class R0ProbeAccount(NamedTuple):
    api_key: str
    tenant_id: str = ""
    client_id: str = ""
    wb_cabinet_id: str = ""
    report_window_end: date | None = None

    @property
    def scope(self) -> tuple[str, str, str] | None:
        values = (self.tenant_id, self.client_id, self.wb_cabinet_id)
        return values if all(value.strip() for value in values) else None


class R0ReportContext(NamedTuple):
    """Minimal report shape compatible with pre-factor database schemas."""

    id: str
    tenant_id: str
    client_id: str
    period_start: date
    period_end: date


class R0RefreshCollectionContext(NamedTuple):
    id: int
    tenant_id: str
    client_id: str
    source_type: str
    snapshot_hash: str
    row_count: int
    raw_path: str
    payload: dict[str, Any]
    loaded_at: datetime


class R0RefreshContext(NamedTuple):
    id: str
    tenant_id: str
    client_id: str
    root_dir: str
    period_start: date
    period_end: date
    source_window_start: date | None
    source_window_end: date | None
    collections: list[R0RefreshCollectionContext]


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


def r0_endpoints(today: date, *, days: int = 7) -> list[tuple[str, str, dict]]:
    """Минимальные read-only запросы причин без raw/PII в результате."""
    if days < 1 or days > 31:
        raise ValueError("R-0 probe days must be between 1 and 31")
    start = (today - timedelta(days=days - 1)).isoformat()
    end = today.isoformat()
    return [
        (
            "goods_return",
            "https://seller-analytics-api.wildberries.ru/api/v1/analytics/goods-return",
            {"dateFrom": start, "dateTo": end},
        ),
        (
            "claims_active",
            "https://returns-api.wildberries.ru/api/v1/claims",
            {"is_archive": False, "limit": 1, "offset": 0},
        ),
        (
            "claims_archive",
            "https://returns-api.wildberries.ru/api/v1/claims",
            {"is_archive": True, "limit": 1, "offset": 0},
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


def load_r0_accounts(settings: WebSettings) -> tuple[list[R0ProbeAccount], bool]:
    """Загрузить read-only keys и внутренний cabinet scope без его публикации."""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    result: list[R0ProbeAccount] = []
    incomplete = False
    seen: set[tuple[str, str]] = set()
    with session_factory() as db:
        integrations_list = list(
            db.scalars(
                select(TenantIntegration).where(
                    TenantIntegration.tenant_id == settings.source_refresh_tenant,
                    TenantIntegration.status == "check_ok",
                )
            )
        )
        for integration in integrations_list:
            if str(integration.provider).split(":", 1)[0] != "wb_api":
                continue
            try:
                secret = integrations.decrypt_secret(
                    settings, integration.config_payload or {}
                )
                wb_settings = wb_finance_settings_from_secret(secret)
            except integrations.IntegrationSecretError:
                incomplete = True
                continue
            payload = integration.config_payload or {}
            cabinet_id = str(payload.get("wbCabinetId") or "").strip()
            cabinet = None
            if cabinet_id:
                cabinet = db.scalar(
                    select(WbCabinet).where(
                        WbCabinet.id == cabinet_id,
                        WbCabinet.tenant_id == settings.source_refresh_tenant,
                    )
                )
            if cabinet is None:
                cabinets = list(
                    db.scalars(
                        select(WbCabinet).where(
                            WbCabinet.tenant_id == settings.source_refresh_tenant,
                            WbCabinet.provider == integration.provider,
                        )
                    )
                )
                if len(cabinets) == 1:
                    cabinet = cabinets[0]
                elif len(cabinets) > 1:
                    incomplete = True
            if cabinet is None:
                incomplete = True
            report_window_end = None
            if cabinet is not None:
                report = _latest_r0_report(
                    db,
                    tenant_id=settings.source_refresh_tenant,
                    client_id=cabinet.client_id,
                    cabinet_id=cabinet.id,
                )
                report_window_end = report.period_end if report is not None else None
            for account in wb_settings.accounts:
                marker = (account.api_key, cabinet.id if cabinet is not None else "")
                if marker in seen:
                    continue
                seen.add(marker)
                result.append(
                    R0ProbeAccount(
                        api_key=account.api_key,
                        tenant_id=settings.source_refresh_tenant,
                        client_id=cabinet.client_id if cabinet is not None else "",
                        wb_cabinet_id=cabinet.id if cabinet is not None else "",
                        report_window_end=report_window_end,
                    )
                )
    return result, incomplete


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


def classify_r0_response(name: str, response: ResponseLike) -> str:
    """Классифицировать R-0 без возврата counts, identifiers или raw values."""
    if response.status_code in {401, 403}:
        return "access_denied"
    if response.status_code == 402:
        return "paid_scope_required"
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
    if name == "goods_return":
        rows = payload.get("report")
        if not isinstance(rows, list):
            return "schema_mismatch"
        if not rows:
            return "confirmed_empty"
    else:
        rows = payload.get("claims")
        total = payload.get("total")
        if (
            not isinstance(rows, list)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
        ):
            return "schema_mismatch"
        if not rows:
            return "confirmed_empty" if total == 0 else "schema_mismatch"
        if total < 1:
            return "schema_mismatch"
    first = rows[0]
    if not isinstance(first, dict) or not R0_REQUIRED_FIELDS[name].issubset(first):
        return "schema_mismatch"
    return "confirmed_nonempty"


def r0_join_keys(
    name: str,
    payload: Any,
    account: R0ProbeAccount,
) -> tuple[set[str], bool]:
    """Построить exact scoped keys в памяти; raw identifiers наружу не выходят."""
    if account.scope is None or not isinstance(payload, dict):
        return set(), bool(isinstance(payload, dict))
    rows = payload.get("report" if name == "goods_return" else "claims")
    if not isinstance(rows, list):
        return set(), True
    keys: set[str] = set()
    invalid_present = False
    for row in rows:
        if not isinstance(row, dict):
            invalid_present = True
            continue
        srid = str(row.get("srid") or "").strip()
        raw_nm_id = row.get("nmId" if name == "goods_return" else "nm_id")
        nm_id = "" if isinstance(raw_nm_id, bool) else str(raw_nm_id or "").strip()
        if not srid or not nm_id:
            invalid_present = True
            continue
        keys.add(
            logistics_chain_key(
                tenant_id=account.tenant_id,
                client_id=account.client_id,
                wb_cabinet_id=account.wb_cabinet_id,
                order_uid=srid,
                product_key=f"nm:{nm_id}",
            )
        )
    return keys, invalid_present


def _r0_identity_key(
    account: R0ProbeAccount,
    *,
    identifier: str,
    nm_id: str,
) -> str:
    return logistics_chain_key(
        tenant_id=account.tenant_id,
        client_id=account.client_id,
        wb_cabinet_id=account.wb_cabinet_id,
        order_uid=identifier,
        product_key=f"nm:{nm_id}",
    )


def r0_identity_source_keys(
    name: str,
    payload: Any,
    account: R0ProbeAccount,
) -> tuple[dict[str, set[str]], dict[str, bool], dict[str, bool]]:
    """Hash R-0I source candidates and retain only boolean quality signals."""

    keys = {field: set() for field in R0_IDENTITY_SOURCE_FIELDS}
    ambiguous = {field: False for field in R0_IDENTITY_SOURCE_FIELDS}
    invalid = {field: False for field in R0_IDENTITY_SOURCE_FIELDS}
    if account.scope is None or not isinstance(payload, dict):
        for field in invalid:
            invalid[field] = True
        return keys, ambiguous, invalid
    rows = payload.get("report" if name == "goods_return" else "claims")
    if not isinstance(rows, list):
        for field in invalid:
            invalid[field] = True
        return keys, ambiguous, invalid

    peer_keys: dict[str, dict[str, set[str]]] = {
        "goodsReturnSrid": {},
        "goodsReturnOrderId": {},
    }
    for row in rows:
        if not isinstance(row, dict):
            for field in invalid:
                invalid[field] = True
            continue
        raw_nm_id = row.get("nmId" if name == "goods_return" else "nm_id")
        nm_id = "" if isinstance(raw_nm_id, bool) else str(raw_nm_id or "").strip()
        srid = str(row.get("srid") or "").strip()
        if name == "goods_return":
            raw_order_id = row.get("orderId")
            order_id = (
                ""
                if isinstance(raw_order_id, bool)
                else str(raw_order_id or "").strip()
            )
            source_values = {
                "goodsReturnSrid": srid,
                "goodsReturnOrderId": order_id,
            }
            for field, value in source_values.items():
                if not nm_id or not value:
                    invalid[field] = True
                    continue
                candidate_key = _r0_identity_key(
                    account,
                    identifier=value,
                    nm_id=nm_id,
                )
                keys[field].add(candidate_key)
                peer = order_id if field == "goodsReturnSrid" else srid
                if peer:
                    peer_key = _r0_identity_key(
                        account,
                        identifier=peer,
                        nm_id=nm_id,
                    )
                    peer_keys[field].setdefault(candidate_key, set()).add(peer_key)
        else:
            if not nm_id or not srid:
                invalid["claimsSrid"] = True
                continue
            keys["claimsSrid"].add(
                _r0_identity_key(account, identifier=srid, nm_id=nm_id)
            )

    for field, candidates in peer_keys.items():
        ambiguous[field] = any(len(peers) > 1 for peers in candidates.values())
    return keys, ambiguous, invalid


def evaluate_r0_join(
    settings: WebSettings,
    source_keys_by_scope: dict[tuple[str, str, str], set[str]],
    *,
    invalid_source_key_present: bool,
) -> dict[str, bool]:
    """Сверить latest immutable Finance-return keys, вернув только booleans."""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    join_evaluated = False
    source_key_present = False
    finance_return_key_present = False
    matched_present = False
    source_unmatched_present = False
    finance_unmatched_present = False
    with session_factory() as db:
        for (tenant_id, client_id, cabinet_id), source_keys in (
            source_keys_by_scope.items()
        ):
            source_key_present = source_key_present or bool(source_keys)
            report_id = db.scalar(
                select(ReportRun.id)
                .where(
                    ReportRun.tenant_id == tenant_id,
                    ReportRun.client_id == client_id,
                    ReportRun.logistics_analysis_required.is_(True),
                    ReportRun.id.in_(
                        select(ReportLogisticsOrderRow.report_run_id).where(
                            ReportLogisticsOrderRow.wb_cabinet_id == cabinet_id
                        )
                    ),
                )
                .order_by(ReportRun.generated_at.desc(), ReportRun.id.desc())
                .limit(1)
            )
            if not report_id:
                continue
            join_evaluated = True
            finance_keys = set(
                db.scalars(
                    select(ReportLogisticsOrderRow.chain_key).where(
                        ReportLogisticsOrderRow.report_run_id == report_id,
                        ReportLogisticsOrderRow.wb_cabinet_id == cabinet_id,
                        or_(
                            ReportLogisticsOrderRow.return_quantity != 0,
                            ReportLogisticsOrderRow.logistics_reverse != 0,
                        ),
                    )
                )
            )
            finance_return_key_present = finance_return_key_present or bool(
                finance_keys
            )
            matched_present = matched_present or bool(source_keys & finance_keys)
            source_unmatched_present = source_unmatched_present or bool(
                source_keys - finance_keys
            )
            finance_unmatched_present = finance_unmatched_present or bool(
                finance_keys - source_keys
            )
    return {
        "joinEvaluated": join_evaluated,
        "sourceKeyPresent": source_key_present,
        "financeReturnKeyPresent": finance_return_key_present,
        "matchedPresent": matched_present,
        "sourceUnmatchedPresent": source_unmatched_present,
        "financeUnmatchedPresent": finance_unmatched_present,
        "invalidSourceKeyPresent": invalid_source_key_present,
        "joinGate": r0_join_gate(join_evaluated, matched_present),
    }


def r0_join_gate(join_evaluated: bool, matched_present: bool) -> bool:
    """Не разблокировать F-5, пока exact join не доказан хотя бы один раз."""
    return join_evaluated and matched_present


def _latest_r0_report(
    db: Any,
    *,
    tenant_id: str,
    client_id: str,
    cabinet_id: str,
) -> R0ReportContext | None:
    row = db.execute(
        select(
            ReportRun.id,
            ReportRun.tenant_id,
            ReportRun.client_id,
            ReportRun.period_start,
            ReportRun.period_end,
        )
        .join(
            ReportLogisticsAnalysisContext,
            ReportLogisticsAnalysisContext.report_run_id == ReportRun.id,
        )
        .where(
            ReportRun.tenant_id == tenant_id,
            ReportRun.client_id == client_id,
            ReportRun.logistics_analysis_required.is_(True),
            ReportLogisticsAnalysisContext.data_status.in_(
                ("ready", "partial", "empty")
            ),
            ReportLogisticsAnalysisContext.source_quality_status == "ready",
            ReportLogisticsAnalysisContext.invalid_source_payload_shape_count == 0,
            ReportLogisticsAnalysisContext.source_identity_error_count == 0,
            ReportLogisticsAnalysisContext.source_revision_conflict_count == 0,
            ReportLogisticsAnalysisContext.scope_mismatch_count == 0,
            ReportRun.id.in_(
                select(ReportLogisticsOrderRow.report_run_id).where(
                    ReportLogisticsOrderRow.wb_cabinet_id == cabinet_id
                )
            ),
        )
        .order_by(ReportRun.generated_at.desc(), ReportRun.id.desc())
        .limit(1)
    ).first()
    return R0ReportContext(*row) if row is not None else None


def _selected_finance_identity_rows(
    db: Any,
    report: R0ReportContext,
) -> tuple[list[LogisticsSourceRow], bool, dict[str, bool]]:
    """Reuse the production lineage selector without exposing its raw rows."""

    failure = {
        "lineageMetadataFailurePresent": False,
        "schemaCompatibilityFailurePresent": False,
        "selectorContractFailurePresent": False,
        "sourceIntegrityFailurePresent": False,
        "payloadShapeFailurePresent": False,
        "payloadHashFailurePresent": False,
        "sourceIdentityFailurePresent": False,
        "sourceRevisionFailurePresent": False,
        "scopeFailurePresent": False,
        "storageIntegrityFailurePresent": False,
        "databaseFileAmbiguityPresent": False,
        "fileSnapshotIntegrityFailurePresent": False,
        "unclassifiedBlockingFailurePresent": False,
    }

    loads = list(
        db.execute(
            select(
                SourceLoad.source_refresh_run_id,
                SourceLoad.lineage_role,
            ).where(
                SourceLoad.report_run_id == report.id,
                SourceLoad.source_type == "wb_finance_detail",
            )
        )
    )
    role_by_run: dict[str, str] = {}
    runs: dict[str, R0RefreshContext] = {}
    integrity_ok = bool(loads)
    for load in loads:
        run_id = str(load.source_refresh_run_id or "").strip()
        role = str(load.lineage_role or "").strip()
        normalized_role = {
            "current": "current",
            "base": "base",
            "overlay": "contributor",
            "contributor": "contributor",
        }.get(role)
        if not run_id or normalized_role is None:
            integrity_ok = False
            continue
        previous_role = role_by_run.get(run_id)
        if previous_role is not None and previous_role != normalized_role:
            integrity_ok = False
            continue
        role_by_run[run_id] = normalized_role

    run_ids = sorted(role_by_run)
    collection_rows = (
        list(
            db.execute(
                select(
                    SourceRefreshCollection.refresh_run_id,
                    SourceRefreshCollection.id,
                    SourceRefreshCollection.tenant_id,
                    SourceRefreshCollection.client_id,
                    SourceRefreshCollection.source_type,
                    SourceRefreshCollection.snapshot_hash,
                    SourceRefreshCollection.row_count,
                    SourceRefreshCollection.raw_path,
                    SourceRefreshCollection.payload,
                    SourceRefreshCollection.loaded_at,
                ).where(
                    SourceRefreshCollection.refresh_run_id.in_(run_ids),
                    SourceRefreshCollection.source_type == "wb_finance_detail",
                )
            )
        )
        if run_ids
        else []
    )
    collections_by_run: dict[str, list[R0RefreshCollectionContext]] = {}
    for collection in collection_rows:
        collections_by_run.setdefault(str(collection.refresh_run_id), []).append(
            R0RefreshCollectionContext(*collection[1:])
        )
    if run_ids:
        for run in db.execute(
            select(
                SourceRefreshRun.id,
                SourceRefreshRun.tenant_id,
                SourceRefreshRun.client_id,
                SourceRefreshRun.root_dir,
                SourceRefreshRun.period_start,
                SourceRefreshRun.period_end,
                SourceRefreshRun.source_window_start,
                SourceRefreshRun.source_window_end,
            ).where(SourceRefreshRun.id.in_(run_ids))
        ):
            context = R0RefreshContext(
                id=str(run.id),
                tenant_id=str(run.tenant_id or ""),
                client_id=str(run.client_id or ""),
                root_dir=str(run.root_dir or ""),
                period_start=run.period_start,
                period_end=run.period_end,
                source_window_start=run.source_window_start,
                source_window_end=run.source_window_end,
                collections=collections_by_run.get(str(run.id), []),
            )
            runs[context.id] = context
    integrity_ok = integrity_ok and set(runs) == set(run_ids)
    integrity_ok = integrity_ok and all(
        run.tenant_id == report.tenant_id and run.client_id == report.client_id
        for run in runs.values()
    )

    primary_runs = [run for run in runs.values() if role_by_run[run.id] == "current"]
    base_runs = [run for run in runs.values() if role_by_run[run.id] == "base"]
    integrity_ok = integrity_ok and len(primary_runs) == 1 and len(base_runs) <= 1
    if not integrity_ok:
        failure["lineageMetadataFailurePresent"] = True
        return [], False, failure
    primary = primary_runs[0]
    base = base_runs[0] if base_runs else None
    roles = {run_id: (run, role_by_run[run_id]) for run_id, run in runs.items()}
    try:
        rows, diagnostics = _select_logistics_source_rows(
            db,
            report,
            roles=roles,
            primary_refresh_run=primary,
            base_refresh_run=base,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        sqlstate = str(getattr(getattr(exc, "orig", None), "sqlstate", ""))
        failure["schemaCompatibilityFailurePresent"] = sqlstate == "42703"
        failure["selectorContractFailurePresent"] = isinstance(
            exc, (AttributeError, TypeError)
        )
        if not any(failure.values()):
            failure["sourceIntegrityFailurePresent"] = True
        return [], False, failure
    verified = not (
        diagnostics.blocking_reasons
        or diagnostics.invalid_source_payload_shape_count
        or diagnostics.source_identity_error_count
        or diagnostics.source_revision_conflict_count
        or diagnostics.scope_mismatch_count
    )
    failure["sourceIntegrityFailurePresent"] = not verified
    blocking = set(diagnostics.blocking_reasons)
    failure["payloadShapeFailurePresent"] = bool(
        diagnostics.invalid_source_payload_shape_count
    )
    failure["payloadHashFailurePresent"] = "source_payload_hash_mismatch" in blocking
    failure["sourceIdentityFailurePresent"] = bool(
        diagnostics.source_identity_error_count
    )
    failure["sourceRevisionFailurePresent"] = bool(
        diagnostics.source_revision_conflict_count
    )
    failure["scopeFailurePresent"] = bool(diagnostics.scope_mismatch_count)
    failure["storageIntegrityFailurePresent"] = bool(
        blocking
        & {
            "source_storage_ambiguity",
            "file_authoritative_snapshot_invalid",
        }
    )
    failure["databaseFileAmbiguityPresent"] = (
        "source_storage_ambiguity" in blocking
    )
    failure["fileSnapshotIntegrityFailurePresent"] = (
        "file_authoritative_snapshot_invalid" in blocking
    )
    classified_blocking = {
        "invalid_source_payload_shape",
        "source_payload_hash_mismatch",
        "source_identity_missing",
        "source_identity_mismatch",
        "source_window_overlap_conflict",
        "source_revision_conflict",
        "tenant_scope_mismatch",
        "source_storage_ambiguity",
        "file_authoritative_snapshot_invalid",
    }
    failure["unclassifiedBlockingFailurePresent"] = bool(
        blocking - classified_blocking
    )
    return rows, verified, failure


def _finance_identity_maps(
    rows: list[LogisticsSourceRow],
    *,
    tenant_id: str,
    client_id: str,
    cabinet_id: str,
    return_keys: set[str],
) -> dict[str, dict[str, set[str]]]:
    result: dict[str, dict[str, set[str]]] = {
        field: {} for field in R0_IDENTITY_FINANCE_FIELDS
    }
    account = R0ProbeAccount(
        api_key="",
        tenant_id=tenant_id,
        client_id=client_id,
        wb_cabinet_id=cabinet_id,
    )
    for row in rows:
        if (
            row.tenant_id != tenant_id
            or row.client_id != client_id
            or row.wb_cabinet_id != cabinet_id
            or not row.nm_id.strip()
            or not row.chain_key
            or row.chain_key not in return_keys
        ):
            continue
        identities = {
            "financeOrderUid": row.order_uid,
            "financeSrid": row.finance_srid,
            "financeOrderId": row.finance_order_id,
        }
        for field, identifier in identities.items():
            if not identifier.strip():
                continue
            identity_key = (
                row.chain_key
                if field == "financeOrderUid"
                else _r0_identity_key(
                    account,
                    identifier=identifier.strip(),
                    nm_id=row.nm_id.strip(),
                )
            )
            result[field].setdefault(identity_key, set()).add(row.chain_key)
    return result


def load_r0_finance_identity(
    settings: WebSettings,
    scopes: set[tuple[str, str, str]],
) -> tuple[
    dict[tuple[str, str, str], dict[str, dict[str, set[str]]]],
    dict[tuple[str, str, str], dict[str, bool]],
]:
    """Load verified Finance identity maps and return only in-memory hashes."""

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    maps_by_scope: dict[
        tuple[str, str, str], dict[str, dict[str, set[str]]]
    ] = {}
    state_by_scope: dict[tuple[str, str, str], dict[str, bool]] = {}
    with session_factory() as db:
        for tenant_id, client_id, cabinet_id in sorted(scopes):
            scope = (tenant_id, client_id, cabinet_id)
            empty_maps = {field: {} for field in R0_IDENTITY_FINANCE_FIELDS}
            try:
                report = _latest_r0_report(
                    db,
                    tenant_id=tenant_id,
                    client_id=client_id,
                    cabinet_id=cabinet_id,
                )
            except Exception:  # noqa: BLE001
                db.rollback()
                maps_by_scope[scope] = empty_maps
                state_by_scope[scope] = {
                    "joinEvaluated": False,
                    "verifiedLineage": False,
                    "lineageFailurePresent": True,
                    "financeReturnKeyPresent": False,
                }
                continue
            if report is None:
                maps_by_scope[scope] = empty_maps
                state_by_scope[scope] = {
                    "joinEvaluated": False,
                    "verifiedLineage": False,
                    "lineageFailurePresent": True,
                    "financeReturnKeyPresent": False,
                }
                continue
            try:
                return_keys = set(
                    db.scalars(
                        select(ReportLogisticsOrderRow.chain_key).where(
                            ReportLogisticsOrderRow.report_run_id == report.id,
                            ReportLogisticsOrderRow.wb_cabinet_id == cabinet_id,
                            or_(
                                ReportLogisticsOrderRow.return_quantity != 0,
                                ReportLogisticsOrderRow.logistics_reverse != 0,
                            ),
                        )
                    )
                )
                rows, verified, failure = _selected_finance_identity_rows(
                    db, report
                )
            except Exception:  # noqa: BLE001
                db.rollback()
                maps_by_scope[scope] = empty_maps
                state_by_scope[scope] = {
                    "joinEvaluated": False,
                    "verifiedLineage": False,
                    "lineageFailurePresent": True,
                    "financeReturnKeyPresent": False,
                }
                continue
            maps_by_scope[scope] = _finance_identity_maps(
                rows,
                tenant_id=tenant_id,
                client_id=client_id,
                cabinet_id=cabinet_id,
                return_keys=return_keys,
            )
            state_by_scope[scope] = {
                "joinEvaluated": True,
                "verifiedLineage": verified,
                "lineageFailurePresent": not verified,
                "financeReturnKeyPresent": bool(return_keys),
                **failure,
            }
    return maps_by_scope, state_by_scope


def evaluate_r0_identity(
    source_keys_by_scope: dict[tuple[str, str, str], dict[str, set[str]]],
    source_ambiguity_by_scope: dict[tuple[str, str, str], dict[str, bool]],
    invalid_source_by_scope: dict[tuple[str, str, str], dict[str, bool]],
    finance_maps_by_scope: dict[
        tuple[str, str, str], dict[str, dict[str, set[str]]]
    ],
    finance_state_by_scope: dict[tuple[str, str, str], dict[str, bool]],
) -> dict[str, Any]:
    """Compare hashed candidates and emit boolean-only crosswalk evidence."""

    candidates: dict[str, dict[str, bool]] = {}
    for candidate_name, (source_field, finance_field, kind) in (
        R0_IDENTITY_CANDIDATES.items()
    ):
        join_evaluated = False
        verified_lineage = False
        lineage_failure = False
        lineage_metadata_failure = False
        schema_compatibility_failure = False
        selector_contract_failure = False
        source_integrity_failure = False
        payload_shape_failure = False
        payload_hash_failure = False
        source_identity_failure = False
        source_revision_failure = False
        scope_failure = False
        storage_integrity_failure = False
        database_file_ambiguity = False
        file_snapshot_integrity_failure = False
        unclassified_blocking_failure = False
        source_present = False
        finance_present = False
        finance_return_present = False
        matched_present = False
        canonical_return_resolved = False
        source_unmatched = False
        finance_unmatched = False
        source_ambiguity = False
        finance_ambiguity = False
        invalid_source = False
        for scope in sorted(
            set(source_keys_by_scope)
            | set(finance_maps_by_scope)
            | set(finance_state_by_scope)
        ):
            source_keys = source_keys_by_scope.get(scope, {}).get(source_field, set())
            finance_map = finance_maps_by_scope.get(scope, {}).get(finance_field, {})
            finance_keys = set(finance_map)
            state = finance_state_by_scope.get(scope, {})
            join_evaluated = join_evaluated or bool(state.get("joinEvaluated"))
            verified_lineage = verified_lineage or bool(
                state.get("verifiedLineage")
            )
            lineage_failure = lineage_failure or bool(
                state.get("lineageFailurePresent")
            )
            lineage_metadata_failure = lineage_metadata_failure or bool(
                state.get("lineageMetadataFailurePresent")
            )
            schema_compatibility_failure = schema_compatibility_failure or bool(
                state.get("schemaCompatibilityFailurePresent")
            )
            selector_contract_failure = selector_contract_failure or bool(
                state.get("selectorContractFailurePresent")
            )
            source_integrity_failure = source_integrity_failure or bool(
                state.get("sourceIntegrityFailurePresent")
            )
            payload_shape_failure = payload_shape_failure or bool(
                state.get("payloadShapeFailurePresent")
            )
            payload_hash_failure = payload_hash_failure or bool(
                state.get("payloadHashFailurePresent")
            )
            source_identity_failure = source_identity_failure or bool(
                state.get("sourceIdentityFailurePresent")
            )
            source_revision_failure = source_revision_failure or bool(
                state.get("sourceRevisionFailurePresent")
            )
            scope_failure = scope_failure or bool(state.get("scopeFailurePresent"))
            storage_integrity_failure = storage_integrity_failure or bool(
                state.get("storageIntegrityFailurePresent")
            )
            database_file_ambiguity = database_file_ambiguity or bool(
                state.get("databaseFileAmbiguityPresent")
            )
            file_snapshot_integrity_failure = (
                file_snapshot_integrity_failure
                or bool(state.get("fileSnapshotIntegrityFailurePresent"))
            )
            unclassified_blocking_failure = unclassified_blocking_failure or bool(
                state.get("unclassifiedBlockingFailurePresent")
            )
            finance_return_present = finance_return_present or bool(
                state.get("financeReturnKeyPresent")
            )
            source_present = source_present or bool(source_keys)
            finance_present = finance_present or bool(finance_keys)
            matches = source_keys & finance_keys
            matched_present = matched_present or bool(matches)
            source_unmatched = source_unmatched or bool(source_keys - finance_keys)
            finance_unmatched = finance_unmatched or bool(finance_keys - source_keys)
            source_ambiguity = source_ambiguity or bool(
                source_ambiguity_by_scope.get(scope, {}).get(source_field)
            )
            invalid_source = invalid_source or bool(
                invalid_source_by_scope.get(scope, {}).get(source_field)
            )
            finance_ambiguity = finance_ambiguity or any(
                len(chains) > 1 for chains in finance_map.values()
            )
            canonical_return_resolved = canonical_return_resolved or any(
                len(finance_map[key]) == 1 for key in matches
            )
        candidate_gate = (
            kind == "same_name"
            and join_evaluated
            and verified_lineage
            and source_present
            and finance_present
            and finance_return_present
            and matched_present
            and canonical_return_resolved
            and not lineage_failure
            and not source_ambiguity
            and not finance_ambiguity
            and not invalid_source
        )
        candidates[candidate_name] = {
            "joinEvaluated": join_evaluated,
            "verifiedLineagePresent": verified_lineage,
            "lineageFailurePresent": lineage_failure,
            "lineageMetadataFailurePresent": lineage_metadata_failure,
            "schemaCompatibilityFailurePresent": schema_compatibility_failure,
            "selectorContractFailurePresent": selector_contract_failure,
            "sourceIntegrityFailurePresent": source_integrity_failure,
            "payloadShapeFailurePresent": payload_shape_failure,
            "payloadHashFailurePresent": payload_hash_failure,
            "sourceIdentityFailurePresent": source_identity_failure,
            "sourceRevisionFailurePresent": source_revision_failure,
            "scopeFailurePresent": scope_failure,
            "storageIntegrityFailurePresent": storage_integrity_failure,
            "databaseFileAmbiguityPresent": database_file_ambiguity,
            "fileSnapshotIntegrityFailurePresent": file_snapshot_integrity_failure,
            "unclassifiedBlockingFailurePresent": unclassified_blocking_failure,
            "sourceKeyPresent": source_present,
            "financeKeyPresent": finance_present,
            "financeReturnKeyPresent": finance_return_present,
            "matchedPresent": matched_present,
            "canonicalReturnResolvedPresent": canonical_return_resolved,
            "sourceUnmatchedPresent": source_unmatched,
            "financeUnmatchedPresent": finance_unmatched,
            "sourceAmbiguityPresent": source_ambiguity,
            "financeAmbiguityPresent": finance_ambiguity,
            "invalidSourceKeyPresent": invalid_source,
            "candidateGate": candidate_gate,
        }

    goods_gate = (
        candidates["goodsReturnSridToFinanceSrid"]["candidateGate"]
        or candidates["goodsReturnOrderIdToFinanceOrderId"]["candidateGate"]
    )
    claims_gate = candidates["claimsSridToFinanceSrid"]["candidateGate"]
    baseline_gate = (
        candidates["goodsReturnSridToFinanceOrderUid"]["matchedPresent"]
        or candidates["claimsSridToFinanceOrderUid"]["matchedPresent"]
    )
    return {
        "candidates": candidates,
        "goodsReturnIdentityGate": goods_gate,
        "claimsIdentityGate": claims_gate,
        "completeIdentityGate": goods_gate and claims_gate,
        "sameNameEvidencePresent": goods_gate or claims_gate,
        "baselineDirectMatchPresent": baseline_gate,
        "contractChangeRequired": (goods_gate or claims_gate) and not baseline_gate,
    }


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


def aggregate_r0_statuses(statuses: dict[str, list[str]]) -> dict:
    """Свести R-0 к boolean-only evidence без source cardinality и PII."""
    endpoints_report: dict[str, dict[str, bool]] = {}
    endpoint_gates: dict[str, bool] = {}
    for name in R0_REQUIRED_FIELDS:
        values = statuses.get(name, [])
        entry = {
            "schemaConfirmedAny": any(
                value.startswith("confirmed_") for value in values
            ),
            "confirmedEmptyPresent": "confirmed_empty" in values,
            "confirmedNonemptyPresent": "confirmed_nonempty" in values,
            "accessDeniedPresent": "access_denied" in values,
            "paidScopeRequiredPresent": "paid_scope_required" in values,
            "unavailablePresent": "unavailable" in values,
            "schemaMismatchPresent": "schema_mismatch" in values,
        }
        endpoint_gates[name] = (
            entry["schemaConfirmedAny"] and not entry["schemaMismatchPresent"]
        )
        endpoints_report[name] = entry
    goods_return_gate = endpoint_gates["goods_return"]
    claims_gate = (
        endpoint_gates["claims_active"] and endpoint_gates["claims_archive"]
    )
    return {
        "endpoints": endpoints_report,
        "goodsReturnGate": goods_return_gate,
        "claimsGate": claims_gate,
        "completeSourceGate": goods_return_gate and claims_gate,
        "implementationGate": goods_return_gate or claims_gate,
    }


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


def run_r0_probe(
    accounts: list[R0ProbeAccount],
    settings: WebSettings,
    today: date,
    *,
    days: int = 7,
) -> dict:
    statuses = {name: [] for name in R0_REQUIRED_FIELDS}
    source_keys_by_scope: dict[tuple[str, str, str], set[str]] = {}
    invalid_source_key_present = False
    report_window_aligned = False
    for account in accounts:
        if account.scope is not None:
            source_keys_by_scope.setdefault(account.scope, set())
        headers = {"Authorization": account.api_key, "Accept": "application/json"}
        with httpx.Client(
            headers=headers, timeout=TIMEOUT, follow_redirects=True
        ) as client:
            window_end = account.report_window_end or today
            report_window_aligned = (
                report_window_aligned or account.report_window_end is not None
            )
            for name, url, params in r0_endpoints(window_end, days=days):
                try:
                    response = client.get(url, params=params)
                    status = classify_r0_response(name, response)
                except httpx.HTTPError:
                    status = "unavailable"
                statuses[name].append(status)
                if status != "confirmed_nonempty" or account.scope is None:
                    continue
                try:
                    keys, invalid = r0_join_keys(name, response.json(), account)
                except Exception:  # noqa: BLE001
                    invalid_source_key_present = True
                    continue
                source_keys_by_scope[account.scope].update(keys)
                invalid_source_key_present = invalid_source_key_present or invalid
    report = aggregate_r0_statuses(statuses)
    join_report = evaluate_r0_join(
        settings,
        source_keys_by_scope,
        invalid_source_key_present=invalid_source_key_present,
    )
    report["join"] = join_report
    report["reportWindowAligned"] = report_window_aligned
    report["sourceImplementationGate"] = report["implementationGate"]
    report["implementationGate"] = (
        report["sourceImplementationGate"] and join_report["joinGate"]
    )
    return report


def run_r0_identity_probe(
    accounts: list[R0ProbeAccount],
    settings: WebSettings,
    today: date,
    *,
    days: int = 31,
) -> dict[str, Any]:
    """Run R-0I without returning raw identifiers, values or cardinality."""

    statuses = {name: [] for name in R0_REQUIRED_FIELDS}
    source_keys_by_scope: dict[tuple[str, str, str], dict[str, set[str]]] = {}
    source_ambiguity_by_scope: dict[
        tuple[str, str, str], dict[str, bool]
    ] = {}
    invalid_source_by_scope: dict[tuple[str, str, str], dict[str, bool]] = {}
    report_window_aligned = False
    for account in accounts:
        if account.scope is not None:
            source_keys_by_scope.setdefault(
                account.scope,
                {field: set() for field in R0_IDENTITY_SOURCE_FIELDS},
            )
            source_ambiguity_by_scope.setdefault(
                account.scope,
                {field: False for field in R0_IDENTITY_SOURCE_FIELDS},
            )
            invalid_source_by_scope.setdefault(
                account.scope,
                {field: False for field in R0_IDENTITY_SOURCE_FIELDS},
            )
        headers = {"Authorization": account.api_key, "Accept": "application/json"}
        with httpx.Client(
            headers=headers, timeout=TIMEOUT, follow_redirects=True
        ) as client:
            window_end = account.report_window_end or today
            report_window_aligned = (
                report_window_aligned or account.report_window_end is not None
            )
            for name, url, params in r0_endpoints(window_end, days=days):
                try:
                    response = client.get(url, params=params)
                    status = classify_r0_response(name, response)
                except httpx.HTTPError:
                    status = "unavailable"
                statuses[name].append(status)
                if status != "confirmed_nonempty" or account.scope is None:
                    continue
                try:
                    keys, ambiguous, invalid = r0_identity_source_keys(
                        name,
                        response.json(),
                        account,
                    )
                except Exception:  # noqa: BLE001
                    for field in R0_IDENTITY_SOURCE_FIELDS:
                        invalid_source_by_scope[account.scope][field] = True
                    continue
                for field in R0_IDENTITY_SOURCE_FIELDS:
                    source_keys_by_scope[account.scope][field].update(keys[field])
                    source_ambiguity_by_scope[account.scope][field] = (
                        source_ambiguity_by_scope[account.scope][field]
                        or ambiguous[field]
                    )
                    invalid_source_by_scope[account.scope][field] = (
                        invalid_source_by_scope[account.scope][field]
                        or invalid[field]
                    )

    finance_maps, finance_state = load_r0_finance_identity(
        settings,
        set(source_keys_by_scope),
    )
    report = aggregate_r0_statuses(statuses)
    report["identity"] = evaluate_r0_identity(
        source_keys_by_scope,
        source_ambiguity_by_scope,
        invalid_source_by_scope,
        finance_maps,
        finance_state,
    )
    report["reportWindowAligned"] = report_window_aligned
    report["sourceImplementationGate"] = report["implementationGate"]
    report["implementationGate"] = False
    return report


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
        choices=("legacy", "f4", "r0", "r0-identity"),
        default="legacy",
        help="legacy F-0 or privacy-restricted F-4/R-0/R-0I gate",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=31,
        help="calendar window length (F-4 1..366; R-0 1..31)",
    )
    args = parser.parse_args(argv)
    if args.days < 1 or args.days > 366:
        parser.error("--days must be between 1 and 366")
    if args.mode in {"r0", "r0-identity"} and args.days > 31:
        parser.error("--days must be between 1 and 31 for R-0/R-0I")
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
    if args.mode == "r0":
        accounts, integration_access_incomplete = load_r0_accounts(settings)
        report = {
            "mode": "r0_return_reasons_gate",
            "authorizedIntegrationPresent": bool(accounts),
            "integrationAccessIncomplete": integration_access_incomplete,
        }
        report.update(run_r0_probe(accounts, settings, today, days=args.days))
        if not accounts:
            report["implementationGate"] = False
            report["completeSourceGate"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if args.mode == "r0-identity":
        accounts, integration_access_incomplete = load_r0_accounts(settings)
        report = {
            "mode": "r0_identity_crosswalk_gate",
            "authorizedIntegrationPresent": bool(accounts),
            "integrationAccessIncomplete": integration_access_incomplete,
        }
        report.update(
            run_r0_identity_probe(
                accounts,
                settings,
                today,
                days=args.days,
            )
        )
        if not accounts:
            report["completeSourceGate"] = False
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
