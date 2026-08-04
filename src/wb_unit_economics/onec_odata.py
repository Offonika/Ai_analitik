from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
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
ONEC_METADATA_SCHEDULED_TIMEOUT_SECONDS = 60.0
ONEC_METADATA_RETRY_DELAYS_SECONDS = (5.0, 15.0)
ONEC_METADATA_RETRYABLE_ERROR_TYPES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "PoolTimeout",
        "ProxyError",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "WriteError",
        "WriteTimeout",
    }
)


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
    attempt_count: int = 1
    timeout_seconds: float | None = None


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


def check_onec_odata_metadata_with_retry(
    settings: OnecODataSettings,
    *,
    timeout_seconds: float = ONEC_METADATA_SCHEDULED_TIMEOUT_SECONDS,
    retry_delays_seconds: tuple[float, ...] = ONEC_METADATA_RETRY_DELAYS_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> OnecODataMetadataCheckResult:
    """Retry only transient scheduled metadata failures before source reads."""

    effective_timeout = max(float(timeout_seconds), 0.001)
    delays = tuple(max(float(delay), 0.0) for delay in retry_delays_seconds)
    retry_settings = replace(settings, timeout_seconds=effective_timeout)
    for attempt_count in range(1, len(delays) + 2):
        result = replace(
            check_onec_odata_metadata(retry_settings, transport=transport),
            attempt_count=attempt_count,
            timeout_seconds=effective_timeout,
        )
        retry_allowed = (
            result.status_code in RETRYABLE_STATUS_CODES
            or result.error in ONEC_METADATA_RETRYABLE_ERROR_TYPES
        )
        if result.ok or not retry_allowed or attempt_count > len(delays):
            return result
        delay = delays[attempt_count - 1]
        if delay > 0:
            time.sleep(delay)
    raise RuntimeError("unreachable metadata retry state")


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
        sample_id="tax_system_settings",
        collection_name="InformationRegister_СистемыНалогообложенияОрганизаций",
        purpose=(
            "Периодические настройки системы, объекта и ставки налога "
            "отдельно по каждой организации 1С."
        ),
        page_size=1000,
        order_by="Period asc,Организация_Key asc",
        select_fields=(
            "Period",
            "Организация_Key",
            "СистемаНалогообложения",
            "ПлательщикУСН",
            "ОбъектНалогообложения",
            "СтавкаНалога",
            "ПовышеннаяСтавкаНалога",
            "ПлательщикНДСПрименяющийУСН",
            "ПлательщикНДС",
        ),
    ),
    OnecSampleCollection(
        sample_id="vat_settings",
        collection_name="InformationRegister_НастройкиУчетаНДС",
        purpose=(
            "Периодические настройки освобождения от НДС и вида ставки "
            "отдельно по каждой организации 1С."
        ),
        page_size=1000,
        order_by="Period asc,Организация_Key asc",
        select_fields=(
            "Period",
            "Организация_Key",
            "ПрименяетсяОсвобождениеОтУплатыНДС",
            "СтавкаНалогообложенияПриУСН",
        ),
    ),
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
            "Покупатель_Key",
            "СтавкаНДС",
            "СуммаБезНДС",
            "НДС",
            "ДатаСобытия",
            "НомерСчетаФактурыНаАванс",
            "ДатаСчетаФактурыНаАванс",
            "НомерДокументаОплаты",
            "ДатаДокументаОплаты",
            "ЗаписьДополнительногоЛиста",
            "Исправление",
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
            "Поставщик_Key",
            "СтавкаНДС",
            "СуммаБезНДС",
            "НДС",
            "ДатаСобытия",
            "НомерСчетаФактуры",
            "ДатаСчетаФактуры",
            "НомерДокументаОплаты",
            "ДатаДокументаОплаты",
            "ЗаписьДополнительногоЛиста",
        ),
    ),
    OnecSampleCollection(
        sample_id="kudir",
        collection_name="AccumulationRegister_КнигаУчетаДоходовИРасходов_RecordType",
        purpose=(
            "КУДиР УСН: признанные доходы и расходы для налоговой базы, "
            "минимального налога и сверки налоговой нагрузки ИП."
        ),
        page_size=1000,
        order_by="Period asc",
        select_fields=(
            "Period",
            "LineNumber",
            "Active",
            "Организация_Key",
            "ВидЗаписи",
            "ДоходБаза",
            "ДоходВсего",
            "РасходБаза",
            "РасходВсего",
            "НДС",
            "ВзносыПодлежащиеУплате",
            "Содержание",
            "ДатаПервичногоДокумента",
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
            "ВидОперации",
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

ACCOUNTING_REPORT_SAMPLE_COLLECTIONS = (
    DEFAULT_SAMPLE_COLLECTIONS[0],  # nomenclature for RWB service labels
    DEFAULT_SAMPLE_COLLECTIONS[1],  # organizations
    DEFAULT_SAMPLE_COLLECTIONS[2],  # special-tax notifications
    *TAX_PROFILE_SAMPLE_COLLECTIONS,
    OnecSampleCollection(
        sample_id="accounting_counterparties",
        collection_name="Catalog_Контрагенты",
        purpose=(
            "Read-only справочник контрагентов для подтвержденной "
            "расшифровки банковских поступлений по маркетплейсам."
        ),
        page_size=1000,
        select_fields=("Ref_Key", "Description", "DeletionMark"),
    ),
    OnecSampleCollection(
        sample_id="accounting_chart",
        collection_name="ChartOfAccounts_Управленческий",
        purpose="План счетов управленческого учета для нормализации ОСВ.",
        page_size=1000,
        select_fields=("Ref_Key", "Code", "Description", "DeletionMark"),
    ),
    OnecSampleCollection(
        sample_id="accounting_register_records",
        collection_name="AccountingRegister_Управленческий_RecordType",
        purpose="Проводки управленческого регистра как fallback ОСВ.",
        period_filter_mode="local_accounting_period",
        page_size=1000,
        min_page_size=100,
        request_timeout_seconds=120,
    ),
    OnecSampleCollection(
        sample_id="accounting_month_close_docs",
        collection_name="Document_ЗакрытиеМесяца",
        purpose="Проведенные документы закрытия месяца.",
        period_filter_mode="local_document_date",
        page_size=500,
    ),
    OnecSampleCollection(
        sample_id="accounting_taxes",
        collection_name="AccumulationRegister_РасчетыПоНалогам_RecordType",
        purpose="Движения расчетов по налогам.",
        period_filter_mode="local_accounting_period",
        page_size=5000,
    ),
    OnecSampleCollection(
        sample_id="accounting_ens",
        collection_name="AccumulationRegister_РасчетыПоЕдиномуНалоговомуСчету_RecordType",
        purpose="Движения по единому налоговому счету.",
        period_filter_mode="local_accounting_period",
        page_size=5000,
    ),
    OnecSampleCollection(
        sample_id="accounting_taxes_on_ens",
        collection_name="AccumulationRegister_РасчетыПоНалогамНаЕдиномНалоговомСчете_RecordType",
        purpose="Детализация налогов на ЕНС.",
        period_filter_mode="local_accounting_period",
        page_size=5000,
    ),
    OnecSampleCollection(
        sample_id="accounting_ens_sanctions",
        collection_name="AccumulationRegister_РасчетыПоСанкциямНаЕдиномНалоговомСчете_RecordType",
        purpose="Санкции на едином налоговом счете.",
        period_filter_mode="local_accounting_period",
        page_size=5000,
    ),
    OnecSampleCollection(
        sample_id="accounting_bank_in",
        collection_name="Document_ПоступлениеНаСчет",
        purpose="Поступления на расчетный счет.",
        period_filter_mode="local_document_date",
        page_size=1000,
    ),
    OnecSampleCollection(
        sample_id="accounting_bank_out",
        collection_name="Document_РасходСоСчета",
        purpose="Расходы с расчетного счета.",
        period_filter_mode="local_document_date",
        page_size=1000,
    ),
    OnecSampleCollection(
        sample_id="accounting_manual_operations",
        collection_name="Document_Операция",
        purpose="Ручные операции за период.",
        period_filter_mode="local_document_date",
        page_size=1000,
    ),
    OnecSampleCollection(
        sample_id="accounting_register_corrections",
        collection_name="Document_КорректировкаРегистров",
        purpose="Корректировки регистров за период.",
        period_filter_mode="local_document_date",
        page_size=1000,
    ),
    OnecSampleCollection(
        sample_id="accounting_purchase_corrections",
        collection_name="Document_КорректировкаПоступления",
        purpose="Корректировки поступлений за период.",
        period_filter_mode="local_document_date",
        page_size=1000,
    ),
    OnecSampleCollection(
        sample_id="accounting_sales_corrections",
        collection_name="Document_КорректировкаРеализации",
        purpose="Корректировки реализаций за период.",
        period_filter_mode="local_document_date",
        page_size=1000,
    ),
    *SERVICE_SAMPLE_COLLECTIONS,
)


def export_onec_accounting_balance_and_turnovers(
    settings: OnecODataSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    page_size: int = 1000,
    max_pages: int = 50,
) -> OnecSampleExportResult:
    """Read the accounting virtual table using GET requests only."""

    sample_id = "accounting_balance_and_turnovers"
    collection_name = "AccountingRegister_Управленческий/BalanceAndTurnovers"
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    last_status: int | None = None
    end_exclusive = period_end + timedelta(days=1)
    register = quote("AccountingRegister_Управленческий", safe="")
    function_call = (
        "BalanceAndTurnovers("
        f"StartPeriod=datetime'{period_start:%Y-%m-%dT00:00:00}',"
        f"EndPeriod=datetime'{end_exclusive:%Y-%m-%dT00:00:00}',"
        "AccountCondition='',Condition='',Dimensions='Организация')"
    )
    try:
        with httpx.Client(
            auth=(settings.username, settings.password),
            headers={"Accept": "application/json"},
            timeout=settings.timeout_seconds,
            verify=settings.verify_ssl,
            follow_redirects=True,
        ) as client:
            for page_index in range(max(1, max_pages)):
                response = client.get(
                    f"{settings.base_url.rstrip('/')}/{register}/{function_call}",
                    params={
                        "$format": "json",
                        "$top": str(max(1, page_size)),
                        "$skip": str(page_index * max(1, page_size)),
                    },
                )
                last_status = response.status_code
                response.raise_for_status()
                page_rows = [
                    row
                    for row in extract_odata_rows(response.json())
                    if isinstance(row, dict)
                ]
                rows.extend(page_rows)
                if len(page_rows) < max(1, page_size):
                    break
            else:
                return OnecSampleExportResult(
                    sample_id=sample_id,
                    collection_name=collection_name,
                    ok=False,
                    row_count=len(rows),
                    page_count=max_pages,
                    status_code=last_status,
                    error="max_pages_reached",
                    status="partial_source",
                    retryable=True,
                )
    except httpx.HTTPStatusError as exc:
        return OnecSampleExportResult(
            sample_id=sample_id,
            collection_name=collection_name,
            ok=False,
            row_count=len(rows),
            status_code=exc.response.status_code,
            error=f"HTTP {exc.response.status_code}",
            status="failed",
            retryable=exc.response.status_code in RETRYABLE_STATUS_CODES,
        )
    except (httpx.HTTPError, ValueError) as exc:
        return OnecSampleExportResult(
            sample_id=sample_id,
            collection_name=collection_name,
            ok=False,
            row_count=len(rows),
            status_code=last_status,
            error=exc.__class__.__name__,
            status="failed",
            retryable=isinstance(exc, httpx.HTTPError),
        )

    payload = {
        "value": rows,
        "_source": {
            "collectionName": collection_name,
            "periodStart": period_start.isoformat(),
            "periodEndExclusive": end_exclusive.isoformat(),
            "readBoundary": "GET only",
        },
    }
    output_path = output_dir / f"{sample_id}.raw.json"
    _write_json(output_path, payload)
    return OnecSampleExportResult(
        sample_id=sample_id,
        collection_name=collection_name,
        ok=True,
        row_count=len(rows),
        page_count=max(1, (len(rows) + max(1, page_size) - 1) // max(1, page_size)),
        raw_payload_hash=raw_payload_hash(payload),
        output_path=output_path,
        status_code=last_status,
        status="loaded",
        retryable=False,
    )


def export_onec_accounting_recordtype_balances(
    settings: OnecODataSettings,
    output_dir: Path,
    *,
    period_start: date,
    period_end: date,
    page_size: int = 1000,
    max_pages: int = 1000,
    transport: httpx.BaseTransport | None = None,
) -> OnecSampleExportResult:
    """Build an organization-aware OSV fallback from RecordType GET pages.

    Some 1C publications return HTTP 500 for ``$filter`` on accounting
    registers. This collector intentionally paginates the unfiltered read-only
    endpoint, retains every raw page locally, and persists only deterministic
    account aggregates for report materialization.
    """

    sample_id = "accounting_register_balances"
    collection_name = "AccountingRegister_Управленческий_RecordType"
    collection_dir = output_dir / sample_id
    collection_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = collection_dir / "manifest.json"
    normalized_path = output_dir / f"{sample_id}.raw.json"
    effective_page_size = max(1, page_size)
    page_limit = max(1, max_pages)
    end_exclusive = period_end + timedelta(days=1)
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    page_meta: list[dict[str, Any]] = []
    scanned_rows = 0
    last_status: int | None = None
    complete = False
    error = ""
    request_params = {
        "$select": ",".join(
            (
                "Period",
                "Recorder",
                "LineNumber",
                "Active",
                "Организация_Key",
                "AccountDr_Key",
                "AccountCr_Key",
                "Сумма",
            )
        ),
        "$orderby": "Period asc,Recorder asc,LineNumber asc",
    }

    def bucket(organization_id: str, account_key: str) -> dict[str, Any]:
        key = (organization_id, account_key)
        if key not in buckets:
            buckets[key] = {
                "Organization_Key": organization_id,
                "Account_Key": account_key,
                "openingNet": Decimal("0"),
                "debitTurnover": Decimal("0"),
                "creditTurnover": Decimal("0"),
                "closingNet": Decimal("0"),
            }
        return buckets[key]

    try:
        with OnecODataClient(settings, transport=transport) as client:
            for page_index in range(page_limit):
                payload, status_code = _fetch_collection_with_retries(
                    client,
                    collection_name,
                    top=effective_page_size,
                    skip=page_index * effective_page_size,
                    params=request_params,
                    next_link="",
                    timeout_seconds=120.0,
                    retry_attempts=2,
                    retry_delay_seconds=2.0,
                    retry_read_timeouts=True,
                )
                last_status = status_code
                rows = [
                    row
                    for row in extract_odata_rows(payload)
                    if isinstance(row, dict)
                ]
                page_path = collection_dir / f"page_{page_index + 1:06d}.raw.json"
                _write_json(page_path, payload)
                page_meta.append(
                    {
                        "pageIndex": page_index + 1,
                        "skip": page_index * effective_page_size,
                        "rowCount": len(rows),
                        "statusCode": status_code,
                        "file": page_path.name,
                        "fileSha256": _file_sha256(page_path),
                    }
                )
                scanned_rows += len(rows)
                ordered_period_complete = False
                for row in rows:
                    row_date = _accounting_row_date(row.get("Period"))
                    if row_date is not None and row_date >= end_exclusive:
                        ordered_period_complete = True
                    if (
                        row_date is None
                        or row_date >= end_exclusive
                        or not _accounting_row_is_active(row.get("Active"))
                    ):
                        continue
                    organization_id = str(
                        row.get("Организация_Key")
                        or row.get("Organization_Key")
                        or ""
                    ).strip()
                    amount = _accounting_decimal(row.get("Сумма") or row.get("Amount"))
                    if not organization_id or amount is None:
                        continue
                    in_period = period_start <= row_date < end_exclusive
                    for side, account_field in (
                        ("debit", "AccountDr_Key"),
                        ("credit", "AccountCr_Key"),
                    ):
                        account_key = str(row.get(account_field) or "").strip()
                        if not account_key:
                            continue
                        item = bucket(organization_id, account_key)
                        signed = amount if side == "debit" else -amount
                        item["closingNet"] += signed
                        if row_date < period_start:
                            item["openingNet"] += signed
                        elif in_period:
                            turnover_field = (
                                "debitTurnover"
                                if side == "debit"
                                else "creditTurnover"
                            )
                            item[turnover_field] += amount
                if ordered_period_complete:
                    # The server accepted an explicit Period ordering. Once
                    # the ordered stream enters the next period, every row
                    # needed for opening balances and current-month turnover
                    # has been retained in the raw lineage.
                    complete = True
                    break
                if len(rows) < effective_page_size:
                    complete = True
                    break
            if not complete:
                error = "max_pages_reached"
    except httpx.HTTPStatusError as exc:
        last_status = exc.response.status_code
        error = f"HTTP {exc.response.status_code}"
    except (httpx.HTTPError, ValueError) as exc:
        error = exc.__class__.__name__

    normalized_rows: list[dict[str, Any]] = []
    for item in buckets.values():
        opening = item.pop("openingNet")
        closing = item.pop("closingNet")
        normalized_rows.append(
            {
                **item,
                "OpeningDebit": _accounting_decimal_text(max(opening, Decimal("0"))),
                "OpeningCredit": _accounting_decimal_text(max(-opening, Decimal("0"))),
                "DebitTurnover": _accounting_decimal_text(item["debitTurnover"]),
                "CreditTurnover": _accounting_decimal_text(item["creditTurnover"]),
                "ClosingDebit": _accounting_decimal_text(max(closing, Decimal("0"))),
                "ClosingCredit": _accounting_decimal_text(max(-closing, Decimal("0"))),
            }
        )
    for row in normalized_rows:
        row.pop("debitTurnover", None)
        row.pop("creditTurnover", None)
    normalized_rows.sort(
        key=lambda row: (str(row["Organization_Key"]), str(row["Account_Key"]))
    )
    status = (
        "loaded" if complete else ("partial_source" if normalized_rows else "failed")
    )
    manifest = {
        "contractVersion": "onec-accounting-recordtype-balances-v3",
        "collectionName": collection_name,
        "readBoundary": "GET only",
        "periodStart": period_start.isoformat(),
        "periodEndExclusive": end_exclusive.isoformat(),
        "status": status,
        "error": error,
        "scannedRows": scanned_rows,
        "normalizedRows": len(normalized_rows),
        "pageSize": effective_page_size,
        "orderBy": request_params["$orderby"],
        "pages": page_meta,
    }
    _write_json(checkpoint_path, manifest)
    output_payload = {
        "value": normalized_rows,
        "_source": {
            "contractVersion": manifest["contractVersion"],
            "periodStart": period_start.isoformat(),
            "periodEndExclusive": end_exclusive.isoformat(),
            "rawManifestSha256": _file_sha256(checkpoint_path),
            "scannedRows": scanned_rows,
            "readBoundary": "GET only",
        },
    }
    _write_json(normalized_path, output_payload)
    return OnecSampleExportResult(
        sample_id=sample_id,
        collection_name=collection_name,
        ok=complete,
        row_count=len(normalized_rows),
        page_count=len(page_meta),
        raw_payload_hash=_file_sha256(checkpoint_path),
        output_path=normalized_path,
        status_code=last_status,
        error=error,
        status=status,
        checkpoint_path=checkpoint_path,
        retryable=not complete,
        next_cursor=(
            f"skip:{len(page_meta) * effective_page_size}" if not complete else ""
        ),
        effective_page_size=effective_page_size,
        detail_mode="normalized_account_balances",
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
    local_period_field = {
        "local_accounting_period": "Period",
        "local_document_date": "Date",
    }.get(collection.period_filter_mode)

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
        local_page_dates = [
            parsed
            for row in rows
            if isinstance(row, Mapping)
            and local_period_field is not None
            and (parsed := _accounting_row_date(row.get(local_period_field)))
            is not None
        ]
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
        if (
            local_period_field is not None
            and period_end is not None
            and local_page_dates
            and min(local_page_dates) > period_end
        ):
            # Period-local accounting collections request an explicit server
            # ordering below. Once an entire page is beyond the selected
            # window, no matching row can appear later in the stream.
            complete = True
            next_link = ""
            break

    if not complete and not error and len(page_meta) >= page_limit:
        error = "max_pages_reached"
        retryable = True

    status = "loaded" if complete else ("partial_source" if page_meta else "failed")
    output_path: Path | None = None
    payload_hash = ""
    if complete:
        output_path = output_dir / f"{collection.sample_id}.raw.json"
        row_count = _write_combined_output(
            output_path,
            collection_dir=collection_dir,
            pages=page_meta,
            local_period_field=local_period_field,
            period_start=period_start,
            period_end=period_end,
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
    if "$orderby" not in params:
        local_order_field = {
            "local_accounting_period": "Period asc,Recorder asc,LineNumber",
            "local_document_date": "Date asc,Ref_Key",
        }.get(collection.period_filter_mode)
        if local_order_field:
            params["$orderby"] = f"{local_order_field} asc"
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
    local_period_field: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> int:
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
        output_row_count = 0
        for page in pages:
            payload = json.loads(
                (collection_dir / str(page["file"])).read_text(encoding="utf-8")
            )
            for row in extract_odata_rows(payload):
                if local_period_field is not None:
                    if not isinstance(row, Mapping):
                        continue
                    row_date = _accounting_row_date(row.get(local_period_field))
                    if row_date is None:
                        continue
                    if period_start is not None and row_date < period_start:
                        continue
                    if period_end is not None and row_date > period_end:
                        continue
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
                output_row_count += 1
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
    return output_row_count


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


def _accounting_row_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _accounting_row_is_active(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() not in {"", "0", "false", "no"}


def _accounting_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _accounting_decimal_text(value: Decimal) -> str:
    return format(value, "f")


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
