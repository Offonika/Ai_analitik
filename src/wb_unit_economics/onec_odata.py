from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

BASE_URL_KEYS = (
    "ONEC_ODATA_BASE_URL",
    "ONEC_ODATA_URL",
    "ONEC_ODATA_ENDPOINT",
)
USERNAME_KEYS = (
    "ONEC_ODATA_USERNAME",
    "ONEC_ODATA_USER",
    "ONEC_ODATA_LOGIN",
)
PASSWORD_KEYS = (
    "ONEC_ODATA_PASSWORD",
    "ONEC_ODATA_PASS",
)
VERIFY_SSL_KEYS = (
    "ONEC_ODATA_VERIFY_SSL",
    "ONEC_ODATA_VERIFY_TLS",
)
TIMEOUT_KEYS = (
    "ONEC_ODATA_TIMEOUT_SECONDS",
    "ONEC_ODATA_TIMEOUT",
)
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class OnecODataSettings:
    base_url: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    timeout_seconds: float = 30.0
    verify_ssl: bool = True

    @classmethod
    def from_env_file(cls, env_file: Path = Path(".env")) -> OnecODataSettings:
        values = _load_env_values(env_file)
        values.update(os.environ)

        missing: list[str] = []
        base_url = _first_present(values, BASE_URL_KEYS)
        username = _first_present(values, USERNAME_KEYS)
        password = _first_present(values, PASSWORD_KEYS)
        if not base_url:
            missing.append(BASE_URL_KEYS[0])
        if not username:
            missing.append(USERNAME_KEYS[0])
        if not password:
            missing.append(PASSWORD_KEYS[0])
        if missing:
            names = ", ".join(missing)
            raise OnecODataConfigError(f"Missing required 1C OData variables: {names}")

        timeout_value = _first_present(values, TIMEOUT_KEYS)
        verify_value = _first_present(values, VERIFY_SSL_KEYS)
        return cls(
            base_url=base_url.rstrip("/"),
            username=username,
            password=password,
            timeout_seconds=float(timeout_value) if timeout_value else 30.0,
            verify_ssl=_parse_bool(verify_value, default=True),
        )


@dataclass(frozen=True)
class OnecSampleCollection:
    sample_id: str
    collection_name: str
    purpose: str
    params: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OnecSampleExportResult:
    sample_id: str
    collection_name: str
    ok: bool
    row_count: int
    page_count: int = 0
    raw_payload_hash: str = ""
    output_path: Path | None = None
    status_code: int | None = None
    error: str = ""


class OnecODataConfigError(ValueError):
    pass


DEFAULT_SAMPLE_COLLECTIONS = (
    OnecSampleCollection(
        sample_id="nomenclature",
        collection_name="Catalog_Номенклатура",
        purpose="Товары, артикулы и идентификаторы 1С.",
    ),
    OnecSampleCollection(
        sample_id="organizations",
        collection_name="Catalog_Организации",
        purpose="Организации 1С для связки с кабинетами WB.",
    ),
    OnecSampleCollection(
        sample_id="characteristics",
        collection_name="Catalog_ХарактеристикиНоменклатуры",
        purpose="Характеристики товаров, если они используются в учете.",
    ),
    OnecSampleCollection(
        sample_id="barcodes",
        collection_name="InformationRegister_ШтрихкодыНоменклатуры",
        purpose="Штрихкоды для маппинга WB <-> 1С.",
    ),
    OnecSampleCollection(
        sample_id="prices",
        collection_name="InformationRegister_ЦеныНоменклатуры",
        purpose="Цены номенклатуры для сверки и диагностики.",
    ),
    OnecSampleCollection(
        sample_id="stock_movements",
        collection_name="AccumulationRegister_Запасы",
        purpose="Количество, сумма и стоимость: основной кандидат для себестоимости.",
    ),
    OnecSampleCollection(
        sample_id="stock_by_warehouse",
        collection_name="AccumulationRegister_ЗапасыНаСкладах",
        purpose="Остатки по складам, полезны для сверки количества.",
    ),
)

GROSS_PROFIT_SAMPLE_COLLECTIONS = (
    OnecSampleCollection(
        sample_id="sales_register",
        collection_name="AccumulationRegister_Продажи",
        purpose=(
            "Продажи, выручка и себестоимость продаж по номенклатуре, "
            "характеристике и организации."
        ),
    ),
    OnecSampleCollection(
        sample_id="income_expense_register",
        collection_name="AccumulationRegister_ДоходыИРасходы",
        purpose="Доходы и расходы для сверки валовой прибыли.",
    ),
    OnecSampleCollection(
        sample_id="product_batches",
        collection_name="AccumulationRegister_ПартииТоваров",
        purpose="Партии товаров для проверки партионной себестоимости.",
    ),
    OnecSampleCollection(
        sample_id="product_batches_usn",
        collection_name="AccumulationRegister_ПартииТоваровУСН",
        purpose="Партии товаров УСН.",
    ),
    OnecSampleCollection(
        sample_id="product_batches_kudir",
        collection_name="AccumulationRegister_ПартииТоваровДляКУДиР",
        purpose="Партии товаров для КУДиР.",
    ),
    OnecSampleCollection(
        sample_id="customer_settlements",
        collection_name="AccumulationRegister_РасчетыСПокупателями",
        purpose=(
            "Взаиморасчеты с покупателями/комиссионерами для контроля "
            "суммы к перечислению по отчетам маркетплейса."
        ),
    ),
    OnecSampleCollection(
        sample_id="supplier_settlements",
        collection_name="AccumulationRegister_РасчетыСПоставщиками",
        purpose=(
            "Взаиморасчеты с поставщиками для контроля выплат и переносов "
            "по маркетплейсу."
        ),
    ),
    OnecSampleCollection(
        sample_id="commissioner_reports",
        collection_name="Document_ОтчетКомиссионера",
        purpose=(
            "Заголовки отчетов комиссионера: входящий номер WB reportId, "
            "дата и сумма документа для точной сверки с 1С."
        ),
    ),
    OnecSampleCollection(
        sample_id="expense_invoices",
        collection_name="Document_РасходнаяНакладная",
        purpose=(
            "Расходные накладные по уведомлениям о выкупе: номер WB отчета "
            "из комментария и сумма документа для точной сверки с 1С."
        ),
    ),
)

SERVICE_SAMPLE_COLLECTIONS = (
    OnecSampleCollection(
        sample_id="incoming_invoices",
        collection_name="Document_ПриходнаяНакладная",
        purpose=(
            "Приходные накладные Ozon: поступления от поставщика и возвраты "
            "от комиссионера для контроля расходов Ozon."
        ),
    ),
    OnecSampleCollection(
        sample_id="supplier_receipts",
        collection_name="Document_ПоступлениеТоваровУслуг",
        purpose="Поступления/УПД услуг WB для сверки расходов маркетплейса.",
    ),
    OnecSampleCollection(
        sample_id="supplier_receipt_expenses",
        collection_name="Document_ПоступлениеТоваровУслуг_Услуги",
        purpose="Табличная часть услуг в поступлениях/УПД WB.",
    ),
)


class OnecODataClient:
    """Small read-only client for the standard 1C OData interface."""

    def __init__(
        self,
        settings: OnecODataSettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.Client(
            auth=(settings.username, settings.password),
            headers={"Accept": "application/json"},
            timeout=settings.timeout_seconds,
            verify=settings.verify_ssl,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OnecODataClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_collection(
        self,
        collection_name: str,
        *,
        top: int,
        skip: int = 0,
        params: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        request_params = {"$format": "json", "$top": str(top)}
        if skip > 0:
            request_params["$skip"] = str(skip)
        if params:
            request_params.update(params)
        response = self._client.get(
            self._collection_url(collection_name),
            params=request_params,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected 1C OData JSON payload")
        return payload, response.status_code

    def _collection_url(self, collection_name: str) -> str:
        encoded = quote(collection_name, safe="")
        return f"{self._settings.base_url}/{encoded}"


def export_collection_sample(
    client: OnecODataClient,
    collection: OnecSampleCollection,
    output_dir: Path,
    *,
    top: int,
    max_pages: int = 1,
    retry_attempts: int = 2,
    retry_delay_seconds: float = 2.0,
) -> OnecSampleExportResult:
    max_pages = max(1, max_pages)
    retry_attempts = max(0, retry_attempts)
    retry_delay_seconds = max(0.0, retry_delay_seconds)
    all_rows: list[Any] = []
    page_meta: list[dict[str, Any]] = []
    last_payload: dict[str, Any] | None = None
    last_status_code: int | None = None
    try:
        for page_index in range(max_pages):
            skip = page_index * top
            payload, status_code = _fetch_collection_with_retries(
                client,
                collection.collection_name,
                top=top,
                skip=skip,
                params=collection.params,
                retry_attempts=retry_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
            rows = extract_odata_rows(payload)
            all_rows.extend(rows)
            last_payload = payload
            last_status_code = status_code
            page_meta.append(
                {
                    "page_index": page_index + 1,
                    "skip": skip,
                    "row_count": len(rows),
                    "status_code": status_code,
                }
            )
            if len(rows) < top:
                break
    except httpx.HTTPStatusError as exc:
        return OnecSampleExportResult(
            sample_id=collection.sample_id,
            collection_name=collection.collection_name,
            ok=False,
            row_count=0,
            page_count=len(page_meta),
            status_code=exc.response.status_code,
            error=f"HTTP {exc.response.status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return OnecSampleExportResult(
            sample_id=collection.sample_id,
            collection_name=collection.collection_name,
            ok=False,
            row_count=0,
            page_count=len(page_meta),
            error=exc.__class__.__name__,
        )

    payload = _combined_payload(last_payload or {}, all_rows, page_meta)
    payload_hash = raw_payload_hash(payload)
    output_path = output_dir / f"{collection.sample_id}.raw.json"
    _write_json(output_path, payload)
    return OnecSampleExportResult(
        sample_id=collection.sample_id,
        collection_name=collection.collection_name,
        ok=True,
        row_count=len(all_rows),
        page_count=len(page_meta),
        raw_payload_hash=payload_hash,
        output_path=output_path,
        status_code=last_status_code,
    )


def export_onec_samples(
    settings: OnecODataSettings,
    collections: Iterable[OnecSampleCollection],
    output_dir: Path,
    *,
    top: int = 25,
    max_pages: int = 1,
    retry_attempts: int = 2,
    retry_delay_seconds: float = 2.0,
) -> list[OnecSampleExportResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with OnecODataClient(settings) as client:
        results = [
            export_collection_sample(
                client,
                collection,
                output_dir,
                top=top,
                max_pages=max_pages,
                retry_attempts=retry_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
            for collection in collections
        ]
    _write_manifest(output_dir / "manifest.json", results, top=top, max_pages=max_pages)
    return results


def _fetch_collection_with_retries(
    client: OnecODataClient,
    collection_name: str,
    *,
    top: int,
    skip: int,
    params: Mapping[str, str],
    retry_attempts: int,
    retry_delay_seconds: float,
) -> tuple[dict[str, Any], int]:
    for attempt in range(retry_attempts + 1):
        try:
            return client.fetch_collection(
                collection_name,
                top=top,
                skip=skip,
                params=params,
            )
        except httpx.HTTPStatusError as exc:
            if not _should_retry_status(
                exc.response.status_code,
                attempt,
                retry_attempts,
            ):
                raise
            _sleep_before_retry(retry_delay_seconds)
        except httpx.HTTPError:
            if attempt >= retry_attempts:
                raise
            _sleep_before_retry(retry_delay_seconds)
    raise RuntimeError("unreachable retry state")


def _should_retry_status(
    status_code: int,
    attempt: int,
    retry_attempts: int,
) -> bool:
    return status_code in RETRYABLE_STATUS_CODES and attempt < retry_attempts


def _sleep_before_retry(delay_seconds: float) -> None:
    if delay_seconds > 0:
        time.sleep(delay_seconds)


def extract_odata_rows(payload: Mapping[str, Any]) -> list[Any]:
    value = payload.get("value")
    if isinstance(value, list):
        return value

    data = payload.get("d")
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return results
    if isinstance(data, list):
        return data
    return []


def raw_payload_hash(payload: Mapping[str, Any]) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _combined_payload(
    last_payload: Mapping[str, Any],
    rows: list[Any],
    page_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    source_pages = {"_source_pages": page_meta}
    if "value" in last_payload:
        return {"value": rows, **source_pages}
    data = last_payload.get("d")
    if isinstance(data, dict) and "results" in data:
        return {"d": {"results": rows}, **source_pages}
    if isinstance(data, list):
        return {"d": rows, **source_pages}
    return {"value": rows, **source_pages}


def _write_manifest(
    path: Path,
    results: list[OnecSampleExportResult],
    *,
    top: int,
    max_pages: int,
) -> None:
    generated_at = datetime.now(tz=MOSCOW_TZ).isoformat()
    manifest = {
        "generated_at": generated_at,
        "top": top,
        "max_pages": max_pages,
        "source": "1c_odata",
        "read_boundary": "GET only",
        "results": [
            {
                "sample_id": item.sample_id,
                "collection_name": item.collection_name,
                "ok": item.ok,
                "row_count": item.row_count,
                "page_count": item.page_count,
                "status_code": item.status_code,
                "raw_payload_hash": item.raw_payload_hash,
                "output_file": item.output_path.name if item.output_path else None,
                "error": item.error,
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _first_present(values: Mapping[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = values.get(key, "").strip()
        if value:
            return value
    return ""


def _parse_bool(value: str, *, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}
