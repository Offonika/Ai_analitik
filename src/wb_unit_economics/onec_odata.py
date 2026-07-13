from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin
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
    period_field: str = ""
    period_filter_mode: str = "none"
    page_size: int | None = None
    min_page_size: int = 100
    order_by: str = ""
    select_fields: tuple[str, ...] = ()
    detail_mode: str = "full"
    request_timeout_seconds: float | None = None


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
    status: str = "loaded"
    checkpoint_path: Path | None = None
    retryable: bool = False
    next_cursor: str = ""
    reused_page_count: int = 0
    effective_page_size: int = 0
    detail_mode: str = "full"


@dataclass(frozen=True)
class OnecODataMetadataCheckResult:
    ok: bool
    status_code: int | None = None
    error: str = ""
    content_type: str = ""


class OnecODataConfigError(ValueError):
    pass


def check_onec_odata_metadata(
    settings: OnecODataSettings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> OnecODataMetadataCheckResult:
    """Validate that the read-only endpoint returns real OData EDMX metadata."""

    metadata_url = settings.base_url.rstrip("/") + "/$metadata"
    try:
        with httpx.Client(
            auth=(settings.username, settings.password),
            headers={"Accept": "application/xml, text/xml"},
            timeout=settings.timeout_seconds,
            verify=settings.verify_ssl,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get(metadata_url)
    except httpx.HTTPError as exc:
        return OnecODataMetadataCheckResult(
            ok=False,
            error=exc.__class__.__name__,
        )

    content_type = response.headers.get("content-type", "")
    if response.status_code != 200:
        return OnecODataMetadataCheckResult(
            ok=False,
            status_code=response.status_code,
            error=f"HTTP {response.status_code}",
            content_type=content_type,
        )
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        return OnecODataMetadataCheckResult(
            ok=False,
            status_code=response.status_code,
            error="invalid_metadata_xml",
            content_type=content_type,
        )
    root_name = root.tag.rsplit("}", 1)[-1]
    has_entity_container = any(
        item.tag.rsplit("}", 1)[-1] == "EntityContainer" for item in root.iter()
    )
    if root_name != "Edmx" or not has_entity_container:
        return OnecODataMetadataCheckResult(
            ok=False,
            status_code=response.status_code,
            error="invalid_metadata_edmx",
            content_type=content_type,
        )
    return OnecODataMetadataCheckResult(
        ok=True,
        status_code=response.status_code,
        content_type=content_type,
    )


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
        sample_id="tax_special_regime_notifications",
        collection_name="Document_УведомлениеОСпецрежимахНалогообложения",
        purpose="Уведомления 1С о спецрежимах налогообложения организаций.",
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
        period_filter_mode="nested_recordset_local",
        page_size=25,
        min_page_size=5,
        order_by="Recorder asc",
        request_timeout_seconds=60,
    ),
    OnecSampleCollection(
        sample_id="stock_by_warehouse",
        collection_name="AccumulationRegister_ЗапасыНаСкладах",
        purpose="Остатки по складам, полезны для сверки количества.",
        period_filter_mode="nested_recordset_local",
        page_size=25,
        min_page_size=5,
        order_by="Recorder asc",
        request_timeout_seconds=60,
    ),
)

TAX_PROFILE_SAMPLE_COLLECTIONS = (
    OnecSampleCollection(
        sample_id="tax_kinds",
        collection_name="Catalog_ВидыНалогов",
        purpose="Виды налогов 1С для подтверждения системы и объекта налога.",
        page_size=1000,
        select_fields=("Ref_Key", "Description", "DeletionMark"),
    ),
    OnecSampleCollection(
        sample_id="tax_accruals",
        collection_name="Document_НачислениеНалогов",
        purpose="Проведенные начисления налогов по организациям 1С.",
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=1000,
        order_by="Date asc,Ref_Key asc",
        select_fields=(
            "Ref_Key",
            "Date",
            "Posted",
            "DeletionMark",
            "Организация_Key",
        ),
        detail_mode="header_only",
    ),
    OnecSampleCollection(
        sample_id="tax_accrual_lines",
        collection_name="Document_НачислениеНалогов_Налоги",
        purpose="Виды налогов в проведенных начислениях 1С без денежных сумм.",
        page_size=1000,
        select_fields=("Ref_Key", "LineNumber", "ВидНалога_Key"),
    ),
    OnecSampleCollection(
        sample_id="vat_sales_book",
        collection_name="AccumulationRegister_НДСЗаписиКнигиПродаж_RecordType",
        purpose="Фактические ставки НДС в книге продаж по организациям 1С.",
        page_size=1000,
        order_by="Period asc",
        select_fields=(
            "Period",
            "LineNumber",
            "Active",
            "Организация_Key",
            "СтавкаНДС",
            "НДС",
        ),
    ),
    OnecSampleCollection(
        sample_id="vat_purchase_book",
        collection_name="AccumulationRegister_НДСЗаписиКнигиПокупок_RecordType",
        purpose="Книга покупок для диагностики входного НДС по организациям 1С.",
        page_size=1000,
        order_by="Period asc",
        select_fields=(
            "Period",
            "LineNumber",
            "Active",
            "Организация_Key",
            "СтавкаНДС",
            "НДС",
        ),
    ),
    OnecSampleCollection(
        sample_id="kudir",
        collection_name="AccumulationRegister_КнигаУчетаДоходовИРасходов_RecordType",
        purpose="Наличие КУДиР как дополнительный учетный признак УСН.",
        page_size=1000,
        order_by="Period asc",
        select_fields=(
            "Period",
            "LineNumber",
            "Active",
            "Организация_Key",
            "ВидЗаписи",
        ),
    ),
    OnecSampleCollection(
        sample_id="tax_registrations",
        collection_name="Catalog_РегистрацииВНалоговомОргане",
        purpose="Регистрация организации в налоговом органе для диагностики ставки.",
        page_size=1000,
        select_fields=("Ref_Key", "Code", "DeletionMark"),
    ),
)

INPUT_VAT_SAMPLE_COLLECTIONS = (
    OnecSampleCollection(
        sample_id="import_expenses",
        collection_name="Document_РасходыПриИмпорте",
        purpose=(
            "Проведенные расходы при импорте с товарными строками, разделами "
            "и признаками предъявления НДС к вычету."
        ),
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=20,
        min_page_size=2,
        order_by="Date asc,Ref_Key asc",
        select_fields=(
            "Ref_Key",
            "Date",
            "Number",
            "Posted",
            "DeletionMark",
            "Организация_Key",
            "СуммаДокумента",
            "НДСВключатьВСтоимость",
            "НДСПредъявленКВычету",
            "Запасы",
            "Разделы",
        ),
        detail_mode="financial_tables",
        request_timeout_seconds=120,
    ),
    OnecSampleCollection(
        sample_id="vat_presented",
        collection_name="AccumulationRegister_НДСПредъявленный_RecordType",
        purpose="Предъявленный входящий НДС по организациям и документам 1С.",
        page_size=1000,
        order_by="Period asc",
    ),
    OnecSampleCollection(
        sample_id="vat_deduction_documents",
        collection_name="Document_ОтражениеНДСКВычету",
        purpose="Проведенные документы отражения НДС к вычету.",
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=100,
        min_page_size=10,
        order_by="Date asc,Ref_Key asc",
        detail_mode="financial_tables",
    ),
    OnecSampleCollection(
        sample_id="vat_payment_confirmations",
        collection_name="Document_ПодтверждениеОплатыНДСВБюджет",
        purpose=(
            "Подтверждения оплаты импортного НДС в бюджет; банковский платеж "
            "сам по себе суммой вычета не считается."
        ),
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=100,
        min_page_size=10,
        order_by="Date asc,Ref_Key asc",
        detail_mode="financial_tables",
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
        period_filter_mode="nested_recordset_local",
        page_size=2,
        min_page_size=1,
        order_by="Recorder asc",
        request_timeout_seconds=30,
    ),
    OnecSampleCollection(
        sample_id="income_expense_register",
        collection_name="AccumulationRegister_ДоходыИРасходы",
        purpose="Доходы и расходы для сверки валовой прибыли.",
        period_filter_mode="nested_recordset_local",
        page_size=50,
        min_page_size=10,
        order_by="Recorder asc",
        request_timeout_seconds=30,
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
        period_filter_mode="nested_recordset_local",
        page_size=100,
        min_page_size=25,
        order_by="Recorder asc",
        request_timeout_seconds=30,
    ),
    OnecSampleCollection(
        sample_id="supplier_settlements",
        collection_name="AccumulationRegister_РасчетыСПоставщиками",
        purpose=(
            "Взаиморасчеты с поставщиками для контроля выплат и переносов "
            "по маркетплейсу."
        ),
        period_filter_mode="nested_recordset_local",
        page_size=100,
        min_page_size=25,
        order_by="Recorder asc",
        request_timeout_seconds=30,
    ),
    OnecSampleCollection(
        sample_id="commissioner_reports",
        collection_name="Document_ОтчетКомиссионера",
        purpose=(
            "Отчеты комиссионера с товарными строками: входящий номер "
            "маркетплейса, дата, сумма и детализация для сверки с 1С."
        ),
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=5,
        min_page_size=1,
        order_by="Date asc,Ref_Key asc",
        select_fields=(
            "Ref_Key",
            "Date",
            "Number",
            "Posted",
            "DeletionMark",
            "Комментарий",
            "НомерВходящегоДокумента",
            "Организация_Key",
            "Контрагент_Key",
            "СуммаДокумента",
            "СуммаДокументаВозврат",
            "СуммаДокументаСУчетомВознаграждения",
            "СуммаВознаграждения",
            "Запасы",
            "ЗапасыВозвраты",
        ),
        detail_mode="financial_tables",
        request_timeout_seconds=120,
    ),
    OnecSampleCollection(
        sample_id="expense_invoices",
        collection_name="Document_РасходнаяНакладная",
        purpose=(
            "Расходные накладные по уведомлениям о выкупе: номер WB отчета "
            "из комментария и сумма документа для точной сверки с 1С."
        ),
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=5,
        min_page_size=1,
        order_by="Date asc,Ref_Key asc",
        select_fields=(
            "Ref_Key",
            "Date",
            "Number",
            "Posted",
            "DeletionMark",
            "Комментарий",
            "ОснованиеПечати",
            "НомерВходящегоДокумента",
            "СуммаДокумента",
        ),
        detail_mode="header_only",
        request_timeout_seconds=120,
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
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=20,
        min_page_size=2,
        order_by="Date asc,Ref_Key asc",
        select_fields=(
            "Ref_Key",
            "Date",
            "Number",
            "Posted",
            "DeletionMark",
            "Организация_Key",
            "Контрагент_Key",
            "ДатаВходящегоДокумента",
            "НомерВходящегоДокумента",
            "Комментарий",
            "СуммаДокумента",
            "Расходы",
            "Запасы",
        ),
        detail_mode="financial_tables",
        request_timeout_seconds=120,
    ),
    OnecSampleCollection(
        sample_id="supplier_receipts",
        collection_name="Document_ПоступлениеТоваровУслуг",
        purpose="Поступления/УПД услуг WB для сверки расходов маркетплейса.",
        params={"$filter": "Posted eq true"},
        period_filter_mode="local_document_date",
        page_size=20,
        min_page_size=2,
        order_by="Date asc,Ref_Key asc",
        request_timeout_seconds=120,
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
        next_link: str = "",
        timeout_seconds: float | None = None,
    ) -> tuple[dict[str, Any], int]:
        request_params = {"$format": "json", "$top": str(top)}
        if skip > 0:
            request_params["$skip"] = str(skip)
        if params:
            request_params.update(params)
        request_url = self._collection_url(collection_name)
        if next_link:
            request_url = urljoin(f"{self._settings.base_url}/", next_link)
            request_params = {}
        response = self._client.get(
            request_url,
            params=request_params,
            timeout=timeout_seconds or self._settings.timeout_seconds,
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
    retry_attempts: int = 3,
    retry_delay_seconds: float = 2.0,
    period_start: date | None = None,
    period_end: date | None = None,
    resume_from_dir: Path | None = None,
    source_identity: str = "",
) -> OnecSampleExportResult:
    max_pages = max(1, max_pages)
    retry_attempts = max(0, retry_attempts)
    retry_delay_seconds = max(0.0, retry_delay_seconds)
    requested_top = max(1, int(top))
    page_size = min(requested_top, collection.page_size or requested_top)
    min_page_size = min(page_size, max(1, collection.min_page_size))
    request_params = _collection_request_params(
        collection,
        period_start=period_start,
        period_end=period_end,
    )
    query_contract = {
        "collection_name": collection.collection_name,
        "params": dict(sorted(request_params.items())),
        "source_identity": source_identity,
        "period_start": period_start.isoformat() if period_start else "",
        "period_end": period_end.isoformat() if period_end else "",
        "period_filter_mode": collection.period_filter_mode,
    }
    query_contract_hash = raw_payload_hash(query_contract)
    compatible_query_contract_hashes = {
        query_contract_hash,
        raw_payload_hash(
            {
                **query_contract,
                # Compatibility with the short-lived 2026-07-10 checkpoint
                # contract. detail_mode is lineage metadata; $select already
                # captures every material wire-level projection change.
                "detail_mode": collection.detail_mode,
            }
        ),
    }
    collection_dir = output_dir / collection.sample_id
    collection_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = collection_dir / "manifest.json"
    page_meta, next_skip, next_link, checkpoint_complete = (
        _restore_collection_checkpoint(
            resume_from_dir=resume_from_dir,
            collection=collection,
            collection_dir=collection_dir,
            compatible_query_contract_hashes=compatible_query_contract_hashes,
        )
    )
    reused_page_count = len(page_meta)
    page_limit = reused_page_count + max_pages
    row_count = sum(int(item.get("row_count", 0)) for item in page_meta)
    last_status_code: int | None = None
    complete = checkpoint_complete
    error = ""
    retryable = False

    while not complete and len(page_meta) < page_limit:
        try:
            retry_read_timeouts = not (page_size > min_page_size and not next_link)
            payload, status_code = _fetch_collection_with_retries(
                client,
                collection.collection_name,
                top=page_size,
                skip=next_skip,
                params=request_params,
                next_link=next_link,
                timeout_seconds=collection.request_timeout_seconds,
                retry_attempts=retry_attempts,
                retry_delay_seconds=retry_delay_seconds,
                retry_read_timeouts=retry_read_timeouts,
            )
        except httpx.ReadTimeout as exc:
            smaller_page_size = _smaller_page_size(page_size, min_page_size)
            if smaller_page_size < page_size and not next_link:
                page_size = smaller_page_size
                continue
            error = exc.__class__.__name__
            retryable = True
            break
        except httpx.HTTPStatusError as exc:
            last_status_code = exc.response.status_code
            error = f"HTTP {exc.response.status_code}"
            retryable = exc.response.status_code in RETRYABLE_STATUS_CODES
            break
        except (httpx.HTTPError, ValueError) as exc:
            error = exc.__class__.__name__
            retryable = isinstance(exc, httpx.HTTPError)
            break

        rows = extract_odata_rows(payload)
        last_status_code = status_code
        page_index = len(page_meta) + 1
        page_path = collection_dir / f"page_{page_index:06d}.raw.json"
        _write_json(page_path, payload)
        returned_next_link = _extract_next_link(payload)
        page_meta.append(
            {
                "page_index": page_index,
                "skip": next_skip,
                "requested_top": page_size,
                "row_count": len(rows),
                "status_code": status_code,
                "file": page_path.name,
                "file_sha256": _file_sha256(page_path),
                "payload_hash": raw_payload_hash(payload),
                "reused": False,
            }
        )
        row_count += len(rows)
        next_skip += len(rows)
        next_link = returned_next_link
        _write_collection_manifest(
            checkpoint_path,
            collection=collection,
            status="running",
            query_contract_hash=query_contract_hash,
            request_params=request_params,
            pages=page_meta,
            next_skip=next_skip,
            next_link=next_link,
            retryable=True,
            error="",
            effective_page_size=page_size,
        )
        if not next_link and len(rows) < page_size:
            complete = True
            break

    if not complete and not error and len(page_meta) >= page_limit:
        error = "max_pages_reached"
        retryable = True

    status = "loaded" if complete else ("partial_source" if page_meta else "failed")
    output_path: Path | None = None
    payload_hash = ""
    if complete:
        output_path = output_dir / f"{collection.sample_id}.raw.json"
        _write_combined_output(
            output_path,
            collection_dir=collection_dir,
            pages=page_meta,
        )
        payload_hash = _file_sha256(output_path)
        retryable = False
        error = ""

    _write_collection_manifest(
        checkpoint_path,
        collection=collection,
        status=status,
        query_contract_hash=query_contract_hash,
        request_params=request_params,
        pages=page_meta,
        next_skip=next_skip,
        next_link=next_link,
        retryable=retryable,
        error=error,
        effective_page_size=page_size,
        output_path=output_path,
        raw_payload_hash=payload_hash,
    )
    next_cursor = next_link or (f"skip:{next_skip}" if retryable else "")
    return OnecSampleExportResult(
        sample_id=collection.sample_id,
        collection_name=collection.collection_name,
        ok=complete,
        row_count=row_count,
        page_count=len(page_meta),
        raw_payload_hash=payload_hash or _file_sha256(checkpoint_path),
        output_path=output_path,
        status_code=last_status_code,
        error=error,
        status=status,
        checkpoint_path=checkpoint_path,
        retryable=retryable,
        next_cursor=next_cursor,
        reused_page_count=reused_page_count,
        effective_page_size=page_size,
        detail_mode=collection.detail_mode,
    )


def export_onec_samples(
    settings: OnecODataSettings,
    collections: Iterable[OnecSampleCollection],
    output_dir: Path,
    *,
    top: int = 25,
    max_pages: int = 1,
    retry_attempts: int = 3,
    retry_delay_seconds: float = 2.0,
    period_start: date | None = None,
    period_end: date | None = None,
    resume_from_dir: Path | None = None,
    source_identity: str = "",
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
                period_start=period_start,
                period_end=period_end,
                resume_from_dir=resume_from_dir,
                source_identity=source_identity,
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
    next_link: str,
    timeout_seconds: float | None,
    retry_attempts: int,
    retry_delay_seconds: float,
    retry_read_timeouts: bool,
) -> tuple[dict[str, Any], int]:
    for attempt in range(retry_attempts + 1):
        try:
            return client.fetch_collection(
                collection_name,
                top=top,
                skip=skip,
                params=params,
                next_link=next_link,
                timeout_seconds=timeout_seconds,
            )
        except httpx.HTTPStatusError as exc:
            if not _should_retry_status(
                exc.response.status_code,
                attempt,
                retry_attempts,
            ):
                raise
            _sleep_before_retry(_retry_delay(retry_delay_seconds, attempt))
        except httpx.ReadTimeout:
            if not retry_read_timeouts or attempt >= retry_attempts:
                raise
            _sleep_before_retry(_retry_delay(retry_delay_seconds, attempt))
        except httpx.HTTPError:
            if attempt >= retry_attempts:
                raise
            _sleep_before_retry(_retry_delay(retry_delay_seconds, attempt))
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


def _retry_delay(base_delay_seconds: float, attempt: int) -> float:
    multipliers = (1.0, 2.5, 7.5)
    return base_delay_seconds * multipliers[min(attempt, len(multipliers) - 1)]


def _collection_request_params(
    collection: OnecSampleCollection,
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, str]:
    params = dict(collection.params)
    filters: list[str] = []
    existing_filter = params.pop("$filter", "").strip()
    if existing_filter:
        filters.append(existing_filter)
    if collection.period_field and period_start is not None:
        filters.append(
            f"{collection.period_field} ge "
            f"datetime'{period_start.isoformat()}T00:00:00'"
        )
    if collection.period_field and period_end is not None:
        exclusive_end = period_end + timedelta(days=1)
        filters.append(
            f"{collection.period_field} lt "
            f"datetime'{exclusive_end.isoformat()}T00:00:00'"
        )
    if filters:
        params["$filter"] = " and ".join(filters)
    if collection.order_by and "$orderby" not in params:
        params["$orderby"] = collection.order_by
    if collection.select_fields and "$select" not in params:
        params["$select"] = ",".join(collection.select_fields)
    return params


def _smaller_page_size(page_size: int, minimum: int) -> int:
    if page_size > 500:
        candidate = 500
    elif page_size > 250:
        candidate = 250
    elif page_size > 100:
        candidate = 100
    else:
        candidate = minimum
    return max(minimum, min(page_size, candidate))


def _extract_next_link(payload: Mapping[str, Any]) -> str:
    for key in ("@odata.nextLink", "odata.nextLink"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("d")
    if isinstance(data, dict):
        value = data.get("__next")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _restore_collection_checkpoint(
    *,
    resume_from_dir: Path | None,
    collection: OnecSampleCollection,
    collection_dir: Path,
    compatible_query_contract_hashes: set[str],
) -> tuple[list[dict[str, Any]], int, str, bool]:
    if resume_from_dir is None:
        return [], 0, "", False
    source_dir = resume_from_dir / collection.sample_id
    manifest_path = source_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], 0, "", False
    if not isinstance(manifest, dict):
        return [], 0, "", False
    checkpoint_status = str(manifest.get("status") or "")
    if checkpoint_status not in {"loaded", "running", "partial_source", "failed"}:
        return [], 0, "", False
    if manifest.get("query_contract_hash") not in compatible_query_contract_hashes:
        return [], 0, "", False
    raw_pages = manifest.get("pages")
    if not isinstance(raw_pages, list):
        return [], 0, "", False

    validated: list[tuple[dict[str, Any], Path, dict[str, Any]]] = []
    for expected_index, raw_page in enumerate(raw_pages, 1):
        if not isinstance(raw_page, dict):
            return [], 0, "", False
        file_name = str(raw_page.get("file") or "")
        if not file_name or Path(file_name).name != file_name:
            return [], 0, "", False
        source_path = source_dir / file_name
        expected_hash = str(raw_page.get("file_sha256") or "")
        if not source_path.is_file() or _file_sha256(source_path) != expected_hash:
            return [], 0, "", False
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], 0, "", False
        if not isinstance(payload, dict):
            return [], 0, "", False
        rows = extract_odata_rows(payload)
        if len(rows) != int(raw_page.get("row_count", -1)):
            return [], 0, "", False
        normalized = dict(raw_page)
        normalized["page_index"] = expected_index
        normalized["reused"] = True
        validated.append((normalized, source_path, payload))

    pages: list[dict[str, Any]] = []
    next_skip = 0
    for page, source_path, _payload in validated:
        destination = collection_dir / source_path.name
        _copy_or_link(source_path, destination)
        pages.append(page)
        next_skip = max(
            next_skip,
            int(page.get("skip", 0)) + int(page.get("row_count", 0)),
        )
    next_link = str(manifest.get("next_link") or "")
    return pages, next_skip, next_link, checkpoint_status == "loaded"


def _copy_or_link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _write_collection_manifest(
    path: Path,
    *,
    collection: OnecSampleCollection,
    status: str,
    query_contract_hash: str,
    request_params: Mapping[str, str],
    pages: list[dict[str, Any]],
    next_skip: int,
    next_link: str,
    retryable: bool,
    error: str,
    effective_page_size: int,
    output_path: Path | None = None,
    raw_payload_hash: str = "",
) -> None:
    _write_json(
        path,
        {
            "version": 1,
            "source": "1c_odata",
            "read_boundary": "GET only",
            "sample_id": collection.sample_id,
            "collection_name": collection.collection_name,
            "status": status,
            "query_contract_hash": query_contract_hash,
            "request_params": dict(sorted(request_params.items())),
            "period_filter_mode": collection.period_filter_mode,
            "detail_mode": collection.detail_mode,
            "row_count": sum(int(item.get("row_count", 0)) for item in pages),
            "page_count": len(pages),
            "effective_page_size": effective_page_size,
            "next_skip": next_skip,
            "next_link": next_link,
            "retryable": retryable,
            "error": error,
            "pages": pages,
            "output_file": output_path.name if output_path else None,
            "raw_payload_hash": raw_payload_hash,
            "updated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        },
    )


def _write_combined_output(
    output_path: Path,
    *,
    collection_dir: Path,
    pages: list[dict[str, Any]],
) -> None:
    shape = "value"
    if pages:
        first_payload = json.loads(
            (collection_dir / str(pages[0]["file"])).read_text(encoding="utf-8")
        )
        data = first_payload.get("d") if isinstance(first_payload, dict) else None
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            shape = "d_results"
        elif isinstance(data, list):
            shape = "d_list"

    temporary = output_path.with_name(f".{output_path.name}.tmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8") as handle:
        if shape == "d_results":
            handle.write('{"d":{"results":[')
        elif shape == "d_list":
            handle.write('{"d":[')
        else:
            handle.write('{"value":[')
        first_row = True
        for page in pages:
            payload = json.loads(
                (collection_dir / str(page["file"])).read_text(encoding="utf-8")
            )
            for row in extract_odata_rows(payload):
                if not first_row:
                    handle.write(",")
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    )
                )
                first_row = False
        if shape == "d_results":
            handle.write("]}")
        else:
            handle.write("]")
        handle.write(',"_source_pages":')
        handle.write(
            json.dumps(pages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        handle.write("}")
    os.replace(temporary, output_path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
                "status": item.status,
                "checkpoint_file": (
                    str(item.checkpoint_path.relative_to(path.parent))
                    if item.checkpoint_path
                    else None
                ),
                "retryable": item.retryable,
                "next_cursor": item.next_cursor,
                "reused_page_count": item.reused_page_count,
                "effective_page_size": item.effective_page_size,
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


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
