from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from calendar import monthrange
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import (
    and_,
    case,
    delete,
    func,
    insert,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from wb_unit_economics.calculation import (
    tax_profile_is_confirmed,
    tax_profile_is_osno,
)
from wb_unit_economics.config import (
    tax_profile_source_diagnostic,
    tax_profiles_from_account_org_mapping,
)
from wb_unit_economics.contracts import (
    AccountOrgMapping,
    InputVatPolicy,
    TaxProfile,
    VatDeductionMode,
    VatMode,
)
from wb_unit_economics.contracts import (
    MarketplaceFinanceDailyFact as MarketplaceFinanceDailyFactContract,
)
from wb_unit_economics.liquidity import (
    GROUP_FIELDS,
    aggregate_liquidity_rows,
    liquidity_rows_payload,
    liquidity_statuses,
)
from wb_unit_economics.logistics_analysis import (
    CHAIN_KEY_VERSION,
    LOGISTICS_CLASSIFIER_VERSION,
    LOGISTICS_FACTORS_METHODOLOGY_VERSION,
    LOGISTICS_METHODOLOGY_VERSION,
    LOW_SAMPLE_THRESHOLD,
    LogisticsAnalysisResult,
)
from wb_unit_economics.ozon_mart import (
    _onec_commissioner_revenue_by_item,
    build_ozon_unit_economics_mart,
    combine_ozon_monthly_marts,
    empty_ozon_mart_payload,
)
from wb_unit_economics.web import providers, security
from wb_unit_economics.web.models import (
    AiClientDraft,
    AiEvent,
    AiMessage,
    AiThread,
    AiToolCall,
    AuditEvent,
    Client,
    ClientCompany,
    ClientCompanyAlias,
    ConsultingFirm,
    DataRefreshJob,
    LiveCheckCache,
    Marketplace1cCurrentMapping,
    MarketplaceFactStaging,
    MarketplaceFinanceDailyFact,
    MarketplaceMappingItem,
    MarketplaceOperationFact,
    MonthCloseControlReport,
    OnecMappingItem,
    OrganizationInputVatPolicy,
    OrganizationTaxProfile,
    OrganizationTaxProfileOverride,
    ReportArtifact,
    ReportDocumentReconciliationRow,
    ReportGenerationRequest,
    ReportLogisticsAnalysisContext,
    ReportLogisticsDimensionContext,
    ReportLogisticsDimensionRow,
    ReportLogisticsOrderRow,
    ReportLogisticsSkuRow,
    ReportLostSalesRow,
    ReportMarketplaceExpenseRow,
    ReportReconciliationMonthly,
    ReportRun,
    ReportUnitRow,
    SessionToken,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
    TaxLoadReport,
    Tenant,
    TenantIntegration,
    User,
    UserTenantAccess,
    WbCabinet,
)
from wb_unit_economics.web.report_kinds import (
    ACCOUNTING_REPORT_KINDS,
    MARKETPLACE_UNIT_ECONOMICS,
    MONTH_CLOSE_CONTROL,
    TAX_LOAD,
    require_report_kind,
)
from wb_unit_economics.web.reports import (
    build_month_close_control_payload,
    build_tax_load_payload,
    canonical_payload_sha256,
)

VALID_ROLES = {"client", "consultant", "admin"}
DEFAULT_CONSULTING_FIRM_ID = "firm_shumeyko_partners"
DEFAULT_CONSULTING_FIRM_NAME = "Шумейко и Партнеры"
STAFF_ROLES = {"consultant", "admin"}
RATE_ANCHOR_REASON_PREFIX = "[rate_anchor_only]"
ACTIVE_REFRESH_STATUSES = {
    "queued",
    "running",
    "source_loaded",
    "rebuilding",
}
ACTIVE_SOURCE_REFRESH_STATUSES = set(ACTIVE_REFRESH_STATUSES)
SOURCE_REFRESH_HEARTBEAT_STALE_AFTER = timedelta(minutes=5)
MARKETPLACE_STAGING_DELETE_BATCH_SIZE = 5_000
CALCULABLE_OZON_REFRESH_STATUSES = {
    "source_loaded",
    "needs_review",
    "report_created",
}
OZON_DRAFT_LINEAGE_TYPE = "ozon_mart_snapshot"
OZON_DRAFT_METHODOLOGY_VERSION = "ozon-unit-economics-mart-v2"
BLOCKED_SOURCE_REFRESH_STATUSES = {
    "blocked_active_refresh",
    "blocked_low_disk",
    "needs_full_refresh",
}
DAILY_FACT_MUTATING_SOURCE_REFRESH_MODES = {
    "daily",
    "incremental",
    "weekly",
    "full",
}
READINESS_REVIEW_RATIO = 0.20
READINESS_REVIEW_MIN_ROWS = 3
REPORT_ROWS_MAX_LIMIT = 1000
LOGISTICS_PRODUCT_SORT_KEYS = frozenset(
    {
        "product",
        "logisticsTotal",
        "logisticsSharePct",
        "orderCount",
        "returnQuantity",
        "profitEffectAmount",
        "quality",
    }
)
LOGISTICS_ORDER_SORT_KEYS = frozenset(
    {
        "chainRef",
        "financialDate",
        "operationDateEnd",
        "orderDate",
        "logisticsForward",
        "logisticsReverse",
        "logisticsTotal",
        "salesQuantity",
        "returnQuantity",
        "classificationStatus",
        "product",
    }
)
LOGISTICS_DIMENSION_SORT_KEYS = frozenset(
    {"product", "volumeL", "weightBruttoKg", "coverageStatus"}
)
REPORT_ROW_SORT_KEYS = frozenset(
    {
        "product",
        "articleWb",
        "article1c",
        "barcode",
        "nmId",
        "cabinet",
        "organization",
        "scheme",
        "status",
        "month",
        "sales",
        "returns",
        "netQty",
        "revenueBeforeSpp",
        "spp",
        "revenue",
        "pnlRevenue",
        "cost",
        "commission",
        "logistics",
        "storage",
        "acceptance",
        "promotion",
        "penalties",
        "acquiring",
        "pnlVatAdjustment",
        "profitBeforeTax",
        "vatOutput",
        "vatInput",
        "vatPayable",
        "incomeTaxBase",
        "incomeTax",
        "includedTaxes",
        "profit",
        "margin",
        "unitProfit",
        "accountingPeriodDate",
        "documentReport",
        "wbReportId",
        "wbReportDate",
    }
)
MARKETPLACE_EXPENSE_CONTEXT_VERSION = "marketplace-expense-reconciliation-v1"
MARKETPLACE_EXPENSE_TOLERANCE = Decimal("1")
MARKETPLACE_EXPENSE_GROUP_LABELS = {
    "promotion": "WB Продвижение",
    "penalties": "Штрафы/доплаты",
    "core_services": (
        "Комиссия + логистика + хранение + приёмка + эквайринг + прочие услуги WB"
    ),
}
PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO = "without_vat_for_osno"
EXPENSE_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("Себестоимость 1С", "cost"),
    ("Комиссия WB", "commission"),
    ("Логистика WB", "logistics"),
    ("Хранение WB", "storage"),
    ("Приемка WB", "acceptance"),
    ("WB Продвижение", "promotion"),
    ("Штрафы/доплаты WB", "penalties"),
    ("Эквайринг WB", "acquiring"),
)
SERVICE_EXPENSE_FIELDS = (
    "commission",
    "logistics",
    "storage",
    "acceptance",
    "promotion",
    "penalties",
    "acquiring",
)
VAT_ELIGIBLE_SERVICE_EXPENSE_FIELDS = tuple(
    field for field in SERVICE_EXPENSE_FIELDS if field != "penalties"
)
READINESS_LABELS = {
    "ready": "Готов к отправке",
    "needs_review": "Нужна проверка",
    "partial_period": "Неполный период",
    "partial_source": "Неполный источник",
    "source_coverage_gap": "Разрыв покрытия",
    "failed": "Ошибка подготовки",
}
SOURCE_LOAD_OK_STATUSES = {"loaded", "ok", "ready", "completed", "empty_expected"}
SOURCE_LOAD_FAILED_MARKERS = (
    "failed",
    "error",
    "ошиб",
    "blocked",
    "auth",
    "access",
    "rate_limited",
    "schema",
    "needs_configuration",
)


class ReportPublicationBlocked(ValueError):
    def __init__(self, blockers: list[dict[str, Any]]) -> None:
        self.blockers = blockers
        codes = ", ".join(as_text(item.get("code")) for item in blockers)
        super().__init__(f"financial publication blocked: {codes}")


OZON_DIAGNOSTIC_FINANCE_SOURCE = "ozon_finance_cash_flow"
OZON_DIAGNOSTIC_PRODUCT_SOURCE = "ozon_products_report"
OZON_REALIZATION_SOURCE = "ozon_realization"
OZON_MUTUAL_SETTLEMENT_SOURCE = "ozon_mutual_settlement"
OZON_BUYOUT_API_SOURCE = "ozon_products_buyout"
OZON_ONEC_BUYOUT_SOURCE = "onec_expense_invoices"
OZON_ONEC_INCOMING_INVOICE_SOURCE = "onec_incoming_invoices"
OZON_ONEC_MARKETPLACE_MAPPING_SOURCES = frozenset(
    {
        "onec_marketplace_mapping",
        "onec_marketplace_ozon_mapping",
    }
)
OZON_EXTRA_RECONCILIATION_SOURCES = frozenset(
    {
        "ozon_realization_posting",
        OZON_BUYOUT_API_SOURCE,
        "ozon_b2b_sales_json",
    }
)
OZON_DIAGNOSTIC_PREVIEW_MAX_ROWS = 100
OZON_PNL_MAX_SOURCE_ROWS = 50000
OZON_ONEC_COUNTERPARTY_LABEL = "ООО Интернет Решения"
OZON_BUYOUT_REPORT_RE = re.compile(
    r"(?:отчет[а]?\s+о\s+выкуп(?:ленных\s+товаров|е)?|"
    r"выкупленных\s+товарах)[^\d№#]{0,80}[№#]?\s*([0-9][0-9\s-]{3,})",
    re.IGNORECASE,
)
OZON_COMMISSIONER_REPORT_RE = re.compile(
    r"отчет(?:а)?\s+комиссионера[^\d№#]{0,80}[№#]?\s*([0-9][0-9\s-]{3,})",
    re.IGNORECASE,
)
OZON_BUYOUT_PERIOD_RE = re.compile(
    r"от\s+(\d{2}\.\d{2}\.\d{4})(?:\s+\d{1,2}:\d{2}:\d{2})?"
    r"\s+по\s+(\d{2}\.\d{2}\.\d{4})(?:\s+\d{1,2}:\d{2}:\d{2})?",
    re.IGNORECASE,
)
DOCUMENT_RECONCILIATION_DELTA_FIELDS = (
    "sales_quantity_delta",
    "return_quantity_delta",
    "net_quantity_delta",
    "quantity_delta",
    "amount_delta",
    "buyout_retail_delta",
    "buyout_for_pay_delta",
    "buyout_bank_delta",
    "settlement_delta",
)
CLIENT_DRAFT_REQUIRED_SECTIONS = [
    "Ключевой вывод",
    "Факты",
    "Что требует проверки",
    "Ограничения",
    "Следующий шаг",
]
CLIENT_DRAFT_FORBIDDEN_TERMS = [
    "draft_management_report",
    "tool_completed",
    "tool_started",
    "debug",
    "traceback",
    "raw tool",
    "я как ai",
    "я как ии",
    "как ai",
    "как ии",
]
INTEGRATION_PROVIDERS = {
    key: definition.label for key, definition in providers.PROVIDER_DEFINITIONS.items()
}
INTEGRATION_PROVIDER_ORDER = providers.PROVIDER_ORDER
INTEGRATION_STATUSES = {
    "not_configured",
    "configured",
    "check_ok",
    "check_failed",
    "disabled",
}

RU_MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}
RU_MONTH_NUMBERS = {name.casefold(): number for number, name in RU_MONTH_NAMES.items()}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def parse_period(period_text: str) -> tuple[date, date]:
    left, _, right = period_text.partition("-")
    start = datetime.strptime(left.strip(), "%d.%m.%Y").date()
    end = datetime.strptime(right.strip(), "%d.%m.%Y").date()
    return start, end


def decimal_value(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def date_or_none(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def as_text(value: Any) -> str:
    return "" if value is None else str(value)


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(Decimal(str(value)))


def audit(
    db: Session,
    *,
    action: str,
    user: User | None = None,
    tenant_id: str | None = None,
    entity_type: str = "",
    entity_id: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            created_at=security.utcnow(),
        )
    )


def allowed_tenant_ids(user: User) -> list[str]:
    return [item.tenant_id for item in user.access]


def roles_for_tenant(user: User, tenant_id: str | None = None) -> set[str]:
    if tenant_id is None:
        return {item.role for item in user.access}
    return {item.role for item in user.access if item.tenant_id == tenant_id}


def has_role(user: User, allowed_roles: set[str], tenant_id: str | None = None) -> bool:
    return bool(roles_for_tenant(user, tenant_id) & allowed_roles)


def require_admin(user: User, tenant_id: str | None = None) -> None:
    if not has_role(user, {"admin"}, tenant_id):
        raise PermissionError("admin role required")


def require_staff(user: User, tenant_id: str | None = None) -> None:
    if not has_role(user, STAFF_ROLES, tenant_id):
        raise PermissionError("staff role required")


def primary_access(user: User, tenant_id: str | None = None) -> UserTenantAccess:
    if tenant_id:
        for item in user.access:
            if item.tenant_id == tenant_id:
                return item
        raise PermissionError("tenant access denied")
    if not user.access:
        raise PermissionError("tenant access denied")
    return user.access[0]


def get_user_by_session(db: Session, token: str) -> User | None:
    token_hash = security.hash_session_token(token)
    session = db.scalar(
        select(SessionToken).where(
            SessionToken.token_hash == token_hash,
            SessionToken.expires_at > security.utcnow(),
        )
    )
    if session is None or not session.user.is_active:
        return None
    session.last_seen_at = security.utcnow()
    return session.user


def create_session(
    db: Session,
    user: User,
    *,
    ttl_hours: int,
    user_agent: str = "",
    ip_address: str = "",
) -> str:
    token = security.new_session_token()
    db.add(
        SessionToken(
            id=new_id("session"),
            user_id=user.id,
            token_hash=security.hash_session_token(token),
            created_at=security.utcnow(),
            expires_at=security.expires_after(ttl_hours),
            last_seen_at=security.utcnow(),
            user_agent=user_agent[:500],
            ip_address=ip_address[:120],
        )
    )
    return token


def delete_session(db: Session, token: str) -> None:
    db.execute(
        delete(SessionToken).where(
            SessionToken.token_hash == security.hash_session_token(token)
        )
    )


def delete_sessions_for_user(db: Session, user_id: str) -> None:
    db.execute(delete(SessionToken).where(SessionToken.user_id == user_id))


def ensure_tenant(db: Session, tenant_id: str, name: str) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, name=name, created_at=security.utcnow())
        db.add(tenant)
        db.flush()
    else:
        tenant.name = name
    ensure_client_for_tenant(db, tenant_id=tenant.id, name=tenant.name)
    return tenant


def client_id_for_tenant(tenant_id: str) -> str:
    safe = _safe_identifier(tenant_id)
    return safe or _stable_entity_id("client", tenant_id)


def ensure_client(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    name: str,
) -> Client:
    now = security.utcnow()
    firm = db.get(ConsultingFirm, DEFAULT_CONSULTING_FIRM_ID)
    if firm is None:
        firm = ConsultingFirm(
            id=DEFAULT_CONSULTING_FIRM_ID,
            name=DEFAULT_CONSULTING_FIRM_NAME,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(firm)
        db.flush()
    else:
        firm.name = firm.name or DEFAULT_CONSULTING_FIRM_NAME
        firm.updated_at = now
    safe_client_id = _safe_identifier(client_id) or _stable_entity_id(
        "client", client_id
    )
    existing_for_tenant = db.scalar(
        select(Client).where(Client.tenant_id == tenant_id, Client.id != safe_client_id)
    )
    if existing_for_tenant is not None:
        raise ValueError(
            "tenant already has a client; use a separate tenant_id for another client"
        )
    client = db.get(Client, safe_client_id)
    if client is None:
        client = Client(
            id=safe_client_id,
            firm_id=firm.id,
            tenant_id=tenant_id,
            name=name or safe_client_id,
            status="active",
            default_report_settings={},
            created_at=now,
            updated_at=now,
        )
        db.add(client)
        db.flush()
    else:
        client.firm_id = client.firm_id or firm.id
        client.tenant_id = tenant_id
        client.name = name or client.name or safe_client_id
        client.updated_at = now
    return client


def ensure_client_for_tenant(db: Session, *, tenant_id: str, name: str) -> Client:
    now = security.utcnow()
    firm = db.get(ConsultingFirm, DEFAULT_CONSULTING_FIRM_ID)
    if firm is None:
        firm = ConsultingFirm(
            id=DEFAULT_CONSULTING_FIRM_ID,
            name=DEFAULT_CONSULTING_FIRM_NAME,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(firm)
        db.flush()
    else:
        firm.updated_at = now
    client_id = client_id_for_tenant(tenant_id)
    client = db.get(Client, client_id)
    if client is None:
        client = Client(
            id=client_id,
            firm_id=firm.id,
            tenant_id=tenant_id,
            name=name or tenant_id,
            status="active",
            default_report_settings={},
            created_at=now,
            updated_at=now,
        )
        db.add(client)
        db.flush()
    else:
        client.firm_id = client.firm_id or firm.id
        client.tenant_id = tenant_id
        client.name = client.name or name or tenant_id
        client.updated_at = now
    return client


def ensure_client_company(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    display_name: str,
) -> ClientCompany | None:
    label = display_name.strip()
    if not label:
        return None
    source_key = _stable_key(label)
    alias_matches = list(
        db.scalars(
            select(ClientCompany)
            .join(
                ClientCompanyAlias,
                ClientCompanyAlias.client_company_id == ClientCompany.id,
            )
            .where(
                ClientCompanyAlias.client_id == client_id,
                ClientCompanyAlias.alias_key == source_key,
                ClientCompany.status == "active",
            )
            .order_by(ClientCompany.id)
        )
    )
    alias_company_ids = {item.id for item in alias_matches}
    if len(alias_company_ids) > 1:
        raise ValueError(
            "company alias is ambiguous; provide an explicit client company id"
        )
    if alias_matches:
        company = alias_matches[0]
        company.updated_at = security.utcnow()
        return company
    company_id = _stable_entity_id("company", client_id, source_key)
    now = security.utcnow()
    company = db.get(ClientCompany, company_id)
    if company is None:
        company = ClientCompany(
            id=company_id,
            tenant_id=tenant_id,
            client_id=client_id,
            display_name=label,
            source_key=source_key,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(company)
        db.flush()
    else:
        company.display_name = company.display_name or label
        company.updated_at = now
    ensure_client_company_alias(
        db,
        company=company,
        display_name=label,
        source="display_name",
    )
    return company


def ensure_client_company_alias(
    db: Session,
    *,
    company: ClientCompany,
    display_name: str,
    source: str,
) -> ClientCompanyAlias | None:
    label = display_name.strip()
    alias_key = _stable_key(label)
    if not label or not alias_key:
        return None
    existing = db.scalar(
        select(ClientCompanyAlias).where(
            ClientCompanyAlias.client_id == company.client_id,
            ClientCompanyAlias.client_company_id == company.id,
            ClientCompanyAlias.alias_key == alias_key,
        )
    )
    now = security.utcnow()
    if existing is not None:
        existing.display_name = existing.display_name or label
        existing.source = existing.source or source
        existing.updated_at = now
        return existing
    alias = ClientCompanyAlias(
        id=_stable_entity_id("company_alias", company.client_id, company.id, alias_key),
        tenant_id=company.tenant_id,
        client_id=company.client_id,
        client_company_id=company.id,
        alias_key=alias_key,
        display_name=label,
        source=source.strip() or "display_name",
        created_at=now,
        updated_at=now,
    )
    db.add(alias)
    db.flush()
    return alias


def set_client_company_onec_organization(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
    onec_organization_id: str,
) -> ClientCompany:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    company = db.get(ClientCompany, company_id)
    if company is None or company.client_id != client.id:
        raise LookupError("client company not found")
    organization_id = onec_organization_id.strip()
    if organization_id and not _onec_organization_exists(
        db,
        client_id=client.id,
        organization_id=organization_id,
    ):
        raise ValueError("1C organization is not present in the latest snapshot")
    previous = company.onec_organization_id
    existing_companies = (
        list(
            db.scalars(
                select(ClientCompany).where(
                    ClientCompany.client_id == client.id,
                    ClientCompany.id != company.id,
                    ClientCompany.onec_organization_id == organization_id,
                    ClientCompany.status == "active",
                )
            )
        )
        if organization_id
        else []
    )
    if len(existing_companies) > 1:
        raise ValueError(
            "multiple canonical companies already use this 1C organization"
        )
    if existing_companies:
        canonical = existing_companies[0]
        merge_client_company_into(db, duplicate=company, canonical=canonical)
        audit(
            db,
            action="client_company_merged_on_onec_link",
            user=user,
            tenant_id=client.tenant_id,
            entity_type="client_company",
            entity_id=canonical.id,
            payload={"mergedCompanyId": company_id},
        )
        return canonical
    company.onec_organization_id = organization_id
    company.updated_at = security.utcnow()
    ensure_client_company_alias(
        db,
        company=company,
        display_name=company.display_name,
        source="display_name",
    )
    audit(
        db,
        action="client_company_onec_organization_changed",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="client_company",
        entity_id=company.id,
        payload={
            "previousOrganizationId": previous,
            "newOrganizationId": organization_id,
        },
    )
    return company


def onec_organizations_payload(
    db: Session,
    *,
    user: User,
    client_id: str,
) -> dict[str, Any]:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    latest = db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.client_id == client.id,
            SourceRefreshRun.status.in_(
                {"source_loaded", "needs_review", "report_created"}
            ),
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )
    if latest is None:
        return {"refreshRunId": None, "items": []}
    items: dict[str, dict[str, str]] = {}
    for row in db.scalars(
        select(SourceSnapshotRow).where(
            SourceSnapshotRow.refresh_run_id == latest.id,
            SourceSnapshotRow.source_type == "onec_organizations",
        )
    ):
        payload = row.row_payload or {}
        organization_id = _safe_payload_text(payload, "Ref_Key")
        if not organization_id:
            continue
        items[organization_id] = {
            "id": organization_id,
            "name": _safe_payload_text(
                payload,
                "Description",
                "НаименованиеПолное",
                "НаименованиеСокращенное",
            ),
        }
    return {
        "refreshRunId": latest.id,
        "items": sorted(
            items.values(),
            key=lambda item: (item["name"].casefold(), item["id"]),
        ),
    }


def create_tax_profile_override(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
    tax_system: str,
    vat_rate: Decimal,
    vat_mode: str,
    vat_deduction_mode: str,
    revenue_tax_rate: Decimal,
    income_tax_kind: str,
    valid_from: date,
    valid_to: date | None,
    reason: str,
    rate_basis_kind: str = "",
    basis_document: str = "",
    source_object_ids: list[str] | None = None,
) -> OrganizationTaxProfileOverride:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    company = db.get(ClientCompany, company_id)
    if company is None or company.client_id != client.id:
        raise LookupError("client company not found")
    if not company.onec_organization_id:
        raise ValueError("link the company to a 1C organization first")
    if not tax_system.strip():
        raise ValueError("tax system is required")
    if vat_mode not in {item.value for item in VatMode}:
        raise ValueError("unsupported VAT mode")
    if vat_deduction_mode not in {item.value for item in VatDeductionMode}:
        raise ValueError("unsupported VAT deduction mode")
    if vat_rate < 0 or revenue_tax_rate < 0:
        raise ValueError("tax rates must be non-negative")
    if valid_to is not None and valid_to < valid_from:
        raise ValueError("valid_to must be on or after valid_from")
    if not reason.strip():
        raise ValueError("override reason is required")
    overlap_conditions = [
        OrganizationTaxProfileOverride.client_company_id == company.id,
        OrganizationTaxProfileOverride.status == "active",
        or_(
            OrganizationTaxProfileOverride.valid_to.is_(None),
            OrganizationTaxProfileOverride.valid_to >= valid_from,
        ),
    ]
    if valid_to is not None:
        overlap_conditions.append(OrganizationTaxProfileOverride.valid_from <= valid_to)
    overlap = db.scalar(
        select(OrganizationTaxProfileOverride.id).where(*overlap_conditions)
    )
    if overlap is not None:
        raise ValueError("active tax profile override overlaps this period")
    now = security.utcnow()
    override = OrganizationTaxProfileOverride(
        id=_stable_entity_id(
            "tax_override",
            company.id,
            valid_from.isoformat(),
            tax_system,
            str(uuid.uuid4()),
        ),
        tenant_id=client.tenant_id,
        client_id=client.id,
        client_company_id=company.id,
        organization_id=company.onec_organization_id,
        tax_system=tax_system.strip(),
        vat_rate=vat_rate,
        vat_mode=vat_mode,
        vat_deduction_mode=vat_deduction_mode,
        revenue_tax_rate=revenue_tax_rate,
        income_tax_kind=income_tax_kind.strip(),
        valid_from=valid_from,
        valid_to=valid_to,
        status="active",
        reason=reason.strip(),
        rate_basis_kind=rate_basis_kind.strip(),
        basis_document=basis_document.strip(),
        confirmed_by=(user.name or user.email or user.id).strip(),
        source_object_ids=json.dumps(
            sorted(
                {
                    str(item).strip()
                    for item in source_object_ids or []
                    if str(item).strip()
                }
            ),
            ensure_ascii=False,
        ),
        created_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(override)
    audit(
        db,
        action="tax_profile_override_created",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="tax_profile_override",
        entity_id=override.id,
        payload={
            "clientCompanyId": company.id,
            "organizationId": company.onec_organization_id,
            "validFrom": valid_from.isoformat(),
            "validTo": valid_to.isoformat() if valid_to else None,
            "taxSystem": override.tax_system,
            "rateBasisKind": override.rate_basis_kind,
            "basisDocument": override.basis_document,
            "sourceObjectIds": json.loads(override.source_object_ids or "[]"),
        },
    )
    return override


def disable_tax_profile_override(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
    override_id: str,
) -> OrganizationTaxProfileOverride:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    override = db.get(OrganizationTaxProfileOverride, override_id)
    if (
        override is None
        or override.client_id != client.id
        or override.client_company_id != company_id
    ):
        raise LookupError("tax profile override not found")
    override.status = "disabled"
    override.updated_at = security.utcnow()
    audit(
        db,
        action="tax_profile_override_disabled",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="tax_profile_override",
        entity_id=override.id,
        payload={"clientCompanyId": company_id},
    )
    return override


def create_input_vat_policy(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
    mode: str,
    valid_from: date,
    valid_to: date | None,
    reason: str,
    product_vat_basis: str = "sales_cost_difference",
    service_vat_basis: str = "wb_gross_22_122",
) -> OrganizationInputVatPolicy:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    company = db.get(ClientCompany, company_id)
    if company is None or company.client_id != client.id:
        raise LookupError("client company not found")
    if not company.onec_organization_id:
        raise ValueError("link the company to a 1C organization first")
    if mode not in {"accounting_fact", "management_assumption"}:
        raise ValueError("unsupported input VAT policy mode")
    if product_vat_basis != "sales_cost_difference":
        raise ValueError("unsupported product input VAT basis")
    if service_vat_basis != "wb_gross_22_122":
        raise ValueError("unsupported service input VAT basis")
    if valid_to is not None and valid_to < valid_from:
        raise ValueError("valid_to must be on or after valid_from")
    if not reason.strip():
        raise ValueError("input VAT policy reason is required")
    overlap_conditions = [
        OrganizationInputVatPolicy.client_company_id == company.id,
        OrganizationInputVatPolicy.status == "active",
        or_(
            OrganizationInputVatPolicy.valid_to.is_(None),
            OrganizationInputVatPolicy.valid_to >= valid_from,
        ),
    ]
    if valid_to is not None:
        overlap_conditions.append(OrganizationInputVatPolicy.valid_from <= valid_to)
    if db.scalar(select(OrganizationInputVatPolicy.id).where(*overlap_conditions)):
        raise ValueError("active input VAT policy overlaps this period")
    now = security.utcnow()
    policy = OrganizationInputVatPolicy(
        id=_stable_entity_id(
            "input_vat_policy",
            company.id,
            valid_from.isoformat(),
            mode,
            str(uuid.uuid4()),
        ),
        tenant_id=client.tenant_id,
        client_id=client.id,
        client_company_id=company.id,
        organization_id=company.onec_organization_id,
        mode=mode,
        product_vat_basis=product_vat_basis,
        service_vat_basis=service_vat_basis,
        valid_from=valid_from,
        valid_to=valid_to,
        status="active",
        reason=reason.strip(),
        created_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(policy)
    audit(
        db,
        action="input_vat_policy_created",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="input_vat_policy",
        entity_id=policy.id,
        payload={
            "clientCompanyId": company.id,
            "organizationId": company.onec_organization_id,
            "mode": mode,
            "validFrom": valid_from.isoformat(),
            "validTo": valid_to.isoformat() if valid_to else None,
            "productVatBasis": product_vat_basis,
            "serviceVatBasis": service_vat_basis,
            "reason": reason.strip(),
            "createdByUserId": user.id,
        },
    )
    return policy


def disable_input_vat_policy(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
    policy_id: str,
) -> OrganizationInputVatPolicy:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    policy = db.get(OrganizationInputVatPolicy, policy_id)
    if (
        policy is None
        or policy.client_id != client.id
        or policy.client_company_id != company_id
    ):
        raise LookupError("input VAT policy not found")
    policy.status = "disabled"
    policy.updated_at = security.utcnow()
    audit(
        db,
        action="input_vat_policy_disabled",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="input_vat_policy",
        entity_id=policy.id,
        payload={"clientCompanyId": company_id},
    )
    return policy


def input_vat_policy_payload(item: OrganizationInputVatPolicy) -> dict[str, Any]:
    return {
        "id": item.id,
        "clientCompanyId": item.client_company_id,
        "organizationId": item.organization_id,
        "mode": item.mode,
        "productVatBasis": item.product_vat_basis,
        "serviceVatBasis": item.service_vat_basis,
        "validFrom": item.valid_from.isoformat(),
        "validTo": item.valid_to.isoformat() if item.valid_to else None,
        "status": item.status,
        "reason": item.reason,
        "createdByUserId": item.created_by_user_id,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def list_input_vat_policies(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
) -> list[OrganizationInputVatPolicy]:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    company = db.get(ClientCompany, company_id)
    if company is None or company.client_id != client.id:
        raise LookupError("client company not found")
    return list(
        db.scalars(
            select(OrganizationInputVatPolicy)
            .where(OrganizationInputVatPolicy.client_company_id == company.id)
            .order_by(
                OrganizationInputVatPolicy.valid_from.desc(),
                OrganizationInputVatPolicy.created_at.desc(),
            )
        )
    )


def input_vat_policies_for_source_refresh(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> list[InputVatPolicy]:
    items = list(
        db.scalars(
            select(OrganizationInputVatPolicy).where(
                OrganizationInputVatPolicy.client_id == refresh_run.client_id,
                OrganizationInputVatPolicy.status == "active",
                OrganizationInputVatPolicy.valid_from <= refresh_run.period_end,
                or_(
                    OrganizationInputVatPolicy.valid_to.is_(None),
                    OrganizationInputVatPolicy.valid_to >= refresh_run.period_start,
                ),
            )
        )
    )
    return [
        InputVatPolicy(
            client_id=item.client_id,
            organization_id=item.organization_id,
            mode=item.mode,
            valid_from=item.valid_from,
            valid_to=item.valid_to,
            product_vat_basis=item.product_vat_basis,
            service_vat_basis=item.service_vat_basis,
            reason=item.reason,
            source=f"organization_policy:{item.id}",
        )
        for item in items
    ]


def confirm_tax_rate_basis(
    db: Session,
    *,
    user: User,
    client_id: str,
    company_id: str,
    override_id: str,
    rate_basis_kind: str,
    basis_document: str,
    source_object_ids: list[str] | None = None,
) -> OrganizationTaxProfileOverride:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    override = db.get(OrganizationTaxProfileOverride, override_id)
    if (
        override is None
        or override.client_id != client.id
        or override.client_company_id != company_id
        or override.status != "active"
    ):
        raise LookupError("active tax profile override not found")
    if rate_basis_kind != "regional_preference":
        raise ValueError("unsupported tax rate basis kind")
    if not basis_document.strip():
        raise ValueError("tax rate basis document is required")
    override.rate_basis_kind = rate_basis_kind
    override.basis_document = basis_document.strip()
    override.confirmed_by = (user.name or user.email or user.id).strip()
    override.source_object_ids = json.dumps(
        sorted(
            {str(item).strip() for item in source_object_ids or [] if str(item).strip()}
        ),
        ensure_ascii=False,
    )
    override.updated_at = security.utcnow()
    audit(
        db,
        action="tax_rate_basis_confirmed",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="tax_profile_override",
        entity_id=override.id,
        payload={
            "clientCompanyId": company_id,
            "rateBasisKind": override.rate_basis_kind,
            "basisDocument": override.basis_document,
            "sourceObjectIds": json.loads(override.source_object_ids or "[]"),
        },
    )
    return override


def resolve_company_tax_profile(
    db: Session,
    *,
    company: ClientCompany | None,
    calculation_date: date,
    refresh_run: SourceRefreshRun | None = None,
) -> tuple[TaxProfile | None, dict[str, Any]]:
    if company is None or not company.onec_organization_id:
        return None, {
            "status": "missing_company_link",
            "source": "missing",
            "message": "Компания не связана с организацией 1C.",
        }
    source_conditions = [
        OrganizationTaxProfile.client_company_id == company.id,
        OrganizationTaxProfile.organization_id == company.onec_organization_id,
        OrganizationTaxProfile.status == "active",
        or_(
            OrganizationTaxProfile.valid_from.is_(None),
            OrganizationTaxProfile.valid_from <= calculation_date,
        ),
        or_(
            OrganizationTaxProfile.valid_to.is_(None),
            OrganizationTaxProfile.valid_to >= calculation_date,
        ),
    ]
    if refresh_run is not None:
        source_conditions.append(
            OrganizationTaxProfile.source_refresh_run_id == refresh_run.id
        )
    source_profiles = list(
        db.scalars(
            select(OrganizationTaxProfile)
            .where(*source_conditions)
            .order_by(
                OrganizationTaxProfile.valid_from.desc(),
                OrganizationTaxProfile.created_at.desc(),
            )
        )
    )
    if refresh_run is None and source_profiles:
        # «Текущий снимок 1С» = профиль самого свежего прогона среди действующих
        # на дату, а не профиль с максимальным valid_from: новый прогон мог
        # переопределить режим строкой с более ранним valid_from. Старые строки
        # не деактивируются, поэтому выбираем последний по времени записи прогон.
        latest_profile = max(
            source_profiles,
            key=lambda item: item.created_at,
        )
        latest_profile_run_id = latest_profile.source_refresh_run_id
        source_profiles = [
            item
            for item in source_profiles
            if item.source_refresh_run_id == latest_profile_run_id
        ]
    if len(source_profiles) > 1:
        return None, {
            "status": "conflict",
            "source": "1c",
            "message": "В 1C найдено несколько налоговых профилей на дату.",
        }
    if source_profiles:
        item = source_profiles[0]
        return _tax_profile_from_model(company.client_id, item), {
            "status": "ready",
            "source": item.source,
            "profileId": item.id,
            "manualOverride": False,
        }
    overrides = [
        item
        for item in db.scalars(
            select(OrganizationTaxProfileOverride)
            .where(
                OrganizationTaxProfileOverride.client_company_id == company.id,
                OrganizationTaxProfileOverride.organization_id
                == company.onec_organization_id,
                OrganizationTaxProfileOverride.status == "active",
                OrganizationTaxProfileOverride.valid_from <= calculation_date,
                or_(
                    OrganizationTaxProfileOverride.valid_to.is_(None),
                    OrganizationTaxProfileOverride.valid_to >= calculation_date,
                ),
            )
            .order_by(OrganizationTaxProfileOverride.valid_from.desc())
        )
        if not _tax_override_is_rate_anchor(item)
    ]
    if len(overrides) > 1:
        return None, {
            "status": "conflict",
            "source": "manual_override",
            "message": "Несколько ручных налоговых профилей действуют одновременно.",
        }
    if overrides:
        item = overrides[0]
        return _tax_profile_from_model(company.client_id, item), {
            "status": "override",
            "source": "manual_override",
            "profileId": item.id,
            "manualOverride": True,
            "reason": item.reason,
        }
    return None, {
        "status": "missing",
        "source": "missing",
        "message": "Налоговый профиль организации на дату не найден.",
    }


def _tax_profile_from_model(client_id: str, item: Any) -> TaxProfile:
    try:
        source_object_ids = json.loads(getattr(item, "source_object_ids", "[]") or "[]")
    except (TypeError, ValueError):
        source_object_ids = []
    return TaxProfile(
        client_id=client_id,
        organization_id=item.organization_id,
        tax_system=item.tax_system,
        tax_object=getattr(item, "tax_object", "") or "",
        tax_rate=getattr(item, "tax_rate", 0) or 0,
        elevated_tax_rate=getattr(item, "elevated_tax_rate", 0) or 0,
        vat_rate=item.vat_rate,
        vat_mode=VatMode(item.vat_mode),
        vat_deduction_mode=VatDeductionMode(
            getattr(item, "vat_deduction_mode", "unknown") or "unknown"
        ),
        revenue_tax_rate=item.revenue_tax_rate,
        income_tax_kind=item.income_tax_kind,
        valid_from=item.valid_from,
        valid_to=item.valid_to,
        source=("manual_override" if hasattr(item, "reason") else item.source),
        rate_basis_kind=getattr(item, "rate_basis_kind", "") or "",
        basis_document=getattr(item, "basis_document", "") or "",
        confirmed_by=getattr(item, "confirmed_by", "") or "",
        source_object_ids=[str(value) for value in source_object_ids if str(value)],
    )


def _tax_override_is_rate_anchor(item: OrganizationTaxProfileOverride) -> bool:
    return (
        item.reason.strip().casefold().startswith(RATE_ANCHOR_REASON_PREFIX.casefold())
    )


def _company_tax_rate_anchor_for_date(
    db: Session,
    *,
    company: ClientCompany,
    calculation_date: date,
) -> tuple[TaxProfile | None, dict[str, Any]]:
    anchors = [
        item
        for item in db.scalars(
            select(OrganizationTaxProfileOverride)
            .where(
                OrganizationTaxProfileOverride.client_company_id == company.id,
                OrganizationTaxProfileOverride.organization_id
                == company.onec_organization_id,
                OrganizationTaxProfileOverride.status == "active",
                OrganizationTaxProfileOverride.valid_from <= calculation_date,
                or_(
                    OrganizationTaxProfileOverride.valid_to.is_(None),
                    OrganizationTaxProfileOverride.valid_to >= calculation_date,
                ),
            )
            .order_by(OrganizationTaxProfileOverride.valid_from.desc())
        )
        if _tax_override_is_rate_anchor(item)
    ]
    if len(anchors) > 1:
        return None, {"status": "conflict"}
    if not anchors:
        return None, {"status": "missing"}
    return _tax_profile_from_model(company.client_id, anchors[0]), {
        "status": "rate_anchor",
        "profileId": anchors[0].id,
    }


def _onec_organization_exists(
    db: Session,
    *,
    client_id: str,
    organization_id: str,
) -> bool:
    latest = db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.client_id == client_id,
            SourceRefreshRun.status.in_(
                {"source_loaded", "needs_review", "report_created"}
            ),
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )
    if latest is None:
        return False
    return (
        db.scalar(
            select(SourceSnapshotRow.id).where(
                SourceSnapshotRow.refresh_run_id == latest.id,
                SourceSnapshotRow.source_type == "onec_organizations",
                SourceSnapshotRow.row_payload["Ref_Key"].as_string() == organization_id,
            )
        )
        is not None
    )


def ensure_wb_cabinet(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    display_name: str,
    cabinet_key: str = "",
    provider: str = "",
    client_company_id: str = "",
) -> WbCabinet | None:
    label = display_name.strip()
    key = _stable_key(cabinet_key or label)
    if not key:
        return None
    cabinet_id = _stable_entity_id("wb", client_id, key)
    now = security.utcnow()
    cabinet = db.get(WbCabinet, cabinet_id)
    if cabinet is None:
        cabinet = _matching_wb_cabinet(
            db,
            client_id=client_id,
            label=label,
            cabinet_key=key,
            provider=provider,
        )
    if cabinet is None:
        cabinet = WbCabinet(
            id=cabinet_id,
            tenant_id=tenant_id,
            client_id=client_id,
            client_company_id=client_company_id or None,
            display_name=label or key,
            cabinet_key=key,
            provider=provider,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(cabinet)
        db.flush()
    else:
        cabinet.display_name = cabinet.display_name or label or key
        cabinet.provider = cabinet.provider or provider
        if client_company_id and not cabinet.client_company_id:
            cabinet.client_company_id = client_company_id
        cabinet.updated_at = now
    return cabinet


def _matching_wb_cabinet(
    db: Session,
    *,
    client_id: str,
    label: str,
    cabinet_key: str,
    provider: str,
) -> WbCabinet | None:
    label_key = _stable_key(label)
    identity_filters = []
    if label:
        identity_filters.append(WbCabinet.display_name == label)
    if label_key:
        identity_filters.append(WbCabinet.cabinet_key == label_key)
    if provider:
        identity_filters.append(WbCabinet.provider == provider)
    if cabinet_key:
        identity_filters.append(WbCabinet.cabinet_key == cabinet_key)
    if not identity_filters:
        return None
    candidates = list(
        db.scalars(
            select(WbCabinet).where(
                WbCabinet.client_id == client_id,
                or_(*identity_filters),
            )
        )
    )
    if not candidates:
        return None

    def sort_key(item: WbCabinet) -> tuple[int, int, int, int, datetime, str]:
        display_match = int(not label or item.display_name != label)
        label_key_match = int(not label_key or item.cabinet_key != label_key)
        provider_match = int(not provider or item.provider != provider)
        active_match = int(item.status != "active")
        return (
            display_match,
            label_key_match,
            provider_match,
            active_match,
            _as_aware(item.created_at),
            item.id,
        )

    return sorted(candidates, key=sort_key)[0]


def dedupe_wb_cabinets(
    db: Session,
    *,
    tenant_id: str = "",
    client_id: str = "",
) -> dict[str, int]:
    conditions = []
    if tenant_id:
        conditions.append(WbCabinet.tenant_id == tenant_id)
    if client_id:
        conditions.append(WbCabinet.client_id == client_id)
    cabinets = list(
        db.scalars(select(WbCabinet).where(*conditions).order_by(WbCabinet.id))
    )
    groups: dict[tuple[str, str], list[WbCabinet]] = defaultdict(list)
    for cabinet in cabinets:
        normalized_name = _stable_key(cabinet.display_name)
        if not normalized_name:
            continue
        groups[(cabinet.client_id, normalized_name)].append(cabinet)

    integration_refs = _wb_integration_refs(db, tenant_id=tenant_id)
    counts: dict[str, int] = {
        "duplicate_groups": 0,
        "merged_cabinets": 0,
        "tenant_integrations": 0,
    }
    reference_models = (
        ReportUnitRow,
        ReportLostSalesRow,
        ReportDocumentReconciliationRow,
        SourceLoad,
        SourceRefreshCollection,
        SourceSnapshotRow,
        MarketplaceMappingItem,
    )
    for group in groups.values():
        if len(group) < 2:
            continue
        counts["duplicate_groups"] += 1
        canonical = _canonical_wb_cabinet(group, integration_refs)
        duplicates = [item for item in group if item.id != canonical.id]
        for duplicate in duplicates:
            _merge_wb_cabinet_fields(canonical, duplicate)
            counts["tenant_integrations"] += _retarget_integration_wb_cabinet(
                db,
                old_id=duplicate.id,
                new_cabinet=canonical,
            )
            for model in reference_models:
                key = model.__tablename__
                counts[key] = counts.get(key, 0) + _retarget_wb_cabinet_model(
                    db,
                    model,
                    old_id=duplicate.id,
                    new_id=canonical.id,
                    tenant_id=canonical.tenant_id,
                    client_id=canonical.client_id,
                )
            db.delete(duplicate)
            counts["merged_cabinets"] += 1
        canonical.updated_at = security.utcnow()
    db.flush()
    return counts


def _wb_integration_refs(
    db: Session, *, tenant_id: str = ""
) -> dict[str, list[TenantIntegration]]:
    conditions = []
    if tenant_id:
        conditions.append(TenantIntegration.tenant_id == tenant_id)
    refs: dict[str, list[TenantIntegration]] = defaultdict(list)
    for integration in db.scalars(select(TenantIntegration).where(*conditions)):
        if integration_provider_base(integration.provider) != "wb_api":
            continue
        payload = integration.config_payload or {}
        wb_cabinet_id = str(payload.get("wbCabinetId") or "").strip()
        if wb_cabinet_id:
            refs[wb_cabinet_id].append(integration)
    return refs


def _canonical_wb_cabinet(
    cabinets: list[WbCabinet],
    integration_refs: dict[str, list[TenantIntegration]],
) -> WbCabinet:
    integration_providers = {
        integration.provider
        for refs in integration_refs.values()
        for integration in refs
    }

    def sort_key(item: WbCabinet) -> tuple[int, int, int, int, datetime, str]:
        return (
            int(not integration_refs.get(item.id)),
            int(not item.provider or item.provider not in integration_providers),
            int(not item.provider),
            int(item.status != "active"),
            _as_aware(item.created_at),
            item.id,
        )

    return sorted(cabinets, key=sort_key)[0]


def _merge_wb_cabinet_fields(canonical: WbCabinet, duplicate: WbCabinet) -> None:
    if not canonical.client_company_id and duplicate.client_company_id:
        canonical.client_company_id = duplicate.client_company_id
    if not canonical.provider and duplicate.provider:
        canonical.provider = duplicate.provider
    if canonical.status != "active" and duplicate.status == "active":
        canonical.status = "active"
    if not canonical.display_name and duplicate.display_name:
        canonical.display_name = duplicate.display_name


def _retarget_integration_wb_cabinet(
    db: Session,
    *,
    old_id: str,
    new_cabinet: WbCabinet,
) -> int:
    changed = 0
    for integration in db.scalars(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == new_cabinet.tenant_id
        )
    ):
        if integration_provider_base(integration.provider) != "wb_api":
            continue
        payload = dict(integration.config_payload or {})
        if payload.get("wbCabinetId") != old_id:
            continue
        payload["wbCabinetId"] = new_cabinet.id
        payload["cabinetName"] = payload.get("cabinetName") or new_cabinet.display_name
        if new_cabinet.client_company_id and not payload.get("clientCompanyId"):
            payload["clientCompanyId"] = new_cabinet.client_company_id
        integration.config_payload = payload
        integration.updated_at = security.utcnow()
        changed += 1
    return changed


def _retarget_wb_cabinet_model(
    db: Session,
    model: type[ReportUnitRow]
    | type[ReportLostSalesRow]
    | type[ReportDocumentReconciliationRow]
    | type[SourceLoad]
    | type[SourceRefreshCollection]
    | type[SourceSnapshotRow]
    | type[MarketplaceMappingItem],
    *,
    old_id: str,
    new_id: str,
    tenant_id: str,
    client_id: str,
) -> int:
    conditions = [model.wb_cabinet_id == old_id]
    if hasattr(model, "tenant_id"):
        conditions.append(model.tenant_id == tenant_id)
    if hasattr(model, "client_id"):
        conditions.append(model.client_id == client_id)
    result = db.execute(
        update(model)
        .where(*conditions)
        .values(wb_cabinet_id=new_id)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def dedupe_client_companies(
    db: Session,
    *,
    tenant_id: str = "",
    client_id: str = "",
) -> dict[str, int]:
    conditions = [
        ClientCompany.status == "active",
        ClientCompany.onec_organization_id != "",
    ]
    if tenant_id:
        conditions.append(ClientCompany.tenant_id == tenant_id)
    if client_id:
        conditions.append(ClientCompany.client_id == client_id)
    companies = list(
        db.scalars(select(ClientCompany).where(*conditions).order_by(ClientCompany.id))
    )
    groups: dict[tuple[str, str], list[ClientCompany]] = defaultdict(list)
    for company in companies:
        groups[(company.client_id, company.onec_organization_id)].append(company)

    counts: dict[str, int] = {
        "duplicate_groups": 0,
        "merged_companies": 0,
        "client_company_aliases": 0,
        "tenant_integrations": 0,
        "wb_cabinets": 0,
        "organization_tax_profiles": 0,
        "organization_tax_profile_overrides": 0,
        "organization_input_vat_policies": 0,
        "report_unit_rows": 0,
        "report_document_reconciliation_rows": 0,
    }
    for group in groups.values():
        if len(group) < 2:
            for company in group:
                if (
                    ensure_client_company_alias(
                        db,
                        company=company,
                        display_name=company.display_name,
                        source="display_name",
                    )
                    is not None
                ):
                    counts["client_company_aliases"] += 1
            continue
        _assert_no_overlapping_tax_overrides(db, group)
        _assert_no_overlapping_input_vat_policies(db, group)
        counts["duplicate_groups"] += 1
        canonical = _canonical_client_company(db, group)
        display_name = max(
            (item.display_name.strip() for item in group if item.display_name.strip()),
            key=lambda value: (len(value), value.casefold()),
            default=canonical.display_name,
        )
        alias_labels = {
            item.display_name.strip() for item in group if item.display_name.strip()
        }
        alias_labels.update(
            label.strip()
            for label in db.scalars(
                select(WbCabinet.display_name).where(
                    WbCabinet.client_company_id.in_([item.id for item in group])
                )
            )
            if label and label.strip()
        )
        for alias in db.scalars(
            select(ClientCompanyAlias).where(
                ClientCompanyAlias.client_company_id.in_([item.id for item in group])
            )
        ):
            if alias.display_name.strip():
                alias_labels.add(alias.display_name.strip())
        duplicate_ids = [item.id for item in group if item.id != canonical.id]
        if duplicate_ids:
            db.execute(
                delete(ClientCompanyAlias).where(
                    ClientCompanyAlias.client_company_id.in_(duplicate_ids)
                )
            )
        canonical.display_name = display_name
        canonical.updated_at = security.utcnow()
        for label in sorted(alias_labels, key=str.casefold):
            ensure_client_company_alias(
                db,
                company=canonical,
                display_name=label,
                source="merged_alias",
            )
            counts["client_company_aliases"] += 1
        for duplicate in [item for item in group if item.id != canonical.id]:
            counts["tenant_integrations"] += _retarget_client_company_integrations(
                db,
                old_id=duplicate.id,
                canonical=canonical,
            )
            for model, field in (
                (WbCabinet, WbCabinet.client_company_id),
                (OrganizationTaxProfile, OrganizationTaxProfile.client_company_id),
                (
                    OrganizationTaxProfileOverride,
                    OrganizationTaxProfileOverride.client_company_id,
                ),
                (
                    OrganizationInputVatPolicy,
                    OrganizationInputVatPolicy.client_company_id,
                ),
                (ReportUnitRow, ReportUnitRow.client_company_id),
                (
                    ReportDocumentReconciliationRow,
                    ReportDocumentReconciliationRow.client_company_id,
                ),
            ):
                result = db.execute(
                    update(model)
                    .where(field == duplicate.id)
                    .values(client_company_id=canonical.id)
                    .execution_options(synchronize_session=False)
                )
                counts[model.__tablename__] += int(result.rowcount or 0)
            db.delete(duplicate)
            counts["merged_companies"] += 1
        db.flush()
    return counts


def preview_client_company_dedupe(
    db: Session,
    *,
    tenant_id: str = "",
    client_id: str = "",
) -> dict[str, int]:
    conditions = [
        ClientCompany.status == "active",
        ClientCompany.onec_organization_id != "",
    ]
    if tenant_id:
        conditions.append(ClientCompany.tenant_id == tenant_id)
    if client_id:
        conditions.append(ClientCompany.client_id == client_id)
    companies = list(
        db.scalars(select(ClientCompany).where(*conditions).order_by(ClientCompany.id))
    )
    groups: dict[tuple[str, str], list[ClientCompany]] = defaultdict(list)
    for company in companies:
        groups[(company.client_id, company.onec_organization_id)].append(company)
    counts: dict[str, int] = {
        "duplicate_groups": 0,
        "merged_companies": 0,
        "client_company_aliases": 0,
        "tenant_integrations": 0,
        "wb_cabinets": 0,
        "organization_tax_profiles": 0,
        "organization_tax_profile_overrides": 0,
        "organization_input_vat_policies": 0,
        "report_unit_rows": 0,
        "report_document_reconciliation_rows": 0,
    }
    for group in groups.values():
        if len(group) < 2:
            continue
        _assert_no_overlapping_tax_overrides(db, group)
        _assert_no_overlapping_input_vat_policies(db, group)
        counts["duplicate_groups"] += 1
        canonical = _canonical_client_company(db, group)
        duplicate_ids = [item.id for item in group if item.id != canonical.id]
        counts["merged_companies"] += len(duplicate_ids)
        alias_labels = {
            item.display_name.strip() for item in group if item.display_name.strip()
        }
        alias_labels.update(
            label.strip()
            for label in db.scalars(
                select(WbCabinet.display_name).where(
                    WbCabinet.client_company_id.in_([item.id for item in group])
                )
            )
            if label and label.strip()
        )
        counts["client_company_aliases"] += len(
            {_stable_key(label) for label in alias_labels if _stable_key(label)}
        )
        for integration in db.scalars(
            select(TenantIntegration).where(
                TenantIntegration.tenant_id == canonical.tenant_id
            )
        ):
            linked_company_id = str(
                (integration.config_payload or {}).get("clientCompanyId") or ""
            )
            if linked_company_id in duplicate_ids:
                counts["tenant_integrations"] += 1
        for model, field in (
            (WbCabinet, WbCabinet.client_company_id),
            (OrganizationTaxProfile, OrganizationTaxProfile.client_company_id),
            (
                OrganizationTaxProfileOverride,
                OrganizationTaxProfileOverride.client_company_id,
            ),
            (
                OrganizationInputVatPolicy,
                OrganizationInputVatPolicy.client_company_id,
            ),
            (ReportUnitRow, ReportUnitRow.client_company_id),
            (
                ReportDocumentReconciliationRow,
                ReportDocumentReconciliationRow.client_company_id,
            ),
        ):
            counts[model.__tablename__] += int(
                db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(field.in_(duplicate_ids))
                )
                or 0
            )
    return counts


def _canonical_client_company(
    db: Session,
    group: list[ClientCompany],
) -> ClientCompany:
    integration_ids = {
        str((item.config_payload or {}).get("clientCompanyId") or "").strip()
        for item in db.scalars(
            select(TenantIntegration).where(
                TenantIntegration.tenant_id == group[0].tenant_id,
                TenantIntegration.disabled_at.is_(None),
            )
        )
    }

    def reference_count(
        model: Any,
        field: Any,
        company_id: str,
        *extra_conditions: Any,
    ) -> int:
        conditions = [field == company_id]
        conditions.extend(extra_conditions)
        return int(
            db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
        )

    def sort_key(item: ClientCompany) -> tuple[int, int, int, datetime, str]:
        active_cabinets = reference_count(
            WbCabinet,
            WbCabinet.client_company_id,
            item.id,
            WbCabinet.status == "active",
        )
        active_profiles = reference_count(
            OrganizationTaxProfile,
            OrganizationTaxProfile.client_company_id,
            item.id,
            OrganizationTaxProfile.status == "active",
        )
        return (
            -int(item.id in integration_ids),
            -active_cabinets,
            -active_profiles,
            _as_aware(item.created_at),
            item.id,
        )

    return sorted(group, key=sort_key)[0]


def _assert_no_overlapping_tax_overrides(
    db: Session,
    companies: list[ClientCompany],
) -> None:
    overrides = list(
        db.scalars(
            select(OrganizationTaxProfileOverride)
            .where(
                OrganizationTaxProfileOverride.client_company_id.in_(
                    [item.id for item in companies]
                ),
                OrganizationTaxProfileOverride.status == "active",
            )
            .order_by(OrganizationTaxProfileOverride.valid_from)
        )
    )
    for index, left in enumerate(overrides):
        left_end = left.valid_to or date.max
        for right in overrides[index + 1 :]:
            right_end = right.valid_to or date.max
            if left.valid_from <= right_end and right.valid_from <= left_end:
                raise ValueError(
                    "cannot merge client companies with overlapping active tax "
                    "overrides"
                )


def _assert_no_overlapping_input_vat_policies(
    db: Session,
    companies: list[ClientCompany],
) -> None:
    policies = list(
        db.scalars(
            select(OrganizationInputVatPolicy)
            .where(
                OrganizationInputVatPolicy.client_company_id.in_(
                    [item.id for item in companies]
                ),
                OrganizationInputVatPolicy.status == "active",
            )
            .order_by(OrganizationInputVatPolicy.valid_from)
        )
    )
    for index, left in enumerate(policies):
        left_end = left.valid_to or date.max
        for right in policies[index + 1 :]:
            right_end = right.valid_to or date.max
            if left.valid_from <= right_end and right.valid_from <= left_end:
                raise ValueError(
                    "cannot merge client companies with overlapping active input "
                    "VAT policies"
                )


def _retarget_client_company_integrations(
    db: Session,
    *,
    old_id: str,
    canonical: ClientCompany,
) -> int:
    changed = 0
    for integration in db.scalars(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == canonical.tenant_id
        )
    ):
        payload = dict(integration.config_payload or {})
        if str(payload.get("clientCompanyId") or "") != old_id:
            continue
        payload["clientCompanyId"] = canonical.id
        payload["organizationName"] = canonical.display_name
        integration.config_payload = payload
        integration.updated_at = security.utcnow()
        changed += 1
    return changed


def ensure_client_company_identity_index(db: Session) -> None:
    db.flush()
    table_name = (
        "client_companies"
        if db.bind is not None and db.bind.dialect.name == "sqlite"
        else "wb_unit_economics.client_companies"
    )
    db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_client_companies_active_onec_organization "
            f"ON {table_name} (client_id, onec_organization_id) "
            "WHERE onec_organization_id <> '' AND status = 'active'"
        )
    )


def merge_client_company_into(
    db: Session,
    *,
    duplicate: ClientCompany,
    canonical: ClientCompany,
) -> dict[str, int]:
    if duplicate.id == canonical.id:
        return {"merged_companies": 0}
    if (
        duplicate.client_id != canonical.client_id
        or duplicate.tenant_id != canonical.tenant_id
    ):
        raise ValueError("client company merge scope mismatch")
    if (
        duplicate.onec_organization_id
        and canonical.onec_organization_id
        and duplicate.onec_organization_id != canonical.onec_organization_id
    ):
        raise ValueError("cannot merge different 1C organizations")
    _assert_no_overlapping_tax_overrides(db, [canonical, duplicate])
    labels = {canonical.display_name, duplicate.display_name}
    labels.update(
        label
        for label in db.scalars(
            select(WbCabinet.display_name).where(
                WbCabinet.client_company_id.in_([canonical.id, duplicate.id])
            )
        )
        if label
    )
    labels.update(
        alias.display_name
        for alias in db.scalars(
            select(ClientCompanyAlias).where(
                ClientCompanyAlias.client_company_id.in_([canonical.id, duplicate.id])
            )
        )
        if alias.display_name
    )
    db.execute(
        delete(ClientCompanyAlias).where(
            ClientCompanyAlias.client_company_id == duplicate.id
        )
    )
    canonical.display_name = max(
        (label.strip() for label in labels if label and label.strip()),
        key=lambda value: (len(value), value.casefold()),
        default=canonical.display_name,
    )
    for label in labels:
        ensure_client_company_alias(
            db,
            company=canonical,
            display_name=label,
            source="merged_alias",
        )
    counts = {
        "merged_companies": 1,
        "tenant_integrations": _retarget_client_company_integrations(
            db,
            old_id=duplicate.id,
            canonical=canonical,
        ),
    }
    for model, field in (
        (WbCabinet, WbCabinet.client_company_id),
        (OrganizationTaxProfile, OrganizationTaxProfile.client_company_id),
        (
            OrganizationTaxProfileOverride,
            OrganizationTaxProfileOverride.client_company_id,
        ),
        (ReportUnitRow, ReportUnitRow.client_company_id),
        (
            ReportDocumentReconciliationRow,
            ReportDocumentReconciliationRow.client_company_id,
        ),
    ):
        result = db.execute(
            update(model)
            .where(field == duplicate.id)
            .values(client_company_id=canonical.id)
            .execution_options(synchronize_session=False)
        )
        counts[model.__tablename__] = int(result.rowcount or 0)
    db.delete(duplicate)
    canonical.updated_at = security.utcnow()
    db.flush()
    return counts


def create_client_workspace(
    db: Session,
    *,
    user: User,
    name: str,
    tenant_id: str = "",
    client_id: str = "",
    companies: list[str] | None = None,
    cabinets: list[str] | None = None,
) -> Client:
    require_staff(user)
    label = name.strip()
    if not label:
        raise ValueError("client name is required")
    tenant_key = _safe_identifier(tenant_id)
    if not tenant_key:
        tenant_key = _safe_identifier(_stable_key(label))
    if not tenant_key:
        tenant_key = _stable_entity_id("tenant", label)
    if db.get(Tenant, tenant_key) is not None:
        raise ValueError("tenant already exists")
    client_key = (
        _safe_identifier(client_id) if client_id else client_id_for_tenant(tenant_key)
    )
    if db.get(Client, client_key) is not None:
        raise ValueError("client already exists")

    now = security.utcnow()
    tenant = Tenant(id=tenant_key, name=label, created_at=now)
    db.add(tenant)
    db.flush()
    client = ensure_client(db, tenant_id=tenant.id, client_id=client_key, name=label)
    creator_role = "admin" if has_role(user, {"admin"}) else "consultant"
    access = UserTenantAccess(
        user_id=user.id,
        tenant_id=tenant.id,
        role=creator_role,
        created_at=now,
    )
    db.add(access)
    user.access.append(access)

    company_ids_by_label: dict[str, str] = {}
    for company_label in _clean_labels(companies or [])[:20]:
        company = ensure_client_company(
            db,
            tenant_id=tenant.id,
            client_id=client.id,
            display_name=company_label,
        )
        if company is not None:
            company_ids_by_label[company.display_name] = company.id

    for cabinet_value in _clean_labels(cabinets or [])[:20]:
        company_label, separator, cabinet_label = cabinet_value.partition("::")
        cabinet_name = cabinet_label.strip() if separator else cabinet_value
        linked_company_id = ""
        if separator:
            company = ensure_client_company(
                db,
                tenant_id=tenant.id,
                client_id=client.id,
                display_name=company_label,
            )
            linked_company_id = company.id if company is not None else ""
        elif len(company_ids_by_label) == 1:
            linked_company_id = next(iter(company_ids_by_label.values()))
        ensure_wb_cabinet(
            db,
            tenant_id=tenant.id,
            client_id=client.id,
            display_name=cabinet_name,
            client_company_id=linked_company_id,
        )

    audit(
        db,
        action="client_created",
        user=user,
        tenant_id=tenant.id,
        entity_type="client",
        entity_id=client.id,
        payload={
            "clientName": client.name,
            "companies": len(company_ids_by_label),
            "cabinets": len(_clean_labels(cabinets or [])),
        },
    )
    return client


def upsert_client_wb_cabinet(
    db: Session,
    *,
    user: User,
    client_id: str,
    display_name: str,
    cabinet_id: str = "",
    organization_name: str = "",
    status: str = "active",
) -> Client:
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    label = display_name.strip()
    if not label:
        raise ValueError("cabinet name is required")
    if status not in {"active", "disabled"}:
        raise ValueError("unsupported cabinet status")

    company = ensure_client_company(
        db,
        tenant_id=client.tenant_id,
        client_id=client.id,
        display_name=organization_name,
    )
    company_id = company.id if company is not None else ""
    now = security.utcnow()
    if cabinet_id:
        cabinet = db.get(WbCabinet, cabinet_id)
        if cabinet is None or cabinet.client_id != client.id:
            raise LookupError("cabinet not found")
        cabinet.display_name = label
        cabinet.client_company_id = company_id or None
        cabinet.status = status
        cabinet.updated_at = now
    else:
        cabinet = ensure_wb_cabinet(
            db,
            tenant_id=client.tenant_id,
            client_id=client.id,
            display_name=label,
            client_company_id=company_id,
        )
        if cabinet is None:
            raise ValueError("cabinet name is required")
        cabinet.status = status
        cabinet.updated_at = now

    if cabinet.provider:
        integration = _tenant_integration(db, client.tenant_id, cabinet.provider)
        if integration is not None:
            provider_base = integration_provider_base(integration.provider)
            config_payload = dict(integration.config_payload or {})
            config_payload.update(
                {
                    "cabinetName": cabinet.display_name,
                    "organizationName": company.display_name if company else "",
                    "clientId": client.id,
                    "clientCompanyId": company_id,
                    "wbCabinetId": cabinet.id,
                }
            )
            integration.config_payload = config_payload
            if provider_base == "wb_api":
                provider_label = providers.provider_label(provider_base)
                integration.label = f"{provider_label} · {cabinet.display_name}"[:200]
            integration.updated_at = now
    db.flush()
    audit(
        db,
        action="wb_cabinet_saved",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="wb_cabinet",
        entity_id=cabinet.id,
        payload={
            "clientId": client.id,
            "cabinetName": cabinet.display_name,
            "organizationName": company.display_name if company else "",
            "status": cabinet.status,
            "provider": cabinet.provider,
        },
    )
    return client


def _clean_labels(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        label = str(value or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(label)
    return result


def list_clients_for_user(db: Session, user: User) -> list[dict[str, Any]]:
    tenant_ids = allowed_tenant_ids(user)
    if not tenant_ids:
        return []
    tenants_by_id = {
        tenant.id: tenant
        for tenant in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids)))
    }
    clients: list[Client] = []
    for tenant_id in tenant_ids:
        tenant = tenants_by_id.get(tenant_id)
        if tenant is None:
            continue
        existing_client = db.scalar(select(Client).where(Client.tenant_id == tenant.id))
        if existing_client is None:
            ensure_client_for_tenant(db, tenant_id=tenant.id, name=tenant.name)
    clients = list(
        db.scalars(
            select(Client)
            .where(Client.tenant_id.in_(tenant_ids))
            .order_by(Client.name, Client.id)
        )
    )
    db.flush()
    return [client_payload(db, user, client) for client in clients]


def client_payload(db: Session, user: User, client: Client) -> dict[str, Any]:
    latest = latest_report_for_client(db, user, client.id)
    roles = roles_for_tenant(user, client.tenant_id)
    role = _highest_role(roles)
    return {
        "clientId": client.id,
        "id": client.id,
        "tenantId": client.tenant_id,
        "firmId": client.firm_id,
        "name": client.name,
        "status": client.status,
        "role": role,
        "currentReportId": latest.id if latest else "",
        "latestReportId": latest.id if latest else "",
        "companies": _client_companies_payload(db, client),
        "cabinets": _client_cabinets_payload(db, client),
    }


def _client_companies_payload(db: Session, client: Client) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in db.scalars(
        select(ClientCompany)
        .where(ClientCompany.client_id == client.id)
        .order_by(ClientCompany.display_name, ClientCompany.id)
    ):
        profile, profile_status = resolve_company_tax_profile(
            db,
            company=item,
            calculation_date=security.utcnow().date(),
        )
        if profile is not None and not tax_profile_is_confirmed(profile):
            profile_status = {
                **profile_status,
                "status": "unconfirmed",
                "message": (
                    "Налоговый профиль найден, но право на вычет или методика "
                    "не подтверждены."
                ),
            }
        result.append(
            {
                "id": item.id,
                "label": item.display_name,
                "status": item.status,
                "onecOrganizationId": item.onec_organization_id,
                "taxProfileStatus": profile_status.get("status") or "missing",
                "taxProfileSource": profile_status.get("source") or "missing",
                "taxSystem": profile.tax_system if profile else "",
                "taxObject": profile.tax_object if profile else "",
                "taxRate": float(profile.tax_rate) if profile else None,
                "elevatedTaxRate": (
                    float(profile.elevated_tax_rate) if profile else None
                ),
                "vatRate": float(profile.vat_rate) if profile else None,
                "vatMode": profile.vat_mode.value if profile else "",
                "vatDeductionMode": (
                    profile.vat_deduction_mode.value if profile else "unknown"
                ),
                "revenueTaxRate": (
                    float(profile.revenue_tax_rate) if profile else None
                ),
                "taxProfileValidFrom": (
                    profile.valid_from.isoformat()
                    if profile and profile.valid_from
                    else None
                ),
                "taxProfileValidTo": (
                    profile.valid_to.isoformat()
                    if profile and profile.valid_to
                    else None
                ),
                "taxProfileManualOverride": bool(profile_status.get("manualOverride")),
            }
        )
    return result


def _client_cabinets_payload(db: Session, client: Client) -> list[dict[str, str]]:
    return [
        {
            "id": item.id,
            "label": item.display_name,
            "clientCompanyId": item.client_company_id or "",
            "provider": item.provider,
            "status": item.status,
        }
        for item in db.scalars(
            select(WbCabinet)
            .where(WbCabinet.client_id == client.id)
            .order_by(WbCabinet.display_name, WbCabinet.id)
        )
    ]


def require_client_access(db: Session, user: User, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None or client.tenant_id not in allowed_tenant_ids(user):
        raise PermissionError("client access denied")
    return client


def list_tenant_integrations(
    db: Session, user: User, *, tenant_id: str
) -> list[dict[str, Any]]:
    require_staff(user, tenant_id)
    existing = []
    for item in db.scalars(
        select(TenantIntegration)
        .where(TenantIntegration.tenant_id == tenant_id)
        .order_by(TenantIntegration.provider)
    ):
        if providers.is_supported_provider(item.provider):
            existing.append(item)
    by_provider = {item.provider: item for item in existing}
    payloads = [
        tenant_integration_payload(by_provider.get(provider), tenant_id, provider)
        for provider in providers.PROVIDER_ORDER
    ]
    payloads.extend(
        tenant_integration_payload(item, tenant_id, item.provider)
        for item in existing
        if not integration_is_primary_provider(item.provider)
    )
    return sorted(payloads, key=_integration_payload_sort_key)


def save_tenant_integration(
    db: Session,
    *,
    user: User,
    tenant_id: str,
    provider: str,
    secret: str,
    label: str = "",
    connection_role: str = "",
    cabinet_name: str = "",
    organization_name: str = "",
    secret_storage: dict[str, Any] | None = None,
) -> TenantIntegration:
    require_staff(user, tenant_id)
    _validate_integration_provider(provider)
    provider_base = integration_provider_base(provider)
    connection_key = integration_connection_key(provider)
    normalized_secret = secret.strip()
    if not normalized_secret:
        raise ValueError("integration secret is required")
    tenant = db.get(Tenant, tenant_id)
    client = ensure_client_for_tenant(
        db,
        tenant_id=tenant_id,
        name=tenant.name if tenant else tenant_id,
    )
    company_id = ""
    cabinet = None
    if provider_base == "wb_api":
        cabinet_label = cabinet_name.strip()
        if cabinet_label:
            cabinet = db.scalar(
                select(WbCabinet)
                .where(
                    WbCabinet.client_id == client.id,
                    WbCabinet.display_name == cabinet_label,
                )
                .order_by((WbCabinet.provider == "").desc(), WbCabinet.id)
            )
        if cabinet is not None:
            company_id = cabinet.client_company_id or ""
            if provider and not cabinet.provider:
                cabinet.provider = provider
                cabinet.updated_at = security.utcnow()
        else:
            company = ensure_client_company(
                db,
                tenant_id=tenant_id,
                client_id=client.id,
                display_name=organization_name,
            )
            company_id = company.id if company else ""
            cabinet = ensure_wb_cabinet(
                db,
                tenant_id=tenant_id,
                client_id=client.id,
                display_name=cabinet_label,
                cabinet_key=connection_key,
                provider=provider,
                client_company_id=company_id,
            )
    else:
        company = ensure_client_company(
            db,
            tenant_id=tenant_id,
            client_id=client.id,
            display_name=organization_name,
        )
        company_id = company.id if company else ""
    wb_cabinet_id = cabinet.id if cabinet else ""
    now = security.utcnow()
    integration = db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == provider,
        )
    )
    if integration is None:
        integration = TenantIntegration(
            tenant_id=tenant_id,
            provider=provider,
            created_at=now,
            updated_at=now,
        )
        db.add(integration)
    integration.label = (label.strip() or providers.provider_label(provider_base))[:200]
    integration.status = "configured"
    integration.secret_hash = _secret_hash(normalized_secret)
    integration.secret_hint = _secret_hint(normalized_secret)
    integration.config_payload = {
        "storage": "hash_only",
        "readOnly": True,
        "providerBase": provider_base,
        "connectionKey": connection_key,
        "connectionRole": _normalize_integration_role(provider_base, connection_role),
        "cabinetName": cabinet_name.strip()[:200],
        "organizationName": organization_name.strip()[:200],
        "clientId": client.id,
        "clientCompanyId": company_id,
        "wbCabinetId": wb_cabinet_id,
        "isPrimary": integration_is_primary_provider(provider),
        **(secret_storage or {}),
    }
    integration.disabled_at = None
    integration.updated_at = now
    db.flush()
    audit(
        db,
        action="tenant_integration_saved",
        user=user,
        tenant_id=tenant_id,
        entity_type="tenant_integration",
        entity_id=f"{tenant_id}:{provider}",
        payload={
            "provider": provider,
            "providerBase": provider_base,
            "connectionKey": connection_key,
            "connectionRole": integration.config_payload.get("connectionRole", ""),
            "clientId": integration.config_payload.get("clientId", ""),
            "clientCompanyId": integration.config_payload.get("clientCompanyId", ""),
            "wbCabinetId": integration.config_payload.get("wbCabinetId", ""),
            "status": integration.status,
            "secretHint": integration.secret_hint,
            "storage": integration.config_payload.get("storage", "hash_only"),
        },
    )
    return integration


def get_tenant_integration_for_staff(
    db: Session,
    *,
    user: User,
    tenant_id: str,
    provider: str,
) -> TenantIntegration:
    require_staff(user, tenant_id)
    _validate_integration_provider(provider)
    return _ensure_empty_integration(db, tenant_id, provider)


def record_tenant_integration_check(
    db: Session,
    *,
    user: User,
    tenant_id: str,
    provider: str,
    status: str,
    message: str,
    check_payload: dict[str, Any],
) -> TenantIntegration:
    require_staff(user, tenant_id)
    _validate_integration_provider(provider)
    if status not in {"check_ok", "check_failed"}:
        raise ValueError("unsupported integration check status")
    integration = _tenant_integration(db, tenant_id, provider)
    now = security.utcnow()
    if integration is None:
        integration = _ensure_empty_integration(db, tenant_id, provider)
    integration.status = status
    integration.last_checked_at = now
    config_payload = dict(integration.config_payload or {})
    config_payload["lastCheck"] = {
        "status": status,
        "message": message,
        **check_payload,
    }
    integration.config_payload = config_payload
    integration.updated_at = now
    db.flush()
    audit(
        db,
        action="tenant_integration_checked",
        user=user,
        tenant_id=tenant_id,
        entity_type="tenant_integration",
        entity_id=f"{tenant_id}:{provider}",
        payload={
            "provider": provider,
            "status": integration.status,
            "mode": check_payload.get("checkMode", "configuration"),
            "message": message,
            "httpStatus": check_payload.get("httpStatus"),
            "endpointCategory": check_payload.get("endpointCategory"),
        },
    )
    return integration


def record_tenant_integration_runtime_check(
    db: Session,
    *,
    tenant_id: str,
    provider: str,
    status: str,
    message: str,
    check_payload: dict[str, Any],
) -> TenantIntegration | None:
    """Store scheduler health separately from the last manual integration check."""

    _validate_integration_provider(provider)
    if status not in {"check_ok", "check_failed"}:
        raise ValueError("unsupported runtime integration check status")
    integration = _tenant_integration(db, tenant_id, provider)
    if integration is None:
        return None
    now = security.utcnow()
    config_payload = dict(integration.config_payload or {})
    config_payload["lastRuntimeCheck"] = {
        "status": status,
        "message": message[:1000],
        "checkedAt": now.isoformat(),
        **check_payload,
    }
    integration.config_payload = config_payload
    integration.updated_at = now
    db.flush()
    return integration


def disable_tenant_integration(
    db: Session,
    *,
    user: User,
    tenant_id: str,
    provider: str,
) -> TenantIntegration:
    require_staff(user, tenant_id)
    _validate_integration_provider(provider)
    integration = _ensure_empty_integration(db, tenant_id, provider)
    now = security.utcnow()
    integration.status = "disabled"
    integration.disabled_at = now
    integration.updated_at = now
    db.flush()
    audit(
        db,
        action="tenant_integration_disabled",
        user=user,
        tenant_id=tenant_id,
        entity_type="tenant_integration",
        entity_id=f"{tenant_id}:{provider}",
        payload={"provider": provider, "status": integration.status},
    )
    return integration


def tenant_integration_payload(
    integration: TenantIntegration | None, tenant_id: str, provider: str
) -> dict[str, Any]:
    _validate_integration_provider(provider)
    provider_base = integration_provider_base(provider)
    connection_key = integration_connection_key(provider)
    if integration is None:
        return {
            "tenantId": tenant_id,
            "provider": provider,
            "providerBase": provider_base,
            "connectionKey": connection_key,
            "connectionRole": _normalize_integration_role(provider_base, ""),
            "cabinetName": "",
            "organizationName": "",
            "clientId": client_id_for_tenant(tenant_id),
            "clientCompanyId": "",
            "wbCabinetId": "",
            "isPrimary": integration_is_primary_provider(provider),
            "label": providers.provider_label(provider_base),
            "status": "not_configured",
            "configured": False,
            "secretHint": "",
            "lastCheckedAt": None,
            "disabledAt": None,
            "readOnly": True,
            "storageMode": "none",
            "lastCheck": None,
            "runtimeStatus": "",
            "runtimeCheckedAt": None,
            "runtimeMessage": "",
            "lastRuntimeCheck": None,
        }
    config_payload = integration.config_payload or {}
    runtime_check = config_payload.get("lastRuntimeCheck") or {}
    return {
        "tenantId": integration.tenant_id,
        "provider": integration.provider,
        "providerBase": provider_base,
        "connectionKey": connection_key,
        "connectionRole": config_payload.get(
            "connectionRole", _normalize_integration_role(provider_base, "")
        ),
        "cabinetName": config_payload.get("cabinetName", ""),
        "organizationName": config_payload.get("organizationName", ""),
        "clientId": config_payload.get(
            "clientId",
            client_id_for_tenant(integration.tenant_id),
        ),
        "clientCompanyId": config_payload.get("clientCompanyId", ""),
        "wbCabinetId": config_payload.get("wbCabinetId", ""),
        "isPrimary": integration_is_primary_provider(provider),
        "label": integration.label or providers.provider_label(provider_base),
        "status": integration.status,
        "configured": bool(integration.secret_hash)
        and integration.status != "disabled",
        "secretHint": integration.secret_hint,
        "lastCheckedAt": (
            integration.last_checked_at.isoformat()
            if integration.last_checked_at
            else None
        ),
        "disabledAt": (
            integration.disabled_at.isoformat() if integration.disabled_at else None
        ),
        "readOnly": True,
        "storageMode": config_payload.get("storage", "hash_only"),
        "lastCheck": config_payload.get("lastCheck"),
        "runtimeStatus": runtime_check.get("status", ""),
        "runtimeCheckedAt": runtime_check.get("checkedAt"),
        "runtimeMessage": runtime_check.get("message", ""),
        "lastRuntimeCheck": runtime_check or None,
    }


def upsert_user(
    db: Session,
    *,
    email: str,
    password: str,
    tenant_id: str,
    role: str,
    name: str = "",
) -> User:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(
            id=new_id("user"),
            email=normalized_email,
            name=name or normalized_email,
            password_hash=security.hash_password(password),
            is_active=True,
            created_at=security.utcnow(),
        )
        db.add(user)
        db.flush()
    else:
        user.password_hash = security.hash_password(password)
        user.is_active = True
        if name:
            user.name = name
    access = db.scalar(
        select(UserTenantAccess).where(
            UserTenantAccess.user_id == user.id,
            UserTenantAccess.tenant_id == tenant_id,
        )
    )
    if access is None:
        db.add(
            UserTenantAccess(
                user_id=user.id,
                tenant_id=tenant_id,
                role=role,
                created_at=security.utcnow(),
            )
        )
    else:
        access.role = role
    return user


def list_users_for_admin(db: Session, admin: User) -> list[User]:
    require_admin(admin)
    tenant_ids = allowed_tenant_ids(admin)
    if not tenant_ids:
        return []
    return list(
        db.scalars(
            select(User)
            .join(UserTenantAccess)
            .where(UserTenantAccess.tenant_id.in_(tenant_ids))
            .distinct()
            .order_by(User.email)
        )
    )


def create_managed_user(
    db: Session,
    *,
    admin: User,
    email: str,
    tenant_id: str,
    role: str,
    password: str,
    name: str = "",
) -> User:
    require_admin(admin, tenant_id)
    if role not in VALID_ROLES:
        raise ValueError("invalid role")
    normalized_email = email.strip().lower()
    if db.scalar(select(User).where(User.email == normalized_email)) is not None:
        raise ValueError("user already exists")
    user = User(
        id=new_id("user"),
        email=normalized_email,
        name=name or normalized_email,
        password_hash=security.hash_password(password),
        is_active=True,
        created_at=security.utcnow(),
    )
    db.add(user)
    db.flush()
    db.add(
        UserTenantAccess(
            user_id=user.id,
            tenant_id=tenant_id,
            role=role,
            created_at=security.utcnow(),
        )
    )
    audit(
        db,
        action="user_created",
        user=admin,
        tenant_id=tenant_id,
        entity_type="user",
        entity_id=user.id,
        payload={"email": normalized_email, "role": role},
    )
    return user


def update_managed_user(
    db: Session,
    *,
    admin: User,
    target_user_id: str,
    tenant_id: str,
    name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    require_admin(admin, tenant_id)
    target = db.get(User, target_user_id)
    if target is None:
        raise LookupError("user not found")
    access = db.scalar(
        select(UserTenantAccess).where(
            UserTenantAccess.user_id == target.id,
            UserTenantAccess.tenant_id == tenant_id,
        )
    )
    if access is None:
        raise PermissionError("user tenant access denied")
    changed: dict[str, Any] = {}
    if name is not None:
        target.name = name.strip() or target.email
        changed["name"] = target.name
    if role is not None:
        if role not in VALID_ROLES:
            raise ValueError("invalid role")
        access.role = role
        changed["role"] = role
    if is_active is not None:
        target.is_active = is_active
        changed["is_active"] = is_active
        if not is_active:
            delete_sessions_for_user(db, target.id)
    audit(
        db,
        action="user_updated",
        user=admin,
        tenant_id=tenant_id,
        entity_type="user",
        entity_id=target.id,
        payload=changed,
    )
    return target


def reset_managed_user_password(
    db: Session,
    *,
    admin: User,
    target_user_id: str,
    tenant_id: str,
    password: str,
) -> User:
    require_admin(admin, tenant_id)
    target = db.get(User, target_user_id)
    if target is None:
        raise LookupError("user not found")
    if tenant_id not in allowed_tenant_ids(target):
        raise PermissionError("user tenant access denied")
    target.password_hash = security.hash_password(password)
    target.is_active = True
    delete_sessions_for_user(db, target.id)
    audit(
        db,
        action="user_password_reset",
        user=admin,
        tenant_id=tenant_id,
        entity_type="user",
        entity_id=target.id,
    )
    return target


def list_reports_for_user(
    db: Session,
    user: User,
    *,
    client_id: str | None = None,
    report_kind: str | None = MARKETPLACE_UNIT_ECONOMICS,
    organization_id: str | None = None,
) -> list[ReportRun]:
    if client_id:
        return list_reports_for_client(
            db,
            user,
            client_id,
            report_kind=report_kind,
            organization_id=organization_id,
        )
    tenant_ids = allowed_tenant_ids(user)
    if not tenant_ids:
        return []
    statement = select(ReportRun).where(ReportRun.tenant_id.in_(tenant_ids))
    if report_kind:
        statement = statement.where(ReportRun.report_kind == report_kind)
    if organization_id:
        statement = statement.where(ReportRun.organization_id == organization_id)
    reports = list(
        db.scalars(
            statement.order_by(
                ReportRun.is_current.desc(), ReportRun.generated_at.desc()
            )
        )
    )
    return [report for report in reports if _report_visible_to_user(user, report)]


def list_reports_for_client(
    db: Session,
    user: User,
    client_id: str,
    *,
    report_kind: str | None = MARKETPLACE_UNIT_ECONOMICS,
    organization_id: str | None = None,
) -> list[ReportRun]:
    client = require_client_access(db, user, client_id)
    statement = select(ReportRun).where(
        ReportRun.tenant_id == client.tenant_id,
        ReportRun.client_id == client.id,
    )
    if report_kind:
        statement = statement.where(ReportRun.report_kind == report_kind)
    if organization_id:
        statement = statement.where(ReportRun.organization_id == organization_id)
    reports = list(
        db.scalars(
            statement.order_by(
                ReportRun.is_current.desc(), ReportRun.generated_at.desc()
            )
        )
    )
    return [report for report in reports if _report_visible_to_user(user, report)]


def latest_report_for_user(
    db: Session,
    user: User,
    *,
    client_id: str | None = None,
    report_kind: str = MARKETPLACE_UNIT_ECONOMICS,
    organization_id: str | None = None,
) -> ReportRun | None:
    if client_id:
        return latest_report_for_client(
            db,
            user,
            client_id,
            report_kind=report_kind,
            organization_id=organization_id,
        )
    tenant_ids = allowed_tenant_ids(user)
    if not tenant_ids:
        return None
    current_filters = [
        ReportRun.tenant_id.in_(tenant_ids),
        ReportRun.report_kind == report_kind,
        ReportRun.is_current.is_(True),
    ]
    if report_kind not in ACCOUNTING_REPORT_KINDS:
        current_filters.append(ReportRun.publication_status == "published")
    if organization_id:
        current_filters.append(ReportRun.organization_id == organization_id)
    current = db.scalar(
        select(ReportRun)
        .where(*current_filters)
        .order_by(ReportRun.generated_at.desc())
    )
    if current is not None and _report_visible_to_user(user, current):
        return current
    reports = list_reports_for_user(
        db,
        user,
        report_kind=report_kind,
        organization_id=organization_id,
    )
    return reports[0] if reports else None


def latest_report_for_client(
    db: Session,
    user: User,
    client_id: str,
    *,
    report_kind: str = MARKETPLACE_UNIT_ECONOMICS,
    organization_id: str | None = None,
) -> ReportRun | None:
    client = require_client_access(db, user, client_id)
    current_filters = [
        ReportRun.tenant_id == client.tenant_id,
        ReportRun.client_id == client.id,
        ReportRun.report_kind == report_kind,
        ReportRun.is_current.is_(True),
    ]
    if report_kind not in ACCOUNTING_REPORT_KINDS:
        current_filters.append(ReportRun.publication_status == "published")
    if organization_id:
        current_filters.append(ReportRun.organization_id == organization_id)
    current = db.scalar(
        select(ReportRun)
        .where(*current_filters)
        .order_by(ReportRun.generated_at.desc())
    )
    if current is not None and _report_visible_to_user(user, current):
        return current
    reports = list_reports_for_client(
        db,
        user,
        client_id,
        report_kind=report_kind,
        organization_id=organization_id,
    )
    return reports[0] if reports else None


def report_kinds_for_user(
    user: User,
    *,
    tenant_id: str,
    enabled_kinds: set[str],
) -> list[dict[str, object]]:
    roles = roles_for_tenant(user, tenant_id)
    result: list[dict[str, object]] = []
    for kind in enabled_kinds:
        definition = require_report_kind(kind)
        if roles.intersection(definition.roles):
            result.append(definition.payload())
    return sorted(result, key=lambda item: str(item["kind"]))


def _normalized_scenario_evidence(
    db: Session,
    *,
    client_id: str,
    report_kind: str,
    organization_id: str,
    period_start: date,
    period_end: date,
    refresh_run_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    source_type = f"{report_kind}_evidence"
    statement = (
        select(SourceRefreshCollection)
        .join(
            SourceRefreshRun,
            SourceRefreshRun.id == SourceRefreshCollection.refresh_run_id,
        )
        .where(
            SourceRefreshCollection.client_id == client_id,
            SourceRefreshCollection.source_type == source_type,
            SourceRefreshCollection.organization_id == organization_id,
        )
        .order_by(SourceRefreshRun.finished_at.desc())
    )
    if refresh_run_id:
        statement = statement.where(
            SourceRefreshCollection.refresh_run_id == refresh_run_id
        )
    else:
        statement = statement.where(
            SourceRefreshRun.period_start <= period_start,
            SourceRefreshRun.period_end >= period_end,
            SourceRefreshRun.finished_at.is_not(None),
        )
    collection = db.scalar(statement)
    if collection is None or not isinstance(collection.payload, dict):
        return {}, ""
    normalized = collection.payload.get("normalizedEvidence")
    if not isinstance(normalized, dict):
        return {}, ""
    evidence_organization = str(normalized.get("organizationId") or "")
    if evidence_organization and evidence_organization != organization_id:
        return {}, ""
    refresh = db.get(SourceRefreshRun, collection.refresh_run_id)
    return dict(normalized), refresh.snapshot_set_id if refresh else ""


def _tax_profile_payload_for_generation(
    db: Session,
    *,
    company: ClientCompany,
    calculation_date: date,
    refresh_run_id: str,
) -> dict[str, Any]:
    override = db.scalar(
        select(OrganizationTaxProfileOverride)
        .where(
            OrganizationTaxProfileOverride.client_company_id == company.id,
            OrganizationTaxProfileOverride.organization_id
            == company.onec_organization_id,
            OrganizationTaxProfileOverride.status == "active",
            OrganizationTaxProfileOverride.valid_from <= calculation_date,
            or_(
                OrganizationTaxProfileOverride.valid_to.is_(None),
                OrganizationTaxProfileOverride.valid_to >= calculation_date,
            ),
        )
        .order_by(OrganizationTaxProfileOverride.valid_from.desc())
    )
    if override is not None:
        override_contract = _tax_profile_from_model(company.client_id, override)
        return {
            "taxSystem": override.tax_system,
            "taxObject": override.tax_object,
            "taxRate": override.tax_rate,
            "elevatedTaxRate": override.elevated_tax_rate,
            "profileStatus": (
                "ready"
                if tax_profile_is_confirmed(override_contract)
                else "unconfirmed"
            ),
            "vatRate": override.vat_rate,
            "vatMode": override.vat_mode,
            "vatDeductionMode": override.vat_deduction_mode,
            "revenueTaxRate": override.revenue_tax_rate,
            "validFrom": override.valid_from.isoformat(),
            "validTo": override.valid_to.isoformat() if override.valid_to else None,
            "sourceKind": "manual_override",
            "sourceRefreshRunId": None,
            "sourceSnapshotHash": hashlib.sha256(
                repr(
                    (override.id, override.updated_at.isoformat(), override.reason)
                ).encode("utf-8")
            ).hexdigest(),
            "profileId": override.id,
        }
    profile = db.scalar(
        select(OrganizationTaxProfile)
        .where(
            OrganizationTaxProfile.source_refresh_run_id == refresh_run_id,
            OrganizationTaxProfile.client_company_id == company.id,
            OrganizationTaxProfile.organization_id == company.onec_organization_id,
            OrganizationTaxProfile.status == "active",
            or_(
                OrganizationTaxProfile.valid_from.is_(None),
                OrganizationTaxProfile.valid_from <= calculation_date,
            ),
            or_(
                OrganizationTaxProfile.valid_to.is_(None),
                OrganizationTaxProfile.valid_to >= calculation_date,
            ),
        )
        .order_by(OrganizationTaxProfile.valid_from.desc())
    )
    if profile is None:
        return {
            "profileStatus": "missing",
            "sourceKind": "missing",
            "sourceRefreshRunId": refresh_run_id,
            "sourceSnapshotHash": "",
            "profileId": None,
        }
    profile_contract = _tax_profile_from_model(company.client_id, profile)
    return {
        "taxSystem": profile.tax_system,
        "taxObject": profile.tax_object,
        "taxRate": profile.tax_rate,
        "elevatedTaxRate": profile.elevated_tax_rate,
        "profileStatus": (
            "ready" if tax_profile_is_confirmed(profile_contract) else "unconfirmed"
        ),
        "vatRate": profile.vat_rate,
        "vatMode": profile.vat_mode,
        "vatDeductionMode": profile.vat_deduction_mode,
        "revenueTaxRate": profile.revenue_tax_rate,
        "validFrom": profile.valid_from.isoformat() if profile.valid_from else None,
        "validTo": profile.valid_to.isoformat() if profile.valid_to else None,
        "sourceKind": profile.source,
        "sourceRefreshRunId": profile.source_refresh_run_id,
        "sourceSnapshotHash": profile.source_snapshot_hash,
        "profileId": profile.id,
    }


def scenario_payload_for_report(db: Session, report: ReportRun) -> dict[str, Any]:
    if report.report_kind == MONTH_CLOSE_CONTROL:
        stored = db.get(MonthCloseControlReport, report.id)
    elif report.report_kind == TAX_LOAD:
        stored = db.get(TaxLoadReport, report.id)
    else:
        raise ValueError("scenario payload is unavailable for report kind")
    if stored is None:
        raise LookupError("scenario payload not found")
    return {
        **dict(stored.payload),
        "payloadSha256": stored.payload_sha256,
    }


def generation_run_payload(run: SourceRefreshRun) -> dict[str, Any]:
    stage = run.generation_stage or (
        "completed"
        if run.status == "completed"
        else "failed"
        if run.status == "failed"
        else run.status
    )
    messages = {
        "queued": "Формирование отчета поставлено в очередь.",
        "refreshing_sources": "Выполняется read-only загрузка данных 1С.",
        "materializing_evidence": "Подготавливается проверяемый evidence-контракт.",
        "building_report": "Формируются Web и Excel из единого payload.",
        "completed": "Отчет сформирован.",
        "failed": "Отчет не сформирован; исходные данные не изменялись.",
    }
    return {
        "generationRunId": run.id,
        "status": run.status,
        "stage": stage,
        "reportKind": run.target_report_kind,
        "organizationId": run.organization_id,
        "periodMonth": run.period_start.strftime("%Y-%m"),
        "reportId": run.new_report_run_id,
        "deduplicated": False,
        "createdAt": run.created_at.isoformat(),
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
        "safeMessage": messages.get(stage, "Формирование отчета выполняется."),
    }


def _generation_request_fingerprint(
    *,
    report_kind: str,
    organization_id: str,
    period_start: date,
    period_end: date,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "reportKind": report_kind,
                "organizationId": organization_id,
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _add_generation_request_key(
    db: Session,
    *,
    client: Client,
    idempotency_key: str,
    request_fingerprint: str,
    generation_run_id: str,
) -> ReportGenerationRequest:
    item = ReportGenerationRequest(
        id=_stable_entity_id(
            "report_generation_request",
            client.tenant_id,
            client.id,
            idempotency_key,
        ),
        tenant_id=client.tenant_id,
        client_id=client.id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        generation_run_id=generation_run_id,
        created_at=security.utcnow(),
    )
    db.add(item)
    db.flush()
    return item


def generate_accounting_report(
    db: Session,
    *,
    user: User,
    client_id: str,
    report_kind: str,
    organization_id: str,
    period_start: date,
    period_end: date,
    idempotency_key: str,
) -> tuple[SourceRefreshRun, bool]:
    definition = require_report_kind(report_kind)
    if report_kind not in ACCOUNTING_REPORT_KINDS:
        raise ValueError("report generation is supported only for accounting kinds")
    if not definition.requires_organization or not organization_id:
        raise ValueError("organization is required")
    client = require_client_access(db, user, client_id)
    require_staff(user, client.tenant_id)
    company = db.scalar(
        select(ClientCompany).where(
            ClientCompany.client_id == client.id,
            ClientCompany.onec_organization_id == organization_id,
            ClientCompany.status == "active",
        )
    )
    if company is None:
        raise LookupError("organization not found")
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise ValueError("idempotency key is required")
    request_fingerprint = _generation_request_fingerprint(
        report_kind=report_kind,
        organization_id=organization_id,
        period_start=period_start,
        period_end=period_end,
    )
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {
                "lock_key": (
                    "report-generation-key:"
                    f"{client.tenant_id}:{client.id}:{idempotency_key}"
                )
            },
        )
    request_key = db.scalar(
        select(ReportGenerationRequest).where(
            ReportGenerationRequest.tenant_id == client.tenant_id,
            ReportGenerationRequest.client_id == client.id,
            ReportGenerationRequest.idempotency_key == idempotency_key,
        )
    )
    if request_key is not None:
        if request_key.request_fingerprint != request_fingerprint:
            raise ValueError("idempotency key was used for a different request")
        existing = db.get(SourceRefreshRun, request_key.generation_run_id)
        if existing is None:
            raise RuntimeError("idempotency mapping references a missing run")
        audit(
            db,
            action="report_generation_deduplicated",
            user=user,
            tenant_id=client.tenant_id,
            entity_type="source_refresh_run",
            entity_id=existing.id,
            payload={"reportKind": report_kind, "reason": "idempotency_key"},
        )
        return existing, True
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {
                "lock_key": (
                    f"report-generation-scope:{client.tenant_id}:{client.id}:"
                    f"{report_kind}:{organization_id}:{period_start:%Y-%m}"
                )
            },
        )
    active = db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.tenant_id == client.tenant_id,
            SourceRefreshRun.client_id == client.id,
            SourceRefreshRun.target_report_kind == report_kind,
            SourceRefreshRun.organization_id == organization_id,
            SourceRefreshRun.period_start == period_start,
            SourceRefreshRun.period_end == period_end,
            SourceRefreshRun.status.in_(ACTIVE_SOURCE_REFRESH_STATUSES),
            SourceRefreshRun.finished_at.is_(None),
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )
    if active is not None:
        _add_generation_request_key(
            db,
            client=client,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            generation_run_id=active.id,
        )
        audit(
            db,
            action="report_generation_deduplicated",
            user=user,
            tenant_id=client.tenant_id,
            entity_type="source_refresh_run",
            entity_id=active.id,
            payload={"reportKind": report_kind, "reason": "active_scope"},
        )
        return active, True

    now = security.utcnow()
    generation = SourceRefreshRun(
        id=new_id("report_generation"),
        tenant_id=client.tenant_id,
        client_id=client.id,
        target_report_kind=report_kind,
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        generation_stage="queued",
        requested_by_user_id=user.id,
        source_report_run_id=None,
        new_report_run_id=None,
        resumed_from_run_id=None,
        base_source_refresh_run_id=None,
        blocked_by_run_id=None,
        worker_id="",
        failure_code="",
        heartbeat_at=None,
        mode="report-generation",
        credential_source="tenant",
        dry_run=False,
        status="queued",
        reason="Staff-only advisory report generation",
        snapshot_set_id=new_id("snapshot_set"),
        period_start=period_start,
        period_end=period_end,
        source_window_start=(
            period_start.replace(month=1, day=1)
            if report_kind == TAX_LOAD
            else period_start
        ),
        source_window_end=period_end,
        root_dir="",
        workbook_path="",
        error_message="",
        created_at=now,
        started_at=None,
        finished_at=None,
        updated_at=now,
    )
    db.add(generation)
    db.flush()
    _add_generation_request_key(
        db,
        client=client,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        generation_run_id=generation.id,
    )
    audit(
        db,
        action="report_generation_requested",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="source_refresh_run",
        entity_id=generation.id,
        payload={
            "reportKind": report_kind,
            "organizationId": organization_id,
            "periodMonth": period_start.strftime("%Y-%m"),
        },
    )
    return generation, False


def complete_accounting_report_generation(
    db: Session,
    *,
    generation: SourceRefreshRun,
    user: User | None,
) -> ReportRun:
    if generation.mode != "report-generation":
        raise ValueError("generation run has an unsupported mode")
    report_kind = generation.target_report_kind
    organization_id = str(generation.organization_id or "")
    definition = require_report_kind(report_kind)
    client = db.get(Client, generation.client_id)
    if client is None:
        raise LookupError("generation client not found")
    company = db.scalar(
        select(ClientCompany).where(
            ClientCompany.client_id == client.id,
            ClientCompany.onec_organization_id == organization_id,
            ClientCompany.status == "active",
        )
    )
    if company is None:
        raise LookupError("generation organization not found")
    evidence_period_start = (
        generation.period_start.replace(month=1, day=1)
        if report_kind == TAX_LOAD
        else generation.period_start
    )
    evidence, snapshot_set_id = _normalized_scenario_evidence(
        db,
        client_id=client.id,
        report_kind=report_kind,
        organization_id=organization_id,
        period_start=evidence_period_start,
        period_end=generation.period_end,
        refresh_run_id=generation.id,
    )
    if not evidence:
        raise LookupError("accounting evidence contract was not materialized")
    now = security.utcnow()
    report = ReportRun(
        id=new_id("report"),
        tenant_id=client.tenant_id,
        client_id=client.id,
        client_name=client.name,
        report_kind=report_kind,
        organization_id=organization_id,
        title=f"{definition.title} — {generation.period_start:%m.%Y}",
        period_start=generation.period_start,
        period_end=generation.period_end,
        source_coverage_start=evidence_period_start,
        source_coverage_end=generation.period_end,
        period_text=(
            f"{generation.period_start:%d.%m.%Y} - {generation.period_end:%d.%m.%Y}"
        ),
        period_status="calendar_month",
        generated_at=now,
        status="preliminary",
        publication_status="draft",
        is_current=False,
        lineage_type="multi_report_advisory_v1",
        source_snapshot_set_id=snapshot_set_id or generation.snapshot_set_id,
        methodology_version=(
            "month-close-control-report-v2"
            if report_kind == MONTH_CLOSE_CONTROL
            else "tax-load-report-v2"
        ),
        marketplace_expense_context_version="",
        source_workbook="",
        source_workbook_path="",
        return_reason_limitation="",
        created_at=now,
    )
    db.add(report)
    db.flush()
    if report_kind == MONTH_CLOSE_CONTROL:
        payload = build_month_close_control_payload(report, evidence)
        stored: MonthCloseControlReport | TaxLoadReport = MonthCloseControlReport(
            report_run_id=report.id,
            contract_version=str(payload["contractVersion"]),
            payload_sha256=canonical_payload_sha256(payload),
            payload=payload,
            created_at=now,
        )
        report.status = str(payload["businessRecommendation"])
    else:
        profile = _tax_profile_payload_for_generation(
            db,
            company=company,
            calculation_date=generation.period_end,
            refresh_run_id=generation.id,
        )
        payload = build_tax_load_payload(report, tax_profile=profile, evidence=evidence)
        stored = TaxLoadReport(
            report_run_id=report.id,
            contract_version=str(payload["contractVersion"]),
            payload_sha256=canonical_payload_sha256(payload),
            payload=payload,
            created_at=now,
        )
        report.status = str(payload["businessStatus"])
    db.add(stored)
    _set_accounting_draft_current(db, report)
    generation.new_report_run_id = report.id
    generation.status = "completed"
    generation.generation_stage = "completed"
    generation.finished_at = security.utcnow()
    generation.updated_at = generation.finished_at
    audit(
        db,
        action="report_generation_completed",
        user=user,
        tenant_id=client.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "generationRunId": generation.id,
            "reportKind": report_kind,
            "payloadSha256": stored.payload_sha256,
        },
    )
    db.flush()
    return report


def _set_accounting_draft_current(db: Session, report: ReportRun) -> None:
    if report.report_kind not in ACCOUNTING_REPORT_KINDS or not report.organization_id:
        raise ValueError("staff advisory current requires an accounting organization")
    previous_reports = list(
        db.scalars(
            select(ReportRun).where(
                ReportRun.tenant_id == report.tenant_id,
                ReportRun.client_id == report.client_id,
                ReportRun.report_kind == report.report_kind,
                ReportRun.organization_id == report.organization_id,
                ReportRun.id != report.id,
                ReportRun.is_current.is_(True),
            )
        )
    )
    for previous in previous_reports:
        previous.is_current = False
    db.flush()
    report.publication_status = "draft"
    report.is_current = True


def require_report(db: Session, user: User, report_id: str) -> ReportRun:
    report = db.get(ReportRun, report_id)
    if (
        report is None
        or report.tenant_id not in allowed_tenant_ids(user)
        or not _report_visible_to_user(user, report)
    ):
        raise PermissionError("report access denied")
    return report


def require_report_for_client(
    db: Session,
    user: User,
    *,
    client_id: str,
    report_id: str,
) -> ReportRun:
    client = require_client_access(db, user, client_id)
    report = db.get(ReportRun, report_id)
    if (
        report is None
        or report.tenant_id != client.tenant_id
        or report.client_id != client.id
        or not _report_visible_to_user(user, report)
    ):
        raise PermissionError("report access denied")
    return report


def _report_visible_to_user(user: User, report: ReportRun) -> bool:
    if has_role(user, STAFF_ROLES, report.tenant_id):
        return True
    return report.publication_status == "published" and report.is_current


def active_data_refresh_job(db: Session, report: ReportRun) -> DataRefreshJob | None:
    return db.scalar(
        select(DataRefreshJob)
        .where(
            DataRefreshJob.tenant_id == report.tenant_id,
            DataRefreshJob.source_report_run_id == report.id,
            DataRefreshJob.status.in_(ACTIVE_REFRESH_STATUSES),
        )
        .order_by(DataRefreshJob.created_at.desc())
    )


def create_data_refresh_job(
    db: Session,
    *,
    user: User,
    report: ReportRun,
    reason: str,
    thread_id: str | None = None,
) -> DataRefreshJob:
    require_staff(user, report.tenant_id)
    existing = active_data_refresh_job(db, report)
    if existing is not None:
        raise ValueError("onec refresh already active for this report")
    now = security.utcnow()
    job = DataRefreshJob(
        id=new_id("refresh"),
        tenant_id=report.tenant_id,
        source_report_run_id=report.id,
        new_report_run_id=None,
        requested_by_user_id=user.id,
        thread_id=thread_id,
        status="queued",
        reason=reason.strip()[:4000],
        collections=[],
        snapshot_dir="",
        workbook_path="",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    audit(
        db,
        action="onec_auto_refresh_requested",
        user=user,
        tenant_id=report.tenant_id,
        entity_type="data_refresh_job",
        entity_id=job.id,
        payload={"source_report_run_id": report.id},
    )
    return job


def require_data_refresh_job(
    db: Session,
    *,
    user: User,
    report: ReportRun,
    job_id: str,
) -> DataRefreshJob:
    require_staff(user, report.tenant_id)
    job = db.get(DataRefreshJob, job_id)
    if (
        job is None
        or job.tenant_id != report.tenant_id
        or job.source_report_run_id != report.id
    ):
        raise PermissionError("refresh job access denied")
    return job


def update_data_refresh_job(
    db: Session,
    job: DataRefreshJob,
    *,
    status: str | None = None,
    collections: list[Any] | None = None,
    snapshot_dir: str | None = None,
    workbook_path: str | None = None,
    new_report_run_id: str | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> DataRefreshJob:
    if status is not None:
        job.status = status[:80]
    if collections is not None:
        job.collections = collections
    if snapshot_dir is not None:
        job.snapshot_dir = snapshot_dir[:1000]
    if workbook_path is not None:
        job.workbook_path = workbook_path[:1000]
    if new_report_run_id is not None:
        job.new_report_run_id = new_report_run_id
    if error_message is not None:
        job.error_message = error_message[:2000]
    if started_at is not None:
        job.started_at = started_at
    if finished_at is not None:
        job.finished_at = finished_at
    job.updated_at = security.utcnow()
    db.flush()
    return job


def data_refresh_job_payload(job: DataRefreshJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "tenantId": job.tenant_id,
        "sourceReportRunId": job.source_report_run_id,
        "newReportRunId": job.new_report_run_id,
        "requestedByUserId": job.requested_by_user_id,
        "threadId": job.thread_id,
        "status": job.status,
        "reason": job.reason,
        "collections": job.collections or [],
        "snapshotDir": job.snapshot_dir,
        "workbookPath": job.workbook_path,
        "errorMessage": job.error_message,
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "finishedAt": job.finished_at.isoformat() if job.finished_at else None,
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat(),
    }


def active_source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
    mode: str | None = None,
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(
        SourceRefreshRun.tenant_id == tenant_id,
        SourceRefreshRun.status.in_(ACTIVE_SOURCE_REFRESH_STATUSES),
        SourceRefreshRun.finished_at.is_(None),
    )
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    if mode:
        statement = statement.where(SourceRefreshRun.mode == mode)
    else:
        statement = statement.where(SourceRefreshRun.mode != "report-generation")
    return db.scalar(statement.order_by(SourceRefreshRun.created_at.desc()))


def active_conflicting_source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    mode: str,
    client_id: str | None = None,
) -> SourceRefreshRun | None:
    modes = (
        DAILY_FACT_MUTATING_SOURCE_REFRESH_MODES
        if mode in DAILY_FACT_MUTATING_SOURCE_REFRESH_MODES
        else {mode}
    )
    statement = select(SourceRefreshRun)
    statement = statement.where(
        SourceRefreshRun.tenant_id == tenant_id,
        SourceRefreshRun.mode.in_(modes),
        SourceRefreshRun.status.in_(ACTIVE_SOURCE_REFRESH_STATUSES),
        SourceRefreshRun.finished_at.is_(None),
    )
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    return db.scalar(statement.order_by(SourceRefreshRun.created_at.desc()))


def latest_source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
    mode: str | None = None,
    include_dry_run: bool = True,
    exclude_statuses: Iterable[str] = (),
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(SourceRefreshRun.tenant_id == tenant_id)
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    if mode:
        statement = statement.where(SourceRefreshRun.mode == mode)
    else:
        statement = statement.where(SourceRefreshRun.mode != "report-generation")
    if not include_dry_run:
        statement = statement.where(SourceRefreshRun.dry_run.is_(False))
    excluded = tuple(exclude_statuses)
    if excluded:
        statement = statement.where(SourceRefreshRun.status.not_in(excluded))
    return db.scalar(statement.order_by(SourceRefreshRun.created_at.desc()))


def latest_calculable_ozon_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(
        SourceRefreshRun.tenant_id == tenant_id,
        SourceRefreshRun.mode == "ozon-only",
        SourceRefreshRun.dry_run.is_(False),
        SourceRefreshRun.finished_at.is_not(None),
        SourceRefreshRun.status.in_(CALCULABLE_OZON_REFRESH_STATUSES),
    )
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    return db.scalar(statement.order_by(SourceRefreshRun.created_at.desc()))


def require_source_refresh_run(
    db: Session,
    *,
    user: User,
    report: ReportRun,
    refresh_run_id: str,
) -> SourceRefreshRun:
    require_report(db, user, report.id)
    refresh_run = db.get(SourceRefreshRun, refresh_run_id)
    if refresh_run is None or refresh_run.tenant_id != report.tenant_id:
        raise PermissionError("source refresh access denied")
    return refresh_run


def create_source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    mode: str,
    credential_source: str,
    dry_run: bool,
    snapshot_set_id: str,
    period_start: date,
    period_end: date,
    source_window_start: date | None = None,
    source_window_end: date | None = None,
    client_id: str | None = None,
    user: User | None = None,
    source_report: ReportRun | None = None,
    resumed_from_run: SourceRefreshRun | None = None,
    base_source_refresh_run: SourceRefreshRun | None = None,
    blocked_by_run: SourceRefreshRun | None = None,
    reason: str = "",
    enforce_active_check: bool = True,
) -> SourceRefreshRun:
    if user is not None:
        require_staff(user, tenant_id)
    resolved_client_id = client_id or (
        source_report.client_id if source_report else client_id_for_tenant(tenant_id)
    )
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"source-refresh:{tenant_id}:{resolved_client_id}"},
        )
    existing = (
        active_conflicting_source_refresh_run(
            db,
            tenant_id=tenant_id,
            mode=mode,
            client_id=resolved_client_id,
        )
        if enforce_active_check
        else None
    )
    if existing is not None:
        raise ValueError("source refresh already active for this tenant")
    now = security.utcnow()
    refresh_run = SourceRefreshRun(
        id=new_id("source_refresh"),
        tenant_id=tenant_id,
        client_id=resolved_client_id,
        requested_by_user_id=user.id if user else None,
        source_report_run_id=source_report.id if source_report else None,
        new_report_run_id=None,
        resumed_from_run_id=resumed_from_run.id if resumed_from_run else None,
        base_source_refresh_run_id=(
            base_source_refresh_run.id if base_source_refresh_run else None
        ),
        blocked_by_run_id=blocked_by_run.id if blocked_by_run else None,
        worker_id="",
        failure_code="",
        heartbeat_at=None,
        mode=mode,
        credential_source=credential_source,
        dry_run=dry_run,
        status="queued",
        reason=reason.strip()[:4000],
        snapshot_set_id=snapshot_set_id,
        period_start=period_start,
        period_end=period_end,
        source_window_start=source_window_start or period_start,
        source_window_end=source_window_end or period_end,
        root_dir="",
        workbook_path="",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    db.add(refresh_run)
    db.flush()
    audit(
        db,
        action="source_refresh_requested",
        user=user,
        tenant_id=tenant_id,
        entity_type="source_refresh_run",
        entity_id=refresh_run.id,
        payload={
            "mode": mode,
            "credentialSource": credential_source,
            "dryRun": dry_run,
            "snapshotSetId": snapshot_set_id,
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "sourceWindowStart": (source_window_start or period_start).isoformat(),
            "sourceWindowEnd": (source_window_end or period_end).isoformat(),
            "resumedFromRunId": resumed_from_run.id if resumed_from_run else None,
            "baseSourceRefreshRunId": (
                base_source_refresh_run.id if base_source_refresh_run else None
            ),
            "blockedByRunId": blocked_by_run.id if blocked_by_run else None,
        },
    )
    return refresh_run


def update_source_refresh_run(
    db: Session,
    refresh_run: SourceRefreshRun,
    *,
    status: str | None = None,
    root_dir: str | None = None,
    workbook_path: str | None = None,
    new_report_run_id: str | None = None,
    error_message: str | None = None,
    worker_id: str | None = None,
    failure_code: str | None = None,
    heartbeat_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> SourceRefreshRun:
    if status is not None:
        refresh_run.status = status[:80]
    if root_dir is not None:
        refresh_run.root_dir = root_dir[:1000]
    if workbook_path is not None:
        refresh_run.workbook_path = workbook_path[:1000]
    if new_report_run_id is not None:
        refresh_run.new_report_run_id = new_report_run_id
    if error_message is not None:
        refresh_run.error_message = error_message[:2000]
    if worker_id is not None:
        refresh_run.worker_id = worker_id[:160]
    if failure_code is not None:
        refresh_run.failure_code = failure_code[:160]
    if heartbeat_at is not None:
        refresh_run.heartbeat_at = heartbeat_at
    if started_at is not None:
        refresh_run.started_at = started_at
    if finished_at is not None:
        refresh_run.finished_at = finished_at
    refresh_run.updated_at = security.utcnow()
    db.flush()
    return refresh_run


def ozon_draft_report_for_refresh(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> ReportRun | None:
    if refresh_run.new_report_run_id:
        report = db.get(ReportRun, refresh_run.new_report_run_id)
        if report is not None and report.lineage_type == OZON_DRAFT_LINEAGE_TYPE:
            return report
    return db.scalar(
        select(ReportRun)
        .where(
            ReportRun.tenant_id == refresh_run.tenant_id,
            ReportRun.client_id == refresh_run.client_id,
            ReportRun.lineage_type == OZON_DRAFT_LINEAGE_TYPE,
            ReportRun.source_snapshot_set_id == refresh_run.snapshot_set_id,
        )
        .order_by(ReportRun.created_at.desc())
    )


def materialize_ozon_draft_report(
    db: Session,
    refresh_run: SourceRefreshRun,
    *,
    user: User | None = None,
) -> ReportRun:
    if (
        refresh_run.mode != "ozon-only"
        or refresh_run.dry_run
        or refresh_run.finished_at is None
        or refresh_run.status not in CALCULABLE_OZON_REFRESH_STATUSES
    ):
        raise ValueError("Ozon draft requires a completed calculable ozon-only run")
    source_blocker = ozon_draft_source_blocker(db, refresh_run)
    if source_blocker:
        raise ValueError(source_blocker)
    existing = ozon_draft_report_for_refresh(db, refresh_run)
    if existing is not None:
        if refresh_run.new_report_run_id != existing.id:
            refresh_run.new_report_run_id = existing.id
            db.flush()
        return existing
    client = db.get(Client, refresh_run.client_id)
    if client is None or client.tenant_id != refresh_run.tenant_id:
        raise ValueError("source refresh client not found")
    diagnostics = latest_ozon_diagnostics_payload(
        db,
        tenant_id=refresh_run.tenant_id,
        client_id=refresh_run.client_id,
        limit=1,
        preview_max_rows=1,
        period_start=refresh_run.period_start,
        period_end=refresh_run.period_end,
        refresh_run_id=refresh_run.id,
    )
    if not diagnostics.get("latestRun"):
        raise ValueError("Ozon draft has no calculable source snapshot")
    now = security.utcnow()
    report = ReportRun(
        id=f"ozon_draft_{refresh_run.id.removeprefix('source_refresh_')}",
        tenant_id=refresh_run.tenant_id,
        client_id=refresh_run.client_id,
        client_name=client.name,
        title=f"Ozon + 1C · внутренний черновик · {client.name}",
        period_start=refresh_run.period_start,
        period_end=refresh_run.period_end,
        source_coverage_start=refresh_run.period_start,
        source_coverage_end=refresh_run.period_end,
        period_text=(
            f"{refresh_run.period_start:%d.%m.%Y} - {refresh_run.period_end:%d.%m.%Y}"
        ),
        period_status="draft",
        generated_at=now,
        status="ready" if diagnostics.get("status") == "ready" else "needs_review",
        publication_status="draft",
        is_current=False,
        lineage_type=OZON_DRAFT_LINEAGE_TYPE,
        source_snapshot_set_id=refresh_run.snapshot_set_id,
        methodology_version=OZON_DRAFT_METHODOLOGY_VERSION,
        source_workbook="",
        source_workbook_path="",
        return_reason_limitation="",
        created_at=now,
    )
    db.add(report)
    db.flush()
    replace_source_loads_from_refresh(db, report, refresh_run)
    final_refresh_status = (
        "report_created" if diagnostics.get("status") == "ready" else "needs_review"
    )
    update_source_refresh_run(
        db,
        refresh_run,
        status=final_refresh_status,
        new_report_run_id=report.id,
    )
    audit(
        db,
        action="ozon_draft_report_created",
        user=user,
        tenant_id=refresh_run.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "sourceRefreshRunId": refresh_run.id,
            "snapshotSetId": refresh_run.snapshot_set_id,
            "status": report.status,
        },
    )
    db.flush()
    return report


def ozon_draft_source_blocker(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> str:
    collections = list(
        db.scalars(
            select(SourceRefreshCollection).where(
                SourceRefreshCollection.refresh_run_id == refresh_run.id,
                SourceRefreshCollection.source_type == "onec_commissioner_reports",
            )
        )
    )
    for collection in collections:
        data_quality = (collection.payload or {}).get("dataQuality") or {}
        if data_quality.get("status") == "partial_source":
            return "Ozon draft requires complete 1C commissioner financial tables"
    return ""


def ozon_refresh_run_for_report(db: Session, report: ReportRun) -> SourceRefreshRun:
    if report.lineage_type != OZON_DRAFT_LINEAGE_TYPE:
        raise ValueError("report is not an Ozon draft")
    refresh_run = db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.tenant_id == report.tenant_id,
            SourceRefreshRun.client_id == report.client_id,
            or_(
                SourceRefreshRun.new_report_run_id == report.id,
                and_(
                    SourceRefreshRun.snapshot_set_id == report.source_snapshot_set_id,
                    SourceRefreshRun.mode == "ozon-only",
                ),
            ),
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )
    if refresh_run is None:
        raise LookupError("Ozon draft source refresh not found")
    return refresh_run


def ozon_draft_diagnostics_payload(
    db: Session,
    report: ReportRun,
    *,
    limit: int = 50,
    preview_max_rows: int = OZON_DIAGNOSTIC_PREVIEW_MAX_ROWS,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    refresh_run = ozon_refresh_run_for_report(db, report)
    return latest_ozon_diagnostics_payload(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        limit=limit,
        preview_max_rows=preview_max_rows,
        period_start=period_start or report.period_start,
        period_end=period_end or report.period_end,
        wb_cabinet_id=wb_cabinet_id,
        refresh_run_id=refresh_run.id,
    )


def add_source_refresh_collection(
    db: Session,
    refresh_run: SourceRefreshRun,
    *,
    source_type: str,
    source_label: str,
    required: bool,
    publication_required: bool = False,
    status: str,
    snapshot_hash: str = "",
    row_count: int = 0,
    raw_path: str = "",
    error_message: str = "",
    payload: dict[str, Any] | None = None,
    client_id: str | None = None,
    wb_cabinet_id: str = "",
    organization_id: str | None = None,
    loaded_at: datetime | None = None,
) -> SourceRefreshCollection:
    item = SourceRefreshCollection(
        refresh_run=refresh_run,
        tenant_id=refresh_run.tenant_id,
        client_id=(
            client_id
            or refresh_run.client_id
            or client_id_for_tenant(refresh_run.tenant_id)
        ),
        wb_cabinet_id=wb_cabinet_id,
        organization_id=organization_id,
        source_type=source_type[:120],
        source_label=source_label[:300],
        required=required,
        publication_required=publication_required,
        status=status[:80],
        snapshot_hash=snapshot_hash[:160],
        row_count=max(0, int(row_count)),
        raw_path=raw_path[:1000],
        error_message=error_message[:2000],
        payload=payload or {},
        loaded_at=loaded_at or security.utcnow(),
    )
    db.add(item)
    db.flush()
    return item


def sync_organization_tax_profiles(
    db: Session,
    refresh_run: SourceRefreshRun,
    *,
    user: User | None = None,
) -> SourceRefreshCollection:
    organization_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_organizations",
            )
        )
    )
    notice_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type
                == "onec_tax_special_regime_notifications",
            )
        )
    )
    tax_system_setting_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_tax_system_settings",
            )
        )
    )
    vat_setting_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_vat_settings",
            )
        )
    )
    tax_kind_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_tax_kinds",
            )
        )
    )
    tax_accrual_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_tax_accruals",
            )
        )
    )
    tax_accrual_line_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_tax_accrual_lines",
            )
        )
    )
    vat_sales_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_vat_sales_book",
            )
        )
    )
    notice_collection = db.scalar(
        select(SourceRefreshCollection).where(
            SourceRefreshCollection.refresh_run_id == refresh_run.id,
            SourceRefreshCollection.source_type
            == "onec_tax_special_regime_notifications",
        )
    )
    special_tax_source_complete = bool(
        notice_collection and notice_collection.status in {"loaded", "empty_expected"}
    )
    organizations = {
        _safe_payload_text(row.row_payload or {}, "Ref_Key"): row
        for row in organization_rows
        if _safe_payload_text(row.row_payload or {}, "Ref_Key")
    }
    all_companies = list(
        db.scalars(
            select(ClientCompany)
            .where(
                ClientCompany.client_id == refresh_run.client_id,
                ClientCompany.status == "active",
            )
            .order_by(ClientCompany.id)
        )
    )
    active_company_ids = {
        company_id
        for company_id in db.scalars(
            select(WbCabinet.client_company_id).where(
                WbCabinet.client_id == refresh_run.client_id,
                WbCabinet.status == "active",
                WbCabinet.client_company_id != "",
            )
        )
        if company_id
    }
    companies = (
        [company for company in all_companies if company.id in active_company_ids]
        if active_company_ids
        else all_companies
    )
    linked_count = 0
    auto_linked_count = 0
    organization_name_index: dict[str, list[str]] = defaultdict(list)
    for organization_id, row in organizations.items():
        payload = row.row_payload or {}
        for value in (
            _safe_payload_text(payload, "Description"),
            _safe_payload_text(payload, "НаименованиеПолное"),
            _safe_payload_text(payload, "НаименованиеСокращенное"),
        ):
            key = _organization_match_key(value)
            if key and organization_id not in organization_name_index[key]:
                organization_name_index[key].append(organization_id)

    def link_company(
        company: ClientCompany,
        organization_id: str,
        *,
        method: str,
    ) -> ClientCompany:
        existing = db.scalar(
            select(ClientCompany)
            .where(
                ClientCompany.client_id == company.client_id,
                ClientCompany.id != company.id,
                ClientCompany.onec_organization_id == organization_id,
                ClientCompany.status == "active",
            )
            .order_by(ClientCompany.id)
        )
        if existing is not None:
            merge_client_company_into(db, duplicate=company, canonical=existing)
            linked_company = existing
            audit_method = f"{method}_merged_alias"
        else:
            company.onec_organization_id = organization_id
            company.updated_at = security.utcnow()
            linked_company = company
            audit_method = method
        ensure_client_company_alias(
            db,
            company=linked_company,
            display_name=linked_company.display_name,
            source="1c_organization",
        )
        organization_row = organizations.get(organization_id)
        organization_payload = (
            organization_row.row_payload or {} if organization_row is not None else {}
        )
        for field in ("Description", "НаименованиеПолное", "НаименованиеСокращенное"):
            label = _safe_payload_text(organization_payload, field)
            if label:
                ensure_client_company_alias(
                    db,
                    company=linked_company,
                    display_name=label,
                    source="1c_organization",
                )
        audit(
            db,
            action="client_company_onec_organization_auto_linked",
            user=user,
            tenant_id=refresh_run.tenant_id,
            entity_type="client_company",
            entity_id=linked_company.id,
            payload={
                "organizationId": organization_id,
                "refreshRunId": refresh_run.id,
                "method": audit_method,
            },
        )
        return linked_company

    for company in companies:
        if company.onec_organization_id in organizations:
            linked_count += 1
            continue
        if company.source_key in organizations:
            link_company(company, company.source_key, method="saved_ref_key")
            linked_count += 1
            auto_linked_count += 1
            continue
        candidates = organization_name_index.get(
            _organization_match_key(company.display_name), []
        )
        if len(candidates) != 1:
            continue
        organization_id = candidates[0]
        link_method = "unique_exact_normalized_name"
        link_company(company, organization_id, method=link_method)
        linked_count += 1
        auto_linked_count += 1
    all_companies = list(
        db.scalars(
            select(ClientCompany)
            .where(
                ClientCompany.client_id == refresh_run.client_id,
                ClientCompany.status == "active",
            )
            .order_by(ClientCompany.id)
        )
    )
    active_company_ids = {
        company_id
        for company_id in db.scalars(
            select(WbCabinet.client_company_id).where(
                WbCabinet.client_id == refresh_run.client_id,
                WbCabinet.status == "active",
                WbCabinet.client_company_id != "",
            )
        )
        if company_id
    }
    companies = (
        [company for company in all_companies if company.id in active_company_ids]
        if active_company_ids
        else all_companies
    )
    _auto_link_single_ozon_cabinet(
        db,
        refresh_run=refresh_run,
        companies=companies,
        user=user,
    )
    notice_payloads = [row.row_payload or {} for row in notice_rows]
    tax_system_setting_payloads = [
        row.row_payload or {} for row in tax_system_setting_rows
    ]
    vat_setting_payloads = [row.row_payload or {} for row in vat_setting_rows]
    tax_kind_payloads = [row.row_payload or {} for row in tax_kind_rows]
    tax_accrual_payloads = [row.row_payload or {} for row in tax_accrual_rows]
    tax_accrual_line_payloads = [row.row_payload or {} for row in tax_accrual_line_rows]
    vat_sales_payloads = [row.row_payload or {} for row in vat_sales_rows]
    shared_tax_evidence_hashes = [
        row.raw_payload_hash
        for row in (
            *tax_kind_rows,
            *tax_accrual_rows,
            *tax_accrual_line_rows,
            *vat_sales_rows,
            *tax_system_setting_rows,
            *vat_setting_rows,
        )
    ]
    source_profile_count = 0
    company_diagnostics: list[dict[str, Any]] = []
    for company in companies:
        organization_id = company.onec_organization_id
        organization_row = organizations.get(organization_id)
        rate_anchor, rate_anchor_status = _company_tax_rate_anchor_for_date(
            db,
            company=company,
            calculation_date=refresh_run.period_end,
        )
        diagnostic = tax_profile_source_diagnostic(
            organization_id,
            organization=(organization_row.row_payload or {})
            if organization_row is not None
            else None,
            tax_system_setting_rows=tax_system_setting_payloads,
            vat_setting_rows=vat_setting_payloads,
            special_tax_mode_rows=notice_payloads,
            tax_kind_rows=tax_kind_payloads,
            tax_accrual_rows=tax_accrual_payloads,
            tax_accrual_line_rows=tax_accrual_line_payloads,
            vat_sales_rows=vat_sales_payloads,
            rate_anchor=rate_anchor,
            calculation_date=refresh_run.period_end,
            special_tax_source_complete=special_tax_source_complete,
        )
        company_diagnostics.append(
            {
                "clientCompanyId": company.id,
                "companyLabel": company.display_name,
                "organizationId": organization_id,
                "rateAnchorStatus": rate_anchor_status.get("status"),
                **diagnostic,
            }
        )
        if organization_row is None:
            continue
        mapping = AccountOrgMapping(
            client_id=refresh_run.client_id,
            seller_account_id=company.id,
            organization_id=organization_id,
            seller_account_name=company.display_name,
            organization_name=company.display_name,
        )
        profile_dates = {refresh_run.period_start, refresh_run.period_end}
        for payload in (*tax_system_setting_payloads, *vat_setting_payloads):
            if _safe_payload_text(payload, "Организация_Key") != organization_id:
                continue
            setting_date = _payload_date_or_none(
                _safe_payload_text(payload, "Period")
            )
            if (
                setting_date is not None
                and refresh_run.period_start <= setting_date <= refresh_run.period_end
            ):
                profile_dates.add(setting_date)
        profiles_by_signature: dict[tuple[Any, ...], TaxProfile] = {}
        for profile_date in sorted(profile_dates):
            resolved_profiles = tax_profiles_from_account_org_mapping(
                refresh_run.client_id,
                [mapping],
                onec_organization_rows=[organization_row.row_payload or {}],
                tax_system_setting_rows=tax_system_setting_payloads,
                vat_setting_rows=vat_setting_payloads,
                special_tax_mode_rows=notice_payloads,
                tax_kind_rows=tax_kind_payloads,
                tax_accrual_rows=tax_accrual_payloads,
                tax_accrual_line_rows=tax_accrual_line_payloads,
                vat_sales_rows=vat_sales_payloads,
                rate_anchors=[rate_anchor] if rate_anchor is not None else [],
                calculation_date=profile_date,
                special_tax_source_complete=special_tax_source_complete,
            )
            if resolved_profiles:
                resolved_profile = resolved_profiles[0]
                profiles_by_signature.setdefault(
                    _tax_profile_signature(resolved_profile),
                    resolved_profile,
                )
        profiles = sorted(
            profiles_by_signature.values(),
            key=lambda item: (item.valid_from or date.min, item.source),
        )
        for index, profile in enumerate(profiles[:-1]):
            next_valid_from = profiles[index + 1].valid_from
            if next_valid_from is not None and (
                profile.valid_to is None or profile.valid_to >= next_valid_from
            ) and (
                profile.valid_from is None or next_valid_from > profile.valid_from
            ):
                profiles[index] = profile.model_copy(
                    update={"valid_to": next_valid_from - timedelta(days=1)}
                )
        if not profiles:
            continue
        source_hashes = [organization_row.raw_payload_hash]
        source_hashes.extend(shared_tax_evidence_hashes)
        if rate_anchor is not None:
            source_hashes.append(
                hashlib.sha256(
                    repr(_tax_profile_signature(rate_anchor)).encode("utf-8")
                ).hexdigest()
            )
        source_hashes.extend(
            row.raw_payload_hash
            for row in notice_rows
            if _safe_payload_text(row.row_payload or {}, "Организация_Key")
            == organization_id
        )
        source_snapshot_hash = hashlib.sha256(
            "|".join(sorted(source_hashes)).encode("utf-8")
        ).hexdigest()
        for profile in profiles:
            profile_id = _stable_entity_id(
                "tax_profile",
                refresh_run.id,
                organization_id,
                profile.valid_from.isoformat() if profile.valid_from else "",
                profile.source,
            )
            if db.get(OrganizationTaxProfile, profile_id) is None:
                db.add(
                    OrganizationTaxProfile(
                        id=profile_id,
                        tenant_id=refresh_run.tenant_id,
                        client_id=refresh_run.client_id,
                        client_company_id=company.id,
                        organization_id=organization_id,
                        tax_system=profile.tax_system,
                        tax_object=profile.tax_object,
                        tax_rate=profile.tax_rate,
                        elevated_tax_rate=profile.elevated_tax_rate,
                        vat_rate=profile.vat_rate,
                        vat_mode=profile.vat_mode.value,
                        vat_deduction_mode=profile.vat_deduction_mode.value,
                        revenue_tax_rate=profile.revenue_tax_rate,
                        income_tax_kind=profile.income_tax_kind,
                        valid_from=profile.valid_from,
                        valid_to=profile.valid_to,
                        source=profile.source,
                        rate_basis_kind=profile.rate_basis_kind,
                        basis_document=profile.basis_document,
                        confirmed_by=profile.confirmed_by,
                        source_object_ids=json.dumps(
                            profile.source_object_ids,
                            ensure_ascii=False,
                        ),
                        source_refresh_run_id=refresh_run.id,
                        source_snapshot_hash=source_snapshot_hash,
                        methodology_version="marketplace-tax-profile-v4",
                        status="active",
                        created_at=security.utcnow(),
                    )
                )
            source_profile_count += 1
    db.flush()
    effective_profiles, resolution = _source_refresh_tax_profile_resolution(
        db,
        refresh_run,
        companies=companies,
    )
    profile_count = int(resolution["profileCount"])
    missing_count = int(resolution["missingProfileCount"])
    unconfirmed_count = int(resolution["unconfirmedProfileCount"])
    configured_company_count = sum(
        1 for item in company_diagnostics if item.get("derivedProfile") is not None
    )
    status = (
        "loaded"
        if companies and not missing_count and not unconfirmed_count
        else "needs_review"
    )
    diagnostic_message = (
        "Налоговые реквизиты всех организаций получены из 1С."
        if company_diagnostics
        and all(item["status"] == "ready" for item in company_diagnostics)
        else (
            "Настройки налогообложения организаций получены из 1С, но для части "
            "профилей расчёт по текущей методике не подтверждён."
            if configured_company_count == len(companies) and companies
            else (
                "Для части организаций периодические настройки налогообложения "
                "не найдены в публикации OData."
            )
        )
    )
    profile_fingerprint = "\n".join(
        repr(_tax_profile_signature(profile))
        for profile in sorted(
            effective_profiles,
            key=lambda item: (
                item.organization_id,
                item.valid_from or date.min,
                item.valid_to or date.max,
                item.source,
            ),
        )
    )
    digest = hashlib.sha256(
        (
            f"{profile_fingerprint}\n{source_profile_count}:{profile_count}:"
            f"{missing_count}:{unconfirmed_count}:{linked_count}:"
            f"{resolution['manualOverrideCount']}"
        ).encode()
    ).hexdigest()
    return add_source_refresh_collection(
        db,
        refresh_run,
        source_type="onec_tax_profiles",
        source_label="Налоговые профили организаций 1C",
        required=False,
        status=status,
        snapshot_hash=digest,
        row_count=profile_count,
        payload={
            "methodologyVersion": "marketplace-tax-profile-v4",
            "companyCount": len(companies),
            "linkedCompanyCount": linked_count,
            "autoLinkedCompanyCount": auto_linked_count,
            "profileCount": profile_count,
            "sourceProfileCount": source_profile_count,
            "configuredCompanyCount": configured_company_count,
            "manualOverrideCount": resolution["manualOverrideCount"],
            "missingProfileCount": missing_count,
            "unconfirmedProfileCount": unconfirmed_count,
            "fallbackPolicy": (
                "periodic_1c_settings_then_explicit_or_accounting_then_override_then_missing"
            ),
            "specialTaxSourceComplete": special_tax_source_complete,
            "message": diagnostic_message,
            "companyDiagnostics": company_diagnostics,
        },
    )


def tax_profiles_for_source_refresh(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> list[TaxProfile]:
    """Return only profiles resolved for this refresh and its report period."""

    profiles, _resolution = _source_refresh_tax_profile_resolution(db, refresh_run)
    return profiles


def _source_refresh_tax_profile_resolution(
    db: Session,
    refresh_run: SourceRefreshRun,
    *,
    companies: list[ClientCompany] | None = None,
) -> tuple[list[TaxProfile], dict[str, int]]:
    active_companies = companies
    if active_companies is None:
        active_companies = list(
            db.scalars(
                select(ClientCompany)
                .where(
                    ClientCompany.client_id == refresh_run.client_id,
                    ClientCompany.status == "active",
                )
                .order_by(ClientCompany.id)
            )
        )
    profiles_by_signature: dict[tuple[Any, ...], TaxProfile] = {}
    ready_count = 0
    manual_override_count = 0
    missing_count = 0
    unconfirmed_count = 0
    for company in active_companies:
        profiles, _checks, ready = _company_tax_profiles_for_period(
            db,
            company=company,
            period_start=refresh_run.period_start,
            period_end=refresh_run.period_end,
            refresh_run=refresh_run,
        )
        if not ready:
            if profiles:
                unconfirmed_count += 1
            else:
                missing_count += 1
            continue
        ready_count += 1
        if any(profile.source == "manual_override" for profile in profiles):
            manual_override_count += 1
        for profile in profiles:
            profiles_by_signature.setdefault(_tax_profile_signature(profile), profile)
    profiles = sorted(
        profiles_by_signature.values(),
        key=lambda profile: (
            profile.organization_id,
            profile.valid_from or date.min,
            profile.valid_to or date.max,
            profile.source,
        ),
    )
    return profiles, {
        "profileCount": ready_count,
        "manualOverrideCount": manual_override_count,
        "missingProfileCount": missing_count,
        "unconfirmedProfileCount": unconfirmed_count,
    }


def validate_source_snapshot_duplicates(
    db: Session,
    refresh_run: SourceRefreshRun,
) -> SourceRefreshCollection:
    position_duplicates = db.execute(
        select(
            SourceSnapshotRow.collection_id,
            SourceSnapshotRow.row_number,
            func.count(SourceSnapshotRow.id).label("count"),
        )
        .where(SourceSnapshotRow.refresh_run_id == refresh_run.id)
        .group_by(SourceSnapshotRow.collection_id, SourceSnapshotRow.row_number)
        .having(func.count(SourceSnapshotRow.id) > 1)
        .limit(100)
    ).all()
    payload_duplicates = db.execute(
        select(
            SourceSnapshotRow.source_type,
            SourceSnapshotRow.wb_cabinet_id,
            SourceSnapshotRow.raw_payload_hash,
            func.count(SourceSnapshotRow.id).label("count"),
        )
        .where(
            SourceSnapshotRow.refresh_run_id == refresh_run.id,
            SourceSnapshotRow.raw_payload_hash != "",
        )
        .group_by(
            SourceSnapshotRow.source_type,
            SourceSnapshotRow.wb_cabinet_id,
            SourceSnapshotRow.raw_payload_hash,
        )
        .having(func.count(SourceSnapshotRow.id) > 1)
        .limit(100)
    ).all()
    extra_rows = sum(int(item.count) - 1 for item in payload_duplicates)
    position_extra_rows = sum(int(item.count) - 1 for item in position_duplicates)
    status = "needs_review" if extra_rows or position_extra_rows else "loaded"
    return add_source_refresh_collection(
        db,
        refresh_run,
        source_type="snapshot_duplicate_control",
        source_label="Контроль дублей снимка",
        required=False,
        status=status,
        row_count=extra_rows + position_extra_rows,
        payload={
            "positionDuplicateGroups": len(position_duplicates),
            "positionExtraRows": position_extra_rows,
            "payloadDuplicateGroups": len(payload_duplicates),
            "payloadExtraRows": extra_rows,
            "scope": "single_refresh_run",
            "blocksProfit": bool(extra_rows or position_extra_rows),
        },
    )


def _auto_link_single_ozon_cabinet(
    db: Session,
    *,
    refresh_run: SourceRefreshRun,
    companies: list[ClientCompany],
    user: User | None,
) -> None:
    if len(companies) != 1:
        return
    cabinets = list(
        db.scalars(
            select(WbCabinet).where(
                WbCabinet.client_id == refresh_run.client_id,
                WbCabinet.status == "active",
                WbCabinet.provider.ilike("ozon%"),
            )
        )
    )
    if len(cabinets) != 1 or cabinets[0].client_company_id:
        return
    cabinet = cabinets[0]
    cabinet.client_company_id = companies[0].id
    cabinet.updated_at = security.utcnow()
    audit(
        db,
        action="ozon_cabinet_company_auto_linked",
        user=user,
        tenant_id=refresh_run.tenant_id,
        entity_type="wb_cabinet",
        entity_id=cabinet.id,
        payload={
            "clientCompanyId": companies[0].id,
            "refreshRunId": refresh_run.id,
            "method": "single_company_single_ozon_cabinet",
        },
    )


def _organization_match_key(value: str) -> str:
    return " ".join(value.casefold().split())


def add_source_snapshot_row(
    db: Session,
    collection: SourceRefreshCollection,
    *,
    row_number: int,
    raw_payload_hash: str,
    row_payload: dict[str, Any],
    source_row_id: str = "",
    client_id: str | None = None,
    wb_cabinet_id: str = "",
    loaded_at: datetime | None = None,
) -> SourceSnapshotRow:
    existing = db.scalar(
        select(SourceSnapshotRow).where(
            SourceSnapshotRow.refresh_run_id == collection.refresh_run_id,
            SourceSnapshotRow.collection_id == collection.id,
            SourceSnapshotRow.row_number == row_number,
        )
    )
    if existing is not None:
        collection.status = "needs_review"
        collection.error_message = (
            "duplicate_source_row_position_same_payload"
            if existing.raw_payload_hash == raw_payload_hash
            else "duplicate_source_row_position"
        )
        raise ValueError("duplicate source row position")
    item = SourceSnapshotRow(
        refresh_run_id=collection.refresh_run_id,
        collection_id=collection.id,
        tenant_id=collection.tenant_id,
        client_id=client_id or collection.client_id,
        wb_cabinet_id=wb_cabinet_id or collection.wb_cabinet_id,
        source_type=collection.source_type,
        source_label=collection.source_label,
        source_row_id=source_row_id[:240],
        row_number=row_number,
        raw_payload_hash=raw_payload_hash[:160],
        row_payload=row_payload,
        loaded_at=loaded_at or security.utcnow(),
    )
    db.add(item)
    db.flush()
    return item


def add_source_snapshot_rows(
    db: Session,
    collection: SourceRefreshCollection,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    positions = [int(row["row_number"]) for row in rows]
    if len(set(positions)) != len(positions):
        collection.status = "needs_review"
        collection.error_message = "duplicate_source_row_position_in_batch"
        raise ValueError("duplicate source row position in batch")
    existing_positions = set(
        db.scalars(
            select(SourceSnapshotRow.row_number).where(
                SourceSnapshotRow.refresh_run_id == collection.refresh_run_id,
                SourceSnapshotRow.collection_id == collection.id,
                SourceSnapshotRow.row_number.in_(positions),
            )
        )
    )
    if existing_positions:
        collection.status = "needs_review"
        collection.error_message = "duplicate_source_row_position_existing"
        raise ValueError("duplicate source row position already exists")
    loaded_at = collection.loaded_at or security.utcnow()
    values = [
        {
            "refresh_run_id": collection.refresh_run_id,
            "collection_id": collection.id,
            "tenant_id": collection.tenant_id,
            "client_id": str(row.get("client_id") or collection.client_id),
            "wb_cabinet_id": str(row.get("wb_cabinet_id") or collection.wb_cabinet_id),
            "source_type": collection.source_type,
            "source_label": collection.source_label,
            "source_row_id": str(row.get("source_row_id", ""))[:240],
            "row_number": int(row["row_number"]),
            "raw_payload_hash": str(row["raw_payload_hash"])[:160],
            "row_payload": row["row_payload"],
            "loaded_at": row.get("loaded_at") or loaded_at,
        }
        for row in rows
    ]
    dialect_name = db.get_bind().dialect.name
    table = SourceSnapshotRow.__table__
    if dialect_name == "postgresql":
        statement = (
            postgresql_insert(table)
            .values(values)
            .on_conflict_do_nothing()
            .returning(table.c.id)
        )
        inserted_count = len(db.execute(statement).scalars().all())
    elif dialect_name == "sqlite":
        statement = (
            sqlite_insert(table)
            .values(values)
            .on_conflict_do_nothing()
            .returning(table.c.id)
        )
        inserted_count = len(db.execute(statement).scalars().all())
    else:
        result = db.execute(insert(table), values)
        inserted_count = int(result.rowcount or 0)
    db.flush()
    if inserted_count != len(values):
        collection.status = "needs_review"
        collection.error_message = "duplicate_source_row_conflict"
        raise ValueError("one or more source rows conflict with existing rows")
    return inserted_count


def replace_marketplace_finance_daily_facts(
    db: Session,
    refresh_run: SourceRefreshRun,
    facts: list[MarketplaceFinanceDailyFactContract],
    *,
    marketplace: str,
    cabinet_ids: Mapping[str, str] | None = None,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
    report_keys: Iterable[tuple[str, str]] = (),
) -> int:
    marketplace = marketplace.strip().lower()
    if marketplace not in {"wb", "ozon"}:
        raise ValueError("unsupported marketplace daily facts provider")
    cabinet_ids = cabinet_ids or {}
    coverage_start = coverage_start or refresh_run.period_start
    coverage_end = coverage_end or refresh_run.period_end
    if coverage_start > coverage_end:
        raise ValueError("daily facts coverage start must not be after end")
    replacement_report_keys = sorted(
        {
            (str(seller_account_id).strip(), str(report_id).strip())
            for seller_account_id, report_id in report_keys
            if str(seller_account_id).strip() and str(report_id).strip()
        }
    )
    loaded_at = security.utcnow()
    values: list[dict[str, Any]] = []
    for fact in facts:
        dimensions = {
            "clientId": fact.client_id,
            "sellerAccountId": fact.seller_account_id,
            "organizationId": fact.organization_id,
            "factDate": fact.fact_date.isoformat(),
            "marketplaceReportId": fact.marketplace_report_id,
            "documentKind": fact.document_kind,
            "nmId": fact.nm_id,
            "vendorCode": fact.vendor_code,
            "barcode": fact.barcode,
            "onecItemId": fact.onec_item_id,
            "salesModel": fact.sales_model,
            "operationGroup": fact.operation_group,
        }
        grain_hash = hashlib.sha256(
            json.dumps(
                dimensions,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        values.append(
            {
                "tenant_id": refresh_run.tenant_id,
                "client_id": refresh_run.client_id,
                "marketplace": marketplace,
                "wb_cabinet_id": str(cabinet_ids.get(fact.seller_account_id, "")),
                "seller_account_id": fact.seller_account_id,
                "organization_id": fact.organization_id,
                "fact_date": fact.fact_date,
                "marketplace_report_id": fact.marketplace_report_id,
                "document_kind": fact.document_kind,
                "nm_id": fact.nm_id,
                "vendor_code": fact.vendor_code,
                "barcode": fact.barcode,
                "onec_item_id": fact.onec_item_id,
                "sales_model": fact.sales_model,
                "operation_group": fact.operation_group,
                "sales_quantity": fact.sales_quantity,
                "return_quantity": fact.return_quantity,
                "quantity": fact.quantity,
                "return_amount": fact.return_amount,
                "spp_discount": fact.spp_discount,
                "net_revenue": fact.net_revenue,
                "wb_commission": fact.wb_commission,
                "logistics": fact.logistics,
                "storage": fact.storage,
                "acceptance": fact.acceptance,
                "marketplace_promotion": fact.marketplace_promotion,
                "penalties_and_holdbacks": fact.penalties_and_holdbacks,
                "acquiring": fact.acquiring,
                "cogs": fact.cogs,
                "gross_profit": fact.gross_profit,
                "vat_input_from_marketplace": fact.vat_input_from_marketplace,
                "vat_input_from_1c": fact.vat_input_from_1c,
                "accounting_service_input_vat": fact.accounting_service_input_vat,
                "source_row_count": fact.source_row_count,
                "source_hash_digest": fact.source_hash_digest,
                "grain_hash": grain_hash,
                "is_partial_source": fact.is_partial_source,
                "source_snapshot_set_id": refresh_run.snapshot_set_id,
                "source_refresh_run_id": refresh_run.id,
                "methodology_version": fact.methodology_version,
                "loaded_at": loaded_at,
            }
        )
    staged_values = _stage_marketplace_values(
        db,
        fact_kind="daily_finance",
        tenant_id=refresh_run.tenant_id,
        client_id=refresh_run.client_id,
        marketplace=marketplace,
        values=values,
        grain_field="grain_hash",
    )
    replacement_scope = [
        MarketplaceFinanceDailyFact.source_refresh_run_id == refresh_run.id,
        and_(
            MarketplaceFinanceDailyFact.fact_date >= coverage_start,
            MarketplaceFinanceDailyFact.fact_date <= coverage_end,
        ),
    ]
    if replacement_report_keys:
        replacement_scope.append(
            or_(
                *(
                    and_(
                        MarketplaceFinanceDailyFact.seller_account_id
                        == seller_account_id,
                        MarketplaceFinanceDailyFact.marketplace_report_id == report_id,
                    )
                    for seller_account_id, report_id in replacement_report_keys
                )
            )
        )
    db.execute(
        delete(MarketplaceFinanceDailyFact).where(
            MarketplaceFinanceDailyFact.tenant_id == refresh_run.tenant_id,
            MarketplaceFinanceDailyFact.client_id == refresh_run.client_id,
            MarketplaceFinanceDailyFact.marketplace == marketplace,
            or_(*replacement_scope),
        )
    )
    if staged_values:
        db.execute(insert(MarketplaceFinanceDailyFact), staged_values)
    db.flush()
    persisted_count = int(
        db.scalar(
            select(func.count())
            .select_from(MarketplaceFinanceDailyFact)
            .where(
                MarketplaceFinanceDailyFact.tenant_id == refresh_run.tenant_id,
                MarketplaceFinanceDailyFact.client_id == refresh_run.client_id,
                MarketplaceFinanceDailyFact.marketplace == marketplace,
                MarketplaceFinanceDailyFact.source_refresh_run_id == refresh_run.id,
            )
        )
        or 0
    )
    if persisted_count != len(staged_values):
        raise ValueError("persisted daily facts count differs from staging")
    return persisted_count


def source_snapshot_row_count_for_run(
    db: Session,
    *,
    refresh_run_id: str,
    source_type: str,
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(SourceSnapshotRow)
            .where(
                SourceSnapshotRow.refresh_run_id == refresh_run_id,
                SourceSnapshotRow.source_type == source_type,
            )
        )
        or 0
    )


def replace_marketplace_operation_facts(
    db: Session,
    collection: SourceRefreshCollection,
    rows: Iterable[dict[str, Any]],
    *,
    marketplace: str = "ozon",
) -> int:
    marketplace = marketplace.strip().lower()
    values: list[dict[str, Any]] = []
    for row in rows:
        values.append(
            {
                "tenant_id": collection.tenant_id,
                "client_id": collection.client_id,
                "marketplace": marketplace,
                "wb_cabinet_id": str(row.get("wb_cabinet_id") or ""),
                "seller_account_id": str(row.get("seller_account_id") or ""),
                "source_type": collection.source_type,
                "source_key": str(row["source_key"]),
                "source_row_id": str(row.get("source_row_id") or ""),
                "source_row_number": int(row.get("source_row_number") or 0),
                "operation_id": str(row.get("operation_id") or ""),
                "posting_number": str(row.get("posting_number") or ""),
                "product_id": str(row.get("product_id") or ""),
                "offer_id": str(row.get("offer_id") or ""),
                "sku": str(row.get("sku") or ""),
                "service_key": str(row.get("service_key") or ""),
                "service_name": str(row.get("service_name") or ""),
                "barcode": str(row.get("barcode") or ""),
                "product_name": str(row.get("product_name") or ""),
                "operation_type": str(row.get("operation_type") or ""),
                "operation_date": row.get("operation_date"),
                "quantity": row.get("quantity") or 0,
                "amount": row.get("amount") or 0,
                "price": row.get("price") or 0,
                "income": row.get("income") or 0,
                "expense": row.get("expense") or 0,
                "debit_amount": row.get("debit_amount") or 0,
                "credit_amount": row.get("credit_amount") or 0,
                "commission": row.get("commission") or 0,
                "service_amount": row.get("service_amount") or 0,
                "logistics": row.get("logistics") or 0,
                "storage": row.get("storage") or 0,
                "promotion": row.get("promotion") or 0,
                "compensation": row.get("compensation") or 0,
                "other_amount": row.get("other_amount") or 0,
                "expenses_loaded": bool(row.get("expenses_loaded")),
                "is_partial_source": bool(row.get("is_partial_source")),
                "currency": str(row.get("currency") or "RUB"),
                "source_endpoint": str(row.get("source_endpoint") or ""),
                "raw_payload_hash": str(row["raw_payload_hash"]),
                "source_snapshot_set_id": collection.refresh_run.snapshot_set_id,
                "source_refresh_run_id": collection.refresh_run_id,
                "loaded_at": collection.loaded_at or security.utcnow(),
            }
        )
    staged_values = _stage_marketplace_values(
        db,
        fact_kind="operation",
        tenant_id=collection.tenant_id,
        client_id=collection.client_id,
        marketplace=marketplace,
        values=values,
        grain_field="source_key",
    )
    db.execute(
        delete(MarketplaceOperationFact).where(
            MarketplaceOperationFact.tenant_id == collection.tenant_id,
            MarketplaceOperationFact.client_id == collection.client_id,
            MarketplaceOperationFact.marketplace == marketplace,
            MarketplaceOperationFact.source_type == collection.source_type,
        )
    )
    if staged_values:
        db.execute(insert(MarketplaceOperationFact), staged_values)
    db.flush()
    persisted_count = int(
        db.scalar(
            select(func.count())
            .select_from(MarketplaceOperationFact)
            .where(
                MarketplaceOperationFact.tenant_id == collection.tenant_id,
                MarketplaceOperationFact.client_id == collection.client_id,
                MarketplaceOperationFact.marketplace == marketplace,
                MarketplaceOperationFact.source_type == collection.source_type,
                MarketplaceOperationFact.source_refresh_run_id
                == collection.refresh_run_id,
            )
        )
        or 0
    )
    if persisted_count != len(staged_values):
        raise ValueError("persisted operation facts count differs from staging")
    return persisted_count


def marketplace_operation_facts_parity(
    db: Session,
    collection: SourceRefreshCollection,
    expected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    persisted = list(
        db.scalars(
            select(MarketplaceOperationFact).where(
                MarketplaceOperationFact.tenant_id == collection.tenant_id,
                MarketplaceOperationFact.client_id == collection.client_id,
                MarketplaceOperationFact.marketplace == "ozon",
                MarketplaceOperationFact.source_type == collection.source_type,
                MarketplaceOperationFact.source_refresh_run_id
                == collection.refresh_run_id,
            )
        )
    )
    fields = (
        "wb_cabinet_id",
        "seller_account_id",
        "source_key",
        "source_row_id",
        "operation_id",
        "posting_number",
        "product_id",
        "offer_id",
        "sku",
        "service_key",
        "service_name",
        "barcode",
        "product_name",
        "operation_type",
        "operation_date",
        "quantity",
        "amount",
        "price",
        "income",
        "expense",
        "debit_amount",
        "credit_amount",
        "commission",
        "service_amount",
        "logistics",
        "storage",
        "promotion",
        "compensation",
        "other_amount",
        "expenses_loaded",
        "is_partial_source",
        "currency",
        "source_endpoint",
        "raw_payload_hash",
    )
    expected = [
        {
            field: (
                row.get(field)
                if field not in {"currency", "service_key"}
                else row.get(field) or ("RUB" if field == "currency" else "")
            )
            for field in fields
        }
        for row in expected_rows
    ]
    actual = [{field: getattr(row, field) for field in fields} for row in persisted]
    expected_encoded = sorted(
        (_staging_encode(row) for row in expected),
        key=lambda row: str(row.get("source_key") or ""),
    )
    actual_encoded = sorted(
        (_staging_encode(row) for row in actual),
        key=lambda row: str(row.get("source_key") or ""),
    )
    expected_digest = _staging_digest(expected_encoded)
    actual_digest = _staging_digest(actual_encoded)
    matched = (
        len(expected_encoded) == len(actual_encoded)
        and expected_digest == actual_digest
    )
    return {
        "status": "matched" if matched else "mismatch",
        "expectedRows": len(expected_encoded),
        "persistedRows": len(actual_encoded),
        "expectedDigest": expected_digest,
        "persistedDigest": actual_digest,
        "mismatches": [] if matched else ["operationFacts"],
    }


def _stage_marketplace_values(
    db: Session,
    *,
    fact_kind: str,
    tenant_id: str,
    client_id: str,
    marketplace: str,
    values: list[dict[str, Any]],
    grain_field: str,
) -> list[dict[str, Any]]:
    if not values:
        return []
    load_id = uuid.uuid4().hex
    created_at = security.utcnow()
    staging_rows = [
        {
            "load_id": load_id,
            "fact_kind": fact_kind,
            "tenant_id": tenant_id,
            "client_id": client_id,
            "marketplace": marketplace,
            "grain_hash": str(value[grain_field]),
            "payload": _staging_encode(value),
            "created_at": created_at,
        }
        for value in values
    ]
    expected_digest = _staging_digest(item["payload"] for item in staging_rows)
    db.execute(insert(MarketplaceFactStaging), staging_rows)
    del staging_rows
    staged_payloads = list(
        db.scalars(
            select(MarketplaceFactStaging.payload)
            .where(MarketplaceFactStaging.load_id == load_id)
            .order_by(MarketplaceFactStaging.id)
        )
    )
    if len(staged_payloads) != len(values):
        raise ValueError("marketplace staging row count mismatch")
    actual_digest = _staging_digest(staged_payloads)
    if expected_digest != actual_digest:
        raise ValueError("marketplace staging digest mismatch")
    _delete_marketplace_staging_load(db, load_id=load_id)
    return values


def _delete_marketplace_staging_load(db: Session, *, load_id: str) -> None:
    while True:
        staging_ids = list(
            db.scalars(
                select(MarketplaceFactStaging.id)
                .where(MarketplaceFactStaging.load_id == load_id)
                .order_by(MarketplaceFactStaging.id)
                .limit(MARKETPLACE_STAGING_DELETE_BATCH_SIZE)
            )
        )
        if not staging_ids:
            return
        db.execute(
            delete(MarketplaceFactStaging).where(
                MarketplaceFactStaging.id.in_(staging_ids)
            )
        )


def _staging_encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {
            "__type__": "decimal",
            "value": format(value.normalize(), "f"),
        }
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"__type__": "date", "value": value.isoformat()}
    if isinstance(value, dict):
        return {key: _staging_encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_staging_encode(item) for item in value]
    return value


def _staging_digest(values: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    for index, value in enumerate(values):
        if index:
            digest.update(b",")
        digest.update(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    digest.update(b"]")
    return digest.hexdigest()


def source_refresh_run_payload(
    refresh_run: SourceRefreshRun,
    *,
    include_sensitive: bool = True,
) -> dict[str, Any]:
    is_active = (
        refresh_run.status in ACTIVE_SOURCE_REFRESH_STATUSES
        and refresh_run.finished_at is None
    )
    heartbeat_at = refresh_run.heartbeat_at
    if heartbeat_at is not None and heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    is_stale = bool(
        is_active
        and heartbeat_at is not None
        and security.utcnow() - heartbeat_at > SOURCE_REFRESH_HEARTBEAT_STALE_AFTER
    )
    collections = [
        source_refresh_collection_payload(item, include_sensitive=include_sensitive)
        for item in sorted(
            refresh_run.collections,
            key=lambda value: (value.required is False, value.source_type, value.id),
        )
    ]
    mapping_collection = next(
        (item for item in refresh_run.collections if item.source_type == "sku_mapping"),
        None,
    )
    mapping_auto_sync = (
        dict((mapping_collection.payload or {}).get("rebuild") or {})
        if include_sensitive and mapping_collection is not None
        else None
    )
    return {
        "id": refresh_run.id,
        "tenantId": refresh_run.tenant_id,
        "clientId": refresh_run.client_id,
        "requestedByUserId": (
            refresh_run.requested_by_user_id if include_sensitive else None
        ),
        "sourceReportRunId": (
            refresh_run.source_report_run_id if include_sensitive else None
        ),
        "newReportRunId": refresh_run.new_report_run_id,
        "resumedFromRunId": refresh_run.resumed_from_run_id,
        "baseSourceRefreshRunId": (
            refresh_run.base_source_refresh_run_id if include_sensitive else None
        ),
        "blockedByRunId": refresh_run.blocked_by_run_id,
        "workerAssigned": bool(refresh_run.worker_id),
        "workerId": refresh_run.worker_id if include_sensitive else "",
        "failureCode": refresh_run.failure_code,
        "heartbeatAt": heartbeat_at.isoformat() if heartbeat_at else None,
        "isActive": is_active,
        "isStale": is_stale,
        "mode": refresh_run.mode,
        "credentialSource": refresh_run.credential_source if include_sensitive else "",
        "dryRun": refresh_run.dry_run,
        "status": refresh_run.status,
        "reason": refresh_run.reason if include_sensitive else "",
        "snapshotSetId": refresh_run.snapshot_set_id,
        "periodStart": refresh_run.period_start.isoformat(),
        "periodEnd": refresh_run.period_end.isoformat(),
        "sourceWindowStart": (
            refresh_run.source_window_start or refresh_run.period_start
        ).isoformat(),
        "sourceWindowEnd": (
            refresh_run.source_window_end or refresh_run.period_end
        ).isoformat(),
        "rootDir": refresh_run.root_dir if include_sensitive else "",
        "workbookPath": refresh_run.workbook_path if include_sensitive else "",
        "errorMessage": (
            refresh_run.error_message
            if include_sensitive
            else _safe_source_refresh_message(refresh_run)
        ),
        "safeMessage": _safe_source_refresh_message(refresh_run),
        "mappingAutoSync": mapping_auto_sync,
        "collections": collections,
        "startedAt": refresh_run.started_at.isoformat()
        if refresh_run.started_at
        else None,
        "finishedAt": refresh_run.finished_at.isoformat()
        if refresh_run.finished_at
        else None,
        "createdAt": refresh_run.created_at.isoformat(),
        "updatedAt": refresh_run.updated_at.isoformat(),
    }


def source_refresh_collection_payload(
    item: SourceRefreshCollection,
    *,
    include_sensitive: bool = True,
) -> dict[str, Any]:
    return {
        "id": item.id,
        "clientId": item.client_id,
        "wbCabinetId": item.wb_cabinet_id,
        "sourceType": item.source_type,
        "sourceLabel": item.source_label,
        "required": item.required,
        "publicationRequired": item.publication_required,
        "status": item.status,
        "snapshotHash": item.snapshot_hash if include_sensitive else "",
        "rowCount": item.row_count,
        "rawPath": item.raw_path if include_sensitive else "",
        "errorMessage": item.error_message if include_sensitive else "",
        "payload": item.payload or {} if include_sensitive else {},
        "loadedAt": item.loaded_at.isoformat(),
    }


def latest_source_refresh_payload(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
    include_sensitive: bool = False,
) -> dict[str, Any] | None:
    refresh_run = active_source_refresh_run(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
    )
    if refresh_run is None:
        refresh_run = latest_source_refresh_run(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            exclude_statuses={"blocked_active_refresh"},
        )
    if refresh_run is None:
        refresh_run = latest_source_refresh_run(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
        )
    if refresh_run is None:
        return None
    return source_refresh_run_payload(
        refresh_run,
        include_sensitive=include_sensitive,
    )


def source_refresh_status_payload(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
    mode: str | None = None,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    active_run = active_source_refresh_run(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        mode=mode,
    )
    latest_attempt = latest_source_refresh_run(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        mode=mode,
    )
    latest_completed = latest_source_refresh_run(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        mode=mode,
        exclude_statuses={"blocked_active_refresh"},
    )
    if latest_completed is not None and latest_completed.finished_at is None:
        completed_conditions = [
            SourceRefreshRun.tenant_id == tenant_id,
            SourceRefreshRun.finished_at.is_not(None),
            SourceRefreshRun.status != "blocked_active_refresh",
        ]
        if client_id:
            completed_conditions.append(SourceRefreshRun.client_id == client_id)
        if mode:
            completed_conditions.append(SourceRefreshRun.mode == mode)
        else:
            completed_conditions.append(SourceRefreshRun.mode != "report-generation")
        latest_completed = db.scalar(
            select(SourceRefreshRun)
            .where(*completed_conditions)
            .order_by(
                SourceRefreshRun.finished_at.desc(),
                SourceRefreshRun.created_at.desc(),
            )
        )
    primary = active_run or latest_completed or latest_attempt

    def payload(item: SourceRefreshRun | None) -> dict[str, Any] | None:
        return (
            source_refresh_run_payload(item, include_sensitive=include_sensitive)
            if item is not None
            else None
        )

    return {
        "latest": payload(primary),
        "activeRun": payload(active_run),
        "latestAttempt": payload(latest_attempt),
        "latestCompleted": payload(latest_completed),
    }


def _source_snapshot_rows_select(
    *,
    tenant_id: str,
    refresh_run: SourceRefreshRun,
    source_type: str,
    wb_cabinet_id: str = "",
):
    conditions = [
        SourceSnapshotRow.tenant_id == tenant_id,
        SourceSnapshotRow.refresh_run_id == refresh_run.id,
        SourceSnapshotRow.source_type == source_type,
    ]
    if wb_cabinet_id:
        conditions.append(SourceSnapshotRow.wb_cabinet_id == wb_cabinet_id)
    return select(SourceSnapshotRow).where(*conditions)


def _ozon_realization_source_rows(
    db: Session,
    *,
    tenant_id: str,
    refresh_run: SourceRefreshRun,
    wb_cabinet_id: str = "",
    limit: int | None,
    prefer_typed: bool = False,
) -> list[Any]:
    return _ozon_typed_source_rows(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=OZON_REALIZATION_SOURCE,
        wb_cabinet_id=wb_cabinet_id,
        limit=limit,
        prefer_typed=prefer_typed,
    )


def _ozon_typed_source_rows(
    db: Session,
    *,
    tenant_id: str,
    refresh_run: SourceRefreshRun,
    source_type: str,
    wb_cabinet_id: str = "",
    limit: int | None,
    prefer_typed: bool = False,
) -> list[Any]:
    raw_select = _source_snapshot_rows_select(
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=source_type,
        wb_cabinet_id=wb_cabinet_id,
    )
    if limit is not None:
        raw_select = raw_select.limit(limit)
    raw_rows = [] if prefer_typed else list(db.scalars(raw_select))
    if source_type == OZON_MUTUAL_SETTLEMENT_SOURCE and raw_rows:
        raw_rows = [
            row
            for row in raw_rows
            if _safe_payload_text(row.row_payload or {}, "source_endpoint")
            == "report_file"
        ]
    if raw_rows:
        return raw_rows
    conditions = [
        MarketplaceOperationFact.tenant_id == tenant_id,
        MarketplaceOperationFact.source_refresh_run_id == refresh_run.id,
        MarketplaceOperationFact.source_type == source_type,
    ]
    if wb_cabinet_id:
        conditions.append(MarketplaceOperationFact.wb_cabinet_id == wb_cabinet_id)
    typed_rows = list(
        db.scalars(
            select(MarketplaceOperationFact)
            .where(*conditions)
            .order_by(
                MarketplaceOperationFact.source_row_number,
                MarketplaceOperationFact.id,
            )
        )
    )
    if source_type == OZON_DIAGNOSTIC_FINANCE_SOURCE:
        rows = _typed_ozon_cash_flow_rows(typed_rows)
        return rows if limit is None else rows[:limit]
    if source_type != OZON_REALIZATION_SOURCE:
        rows = [_typed_ozon_namespace(item) for item in typed_rows]
        return rows if limit is None else rows[:limit]
    typed_rows.sort(
        key=lambda item: (
            _typed_ozon_source_position(item.source_row_id),
            item.product_id,
            item.offer_id,
            item.sku,
            item.service_key,
        )
    )
    grouped: dict[tuple[str, ...], list[MarketplaceOperationFact]] = defaultdict(list)
    for item in typed_rows:
        key = (
            item.seller_account_id,
            item.source_row_id,
            item.operation_id,
            item.posting_number,
            item.product_id,
            item.offer_id,
            item.sku,
        )
        grouped[key].append(item)
    result: list[Any] = []
    for row_number, items in enumerate(grouped.values(), 1):
        base = next((item for item in items if item.service_key == "product"), items[0])
        totals = {
            field: sum((Decimal(getattr(item, field)) for item in items), Decimal("0"))
            for field in (
                "commission",
                "service_amount",
                "logistics",
                "storage",
                "promotion",
                "compensation",
                "other_amount",
            )
        }
        result.append(
            _typed_ozon_namespace(
                base,
                expense_totals=totals,
                row_number=row_number,
            )
        )
    return result if limit is None else result[:limit]


def _typed_ozon_source_position(value: str) -> tuple[int, int]:
    match = re.match(r"^ozon_[^:]+:(\d+):(\d+)", str(value or ""))
    if not match:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def _typed_ozon_cash_flow_rows(
    rows: list[MarketplaceOperationFact],
) -> list[Any]:
    pages: dict[tuple[str, int], dict[str, Any]] = {}
    for item in rows:
        match = re.match(
            rf"{re.escape(OZON_DIAGNOSTIC_FINANCE_SOURCE)}:(\d+):",
            item.source_row_id,
        )
        page_index = int(match.group(1)) if match else 1
        page = pages.setdefault(
            (item.seller_account_id, page_index),
            {
                "loaded_at": item.loaded_at,
                "source_endpoint": item.source_endpoint,
                "cash_flows": {},
                "details": {},
            },
        )
        bounds = str(item.operation_id or "").split("|", 1)
        period_start = bounds[0] if bounds and bounds[0] else ""
        period_end = bounds[1] if len(bounds) > 1 else period_start
        period = {"begin": period_start, "end": period_end}
        if item.service_key == "cash_flow_summary":
            page["cash_flows"][item.operation_id] = {
                "period": period,
                "orders_amount": item.income,
                "returns_amount": item.expense,
                "commission_amount": item.commission,
                "services_amount": item.service_amount,
                "item_delivery_and_return_amount": item.logistics,
                "currency_code": item.currency,
            }
            page["details"].setdefault(item.operation_id, {"period": period})
            continue
        detail = page["details"].setdefault(item.operation_id, {"period": period})
        if item.service_key.startswith("cash_flow_category:"):
            category = item.service_key.split(":", 1)[1]
            detail.setdefault(category, {"total": item.amount, "items": []})[
                "total"
            ] = item.amount
            continue
        if item.service_key.startswith("cash_flow_item:"):
            parts = item.service_key.split(":", 2)
            if len(parts) < 3:
                continue
            category = parts[1]
            category_payload = detail.setdefault(
                category,
                {"total": Decimal("0"), "items": []},
            )
            category_payload.setdefault("items", []).append(
                {"name": item.service_name, "price": item.amount}
            )
    result: list[Any] = []
    for row_number, ((seller, page_index), page) in enumerate(
        sorted(pages.items()),
        1,
    ):
        result.append(
            SimpleNamespace(
                row_number=row_number,
                source_row_id=(f"{OZON_DIAGNOSTIC_FINANCE_SOURCE}:{page_index}:1"),
                loaded_at=page["loaded_at"],
                row_payload={
                    "marketplace": "ozon",
                    "seller_account_id": seller,
                    "source_page_index": page_index,
                    "source_endpoint": page["source_endpoint"],
                    "cash_flows": list(page["cash_flows"].values()),
                    "details": list(page["details"].values()),
                },
            )
        )
    return result


def _typed_ozon_namespace(
    item: MarketplaceOperationFact,
    *,
    expense_totals: Mapping[str, Decimal] | None = None,
    row_number: int | None = None,
) -> Any:
    totals = expense_totals or {}
    return SimpleNamespace(
        row_number=row_number or item.source_row_number or item.id,
        source_row_id=item.source_row_id,
        loaded_at=item.loaded_at,
        row_payload={
            "marketplace": "ozon",
            "seller_account_id": item.seller_account_id,
            "operation_id": item.operation_id,
            "Документ": item.operation_id,
            "posting_number": item.posting_number,
            "product_name": item.product_name,
            "name": item.product_name,
            "Название товара": item.product_name,
            "offer_id": item.offer_id,
            "Артикул": item.offer_id,
            "product_id": item.product_id,
            "Ozon Product ID": item.product_id,
            "sku": item.sku,
            "SKU": item.sku,
            "barcode": item.barcode,
            "Штрихкод (Серийный номер / EAN)": item.barcode,
            "service_key": item.service_key,
            "service_name": item.service_name,
            "quantity": item.quantity,
            "sale_amount": (
                None
                if item.is_partial_source and item.amount == Decimal("0")
                else item.amount
            ),
            "amount": (
                None
                if item.is_partial_source and item.amount == Decimal("0")
                else item.amount
            ),
            "price": (
                None
                if item.is_partial_source and item.amount == Decimal("0")
                else item.price
            ),
            "income": item.income,
            "expense": item.expense,
            "Сумма дебиторской задолженности, RUR": item.debit_amount,
            "Сумма кредиторской задолженности, RUR": item.credit_amount,
            "commission": totals.get("commission", item.commission),
            "services": totals.get("service_amount", item.service_amount),
            "logistics": totals.get("logistics", item.logistics),
            "storage": totals.get("storage", item.storage),
            "promotion": totals.get("promotion", item.promotion),
            "compensation": totals.get("compensation", item.compensation),
            "other": totals.get("other_amount", item.other_amount),
            "operation_type": item.operation_type,
            "Наименование": item.operation_type or item.product_name,
            "operation_date": (
                item.operation_date.isoformat() if item.operation_date else ""
            ),
            "Дата": (item.operation_date.isoformat() if item.operation_date else ""),
            "expenses_loaded": item.expenses_loaded,
            "is_partial_source": item.is_partial_source,
            "source_endpoint": item.source_endpoint,
        },
    )


def _source_snapshot_row_count(
    db: Session,
    *,
    tenant_id: str,
    refresh_run: SourceRefreshRun,
    source_type: str,
    wb_cabinet_id: str = "",
) -> int:
    stmt = _source_snapshot_rows_select(
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=source_type,
        wb_cabinet_id=wb_cabinet_id,
    )
    row_count = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    if row_count or not source_type.startswith("ozon_"):
        return row_count
    conditions = [
        MarketplaceOperationFact.tenant_id == tenant_id,
        MarketplaceOperationFact.source_refresh_run_id == refresh_run.id,
        MarketplaceOperationFact.source_type == source_type,
    ]
    if wb_cabinet_id:
        conditions.append(MarketplaceOperationFact.wb_cabinet_id == wb_cabinet_id)
    positions = db.execute(
        select(
            MarketplaceOperationFact.seller_account_id,
            MarketplaceOperationFact.source_row_number,
        ).where(*conditions)
    ).all()
    return len({(str(seller), int(position or 0)) for seller, position in positions})


def latest_ozon_diagnostics_payload(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
    limit: int = 50,
    preview_max_rows: int = OZON_DIAGNOSTIC_PREVIEW_MAX_ROWS,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    refresh_run_id: str = "",
    prefer_typed: bool = False,
) -> dict[str, Any]:
    row_limit = max(1, min(int(limit), max(1, int(preview_max_rows))))
    wb_cabinet_id = wb_cabinet_id.strip()
    refresh_run_id = refresh_run_id.strip()
    if refresh_run_id:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        if (
            refresh_run is None
            or refresh_run.tenant_id != tenant_id
            or (client_id and refresh_run.client_id != client_id)
            or refresh_run.mode != "ozon-only"
            or refresh_run.dry_run
            or refresh_run.finished_at is None
            or refresh_run.status not in CALCULABLE_OZON_REFRESH_STATUSES
        ):
            raise LookupError("calculable Ozon refresh run not found")
        latest_attempt = refresh_run
    else:
        latest_attempt = latest_source_refresh_run(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            mode="ozon-only",
        )
        refresh_run = latest_calculable_ozon_refresh_run(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
        )
    if refresh_run is None:
        return {
            "status": "needs_review" if latest_attempt is not None else "not_started",
            "message": (
                "Последняя попытка Ozon + 1C не дала завершенного расчетного снимка."
                if latest_attempt is not None
                else "Запустите Ozon + 1C, чтобы увидеть диагностику источников."
            ),
            "latestRun": None,
            "latestAttempt": (
                _ozon_refresh_run_summary(latest_attempt)
                if latest_attempt is not None
                else None
            ),
            "readiness": {
                "ozonFinanceLoaded": False,
                "ozonRealizationLoaded": False,
                "mappingLoaded": False,
                "onecRequiredLoaded": False,
                "reportExpected": False,
            },
            "sourceSummary": {},
            "collections": [],
            "finance": {
                "sourceType": OZON_DIAGNOSTIC_FINANCE_SOURCE,
                "rowCount": 0,
                "previewLimit": row_limit,
                "previewRowCount": 0,
                "previewLimited": False,
                "totals": {},
            },
            "financeRows": [],
            "ozonBuyouts": _empty_ozon_buyouts_payload(row_limit),
            "ozonMapping": _empty_ozon_mapping_payload(row_limit),
            "pnl": _empty_ozon_pnl_payload(),
            "ozonMart": empty_ozon_mart_payload(row_limit),
            "unitRows": _empty_ozon_unit_rows_payload(row_limit),
            "issues": _ozon_issue_payload(
                collections=[],
                readiness={
                    "ozonFinanceLoaded": False,
                    "ozonRealizationLoaded": False,
                    "mappingLoaded": False,
                    "onecRequiredLoaded": False,
                },
                ozon_mapping=_empty_ozon_mapping_payload(row_limit),
                ozon_buyouts=_empty_ozon_buyouts_payload(row_limit),
                source_row_count=0,
                pnl=_empty_ozon_pnl_payload(),
                ozon_mart=empty_ozon_mart_payload(row_limit),
            ),
        }

    collections = sorted(
        refresh_run.collections,
        key=lambda value: (value.required is False, value.source_type, value.id),
    )
    finance_row_count = sum(
        item.row_count
        for item in collections
        if item.source_type == OZON_DIAGNOSTIC_FINANCE_SOURCE
    )
    realization_row_count = sum(
        item.row_count
        for item in collections
        if item.source_type == OZON_REALIZATION_SOURCE
    )
    if wb_cabinet_id:
        finance_row_count = _source_snapshot_row_count(
            db,
            tenant_id=tenant_id,
            refresh_run=refresh_run,
            source_type=OZON_DIAGNOSTIC_FINANCE_SOURCE,
            wb_cabinet_id=wb_cabinet_id,
        )
        realization_row_count = _source_snapshot_row_count(
            db,
            tenant_id=tenant_id,
            refresh_run=refresh_run,
            source_type=OZON_REALIZATION_SOURCE,
            wb_cabinet_id=wb_cabinet_id,
        )
    finance_snapshot_rows = _ozon_typed_source_rows(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=OZON_DIAGNOSTIC_FINANCE_SOURCE,
        wb_cabinet_id=wb_cabinet_id,
        limit=None,
        prefer_typed=prefer_typed,
    )
    finance_rows = [
        _ozon_finance_preview_row(row) for row in finance_snapshot_rows[:row_limit]
    ]
    mutual_settlement_rows = _ozon_typed_source_rows(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=OZON_MUTUAL_SETTLEMENT_SOURCE,
        wb_cabinet_id=wb_cabinet_id,
        limit=None,
        prefer_typed=prefer_typed,
    )
    mutual_settlement_pnl_rows = _ozon_rows_matching_period(
        mutual_settlement_rows,
        collections=collections,
        source_type=OZON_MUTUAL_SETTLEMENT_SOURCE,
        period_start=period_start,
        period_end=period_end,
    )
    realization_snapshot_rows = _ozon_realization_source_rows(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        wb_cabinet_id=wb_cabinet_id,
        limit=None,
        prefer_typed=prefer_typed,
    )
    realization_pnl_rows = _ozon_rows_matching_period(
        realization_snapshot_rows,
        collections=collections,
        source_type=OZON_REALIZATION_SOURCE,
        period_start=period_start,
        period_end=period_end,
    )
    sales_register_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_sales_register",
            )
        )
    )
    commissioner_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_commissioner_reports",
            )
        )
    )
    expense_invoice_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == OZON_ONEC_BUYOUT_SOURCE,
            )
        )
    )
    incoming_invoice_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == OZON_ONEC_INCOMING_INVOICE_SOURCE,
            )
        )
    )
    supplier_receipt_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_supplier_receipts",
            )
        )
    )
    supplier_receipt_expense_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run.id,
                SourceSnapshotRow.source_type == "onec_supplier_receipt_expenses",
            )
        )
    )
    ozon_buyout_rows = _ozon_typed_source_rows(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=OZON_BUYOUT_API_SOURCE,
        wb_cabinet_id=wb_cabinet_id,
        limit=None,
        prefer_typed=prefer_typed,
    )
    ozon_mapping = _ozon_mapping_diagnostics_payload(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        limit=row_limit,
        wb_cabinet_id=wb_cabinet_id,
        prefer_typed=prefer_typed,
    )
    ozon_buyouts = _ozon_buyouts_payload(
        expense_invoice_rows,
        ozon_buyout_rows=ozon_buyout_rows,
        collections=collections,
        period_start=period_start,
        period_end=period_end,
        limit=row_limit,
    )
    onec_indexes = _ozon_onec_indexes_for_run(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
    )
    onec_costs = _onec_sales_cost_index(sales_register_rows)
    pnl = _ozon_pnl_payload(
        finance_snapshot_rows,
        finance_row_count=finance_row_count,
        realization_rows=realization_pnl_rows,
        realization_row_count=len(realization_pnl_rows),
        commissioner_rows=commissioner_rows,
        sales_register_rows=sales_register_rows,
        onec_indexes=onec_indexes,
        onec_costs=onec_costs,
        ozon_mapping=ozon_mapping,
        period_start=period_start,
        period_end=period_end,
        unit_row_limit=row_limit,
    )
    reconciliation = _ozon_revenue_reconciliation_payload(pnl, ozon_buyouts)
    _apply_ozon_buyout_unit_row(pnl, reconciliation)
    cash_flow_expenses = _ozon_cash_flow_expenses_payload(
        finance_snapshot_rows,
        period_start=period_start,
        period_end=period_end,
    )
    mutual_settlement_expenses = _ozon_mutual_settlement_expenses_payload(
        mutual_settlement_pnl_rows,
    )
    ozon_expenses = (
        mutual_settlement_expenses
        if mutual_settlement_expenses.get("status") == "loaded"
        else cash_flow_expenses
    )
    if ozon_expenses is not cash_flow_expenses:
        ozon_expenses["cashFlowControl"] = cash_flow_expenses
    onec_expenses = _onec_ozon_expense_control_payload(
        incoming_invoice_rows=incoming_invoice_rows,
        supplier_receipt_rows=supplier_receipt_rows,
        supplier_receipt_expense_rows=supplier_receipt_expense_rows,
        counterparty_ids=(pnl.get("onecOzon") or {}).get("counterpartyIds") or [],
        period_start=period_start,
        period_end=period_end,
    )
    expense_reconciliation = _ozon_expense_reconciliation_payload(
        ozon_expenses,
        onec_expenses,
    )
    _apply_ozon_period_expenses_to_pnl(pnl, ozon_expenses)
    pnl["deprecated"] = True
    pnl["replacement"] = "ozonMart"
    pnl["message"] = (
        "Прежний расчёт прибылей и убытков Ozon сохранён только "
        "для технической диагностики; "
        "используйте ozonMart."
    )
    effective_period_start = period_start or refresh_run.period_start
    effective_period_end = period_end or refresh_run.period_end
    cabinet = _ozon_calculation_cabinet(
        db,
        client_id=refresh_run.client_id,
        requested_cabinet_id=wb_cabinet_id,
    )
    company = (
        db.get(ClientCompany, cabinet.client_company_id)
        if cabinet is not None and cabinet.client_company_id
        else None
    )
    organization_id = company.onec_organization_id if company is not None else ""
    organization_scope_status = (
        "ready" if organization_id else "missing_1c_organization"
    )
    organization_sales_register_rows = sales_register_rows if organization_id else []
    project_mapping_preview_index = _ozon_project_mapping_preview_index(
        db,
        tenant_id=tenant_id,
        client_id=refresh_run.client_id,
        wb_cabinet_id=wb_cabinet_id,
    )
    organization_commissioner_rows = _onec_rows_for_organization(
        commissioner_rows,
        organization_id=organization_id,
    )
    ozon_counterparty_ids = tuple(
        str(item)
        for item in ((pnl.get("onecOzon") or {}).get("counterpartyIds") or [])
        if item
    )
    realization_periods_known = bool(
        _ozon_source_periods(collections, OZON_REALIZATION_SOURCE)
    )
    fallback_realization_month = _single_onec_document_month(
        organization_commissioner_rows
    )
    monthly_marts: list[dict[str, Any]] = []
    for month_start, month_end in _month_ranges(
        effective_period_start,
        effective_period_end,
    ):
        monthly_realization_rows = _ozon_rows_matching_period(
            realization_snapshot_rows,
            collections=collections,
            source_type=OZON_REALIZATION_SOURCE,
            period_start=month_start,
            period_end=month_end,
        )
        if not realization_periods_known:
            requested_month = (month_start.year, month_start.month)
            monthly_realization_rows = (
                realization_snapshot_rows
                if fallback_realization_month == requested_month
                else []
            )
        monthly_mutual_rows = _ozon_rows_matching_period(
            mutual_settlement_rows,
            collections=collections,
            source_type=OZON_MUTUAL_SETTLEMENT_SOURCE,
            period_start=month_start,
            period_end=month_end,
        )
        tax_profile, tax_profile_status = resolve_company_tax_profile(
            db,
            company=company,
            calculation_date=month_end,
            refresh_run=refresh_run,
        )
        monthly_costs = _onec_sales_cost_index(
            organization_sales_register_rows,
            period_start=month_start,
            period_end=month_end,
            organization_id=organization_id,
        )
        reference_unit_costs = _onec_previous_closed_month_costs(
            organization_sales_register_rows,
            commissioner_rows=organization_commissioner_rows,
            before_month=month_start,
            organization_id=organization_id,
        )
        direct_1c_cost_control = _onec_direct_cost_control(
            organization_sales_register_rows,
            period_start=month_start,
            period_end=month_end,
            organization_id=organization_id,
            counterparty_ids=ozon_counterparty_ids,
        )
        monthly_input_vat = _onec_sales_input_vat_index(
            organization_sales_register_rows,
            period_start=month_start,
            period_end=month_end,
            organization_id=organization_id,
        )
        monthly_expenses = _ozon_mutual_settlement_expenses_payload(monthly_mutual_rows)
        if monthly_expenses.get("status") != "loaded":
            monthly_expenses = _ozon_cash_flow_expenses_payload(
                finance_snapshot_rows,
                period_start=month_start,
                period_end=month_end,
            )
        monthly_mart = build_ozon_unit_economics_mart(
            realization_rows=monthly_realization_rows,
            commissioner_rows=organization_commissioner_rows,
            unit_costs=monthly_costs,
            mapping_resolver=_ozon_mart_mapping_resolver(
                onec_indexes=onec_indexes,
                ozon_mapping=ozon_mapping,
                project_mapping_preview_index=project_mapping_preview_index,
                preferred_onec_item_ids=_ozon_mart_preferred_onec_item_ids(
                    commissioner_rows=organization_commissioner_rows,
                    unit_costs=monthly_costs,
                    period_start=month_start,
                    period_end=month_end,
                ),
            ),
            buyout_reconciliation={},
            period_expense_amount=(
                (monthly_expenses.get("summary") or {}).get("expenseAmount")
                if monthly_expenses.get("basis")
                == "ozon_mutual_settlement_expense_documents"
                else None
            ),
            period_expense_articles=(
                monthly_expenses.get("categoryRows") or []
                if monthly_expenses.get("basis")
                == "ozon_mutual_settlement_expense_documents"
                else []
            ),
            period_expense_basis=str(monthly_expenses.get("basis") or ""),
            period_start=month_start,
            period_end=month_end,
            preview_limit=row_limit,
            tax_profile=tax_profile,
            tax_profile_required=True,
            input_vat_by_item=monthly_input_vat,
            reference_unit_costs=reference_unit_costs,
            direct_1c_cost_control=direct_1c_cost_control,
            organization_scope_status=organization_scope_status,
        )
        calculation_profile_status = monthly_mart["taxProfile"].get("status")
        monthly_mart["taxProfile"].update(tax_profile_status)
        if calculation_profile_status == "unconfirmed":
            monthly_mart["taxProfile"]["status"] = "unconfirmed"
        monthly_mart["periodExpenseSource"] = monthly_expenses
        monthly_marts.append(monthly_mart)
    ozon_mart = combine_ozon_monthly_marts(
        monthly_marts,
        preview_limit=row_limit,
    )
    direct_onec_control = _onec_direct_sales_control(
        organization_sales_register_rows,
        period_start=effective_period_start,
        period_end=effective_period_end,
        organization_id=organization_id,
        counterparty_ids=ozon_counterparty_ids,
    )
    ozon_mart["reconciliationTotals"] = _ozon_mart_reconciliation_totals_payload(
        ozon_mart,
        direct_onec_control,
    )
    _apply_direct_onec_totals_to_ozon_mart(ozon_mart, direct_onec_control)
    ozon_mart["periodExpenseSource"] = ozon_expenses
    _block_ozon_profit_for_duplicate_snapshot(ozon_mart, collections)
    ozon_mart["articleDrilldown"] = _ozon_article_drilldown_payload(
        ozon_mart,
        expense_reconciliation,
    )
    readiness = _ozon_diagnostic_readiness(collections)
    ready = (
        readiness["ozonRealizationLoaded"]
        and readiness["mappingLoaded"]
        and readiness["onecRequiredLoaded"]
        and ozon_mapping["status"] in {"ready", "not_applicable"}
        and ozon_mart.get("status") == "ready"
    )
    issues = _ozon_issue_payload(
        collections=collections,
        readiness=readiness,
        ozon_mapping=ozon_mapping,
        ozon_buyouts=ozon_buyouts,
        source_row_count=realization_row_count,
        pnl=pnl,
        ozon_mart=ozon_mart,
    )
    issues = _with_ozon_mart_issues(issues, ozon_mart)
    source_summary = _ozon_diagnostic_source_summary(
        collections,
        wb_cabinet_id=wb_cabinet_id,
    )
    _apply_ozon_buyout_source_summary(source_summary, ozon_buyouts)
    collection_payloads = [
        _ozon_diagnostic_collection_payload(
            item,
            ozon_buyouts=ozon_buyouts,
            wb_cabinet_id=wb_cabinet_id,
        )
        for item in collections
    ]
    return {
        "status": "ready" if ready else "needs_review",
        "message": _ozon_diagnostic_message(refresh_run, readiness),
        "latestRun": _ozon_refresh_run_summary(refresh_run),
        "latestAttempt": (
            _ozon_refresh_run_summary(latest_attempt)
            if latest_attempt is not None and latest_attempt.id != refresh_run.id
            else None
        ),
        "readiness": readiness,
        "sourceSummary": source_summary,
        "collections": collection_payloads,
        "finance": {
            "sourceType": OZON_DIAGNOSTIC_FINANCE_SOURCE,
            "rowCount": finance_row_count,
            "previewLimit": row_limit,
            "previewRowCount": len(finance_rows),
            "previewLimited": finance_row_count > len(finance_rows),
            "totals": _ozon_finance_preview_totals(finance_rows),
        },
        "financeRows": finance_rows,
        "ozonBuyouts": ozon_buyouts,
        "ozonMapping": ozon_mapping,
        "pnl": pnl,
        "reconciliation": reconciliation,
        "expenseReconciliation": expense_reconciliation,
        "ozonMart": ozon_mart,
        "unitRows": _ozon_unit_rows_payload_from_mart(ozon_mart, row_limit),
        "issues": issues,
    }


def _ozon_refresh_run_summary(refresh_run: SourceRefreshRun) -> dict[str, Any]:
    return {
        "id": refresh_run.id,
        "status": refresh_run.status,
        "mode": refresh_run.mode,
        "dryRun": refresh_run.dry_run,
        "snapshotSetId": refresh_run.snapshot_set_id,
        "periodStart": refresh_run.period_start.isoformat(),
        "periodEnd": refresh_run.period_end.isoformat(),
        "createdAt": refresh_run.created_at.isoformat(),
        "startedAt": (
            refresh_run.started_at.isoformat() if refresh_run.started_at else None
        ),
        "finishedAt": (
            refresh_run.finished_at.isoformat() if refresh_run.finished_at else None
        ),
        "safeMessage": _safe_source_refresh_message(refresh_run),
    }


def _ozon_calculation_cabinet(
    db: Session,
    *,
    client_id: str,
    requested_cabinet_id: str,
) -> WbCabinet | None:
    if requested_cabinet_id:
        cabinet = db.get(WbCabinet, requested_cabinet_id)
        if cabinet is not None and cabinet.client_id == client_id:
            return cabinet
        return None
    cabinets = list(
        db.scalars(
            select(WbCabinet).where(
                WbCabinet.client_id == client_id,
                WbCabinet.status == "active",
                WbCabinet.provider.ilike("ozon%"),
            )
        )
    )
    return cabinets[0] if len(cabinets) == 1 else None


def _onec_rows_for_organization(
    rows: list[SourceSnapshotRow],
    *,
    organization_id: str,
) -> list[SourceSnapshotRow]:
    if not organization_id:
        return []
    return [
        row
        for row in rows
        if _safe_payload_text(
            row.row_payload or {},
            "Организация_Key",
            "organization_id",
            "organizationId",
        )
        == organization_id
    ]


def _single_onec_document_month(
    rows: list[SourceSnapshotRow],
) -> tuple[int, int] | None:
    months = {
        (value.year, value.month)
        for row in rows
        if (
            value := date_or_none(
                _safe_payload_text(
                    row.row_payload or {},
                    "Date",
                    "Дата",
                    "date",
                )
            )
        )
        is not None
    }
    return next(iter(months)) if len(months) == 1 else None


def _ozon_issue_payload(
    *,
    collections: list[SourceRefreshCollection],
    readiness: dict[str, bool],
    ozon_mapping: dict[str, Any],
    ozon_buyouts: dict[str, Any] | None = None,
    source_row_count: int,
    pnl: dict[str, Any] | None = None,
    ozon_mart: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = ozon_mapping.get("summary") or {}
    issues: list[dict[str, str]] = []
    failed_sources = sum(1 for item in collections if _source_collection_failed(item))
    review_sources = sum(
        1
        for item in collections
        if item.status in {"needs_review", "partial_source", "stale"}
    )
    missing = int(summary.get("missing") or 0)
    ambiguous = int(summary.get("ambiguous") or 0)
    no_key = int(summary.get("noKey") or 0)
    checked = int(ozon_mapping.get("checkedRows") or 0)
    matched = int(summary.get("matched") or 0)

    if failed_sources:
        issues.append(
            {
                "code": "ozon_source_failed",
                "title": "Ошибки источников",
                "value": f"{failed_sources} источников",
                "detail": "Сначала проверить доступы или повторить Ozon + 1C загрузку.",
                "tone": "bad",
            }
        )
    if not readiness.get("ozonRealizationLoaded"):
        issues.append(
            {
                "code": "ozon_realization_missing",
                "title": "Ozon реализации",
                "value": "нет данных",
                "detail": "Отчет реализации Ozon не загружен.",
                "tone": "bad",
            }
        )
    if not readiness.get("mappingLoaded"):
        issues.append(
            {
                "code": "ozon_mapping_source_missing",
                "title": "Файл сопоставления",
                "value": "не загружен",
                "detail": "Бухгалтерии нужно загрузить сопоставление Ozon -> 1C.",
                "tone": "review",
            }
        )
    if not readiness.get("onecRequiredLoaded"):
        issues.append(
            {
                "code": "ozon_onec_missing",
                "title": "Источники 1C",
                "value": "не готовы",
                "detail": "Обязательные 1C-источники не прошли загрузку.",
                "tone": "bad",
            }
        )
    if ambiguous:
        issues.append(
            {
                "code": "ozon_mapping_ambiguous",
                "title": "Неоднозначное сопоставление",
                "value": f"{ambiguous} строк",
                "detail": "Один Ozon-товар связан с несколькими позициями 1C.",
                "tone": "review",
            }
        )
    if missing:
        issues.append(
            {
                "code": "ozon_mapping_missing",
                "title": "Нет связи Ozon -> 1C",
                "value": f"{missing} строк",
                "detail": (
                    "Эти строки нужно поправить в 1C ИС_Маркетплейс "
                    "или ручном файле сопоставления."
                ),
                "tone": "review",
            }
        )
    if no_key:
        issues.append(
            {
                "code": "ozon_mapping_no_key",
                "title": "Нет ключа товара",
                "value": f"{no_key} строк",
                "detail": "В каталоге Ozon нет ключа для автоматической проверки.",
                "tone": "review",
            }
        )
    if review_sources and not failed_sources:
        issues.append(
            {
                "code": "ozon_source_review",
                "title": "Источник к проверке",
                "value": f"{review_sources} источников",
                "detail": "Есть неполные или устаревшие источники.",
                "tone": "review",
            }
        )
    if ozon_buyouts:
        buyout_summary = ozon_buyouts.get("summary") or {}
        missing_buyouts = int(buyout_summary.get("missingInOzonApi") or 0)
        period_total_matches = int(buyout_summary.get("matchedByPeriodTotal") or 0)
        if missing_buyouts:
            issues.append(
                {
                    "code": "ozon_buyout_report_not_found",
                    "title": "Выкупы Ozon",
                    "value": f"{missing_buyouts} отчетов",
                    "detail": (
                        "Номер выкупного отчета найден в 1C, но не найден "
                        "в загруженном Ozon buyout API."
                    ),
                    "tone": "review",
                }
            )
        elif period_total_matches:
            issues.append(
                {
                    "code": "ozon_buyout_matched_without_report_number",
                    "title": "Выкупы Ozon",
                    "value": f"{period_total_matches} отчетов",
                    "detail": (
                        "Сумма и количество сходятся с Ozon buyout за период, "
                        "но Ozon API не вернул номер выкупного отчета."
                    ),
                    "tone": "review",
                }
            )
    if (
        pnl
        and pnl.get("status") == "partial_source"
        and readiness.get("ozonRealizationLoaded")
    ):
        onec_ozon = pnl.get("onecOzon") or {}
        has_realization = bool(pnl.get("realizationRows"))
        has_partial_cogs = bool(pnl.get("costedItemRows")) and bool(
            pnl.get("realizationRowsLimited")
        )
        if has_realization and onec_ozon.get("status") != "loaded":
            issues.append(
                {
                    "code": "ozon_onec_commissioner_missing",
                    "title": "Нет выручки 1C",
                    "value": "нет строк",
                    "detail": (
                        "Ozon realization за период есть, но в 1C нет выручки "
                        "отчета комиссионера по товару; выручку из Ozon API "
                        "не подставляем."
                    ),
                    "tone": "review",
                }
            )
        else:
            issues.append(
                {
                    "code": (
                        "ozon_pnl_limited_item_rows"
                        if has_partial_cogs
                        else "ozon_pnl_needs_cost_mapping"
                        if has_realization
                        else "ozon_pnl_needs_item_detail"
                    ),
                    "title": "Себестоимость 1C",
                    "value": (
                        f"{int(pnl.get('realizationRowsUsed') or 0)} / "
                        f"{int(pnl.get('realizationRows') or 0)} строк"
                        if has_partial_cogs
                        else "не применена"
                    ),
                    "detail": (
                        "Себестоимость посчитана только по предварительно "
                        "показанной части Ozon "
                        "realization; для финальной прибыли нужен полный расчет."
                        if has_partial_cogs
                        else (
                            "Проверьте сопоставление и себестоимость 1C "
                            "по товарным строкам."
                        )
                        if has_realization
                        else "Для прибыли после 1C нужны товарные продажи Ozon."
                    ),
                    "tone": "review",
                }
            )
    if pnl:
        onec_ozon = pnl.get("onecOzon") or {}
        sales_register = onec_ozon.get("salesRegister") or {}
        delta = _decimal_from_payload_value(
            sales_register.get("deltaVsCommissionerNet")
        ) or Decimal("0")
        extra_loaded = any(
            item.source_type in OZON_EXTRA_RECONCILIATION_SOURCES
            and _source_collection_loaded(item)
            and item.row_count > 0
            for item in collections
        )
        if delta and not extra_loaded:
            issues.append(
                {
                    "code": "ozon_extra_reconciliation_missing",
                    "title": "Дельта к комиссионеру",
                    "value": f"{_json_number(delta)} ₽",
                    "detail": (
                        "Нужны доп. Ozon-источники: позаказная реализация, "
                        "выкупы или B2B."
                    ),
                    "tone": "review",
                }
            )

    if ozon_mart:
        for item in ozon_mart.get("issues") or []:
            if not isinstance(item, dict):
                continue
            if item.get("code") in {
                "ozon_mart_partial_expenses",
                "ozon_mart_missing_cost",
            }:
                issues.append(
                    {
                        "code": str(item.get("code") or ""),
                        "title": str(item.get("title") or ""),
                        "value": str(item.get("value") or ""),
                        "detail": str(item.get("detail") or ""),
                        "tone": str(item.get("tone") or "review"),
                    }
                )

    if not issues and checked and matched == checked and source_row_count:
        issues.append(
            {
                "code": "ozon_no_critical_issues",
                "title": "Критичных ошибок нет",
                "value": "готово",
                "detail": "Можно читать Ozon-витрину и готовить вывод.",
                "tone": "ok",
            }
        )

    return {
        "blockingCount": sum(1 for item in issues if item["tone"] == "bad"),
        "reviewCount": sum(1 for item in issues if item["tone"] == "review"),
        "items": issues[:8],
    }


def _with_ozon_mart_issues(
    issues: dict[str, Any],
    ozon_mart: dict[str, Any],
) -> dict[str, Any]:
    existing_codes = {str(item.get("code") or "") for item in issues.get("items") or []}
    merged_items = list(issues.get("items") or [])
    for item in ozon_mart.get("issues") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        if not code or code in existing_codes:
            continue
        if code == "ozon_mart_buyout_period_only":
            continue
        merged_items.append(
            {
                "code": code,
                "title": str(item.get("title") or ""),
                "value": str(item.get("value") or ""),
                "detail": str(item.get("detail") or ""),
                "tone": str(item.get("tone") or "review"),
            }
        )
        existing_codes.add(code)
    return {
        "blockingCount": sum(1 for item in merged_items if item["tone"] == "bad"),
        "reviewCount": sum(1 for item in merged_items if item["tone"] == "review"),
        "items": merged_items[:8],
    }


def _empty_ozon_pnl_payload() -> dict[str, Any]:
    return {
        "status": "not_started",
        "message": "Запустите Ozon + 1C, чтобы увидеть расчетную витрину.",
        "basis": "onec_sales_register",
        "rowCount": 0,
        "cashFlowRows": 0,
        "sourceRowsUsed": 0,
        "sourceRowsLimited": False,
        "realizationRows": 0,
        "ozonRealizationAmount": None,
        "itemLevelRows": 0,
        "costedItemRows": 0,
        "totals": {
            "ordersAmount": 0.0,
            "returnsAmount": 0.0,
            "cashFlowRevenue": 0.0,
            "revenue": 0.0,
            "revenueBasis": "none",
            "commissionAmount": 0.0,
            "deliveryAndReturnAmount": 0.0,
            "servicesAmount": 0.0,
            "ozonExpenses": 0.0,
            "profitBeforeCogs": 0.0,
            "onecCogs": None,
            "profitAfterCogs": None,
            "marginBeforeCogs": None,
        },
        "onecOzon": _empty_ozon_onec_commissioner_payload(),
        "periods": [],
    }


def _empty_ozon_unit_rows_payload(limit: int = 0) -> dict[str, Any]:
    return {
        "status": "not_started",
        "rowCount": 0,
        "previewLimit": limit,
        "previewRowCount": 0,
        "previewLimited": False,
        "summary": _empty_ozon_unit_row_summary(),
        "rows": [],
    }


def _empty_ozon_unit_row_summary() -> dict[str, int]:
    return {
        "ready": 0,
        "missingMapping": 0,
        "ambiguousMapping": 0,
        "missingCost": 0,
        "missing1cCommissioner": 0,
        "missing1cOrganization": 0,
        "buyoutPeriodOnly": 0,
    }


def _ozon_unit_rows_payload(pnl: dict[str, Any], limit: int) -> dict[str, Any]:
    rows = list(pnl.get("unitRows") or [])
    row_count = int(pnl.get("unitRowCount") or len(rows))
    return {
        "status": pnl.get("status") or "not_started",
        "rowCount": row_count,
        "previewLimit": limit,
        "previewRowCount": len(rows),
        "previewLimited": bool(pnl.get("unitRowsLimited") or row_count > len(rows)),
        "summary": pnl.get("unitRowSummary") or _empty_ozon_unit_row_summary(),
        "rows": rows,
    }


def _ozon_unit_rows_payload_from_mart(
    ozon_mart: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    rows = [
        _ozon_unit_row_from_mart_row(row)
        for row in (ozon_mart.get("rows") or [])
        if isinstance(row, dict)
    ]
    row_count = int(ozon_mart.get("rowCount") or len(rows))
    summary = ozon_mart.get("summary") or {}
    return {
        "status": ozon_mart.get("status") or "not_started",
        "rowCount": row_count,
        "previewLimit": limit,
        "previewRowCount": len(rows),
        "previewLimited": bool(ozon_mart.get("previewLimited")),
        "summary": {
            "ready": int(summary.get("ready") or 0),
            "partialSource": int(summary.get("partialSource") or 0),
            "missingMapping": int(summary.get("missingMapping") or 0),
            "ambiguousMapping": int(summary.get("ambiguousMapping") or 0),
            "missingCost": int(summary.get("missingCost") or 0),
            "missing1cCommissioner": int(summary.get("missing1cCommissioner") or 0),
            "missing1cOrganization": int(summary.get("missing1cOrganization") or 0),
            "buyoutPeriodOnly": int(summary.get("buyoutPeriodOnly") or 0),
            "partialExpenses": int(summary.get("partialExpenses") or 0),
        },
        "rows": rows,
    }


def _ozon_unit_row_from_mart_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rowType": row.get("rowType") or "realization_item",
        "periodStart": row.get("periodStart"),
        "periodEnd": row.get("periodEnd"),
        "rowNumber": row.get("rowNumber"),
        "sourceRowId": row.get("sourceRowId") or "",
        "productName": row.get("productName") or "",
        "offerId": row.get("offerId") or "",
        "productId": row.get("productId") or "",
        "sku": row.get("sku") or "",
        "barcode": row.get("barcode") or "",
        "quantity": row.get("quantity"),
        "realizationAmount": row.get("realizationAmount"),
        "onecRevenue": row.get("onecRevenue"),
        "revenueAmount": row.get("revenueAmount"),
        "revenueBasis": row.get("revenueBasis") or "none",
        "onecItemId": row.get("onecItemId") or "",
        "onecName": row.get("onecName") or "",
        "unitCost": row.get("unitCost"),
        "cogs": row.get("cogs"),
        "cogsAmount": row.get("cogsAmount"),
        "ozonCommission": row.get("ozonCommission"),
        "ozonServices": row.get("ozonServices"),
        "ozonPartnerServices": row.get("ozonPartnerServices"),
        "ozonLogistics": row.get("ozonLogistics"),
        "ozonStorage": row.get("ozonStorage"),
        "ozonOtherExpenses": row.get("ozonOtherExpenses"),
        "ozonExpenses": row.get("ozonExpenses"),
        "skuAttributedExpenseAmount": row.get("skuAttributedExpenseAmount"),
        "periodUnattributedExpenseAmount": row.get("periodUnattributedExpenseAmount"),
        "profit": row.get("profit"),
        "profitAmount": row.get("profitAmount"),
        "margin": row.get("margin"),
        "profitBeforeTax": row.get("profitBeforeTax"),
        "marginBeforeTax": row.get("marginBeforeTax"),
        "vatOutput": row.get("vatOutput"),
        "vatInput": row.get("vatInput"),
        "vatPayable": row.get("vatPayable"),
        "revenueTax": row.get("revenueTax"),
        "incomeTax": row.get("incomeTax"),
        "profitBeforeIncomeTax": row.get("profitBeforeIncomeTax"),
        "profitAfterTax": row.get("profitAfterTax"),
        "marginAfterTax": row.get("marginAfterTax"),
        "taxSystem": row.get("taxSystem") or "",
        "taxProfileSource": row.get("taxProfileSource") or "missing",
        "taxCompleteness": row.get("taxCompleteness") or "not_calculated",
        "profitAliasDeprecated": True,
        "mappingStatus": row.get("mappingStatus") or "",
        "qualityStatus": row.get("qualityStatus") or "",
        "costQualityStatus": row.get("costQualityStatus") or "not_evaluated",
        "referenceUnitCost": row.get("referenceUnitCost"),
        "unitCostDeviationPct": row.get("unitCostDeviationPct"),
        "estimatedCostImpact": row.get("estimatedCostImpact"),
        "costQualityReason": row.get("costQualityReason") or "not_evaluated",
        "expenseStatus": row.get("expenseStatus") or "",
        "expenseBasis": row.get("expenseBasis") or "",
        "expenseAttributionType": row.get("expenseAttributionType") or "",
        "expenseAllocationBasis": row.get("expenseAllocationBasis") or "",
        "expenseAllocationShare": row.get("expenseAllocationShare"),
        "problemReason": row.get("problemReason") or "",
        "statusReason": row.get("statusReason") or "",
        "actionText": row.get("actionText") or "",
    }


def _increment_ozon_unit_summary(summary: dict[str, int], status: str) -> None:
    key = {
        "ready": "ready",
        "missing_mapping": "missingMapping",
        "ambiguous_mapping": "ambiguousMapping",
        "missing_cost": "missingCost",
        "missing_1c_commissioner": "missing1cCommissioner",
        "buyout_period_only": "buyoutPeriodOnly",
    }.get(status)
    if key:
        summary[key] = int(summary.get(key) or 0) + 1


def _ozon_mapping_preview_index(
    ozon_mapping: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in ozon_mapping.get("rows") or []:
        if not isinstance(row, dict):
            continue
        for field in ("offerId", "productId", "sku", "barcode"):
            key = _mapping_lookup_key(row.get(field))
            if key:
                index[(field, key)] = row
        name_key = _mapping_name_key(row.get("productName"))
        if name_key:
            index[("productName", name_key)] = row
    return index


def _ozon_project_mapping_preview_index(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    wb_cabinet_id: str = "",
) -> dict[tuple[str, str], dict[str, Any]]:
    conditions = [
        MarketplaceMappingItem.tenant_id == tenant_id,
        MarketplaceMappingItem.client_id == client_id,
        MarketplaceMappingItem.marketplace == "ozon",
        MarketplaceMappingItem.status == "matched",
        Marketplace1cCurrentMapping.revoked_at.is_(None),
        Marketplace1cCurrentMapping.status == "matched",
    ]
    if wb_cabinet_id:
        conditions.append(MarketplaceMappingItem.wb_cabinet_id == wb_cabinet_id)
    rows = db.execute(
        select(
            MarketplaceMappingItem,
            Marketplace1cCurrentMapping,
            OnecMappingItem,
        )
        .join(
            Marketplace1cCurrentMapping,
            Marketplace1cCurrentMapping.item_id == MarketplaceMappingItem.id,
        )
        .join(
            OnecMappingItem,
            OnecMappingItem.id == Marketplace1cCurrentMapping.onec_mapping_item_id,
        )
        .where(*conditions)
    ).all()
    candidates_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item, current, onec in rows:
        preview = {
            "productName": item.title,
            "offerId": item.offer_id,
            "productId": item.product_id,
            "sku": item.ozon_sku,
            "barcode": item.barcode,
            "status": "matched",
            "matchMethod": f"mapping_service:{current.match_method or 'current'}",
            "matchKey": item.offer_id or item.ozon_sku or item.product_id,
            "onecItemId": onec.onec_item_id,
            "onecName": onec.name[:240],
            "onecArticle": onec.onec_article[:120],
        }
        for field, value in (
            ("offerId", item.offer_id),
            ("productId", item.product_id),
            ("sku", item.ozon_sku),
            ("barcode", item.barcode),
        ):
            key = _mapping_lookup_key(value)
            if key:
                candidates_by_key[(field, key)].append(preview)
        name_key = _mapping_name_key(item.title)
        if name_key:
            candidates_by_key[("productName", name_key)].append(preview)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, candidates in candidates_by_key.items():
        unique = {
            str(candidate.get("onecItemId") or ""): candidate
            for candidate in candidates
            if candidate.get("onecItemId")
        }
        if len(unique) == 1:
            result[key] = next(iter(unique.values()))
    return result


def _ozon_mapping_preview_for_candidate(
    candidate: dict[str, Any],
    index: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    attempts: list[tuple[str, str]] = []
    for field in ("productId", "sku", "barcode", "offerId"):
        key = _mapping_lookup_key(candidate.get(field))
        if key:
            attempts.append((field, key))

    sku_key = _mapping_lookup_key(candidate.get("sku"))
    if sku_key:
        attempts.append(("barcode", sku_key))
    barcode_key = _mapping_lookup_key(candidate.get("barcode"))
    if barcode_key:
        attempts.append(("sku", barcode_key))

    name_key = _mapping_name_key(candidate.get("productName"))
    if name_key:
        attempts.append(("productName", name_key))

    for field, key in attempts:
        row = index.get((field, key))
        if row:
            return row
    return None


def _ozon_mapping_status_counter(status: str) -> str:
    return {
        "matched": "matched",
        "missing": "missing",
        "ambiguous": "ambiguous",
        "no_key": "noKey",
    }.get(status, "notChecked")


def _check_ozon_unit_mapping_candidate(
    candidate: dict[str, Any],
    *,
    onec_indexes: dict[str, Any],
    ozon_mapping_preview_index: dict[tuple[str, str], dict[str, Any]],
    preferred_onec_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    preview = _ozon_mapping_preview_for_candidate(
        candidate,
        ozon_mapping_preview_index,
    )
    if preview and str(preview.get("status") or "") != "ambiguous":
        return {
            "statusCounter": _ozon_mapping_status_counter(
                str(preview.get("status") or "")
            ),
            "row": preview,
        }
    checked = _check_ozon_mapping_candidate(
        candidate,
        onec_indexes,
        preferred_onec_item_ids=preferred_onec_item_ids or set(),
    )
    if preview and (checked.get("row") or {}).get("status") != "matched":
        return {
            "statusCounter": _ozon_mapping_status_counter(
                str(preview.get("status") or "")
            ),
            "row": preview,
        }
    return checked


def _ozon_mart_mapping_resolver(
    *,
    onec_indexes: dict[str, Any],
    ozon_mapping: dict[str, Any],
    project_mapping_preview_index: dict[tuple[str, str], dict[str, Any]] | None = None,
    preferred_onec_item_ids: set[str] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any] | None]:
    preview_index = _ozon_mapping_preview_index(ozon_mapping)
    project_mapping_preview_index = project_mapping_preview_index or {}

    def _resolve(candidate: dict[str, Any]) -> dict[str, Any] | None:
        project_mapping = _ozon_mapping_preview_for_candidate(
            candidate,
            project_mapping_preview_index,
        )
        if project_mapping is not None:
            return project_mapping
        checked = _check_ozon_unit_mapping_candidate(
            candidate,
            onec_indexes=onec_indexes,
            ozon_mapping_preview_index=preview_index,
            preferred_onec_item_ids=preferred_onec_item_ids or set(),
        )
        row = checked.get("row")
        return row if isinstance(row, dict) else None

    return _resolve


def _ozon_mart_preferred_onec_item_ids(
    *,
    commissioner_rows: list[SourceSnapshotRow],
    unit_costs: Mapping[str, Decimal],
    period_start: date | None,
    period_end: date | None,
) -> set[str]:
    revenue_by_item, _ = _onec_commissioner_revenue_by_item(
        commissioner_rows,
        period_start=period_start,
        period_end=period_end,
    )
    return set(revenue_by_item).intersection(unit_costs)


def _ozon_revenue_reconciliation_payload(
    pnl: dict[str, Any],
    ozon_buyouts: dict[str, Any],
) -> dict[str, Any]:
    onec_ozon = pnl.get("onecOzon") or {}
    sales_register = onec_ozon.get("salesRegister") or {}
    onec_loaded = onec_ozon.get("status") == "loaded"
    register_amount = (
        _decimal_from_payload_value(sales_register.get("amount"))
        if onec_loaded
        else None
    )
    onec_commissioner_amount = (
        _decimal_from_payload_value(onec_ozon.get("netSalesAmount"))
        if onec_loaded
        else None
    )
    ozon_commissioner_amount = _decimal_from_payload_value(
        pnl.get("ozonRealizationAmount")
    )
    buyout_summary = ozon_buyouts.get("summary") or {}
    buyout_api_loaded = buyout_summary.get("ozonApiLoaded") is True
    buyout_amount = (
        _decimal_from_payload_value(buyout_summary.get("ozonApiAmount"))
        if buyout_api_loaded
        else None
    )
    onec_buyout_amount = _decimal_from_payload_value(buyout_summary.get("amount"))
    buyout_quantity = _decimal_from_payload_value(
        buyout_summary.get("ozonApiQuantity")
    ) or Decimal("0")
    ozon_total = (
        ozon_commissioner_amount + buyout_amount
        if ozon_commissioner_amount is not None and buyout_amount is not None
        else None
    )
    delta = (
        register_amount - ozon_total
        if register_amount is not None and ozon_total is not None
        else None
    )
    commissioner_delta = (
        onec_commissioner_amount - ozon_commissioner_amount
        if onec_commissioner_amount is not None and ozon_commissioner_amount is not None
        else None
    )
    buyout_delta = (
        (onec_buyout_amount or Decimal("0")) - buyout_amount
        if buyout_amount is not None
        else None
    )
    matched_buyouts = int(buyout_summary.get("foundInOzonApi") or 0)
    missing_buyouts = int(buyout_summary.get("missingInOzonApi") or 0)
    matched_without_number = int(buyout_summary.get("matchedByPeriodTotal") or 0)
    document_control = _ozon_revenue_document_control_payload(
        pnl=pnl,
        ozon_buyouts=ozon_buyouts,
        ozon_commissioner_amount=ozon_commissioner_amount,
        onec_commissioner_amount=onec_commissioner_amount,
        commissioner_delta=commissioner_delta,
        buyout_amount=buyout_amount,
        onec_buyout_amount=onec_buyout_amount,
        buyout_delta=buyout_delta,
    )
    status = (
        "matched"
        if delta is not None
        and _decimal_close(delta, Decimal("0"), Decimal("0.01"))
        and not document_control["issueCount"]
        else "review"
    )
    message = (
        "API Ozon по реализации и выкупам сходится с регистром продаж 1C."
        if status == "matched"
        else (
            f"Найдено проблем по первичным документам 1C: "
            f"{document_control['issueCount']}."
        )
    )
    return {
        "status": status,
        "message": message,
        "sourceType": "onec_sales_register",
        "sourceLabel": "1C · регистр продаж",
        "ozonSourceLabel": "Ozon API · реализация и выкупы",
        "ozonCommissionerAmount": _json_number(ozon_commissioner_amount),
        "commissionerAmount": _json_number(onec_commissioner_amount),
        "commissionerDeltaAmount": _json_number(commissioner_delta),
        "buyoutAmount": _json_number(buyout_amount),
        "onecBuyoutAmount": _json_number(onec_buyout_amount),
        "buyoutDeltaAmount": _json_number(buyout_delta),
        "ozonTotalAmount": _json_number(ozon_total),
        "onecSalesRegisterAmount": _json_number(register_amount),
        "deltaAmount": _json_number(delta),
        "buyoutQuantity": _json_number(buyout_quantity),
        "matchedBuyouts": matched_buyouts,
        "missingBuyouts": missing_buyouts,
        "matchedWithoutReportNumber": matched_without_number,
        "documentControl": document_control,
    }


def _ozon_revenue_document_control_payload(
    *,
    pnl: Mapping[str, Any],
    ozon_buyouts: Mapping[str, Any],
    ozon_commissioner_amount: Decimal | None,
    onec_commissioner_amount: Decimal | None,
    commissioner_delta: Decimal | None,
    buyout_amount: Decimal | None,
    onec_buyout_amount: Decimal | None,
    buyout_delta: Decimal | None,
) -> dict[str, Any]:
    onec_ozon = pnl.get("onecOzon") or {}
    period = pnl.get("periodFilter") or {}
    commissioner_documents = list(onec_ozon.get("documentRows") or [])
    buyout_documents = list(ozon_buyouts.get("rows") or [])
    commissioner_status = _ozon_commissioner_control_status(
        ozon_amount=ozon_commissioner_amount,
        onec_amount=onec_commissioner_amount,
        delta=commissioner_delta,
        documents=commissioner_documents,
    )
    buyout_status = _ozon_buyout_control_status(
        ozon_amount=buyout_amount,
        onec_amount=onec_buyout_amount,
        delta=buyout_delta,
        documents=buyout_documents,
    )
    rows = [
        _ozon_document_control_row(
            kind="commissioner",
            label="Отчет комиссионера",
            period_start=str(period.get("periodStart") or ""),
            period_end=str(period.get("periodEnd") or ""),
            ozon_amount=ozon_commissioner_amount,
            onec_amount=onec_commissioner_amount,
            delta=commissioner_delta,
            documents=commissioner_documents,
            status=commissioner_status,
        ),
        _ozon_document_control_row(
            kind="buyout",
            label="Выкупы",
            period_start=str(period.get("periodStart") or ""),
            period_end=str(period.get("periodEnd") or ""),
            ozon_amount=buyout_amount,
            onec_amount=onec_buyout_amount,
            delta=buyout_delta,
            documents=buyout_documents,
            status=buyout_status,
        ),
    ]
    issue_rows = [row for row in rows if row["status"] != "matched"]
    return {
        "status": "matched" if not issue_rows else "review",
        "issueCount": len(issue_rows),
        "missingPrimaryCount": sum(row["status"] == "missing_in_1c" for row in rows),
        "wrongDateCount": sum(row["status"] == "wrong_date" for row in rows),
        "notPostedCount": sum(row["status"] == "not_posted" for row in rows),
        "amountMismatchCount": sum(row["status"] == "amount_mismatch" for row in rows),
        "rows": rows,
    }


def _ozon_commissioner_control_status(
    *,
    ozon_amount: Decimal | None,
    onec_amount: Decimal | None,
    delta: Decimal | None,
    documents: list[Mapping[str, Any]],
) -> str:
    if ozon_amount is None:
        return "missing_ozon_source"
    if not documents:
        return "missing_in_1c"
    if any(item.get("status") == "not_posted" for item in documents):
        return "not_posted"
    if any(item.get("status") == "wrong_date" for item in documents):
        return "wrong_date"
    if onec_amount is None:
        return "missing_in_1c"
    if delta is None or abs(delta) > Decimal("1"):
        return "amount_mismatch"
    return "matched"


def _ozon_buyout_control_status(
    *,
    ozon_amount: Decimal | None,
    onec_amount: Decimal | None,
    delta: Decimal | None,
    documents: list[Mapping[str, Any]],
) -> str:
    if ozon_amount is None:
        return "missing_ozon_source"
    if ozon_amount and not documents:
        return "missing_in_1c"
    if any(_ozon_buyout_document_wrong_date(item) for item in documents):
        return "wrong_date"
    if delta is None or abs(delta) > Decimal("1"):
        return "amount_mismatch"
    if onec_amount is None and ozon_amount:
        return "missing_in_1c"
    return "matched"


def _ozon_buyout_document_wrong_date(item: Mapping[str, Any]) -> bool:
    document_date = date_or_none(item.get("documentDate"))
    period_start = date_or_none(item.get("periodFrom"))
    period_end = date_or_none(item.get("periodTo"))
    return bool(
        document_date
        and period_start
        and period_end
        and not period_start <= document_date <= period_end
    )


def _ozon_document_control_row(
    *,
    kind: str,
    label: str,
    period_start: str,
    period_end: str,
    ozon_amount: Decimal | None,
    onec_amount: Decimal | None,
    delta: Decimal | None,
    documents: list[Mapping[str, Any]],
    status: str,
) -> dict[str, Any]:
    document_labels = [
        " · ".join(
            value
            for value in (
                str(item.get("documentNumber") or "").strip(),
                str(item.get("documentDate") or "").strip(),
            )
            if value
        )
        for item in documents
    ]
    return {
        "kind": kind,
        "label": label,
        "periodStart": period_start,
        "periodEnd": period_end,
        "ozonAmount": _json_number(ozon_amount),
        "onecAmount": _json_number(onec_amount),
        "deltaAmount": _json_number(delta),
        "documentCount": len(documents),
        "documents": [label for label in document_labels if label],
        "status": status,
        "problem": _ozon_document_control_problem(status),
        "action": _ozon_document_control_action(status, label, period_end),
    }


def _ozon_document_control_problem(status: str) -> str:
    return {
        "matched": "Сумма и дата подтверждены.",
        "missing_ozon_source": "Не загружен контрольный отчет Ozon API.",
        "missing_in_1c": "В Ozon есть сумма, но первичный документ 1C не найден.",
        "not_posted": "Документ 1C найден, но не проведен.",
        "wrong_date": "Документ 1C относится к периоду, но проведен не той датой.",
        "amount_mismatch": "Документ 1C найден, но сумма не совпадает с Ozon API.",
    }.get(status, "Нужно проверить первичный документ.")


def _ozon_document_control_action(status: str, label: str, period_end: str) -> str:
    if status == "matched":
        return "Ничего исправлять не нужно."
    if status == "missing_ozon_source":
        return "Повторно загрузить Ozon + 1C и проверить доступ к отчету Ozon."
    if status == "missing_in_1c":
        return f"Создать и провести в 1C документ «{label}» за выбранный период."
    if status == "not_posted":
        return f"Провести документ «{label}» в 1C и повторить проверку."
    if status == "wrong_date":
        suffix = f" {period_end}" if period_end else " окончания периода"
        return f"Исправить дату документа «{label}» в 1C на дату{suffix}."
    return f"Сверить сумму документа «{label}» с отчетом Ozon и перепровести."


def _ozon_mart_reconciliation_totals_payload(
    mart: Mapping[str, Any],
    direct_control: Mapping[str, Decimal | None],
) -> dict[str, Any]:
    totals = mart.get("totals") or {}
    direct_quantity = _decimal_from_payload_value(direct_control.get("quantity"))
    direct_revenue = _decimal_from_payload_value(direct_control.get("revenue"))
    direct_cogs = _decimal_from_payload_value(direct_control.get("cogs"))
    sku_revenue = _decimal_from_payload_value(totals.get("onecRevenue"))
    sku_cogs = _decimal_from_payload_value(totals.get("cogs"))
    sku_profit = _decimal_from_payload_value(
        totals.get("profitBeforeTax") or totals.get("profit")
    )
    revenue_delta = (
        direct_revenue - sku_revenue
        if direct_revenue is not None and sku_revenue is not None
        else None
    )
    cogs_delta = (
        direct_cogs - sku_cogs
        if direct_cogs is not None and sku_cogs is not None
        else None
    )
    return {
        "basis": "onec_sales_register",
        "quantity": _json_number(direct_quantity),
        "onecRevenue": _json_number(direct_revenue),
        "cogs": _json_number(direct_cogs),
        "revenueStatus": (
            "available" if direct_revenue is not None else "not_available"
        ),
        "cogsStatus": "available" if direct_cogs is not None else "not_available",
        "revenueDeltaVsSku": _json_number(revenue_delta),
        "cogsDeltaVsSku": _json_number(cogs_delta),
        "profitDeltaVsSku": _json_number(
            revenue_delta - cogs_delta
            if sku_profit is not None
            and revenue_delta is not None
            and cogs_delta is not None
            else None
        ),
    }


def _apply_direct_onec_totals_to_ozon_mart(
    mart: dict[str, Any],
    direct_control: Mapping[str, Decimal | None],
) -> None:
    """Align aggregate P&L to the direct 1C register without faking SKU links."""

    totals = mart.get("totals") or {}
    sku_revenue = _decimal_from_payload_value(totals.get("onecRevenue"))
    sku_cogs = _decimal_from_payload_value(totals.get("cogs"))
    direct_revenue = _decimal_from_payload_value(direct_control.get("revenue"))
    direct_cogs = _decimal_from_payload_value(direct_control.get("cogs"))
    if (
        sku_revenue is None
        or sku_cogs is None
        or direct_revenue is None
        or direct_cogs is None
    ):
        return

    sku_profit = _decimal_from_payload_value(
        totals.get("profitBeforeTax") or totals.get("profit")
    )
    revenue_delta = direct_revenue - sku_revenue
    cogs_delta = direct_cogs - sku_cogs
    direct_profit = (
        sku_profit + revenue_delta - cogs_delta if sku_profit is not None else None
    )
    totals["onecRevenue"] = _json_number(direct_revenue)
    totals["cogs"] = _json_number(direct_cogs)
    if direct_profit is not None:
        totals["profit"] = _json_number(direct_profit)
        totals["profitBeforeTax"] = _json_number(direct_profit)
        totals["margin"] = _json_number(
            direct_profit / direct_revenue if direct_revenue else None
        )
        totals["marginBeforeTax"] = totals["margin"]
    mart["totals"] = totals
    if not mart.get("excludedOpenPeriods") and not mart.get(
        "excludedIncompletePeriods"
    ):
        closed_totals = dict(mart.get("closedPeriodTotals") or {})
        closed_totals["onecRevenue"] = _json_number(direct_revenue)
        closed_totals["cogs"] = _json_number(direct_cogs)
        if direct_profit is not None:
            closed_totals["profit"] = _json_number(direct_profit)
            closed_totals["profitBeforeTax"] = _json_number(direct_profit)
            closed_totals["margin"] = _json_number(
                direct_profit / direct_revenue if direct_revenue else None
            )
            closed_totals["marginBeforeTax"] = closed_totals["margin"]
        mart["closedPeriodTotals"] = closed_totals
    mart["pnlScope"] = "onec_sales_register_including_additional_documents"
    mart["pnlScopeNote"] = (
        "Итоги включают дополнительные документы 1C, в том числе выкупы; "
        "без подтвержденной связи они не распределяются по SKU."
    )

    labels = {
        "revenue": "Выручка 1C Ozon (включая выкупы)",
        "cogs": "Себестоимость 1C (включая выкупы; НДС не выделен)",
        "profit": "Прибыль до налогов (включая выкупы)",
    }
    article_rows: list[dict[str, Any]] = []
    for source in mart.get("articleRows") or []:
        item = dict(source)
        article_id = str(item.get("articleId") or "")
        if article_id == "revenue":
            item.update(
                label=labels[article_id],
                amount=_json_number(direct_revenue),
                effectAmount=_json_number(direct_revenue),
            )
        elif article_id == "cogs":
            item.update(
                label=labels[article_id],
                amount=_json_number(direct_cogs),
                effectAmount=_json_number(-direct_cogs),
            )
        elif article_id == "profit" and direct_profit is not None:
            item.update(
                label=labels[article_id],
                amount=_json_number(direct_profit),
                effectAmount=_json_number(direct_profit),
            )
        article_rows.append(item)
    mart["articleRows"] = article_rows


def _ozon_cash_flow_expenses_payload(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    item_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    gross_expense = Decimal("0")
    positive_adjustment = Decimal("0")
    period_count = 0
    expense_categories = {"return", "services", "rfbs", "others"}
    for detail in _iter_ozon_cash_flow_details(rows):
        detail_period = _ozon_cash_flow_detail_period(detail)
        if not _periods_overlap(
            detail_period,
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        period_count += 1
        for category in ("delivery", "return", "services", "rfbs", "others"):
            category_payload = detail.get(category)
            if not isinstance(category_payload, dict):
                continue
            amount = _decimal_from_payload_value(category_payload.get("total"))
            if amount is None:
                continue
            category_totals[category] += amount
            if category in expense_categories:
                if amount < 0:
                    gross_expense += abs(amount)
                elif amount > 0:
                    positive_adjustment += amount
            items = category_payload.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_amount = _decimal_from_payload_value(
                        item.get("price") or item.get("amount") or item.get("total")
                    )
                    if item_amount is None:
                        continue
                    name = _safe_payload_text(
                        item,
                        "name",
                        "operation_type",
                        "type",
                    )
                    item_totals[(category, name or category)] += item_amount
    expense_amount = max(gross_expense - positive_adjustment, Decimal("0"))
    status = "loaded" if period_count else "missing"
    category_rows = _ozon_expense_category_rows(category_totals)
    return {
        "status": status,
        "message": (
            "Расходы Ozon взяты из отчёта Seller API о движении средств "
            "за выбранный период."
            if status == "loaded"
            else "Нет расходов Ozon по движению средств за выбранный период."
        ),
        "sourceType": OZON_DIAGNOSTIC_FINANCE_SOURCE,
        "basis": "ozon_cash_flow_statement",
        "periodCount": period_count,
        "summary": {
            "expenseAmount": _json_number(expense_amount),
            "grossExpenseAmount": _json_number(gross_expense),
            "positiveAdjustmentAmount": _json_number(positive_adjustment),
            "signedNetAmount": _json_number(-expense_amount),
            "deliveryAmount": _json_number(category_totals["delivery"]),
            "returnAmount": _json_number(category_totals["return"]),
            "servicesAmount": _json_number(category_totals["services"]),
            "rfbsAmount": _json_number(category_totals["rfbs"]),
            "othersAmount": _json_number(category_totals["others"]),
        },
        "categoryRows": category_rows,
        "topItems": [
            {
                "category": category,
                "categoryLabel": _ozon_expense_category_label(category),
                "name": name,
                "amount": _json_number(amount),
                "expenseEffectAmount": _json_number(
                    _ozon_expense_effect(category, amount)
                ),
                "includedInExpense": category
                in {"return", "services", "rfbs", "others"},
            }
            for (category, name), amount in sorted(
                item_totals.items(),
                key=lambda item: abs(item[1]),
                reverse=True,
            )[:10]
        ],
    }


def _ozon_mutual_settlement_expenses_payload(
    rows: list[SourceSnapshotRow],
) -> dict[str, Any]:
    expense_names = {
        "Акт выполненных работ",
        "Отчет о перевыставлении услуг",
    }
    item_totals: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {
            "debit": Decimal("0"),
            "credit": Decimal("0"),
            "expense": Decimal("0"),
            "rows": 0,
        }
    )
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    expense_amount = Decimal("0")
    for row in rows:
        payload = row.row_payload or {}
        name = _safe_payload_text(payload, "Наименование", "name")
        if not name:
            continue
        debit = _decimal_from_payload_value(
            payload.get("Сумма дебиторской задолженности, RUR")
        ) or Decimal("0")
        credit = _decimal_from_payload_value(
            payload.get("Сумма кредиторской задолженности, RUR")
        ) or Decimal("0")
        item = item_totals[name]
        item["debit"] = Decimal(item["debit"]) + debit
        item["credit"] = Decimal(item["credit"]) + credit
        item["rows"] = int(item["rows"]) + 1
        total_debit += debit
        total_credit += credit
        if name in expense_names and debit > 0:
            item["expense"] = Decimal(item["expense"]) + debit
            expense_amount += debit

    status = "loaded" if rows else "missing"
    category_rows = [
        {
            "category": "mutual_settlement",
            "label": name,
            "signedAmount": _json_number(
                Decimal(values["debit"]) - Decimal(values["credit"])
            ),
            "expenseEffectAmount": _json_number(values["expense"]),
            "includedInExpense": name in expense_names,
            "note": (
                "Входит в прямые расходы по документам Ozon."
                if name in expense_names
                else "Справочно: взаиморасчеты, выплаты, сальдо или выкуп."
            ),
            "debitAmount": _json_number(values["debit"]),
            "creditAmount": _json_number(values["credit"]),
            "rowCount": int(values["rows"]),
        }
        for name, values in sorted(
            item_totals.items(),
            key=lambda item: abs(
                Decimal(item[1]["debit"]) - Decimal(item[1]["credit"])
            ),
            reverse=True,
        )
    ]
    return {
        "status": status,
        "message": (
            "Расходы Ozon взяты из отчета взаиморасчетов за выбранный период."
            if status == "loaded"
            else "Нет отчета взаиморасчетов Ozon за выбранный период."
        ),
        "sourceType": OZON_MUTUAL_SETTLEMENT_SOURCE,
        "basis": "ozon_mutual_settlement_expense_documents",
        "periodCount": len(rows),
        "summary": {
            "expenseAmount": _json_number(expense_amount),
            "debitAmount": _json_number(total_debit),
            "creditAmount": _json_number(total_credit),
            "signedNetAmount": _json_number(total_credit - total_debit),
        },
        "categoryRows": category_rows,
        "topItems": [],
    }


def _ozon_expense_category_rows(
    category_totals: Mapping[str, Decimal],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in ("services", "return", "rfbs", "others", "delivery"):
        amount = category_totals.get(category, Decimal("0"))
        if not amount:
            continue
        included = category in {"services", "return", "rfbs", "others"}
        rows.append(
            {
                "category": category,
                "label": _ozon_expense_category_label(category),
                "signedAmount": _json_number(amount),
                "expenseEffectAmount": _json_number(
                    _ozon_expense_effect(category, amount)
                ),
                "includedInExpense": included,
                "note": (
                    "Входит в расходы Ozon API."
                    if included
                    else "Не входит в расходы V1: это отдельный денежный блок."
                ),
            }
        )
    return rows


def _ozon_expense_category_label(category: str) -> str:
    return {
        "services": "Ozon услуги и комиссии",
        "return": "Ozon возвраты и корректировки",
        "rfbs": "Ozon rFBS",
        "others": "Ozon прочие корректировки",
        "delivery": "Ozon доставка / денежный блок",
    }.get(category, category)


def _ozon_expense_effect(category: str, amount: Decimal) -> Decimal | None:
    if category not in {"services", "return", "rfbs", "others"}:
        return None
    if amount < 0:
        return abs(amount)
    return -amount


def _iter_ozon_cash_flow_details(
    rows: list[SourceSnapshotRow],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = row.row_payload or {}
        details = payload.get("details")
        if isinstance(details, list):
            result.extend(item for item in details if isinstance(item, dict))
            continue
        if isinstance(details, dict):
            result.append(details)
            continue
        if isinstance(payload.get("period"), dict):
            result.append(payload)
    return result


def _ozon_cash_flow_detail_period(
    detail: dict[str, Any],
) -> tuple[date, date] | None:
    period = detail.get("period")
    if not isinstance(period, dict):
        return None
    period_start = date_or_none(period.get("begin"))
    period_end = date_or_none(period.get("end")) or period_start
    if period_start is None or period_end is None:
        return None
    return period_start, period_end


def _periods_overlap(
    item_period: tuple[date, date] | None,
    *,
    period_start: date | None,
    period_end: date | None,
) -> bool:
    if period_start is None and period_end is None:
        return True
    if item_period is None:
        return False
    requested_start = period_start or date.min
    requested_end = period_end or date.max
    return item_period[0] <= requested_end and item_period[1] >= requested_start


def _onec_ozon_expense_control_payload(
    *,
    incoming_invoice_rows: list[SourceSnapshotRow],
    supplier_receipt_rows: list[SourceSnapshotRow],
    supplier_receipt_expense_rows: list[SourceSnapshotRow],
    counterparty_ids: list[Any],
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    supplier_payload = _onec_supplier_receipt_expense_payload(
        supplier_receipt_rows=supplier_receipt_rows,
        supplier_receipt_expense_rows=supplier_receipt_expense_rows,
        counterparty_ids=counterparty_ids,
        period_start=period_start,
        period_end=period_end,
    )
    if supplier_payload["status"] == "loaded":
        return supplier_payload
    incoming_payload = _onec_incoming_invoice_expense_payload(
        incoming_invoice_rows,
        counterparty_ids=counterparty_ids,
        period_start=period_start,
        period_end=period_end,
    )
    if incoming_payload["status"] == "loaded":
        return incoming_payload
    return supplier_payload


def _onec_supplier_receipt_expense_payload(
    *,
    supplier_receipt_rows: list[SourceSnapshotRow],
    supplier_receipt_expense_rows: list[SourceSnapshotRow],
    counterparty_ids: list[Any],
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    counterparty_set = {str(item) for item in counterparty_ids if str(item or "")}
    receipts: dict[str, dict[str, Any]] = {}
    for row in supplier_receipt_rows:
        payload = row.row_payload or {}
        ref_key = _safe_payload_text(payload, "Ref_Key")
        if not ref_key or bool(payload.get("DeletionMark")):
            continue
        document_date = _payload_date_or_none(
            _safe_payload_text(payload, "Date", "Дата")
        )
        if not _date_in_period(
            document_date,
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        counterparty_id = _safe_payload_text(payload, "Контрагент_Key", "counterparty")
        if (
            counterparty_set
            and counterparty_id
            and counterparty_id not in counterparty_set
        ):
            continue
        receipts[ref_key] = payload
    amount = Decimal("0")
    row_count = 0
    for row in supplier_receipt_expense_rows:
        payload = row.row_payload or {}
        ref_key = _safe_payload_text(payload, "Ref_Key")
        if ref_key not in receipts:
            continue
        line_amount = _first_payload_decimal(payload, "Всего", "Сумма", "amount")
        if line_amount is None:
            continue
        amount += abs(line_amount)
        row_count += 1
    return {
        "status": "loaded" if row_count else "missing",
        "sourceType": "onec_supplier_receipt_expenses",
        "basis": "1c_supplier_receipt_expense_lines",
        "rowCount": row_count,
        "amount": _json_number(amount),
        "serviceAmount": _json_number(amount),
        "returnAmount": 0.0,
        "documentRows": [],
        "message": (
            "1C услуги маркетплейса найдены в поступлениях/УПД."
            if row_count
            else "1C услуги маркетплейса не загружены из поступлений/УПД."
        ),
    }


def _onec_incoming_invoice_expense_payload(
    rows: list[SourceSnapshotRow],
    *,
    counterparty_ids: list[Any],
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    counterparty_set = {str(item) for item in counterparty_ids if str(item or "")}
    service_amount = Decimal("0")
    return_amount = Decimal("0")
    row_count = 0
    operation_counts: dict[str, int] = defaultdict(int)
    operation_amounts: dict[str, Decimal] = defaultdict(Decimal)
    document_rows: list[dict[str, Any]] = []
    for row in rows:
        payload = row.row_payload or {}
        if bool(payload.get("DeletionMark")):
            continue
        document_date = _payload_date_or_none(
            _safe_payload_text(payload, "Date", "Дата")
        )
        if not _date_in_period(
            document_date,
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        counterparty_id = _safe_payload_text(payload, "Контрагент_Key", "counterparty")
        if (
            counterparty_set
            and counterparty_id
            and counterparty_id not in counterparty_set
        ):
            continue
        amount = _first_payload_decimal(
            payload,
            "СуммаДокумента",
            "Сумма",
            "Amount",
            "amount",
        )
        if amount is None:
            continue
        operation = _safe_payload_text(payload, "ВидОперации", "Операция")
        operation_label = operation or "unknown"
        document_number = _safe_payload_text(payload, "Number", "Номер")
        included = "возврат" not in operation.casefold()
        operation_counts[operation_label] += 1
        operation_amounts[operation_label] += abs(amount)
        if not included:
            return_amount += abs(amount)
        else:
            service_amount += abs(amount)
        document_label_parts = [
            operation_label if operation_label != "unknown" else "1C документ"
        ]
        if document_number:
            document_label_parts.append(f"№ {document_number}")
        if document_date:
            document_label_parts.append(document_date.strftime("%d.%m.%Y"))
        document_rows.append(
            {
                "label": " · ".join(document_label_parts),
                "date": document_date.isoformat() if document_date else "",
                "number": document_number,
                "operation": operation_label,
                "amount": _json_number(abs(amount)),
                "includedInControl": included,
                "note": (
                    "Входит в 1C контроль расходов."
                    if included
                    else "Показано отдельно, не прибавляется к расходам V1."
                ),
            }
        )
        row_count += 1
    total_amount = service_amount + return_amount
    return {
        "status": "loaded" if row_count else "missing",
        "sourceType": OZON_ONEC_INCOMING_INVOICE_SOURCE,
        "basis": "1c_incoming_invoices",
        "rowCount": row_count,
        "amount": _json_number(service_amount),
        "serviceAmount": _json_number(service_amount),
        "returnAmount": _json_number(return_amount),
        "totalAmount": _json_number(total_amount),
        "operations": dict(sorted(operation_counts.items())),
        "documentRows": sorted(
            document_rows,
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("number") or ""),
                str(item.get("operation") or ""),
            ),
        ),
        "operationRows": [
            {
                "operation": operation,
                "amount": _json_number(amount),
                "rowCount": operation_counts.get(operation, 0),
                "includedInControl": "возврат" not in operation.casefold(),
                "note": (
                    "Входит в 1C контроль расходов."
                    if "возврат" not in operation.casefold()
                    else "Показано отдельно, не прибавляется к расходам V1."
                ),
            }
            for operation, amount in sorted(operation_amounts.items())
        ],
        "message": (
            "1C приходные накладные Ozon найдены для контроля расходов."
            if row_count
            else "1C приходные накладные Ozon не загружены для контроля расходов."
        ),
    }


def _date_in_period(
    value: date | None,
    *,
    period_start: date | None,
    period_end: date | None,
) -> bool:
    if value is None:
        return period_start is None and period_end is None
    if period_start is not None and value < period_start:
        return False
    return not (period_end is not None and value > period_end)


def _ozon_expense_reconciliation_payload(
    ozon_expenses: dict[str, Any],
    onec_expenses: dict[str, Any],
) -> dict[str, Any]:
    ozon_amount = _decimal_from_payload_value(
        (ozon_expenses.get("summary") or {}).get("expenseAmount")
    )
    onec_amount = _decimal_from_payload_value(onec_expenses.get("amount"))
    if ozon_amount is None:
        return {
            "status": "missing",
            "message": "Нет расходов Ozon API для сверки с 1C.",
            "ozonExpenseAmount": None,
            "onecExpenseAmount": _json_number(onec_amount),
            "deltaAmount": None,
            "detailRows": _ozon_expense_reconciliation_detail_rows(
                ozon_expenses,
                onec_expenses,
                ozon_amount=Decimal("0"),
                onec_amount=onec_amount,
                delta=None,
            ),
            "articleRows": _ozon_expense_article_reconciliation_rows(
                ozon_expenses,
                onec_expenses,
                ozon_amount=Decimal("0"),
                onec_amount=onec_amount,
                delta=None,
            ),
            "ozon": ozon_expenses,
            "onec": onec_expenses,
        }
    if onec_amount is None or onec_expenses.get("status") != "loaded":
        return {
            "status": "review",
            "message": (
                "Расходы Ozon API загружены, но 1C-контроль услуг/приходных "
                "не найден или не разнесен."
            ),
            "ozonExpenseAmount": _json_number(ozon_amount),
            "onecExpenseAmount": None,
            "deltaAmount": None,
            "detailRows": _ozon_expense_reconciliation_detail_rows(
                ozon_expenses,
                onec_expenses,
                ozon_amount=ozon_amount,
                onec_amount=None,
                delta=None,
            ),
            "articleRows": _ozon_expense_article_reconciliation_rows(
                ozon_expenses,
                onec_expenses,
                ozon_amount=ozon_amount,
                onec_amount=None,
                delta=None,
            ),
            "ozon": ozon_expenses,
            "onec": onec_expenses,
        }
    control_only_matches = _ozon_control_only_expense_matches(
        ozon_expenses,
        onec_expenses,
    )
    control_only_matched_amount = sum(
        (Decimal(str(item["amount"])) for item in control_only_matches),
        Decimal("0"),
    )
    comparable_onec_amount = onec_amount - control_only_matched_amount
    delta = comparable_onec_amount - ozon_amount
    tolerance = max(abs(ozon_amount) * Decimal("0.0005"), Decimal("1"))
    detail_rows = _ozon_expense_reconciliation_detail_rows(
        ozon_expenses,
        onec_expenses,
        ozon_amount=ozon_amount,
        onec_amount=comparable_onec_amount,
        delta=delta,
    )
    article_rows = _ozon_expense_article_reconciliation_rows(
        ozon_expenses,
        onec_expenses,
        ozon_amount=ozon_amount,
        onec_amount=comparable_onec_amount,
        delta=delta,
    )
    has_unmatched_article = any(
        item.get("kind") in {"onec_unmatched", "ozon_unmatched"}
        for item in article_rows
    )
    status = (
        "matched"
        if not has_unmatched_article and _decimal_close(delta, Decimal("0"), tolerance)
        else "review"
    )
    return {
        "status": status,
        "message": (
            "Расходы Ozon API сходятся с 1C-контролем."
            if status == "matched" and _decimal_close(delta, Decimal("0"), Decimal("1"))
            else "Расходы Ozon API сходятся с 1C-контролем с остаточной дельтой."
            if status == "matched"
            else (
                "1C-контроль расходов найден, но есть статьи без пары "
                "в Ozon API или 1C."
            )
            if has_unmatched_article
            else "1C-контроль расходов найден, но сумма отличается от Ozon API."
        ),
        "ozonExpenseAmount": _json_number(ozon_amount),
        "onecExpenseAmount": _json_number(onec_amount),
        "onecComparableExpenseAmount": _json_number(comparable_onec_amount),
        "controlOnlyMatchedAmount": _json_number(control_only_matched_amount),
        "deltaAmount": _json_number(delta),
        "detailRows": detail_rows,
        "articleRows": article_rows,
        "ozon": ozon_expenses,
        "onec": onec_expenses,
    }


def _ozon_control_only_expense_matches(
    ozon_expenses: Mapping[str, Any],
    onec_expenses: Mapping[str, Any],
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for item in _safe_payload_list(ozon_expenses.get("categoryRows")):
        if not isinstance(item, Mapping) or item.get("includedInExpense"):
            continue
        if str(item.get("label") or "").strip().casefold() != "отчет о реализации":
            continue
        amount = _decimal_from_payload_value(item.get("debitAmount"))
        if amount is None or amount <= 0:
            continue
        controls.append(
            {
                "label": item.get("label") or "Отчет о реализации",
                "amount": amount,
            }
        )
    documents: list[dict[str, Any]] = []
    for item in _safe_payload_list(onec_expenses.get("documentRows")):
        if not isinstance(item, Mapping) or not item.get("includedInControl"):
            continue
        amount = _decimal_from_payload_value(item.get("amount"))
        if amount is None:
            continue
        documents.append(
            {
                "label": item.get("label") or "1C документ",
                "amount": amount,
            }
        )
    matches: list[dict[str, Any]] = []
    used_document_indexes: set[int] = set()
    tolerance = Decimal("1")
    for control in controls:
        match_index: int | None = None
        match_diff: Decimal | None = None
        for index, document in enumerate(documents):
            if index in used_document_indexes:
                continue
            diff = abs(Decimal(document["amount"]) - Decimal(control["amount"]))
            if diff <= tolerance and (match_diff is None or diff < match_diff):
                match_index = index
                match_diff = diff
        if match_index is None:
            continue
        used_document_indexes.add(match_index)
        document = documents[match_index]
        matches.append(
            {
                "label": control["label"],
                "onecLabel": document["label"],
                "amount": Decimal(control["amount"]),
            }
        )
    return matches


def _ozon_expense_article_reconciliation_rows(
    ozon_expenses: Mapping[str, Any],
    onec_expenses: Mapping[str, Any],
    *,
    ozon_amount: Decimal,
    onec_amount: Decimal | None,
    delta: Decimal | None,
) -> list[dict[str, Any]]:
    ozon_rows: list[dict[str, Any]] = []
    for item in _safe_payload_list(ozon_expenses.get("categoryRows")):
        if not isinstance(item, dict) or not item.get("includedInExpense"):
            continue
        amount = _decimal_from_payload_value(item.get("expenseEffectAmount"))
        if amount is None:
            continue
        ozon_rows.append(
            {
                "label": item.get("label") or item.get("category") or "Ozon",
                "amount": amount,
                "rowCount": item.get("rowCount"),
            }
        )

    onec_rows: list[dict[str, Any]] = []
    for item in _safe_payload_list(onec_expenses.get("documentRows")):
        if not isinstance(item, dict) or not item.get("includedInControl"):
            continue
        amount = _decimal_from_payload_value(item.get("amount"))
        if amount is None:
            continue
        onec_rows.append(
            {
                "label": item.get("label") or item.get("operation") or "1C документ",
                "amount": amount,
                "rowCount": 1,
            }
        )
    if not onec_rows:
        for item in _safe_payload_list(onec_expenses.get("operationRows")):
            if not isinstance(item, dict) or not item.get("includedInControl"):
                continue
            amount = _decimal_from_payload_value(item.get("amount"))
            if amount is None:
                continue
            onec_rows.append(
                {
                    "label": f"1C: {item.get('operation') or 'операция'}",
                    "amount": amount,
                    "rowCount": item.get("rowCount"),
                }
            )

    rows: list[dict[str, Any]] = []
    used_onec_indexes: set[int] = set()
    tolerance = Decimal("1")
    for control_match in _ozon_control_only_expense_matches(
        ozon_expenses,
        onec_expenses,
    ):
        amount = Decimal(control_match["amount"])
        match_index = next(
            (
                index
                for index, onec_item in enumerate(onec_rows)
                if index not in used_onec_indexes
                and onec_item["label"] == control_match["onecLabel"]
                and _decimal_close(
                    Decimal(onec_item["amount"]),
                    amount,
                    tolerance,
                )
            ),
            None,
        )
        if match_index is None:
            continue
        used_onec_indexes.add(match_index)
        rows.append(
            {
                "kind": "control_matched",
                "label": control_match["label"],
                "parentLabel": f"1C: {control_match['onecLabel']}",
                "ozonAmount": _json_number(amount),
                "onecAmount": _json_number(amount),
                "deltaAmount": 0.0,
                "includedInExpense": False,
                "note": (
                    "Сверено с дебетовой частью отчета о реализации; "
                    "это контроль взаиморасчётов, а не дополнительный расход "
                    "в расчёте прибылей и убытков."
                ),
            }
        )
    for ozon_item in ozon_rows:
        ozon_row_amount = Decimal(ozon_item["amount"])
        match_index: int | None = None
        match_diff: Decimal | None = None
        for index, onec_item in enumerate(onec_rows):
            if index in used_onec_indexes:
                continue
            diff = abs(Decimal(onec_item["amount"]) - ozon_row_amount)
            if diff <= tolerance and (match_diff is None or diff < match_diff):
                match_index = index
                match_diff = diff
        if match_index is None:
            rows.append(
                {
                    "kind": "ozon_unmatched",
                    "label": ozon_item["label"],
                    "ozonAmount": _json_number(ozon_row_amount),
                    "onecAmount": 0.0,
                    "deltaAmount": _json_number(-ozon_row_amount),
                    "includedInExpense": True,
                    "note": "Статья есть в Ozon API, пары в 1C контроле нет.",
                }
            )
            continue
        used_onec_indexes.add(match_index)
        onec_item = onec_rows[match_index]
        onec_row_amount = Decimal(onec_item["amount"])
        row_delta = onec_row_amount - ozon_row_amount
        rows.append(
            {
                "kind": "article_matched",
                "label": ozon_item["label"],
                "parentLabel": f"1C: {onec_item['label']}",
                "ozonAmount": _json_number(ozon_row_amount),
                "onecAmount": _json_number(onec_row_amount),
                "deltaAmount": _json_number(row_delta),
                "includedInExpense": True,
                "note": (
                    "Сверено по сумме документа."
                    if _decimal_close(row_delta, Decimal("0"), tolerance)
                    else "Сумма 1C отличается от Ozon API."
                ),
            }
        )

    for index, onec_item in enumerate(onec_rows):
        if index in used_onec_indexes:
            continue
        onec_row_amount = Decimal(onec_item["amount"])
        rows.append(
            {
                "kind": "onec_unmatched",
                "label": f"1C без пары в Ozon: {onec_item['label']}",
                "ozonAmount": 0.0,
                "onecAmount": _json_number(onec_row_amount),
                "deltaAmount": _json_number(onec_row_amount),
                "includedInExpense": True,
                "note": (
                    "Документ есть в 1C контроле, но нет пары "
                    "в Ozon API расходах периода. Проверьте соседний месяц "
                    "отчёт о взаиморасчётах за соседний месяц или "
                    "отдельный отчёт услуг Ozon."
                ),
            }
        )

    if rows or onec_amount is not None or ozon_amount:
        rows.append(
            {
                "kind": "total",
                "label": "Итого дельта расходов",
                "ozonAmount": _json_number(ozon_amount),
                "onecAmount": _json_number(onec_amount),
                "deltaAmount": _json_number(delta),
                "includedInExpense": True,
                "note": "Дельта = 1C контроль минус Ozon API.",
            }
        )
    return rows


def _ozon_article_drilldown_payload(
    ozon_mart: Mapping[str, Any],
    expense_reconciliation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        dict(item)
        for item in _safe_payload_list(ozon_mart.get("articleDrilldown"))
        if isinstance(item, Mapping)
    ]
    rows.extend(_ozon_expense_attribution_control_rows(ozon_mart))
    for item in _safe_payload_list(expense_reconciliation.get("articleRows")):
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        label = str(item.get("label") or "Статья сверки Ozon").strip()
        rows.append(
            {
                "kind": f"reconciliation_{kind or 'row'}",
                "articleId": _ozon_reconciliation_article_id(label),
                "label": label,
                "group": "reconciliation",
                "sourceLabel": item.get("parentLabel") or "",
                "sourceRowId": "",
                "martRowId": "",
                "offerId": "",
                "productId": "",
                "sku": "",
                "barcode": "",
                "productName": "",
                "onecItemId": "",
                "onecName": "",
                "amount": item.get("onecAmount") or item.get("ozonAmount"),
                "effectAmount": item.get("deltaAmount"),
                "ozonAmount": item.get("ozonAmount"),
                "onecAmount": item.get("onecAmount"),
                "deltaAmount": item.get("deltaAmount"),
                "includedInSkuProfit": False,
                "basis": "ozon_1c_expense_reconciliation",
                "expenseBasis": "ozon_1c_expense_reconciliation",
                "attributionType": "reconciliation",
                "allocationShare": None,
                "qualityStatus": "review" if "unmatched" in kind else "ready",
                "expenseStatus": kind,
                "status": "review" if "unmatched" in kind else "matched",
                "note": item.get("note") or "",
                "actionText": _ozon_reconciliation_action_text(kind),
            }
        )
    return rows


def _ozon_expense_attribution_control_rows(
    ozon_mart: Mapping[str, Any],
) -> list[dict[str, Any]]:
    attribution = ozon_mart.get("expenseAttribution")
    if not isinstance(attribution, Mapping):
        return []
    status = str(attribution.get("status") or "")
    if not status or status == "not_applicable":
        return []
    period_amount = attribution.get("periodExpenseAmount")
    sku_amount = attribution.get("skuAttributedExpenseAmount")
    residual_amount = attribution.get("unattributedExpenseAmount")
    allocated_amount = attribution.get("allocatedUnattributedExpenseAmount")
    over_amount = attribution.get("overAttributedExpenseAmount")
    delta_amount = attribution.get("periodExpenseDeltaAmount")
    tone_status = (
        "review"
        if status in {"sku_detail_above_period", "not_allocated"}
        else "matched"
    )
    return [
        {
            "kind": "period_expense_control",
            "articleId": "period_expense_control",
            "label": "Контроль детализации расходов Ozon ↔ отчёт о взаиморасчётах",
            "group": "reconciliation",
            "sourceLabel": attribution.get("basis") or "",
            "sourceRowId": "",
            "martRowId": "",
            "offerId": "",
            "productId": "",
            "sku": "",
            "barcode": "",
            "productName": "",
            "onecItemId": "",
            "onecName": "",
            "amount": allocated_amount,
            "effectAmount": delta_amount,
            "periodExpenseAmount": period_amount,
            "skuAttributedExpenseAmount": sku_amount,
            "unattributedExpenseAmount": residual_amount,
            "allocatedUnattributedExpenseAmount": allocated_amount,
            "overAttributedExpenseAmount": over_amount,
            "roundingDeltaAmount": attribution.get("roundingDeltaAmount"),
            "periodExpenseDeltaAmount": delta_amount,
            "includedInSkuProfit": False,
            "basis": attribution.get("basis") or "",
            "expenseBasis": attribution.get("basis") or "",
            "attributionType": status,
            "allocationShare": None,
            "expenseAllocationBasis": attribution.get("allocationBasis") or "",
            "qualityStatus": tone_status,
            "expenseStatus": status,
            "status": tone_status,
            "note": attribution.get("message") or "",
            "actionText": _ozon_expense_attribution_action_text(status),
        }
    ]


def _ozon_expense_attribution_action_text(status: str) -> str:
    if status == "mixed_sku_and_period_unattributed":
        return "Проверить распределенный остаток периода по статьям Ozon."
    if status == "allocated_period_expense":
        return (
            "Проверить, можно ли получить детализацию расходов по SKU "
            "вместо резервного расчёта."
        )
    if status == "sku_detail_above_period":
        return (
            "Проверить период отчёта о взаиморасчётах и состав детализации; "
            "отрицательный "
            "остаток не распределен."
        )
    if status == "sku_direct":
        return "Действие не требуется: детализация по SKU покрывает расходы периода."
    return "Проверить базу расходов Ozon."


def _ozon_reconciliation_article_id(label: str) -> str:
    text = label.casefold()
    if "комисс" in text or "вознагражден" in text:
        return "commission"
    if "перевыстав" in text:
        return "partner_services"
    if "акт выполненных работ" in text or "услуг" in text or "услуги" in text:
        return "services"
    if "логист" in text or "достав" in text:
        return "logistics"
    if "хран" in text or "размещ" in text:
        return "storage"
    if "итого" in text:
        return "total"
    return "other"


def _ozon_reconciliation_action_text(kind: str) -> str:
    if kind == "onec_unmatched":
        return (
            "Проверить отчёт о взаиморасчётах за соседний месяц "
            "или отдельный отчёт услуг Ozon."
        )
    if kind == "ozon_unmatched":
        return "Проверить, почему статья Ozon API не разнесена в 1C."
    if kind == "article_matched":
        return "Действие не требуется: статья сверена по сумме."
    if kind == "control_matched":
        return "Действие не требуется: контрольная сумма объяснена."
    return "Проверить итоговую дельту сверки."


def _ozon_expense_reconciliation_detail_rows(
    ozon_expenses: Mapping[str, Any],
    onec_expenses: Mapping[str, Any],
    *,
    ozon_amount: Decimal,
    onec_amount: Decimal | None,
    delta: Decimal | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _safe_payload_list(ozon_expenses.get("categoryRows")):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "kind": "ozon_category",
                "label": item.get("label") or item.get("category") or "Ozon",
                "ozonAmount": item.get("expenseEffectAmount"),
                "ozonSignedAmount": item.get("signedAmount"),
                "onecAmount": None,
                "deltaAmount": None,
                "includedInExpense": bool(item.get("includedInExpense")),
                "note": item.get("note") or "",
            }
        )
    for item in _safe_payload_list(ozon_expenses.get("topItems")):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "kind": "ozon_item",
                "label": item.get("name") or item.get("categoryLabel") or "Ozon",
                "parentLabel": item.get("categoryLabel") or "",
                "ozonAmount": item.get("expenseEffectAmount"),
                "ozonSignedAmount": item.get("amount"),
                "onecAmount": None,
                "deltaAmount": None,
                "includedInExpense": bool(item.get("includedInExpense")),
                "note": (
                    "Крупная статья Ozon API."
                    if item.get("includedInExpense")
                    else "Справочно, не входит в расходы V1."
                ),
            }
        )
    cash_flow_control = ozon_expenses.get("cashFlowControl")
    if isinstance(cash_flow_control, Mapping):
        for item in _safe_payload_list(cash_flow_control.get("categoryRows")):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "kind": "ozon_cash_flow_control",
                    "label": item.get("label")
                    or item.get("category")
                    or "Ozon cash-flow",
                    "ozonAmount": item.get("expenseEffectAmount"),
                    "ozonSignedAmount": item.get("signedAmount"),
                    "onecAmount": None,
                    "deltaAmount": None,
                    "includedInExpense": False,
                    "note": (
                        "Движение денежных средств Ozon, справочно; "
                        "не база расчёта прибылей и убытков."
                    ),
                }
            )
    operation_rows = _safe_payload_list(onec_expenses.get("operationRows"))
    if operation_rows:
        for item in operation_rows:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "kind": "onec_operation",
                    "label": f"1C: {item.get('operation') or 'операция'}",
                    "ozonAmount": None,
                    "ozonSignedAmount": None,
                    "onecAmount": item.get("amount"),
                    "deltaAmount": None,
                    "includedInExpense": bool(item.get("includedInControl")),
                    "note": item.get("note") or "",
                }
            )
    elif onec_amount is not None:
        rows.append(
            {
                "kind": "onec_total",
                "label": "1C контроль расходов",
                "ozonAmount": None,
                "ozonSignedAmount": None,
                "onecAmount": _json_number(onec_amount),
                "deltaAmount": None,
                "includedInExpense": True,
                "note": onec_expenses.get("message") or "",
            }
        )
    rows.append(
        {
            "kind": "total",
            "label": "Итого к расчету",
            "ozonAmount": _json_number(ozon_amount),
            "ozonSignedAmount": None,
            "onecAmount": _json_number(onec_amount),
            "deltaAmount": _json_number(delta),
            "includedInExpense": True,
            "note": "Дельта = 1C контроль минус Ozon API.",
        }
    )
    return rows


def _safe_payload_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _apply_ozon_period_expenses_to_pnl(
    pnl: dict[str, Any],
    ozon_expenses: dict[str, Any],
) -> None:
    expense_amount = _decimal_from_payload_value(
        (ozon_expenses.get("summary") or {}).get("expenseAmount")
    )
    if expense_amount is None or ozon_expenses.get("status") != "loaded":
        pnl["ozonExpenses"] = ozon_expenses
        return
    totals = pnl.get("totals")
    if not isinstance(totals, dict):
        pnl["ozonExpenses"] = ozon_expenses
        return
    totals["ozonExpenses"] = _json_number(expense_amount)
    totals["expenseBasis"] = ozon_expenses.get("basis") or "ozon_expense_source"
    revenue = _decimal_from_payload_value(totals.get("revenue"))
    cogs = _decimal_from_payload_value(totals.get("onecCogs"))
    if revenue is not None:
        profit_before_cogs = revenue - expense_amount
        totals["profitBeforeCogs"] = _json_number(profit_before_cogs)
        totals["marginBeforeCogs"] = (
            _json_number(profit_before_cogs / revenue)
            if revenue != Decimal("0")
            else None
        )
        if cogs is not None:
            totals["profitAfterCogs"] = _json_number(profit_before_cogs - cogs)
    pnl["ozonExpenses"] = ozon_expenses


def _apply_ozon_period_expenses_to_mart(
    mart: dict[str, Any],
    ozon_expenses: dict[str, Any],
) -> None:
    expense_amount = _decimal_from_payload_value(
        (ozon_expenses.get("summary") or {}).get("expenseAmount")
    )
    mart["periodExpenseSource"] = ozon_expenses
    if (
        expense_amount is None
        or ozon_expenses.get("status") != "loaded"
        or ozon_expenses.get("basis") != "ozon_mutual_settlement_expense_documents"
    ):
        return
    totals = mart.get("totals")
    if not isinstance(totals, dict):
        return
    totals["periodExpenseAmount"] = _json_number(expense_amount)
    totals["periodExpenseBasis"] = ozon_expenses.get("basis") or ""


def _ozon_pnl_payload(
    rows: list[SourceSnapshotRow],
    *,
    finance_row_count: int,
    realization_rows: list[SourceSnapshotRow],
    realization_row_count: int,
    commissioner_rows: list[SourceSnapshotRow],
    sales_register_rows: list[SourceSnapshotRow],
    onec_indexes: dict[str, Any],
    onec_costs: dict[str, Decimal],
    ozon_mapping: dict[str, Any],
    period_start: date | None = None,
    period_end: date | None = None,
    unit_row_limit: int = 0,
) -> dict[str, Any]:
    totals = _ozon_pnl_zero_totals()
    onec_ozon = _ozon_onec_commissioner_payload(
        commissioner_rows,
        sales_register_rows=sales_register_rows,
        period_start=period_start,
        period_end=period_end,
    )
    has_onec_ozon = onec_ozon["status"] == "loaded"
    cogs = Decimal("0")
    realization_item_rows = 0
    ozon_realization_amount = Decimal("0")
    ozon_realization_amount_available = False
    costed_item_rows = 0
    unit_row_summary = _empty_ozon_unit_row_summary()
    unit_rows: list[dict[str, Any]] = []
    unit_row_limit = max(0, int(unit_row_limit))
    ozon_mapping_preview_index = _ozon_mapping_preview_index(ozon_mapping)
    for row in realization_rows:
        for item in _iter_ozon_realization_items(row.row_payload or {}):
            realization_item_rows += 1
            candidate = _ozon_mapping_candidate(row, item)
            checked = (
                _check_ozon_unit_mapping_candidate(
                    candidate,
                    onec_indexes=onec_indexes,
                    ozon_mapping_preview_index=ozon_mapping_preview_index,
                )
                if candidate
                else {
                    "statusCounter": "noKey",
                    "row": _ozon_mapping_preview_row(
                        {
                            "rowNumber": row.row_number,
                            "sourceRowId": row.source_row_id,
                        },
                        "no_key",
                        "",
                        {},
                        "",
                    ),
                }
            )
            preview = checked.get("row") or {}
            onec_item_id = preview.get("onecItemId") or ""
            mapping_status = str(preview.get("status") or "")
            quantity = _ozon_realization_quantity(item)
            revenue_amount = _ozon_realization_amount(item)
            if revenue_amount is not None:
                ozon_realization_amount += revenue_amount
                ozon_realization_amount_available = True
            unit_cost = (
                onec_costs.get(onec_item_id) if mapping_status == "matched" else None
            )
            cogs_amount = quantity * unit_cost if quantity > 0 and unit_cost else None
            if cogs_amount is not None:
                cogs += cogs_amount
                costed_item_rows += 1
            profit_amount = (
                revenue_amount - cogs_amount
                if has_onec_ozon
                and revenue_amount is not None
                and cogs_amount is not None
                else None
            )
            quality_status = _ozon_unit_quality_status(
                mapping_status=mapping_status,
                has_onec_ozon=has_onec_ozon,
                quantity=quantity,
                unit_cost=unit_cost,
            )
            _increment_ozon_unit_summary(unit_row_summary, quality_status)
            if len(unit_rows) < unit_row_limit:
                unit_rows.append(
                    _ozon_unit_row_payload(
                        row=row,
                        item=item,
                        preview=preview,
                        quantity=quantity,
                        revenue_amount=revenue_amount if has_onec_ozon else None,
                        revenue_basis=(
                            "ozon_realization_item_check"
                            if has_onec_ozon and revenue_amount is not None
                            else "none"
                        ),
                        unit_cost=unit_cost,
                        cogs_amount=cogs_amount,
                        profit_amount=profit_amount,
                        quality_status=quality_status,
                        period_start=period_start,
                        period_end=period_end,
                    )
                )

    if onec_ozon["status"] != "loaded":
        empty_payload = _empty_ozon_pnl_payload()
        empty_payload["status"] = (
            "partial_source" if realization_item_rows else "not_started"
        )
        empty_payload["message"] = (
            "Ozon v1: Ozon realization за период есть, но в 1C нет закрывающего "
            "отчета комиссионера Ozon. Выручку из Ozon API не подставляем."
            if realization_item_rows
            else "Ozon v1: нет 1C-выручки Ozon для выбранного периода."
        )
        empty_payload["rowCount"] = realization_row_count
        empty_payload["sourceRowsUsed"] = len(realization_rows)
        empty_payload["sourceRowsLimited"] = realization_row_count > len(
            realization_rows
        )
        empty_payload["realizationRows"] = realization_row_count
        empty_payload["ozonRealizationAmount"] = _json_number(
            ozon_realization_amount if ozon_realization_amount_available else None
        )
        empty_payload["realizationRowsUsed"] = len(realization_rows)
        empty_payload["realizationRowsLimited"] = realization_row_count > len(
            realization_rows
        )
        empty_payload["itemLevelRows"] = realization_item_rows
        empty_payload["costedItemRows"] = costed_item_rows
        empty_payload["unitRows"] = unit_rows
        empty_payload["unitRowCount"] = realization_item_rows
        empty_payload["unitRowsLimited"] = realization_item_rows > len(unit_rows)
        empty_payload["unitRowSummary"] = unit_row_summary
        empty_payload["unitRowPreviewLimit"] = unit_row_limit
        empty_payload["mappedProducts"] = int(
            (ozon_mapping.get("summary") or {}).get("matched") or 0
        )
        empty_payload["mappingReviewRows"] = (
            int((ozon_mapping.get("summary") or {}).get("missing") or 0)
            + int((ozon_mapping.get("summary") or {}).get("ambiguous") or 0)
            + int((ozon_mapping.get("summary") or {}).get("noKey") or 0)
        )
        empty_payload["onecOzon"] = onec_ozon
        empty_payload["periodFilter"] = {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
        }
        return empty_payload

    onec_revenue, revenue_basis = _ozon_onec_revenue_basis(onec_ozon)
    onec_cogs = cogs if costed_item_rows else None
    totals_payload = _ozon_pnl_totals_payload(
        totals,
        onec_cogs=onec_cogs,
        revenue_override=onec_revenue,
        revenue_basis=revenue_basis,
    )
    realization_rows_limited = realization_row_count > len(realization_rows)
    status = (
        "partial_source"
        if realization_rows_limited
        else "provisional"
        if costed_item_rows
        else "partial_source"
    )
    if costed_item_rows and realization_rows_limited:
        message = (
            "Ozon v1: выручка сверена с 1C; себестоимость пока рассчитана "
            "по предварительно показанной части товарных строк Ozon."
        )
    elif onec_ozon["status"] == "loaded":
        message = (
            "Ozon v1: выручка взята из регистра продаж 1C по контрагенту "
            f"{OZON_ONEC_COUNTERPARTY_LABEL}; отчет комиссионера показан "
            "для сверки."
        )
    elif costed_item_rows:
        message = "Ozon v1: 1C-себестоимость применена по доступным товарным строкам."
    elif not realization_item_rows:
        message = (
            "Ozon v1: для прибыли после 1C нужна товарная детализация продаж Ozon."
        )
    else:
        message = (
            "Ozon v1: товарная детализация есть, но для прибыли после 1C "
            "не хватает сопоставления или себестоимости."
        )
    mapping_summary = ozon_mapping.get("summary") or {}
    return {
        "status": status,
        "message": message,
        "basis": "onec_sales_register_and_commissioner_reports",
        "rowCount": realization_row_count,
        "cashFlowRows": 0,
        "sourceRowsUsed": len(realization_rows),
        "sourceRowsLimited": realization_rows_limited,
        "realizationRows": realization_row_count,
        "ozonRealizationAmount": _json_number(
            ozon_realization_amount if ozon_realization_amount_available else None
        ),
        "realizationRowsUsed": len(realization_rows),
        "realizationRowsLimited": realization_rows_limited,
        "itemLevelRows": realization_item_rows,
        "costedItemRows": costed_item_rows,
        "mappedProducts": int(mapping_summary.get("matched") or 0),
        "mappingReviewRows": int(mapping_summary.get("missing") or 0)
        + int(mapping_summary.get("ambiguous") or 0)
        + int(mapping_summary.get("noKey") or 0),
        "totals": totals_payload,
        "onecOzon": onec_ozon,
        "periods": [],
        "periodsLimited": False,
        "periodFilter": {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
        },
        "unitRows": unit_rows,
        "unitRowCount": realization_item_rows,
        "unitRowsLimited": realization_item_rows > len(unit_rows),
        "unitRowSummary": unit_row_summary,
        "unitRowPreviewLimit": unit_row_limit,
    }


def _ozon_pnl_zero_totals() -> dict[str, Decimal]:
    return {
        "ordersAmount": Decimal("0"),
        "returnsAmount": Decimal("0"),
        "commissionAmount": Decimal("0"),
        "deliveryAndReturnAmount": Decimal("0"),
        "servicesAmount": Decimal("0"),
    }


def _payload_decimal(payload: dict[str, Any], *keys: str) -> Decimal:
    return _first_payload_decimal(payload, *keys) or Decimal("0")


def _iter_ozon_realization_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "rows", "data", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested_item = payload.get("item")
    if isinstance(nested_item, dict):
        normalized = dict(payload)
        normalized.update(nested_item)
        delivery_commission = payload.get("delivery_commission")
        if isinstance(delivery_commission, dict) and "quantity" not in normalized:
            normalized["quantity"] = delivery_commission.get("quantity")
        return [normalized]
    return [payload]


def _ozon_realization_quantity(item: dict[str, Any]) -> Decimal:
    quantity = _payload_decimal(
        item,
        "sale_qty",
        "saleQuantity",
        "quantity",
        "qty",
        "Количество",
        "items_count",
    )
    returns = _payload_decimal(
        item,
        "return_qty",
        "returnQuantity",
        "returns_qty",
        "КоличествоВозврат",
    )
    net = quantity - abs(returns)
    return abs(net)


def _ozon_realization_amount(item: dict[str, Any]) -> Decimal | None:
    amount = _first_payload_decimal(
        item,
        "sale_amount",
        "saleAmount",
        "amount",
        "sum",
        "seller_price",
        "sellerPrice",
        "retail_price",
        "retailPrice",
        "price",
        "Всего",
        "Сумма",
    )
    if amount is not None:
        return amount
    delivery_commission = item.get("delivery_commission")
    if isinstance(delivery_commission, dict):
        return _first_payload_decimal(
            delivery_commission,
            "amount",
            "sale_amount",
            "saleAmount",
            "price",
        )
    return None


def _ozon_unit_quality_status(
    *,
    mapping_status: str,
    has_onec_ozon: bool,
    quantity: Decimal,
    unit_cost: Decimal | None,
) -> str:
    if not has_onec_ozon:
        return "missing_1c_commissioner"
    if mapping_status == "ambiguous":
        return "ambiguous_mapping"
    if mapping_status in {"missing", "no_key", ""}:
        return "missing_mapping"
    if quantity <= 0 or unit_cost is None:
        return "missing_cost"
    return "ready"


def _ozon_unit_status_reason(status: str) -> str:
    return {
        "ready": "Можно читать предварительную юнит-экономику.",
        "missing_mapping": "Аналитику нужно добавить связь Ozon -> 1C.",
        "ambiguous_mapping": "Аналитику нужно выбрать правильную номенклатуру 1C.",
        "missing_cost": "Есть сопоставление, но нет себестоимости 1C.",
        "missing_1c_commissioner": (
            "Ozon realization есть, но в 1C нет закрывающего отчета комиссионера."
        ),
        "buyout_period_only": (
            "Выкуп подтвержден агрегатом периода, но Ozon API не вернул номер отчета."
        ),
    }.get(status, "Проверить строку детализации.")


def _ozon_unit_row_payload(
    *,
    row: SourceSnapshotRow,
    item: dict[str, Any],
    preview: dict[str, Any],
    quantity: Decimal,
    revenue_amount: Decimal | None,
    revenue_basis: str,
    unit_cost: Decimal | None,
    cogs_amount: Decimal | None,
    profit_amount: Decimal | None,
    quality_status: str,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    product_name = (
        preview.get("productName")
        or _first_payload_text(item, "name", "product_name", "Название товара")
        or ""
    )
    return {
        "rowType": "realization_item",
        "periodStart": period_start.isoformat() if period_start else None,
        "periodEnd": period_end.isoformat() if period_end else None,
        "rowNumber": row.row_number,
        "sourceRowId": row.source_row_id,
        "productName": str(product_name)[:240],
        "offerId": preview.get("offerId") or "",
        "productId": preview.get("productId") or "",
        "sku": preview.get("sku") or "",
        "barcode": preview.get("barcode") or "",
        "quantity": _json_number(quantity),
        "revenueAmount": _json_number(revenue_amount),
        "revenueBasis": revenue_basis,
        "onecItemId": preview.get("onecItemId") or "",
        "onecName": preview.get("onecName") or "",
        "unitCost": _json_number(unit_cost),
        "cogsAmount": _json_number(cogs_amount),
        "profitAmount": _json_number(profit_amount),
        "mappingStatus": preview.get("status") or "",
        "qualityStatus": quality_status,
        "statusReason": _ozon_unit_status_reason(quality_status),
    }


def _apply_ozon_buyout_unit_row(
    pnl: dict[str, Any],
    reconciliation: dict[str, Any],
) -> None:
    matched_without_number = int(reconciliation.get("matchedWithoutReportNumber") or 0)
    if not matched_without_number:
        return
    rows = list(pnl.get("unitRows") or [])
    row_count = int(pnl.get("unitRowCount") or len(rows)) + 1
    summary = dict(pnl.get("unitRowSummary") or _empty_ozon_unit_row_summary())
    _increment_ozon_unit_summary(summary, "buyout_period_only")
    limit = int(pnl.get("unitRowPreviewLimit") or len(rows) or 0)
    if not limit or len(rows) < limit:
        period_filter = pnl.get("periodFilter") or {}
        rows.append(
            {
                "rowType": "buyout_reconciliation",
                "periodStart": period_filter.get("periodStart"),
                "periodEnd": period_filter.get("periodEnd"),
                "rowNumber": None,
                "sourceRowId": "",
                "productName": "Выкупы Ozon",
                "offerId": "",
                "productId": "",
                "sku": "",
                "barcode": "",
                "quantity": reconciliation.get("buyoutQuantity"),
                "revenueAmount": reconciliation.get("buyoutAmount"),
                "revenueBasis": "ozon_buyout_period_total",
                "onecItemId": "",
                "onecName": "",
                "unitCost": None,
                "cogsAmount": None,
                "profitAmount": None,
                "mappingStatus": "",
                "qualityStatus": "buyout_period_only",
                "statusReason": _ozon_unit_status_reason("buyout_period_only"),
            }
        )
    pnl["unitRows"] = rows
    pnl["unitRowCount"] = row_count
    pnl["unitRowsLimited"] = row_count > len(rows)
    pnl["unitRowSummary"] = summary


def _onec_sales_cost_index(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    without_vat: bool = False,
    organization_id: str = "",
) -> dict[str, Decimal]:
    document_totals: dict[tuple[str, str, str, str], dict[str, Decimal]] = defaultdict(
        lambda: {"quantity": Decimal("0"), "cost": Decimal("0")}
    )
    for row_index, row in enumerate(rows, start=1):
        payload = row.row_payload or {}
        row_organization_id = _safe_payload_text(
            payload,
            "Организация_Key",
            "organization_id",
            "organizationId",
        )
        for item in _iter_onec_recordset_items(payload):
            item_organization_id = (
                _safe_payload_text(
                    item,
                    "Организация_Key",
                    "organization_id",
                    "organizationId",
                )
                or row_organization_id
            )
            if organization_id and item_organization_id != organization_id:
                continue
            if (period_start is not None or period_end is not None) and not (
                _onec_payload_matches_period(
                    item,
                    period_start=period_start,
                    period_end=period_end,
                )
            ):
                continue
            onec_item_id = _safe_payload_text(
                item,
                "Номенклатура_Key",
                "onec_item_id",
                "item_id",
            )
            if not onec_item_id:
                continue
            movement_date = date_or_none(
                _safe_payload_text(item, "Period", "Период", "Date", "Дата", "date")
                or _safe_payload_text(
                    payload,
                    "Period",
                    "Период",
                    "Date",
                    "Дата",
                    "date",
                )
            )
            month_key = (
                f"{movement_date.year:04d}-{movement_date.month:02d}"
                if movement_date is not None
                else (
                    f"{period_start.year:04d}-{period_start.month:02d}"
                    if period_start is not None
                    else "unknown-month"
                )
            )
            document_id = _safe_payload_text(
                item, "Документ", "Recorder", "document_id"
            ) or _safe_payload_text(
                payload,
                "Документ",
                "Recorder",
                "document_id",
            )
            if not document_id:
                source_identity = (
                    getattr(row, "id", "")
                    or getattr(row, "source_row_id", "")
                    or getattr(row, "row_number", "")
                    or row_index
                )
                document_id = f"snapshot-row:{source_identity}"
            document_key = (
                item_organization_id,
                onec_item_id,
                month_key,
                document_id,
            )
            quantity = _payload_decimal(item, "Количество", "quantity", "qty")
            cost_keys = (
                ("СебестоимостьБезНДС", "cost_without_vat")
                if without_vat
                else ("Себестоимость", "cost", "cost_amount")
            )
            cost = _payload_decimal(item, *cost_keys)
            document_totals[document_key]["quantity"] += quantity
            document_totals[document_key]["cost"] += cost

    totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"quantity": Decimal("0"), "cost": Decimal("0")}
    )
    for (
        _organization,
        onec_item_id,
        _month,
        _document,
    ), values in document_totals.items():
        if values["quantity"] == 0:
            continue
        totals[onec_item_id]["quantity"] += values["quantity"]
        totals[onec_item_id]["cost"] += values["cost"]

    result: dict[str, Decimal] = {}
    for onec_item_id, values in totals.items():
        if values["quantity"]:
            result[onec_item_id] = values["cost"] / values["quantity"]
    return result


def _onec_previous_closed_month_costs(
    rows: list[SourceSnapshotRow],
    *,
    commissioner_rows: list[SourceSnapshotRow],
    before_month: date,
    organization_id: str = "",
    month_count: int = 3,
) -> dict[str, tuple[Decimal, ...]]:
    history: dict[str, list[Decimal]] = defaultdict(list)
    closed_months = 0
    cursor = date(before_month.year, before_month.month, 1)
    for _ in range(12):
        cursor_end = cursor - timedelta(days=1)
        cursor_start = date(cursor_end.year, cursor_end.month, 1)
        _revenue, has_commissioner = _onec_commissioner_revenue_by_item(
            commissioner_rows,
            period_start=cursor_start,
            period_end=cursor_end,
        )
        cursor = cursor_start
        if not has_commissioner:
            continue
        index = _onec_sales_cost_index(
            rows,
            period_start=cursor_start,
            period_end=cursor_end,
            organization_id=organization_id,
        )
        for item_id, unit_cost in index.items():
            if unit_cost > 0:
                history[item_id].append(unit_cost)
        closed_months += 1
        if closed_months >= max(1, int(month_count)):
            break
    return {item_id: tuple(values) for item_id, values in history.items()}


def _onec_direct_sales_control(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date,
    period_end: date,
    organization_id: str = "",
    counterparty_ids: tuple[str, ...] = (),
) -> dict[str, Decimal | None]:
    if not counterparty_ids:
        return {"quantity": None, "revenue": None, "cogs": None}
    counterparties = set(counterparty_ids)
    document_totals: dict[tuple[str, str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "quantity": Decimal("0"),
            "revenue": Decimal("0"),
            "cogs": Decimal("0"),
            "counterparty_ids": set(),
        }
    )
    ambiguous_fallback = False
    for row_index, row in enumerate(rows, start=1):
        payload = row.row_payload or {}
        row_organization_id = _safe_payload_text(
            payload,
            "Организация_Key",
            "organization_id",
            "organizationId",
        )
        row_counterparty_id = _safe_payload_text(
            payload,
            "Контрагент_Key",
            "counterparty_id",
            "counterpartyId",
        )
        scoped_items: list[dict[str, Any]] = []
        for item in _iter_onec_recordset_items(payload):
            item_organization_id = (
                _safe_payload_text(
                    item,
                    "Организация_Key",
                    "organization_id",
                    "organizationId",
                )
                or row_organization_id
            )
            if organization_id and item_organization_id != organization_id:
                continue
            if not _onec_payload_matches_period(
                item,
                period_start=period_start,
                period_end=period_end,
            ):
                continue
            scoped_items.append(item)
        row_counterparty_ids = {
            counterparty_id
            for counterparty_id in (
                row_counterparty_id,
                *(
                    _safe_payload_text(
                        item,
                        "Контрагент_Key",
                        "counterparty_id",
                        "counterpartyId",
                    )
                    for item in scoped_items
                ),
            )
            if counterparty_id
        }
        single_row_counterparty_id = (
            next(iter(row_counterparty_ids)) if len(row_counterparty_ids) == 1 else ""
        )
        source_identity = (
            getattr(row, "id", "")
            or getattr(row, "source_row_id", "")
            or getattr(row, "row_number", "")
            or row_index
        )
        payload_document_id = _safe_payload_text(
            payload,
            "Документ",
            "Recorder",
            "document_id",
        )
        for item in scoped_items:
            item_organization_id = (
                _safe_payload_text(
                    item,
                    "Организация_Key",
                    "organization_id",
                    "organizationId",
                )
                or row_organization_id
            )
            item_id = (
                _safe_payload_text(
                    item,
                    "Номенклатура_Key",
                    "onec_item_id",
                    "item_id",
                )
                or "__all_items__"
            )
            item_counterparty_id = _safe_payload_text(
                item,
                "Контрагент_Key",
                "counterparty_id",
                "counterpartyId",
            )
            counterparty_id = item_counterparty_id or row_counterparty_id
            movement_date = date_or_none(
                _safe_payload_text(item, "Period", "Период", "Date", "Дата", "date")
            )
            month_key = (
                f"{movement_date.year:04d}-{movement_date.month:02d}"
                if movement_date is not None
                else f"{period_start.year:04d}-{period_start.month:02d}"
            )
            document_id = (
                _safe_payload_text(item, "Документ", "Recorder", "document_id")
                or payload_document_id
            )
            if not counterparty_id:
                if len(row_counterparty_ids) > 1:
                    quantity_value = _payload_decimal(
                        item, "Количество", "quantity", "qty"
                    )
                    cogs_value = _payload_decimal(
                        item, "Себестоимость", "cost", "cost_amount"
                    )
                    if (
                        quantity_value != 0 or cogs_value != 0
                    ) and row_counterparty_ids & counterparties:
                        ambiguous_fallback = True
                    continue
                counterparty_id = single_row_counterparty_id
            if not document_id:
                document_id = f"snapshot-row:{source_identity}"
            key = (
                item_organization_id,
                item_id,
                month_key,
                document_id,
                counterparty_id,
            )
            values = document_totals[key]
            values["quantity"] += _payload_decimal(
                item, "Количество", "quantity", "qty"
            )
            values["revenue"] += _payload_decimal(item, "Сумма", "amount")
            values["cogs"] += _payload_decimal(
                item, "Себестоимость", "cost", "cost_amount"
            )
            if counterparty_id:
                values["counterparty_ids"].add(counterparty_id)

    if ambiguous_fallback:
        return {"quantity": None, "revenue": None, "cogs": None}
    quantity = Decimal("0")
    revenue = Decimal("0")
    cogs = Decimal("0")
    matched = False
    for values in document_totals.values():
        if not (values["counterparty_ids"] & counterparties):
            continue
        if values["quantity"] == 0:
            continue
        matched = True
        quantity += values["quantity"]
        revenue += values["revenue"]
        cogs += values["cogs"]
    return {
        "quantity": quantity if matched else None,
        "revenue": revenue if matched else None,
        "cogs": cogs if matched else None,
    }


def _onec_direct_cost_control(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date,
    period_end: date,
    organization_id: str = "",
    counterparty_ids: tuple[str, ...] = (),
) -> dict[str, Decimal | None]:
    control = _onec_direct_sales_control(
        rows,
        period_start=period_start,
        period_end=period_end,
        organization_id=organization_id,
        counterparty_ids=counterparty_ids,
    )
    return {
        "quantity": control["quantity"],
        "cogs": control["cogs"],
    }


def _onec_sales_input_vat_index(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    organization_id: str = "",
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = defaultdict(Decimal)
    confirmed_items: set[str] = set()
    for row in rows:
        payload = row.row_payload or {}
        row_organization_id = _safe_payload_text(
            payload,
            "Организация_Key",
            "organization_id",
            "organizationId",
        )
        for item in _iter_onec_recordset_items(payload):
            item_organization_id = (
                _safe_payload_text(
                    item,
                    "Организация_Key",
                    "organization_id",
                    "organizationId",
                )
                or row_organization_id
            )
            if organization_id and item_organization_id != organization_id:
                continue
            if (period_start is not None or period_end is not None) and not (
                _onec_payload_matches_period(
                    item,
                    period_start=period_start,
                    period_end=period_end,
                )
            ):
                continue
            onec_item_id = _safe_payload_text(
                item,
                "Номенклатура_Key",
                "onec_item_id",
                "item_id",
            )
            if not onec_item_id:
                continue
            input_vat = _first_payload_decimal(
                item,
                "ВходящийНДСИтого",
                "СуммаВходящегоНДСИтого",
                "input_vat_total",
                "confirmed_input_vat",
            )
            if input_vat is None:
                continue
            confirmed_items.add(onec_item_id)
            result[onec_item_id] += abs(input_vat)
    return {item_id: result[item_id] for item_id in confirmed_items}


def _iter_onec_recordset_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recordset = payload.get("RecordSet")
    if isinstance(recordset, list):
        return [item for item in recordset if isinstance(item, dict)]
    return [payload]


def _ozon_pnl_totals_payload(
    totals: dict[str, Decimal],
    *,
    onec_cogs: Decimal | None = None,
    revenue_override: Decimal | None = None,
    revenue_basis: str | None = None,
) -> dict[str, float | None]:
    cash_flow_revenue = totals["ordersAmount"] + totals["returnsAmount"]
    revenue = revenue_override if revenue_override is not None else cash_flow_revenue
    expenses = (
        totals["commissionAmount"]
        + totals["deliveryAndReturnAmount"]
        + totals["servicesAmount"]
    )
    pnl_expenses = Decimal("0") if revenue_override is not None else expenses
    profit_before_cogs = revenue + pnl_expenses
    profit_after_cogs = (
        profit_before_cogs - onec_cogs if onec_cogs is not None else None
    )
    margin_before_cogs = (
        profit_before_cogs / revenue if revenue != Decimal("0") else None
    )
    return {
        "ordersAmount": _json_number(totals["ordersAmount"]),
        "returnsAmount": _json_number(totals["returnsAmount"]),
        "cashFlowRevenue": _json_number(cash_flow_revenue),
        "revenue": _json_number(revenue),
        "revenueBasis": revenue_basis
        or ("onec_commissioner_net" if revenue_override is not None else "none"),
        "commissionAmount": _json_number(totals["commissionAmount"]),
        "deliveryAndReturnAmount": _json_number(totals["deliveryAndReturnAmount"]),
        "servicesAmount": _json_number(totals["servicesAmount"]),
        "ozonExpenses": _json_number(expenses),
        "profitBeforeCogs": _json_number(profit_before_cogs),
        "onecCogs": _json_number(onec_cogs),
        "profitAfterCogs": _json_number(profit_after_cogs),
        "marginBeforeCogs": _json_number(margin_before_cogs),
    }


def _ozon_onec_revenue_basis(payload: dict[str, Any]) -> tuple[Decimal | None, str]:
    if payload.get("status") != "loaded":
        return None, "none"
    sales_register = payload.get("salesRegister")
    if isinstance(sales_register, dict):
        register_amount = _decimal_from_payload_value(sales_register.get("amount"))
        if int(sales_register.get("rowCount") or 0) > 0 and register_amount is not None:
            return register_amount, "onec_sales_register"
    return _decimal_from_payload_value(payload.get("netSalesAmount")), (
        "onec_commissioner_net"
    )


def _empty_ozon_onec_commissioner_payload() -> dict[str, Any]:
    return {
        "status": "missing",
        "counterpartyLabel": OZON_ONEC_COUNTERPARTY_LABEL,
        "counterpartyIds": [],
        "reportCount": 0,
        "salesLines": 0,
        "returnLines": 0,
        "salesQuantity": 0.0,
        "returnQuantity": 0.0,
        "salesAmount": 0.0,
        "returnsAmount": 0.0,
        "netSalesAmount": 0.0,
        "vatAmount": 0.0,
        "returnVatAmount": 0.0,
        "documentRows": [],
        "salesRegister": {
            "rowCount": 0,
            "documentCount": 0,
            "quantity": 0.0,
            "amount": 0.0,
            "cost": 0.0,
            "deltaVsCommissionerNet": 0.0,
        },
    }


def _ozon_onec_commissioner_payload(
    rows: list[SourceSnapshotRow],
    *,
    sales_register_rows: list[SourceSnapshotRow],
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    source_payloads = [row.row_payload or {} for row in rows]
    ozon_counterparty_ids = {
        counterparty_id
        for counterparty_id in (
            _safe_payload_text(payload, "Контрагент_Key", "counterparty_id")
            for payload in source_payloads
            if _is_ozon_onec_commissioner_payload(payload)
        )
        if counterparty_id
    }
    matched_payloads = [
        payload
        for payload in source_payloads
        if (
            _is_ozon_onec_commissioner_payload(payload)
            or _safe_payload_text(payload, "Контрагент_Key", "counterparty_id")
            in ozon_counterparty_ids
        )
        and _onec_payload_matches_period(
            payload,
            period_start=period_start,
            period_end=period_end,
        )
    ]
    document_rows = _ozon_commissioner_document_rows(
        source_payloads,
        period_start=period_start,
        period_end=period_end,
    )
    if not matched_payloads:
        result = _empty_ozon_onec_commissioner_payload()
        result["documentRows"] = document_rows
        return result

    sales_amount = Decimal("0")
    returns_amount = Decimal("0")
    vat_amount = Decimal("0")
    return_vat_amount = Decimal("0")
    sales_quantity = Decimal("0")
    return_quantity = Decimal("0")
    sales_lines = 0
    return_lines = 0
    counterparty_ids: set[str] = set()
    for payload in matched_payloads:
        counterparty_id = _safe_payload_text(
            payload,
            "Контрагент_Key",
            "counterparty_id",
        )
        if counterparty_id:
            counterparty_ids.add(counterparty_id)
        sales_totals = _onec_commissioner_table_totals(payload.get("Запасы"))
        return_totals = _onec_commissioner_table_totals(payload.get("ЗапасыВозвраты"))
        sales_amount += sales_totals["amount"]
        returns_amount += return_totals["amount"]
        vat_amount += sales_totals["vat"]
        return_vat_amount += return_totals["vat"]
        sales_quantity += sales_totals["quantity"]
        return_quantity += return_totals["quantity"]
        sales_lines += sales_totals["lineCount"]
        return_lines += return_totals["lineCount"]

    sales_register = _onec_sales_register_by_counterparty_payload(
        sales_register_rows,
        counterparty_ids=counterparty_ids,
        commissioner_net=sales_amount - returns_amount,
        period_start=period_start,
        period_end=period_end,
    )
    return {
        "status": "loaded",
        "counterpartyLabel": OZON_ONEC_COUNTERPARTY_LABEL,
        "counterpartyIds": sorted(counterparty_ids)[:10],
        "reportCount": len(matched_payloads),
        "salesLines": sales_lines,
        "returnLines": return_lines,
        "salesQuantity": _json_number(sales_quantity),
        "returnQuantity": _json_number(return_quantity),
        "salesAmount": _json_number(sales_amount),
        "returnsAmount": _json_number(returns_amount),
        "netSalesAmount": _json_number(sales_amount - returns_amount),
        "vatAmount": _json_number(vat_amount),
        "returnVatAmount": _json_number(return_vat_amount),
        "documentRows": document_rows,
        "salesRegister": sales_register,
    }


def _ozon_commissioner_document_rows(
    payloads: list[dict[str, Any]],
    *,
    period_start: date | None,
    period_end: date | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        if not _is_ozon_onec_commissioner_payload(payload):
            continue
        document_date = _payload_date_or_none(
            _safe_payload_text(payload, "Date", "Дата", "date", "Period", "Период")
        )
        report_period_start, report_period_end = _onec_buyout_report_period(payload)
        period_matches = _date_ranges_overlap(
            report_period_start,
            report_period_end,
            period_start,
            period_end,
        )
        date_matches = bool(
            document_date
            and _date_in_period(
                document_date,
                period_start=period_start,
                period_end=period_end,
            )
        )
        if (period_start or period_end) and not (period_matches or date_matches):
            continue
        sales_totals = _onec_commissioner_table_totals(payload.get("Запасы"))
        return_totals = _onec_commissioner_table_totals(payload.get("ЗапасыВозвраты"))
        posted = (
            payload.get("Posted") is not False
            and payload.get("DeletionMark") is not True
        )
        wrong_date = bool(period_matches and document_date and not date_matches)
        rows.append(
            {
                "documentNumber": _safe_payload_text(
                    payload, "Number", "Номер", "number"
                ),
                "documentDate": document_date.isoformat() if document_date else None,
                "reportNumber": _onec_commissioner_report_number(payload),
                "periodFrom": (
                    report_period_start.isoformat() if report_period_start else None
                ),
                "periodTo": (
                    report_period_end.isoformat() if report_period_end else None
                ),
                "amount": _json_number(
                    Decimal(sales_totals["amount"]) - Decimal(return_totals["amount"])
                ),
                "posted": posted,
                "status": (
                    "not_posted"
                    if not posted
                    else "wrong_date"
                    if wrong_date
                    else "matched"
                ),
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("periodFrom") or ""),
            str(item.get("documentDate") or ""),
            str(item.get("documentNumber") or ""),
        ),
    )


def _date_ranges_overlap(
    left_start: date | None,
    left_end: date | None,
    right_start: date | None,
    right_end: date | None,
) -> bool:
    if left_start is None or left_end is None:
        return False
    return left_start <= (right_end or date.max) and left_end >= (
        right_start or date.min
    )


def _onec_commissioner_report_number(payload: dict[str, Any]) -> str:
    text = " ".join(
        _safe_payload_text(payload, key)
        for key in (
            "Комментарий",
            "Comment",
            "comment",
            "НомерВходящегоДокумента",
        )
    )
    match = OZON_COMMISSIONER_REPORT_RE.search(text)
    return re.sub(r"\D+", "", match.group(1)) if match else ""


def _is_ozon_onec_commissioner_payload(payload: dict[str, Any]) -> bool:
    text = " ".join(
        _safe_payload_text(payload, key)
        for key in (
            "Комментарий",
            "НомерВходящегоДокумента",
            "Контрагент",
            "КонтрагентНаименование",
            "counterparty",
            "counterpartyName",
        )
    ).casefold()
    return "озон" in text or "ozon" in text or "интернет решения" in text


def _onec_payload_matches_period(
    payload: dict[str, Any],
    *,
    period_start: date | None,
    period_end: date | None,
) -> bool:
    if period_start is None and period_end is None:
        return True
    document_date = date_or_none(
        _safe_payload_text(payload, "Date", "Дата", "date", "Period", "Период")
    )
    if document_date is None:
        return False
    if period_start is not None and document_date < period_start:
        return False
    return not (period_end is not None and document_date > period_end)


def _onec_commissioner_table_totals(value: Any) -> dict[str, Decimal | int]:
    if not isinstance(value, list):
        return {
            "lineCount": 0,
            "quantity": Decimal("0"),
            "amount": Decimal("0"),
            "vat": Decimal("0"),
        }
    amount = Decimal("0")
    vat = Decimal("0")
    quantity = Decimal("0")
    for item in value:
        if not isinstance(item, dict):
            continue
        amount += _payload_decimal(item, "Всего", "Сумма", "amount")
        vat += _payload_decimal(item, "СуммаНДС", "vat")
        quantity += _payload_decimal(item, "Количество", "quantity", "qty")
    return {
        "lineCount": len([item for item in value if isinstance(item, dict)]),
        "quantity": quantity,
        "amount": amount,
        "vat": vat,
    }


def _onec_sales_register_by_counterparty_payload(
    rows: list[SourceSnapshotRow],
    *,
    counterparty_ids: set[str],
    commissioner_net: Decimal,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    if not counterparty_ids:
        return _empty_ozon_onec_commissioner_payload()["salesRegister"]
    quantity = Decimal("0")
    amount = Decimal("0")
    cost = Decimal("0")
    row_count = 0
    document_ids: set[str] = set()
    for row in rows:
        for item in _iter_onec_recordset_items(row.row_payload or {}):
            if _safe_payload_text(item, "Контрагент_Key", "counterparty_id") not in (
                counterparty_ids
            ):
                continue
            if not _onec_payload_matches_period(
                item,
                period_start=period_start,
                period_end=period_end,
            ):
                continue
            row_count += 1
            document_id = _safe_payload_text(
                item,
                "Документ",
                "Recorder",
                "document_id",
            )
            if document_id:
                document_ids.add(document_id)
            quantity += _payload_decimal(item, "Количество", "quantity", "qty")
            amount += _payload_decimal(item, "Сумма", "amount")
            cost += _payload_decimal(item, "Себестоимость", "cost")
    return {
        "rowCount": row_count,
        "documentCount": len(document_ids),
        "quantity": _json_number(quantity),
        "amount": _json_number(amount),
        "cost": _json_number(cost),
        "deltaVsCommissionerNet": _json_number(amount - commissioner_net),
    }


def _ozon_diagnostic_readiness(
    collections: list[SourceRefreshCollection],
) -> dict[str, bool]:
    onec_required = [
        item
        for item in collections
        if item.required and item.source_type.startswith("onec_")
    ]
    return {
        "ozonFinanceLoaded": any(
            item.source_type == OZON_DIAGNOSTIC_FINANCE_SOURCE
            and _source_collection_loaded(item)
            for item in collections
        ),
        "ozonRealizationLoaded": any(
            item.source_type == OZON_REALIZATION_SOURCE
            and _source_collection_loaded(item)
            for item in collections
        ),
        "mappingLoaded": any(
            (
                item.source_type == "sku_mapping"
                or item.source_type in OZON_ONEC_MARKETPLACE_MAPPING_SOURCES
            )
            and _source_collection_loaded(item)
            for item in collections
        ),
        "onecRequiredLoaded": bool(onec_required)
        and all(_source_collection_loaded(item) for item in onec_required),
        "reportExpected": False,
    }


def _ozon_diagnostic_source_summary(
    collections: list[SourceRefreshCollection],
    *,
    wb_cabinet_id: str = "",
) -> dict[str, dict[str, Any]]:
    return {
        "ozonFinance": _collection_group_summary(
            collections,
            lambda item: item.source_type == OZON_DIAGNOSTIC_FINANCE_SOURCE,
            wb_cabinet_id=wb_cabinet_id,
        ),
        "ozonProducts": _collection_group_summary(
            collections,
            lambda item: item.source_type == OZON_DIAGNOSTIC_PRODUCT_SOURCE,
            wb_cabinet_id=wb_cabinet_id,
        ),
        "ozonRealization": _collection_group_summary(
            collections,
            lambda item: item.source_type == OZON_REALIZATION_SOURCE,
            wb_cabinet_id=wb_cabinet_id,
        ),
        "ozonBuyouts": _collection_group_summary(
            collections,
            lambda item: item.source_type == OZON_BUYOUT_API_SOURCE,
            wb_cabinet_id=wb_cabinet_id,
        ),
        "ozonExtra": _collection_group_summary(
            collections,
            lambda item: item.source_type in OZON_EXTRA_RECONCILIATION_SOURCES,
            wb_cabinet_id=wb_cabinet_id,
        ),
        "mapping": _collection_group_summary(
            collections,
            lambda item: (
                item.source_type == "sku_mapping"
                or item.source_type in OZON_ONEC_MARKETPLACE_MAPPING_SOURCES
            ),
        ),
        "onec": _collection_group_summary(
            collections,
            lambda item: item.source_type.startswith("onec_"),
        ),
    }


def _collection_group_summary(
    collections: list[SourceRefreshCollection],
    predicate: Callable[[SourceRefreshCollection], bool],
    *,
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    items = [item for item in collections if predicate(item)]
    return {
        "total": len(items),
        "required": sum(1 for item in items if item.required),
        "publicationRequired": sum(1 for item in items if item.publication_required),
        "loaded": sum(1 for item in items if _source_collection_loaded(item)),
        "failed": sum(1 for item in items if _source_collection_failed(item)),
        "rowCount": sum(
            _collection_row_count_for_cabinet(item, wb_cabinet_id) for item in items
        ),
    }


def _collection_row_count_for_cabinet(
    item: SourceRefreshCollection,
    wb_cabinet_id: str = "",
) -> int:
    if not wb_cabinet_id:
        return item.row_count
    results = (item.payload or {}).get("results")
    if not isinstance(results, list):
        return item.row_count
    matched_rows = [
        row
        for row in results
        if isinstance(row, dict)
        and _safe_payload_text(row, "wbCabinetId") == wb_cabinet_id
    ]
    if not matched_rows:
        return 0
    return sum(int_or_none(row.get("rowCount")) or 0 for row in matched_rows)


def _apply_ozon_buyout_source_summary(
    source_summary: dict[str, dict[str, Any]],
    ozon_buyouts: dict[str, Any],
) -> None:
    buyout_summary = ozon_buyouts.get("summary") or {}
    product_rows = int(
        buyout_summary.get("ozonApiLoadedProductRows")
        or buyout_summary.get("ozonApiProductRows")
        or 0
    )
    matched_product_rows = int(buyout_summary.get("ozonApiProductRows") or 0)
    snapshot_rows = int(buyout_summary.get("ozonApiRows") or 0)
    if "ozonBuyouts" not in source_summary:
        source_summary["ozonBuyouts"] = {}
    source_summary["ozonBuyouts"].update(
        {
            "rowCount": product_rows or snapshot_rows,
            "snapshotRows": snapshot_rows,
            "productRows": product_rows,
            "matchedProductRows": matched_product_rows,
            "quantity": buyout_summary.get("ozonApiLoadedQuantity"),
            "amount": buyout_summary.get("ozonApiLoadedAmount"),
            "matchedQuantity": buyout_summary.get("ozonApiQuantity"),
            "matchedAmount": buyout_summary.get("ozonApiAmount"),
        }
    )


def _ozon_diagnostic_collection_payload(
    item: SourceRefreshCollection,
    *,
    ozon_buyouts: dict[str, Any],
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    payload = source_refresh_collection_payload(item, include_sensitive=False)
    if item.source_type.startswith("ozon_"):
        payload["rowCount"] = _collection_row_count_for_cabinet(
            item,
            wb_cabinet_id,
        )
    if item.source_type != OZON_BUYOUT_API_SOURCE:
        return payload
    buyout_summary = ozon_buyouts.get("summary") or {}
    product_rows = int(
        buyout_summary.get("ozonApiLoadedProductRows")
        or buyout_summary.get("ozonApiProductRows")
        or 0
    )
    snapshot_rows = int(buyout_summary.get("ozonApiRows") or 0)
    payload["rowCount"] = product_rows or snapshot_rows or payload["rowCount"]
    payload["sourceRows"] = snapshot_rows
    payload["productRows"] = product_rows
    return payload


def _source_collection_loaded(item: SourceRefreshCollection) -> bool:
    return item.status in SOURCE_LOAD_OK_STATUSES


def _source_collection_failed(item: SourceRefreshCollection) -> bool:
    status = item.status.lower()
    return any(marker in status for marker in SOURCE_LOAD_FAILED_MARKERS)


def _empty_ozon_buyouts_payload(limit: int = 0) -> dict[str, Any]:
    return {
        "status": "not_started",
        "message": "Нет 1C расходных накладных по выкупам Ozon.",
        "sourceType": OZON_ONEC_BUYOUT_SOURCE,
        "ozonSourceType": OZON_BUYOUT_API_SOURCE,
        "rowCount": 0,
        "documentCount": 0,
        "previewLimit": limit,
        "previewRowCount": 0,
        "previewLimited": False,
        "summary": {
            "foundInOzonApi": 0,
            "missingInOzonApi": 0,
            "matchedByReportNumber": 0,
            "matchedByPeriodTotal": 0,
            "ozonApiRows": 0,
            "ozonApiProductRows": 0,
            "ozonApiLoaded": False,
            "ozonApiAmount": 0.0,
            "ozonApiQuantity": 0.0,
            "ozonApiLoadedAmount": 0.0,
            "ozonApiLoadedQuantity": 0.0,
            "amount": 0.0,
            "quantity": 0.0,
        },
        "rows": [],
    }


def _ozon_buyouts_payload(
    rows: list[SourceSnapshotRow],
    *,
    ozon_buyout_rows: list[SourceSnapshotRow],
    collections: list[SourceRefreshCollection],
    period_start: date | None,
    period_end: date | None,
    limit: int,
) -> dict[str, Any]:
    ozon_api_loaded = any(
        item.source_type == OZON_BUYOUT_API_SOURCE and _source_collection_loaded(item)
        for item in collections
    )
    ozon_api_snapshot_rows = _ozon_buyout_snapshot_row_count(collections)
    ozon_report_numbers = _ozon_api_buyout_report_numbers(ozon_buyout_rows)
    ozon_period_totals = _ozon_api_buyout_period_totals(
        ozon_buyout_rows,
        collections=collections,
    )
    items = _dedupe_onec_buyout_items(
        [
            item
            for row in rows
            if (item := _onec_ozon_buyout_row_payload(row)) is not None
            and _onec_buyout_matches_period(
                row.row_payload or {},
                period_start=period_start,
                period_end=period_end,
            )
        ]
    )
    if not items:
        ozon_loaded_amount = sum(item["amount"] for item in ozon_period_totals.values())
        ozon_loaded_quantity = sum(
            item["quantity"] for item in ozon_period_totals.values()
        )
        ozon_loaded_product_rows = sum(
            item["productRows"] for item in ozon_period_totals.values()
        )
        payload = _empty_ozon_buyouts_payload(limit)
        payload["summary"]["ozonApiRows"] = ozon_api_snapshot_rows
        payload["summary"]["ozonApiProductRows"] = int(ozon_loaded_product_rows)
        payload["summary"]["ozonApiLoaded"] = ozon_api_loaded
        payload["summary"]["ozonApiAmount"] = _json_number(ozon_loaded_amount)
        payload["summary"]["ozonApiQuantity"] = _json_number(ozon_loaded_quantity)
        payload["summary"]["ozonApiLoadedAmount"] = _json_number(ozon_loaded_amount)
        payload["summary"]["ozonApiLoadedQuantity"] = _json_number(ozon_loaded_quantity)
        payload["summary"]["ozonApiLoadedProductRows"] = int(ozon_loaded_product_rows)
        return payload

    total_amount = sum(
        (_decimal_from_payload_value(item.get("amount")) or Decimal("0"))
        for item in items
    )
    total_quantity = sum(
        (_decimal_from_payload_value(item.get("quantity")) or Decimal("0"))
        for item in items
    )
    relevant_periods = {
        period
        for item in items
        if (period := _ozon_buyout_item_month_period(item)) is not None
    }
    ozon_selected_period_totals = {
        period: totals
        for period, totals in ozon_period_totals.items()
        if not relevant_periods or period in relevant_periods
    }
    ozon_loaded_amount = sum(item["amount"] for item in ozon_period_totals.values())
    ozon_loaded_quantity = sum(item["quantity"] for item in ozon_period_totals.values())
    ozon_loaded_product_rows = sum(
        item["productRows"] for item in ozon_period_totals.values()
    )
    ozon_total_amount = sum(
        item["amount"] for item in ozon_selected_period_totals.values()
    )
    ozon_total_quantity = sum(
        item["quantity"] for item in ozon_selected_period_totals.values()
    )
    ozon_product_rows = sum(
        item["productRows"] for item in ozon_selected_period_totals.values()
    )
    matched_by_report = 0
    for item in items:
        report_number = str(item.get("reportNumber") or "")
        found = bool(report_number and report_number in ozon_report_numbers)
        item["foundInOzonApi"] = found
        item["ozonMatchStatus"] = (
            "found" if found else "not_found" if report_number else "no_report_number"
        )
        if found:
            matched_by_report += 1
    matched_by_period_total = _mark_ozon_buyout_period_total_matches(
        items,
        ozon_period_totals=ozon_period_totals,
    )
    found_count = sum(1 for item in items if item.get("foundInOzonApi"))

    preview_rows = items[:limit]
    message = (
        "1C выкупы Ozon сверены с Ozon buyout API."
        if found_count == len(items)
        else "1C выкупы Ozon требуют проверки по Ozon buyout API."
    )
    return {
        "status": "loaded",
        "message": message,
        "sourceType": OZON_ONEC_BUYOUT_SOURCE,
        "ozonSourceType": OZON_BUYOUT_API_SOURCE,
        "rowCount": len(items),
        "documentCount": len(
            {
                str(item.get("documentNumber") or "")
                for item in items
                if item.get("documentNumber")
            }
        ),
        "previewLimit": limit,
        "previewRowCount": len(preview_rows),
        "previewLimited": len(items) > len(preview_rows),
        "summary": {
            "foundInOzonApi": found_count,
            "missingInOzonApi": len(items) - found_count,
            "matchedByReportNumber": matched_by_report,
            "matchedByPeriodTotal": matched_by_period_total,
            "ozonApiRows": ozon_api_snapshot_rows,
            "ozonApiProductRows": int(ozon_product_rows),
            "ozonApiLoaded": ozon_api_loaded,
            "ozonApiAmount": _json_number(ozon_total_amount),
            "ozonApiQuantity": _json_number(ozon_total_quantity),
            "ozonApiLoadedAmount": _json_number(ozon_loaded_amount),
            "ozonApiLoadedQuantity": _json_number(ozon_loaded_quantity),
            "ozonApiLoadedProductRows": int(ozon_loaded_product_rows),
            "amount": _json_number(total_amount),
            "quantity": _json_number(total_quantity),
        },
        "rows": preview_rows,
    }


def _ozon_buyout_snapshot_row_count(
    collections: list[SourceRefreshCollection],
) -> int:
    return sum(
        1
        for collection in collections
        if collection.source_type == OZON_BUYOUT_API_SOURCE
        for item in ((collection.payload or {}).get("results") or [])
        if isinstance(item, dict) and bool(item.get("outputFile"))
    )


def _onec_ozon_buyout_row_payload(row: SourceSnapshotRow) -> dict[str, Any] | None:
    payload = row.row_payload or {}
    if not _is_ozon_buyout_expense_invoice_payload(payload):
        return None
    report_number = _onec_buyout_report_number(payload)
    period_from, period_to = _onec_buyout_report_period(payload)
    totals = _onec_buyout_totals(payload)
    document_date = _payload_date_or_none(
        _safe_payload_text(payload, "Date", "Дата", "date", "Period", "Период")
    )
    return {
        "rowNumber": row.row_number,
        "sourceRowId": row.source_row_id,
        "documentNumber": _safe_payload_text(payload, "Number", "Номер", "number"),
        "documentDate": document_date.isoformat() if document_date else None,
        "basis": _safe_payload_text(
            payload,
            "ОснованиеПечати",
            "Основание",
            "basis",
            "Basis",
        ),
        "reportNumber": report_number,
        "periodFrom": period_from.isoformat() if period_from else None,
        "periodTo": period_to.isoformat() if period_to else None,
        "quantity": _json_number(totals["quantity"]),
        "amount": _json_number(totals["amount"]),
        "foundInOzonApi": False,
        "ozonMatchStatus": "not_checked",
    }


def _is_ozon_buyout_expense_invoice_payload(payload: dict[str, Any]) -> bool:
    comment = _safe_payload_text(
        payload,
        "Комментарий",
        "Comment",
        "comment",
        "ОснованиеПечати",
        "printBasis",
    )
    basis = _safe_payload_text(
        payload,
        "ОснованиеПечати",
        "Основание",
        "basis",
        "Basis",
    )
    text = f"{comment} {basis}".casefold()
    report_number = _onec_buyout_report_number(payload)
    has_ozon = "озон" in text or "ozon" in text or "интернет решения" in text
    has_buyout_report = "выкуп" in text and bool(report_number)
    return has_buyout_report and (
        has_ozon or "выкупленных товарах" in text or "отчет о выкупе" in text
    )


def _dedupe_onec_buyout_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, float | None, float | None], dict[str, Any]] = {}
    for item in items:
        key = (
            str(item.get("reportNumber") or ""),
            item.get("amount"),
            item.get("quantity"),
        )
        current = deduped.get(key)
        if current is None or _buyout_item_sort_key(item) > _buyout_item_sort_key(
            current
        ):
            deduped[key] = item
    return sorted(
        deduped.values(),
        key=lambda item: (
            str(item.get("periodFrom") or ""),
            str(item.get("documentDate") or ""),
            str(item.get("documentNumber") or ""),
        ),
    )


def _buyout_item_sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
    return (
        str(item.get("documentDate") or ""),
        1 if "озон" in str(item.get("basis") or "").casefold() else 0,
        str(item.get("documentNumber") or ""),
    )


def _onec_buyout_report_number(payload: dict[str, Any]) -> str:
    text = " ".join(
        _safe_payload_text(payload, key)
        for key in (
            "Комментарий",
            "Comment",
            "comment",
            "ОснованиеПечати",
            "printBasis",
            "Основание",
            "basis",
        )
    )
    match = OZON_BUYOUT_REPORT_RE.search(text)
    if not match:
        return ""
    return re.sub(r"\D+", "", match.group(1))


def _onec_buyout_report_period(
    payload: dict[str, Any],
) -> tuple[date | None, date | None]:
    text = _safe_payload_text(payload, "Комментарий", "Comment", "comment")
    match = OZON_BUYOUT_PERIOD_RE.search(text)
    if not match:
        return None, None
    return _ru_date_or_none(match.group(1)), _ru_date_or_none(match.group(2))


def _ru_date_or_none(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except (TypeError, ValueError):
        return None


def _payload_date_or_none(value: str) -> date | None:
    if not value:
        return None
    try:
        return date_or_none(value)
    except (TypeError, ValueError):
        return _ru_date_or_none(value.split(maxsplit=1)[0])


def _onec_buyout_matches_period(
    payload: dict[str, Any],
    *,
    period_start: date | None,
    period_end: date | None,
) -> bool:
    if period_start is None and period_end is None:
        return True
    document_date = _payload_date_or_none(
        _safe_payload_text(payload, "Date", "Дата", "date", "Period", "Период")
    )
    if document_date is None:
        return False
    if period_start is not None and document_date < period_start:
        return False
    return not (period_end is not None and document_date > period_end)


def _onec_buyout_totals(payload: dict[str, Any]) -> dict[str, Decimal]:
    quantity = Decimal("0")
    amount = Decimal("0")
    table = payload.get("Запасы")
    if not isinstance(table, list):
        table = payload.get("Товары")
    if isinstance(table, list):
        for item in table:
            if not isinstance(item, dict):
                continue
            quantity += _payload_decimal(item, "Количество", "quantity", "qty")
            amount += _payload_decimal(
                item,
                "Всего",
                "Сумма",
                "СуммаДокумента",
                "amount",
            )
    if quantity == Decimal("0"):
        quantity = _payload_decimal(payload, "Количество", "quantity", "qty")
    if amount == Decimal("0"):
        amount = _payload_decimal(
            payload,
            "Всего",
            "Сумма",
            "СуммаДокумента",
            "amount",
        )
    return {"quantity": quantity, "amount": amount}


def _ozon_api_buyout_report_numbers(rows: list[SourceSnapshotRow]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        payload = row.row_payload or {}
        for key in (
            "report_id",
            "reportId",
            "report_number",
            "reportNumber",
            "buyout_report_number",
            "buyoutReportNumber",
            "document_number",
            "documentNumber",
            "НомерОтчета",
            "Номер отчета",
            "Отчет",
        ):
            number = re.sub(r"\D+", "", _safe_payload_text(payload, key))
            if number:
                result.add(number)
    return result


def _ozon_rows_matching_period(
    rows: list[SourceSnapshotRow],
    *,
    collections: list[SourceRefreshCollection],
    source_type: str,
    period_start: date | None,
    period_end: date | None,
) -> list[SourceSnapshotRow]:
    if period_start is None and period_end is None:
        return rows
    periods = _ozon_source_periods(collections, source_type)
    if not periods:
        return rows
    requested_start = period_start or date.min
    requested_end = period_end or date.max
    result: list[SourceSnapshotRow] = []
    for row in rows:
        row_period = _ozon_row_period(row, source_type=source_type, periods=periods)
        if row_period is None:
            continue
        if row_period[0] <= requested_end and row_period[1] >= requested_start:
            result.append(row)
    return result


def _month_ranges(period_start: date, period_end: date) -> list[tuple[date, date]]:
    if period_end < period_start:
        return []
    result: list[tuple[date, date]] = []
    current = date(period_start.year, period_start.month, 1)
    while current <= period_end:
        next_month = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
        result.append(
            (
                max(current, period_start),
                min(next_month - timedelta(days=1), period_end),
            )
        )
        current = next_month
    return result


def _block_ozon_profit_for_duplicate_snapshot(
    mart: dict[str, Any],
    collections: list[SourceRefreshCollection],
) -> None:
    duplicate_control = next(
        (
            item
            for item in collections
            if item.source_type == "snapshot_duplicate_control"
        ),
        None,
    )
    if duplicate_control is None or duplicate_control.status != "needs_review":
        return
    payload = duplicate_control.payload or {}
    if not payload.get("blocksProfit"):
        return
    mart["status"] = "needs_review"
    mart["message"] = (
        "В снимке найдены дубли строк; прибыль заблокирована до сверки источника."
    )
    for totals_key in ("totals", "closedPeriodTotals"):
        totals = mart.get(totals_key)
        if not isinstance(totals, dict):
            continue
        for key in (
            "profit",
            "margin",
            "profitBeforeTax",
            "marginBeforeTax",
            "profitBeforeIncomeTax",
            "profitAfterTax",
            "marginAfterTax",
        ):
            totals[key] = None
    mart.setdefault("issues", []).append(
        {
            "code": "ozon_mart_duplicate_snapshot_rows",
            "title": "Дубли строк источника",
            "value": f"{int(duplicate_control.row_count or 0)} строк",
            "detail": "Повторно загрузите источник после исправления дублей.",
            "tone": "review",
        }
    )


def _ozon_row_period(
    row: SourceSnapshotRow,
    *,
    source_type: str,
    periods: dict[tuple[str, int], tuple[date, date]],
) -> tuple[date, date] | None:
    payload = row.row_payload or {}
    payload_period = _ozon_period_from_output_file(
        _safe_payload_text(payload, "source_output_file", "outputFile")
    )
    if payload_period is not None:
        return payload_period
    seller_id = _safe_payload_text(payload, "seller_account_id", "sellerAccountId")
    page_index = _ozon_row_page_index(row, source_type=source_type)
    if page_index is not None:
        page_period = periods.get((seller_id, page_index)) or periods.get(
            (str(page_index), page_index)
        )
        if page_period is not None:
            return page_period
    collection_id = str(getattr(row, "collection_id", "") or "")
    collection_period = periods.get((f"collection:{collection_id}", row.row_number))
    if collection_period is not None:
        return collection_period
    row_number_period = periods.get(("row_number", row.row_number))
    if row_number_period is not None:
        return row_number_period
    return None


def _ozon_row_page_index(
    row: SourceSnapshotRow,
    *,
    source_type: str,
) -> int | None:
    payload = row.row_payload or {}
    source_page_index = int_or_none(payload.get("source_page_index"))
    if source_page_index is not None:
        return source_page_index
    match = re.match(rf"{re.escape(source_type)}:(\d+):", row.source_row_id)
    if match:
        return int(match.group(1))
    return None


def _ozon_source_periods(
    collections: list[SourceRefreshCollection],
    source_type: str,
) -> dict[tuple[str, int], tuple[date, date]]:
    result: dict[tuple[str, int], tuple[date, date]] = {}
    fallback: dict[tuple[str, int], tuple[date, date]] = {}
    for collection in collections:
        if collection.source_type != source_type:
            continue
        payload = collection.payload or {}
        items = payload.get("results")
        if not isinstance(items, list):
            continue
        collection_id = str(getattr(collection, "id", "") or "")
        next_row_number = 1
        for item in items:
            if not isinstance(item, dict):
                continue
            row_count = max(0, int_or_none(item.get("rowCount")) or 0)
            page_index = int_or_none(item.get("pageIndex"))
            if page_index is None:
                next_row_number += row_count
                continue
            period = _ozon_period_from_output_file(
                _safe_payload_text(item, "outputFile")
            )
            if period is None:
                next_row_number += row_count
                continue
            seller_id = _safe_payload_text(item, "sellerAccountId")
            result[(seller_id, page_index)] = period
            fallback[(str(page_index), page_index)] = period
            for row_number in range(next_row_number, next_row_number + row_count):
                if collection_id:
                    result[(f"collection:{collection_id}", row_number)] = period
                result[("row_number", row_number)] = period
            next_row_number += row_count
    for key, value in fallback.items():
        result.setdefault(key, value)
    return result


def _ozon_period_from_output_file(value: str) -> tuple[date, date] | None:
    range_match = re.search(
        r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.raw\.json$",
        value,
    )
    if range_match:
        start = date_or_none(range_match.group(1))
        end = date_or_none(range_match.group(2))
        if start is None or end is None:
            return None
        return start, end

    month_match = re.search(
        r"_(\d{4})-(\d{2})(?:_page_\d+|_file)?\.raw\.(?:json|csv|tsv|xlsx)$",
        value,
    )
    if not month_match:
        return None
    year = int(month_match.group(1))
    month = int(month_match.group(2))
    if month < 1 or month > 12:
        return None
    start = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, next_month - timedelta(days=1)


def _ozon_api_buyout_period_totals(
    rows: list[SourceSnapshotRow],
    *,
    collections: list[SourceRefreshCollection],
) -> dict[tuple[date, date], dict[str, Decimal]]:
    periods = _ozon_buyout_api_periods(collections)
    totals: dict[tuple[date, date], dict[str, Decimal]] = {}
    for row in rows:
        payload = row.row_payload or {}
        period = _ozon_buyout_row_period(row, periods=periods)
        if period is None:
            continue
        row_totals = _ozon_buyout_api_row_totals(payload)
        bucket = totals.setdefault(
            period,
            {
                "quantity": Decimal("0"),
                "amount": Decimal("0"),
                "productRows": Decimal("0"),
            },
        )
        bucket["quantity"] += row_totals["quantity"]
        bucket["amount"] += row_totals["amount"]
        bucket["productRows"] += row_totals["productRows"]
    return totals


def _ozon_buyout_api_periods(
    collections: list[SourceRefreshCollection],
) -> dict[tuple[str, int], tuple[date, date]]:
    result: dict[tuple[str, int], tuple[date, date]] = {}
    fallback: dict[tuple[str, int], tuple[date, date]] = {}
    for collection in collections:
        if collection.source_type != OZON_BUYOUT_API_SOURCE:
            continue
        payload = collection.payload or {}
        items = payload.get("results")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            page_index = int_or_none(item.get("pageIndex"))
            if page_index is None:
                continue
            period = _ozon_buyout_period_from_output_file(
                _safe_payload_text(item, "outputFile")
            )
            if period is None:
                continue
            seller_id = _safe_payload_text(item, "sellerAccountId")
            result[(seller_id, page_index)] = period
            fallback[(str(page_index), page_index)] = period
    for key, value in fallback.items():
        result.setdefault(key, value)
    return result


def _ozon_buyout_period_from_output_file(value: str) -> tuple[date, date] | None:
    match = re.search(
        r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.raw\.json$",
        value,
    )
    if not match:
        return None
    start = date_or_none(match.group(1))
    end = date_or_none(match.group(2))
    if start is None or end is None:
        return None
    return start, end


def _ozon_buyout_row_period(
    row: SourceSnapshotRow,
    *,
    periods: dict[tuple[str, int], tuple[date, date]],
) -> tuple[date, date] | None:
    payload = row.row_payload or {}
    seller_id = _safe_payload_text(payload, "seller_account_id", "sellerAccountId")
    page_index = _ozon_buyout_row_page_index(row)
    if page_index is None:
        return None
    return periods.get((seller_id, page_index)) or periods.get(
        (str(page_index), page_index)
    )


def _ozon_buyout_row_page_index(row: SourceSnapshotRow) -> int | None:
    match = re.match(rf"{re.escape(OZON_BUYOUT_API_SOURCE)}:(\d+):", row.source_row_id)
    if match:
        return int(match.group(1))
    return row.row_number


def _ozon_buyout_api_row_totals(payload: dict[str, Any]) -> dict[str, Decimal]:
    products = payload.get("products")
    if not isinstance(products, list):
        products = []
    if products:
        quantity = Decimal("0")
        amount = Decimal("0")
        for item in products:
            if not isinstance(item, dict):
                continue
            quantity += _payload_decimal(item, "quantity", "qty", "Количество")
            amount += _payload_decimal(item, "amount", "sum", "Сумма", "Всего")
        return {
            "quantity": quantity,
            "amount": amount,
            "productRows": Decimal(str(len(products))),
        }
    return {
        "quantity": _payload_decimal(payload, "quantity", "qty", "Количество"),
        "amount": _payload_decimal(payload, "amount", "sum", "Сумма", "Всего"),
        "productRows": Decimal("1"),
    }


def _mark_ozon_buyout_period_total_matches(
    items: list[dict[str, Any]],
    *,
    ozon_period_totals: dict[tuple[date, date], dict[str, Decimal]],
) -> int:
    items_by_period: dict[tuple[date, date], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("foundInOzonApi"):
            continue
        period = _ozon_buyout_item_month_period(item)
        if period is not None:
            items_by_period[period].append(item)

    matched_count = 0
    for period, period_items in items_by_period.items():
        ozon_totals = ozon_period_totals.get(period)
        if not ozon_totals:
            continue
        onec_quantity = sum(
            (_decimal_from_payload_value(item.get("quantity")) or Decimal("0"))
            for item in period_items
        )
        onec_amount = sum(
            (_decimal_from_payload_value(item.get("amount")) or Decimal("0"))
            for item in period_items
        )
        if not (
            _decimal_close(onec_quantity, ozon_totals["quantity"], Decimal("0.0001"))
            and _decimal_close(onec_amount, ozon_totals["amount"], Decimal("0.01"))
        ):
            continue
        for item in period_items:
            item["foundInOzonApi"] = True
            item["ozonMatchStatus"] = "matched_by_period_total"
            item["ozonMatchedPeriodFrom"] = period[0].isoformat()
            item["ozonMatchedPeriodTo"] = period[1].isoformat()
            item["ozonMatchedQuantity"] = _json_number(ozon_totals["quantity"])
            item["ozonMatchedAmount"] = _json_number(ozon_totals["amount"])
            matched_count += 1
    return matched_count


def _ozon_buyout_item_month_period(item: dict[str, Any]) -> tuple[date, date] | None:
    document_date = date_or_none(item.get("documentDate"))
    if document_date is None:
        period_from = date_or_none(item.get("periodFrom"))
        period_to = date_or_none(item.get("periodTo"))
        if period_from is None or period_to is None:
            return None
        document_date = period_from
    start = document_date.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - timedelta(days=1)


def _decimal_close(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    return abs(left - right) <= tolerance


def _ozon_diagnostic_message(
    refresh_run: SourceRefreshRun,
    readiness: dict[str, bool],
) -> str:
    if (
        refresh_run.status in ACTIVE_SOURCE_REFRESH_STATUSES
        and not refresh_run.finished_at
    ):
        return "Ozon + 1C еще загружается. Диагностика обновится после завершения."
    if all(
        readiness[key]
        for key in ("ozonRealizationLoaded", "mappingLoaded", "onecRequiredLoaded")
    ):
        return (
            "Ozon + 1C источники загружены. Полноценный Ozon-отчет пока не "
            "создается: это диагностическая витрина."
        )
    return (
        "Ozon + 1C требует проверки: один из обязательных источников не готов "
        "или не дал строк."
    )


def _empty_ozon_mapping_payload(limit: int) -> dict[str, Any]:
    return {
        "status": "not_started",
        "message": "Запустите Ozon + 1C, чтобы проверить сопоставление Ozon с 1С.",
        "sourceType": OZON_DIAGNOSTIC_PRODUCT_SOURCE,
        "rowCount": 0,
        "checkedRows": 0,
        "previewLimit": limit,
        "previewRowCount": 0,
        "previewLimited": False,
        "summary": {
            "matched": 0,
            "missing": 0,
            "ambiguous": 0,
            "noKey": 0,
            "notChecked": 0,
        },
        "rows": [],
    }


def _ozon_mapping_diagnostics_payload(
    db: Session,
    *,
    tenant_id: str,
    refresh_run: SourceRefreshRun,
    limit: int,
    wb_cabinet_id: str = "",
    prefer_typed: bool = False,
) -> dict[str, Any]:
    product_collection = next(
        (
            item
            for item in refresh_run.collections
            if item.source_type == OZON_DIAGNOSTIC_PRODUCT_SOURCE
        ),
        None,
    )
    if product_collection is None:
        payload = _empty_ozon_mapping_payload(limit)
        payload.update(
            {
                "status": "not_ready",
                "message": (
                    "Каталог Ozon ещё не загружался. Запустите Ozon + 1C после "
                    "добавления доступа «Товары и каталог» или полного доступа "
                    "только для чтения."
                ),
            }
        )
        return payload

    if _source_collection_failed(product_collection):
        payload = _empty_ozon_mapping_payload(limit)
        payload.update(
            {
                "status": "needs_catalog_access",
                "message": (
                    "Не удалось загрузить каталог Ozon. Для проверки "
                    "сопоставления нужен доступ к товарам Ozon."
                ),
                "rowCount": product_collection.row_count,
            }
        )
        return payload

    product_rows = _ozon_typed_source_rows(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        source_type=OZON_DIAGNOSTIC_PRODUCT_SOURCE,
        wb_cabinet_id=wb_cabinet_id,
        limit=None,
        prefer_typed=prefer_typed,
    )
    product_row_count = (
        len(product_rows) if wb_cabinet_id else product_collection.row_count
    )
    candidates = list(
        _iter_ozon_mapping_candidates(
            product_rows,
            max_rows=None,
        )
    )
    if not candidates:
        payload = _empty_ozon_mapping_payload(limit)
        payload.update(
            {
                "status": "not_ready",
                "message": "Каталог Ozon загружен, но в нём нет товарных ключей.",
                "rowCount": product_row_count,
            }
        )
        return payload

    onec_indexes = _ozon_onec_indexes_for_run(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
    )
    project_mapping_preview_index = _ozon_project_mapping_preview_index(
        db,
        tenant_id=tenant_id,
        client_id=refresh_run.client_id,
        wb_cabinet_id=wb_cabinet_id,
    )
    summary = {
        "matched": 0,
        "missing": 0,
        "ambiguous": 0,
        "noKey": 0,
        "notChecked": 0,
    }
    preview_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        project_mapping = _ozon_mapping_preview_for_candidate(
            candidate,
            project_mapping_preview_index,
        )
        checked = (
            {
                "statusCounter": "matched",
                "row": project_mapping,
            }
            if project_mapping is not None
            else _check_ozon_mapping_candidate(candidate, onec_indexes)
        )
        summary[checked["statusCounter"]] += 1
        if len(preview_rows) < limit:
            preview_rows.append(checked["row"])

    matched = summary["matched"]
    checked_rows = len(candidates)
    status = "ready" if checked_rows and matched == checked_rows else "needs_review"
    message = (
        "Сопоставление Ozon проверено: все строки предварительного просмотра "
        "нашли связь с 1С."
        if status == "ready"
        else (
            "Сопоставление Ozon требует проверки: есть строки без связи или "
            "с неоднозначной связью."
        )
    )
    return {
        "status": status,
        "message": message,
        "sourceType": OZON_DIAGNOSTIC_PRODUCT_SOURCE,
        "rowCount": product_row_count,
        "checkedRows": checked_rows,
        "previewLimit": limit,
        "previewRowCount": len(preview_rows),
        "previewLimited": checked_rows > len(preview_rows),
        "summary": summary,
        "rows": preview_rows,
        "indexes": {
            "onecNomenclatureRows": onec_indexes["nomenclatureRows"],
            "onecBarcodeRows": onec_indexes["barcodeRows"],
            "onecOzonMappingRows": onec_indexes.get("onecOzonMappingRows", 0),
        },
    }


def _ozon_onec_indexes_for_run(
    db: Session,
    *,
    tenant_id: str,
    refresh_run: SourceRefreshRun,
) -> dict[str, Any]:
    onec_indexes = _onec_mapping_indexes(
        db,
        tenant_id=tenant_id,
        refresh_run_id=refresh_run.id,
    )
    mapping_collection = next(
        (item for item in refresh_run.collections if item.source_type == "sku_mapping"),
        None,
    )
    onec_indexes["byOzonNameMapping"] = _ozon_uploaded_mapping_index(
        mapping_collection,
        onec_indexes=onec_indexes,
    )
    onec_indexes.update(
        _ozon_onec_marketplace_mapping_indexes(
            db,
            tenant_id=tenant_id,
            refresh_run_id=refresh_run.id,
        )
    )
    return onec_indexes


def _ozon_onec_marketplace_mapping_indexes(
    db: Session,
    *,
    tenant_id: str,
    refresh_run_id: str,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run_id,
                SourceSnapshotRow.source_type.in_(
                    [*OZON_ONEC_MARKETPLACE_MAPPING_SOURCES, "sku_mapping"]
                ),
            )
        )
    )
    return _ozon_onec_marketplace_mapping_indexes_from_rows(rows)


def _ozon_onec_marketplace_mapping_indexes_from_rows(rows: list[Any]) -> dict[str, Any]:
    indexes: dict[str, Any] = {
        "byOzonMarketplaceOffer": defaultdict(list),
        "byOzonMarketplaceProduct": defaultdict(list),
        "byOzonMarketplaceSku": defaultdict(list),
        "byOzonMarketplaceBarcode": defaultdict(list),
        "byOzonMarketplaceName": defaultdict(list),
        "onecOzonMappingRows": 0,
    }
    for row in rows:
        source_type = str(getattr(row, "source_type", "") or "")
        require_marketplace = source_type in {"sku_mapping", "onec_marketplace_mapping"}
        for payload in _iter_ozon_onec_marketplace_mapping_payloads(
            getattr(row, "row_payload", None) or {},
            require_marketplace=require_marketplace,
        ):
            onec_item = _ozon_onec_marketplace_mapping_item(payload)
            if not onec_item.get("id"):
                continue
            indexes["onecOzonMappingRows"] += 1
            _append_ozon_mapping_index(
                indexes["byOzonMarketplaceOffer"],
                onec_item,
                payload,
                "offer_id",
                "offerId",
                "vendor_code",
                "vendorCode",
                "Артикул продавца",
            )
            _append_ozon_mapping_index(
                indexes["byOzonMarketplaceProduct"],
                onec_item,
                payload,
                "product_id",
                "productId",
                "ozon_product_id",
                "Ozon Product ID",
                "ID товара",
            )
            _append_ozon_mapping_index(
                indexes["byOzonMarketplaceSku"],
                onec_item,
                payload,
                "sku",
                "SKU",
                "sku_fbs",
                "sku_fbo",
                "ozon_sku",
            )
            _append_ozon_mapping_index(
                indexes["byOzonMarketplaceBarcode"],
                onec_item,
                payload,
                "barcode",
                "barcodes",
                "Штрихкод",
                "Баркод",
            )
            _append_ozon_mapping_index(
                indexes["byOzonMarketplaceName"],
                onec_item,
                payload,
                "ozon_name",
                "product_name",
                "productName",
                "Номенклатура Ozon",
                "НоменклатураOzon",
                "Название товара",
                name_key=True,
            )
    return indexes


def _iter_ozon_onec_marketplace_mapping_payloads(
    payload: Any,
    *,
    require_marketplace: bool,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for value in payload:
            items.extend(
                _iter_ozon_onec_marketplace_mapping_payloads(
                    value,
                    require_marketplace=require_marketplace,
                )
            )
        return items
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [
            item
            for row in rows
            for item in _iter_ozon_onec_marketplace_mapping_payloads(
                row,
                require_marketplace=require_marketplace,
            )
        ]
    marketplace = _first_payload_text(
        payload,
        "marketplace",
        "source_marketplace",
        "sourceMarketplace",
    ).casefold()
    if require_marketplace and marketplace not in {"ozon", "озон"}:
        return []
    if marketplace and marketplace not in {"ozon", "озон"}:
        return []
    if not _first_payload_text(payload, "onec_item_id", "onecItemId"):
        return []
    if not any(
        _payload_text_values(payload, *keys)
        for keys in (
            ("offer_id", "offerId", "vendor_code", "vendorCode"),
            ("product_id", "productId", "ozon_product_id"),
            ("sku", "SKU", "sku_fbs", "sku_fbo", "ozon_sku"),
            ("barcode", "barcodes", "Штрихкод", "Баркод"),
            ("ozon_name", "product_name", "productName", "Номенклатура Ozon"),
        )
    ):
        return []
    return [payload]


def _ozon_onec_marketplace_mapping_item(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _first_payload_text(payload, "onec_item_id", "onecItemId"),
        "name": _first_payload_text(
            payload,
            "onec_name",
            "onecName",
            "Номенклатура",
            "Номенклатура 1C",
            "Номенклатура 1С",
        ),
        "article": _first_payload_text(
            payload,
            "onec_article",
            "onecArticle",
            "onec_code",
            "onecCode",
            "Артикул",
        ),
    }


def _append_ozon_mapping_index(
    index: dict[str, list[dict[str, str]]],
    onec_item: dict[str, str],
    payload: dict[str, Any],
    *keys: str,
    name_key: bool = False,
) -> None:
    for value in _payload_text_values(payload, *keys):
        lookup_key = (
            _mapping_name_key(value) if name_key else _mapping_lookup_key(value)
        )
        if lookup_key:
            index[lookup_key].append(onec_item)


def _iter_ozon_mapping_candidates(
    rows: list[SourceSnapshotRow],
    *,
    max_rows: int | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        for payload in _iter_product_like_payloads(row.row_payload or {}):
            candidate = _ozon_mapping_candidate(row, payload)
            if candidate:
                candidates.append(candidate)
                if max_rows is not None and len(candidates) >= max_rows:
                    return candidates
    return candidates


def _iter_product_like_payloads(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for value in payload:
            items.extend(_iter_product_like_payloads(value))
        return items
    if not isinstance(payload, dict):
        return []
    if _has_ozon_product_key(payload):
        return [payload]
    items = []
    for value in payload.values():
        if isinstance(value, (dict, list)):
            items.extend(_iter_product_like_payloads(value))
    return items


def _has_ozon_product_key(payload: dict[str, Any]) -> bool:
    return any(
        _payload_text_values(payload, *keys)
        for keys in (
            (
                "Название товара",
                "Номенклатура Ozon",
                "product_name",
                "Product name",
                "name",
            ),
            (
                "offer_id",
                "offerId",
                "Offer ID",
                "offer id",
                "vendor_code",
                "vendorCode",
                "Артикул",
                "Артикул продавца",
                "Артикул продавца",
            ),
            (
                "product_id",
                "productId",
                "Product ID",
                "Ozon Product ID",
                "ID товара",
                "Идентификатор товара",
                "id",
            ),
            (
                "sku",
                "SKU",
                "ozon_sku",
                "Ozon SKU",
                "fbo_sku",
                "FBO SKU",
                "fbs_sku",
                "FBS SKU",
            ),
            (
                "barcode",
                "barcodes",
                "Barcode",
                "Штрихкод",
                "Баркод",
                "Штрихкод (Серийный номер / EAN)",
            ),
        )
    )


def _ozon_mapping_candidate(
    row: SourceSnapshotRow,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    product_name = _first_payload_text(
        payload,
        "Название товара",
        "Номенклатура Ozon",
        "product_name",
        "Product name",
        "name",
    )
    offer_id = _first_payload_text(
        payload,
        "offer_id",
        "offerId",
        "Offer ID",
        "offer id",
        "vendor_code",
        "vendorCode",
        "Артикул",
        "Артикул продавца",
        "Артикул продавца",
    )
    product_id = _first_payload_text(
        payload,
        "product_id",
        "productId",
        "Product ID",
        "Ozon Product ID",
        "ID товара",
        "Идентификатор товара",
        "id",
    )
    sku = _first_payload_text(
        payload,
        "sku",
        "SKU",
        "ozon_sku",
        "Ozon SKU",
        "fbo_sku",
        "FBO SKU",
        "fbs_sku",
        "FBS SKU",
    )
    barcode = _first_payload_text(
        payload,
        "barcode",
        "barcodes",
        "Barcode",
        "Штрихкод",
        "Баркод",
        "Штрихкод (Серийный номер / EAN)",
    )
    if not any((product_name, offer_id, product_id, sku, barcode)):
        return None
    return {
        "rowNumber": row.row_number,
        "sourceRowId": row.source_row_id,
        "productName": product_name,
        "offerId": offer_id,
        "productId": product_id,
        "sku": sku,
        "barcode": barcode,
    }


def _onec_mapping_indexes(
    db: Session,
    *,
    tenant_id: str,
    refresh_run_id: str,
) -> dict[str, Any]:
    nomenclature_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run_id,
                SourceSnapshotRow.source_type == "onec_nomenclature",
            )
        )
    )
    barcode_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.tenant_id == tenant_id,
                SourceSnapshotRow.refresh_run_id == refresh_run_id,
                SourceSnapshotRow.source_type == "onec_barcodes",
            )
        )
    )
    by_ref: dict[str, dict[str, str]] = {}
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_article: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in nomenclature_rows:
        item = _onec_mapping_item(row.row_payload or {})
        for key in _payload_text_values(row.row_payload or {}, "Ref_Key", "RefKey"):
            by_ref[_mapping_lookup_key(key)] = item
        for key in _payload_text_values(
            row.row_payload or {},
            "Description",
            "Наименование",
            "НаименованиеПолное",
            "name",
        ):
            by_name[_mapping_name_key(key)].append(item)
        for key in _payload_text_values(row.row_payload or {}, "Артикул", "article"):
            by_article[_mapping_lookup_key(key)].append(item)
        for key in _payload_text_values(row.row_payload or {}, "Code", "Код", "code"):
            by_code[_mapping_lookup_key(key)].append(item)

    by_barcode: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in barcode_rows:
        barcode_values = _payload_text_values(
            row.row_payload or {},
            "Штрихкод",
            "barcode",
        )
        item_ref = _first_payload_text(row.row_payload or {}, "Номенклатура_Key")
        item = by_ref.get(_mapping_lookup_key(item_ref)) or {
            "id": item_ref,
            "name": "",
            "article": "",
        }
        for barcode in barcode_values:
            by_barcode[_mapping_lookup_key(barcode)].append(item)

    return {
        "byName": by_name,
        "byArticle": by_article,
        "byCode": by_code,
        "byBarcode": by_barcode,
        "nomenclatureRows": len(nomenclature_rows),
        "barcodeRows": len(barcode_rows),
    }


def _onec_mapping_item(payload: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _first_payload_text(payload, "Ref_Key", "RefKey", "Code", "Код"),
        "name": _first_payload_text(payload, "Description", "НаименованиеПолное"),
        "article": _first_payload_text(payload, "Артикул", "article"),
    }


def _check_ozon_mapping_candidate(
    candidate: dict[str, Any],
    indexes: dict[str, Any],
    *,
    preferred_onec_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    attempts = [
        (
            "onec_marketplace_ozon_offer",
            candidate.get("offerId"),
            indexes.get("byOzonMarketplaceOffer", {}),
        ),
        (
            "onec_marketplace_ozon_product_id",
            candidate.get("productId"),
            indexes.get("byOzonMarketplaceProduct", {}),
        ),
        (
            "onec_marketplace_ozon_sku",
            candidate.get("sku"),
            indexes.get("byOzonMarketplaceSku", {}),
        ),
        (
            "onec_marketplace_ozon_barcode",
            candidate.get("barcode"),
            indexes.get("byOzonMarketplaceBarcode", {}),
        ),
        (
            "onec_marketplace_ozon_name",
            candidate.get("productName"),
            indexes.get("byOzonMarketplaceName", {}),
        ),
        (
            "uploaded_mapping_name",
            candidate.get("productName"),
            indexes.get("byOzonNameMapping", {}),
        ),
        ("offer_id", candidate.get("offerId"), indexes.get("byArticle", {})),
        ("offer_id_code", candidate.get("offerId"), indexes.get("byCode", {})),
        ("barcode", candidate.get("barcode"), indexes.get("byBarcode", {})),
        ("sku_as_barcode", candidate.get("sku"), indexes.get("byBarcode", {})),
    ]
    if not any(value for _, value, _ in attempts):
        return {
            "statusCounter": "noKey",
            "row": _ozon_mapping_preview_row(candidate, "no_key", "", {}, ""),
        }

    preferred_onec_item_ids = preferred_onec_item_ids or set()
    ambiguous_result: dict[str, Any] | None = None
    for method, value, index in attempts:
        key = _mapping_lookup_key(value)
        if not key:
            continue
        matches = _unique_onec_matches(index.get(key, []))
        if len(matches) == 1:
            return {
                "statusCounter": "matched",
                "row": _ozon_mapping_preview_row(
                    candidate,
                    "matched",
                    method,
                    matches[0],
                    value or "",
                ),
            }
        if len(matches) > 1:
            preferred_matches = [
                item
                for item in matches
                if str(item.get("id") or "") in preferred_onec_item_ids
            ]
            if len(preferred_matches) == 1:
                return {
                    "statusCounter": "matched",
                    "row": _ozon_mapping_preview_row(
                        candidate,
                        "matched",
                        f"{method}_period_financials",
                        preferred_matches[0],
                        value or "",
                    ),
                }
            ambiguous_result = ambiguous_result or {
                "statusCounter": "ambiguous",
                "row": _ozon_mapping_preview_row(
                    candidate,
                    "ambiguous",
                    method,
                    matches[0],
                    value or "",
                ),
            }

    if ambiguous_result is not None:
        return ambiguous_result

    return {
        "statusCounter": "missing",
        "row": _ozon_mapping_preview_row(candidate, "missing", "", {}, ""),
    }


def _ozon_mapping_preview_row(
    candidate: dict[str, Any],
    status: str,
    method: str,
    onec_item: dict[str, str],
    match_key: str,
) -> dict[str, Any]:
    return {
        "rowNumber": candidate.get("rowNumber"),
        "sourceRowId": candidate.get("sourceRowId"),
        "productName": candidate.get("productName") or "",
        "offerId": candidate.get("offerId") or "",
        "productId": candidate.get("productId") or "",
        "sku": candidate.get("sku") or "",
        "barcode": candidate.get("barcode") or "",
        "status": status,
        "matchMethod": method,
        "matchKey": str(match_key or "")[:240],
        "onecItemId": onec_item.get("id", ""),
        "onecName": onec_item.get("name", "")[:240],
        "onecArticle": onec_item.get("article", "")[:120],
    }


def _unique_onec_matches(items: list[dict[str, str]]) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for item in items:
        item_id = item.get("id") or item.get("name") or item.get("article") or ""
        if item_id:
            by_id[item_id] = item
    return list(by_id.values())


def _ozon_uploaded_mapping_index(
    collection: SourceRefreshCollection | None,
    *,
    onec_indexes: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    if collection is None or not collection.raw_path:
        return {}
    root = Path(collection.raw_path)
    if not root.exists() or not root.is_dir():
        return {}
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in sorted(root.glob("*.txt")):
        for row in _read_uploaded_ozon_mapping_rows(path, max_rows=5000):
            ozon_name = _first_mapping_field(
                row,
                "Номенклатура Ozon",
                "НоменклатураOzon",
                "Название товара",
                "product_name",
            )
            onec_name = _first_mapping_field(
                row,
                "Номенклатура",
                "Номенклатура 1C",
                "Номенклатура 1С",
                "onec_name",
            )
            if not ozon_name or not onec_name:
                continue
            matches = _unique_onec_matches(
                onec_indexes["byName"].get(_mapping_name_key(onec_name), [])
            )
            if matches:
                result[_mapping_name_key(ozon_name)].extend(matches)
    return result


def _read_uploaded_ozon_mapping_rows(
    path: Path,
    *,
    max_rows: int,
) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    if not text.strip():
        return []
    delimiter = _mapping_file_delimiter(text)
    reader = csv.DictReader(StringIO(text), delimiter=delimiter)
    fieldnames = [str(item or "").strip() for item in (reader.fieldnames or [])]
    if not _looks_like_ozon_mapping_header(fieldnames):
        return []
    rows: list[dict[str, str]] = []
    for index, row in enumerate(reader):
        if index >= max_rows:
            break
        rows.append(
            {
                str(key or "").strip(): str(value or "").strip()
                for key, value in row.items()
            }
        )
    return rows


def _mapping_file_delimiter(text: str) -> str:
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    header_candidates = {
        "\t": first_line.count("\t"),
        ";": first_line.count(";"),
        ",": first_line.count(","),
    }
    header_delimiter = max(header_candidates, key=header_candidates.get)
    if header_candidates[header_delimiter] > 0:
        return header_delimiter
    sample = text[:4096]
    candidates = {
        "\t": sample.count("\t"),
        ";": sample.count(";"),
        ",": sample.count(","),
    }
    return max(candidates, key=candidates.get)


def _looks_like_ozon_mapping_header(fieldnames: list[str]) -> bool:
    normalized = {_mapping_name_key(item) for item in fieldnames}
    return (
        "номенклатураozon" in normalized
        or "названиетовара" in normalized
        or "ozonproduct" in normalized
    )


def _first_mapping_field(row: dict[str, str], *keys: str) -> str:
    normalized = {_mapping_name_key(key): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(_mapping_name_key(key), "")
        if value:
            return value.strip()
    return ""


def _first_payload_text(payload: dict[str, Any], *keys: str) -> str:
    values = _payload_text_values(payload, *keys)
    return values[0] if values else ""


def _payload_text_values(payload: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, (list, tuple, set)):
            values.extend(_scalar_text(item) for item in value)
        else:
            values.append(_scalar_text(value))
    return [item[:240] for item in values if item]


def _scalar_text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _mapping_lookup_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _mapping_name_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().casefold())


def _ozon_finance_preview_row(item: SourceSnapshotRow) -> dict[str, Any]:
    payload = item.row_payload or {}
    return {
        "rowNumber": item.row_number,
        "sourceRowId": item.source_row_id,
        "loadedAt": item.loaded_at.isoformat(),
        "operationId": _safe_payload_text(payload, "operation_id", "id"),
        "operationDate": _safe_payload_text(
            payload,
            "operation_date",
            "date",
            "created_at",
        ),
        "operationType": _safe_payload_text(
            payload,
            "operation_type_name",
            "operation_type",
            "type",
        ),
        "offerId": _safe_payload_text(payload, "offer_id", "vendor_code", "barcode"),
        "productId": _safe_payload_text(payload, "product_id"),
        "sku": _safe_payload_text(payload, "sku", "ozon_sku"),
        "amount": _json_number(_first_payload_decimal(payload, "amount", "payout")),
        "price": _json_number(_first_payload_decimal(payload, "price")),
        "income": _json_number(
            _first_payload_decimal(payload, "income", "revenue", "accruals_for_sale")
        ),
        "expense": _json_number(
            _first_payload_decimal(
                payload,
                "expense",
                "sale_commission",
                "delivery_charge",
                "return_delivery_charge",
            )
        ),
        "sourceEndpoint": _safe_payload_text(payload, "source_endpoint"),
        "hasMappingKey": any(
            _safe_payload_text(payload, key)
            for key in ("offer_id", "vendor_code", "barcode", "product_id", "sku")
        ),
    }


def _safe_payload_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        text = str(value).strip()
        if text:
            return text[:240]
    return ""


def _first_payload_decimal(payload: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = _decimal_from_payload_value(payload.get(key))
        if value is not None:
            return value
    return None


def _decimal_from_payload_value(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return None
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _json_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _ozon_finance_preview_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for key in ("amount", "price", "income", "expense"):
        total = sum(float(row[key] or 0) for row in rows if row.get(key) is not None)
        if total:
            totals[key] = total
    return totals


def _safe_source_refresh_message(refresh_run: SourceRefreshRun) -> str:
    if refresh_run.new_report_run_id:
        return "Последнее обновление данных создало новый отчёт."
    if (
        refresh_run.status in {"queued", "running", "source_loaded", "rebuilding"}
        and refresh_run.finished_at is None
    ):
        return "Обновление данных выполняется."
    if refresh_run.status == "source_loaded":
        return "Источники обновлены без публикации нового отчета."
    if refresh_run.status == "needs_configuration":
        return (
            "Последнее обновление данных не создало отчёт: нужно настроить источники."
        )
    if refresh_run.status == "needs_review":
        return "Последнее обновление данных требует проверки источников."
    if refresh_run.status == "blocked_active_refresh":
        return "Обновление данных не запущено: другое обновление уже выполняется."
    if refresh_run.status == "blocked_low_disk":
        return (
            "Обновление данных не запущено: недостаточно свободного места "
            "для снимка данных."
        )
    if refresh_run.status == "needs_full_refresh":
        return (
            "Инкрементальное обновление не запущено: нужна полная пересборка истории."
        )
    if refresh_run.status == "failed":
        return (
            "Последнее обновление данных не создало отчёт: "
            "один из обязательных источников не прошел проверку."
        )
    if refresh_run.status == "dry_run_ready":
        return "Проверка обновления данных прошла без публикации отчёта."
    return "Последнее обновление данных не создало отчёт."


def client_draft_payload(db: Session, report: ReportRun) -> dict[str, Any]:
    revisions = client_draft_revisions(db, report)
    latest = revisions[0] if revisions else None
    return {
        "reportId": report.id,
        "latest": _client_draft_payload(latest) if latest else None,
        "revisions": [_client_draft_payload(item) for item in revisions],
        "requiredSections": CLIENT_DRAFT_REQUIRED_SECTIONS,
        "forbiddenTerms": CLIENT_DRAFT_FORBIDDEN_TERMS,
    }


def client_draft_revisions(db: Session, report: ReportRun) -> list[AiClientDraft]:
    return list(
        db.scalars(
            select(AiClientDraft)
            .where(
                AiClientDraft.tenant_id == report.tenant_id,
                AiClientDraft.report_run_id == report.id,
            )
            .order_by(AiClientDraft.revision.desc(), AiClientDraft.id.desc())
        )
    )


def latest_client_draft(db: Session, report: ReportRun) -> AiClientDraft | None:
    return db.scalar(
        select(AiClientDraft)
        .where(
            AiClientDraft.tenant_id == report.tenant_id,
            AiClientDraft.report_run_id == report.id,
        )
        .order_by(AiClientDraft.revision.desc(), AiClientDraft.id.desc())
    )


def create_client_draft_revision(
    db: Session,
    *,
    user: User,
    report: ReportRun,
    content: str,
    source: str,
    instruction: str = "",
    thread_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    limitations: list[Any] | None = None,
    status: str = "draft",
) -> AiClientDraft:
    require_staff(user, report.tenant_id)
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("draft content is required")
    if client_draft_contains_forbidden_text(normalized_content):
        raise ValueError("client draft contains forbidden internal labels")
    if status not in {"draft", "ready"}:
        raise ValueError("invalid draft status")
    revision = _next_client_draft_revision(db, report)
    now = security.utcnow()
    draft = AiClientDraft(
        tenant_id=report.tenant_id,
        report_run_id=report.id,
        thread_id=thread_id,
        author_user_id=user.id,
        revision=revision,
        status=status,
        source=source[:80] or "manual",
        content=normalized_content,
        instruction=instruction.strip()[:8000],
        evidence=evidence or {},
        limitations=limitations or [],
        created_at=now,
        updated_at=now,
    )
    db.add(draft)
    db.flush()
    action = {
        "deterministic_base": "ai_client_draft_created",
        "ai": "ai_client_draft_refined",
        "manual": "ai_client_draft_saved",
    }.get(source, "ai_client_draft_saved")
    audit(
        db,
        action=action,
        user=user,
        tenant_id=report.tenant_id,
        entity_type="ai_client_draft",
        entity_id=str(draft.id),
        payload={
            "report_run_id": report.id,
            "revision": revision,
            "source": draft.source,
            "status": status,
        },
    )
    return draft


def finalize_client_draft(
    db: Session,
    *,
    user: User,
    report: ReportRun,
    revision: int | None = None,
) -> AiClientDraft:
    require_staff(user, report.tenant_id)
    if revision is None:
        draft = latest_client_draft(db, report)
    else:
        draft = db.scalar(
            select(AiClientDraft).where(
                AiClientDraft.tenant_id == report.tenant_id,
                AiClientDraft.report_run_id == report.id,
                AiClientDraft.revision == revision,
            )
        )
    if draft is None:
        raise LookupError("client draft not found")
    draft.status = "ready"
    draft.updated_at = security.utcnow()
    audit(
        db,
        action="ai_client_draft_finalized",
        user=user,
        tenant_id=report.tenant_id,
        entity_type="ai_client_draft",
        entity_id=str(draft.id),
        payload={"report_run_id": report.id, "revision": draft.revision},
    )
    return draft


def client_draft_contains_forbidden_text(content: str) -> bool:
    lowered = content.lower()
    return any(term in lowered for term in CLIENT_DRAFT_FORBIDDEN_TERMS)


def client_draft_evidence_payload(summary: dict[str, Any]) -> dict[str, Any]:
    rows = summary["unitRows"]
    kpis = summary.get("kpis") or {}
    revenue = kpis.get("revenue")
    profit = kpis.get("profit")
    losses = sorted(
        [row for row in rows if float(row.get("profit") or 0) < 0],
        key=lambda row: float(row.get("profit") or 0),
    )
    quality: dict[str, int] = {}
    for row in rows:
        status = row.get("status") or "Не указан"
        quality[status] = quality.get(status, 0) + 1
    return {
        "kpi": {
            "period": summary["meta"]["period"],
            "periodStatus": summary["meta"].get("periodStatus", ""),
            "methodologyVersion": summary["meta"].get("methodologyVersion", ""),
            "revenue": revenue,
            "profit": profit,
            "profitBeforeTax": kpis.get("profitBeforeTax"),
            "margin": kpis.get("margin"),
            "rows": int(kpis.get("rowCount") or len(rows)),
            "lossRows": int(kpis.get("lossRows") or 0),
        },
        "topLosses": [
            {
                "product": row.get("product"),
                "article1c": row.get("article1c"),
                "barcode": row.get("barcode"),
                "profit": row.get("profit"),
                "lossDriver": row.get("lossDriver"),
                "status": row.get("status"),
            }
            for row in losses[:5]
        ],
        "quality": [
            {"status": status, "rows": count}
            for status, count in sorted(
                quality.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ],
    }


def client_draft_limitations(summary: dict[str, Any]) -> list[str]:
    limitations = []
    period_status = str(summary.get("meta", {}).get("periodStatus") or "")
    if "неполн" in period_status.casefold() or "предвар" in period_status.casefold():
        limitations.append(
            f"Период имеет статус «{period_status}» и не должен читаться как полный."
        )
    limitations.extend(
        [
            summary["meta"].get("returnReasonLimitation")
            or "Причины возвратов не передаются текущими источниками.",
            (
                "Упущенные продажи являются управленческой оценкой, "
                "не финальным прогнозом."
            ),
            "AI не меняет данные WB/1C и не выполняет отправку клиенту.",
        ]
    )
    return limitations


def import_dashboard_payload(
    db: Session,
    payload: dict[str, Any],
    *,
    tenant_id: str,
    tenant_name: str,
    report_id: str,
    source_workbook_path: str = "",
    lineage_type: str = "legacy_excel_import",
    publication_status: str = "published",
    publish: bool = True,
    source_snapshot_set_id: str = "",
) -> ReportRun:
    meta = payload["meta"]
    period_start, period_end = parse_period(meta["period"])
    source_coverage_start = date_or_none(meta.get("sourceCoverageStart"))
    source_coverage_end = date_or_none(meta.get("sourceCoverageEnd"))
    generated_at = datetime.now(UTC)
    tenant = ensure_tenant(db, tenant_id, tenant_name)
    client = ensure_client_for_tenant(
        db,
        tenant_id=tenant.id,
        name=meta.get("client", tenant_name),
    )
    client_name = client.name or meta.get("client", tenant_name)
    existing = db.get(ReportRun, report_id)
    if existing is not None:
        _clear_report_payload(db, report_id)
        report = existing
        report.tenant_id = tenant_id
        report.client_id = client.id
        report.client_name = client_name
        report.title = meta.get("title", "Кабинет юнит-экономики WB")
        report.period_start = period_start
        report.period_end = period_end
        report.source_coverage_start = source_coverage_start
        report.source_coverage_end = source_coverage_end
        report.period_text = meta.get("periodText", meta["period"])
        report.period_status = meta.get("periodStatus", "")
        report.generated_at = generated_at
        report.status = (
            "partial_period" if "непол" in meta.get("periodStatus", "") else "final"
        )
        report.publication_status = publication_status
        report.is_current = False
        report.lineage_type = lineage_type
        report.source_snapshot_set_id = source_snapshot_set_id
        report.methodology_version = meta.get("methodologyVersion", "")
        report.marketplace_expense_context_version = meta.get(
            "marketplaceExpenseContextVersion", ""
        )
        report.source_workbook = meta.get("sourceWorkbook", "")
        report.source_workbook_path = source_workbook_path
        report.return_reason_limitation = meta.get("returnReasonLimitation", "")
        db.flush()
    else:
        report = ReportRun(
            id=report_id,
            tenant_id=tenant_id,
            client_id=client.id,
            client_name=client_name,
            title=meta.get("title", "Кабинет юнит-экономики WB"),
            period_start=period_start,
            period_end=period_end,
            source_coverage_start=source_coverage_start,
            source_coverage_end=source_coverage_end,
            period_text=meta.get("periodText", meta["period"]),
            period_status=meta.get("periodStatus", ""),
            generated_at=generated_at,
            status=(
                "partial_period" if "непол" in meta.get("periodStatus", "") else "final"
            ),
            publication_status=publication_status,
            is_current=False,
            lineage_type=lineage_type,
            source_snapshot_set_id=source_snapshot_set_id,
            methodology_version=meta.get("methodologyVersion", ""),
            marketplace_expense_context_version=meta.get(
                "marketplaceExpenseContextVersion", ""
            ),
            source_workbook=meta.get("sourceWorkbook", ""),
            source_workbook_path=source_workbook_path,
            return_reason_limitation=meta.get("returnReasonLimitation", ""),
            created_at=security.utcnow(),
        )
        db.add(report)
    db.flush()
    for item in payload.get("unitRows", []):
        ids = _row_entity_ids(db, report, item)
        row_item = _row_item_with_resolved_cabinet(item, ids)
        db.add(
            _unit_row(
                report.id,
                row_item,
                client_id=ids["client_id"],
                client_company_id=ids["client_company_id"],
                wb_cabinet_id=ids["wb_cabinet_id"],
            )
        )
    for item in payload.get("lostSales", []):
        ids = _row_entity_ids(db, report, item)
        row_item = _row_item_with_resolved_cabinet(item, ids)
        db.add(
            _lost_sales_row(
                report.id,
                row_item,
                client_id=ids["client_id"],
                wb_cabinet_id=ids["wb_cabinet_id"],
            )
        )
    for item in payload.get("reconciliationMonthly", []):
        db.add(_reconciliation_row(report.id, item))
    for item in payload.get("marketplaceServiceRows", []):
        ids = _marketplace_expense_entity_ids(db, report, item)
        db.add(
            _marketplace_expense_row(
                report.id,
                item,
                client_id=ids["client_id"],
                client_company_id=ids["client_company_id"],
                wb_cabinet_id=ids["wb_cabinet_id"],
            )
        )
    for item in payload.get("documentReconciliation", []):
        ids = _row_entity_ids(db, report, item)
        row_item = _row_item_with_resolved_cabinet(item, ids)
        db.add(
            _document_reconciliation_row(
                report.id,
                row_item,
                client_id=ids["client_id"],
                client_company_id=ids["client_company_id"],
                wb_cabinet_id=ids["wb_cabinet_id"],
            )
        )
    db.add(
        SourceLoad(
            tenant_id=tenant_id,
            client_id=report.client_id,
            wb_cabinet_id="",
            report_run_id=report.id,
            source_refresh_run_id=None,
            required=False,
            source_type=lineage_type,
            source_label=report.source_workbook or lineage_type,
            status="loaded",
            snapshot_hash="",
            row_count=len(payload.get("unitRows", [])),
            loaded_at=generated_at,
        )
    )
    audit(
        db,
        action=(
            "report_imported"
            if lineage_type == "legacy_excel_import"
            else "report_marts_saved"
        ),
        tenant_id=tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "source": report.source_workbook,
            "lineageType": lineage_type,
            "publicationStatus": publication_status,
            "rows": len(payload.get("unitRows", [])),
        },
    )
    if publish and publication_status == "published":
        publish_report(db, report)
    return report


def save_report_marts(
    db: Session,
    payload: dict[str, Any],
    *,
    tenant_id: str,
    tenant_name: str,
    report_id: str,
    publication_status: str = "published",
    publish: bool = True,
    source_snapshot_set_id: str = "",
) -> ReportRun:
    report = import_dashboard_payload(
        db,
        payload,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        report_id=report_id,
        source_workbook_path="",
        lineage_type="db_first_report_marts",
        publication_status=publication_status,
        publish=publish,
        source_snapshot_set_id=source_snapshot_set_id,
    )
    db.flush()
    contexts = {
        as_text(item.get("id")): dict(item["calculationContext"])
        for item in payload.get("lostSales", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("calculationContext"), Mapping)
    }
    if contexts:
        rows = list(
            db.scalars(
                select(ReportLostSalesRow).where(
                    ReportLostSalesRow.report_run_id == report.id
                )
            )
        )
        persisted_ids = {row.row_uid for row in rows}
        if persisted_ids != set(contexts):
            raise ValueError(
                "ReportMarts lost-sales calculation contexts do not match rows."
            )
        for row in rows:
            row.calculation_context = contexts[row.row_uid]
        db.flush()
        persisted_contexts = dict(
            db.execute(
                select(
                    ReportLostSalesRow.row_uid,
                    ReportLostSalesRow.calculation_context,
                ).where(ReportLostSalesRow.report_run_id == report.id)
            ).all()
        )
        if any(
            not isinstance(persisted_contexts.get(row_uid), Mapping)
            or persisted_contexts[row_uid].get("version") != "lost-sales-filter-v1"
            for row_uid in contexts
        ):
            raise ValueError(
                "ReportMarts lost-sales calculation contexts were not persisted."
            )
    return report


def replace_source_loads_from_refresh(
    db: Session,
    report: ReportRun,
    refresh_run: SourceRefreshRun,
    *,
    base_refresh_run: SourceRefreshRun | None = None,
    contributing_runs: Iterable[SourceRefreshRun] = (),
) -> None:
    if (
        refresh_run.tenant_id != report.tenant_id
        or refresh_run.client_id != report.client_id
    ):
        raise ValueError("source refresh does not belong to report client")
    db.execute(delete(SourceLoad).where(SourceLoad.report_run_id == report.id))
    if base_refresh_run is not None and (
        base_refresh_run.tenant_id != report.tenant_id
        or base_refresh_run.client_id != report.client_id
    ):
        raise ValueError("base source refresh does not belong to report client")
    contributors = [
        item
        for item in contributing_runs
        if item.id not in {refresh_run.id, getattr(base_refresh_run, "id", None)}
    ]
    source_items: list[tuple[SourceRefreshRun, SourceRefreshCollection, str]] = []
    incremental_composite_types = {
        "wb_finance_detail",
        "wb_sales_report_list",
        "wb_redeem_notifications",
    }
    if base_refresh_run is not None:
        source_items.extend(
            (base_refresh_run, item, "base")
            for item in base_refresh_run.collections
            if item.source_type.startswith("wb_")
            and (
                refresh_run.mode != "incremental"
                or item.source_type in incremental_composite_types
            )
        )
    for contributor in contributors:
        source_items.extend(
            (contributor, item, "overlay")
            for item in contributor.collections
            if item.source_type.startswith("wb_")
            and (
                refresh_run.mode != "incremental"
                or item.source_type in incremental_composite_types
            )
        )
    if (
        base_refresh_run is not None
        and not contributors
        and refresh_run.mode != "incremental"
    ):
        current_types = {item.source_type for item in refresh_run.collections}
        source_items = [
            (run, item, role)
            for run, item, role in source_items
            if item.source_type not in current_types
        ]
    source_items.extend(
        (refresh_run, item, "current") for item in refresh_run.collections
    )
    seen_collection_ids: set[int] = set()
    for source_run, item, lineage_role in source_items:
        if item.id in seen_collection_ids:
            continue
        seen_collection_ids.add(item.id)
        if item.source_type.startswith("wb_"):
            coverage_start = source_run.source_window_start or source_run.period_start
            coverage_end = source_run.source_window_end or source_run.period_end
        else:
            coverage_start = source_run.period_start
            coverage_end = source_run.period_end
        db.add(
            SourceLoad(
                tenant_id=source_run.tenant_id,
                client_id=report.client_id,
                wb_cabinet_id=item.wb_cabinet_id,
                report_run_id=report.id,
                source_refresh_run_id=source_run.id,
                required=item.required,
                publication_required=item.publication_required,
                source_type=item.source_type,
                source_label=item.source_label,
                status=item.status,
                snapshot_hash=item.snapshot_hash,
                row_count=item.row_count,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                lineage_role=lineage_role,
                loaded_at=item.loaded_at,
            )
        )
    db.flush()


def replace_report_source_load_from_refresh(
    db: Session,
    report: ReportRun,
    refresh_run: SourceRefreshRun,
    *,
    source_type: str,
) -> None:
    """Replace one report source with the exact collection used for its build."""
    if (
        refresh_run.tenant_id != report.tenant_id
        or refresh_run.client_id != report.client_id
    ):
        raise ValueError("source refresh does not belong to report client")
    collections = [
        item for item in refresh_run.collections if item.source_type == source_type
    ]
    if not collections:
        raise ValueError(f"source refresh has no {source_type} collection")
    db.execute(
        delete(SourceLoad).where(
            SourceLoad.report_run_id == report.id,
            SourceLoad.source_type == source_type,
        )
    )
    for item in collections:
        db.add(
            SourceLoad(
                tenant_id=refresh_run.tenant_id,
                client_id=report.client_id,
                wb_cabinet_id=item.wb_cabinet_id,
                report_run_id=report.id,
                source_refresh_run_id=refresh_run.id,
                required=item.required,
                publication_required=item.publication_required,
                source_type=item.source_type,
                source_label=item.source_label,
                status=item.status,
                snapshot_hash=item.snapshot_hash,
                row_count=item.row_count,
                loaded_at=item.loaded_at,
            )
        )
    db.flush()


def reconcile_report_mapping_source_load(
    db: Session,
    report: ReportRun,
) -> dict[str, Any]:
    """Scope global mapping health to the products that are present in a report."""
    mapping_issue_count = int(_report_row_stats(db, report)["mapping_rows"])
    loads = list(
        db.scalars(
            select(SourceLoad).where(
                SourceLoad.report_run_id == report.id,
                SourceLoad.source_type == "sku_mapping",
            )
        )
    )
    updated = 0
    if mapping_issue_count == 0:
        for load in loads:
            if load.status == "needs_review":
                load.status = "loaded"
                updated += 1
    db.flush()
    return {
        "reportRunId": report.id,
        "mappingIssueRows": mapping_issue_count,
        "sourceLoadUpdated": updated > 0,
        "sourceLoadStatus": (
            "loaded"
            if loads and mapping_issue_count == 0
            else loads[0].status
            if loads
            else "missing"
        ),
    }


def publish_report(db: Session, report: ReportRun) -> ReportRun:
    db.flush()
    blockers = report_publication_blockers(db, report)
    if blockers:
        audit(
            db,
            action="report_publication_blocked",
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={"blockers": blockers},
        )
        raise ReportPublicationBlocked(blockers)
    _set_report_current(db, report)
    audit(
        db,
        action="report_published_current",
        tenant_id=report.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={"lineageType": report.lineage_type},
    )
    db.flush()
    return report


def publish_report_with_tasks(
    db: Session,
    report: ReportRun,
    *,
    user: User,
    reason: str,
) -> tuple[ReportRun, list[dict[str, Any]]]:
    """Publish an explicitly accepted draft while retaining blockers as Kanban tasks."""

    require_staff(user, report.tenant_id)
    audit_reason = reason.strip()
    if not audit_reason:
        raise ValueError("publication reason is required")
    db.flush()
    blockers = report_publication_blockers(db, report)
    if not blockers:
        return publish_report(db, report), []
    non_overridable = [
        item
        for item in blockers
        if item.get("code") == "company_cabinet_mismatch"
        or item.get("nonOverridable") is True
    ]
    if non_overridable:
        audit(
            db,
            action="report_publication_blocked",
            user=user,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={"blockers": non_overridable},
        )
        raise ReportPublicationBlocked(non_overridable)
    _set_report_current(db, report)
    audit(
        db,
        action="report_published_with_tasks",
        user=user,
        tenant_id=report.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "lineageType": report.lineage_type,
            "reason": audit_reason,
            "blockingTasks": [
                {
                    "code": as_text(item.get("code")),
                    "message": as_text(item.get("message")),
                    "count": item.get("count"),
                }
                for item in blockers
            ],
        },
    )
    db.flush()
    return report, blockers


def _set_report_current(db: Session, report: ReportRun) -> None:
    scope_filters = [
        ReportRun.tenant_id == report.tenant_id,
        ReportRun.client_id == report.client_id,
        ReportRun.report_kind == report.report_kind,
        ReportRun.id != report.id,
        ReportRun.is_current.is_(True),
    ]
    if report.report_kind in ACCOUNTING_REPORT_KINDS:
        if not report.organization_id:
            raise ValueError("organization is required for accounting report")
        scope_filters.append(ReportRun.organization_id == report.organization_id)
    else:
        scope_filters.append(ReportRun.organization_id.is_(None))
    previous_reports = list(db.scalars(select(ReportRun).where(*scope_filters)))
    for previous in previous_reports:
        previous.is_current = False
        if previous.publication_status == "published":
            previous.publication_status = "superseded"
    # The partial unique indexes enforce one current report per scope. Flush the
    # demotion before promoting the new revision so SQLite/PostgreSQL never see
    # two current rows within the same statement batch.
    db.flush()
    report.publication_status = "published"
    report.is_current = True


def _clear_report_payload(db: Session, report_id: str) -> None:
    if db.get(ReportLogisticsAnalysisContext, report_id) is not None:
        raise ValueError(
            "report run with logistics context is immutable; create a new report run"
        )
    for model in (
        ReportLogisticsSkuRow,
        ReportLogisticsOrderRow,
        ReportUnitRow,
        ReportLostSalesRow,
        ReportReconciliationMonthly,
        ReportMarketplaceExpenseRow,
        ReportDocumentReconciliationRow,
        ReportArtifact,
        SourceLoad,
        LiveCheckCache,
    ):
        db.execute(delete(model).where(model.report_run_id == report_id))


def replace_report_logistics_analysis(
    db: Session,
    report: ReportRun,
    result: LogisticsAnalysisResult,
) -> ReportLogisticsAnalysisContext:
    _validate_logistics_result_scope(db, report, result)
    existing = db.get(ReportLogisticsAnalysisContext, report.id)
    if existing is not None:
        raise ValueError("logistics analysis marts are immutable for a report")
    db.execute(
        delete(ReportLogisticsSkuRow).where(
            ReportLogisticsSkuRow.report_run_id == report.id
        )
    )
    db.execute(
        delete(ReportLogisticsOrderRow).where(
            ReportLogisticsOrderRow.report_run_id == report.id
        )
    )
    db.execute(
        delete(ReportLogisticsAnalysisContext).where(
            ReportLogisticsAnalysisContext.report_run_id == report.id
        )
    )
    context = result.context
    persisted = ReportLogisticsAnalysisContext(
        report_run_id=report.id,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        source_snapshot_set_id=report.source_snapshot_set_id,
        data_status=context.data_status,
        source_quality_status=context.source_quality_status,
        methodology_version=context.methodology_version,
        chain_key_version=context.chain_key_version,
        source_row_count=context.source_row_count,
        logistics_row_count=context.logistics_row_count,
        keyed_logistics_row_count=context.keyed_logistics_row_count,
        product_logistics_row_count=context.product_logistics_row_count,
        invalid_source_row_count=context.invalid_source_row_count,
        required_field_error_count=context.required_field_error_count,
        invalid_report_row_count=context.invalid_report_row_count,
        report_required_field_error_count=(context.report_required_field_error_count),
        chain_dimension_conflict_count=context.chain_dimension_conflict_count,
        invalid_source_payload_shape_count=(context.invalid_source_payload_shape_count),
        source_identity_error_count=context.source_identity_error_count,
        source_revision_conflict_count=(context.source_revision_conflict_count),
        source_revision_discarded_count=(context.source_revision_discarded_count),
        scope_mismatch_count=context.scope_mismatch_count,
        key_coverage_pct=context.key_coverage_pct,
        product_coverage_pct=context.product_coverage_pct,
        classification_row_coverage_pct=(context.classification_row_coverage_pct),
        cross_cabinet_collision_count=context.cross_cabinet_collision_count,
        raw_order_uid_cross_cabinet_reuse_count=(
            context.raw_order_uid_cross_cabinet_reuse_count
        ),
        unmatched_source_dimension_count=(context.unmatched_source_dimension_count),
        unmatched_report_dimension_count=(context.unmatched_report_dimension_count),
        dimension_delta_count=context.dimension_delta_count,
        max_dimension_delta=context.max_dimension_delta,
        raw_logistics_total=context.raw_logistics_total,
        order_logistics_total=context.order_logistics_total,
        sku_logistics_total=context.sku_logistics_total,
        report_logistics_total=context.report_logistics_total,
        order_delta=context.order_delta,
        sku_delta=context.sku_delta,
        blocking_reasons=list(context.blocking_reasons),
        review_reasons=list(context.review_reasons),
        input_hash=context.input_hash,
        created_at=security.utcnow(),
    )
    db.add(persisted)
    for row in result.order_rows:
        db.add(
            ReportLogisticsOrderRow(
                report_run_id=report.id,
                tenant_id=row.tenant_id,
                client_id=row.client_id,
                wb_cabinet_id=row.wb_cabinet_id,
                client_company_id=row.client_company_id,
                chain_key=row.chain_key,
                chain_segment_key=row.chain_segment_key,
                countable_order=row.countable_order,
                financial_date=row.financial_date,
                financial_week_start=row.financial_week_start,
                operation_date_start=row.operation_date_start,
                operation_date_end=row.operation_date_end,
                order_date=row.order_date,
                order_period_status=row.order_period_status,
                product_ref=row.product_ref,
                product_key=row.product_key,
                nm_id=row.nm_id,
                sku=row.sku,
                vendor_code=row.vendor_code,
                product=row.product,
                scheme=row.scheme,
                warehouse=row.warehouse,
                warehouse_status=row.warehouse_status,
                destination=row.destination,
                destination_status=row.destination_status,
                logistics_total=row.logistics_total,
                logistics_forward=row.logistics_forward,
                logistics_reverse=row.logistics_reverse,
                logistics_adjustment=row.logistics_adjustment,
                logistics_unclassified=row.logistics_unclassified,
                sales_quantity=row.sales_quantity,
                return_quantity=row.return_quantity,
                net_quantity=row.net_quantity,
                source_revenue=row.source_revenue,
                source_row_count=row.source_row_count,
                logistics_row_count=row.logistics_row_count,
                classified_row_count=row.classified_row_count,
                source_hash_digest=row.source_hash_digest,
                classification_status=row.classification_status,
                coverage_status=row.coverage_status,
                data_quality_status=row.data_quality_status,
            )
        )
    for row in result.sku_rows:
        row_uid = hashlib.sha256(
            "\x1f".join(
                (
                    report.id,
                    row.tenant_id,
                    row.client_id,
                    row.financial_week_start.isoformat(),
                    row.wb_cabinet_id,
                    row.client_company_id,
                    row.scheme,
                    row.product_key,
                )
            ).encode()
        ).hexdigest()
        db.add(
            ReportLogisticsSkuRow(
                report_run_id=report.id,
                tenant_id=row.tenant_id,
                client_id=row.client_id,
                row_uid=row_uid,
                financial_week_start=row.financial_week_start,
                financial_week_end=row.financial_week_end,
                wb_cabinet_id=row.wb_cabinet_id,
                client_company_id=row.client_company_id,
                scheme=row.scheme,
                product_ref=row.product_ref,
                product_key=row.product_key,
                nm_id=row.nm_id,
                sku=row.sku,
                vendor_code=row.vendor_code,
                product=row.product,
                logistics_total=row.logistics_total,
                logistics_forward=row.logistics_forward,
                logistics_reverse=row.logistics_reverse,
                logistics_adjustment=row.logistics_adjustment,
                logistics_unclassified=row.logistics_unclassified,
                # Legacy non-null columns keep real logistics-source facts.
                # v5 financial queries use the nullable report-linked columns.
                revenue=row.source_revenue,
                financial_revenue=row.revenue,
                profit_before_tax=row.profit_before_tax,
                profit_without_logistics=row.profit_without_logistics,
                profit_effect_amount=(
                    row.profit_effect_amount
                    if row.profit_effect_amount is not None
                    else -row.logistics_total
                ),
                logistics_share_pct=row.logistics_share_pct,
                logistics_per_order=row.logistics_per_order,
                logistics_per_sale=row.logistics_per_sale,
                sales_quantity=row.sales_quantity,
                return_quantity=row.return_quantity,
                chain_count=row.chain_count,
                logistics_row_count=row.logistics_row_count,
                classified_row_count=row.classified_row_count,
                low_sample=row.low_sample,
                classification_status=row.classification_status,
                coverage_status=row.coverage_status,
                data_quality_status=row.data_quality_status,
                recommendation_flags=list(row.recommendation_flags),
                source_hash_digest=row.source_hash_digest,
            )
        )
    report.logistics_analysis_required = True
    audit(
        db,
        action="report_logistics_analysis_saved",
        tenant_id=report.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "dataStatus": context.data_status,
            "methodologyVersion": context.methodology_version,
            "chainKeyVersion": context.chain_key_version,
            "orderRows": len(result.order_rows),
            "skuRows": len(result.sku_rows),
        },
    )
    db.flush()
    return persisted


def replace_report_logistics_dimension_rows(
    db: Session,
    report: ReportRun,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    """Persist F-1 rows внутри ещё не опубликованного immutable report run.

    Габариты/вес/объём/штраф сохраняются как есть, включая ``None`` — пропуск
    остаётся явным, а не нулём.
    """
    if report.publication_status != "draft" or report.is_current:
        raise ValueError("published logistics dimension mart is immutable")
    db.execute(
        delete(ReportLogisticsDimensionRow).where(
            ReportLogisticsDimensionRow.report_run_id == report.id
        )
    )
    count = 0
    for row in rows:
        db.add(
            ReportLogisticsDimensionRow(
                report_run_id=report.id,
                tenant_id=str(row.get("tenant_id") or report.tenant_id),
                client_id=str(row.get("client_id") or report.client_id),
                row_uid=str(row["row_uid"]),
                wb_cabinet_id=str(row.get("wb_cabinet_id", "")),
                client_company_id=str(row.get("client_company_id", "")),
                scheme=str(row.get("scheme", "")),
                product_ref=str(row.get("product_ref", "")),
                product_key=str(row.get("product_key", "")),
                nm_id=str(row.get("nm_id", "")),
                sku=str(row.get("sku", "")),
                vendor_code=str(row.get("vendor_code", "")),
                product=str(row.get("product", "")),
                length_cm=row.get("length_cm"),
                width_cm=row.get("width_cm"),
                height_cm=row.get("height_cm"),
                weight_brutto_kg=row.get("weight_brutto_kg"),
                volume_l=row.get("volume_l"),
                dimensions_valid=row.get("dimensions_valid"),
                measured_penalty_amount=row.get("measured_penalty_amount"),
                evidence_type=str(row.get("evidence_type", "")),
                coverage_status=str(row.get("coverage_status", "")),
                data_quality_status=str(row.get("data_quality_status", "")),
                source_hash_digest=str(row.get("source_hash_digest", "")),
            )
        )
        count += 1
    db.flush()
    return count


def replace_report_logistics_dimension_analysis(
    db: Session,
    report: ReportRun,
    *,
    context: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> ReportLogisticsDimensionContext:
    """Atomically stage F-1 context and rows for a draft report."""

    if report.publication_status != "draft" or report.is_current:
        raise ValueError("published logistics dimension analysis is immutable")
    if str(context.get("tenant_id") or "") != report.tenant_id:
        raise ValueError("dimension context tenant does not match report")
    if str(context.get("client_id") or "") != report.client_id:
        raise ValueError("dimension context client does not match report")
    status = str(context.get("data_status") or "")
    if status not in {"ready", "partial", "blocked"}:
        raise ValueError("unsupported dimension context status")
    if status == "blocked" and rows:
        raise ValueError("blocked dimension context cannot persist mart rows")
    _validate_logistics_dimension_rows_scope(db, report, rows)
    expected_count = int(context.get("dimension_row_count") or 0)
    if expected_count != len(rows):
        raise ValueError("dimension context row count does not match mart")

    db.execute(
        delete(ReportLogisticsDimensionContext).where(
            ReportLogisticsDimensionContext.report_run_id == report.id
        )
    )
    replace_report_logistics_dimension_rows(db, report, rows)
    persisted = ReportLogisticsDimensionContext(
        report_run_id=report.id,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        factor_methodology_version=str(context["factor_methodology_version"]),
        data_status=status,
        input_hash=str(context.get("input_hash") or ""),
        source_snapshot_hash=str(context.get("source_snapshot_hash") or ""),
        source_loaded_at=context.get("source_loaded_at"),
        source_row_count=int(context.get("source_row_count") or 0),
        dimension_row_count=expected_count,
        matched_product_count=int(context.get("matched_product_count") or 0),
        missing_product_count=int(context.get("missing_product_count") or 0),
        invalid_product_count=int(context.get("invalid_product_count") or 0),
        conflicting_product_count=int(
            context.get("conflicting_product_count") or 0
        ),
        signal_product_count=int(context.get("signal_product_count") or 0),
        blocking_reasons=list(context.get("blocking_reasons") or []),
        review_reasons=list(context.get("review_reasons") or []),
        created_at=context.get("created_at") or datetime.now(UTC),
    )
    db.add(persisted)
    report.logistics_dimensions_required = True
    audit(
        db,
        action="report_logistics_dimensions_saved",
        tenant_id=report.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "dataStatus": status,
            "factorMethodologyVersion": persisted.factor_methodology_version,
            "dimensionRows": expected_count,
        },
    )
    db.flush()
    return persisted


def report_logistics_dimension_rows(
    db: Session, report_run_id: str
) -> list[ReportLogisticsDimensionRow]:
    return list(
        db.scalars(
            select(ReportLogisticsDimensionRow)
            .where(ReportLogisticsDimensionRow.report_run_id == report_run_id)
            .order_by(ReportLogisticsDimensionRow.product_ref)
        )
    )


def report_logistics_dimensions_payload(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    scheme: str = "",
    product_query: str = "",
    sort_by: str = "product",
    sort_order: str = "asc",
    offset: int = 0,
    limit: int = 250,
) -> dict[str, Any]:
    logistics_context = db.get(ReportLogisticsAnalysisContext, report.id)
    context = db.get(ReportLogisticsDimensionContext, report.id)
    state = _logistics_dimension_context_state(report, context)
    base_state = _logistics_context_state(report, logistics_context)
    filter_context = {
        "periodStart": period_start.isoformat() if period_start else None,
        "periodEnd": period_end.isoformat() if period_end else None,
        "wbCabinetId": wb_cabinet_id or None,
        "clientCompanyId": client_company_id or None,
        "scheme": scheme.casefold() or None,
        "product": product_query.strip() or None,
        "dateGrain": "calendar_day",
    }
    meta = {
        "reportId": report.id,
        "dataStatus": "needs_rebuild",
        "sliceStatus": "needs_rebuild",
        "methodologyVersion": (
            logistics_context.methodology_version
            if logistics_context is not None
            else LOGISTICS_METHODOLOGY_VERSION
        ),
        "factorMethodologyVersion": LOGISTICS_FACTORS_METHODOLOGY_VERSION,
        "generatedAt": (
            context.created_at.isoformat()
            if context is not None
            else report.generated_at.isoformat()
        ),
        "sourceCoverageEnd": (
            report.source_coverage_end.isoformat()
            if report.source_coverage_end
            else None
        ),
        "factorSnapshotAt": (
            context.source_loaded_at.isoformat()
            if context is not None and context.source_loaded_at is not None
            else None
        ),
        "valueType": "fact",
        "filterContext": filter_context,
    }
    empty_payload = {
        **meta,
        "coverage": _empty_logistics_dimension_coverage(),
        "rows": [],
        "total": 0,
        "offset": offset,
        "limit": limit,
        "recommendations": [],
    }
    if base_state == "blocked" or state in {"blocked", "scope_mismatch"}:
        return _logistics_json_safe(
            {**empty_payload, "dataStatus": "blocked", "sliceStatus": "blocked"}
        )
    if base_state not in {"ready", "partial"} or state not in {"ready", "partial"}:
        return _logistics_json_safe(empty_payload)

    order_conditions = _logistics_order_conditions(
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
    )
    active_product_refs = (
        select(ReportLogisticsOrderRow.product_ref)
        .where(*order_conditions)
        .distinct()
    )
    conditions: list[Any] = [
        ReportLogisticsDimensionRow.report_run_id == report.id,
        ReportLogisticsDimensionRow.product_ref.in_(active_product_refs),
    ]
    if wb_cabinet_id:
        conditions.append(ReportLogisticsDimensionRow.wb_cabinet_id == wb_cabinet_id)
    if client_company_id:
        conditions.append(
            ReportLogisticsDimensionRow.client_company_id == client_company_id
        )
    if scheme:
        conditions.append(ReportLogisticsDimensionRow.scheme == scheme.casefold())

    stats = db.execute(
        select(
            func.count(),
            func.coalesce(
                func.sum(
                    case(
                        (ReportLogisticsDimensionRow.coverage_status == "ready", 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            ReportLogisticsDimensionRow.coverage_status
                            == "missing_dimensions",
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            ReportLogisticsDimensionRow.coverage_status.in_(
                                {"invalid_dimensions", "identity_conflict"}
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            ReportLogisticsDimensionRow.coverage_status
                            == "conflicting_dimensions",
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (ReportLogisticsDimensionRow.dimensions_valid.is_(False), 1),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(*conditions)
    ).one()
    total = int(stats[0] or 0)
    with_dimensions = int(stats[1] or 0)
    missing = int(stats[2] or 0)
    invalid = int(stats[3] or 0)
    conflicting = int(stats[4] or 0)
    signals = int(stats[5] or 0)
    coverage = {
        "total": total,
        "withDimensions": with_dimensions,
        "missingDimensions": missing,
        "invalidDimensions": invalid,
        "conflictingDimensions": conflicting,
        "signalCount": signals,
        "coveragePct": (
            Decimal(with_dimensions) * Decimal("100") / Decimal(total)
            if total
            else None
        ),
    }
    if total == 0:
        return _logistics_json_safe(
            {
                **empty_payload,
                "dataStatus": context.data_status,
                "sliceStatus": "empty",
                "coverage": coverage,
            }
        )
    sort_fields = {
        "product": ReportLogisticsDimensionRow.product,
        "volumeL": ReportLogisticsDimensionRow.volume_l,
        "weightBruttoKg": ReportLogisticsDimensionRow.weight_brutto_kg,
        "coverageStatus": ReportLogisticsDimensionRow.coverage_status,
    }
    sort_column = sort_fields[sort_by]
    direction = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    rows = list(
        db.scalars(
            select(ReportLogisticsDimensionRow)
            .where(*conditions)
            .order_by(
                case((sort_column.is_(None), 1), else_=0),
                direction,
                ReportLogisticsDimensionRow.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    slice_status = (
        "partial"
        if context.data_status == "partial" or missing or invalid or conflicting
        else "ready"
    )
    recommendations: list[dict[str, Any]] = []
    if signals:
        recommendations.append(
            {
                "code": "dimension_card_signal",
                "priority": 30,
                "title": "Проверить упаковку и карточку товара",
                "message": (
                    "WB отметил часть карточек сигналом isValid=false. "
                    "Это ограничение данных, а не подтверждённый штраф."
                ),
                "impactAmount": None,
                "evidenceType": "limitation",
                "actionTarget": "#logistics-dimensions",
                "actionLabel": "Посмотреть габариты",
                "evidence": {"productCount": signals},
            }
        )
    unavailable = missing + invalid + conflicting
    if unavailable:
        recommendations.append(
            {
                "code": "dimension_data_unavailable",
                "priority": 40,
                "title": "Проверить данные габаритов",
                "message": (
                    "Для части товаров габариты отсутствуют, невалидны или "
                    "конфликтуют; значения не подставлены нулями."
                ),
                "impactAmount": None,
                "evidenceType": "data_unavailable",
                "actionTarget": "#logistics-dimensions",
                "actionLabel": "Проверить источник",
                "evidence": {"productCount": unavailable},
            }
        )
    return _logistics_json_safe(
        {
            **meta,
            "dataStatus": context.data_status,
            "sliceStatus": slice_status,
            "coverage": coverage,
            "rows": [_logistics_dimension_row_payload(row) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
            "recommendations": recommendations,
        }
    )


def _logistics_dimension_context_state(
    report: ReportRun,
    context: ReportLogisticsDimensionContext | None,
) -> str:
    if context is None:
        return "missing"
    if context.factor_methodology_version != LOGISTICS_FACTORS_METHODOLOGY_VERSION:
        return "outdated_methodology"
    if context.tenant_id != report.tenant_id or context.client_id != report.client_id:
        return "scope_mismatch"
    if context.data_status not in {"ready", "partial", "blocked"}:
        return "invalid_status"
    return context.data_status


def _empty_logistics_dimension_coverage() -> dict[str, Any]:
    return {
        "total": 0,
        "withDimensions": 0,
        "missingDimensions": 0,
        "invalidDimensions": 0,
        "conflictingDimensions": 0,
        "signalCount": 0,
        "coveragePct": None,
    }


def _logistics_dimension_row_payload(
    row: ReportLogisticsDimensionRow,
) -> dict[str, Any]:
    return {
        "productRef": row.product_ref,
        "nmId": row.nm_id,
        "product": row.product,
        "vendorCode": row.vendor_code,
        "scheme": row.scheme,
        "lengthCm": row.length_cm,
        "widthCm": row.width_cm,
        "heightCm": row.height_cm,
        "weightBruttoKg": row.weight_brutto_kg,
        "volumeL": row.volume_l,
        "dimensionsValid": row.dimensions_valid,
        "measuredPenaltyAmount": row.measured_penalty_amount,
        "evidenceType": row.evidence_type,
        "coverageStatus": row.coverage_status,
        "dataQualityStatus": row.data_quality_status,
    }


def _validate_logistics_dimension_rows_scope(
    db: Session,
    report: ReportRun,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    cabinet_ids: set[str] = set()
    company_ids: set[str] = set()
    for row in rows:
        if str(row.get("tenant_id") or "") != report.tenant_id:
            raise ValueError("dimension row tenant does not match report")
        if str(row.get("client_id") or "") != report.client_id:
            raise ValueError("dimension row client does not match report")
        cabinet_id = str(row.get("wb_cabinet_id") or "")
        company_id = str(row.get("client_company_id") or "")
        if cabinet_id:
            cabinet_ids.add(cabinet_id)
        if company_id:
            company_ids.add(company_id)
    cabinets = {
        item.id: item
        for item in db.scalars(select(WbCabinet).where(WbCabinet.id.in_(cabinet_ids)))
    } if cabinet_ids else {}
    companies = {
        item.id: item
        for item in db.scalars(
            select(ClientCompany).where(ClientCompany.id.in_(company_ids))
        )
    } if company_ids else {}
    for row in rows:
        cabinet_id = str(row.get("wb_cabinet_id") or "")
        company_id = str(row.get("client_company_id") or "")
        cabinet = cabinets.get(cabinet_id)
        company = companies.get(company_id)
        if (
            cabinet is None
            or company is None
            or cabinet.tenant_id != report.tenant_id
            or cabinet.client_id != report.client_id
            or cabinet.client_company_id != company_id
            or company.tenant_id != report.tenant_id
            or company.client_id != report.client_id
        ):
            raise ValueError(
                "dimension row cabinet/company scope does not match report"
            )


def _validate_logistics_result_scope(
    db: Session,
    report: ReportRun,
    result: LogisticsAnalysisResult,
) -> None:
    if result.context.scope_mismatch_count and result.context.data_status != "blocked":
        raise ValueError("logistics scope mismatch must block marts")
    rows = (*result.order_rows, *result.sku_rows)
    for row in rows:
        if row.tenant_id != report.tenant_id or row.client_id != report.client_id:
            raise ValueError("logistics row scope does not match report")
    cabinet_ids = {row.wb_cabinet_id for row in rows if row.wb_cabinet_id}
    company_ids = {row.client_company_id for row in rows if row.client_company_id}
    cabinets = (
        {
            item.id: item
            for item in db.scalars(
                select(WbCabinet).where(WbCabinet.id.in_(cabinet_ids))
            )
        }
        if cabinet_ids
        else {}
    )
    companies = (
        {
            item.id: item
            for item in db.scalars(
                select(ClientCompany).where(ClientCompany.id.in_(company_ids))
            )
        }
        if company_ids
        else {}
    )
    for row in rows:
        cabinet = cabinets.get(row.wb_cabinet_id)
        company = companies.get(row.client_company_id)
        if (
            cabinet is None
            or company is None
            or cabinet.tenant_id != report.tenant_id
            or cabinet.client_id != report.client_id
            or company.tenant_id != report.tenant_id
            or company.client_id != report.client_id
            or cabinet.client_company_id != company.id
        ):
            raise ValueError("logistics cabinet or company scope does not match report")


def report_logistics_summary_payload(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    scheme: str = "",
    product_query: str = "",
) -> dict[str, Any]:
    context = db.get(ReportLogisticsAnalysisContext, report.id)
    meta = _report_logistics_slice_meta(
        db,
        report,
        context,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
    )
    if not _logistics_context_usable(report, context):
        return _logistics_json_safe(
            {
                **meta,
                "kpis": _empty_logistics_kpis(),
                "dynamics": [],
                "components": _empty_logistics_components(),
                "rankings": {
                    "byTotal": [],
                    "byRevenueShare": [],
                    "byProfitEffect": [],
                },
                "recommendations": _logistics_recommendations(
                    _logistics_context_state(report, context),
                    context,
                ),
            }
        )
    if meta["sliceStatus"] == "empty":
        return _logistics_json_safe(
            {
                **meta,
                "kpis": _empty_logistics_kpis(),
                "dynamics": [],
                "components": _empty_logistics_components(),
                "rankings": {
                    "byTotal": [],
                    "byRevenueShare": [],
                    "byProfitEffect": [],
                },
                "recommendations": [],
            }
        )
    order_conditions = _logistics_order_conditions(
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
    )
    totals = db.execute(
        select(
            func.coalesce(func.sum(ReportLogisticsOrderRow.logistics_total), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.logistics_forward), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.logistics_reverse), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.logistics_adjustment), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.logistics_unclassified), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.sales_quantity), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.return_quantity), 0),
            func.count(
                func.distinct(
                    case(
                        (
                            ReportLogisticsOrderRow.countable_order.is_(True),
                            ReportLogisticsOrderRow.chain_key,
                        ),
                        else_=None,
                    )
                )
            ),
        ).where(*order_conditions)
    ).one()
    logistics_total = decimal_value(totals[0])
    sales_quantity = decimal_value(totals[5])
    return_quantity = decimal_value(totals[6])
    order_count = int(totals[7] or 0)
    financial_status = meta["financialMetricStatus"]
    revenue: Decimal | None = None
    profit_before_tax: Decimal | None = None
    if financial_status == "ready":
        sku_conditions = _logistics_sku_conditions(
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            scheme=scheme,
            product_query="" if product_query.strip() else product_query,
        )
        if product_query.strip():
            sku_conditions.append(
                _logistics_sku_product_ref_condition(order_conditions)
            )
        financials = db.execute(
            select(
                func.sum(ReportLogisticsSkuRow.financial_revenue),
                func.sum(ReportLogisticsSkuRow.profit_before_tax),
            ).where(*sku_conditions)
        ).one()
        revenue = (
            decimal_value(financials[0]) if financials[0] is not None else None
        )
        profit_before_tax = (
            decimal_value(financials[1]) if financials[1] is not None else None
        )
    dynamics = _logistics_dynamics(
        db,
        report,
        order_conditions=order_conditions,
        financial_status=financial_status,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
    )
    ranking_args = {
        "period_start": period_start,
        "period_end": period_end,
        "wb_cabinet_id": wb_cabinet_id,
        "client_company_id": client_company_id,
        "scheme": scheme,
        "product_query": product_query,
        "financial_status": financial_status,
        "offset": 0,
        "limit": 10,
    }
    by_total, _ = _query_logistics_products(
        db, report, sort_by="logisticsTotal", sort_order="desc", **ranking_args
    )
    by_profit: list[dict[str, Any]] = []
    if financial_status == "ready":
        by_profit, _ = _query_logistics_products(
            db, report, sort_by="profitEffectAmount", sort_order="asc", **ranking_args
        )
    by_reverse, _ = _query_logistics_products(
        db,
        report,
        sort_by="logisticsReverse",
        sort_order="desc",
        **{**ranking_args, "limit": 1},
    )
    by_share: list[dict[str, Any]] = []
    if financial_status == "ready":
        by_share, _ = _query_logistics_products(
            db,
            report,
            sort_by="logisticsSharePct",
            sort_order="desc",
            **ranking_args,
        )

    return _logistics_json_safe(
        {
            **meta,
            "kpis": {
                "logisticsTotal": logistics_total,
                "logisticsSharePct": (
                    _positive_share(logistics_total, revenue)
                    if revenue is not None
                    else None
                ),
                "profitEffectAmount": (
                    -logistics_total if financial_status == "ready" else None
                ),
                "profitBeforeTax": profit_before_tax,
                "profitWithoutLogistics": (
                    profit_before_tax + logistics_total
                    if profit_before_tax is not None
                    else None
                ),
                "logisticsPerOrder": (
                    logistics_total / order_count if order_count else None
                ),
                "logisticsPerSale": (
                    logistics_total / sales_quantity if sales_quantity > 0 else None
                ),
                "orderCount": order_count,
                "salesQuantity": sales_quantity,
                "returnQuantity": return_quantity,
                "revenue": revenue,
            },
            "dynamics": dynamics,
            "components": {
                "forward": decimal_value(totals[1]),
                "reverse": decimal_value(totals[2]),
                "adjustment": decimal_value(totals[3]),
                "unclassified": decimal_value(totals[4]),
            },
            "rankings": {
                "byTotal": by_total,
                "byRevenueShare": by_share,
                "byProfitEffect": by_profit,
            },
            "recommendations": _logistics_recommendations(
                _logistics_context_state(report, context),
                context,
                total_leader=by_total[0] if by_total else None,
                reverse_leader=(
                    by_reverse[0]
                    if by_reverse
                    and decimal_value(by_reverse[0]["logisticsReverse"]) > 0
                    else None
                ),
                share_leader=by_share[0] if by_share else None,
                classification_coverage=meta["coverage"]["classificationPct"],
                data_quality_issue_count=meta["coverage"]["dataQualityIssues"],
                data_quality_issue_amount=meta["coverage"][
                    "dataQualityIssueAmount"
                ],
                missing_profit_link_count=meta["coverage"]["missingProfitLinks"],
                missing_profit_link_amount=meta["coverage"][
                    "missingProfitLinkAmount"
                ],
                unclassified_amount=decimal_value(totals[4]),
            ),
        }
    )


def report_logistics_products_payload(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    scheme: str = "",
    product_query: str = "",
    sort_by: str = "logisticsTotal",
    sort_order: str = "desc",
    offset: int = 0,
    limit: int = 250,
) -> dict[str, Any]:
    context = db.get(ReportLogisticsAnalysisContext, report.id)
    meta = _report_logistics_slice_meta(
        db,
        report,
        context,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
    )
    if not _logistics_context_usable(report, context):
        return _logistics_json_safe(
            {**meta, "items": [], "total": 0, "offset": offset, "limit": limit}
        )
    items, total = _query_logistics_products(
        db,
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
        financial_status=meta["financialMetricStatus"],
        sort_by=sort_by,
        sort_order=sort_order,
        offset=offset,
        limit=limit,
    )
    return _logistics_json_safe(
        {
            **meta,
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    )


def report_logistics_orders_payload(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    scheme: str = "",
    product_query: str = "",
    product_ref: str = "",
    sort_by: str = "operationDateEnd",
    sort_order: str = "desc",
    offset: int = 0,
    limit: int = 250,
) -> dict[str, Any]:
    context = db.get(ReportLogisticsAnalysisContext, report.id)
    meta = _report_logistics_slice_meta(
        db,
        report,
        context,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
        product_ref=product_ref,
    )
    if not _logistics_context_usable(report, context):
        return _logistics_json_safe(
            {**meta, "items": [], "total": 0, "offset": offset, "limit": limit}
        )
    conditions = _logistics_order_conditions(
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
        product_ref=product_ref,
    )
    sort_fields = {
        "chainRef": ReportLogisticsOrderRow.chain_key,
        "financialDate": ReportLogisticsOrderRow.financial_date,
        "operationDateEnd": ReportLogisticsOrderRow.financial_date,
        "orderDate": ReportLogisticsOrderRow.order_date,
        "logisticsForward": ReportLogisticsOrderRow.logistics_forward,
        "logisticsReverse": ReportLogisticsOrderRow.logistics_reverse,
        "logisticsTotal": ReportLogisticsOrderRow.logistics_total,
        "salesQuantity": ReportLogisticsOrderRow.sales_quantity,
        "returnQuantity": ReportLogisticsOrderRow.return_quantity,
        "classificationStatus": ReportLogisticsOrderRow.classification_status,
        "product": ReportLogisticsOrderRow.product,
    }
    sort_column = sort_fields.get(sort_by, ReportLogisticsOrderRow.financial_date)
    direction = (
        sort_column.asc() if sort_order.casefold() == "asc" else sort_column.desc()
    )
    total = int(
        db.scalar(
            select(func.count()).select_from(ReportLogisticsOrderRow).where(*conditions)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(ReportLogisticsOrderRow)
            .where(*conditions)
            .order_by(
                case((sort_column.is_(None), 1), else_=0),
                direction,
                ReportLogisticsOrderRow.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return _logistics_json_safe(
        {
            **meta,
            "items": [_logistics_order_payload(row) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    )


def _report_logistics_meta(
    report: ReportRun,
    context: ReportLogisticsAnalysisContext | None,
) -> dict[str, Any]:
    context_state = _logistics_context_state(report, context)
    if context_state in {
        "missing",
        "outdated_methodology",
        "outdated_chain_key",
        "invalid_status",
        "scope_mismatch",
    }:
        return {
            "reportId": report.id,
            "dataStatus": "needs_rebuild",
            "sliceStatus": "needs_rebuild",
            "methodologyVersion": LOGISTICS_METHODOLOGY_VERSION,
            "classifierVersion": LOGISTICS_CLASSIFIER_VERSION,
            "chainKeyVersion": CHAIN_KEY_VERSION,
            "generatedAt": report.generated_at.isoformat(),
            "sourceCoverageEnd": (
                report.source_coverage_end.isoformat()
                if report.source_coverage_end
                else None
            ),
            "financialMetricStatus": "not_available",
            "valueType": "fact",
            "coverage": {
                "keyPct": None,
                "productPct": None,
                "classificationPct": None,
                "logisticsRows": 0,
                "keyedRows": 0,
                "productRows": 0,
                "classifiedRows": 0,
                "dataQualityIssues": 0,
                "dataQualityIssueAmount": None,
                "missingProfitLinks": 0,
                "missingProfitLinkAmount": None,
                "lowSampleProductCount": None,
            },
            "reportCoverage": None,
            "filterContext": {},
        }
    return {
        "reportId": report.id,
        "dataStatus": context_state,
        "sliceStatus": context_state,
        "methodologyVersion": context.methodology_version,
        "classifierVersion": LOGISTICS_CLASSIFIER_VERSION,
        "chainKeyVersion": context.chain_key_version,
        "generatedAt": context.created_at.isoformat(),
        "sourceCoverageEnd": (
            report.source_coverage_end.isoformat()
            if report.source_coverage_end
            else None
        ),
        "financialMetricStatus": "ready",
        "valueType": "fact",
        "coverage": {
            "keyPct": context.key_coverage_pct,
            "productPct": context.product_coverage_pct,
            "classificationPct": context.classification_row_coverage_pct,
            "logisticsRows": context.logistics_row_count,
            "keyedRows": context.keyed_logistics_row_count,
            "productRows": context.product_logistics_row_count,
            "crossCabinetCollisions": context.cross_cabinet_collision_count,
            "classifiedRows": None,
            "dataQualityIssues": 0,
            "dataQualityIssueAmount": Decimal("0"),
            "missingProfitLinks": 0,
            "missingProfitLinkAmount": Decimal("0"),
            "lowSampleProductCount": None,
        },
        "reportCoverage": _report_logistics_coverage(context),
        "filterContext": {},
    }


def _logistics_context_usable(
    report: ReportRun,
    context: ReportLogisticsAnalysisContext | None,
) -> bool:
    return _logistics_context_state(report, context) in {"ready", "partial"}


def _logistics_context_state(
    report: ReportRun,
    context: ReportLogisticsAnalysisContext | None,
) -> str:
    if context is None:
        return "missing"
    if context.methodology_version != LOGISTICS_METHODOLOGY_VERSION:
        return "outdated_methodology"
    if context.chain_key_version != CHAIN_KEY_VERSION:
        return "outdated_chain_key"
    if context.tenant_id != report.tenant_id or context.client_id != report.client_id:
        return "scope_mismatch"
    if context.data_status not in {"ready", "partial", "blocked"}:
        return "invalid_status"
    return context.data_status


def _report_logistics_slice_meta(
    db: Session,
    report: ReportRun,
    context: ReportLogisticsAnalysisContext | None,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
    product_ref: str = "",
) -> dict[str, Any]:
    meta = _report_logistics_meta(report, context)
    financial_status = _logistics_financial_metric_status(
        report, period_start=period_start, period_end=period_end
    )
    filter_context = {
        "periodStart": period_start.isoformat() if period_start else None,
        "periodEnd": period_end.isoformat() if period_end else None,
        "wbCabinetId": wb_cabinet_id or None,
        "clientCompanyId": client_company_id or None,
        "scheme": scheme.casefold() or None,
        "product": product_query.strip() or None,
        "productRef": product_ref or None,
        "dateGrain": "calendar_day",
    }
    meta["filterContext"] = filter_context
    if not _logistics_context_usable(report, context):
        meta["financialMetricStatus"] = "not_available"
        return meta
    conditions = _logistics_order_conditions(
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
        product_ref=product_ref,
    )
    counts = db.execute(
        select(
            func.coalesce(func.sum(ReportLogisticsOrderRow.logistics_row_count), 0),
            func.coalesce(func.sum(ReportLogisticsOrderRow.classified_row_count), 0),
            func.coalesce(
                func.sum(
                    case(
                        (ReportLogisticsOrderRow.data_quality_status != "ready", 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            ReportLogisticsOrderRow.data_quality_status != "ready",
                            ReportLogisticsOrderRow.logistics_total,
                        ),
                        else_=Decimal("0"),
                    )
                ),
                0,
            ),
        ).where(*conditions)
    ).one()
    logistics_rows = int(counts[0] or 0)
    classified_rows = int(counts[1] or 0)
    data_quality_issues = int(counts[2] or 0)
    data_quality_issue_amount = decimal_value(counts[3])
    sku_conditions = _logistics_sku_conditions(
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query="",
    )
    if product_query.strip() or product_ref:
        sku_conditions.append(_logistics_sku_product_ref_condition(conditions))
    missing_profit_metrics = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(ReportLogisticsSkuRow.logistics_total), 0),
        )
        .select_from(ReportLogisticsSkuRow)
        .where(
            *sku_conditions,
            ReportLogisticsSkuRow.data_quality_status == "missing_profit_link",
        )
    ).one()
    missing_profit_links = int(missing_profit_metrics[0] or 0)
    missing_profit_link_amount = decimal_value(missing_profit_metrics[1])
    product_samples = (
        select(
            ReportLogisticsOrderRow.product_ref.label("product_ref"),
            func.count(
                func.distinct(
                    case(
                        (
                            ReportLogisticsOrderRow.countable_order.is_(True),
                            ReportLogisticsOrderRow.chain_key,
                        ),
                        else_=None,
                    )
                )
            ).label("order_count"),
        )
        .where(*conditions)
        .group_by(ReportLogisticsOrderRow.product_ref)
        .having(func.sum(ReportLogisticsOrderRow.logistics_row_count) > 0)
        .subquery()
    )
    low_sample_product_count = int(
        db.scalar(
            select(func.count())
            .select_from(product_samples)
            .where(product_samples.c.order_count < LOW_SAMPLE_THRESHOLD)
        )
        or 0
    )
    meta["coverage"] = {
        "keyPct": Decimal("100") if logistics_rows else None,
        "productPct": Decimal("100") if logistics_rows else None,
        "classificationPct": (
            Decimal(classified_rows) * 100 / Decimal(logistics_rows)
            if logistics_rows
            else None
        ),
        "logisticsRows": logistics_rows,
        "keyedRows": logistics_rows,
        "productRows": logistics_rows,
        "classifiedRows": classified_rows,
        "dataQualityIssues": data_quality_issues,
        "dataQualityIssueAmount": data_quality_issue_amount,
        "missingProfitLinks": missing_profit_links,
        "missingProfitLinkAmount": missing_profit_link_amount,
        "lowSampleProductCount": low_sample_product_count,
    }
    meta["sliceStatus"] = (
        "empty"
        if logistics_rows == 0
        else "partial"
        if (
            classified_rows != logistics_rows
            or data_quality_issues
            or missing_profit_links
        )
        else "ready"
    )
    meta["financialMetricStatus"] = (
        "not_available_empty_slice"
        if logistics_rows == 0
        else "not_available_missing_profit_link"
        if missing_profit_links
        else financial_status
    )
    return meta


def _report_logistics_coverage(
    context: ReportLogisticsAnalysisContext,
) -> dict[str, Any]:
    return {
        "keyPct": context.key_coverage_pct,
        "productPct": context.product_coverage_pct,
        "classificationPct": context.classification_row_coverage_pct,
        "logisticsRows": context.logistics_row_count,
        "keyedRows": context.keyed_logistics_row_count,
        "productRows": context.product_logistics_row_count,
        "invalidRows": context.invalid_source_row_count,
        "requiredFieldErrors": context.required_field_error_count,
        "invalidReportRows": context.invalid_report_row_count,
        "reportRequiredFieldErrors": context.report_required_field_error_count,
        "chainDimensionConflicts": context.chain_dimension_conflict_count,
        "invalidSourcePayloadShapes": (context.invalid_source_payload_shape_count),
        "sourceIdentityErrors": context.source_identity_error_count,
        "sourceRevisionConflicts": context.source_revision_conflict_count,
        "sourceRevisionsDiscarded": context.source_revision_discarded_count,
        "scopeMismatches": context.scope_mismatch_count,
        "unmatchedSourceDimensions": context.unmatched_source_dimension_count,
        "unmatchedReportDimensions": context.unmatched_report_dimension_count,
        "dimensionDeltaCount": context.dimension_delta_count,
        "maxDimensionDelta": context.max_dimension_delta,
        "compositeKeyCollisions": context.cross_cabinet_collision_count,
        "rawOrderUidCrossCabinetReuse": (
            context.raw_order_uid_cross_cabinet_reuse_count
        ),
    }


def _logistics_financial_metric_status(
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
) -> str:
    effective_start = period_start or report.period_start
    effective_end = period_end or report.period_end
    if effective_start.weekday() != 0 or effective_end.weekday() != 6:
        return "not_available_partial_week"
    return "ready"


def _logistics_order_conditions(
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
    product_ref: str = "",
) -> list[Any]:
    conditions = _logistics_order_scope_conditions(
        ReportLogisticsOrderRow,
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_ref=product_ref,
    )
    query = product_query.strip()
    if query:
        matched_row = aliased(ReportLogisticsOrderRow)
        matched_conditions = _logistics_order_scope_conditions(
            matched_row,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            scheme=scheme,
            product_ref=product_ref,
        )
        pattern = f"%{query}%"
        matched_product_refs = (
            select(matched_row.product_ref)
            .where(
                *matched_conditions,
                or_(
                    matched_row.product.ilike(pattern),
                    matched_row.vendor_code.ilike(pattern),
                    matched_row.nm_id.ilike(pattern),
                    matched_row.sku.ilike(pattern),
                ),
            )
            .distinct()
        )
        conditions.append(
            ReportLogisticsOrderRow.product_ref.in_(matched_product_refs)
        )
    return conditions


def _logistics_order_scope_conditions(
    row: Any,
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_ref: str,
) -> list[Any]:
    conditions: list[Any] = [row.report_run_id == report.id]
    if period_start is not None:
        conditions.append(row.financial_date >= period_start)
    if period_end is not None:
        conditions.append(row.financial_date <= period_end)
    if wb_cabinet_id:
        conditions.append(row.wb_cabinet_id == wb_cabinet_id)
    if client_company_id:
        conditions.append(row.client_company_id == client_company_id)
    if scheme:
        conditions.append(row.scheme == scheme.casefold())
    if product_ref:
        conditions.append(row.product_ref == product_ref)
    return conditions


def _logistics_sku_conditions(
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
) -> list[Any]:
    conditions: list[Any] = [ReportLogisticsSkuRow.report_run_id == report.id]
    if period_start is not None:
        conditions.append(ReportLogisticsSkuRow.financial_week_start >= period_start)
    if period_end is not None:
        conditions.append(ReportLogisticsSkuRow.financial_week_end <= period_end)
    if wb_cabinet_id:
        conditions.append(ReportLogisticsSkuRow.wb_cabinet_id == wb_cabinet_id)
    if client_company_id:
        conditions.append(ReportLogisticsSkuRow.client_company_id == client_company_id)
    if scheme:
        conditions.append(ReportLogisticsSkuRow.scheme == scheme.casefold())
    query = product_query.strip()
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(
                ReportLogisticsSkuRow.product.ilike(pattern),
                ReportLogisticsSkuRow.vendor_code.ilike(pattern),
                ReportLogisticsSkuRow.nm_id.ilike(pattern),
                ReportLogisticsSkuRow.sku.ilike(pattern),
            )
        )
    return conditions


def _logistics_sku_product_ref_condition(order_conditions: Sequence[Any]) -> Any:
    product_refs = (
        select(ReportLogisticsOrderRow.product_ref)
        .where(*order_conditions)
        .distinct()
    )
    return ReportLogisticsSkuRow.product_ref.in_(product_refs)


def _query_logistics_products(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
    financial_status: str,
    sort_by: str,
    sort_order: str,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    order_conditions = _logistics_order_conditions(
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        scheme=scheme,
        product_query=product_query,
    )
    orders = (
        select(
            ReportLogisticsOrderRow.product_ref.label("product_ref"),
            func.min(ReportLogisticsOrderRow.product_key).label("product_key"),
            func.min(ReportLogisticsOrderRow.nm_id).label("nm_id"),
            func.min(ReportLogisticsOrderRow.sku).label("sku"),
            func.min(ReportLogisticsOrderRow.vendor_code).label("vendor_code"),
            func.min(ReportLogisticsOrderRow.product).label("product"),
            func.sum(ReportLogisticsOrderRow.logistics_total).label("logistics_total"),
            func.sum(ReportLogisticsOrderRow.logistics_forward).label(
                "logistics_forward"
            ),
            func.sum(ReportLogisticsOrderRow.logistics_reverse).label(
                "logistics_reverse"
            ),
            func.sum(ReportLogisticsOrderRow.logistics_adjustment).label(
                "logistics_adjustment"
            ),
            func.sum(ReportLogisticsOrderRow.logistics_unclassified).label(
                "logistics_unclassified"
            ),
            func.sum(ReportLogisticsOrderRow.sales_quantity).label("sales_quantity"),
            func.sum(ReportLogisticsOrderRow.return_quantity).label("return_quantity"),
            func.count(
                func.distinct(
                    case(
                        (
                            ReportLogisticsOrderRow.countable_order.is_(True),
                            ReportLogisticsOrderRow.chain_key,
                        ),
                        else_=None,
                    )
                )
            ).label("order_count"),
            func.sum(ReportLogisticsOrderRow.logistics_row_count).label(
                "logistics_row_count"
            ),
            func.sum(ReportLogisticsOrderRow.classified_row_count).label(
                "classified_row_count"
            ),
            func.sum(
                case(
                    (ReportLogisticsOrderRow.data_quality_status != "ready", 1),
                    else_=0,
                )
            ).label("order_quality_issue_count"),
        )
        .where(*order_conditions)
        .group_by(ReportLogisticsOrderRow.product_ref)
        .having(func.sum(ReportLogisticsOrderRow.logistics_row_count) > 0)
        .subquery()
    )
    total = int(db.scalar(select(func.count()).select_from(orders)) or 0)
    financials = (
        select(
            ReportLogisticsSkuRow.product_ref.label("product_ref"),
            func.sum(ReportLogisticsSkuRow.financial_revenue).label("revenue"),
            func.sum(ReportLogisticsSkuRow.profit_before_tax).label(
                "profit_before_tax"
            ),
            func.sum(
                case(
                    (ReportLogisticsSkuRow.data_quality_status != "ready", 1),
                    else_=0,
                )
            ).label("sku_quality_issue_count"),
            func.sum(
                case(
                    (
                        ReportLogisticsSkuRow.data_quality_status
                        == "missing_profit_link",
                        1,
                    ),
                    else_=0,
                )
            ).label("missing_profit_link_count"),
        )
        .where(
            *_logistics_sku_conditions(
                report,
                period_start=period_start,
                period_end=period_end,
                wb_cabinet_id=wb_cabinet_id,
                client_company_id=client_company_id,
                scheme=scheme,
                product_query="",
            )
        )
        .group_by(ReportLogisticsSkuRow.product_ref)
        .subquery()
    )
    revenue_expr = (
        financials.c.revenue if financial_status == "ready" else literal(None)
    )
    profit_expr = (
        financials.c.profit_before_tax
        if financial_status == "ready"
        else literal(None)
    )
    statement = (
        select(orders)
        .add_columns(
            revenue_expr.label("revenue"),
            profit_expr.label("profit_before_tax"),
            financials.c.sku_quality_issue_count.label("sku_quality_issue_count"),
            financials.c.missing_profit_link_count.label(
                "missing_profit_link_count"
            ),
        )
        .outerjoin(financials, financials.c.product_ref == orders.c.product_ref)
    )
    share_expr = case(
        (
            revenue_expr > 0,
            orders.c.logistics_total / revenue_expr * 100,
        ),
        else_=None,
    )
    quality_expr = case(
        (
            or_(
                orders.c.classified_row_count != orders.c.logistics_row_count,
                orders.c.order_quality_issue_count > 0,
                financials.c.sku_quality_issue_count > 0
                if financial_status == "ready"
                else literal(False),
            ),
            2,
        ),
        (orders.c.order_count < LOW_SAMPLE_THRESHOLD, 1),
        else_=0,
    )
    sort_expressions = {
        "logisticsTotal": orders.c.logistics_total,
        "logisticsReverse": orders.c.logistics_reverse,
        "logisticsSharePct": share_expr,
        "profitEffectAmount": (
            -orders.c.logistics_total if financial_status == "ready" else literal(None)
        ),
        "revenue": revenue_expr,
        "orderCount": orders.c.order_count,
        "returnQuantity": orders.c.return_quantity,
        "product": orders.c.product,
        "quality": quality_expr,
    }
    sort_expression = sort_expressions.get(sort_by, orders.c.logistics_total)
    direction = (
        sort_expression.asc()
        if sort_order.casefold() == "asc"
        else sort_expression.desc()
    )
    statement = (
        statement.order_by(
            case((sort_expression.is_(None), 1), else_=0),
            direction,
            orders.c.product_ref.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    items: list[dict[str, Any]] = []
    for row in db.execute(statement).mappings():
        logistics_total = decimal_value(row["logistics_total"])
        revenue = decimal_value(row["revenue"]) if row["revenue"] is not None else None
        profit = (
            decimal_value(row["profit_before_tax"])
            if row["profit_before_tax"] is not None
            else None
        )
        sales = decimal_value(row["sales_quantity"])
        order_count = int(row["order_count"] or 0)
        logistics_rows = int(row["logistics_row_count"] or 0)
        classified_rows = int(row["classified_row_count"] or 0)
        data_quality_issues = int(row["order_quality_issue_count"] or 0) + int(
            row["sku_quality_issue_count"] or 0
        )
        missing_profit_links = int(row["missing_profit_link_count"] or 0)
        flags: list[str] = []
        if classified_rows != logistics_rows:
            flags.append("restore_classification")
        if decimal_value(row["logistics_reverse"]) != 0:
            flags.append("check_returns")
        if revenue is not None and revenue > 0 and logistics_total != 0:
            flags.append("check_margin")
        if missing_profit_links:
            flags.append("restore_profit_link")
        items.append(
            {
                "productRef": row["product_ref"],
                "productKey": row["product_key"],
                "nmId": row["nm_id"],
                "sku": row["sku"],
                "vendorCode": row["vendor_code"],
                "product": row["product"],
                "logisticsTotal": logistics_total,
                "logisticsForward": decimal_value(row["logistics_forward"]),
                "logisticsReverse": decimal_value(row["logistics_reverse"]),
                "logisticsAdjustment": decimal_value(row["logistics_adjustment"]),
                "logisticsUnclassified": decimal_value(row["logistics_unclassified"]),
                "revenue": revenue,
                "profitBeforeTax": profit,
                "profitWithoutLogistics": (
                    profit + logistics_total if profit is not None else None
                ),
                "profitEffectAmount": (
                    -logistics_total if financial_status == "ready" else None
                ),
                "logisticsSharePct": (
                    _positive_share(logistics_total, revenue)
                    if revenue is not None
                    else None
                ),
                "logisticsPerOrder": (
                    logistics_total / order_count if order_count else None
                ),
                "logisticsPerSale": (logistics_total / sales if sales > 0 else None),
                "salesQuantity": sales,
                "returnQuantity": decimal_value(row["return_quantity"]),
                "orderCount": order_count,
                "logisticsRowCount": logistics_rows,
                "lowSample": order_count < LOW_SAMPLE_THRESHOLD,
                "classificationStatus": (
                    "ready" if classified_rows == logistics_rows else "partial"
                ),
                "dataQualityStatus": (
                    "missing_profit_link"
                    if missing_profit_links
                    else "partial"
                    if data_quality_issues
                    else "ready"
                ),
                "recommendationFlags": flags,
            }
        )
    return items, total


def _logistics_dynamics(
    db: Session,
    report: ReportRun,
    *,
    order_conditions: Sequence[Any],
    financial_status: str,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
) -> list[dict[str, Any]]:
    order_rows = db.execute(
        select(
            ReportLogisticsOrderRow.financial_week_start,
            func.sum(ReportLogisticsOrderRow.logistics_total),
        )
        .where(*order_conditions)
        .group_by(ReportLogisticsOrderRow.financial_week_start)
        .order_by(ReportLogisticsOrderRow.financial_week_start)
    ).all()
    revenue_by_week: dict[date, Decimal] = {}
    if financial_status == "ready":
        sku_conditions = _logistics_sku_conditions(
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            scheme=scheme,
            product_query="" if product_query.strip() else product_query,
        )
        if product_query.strip():
            sku_conditions.append(
                _logistics_sku_product_ref_condition(order_conditions)
            )
        for week_start, revenue in db.execute(
            select(
                ReportLogisticsSkuRow.financial_week_start,
                func.sum(ReportLogisticsSkuRow.financial_revenue),
            )
            .where(*sku_conditions)
            .group_by(ReportLogisticsSkuRow.financial_week_start)
        ):
            revenue_by_week[week_start] = decimal_value(revenue)
    result: list[dict[str, Any]] = []
    for week_start, logistics in order_rows:
        logistics_total = decimal_value(logistics)
        revenue = revenue_by_week.get(week_start)
        result.append(
            {
                "periodStart": week_start.isoformat(),
                "logisticsTotal": logistics_total,
                "revenue": revenue,
                "logisticsSharePct": (
                    _positive_share(logistics_total, revenue)
                    if revenue is not None
                    else None
                ),
            }
        )
    return result


def _filtered_logistics_sku_rows(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
) -> list[ReportLogisticsSkuRow]:
    conditions: list[Any] = [ReportLogisticsSkuRow.report_run_id == report.id]
    if period_start is not None:
        conditions.append(ReportLogisticsSkuRow.financial_week_start >= period_start)
    if period_end is not None:
        conditions.append(ReportLogisticsSkuRow.financial_week_start <= period_end)
    if wb_cabinet_id:
        conditions.append(ReportLogisticsSkuRow.wb_cabinet_id == wb_cabinet_id)
    if client_company_id:
        conditions.append(ReportLogisticsSkuRow.client_company_id == client_company_id)
    if scheme:
        conditions.append(ReportLogisticsSkuRow.scheme == scheme.casefold())
    query = product_query.strip()
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(
                ReportLogisticsSkuRow.product.ilike(pattern),
                ReportLogisticsSkuRow.vendor_code.ilike(pattern),
                ReportLogisticsSkuRow.nm_id.ilike(pattern),
                ReportLogisticsSkuRow.sku.ilike(pattern),
            )
        )
    return list(
        db.scalars(
            select(ReportLogisticsSkuRow)
            .where(*conditions)
            .order_by(
                ReportLogisticsSkuRow.financial_week_start,
                ReportLogisticsSkuRow.product_key,
            )
        )
    )


def _filtered_logistics_order_rows(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    wb_cabinet_id: str,
    client_company_id: str,
    scheme: str,
    product_query: str,
    product_key: str = "",
) -> list[ReportLogisticsOrderRow]:
    conditions: list[Any] = [ReportLogisticsOrderRow.report_run_id == report.id]
    if period_start is not None:
        conditions.append(ReportLogisticsOrderRow.financial_week_start >= period_start)
    if period_end is not None:
        conditions.append(ReportLogisticsOrderRow.financial_week_start <= period_end)
    if wb_cabinet_id:
        conditions.append(ReportLogisticsOrderRow.wb_cabinet_id == wb_cabinet_id)
    if client_company_id:
        conditions.append(
            ReportLogisticsOrderRow.client_company_id == client_company_id
        )
    if scheme:
        conditions.append(ReportLogisticsOrderRow.scheme == scheme.casefold())
    if product_key:
        conditions.append(ReportLogisticsOrderRow.product_key == product_key)
    query = product_query.strip()
    if query:
        pattern = f"%{query}%"
        conditions.append(
            or_(
                ReportLogisticsOrderRow.product.ilike(pattern),
                ReportLogisticsOrderRow.vendor_code.ilike(pattern),
                ReportLogisticsOrderRow.nm_id.ilike(pattern),
                ReportLogisticsOrderRow.sku.ilike(pattern),
            )
        )
    return list(
        db.scalars(
            select(ReportLogisticsOrderRow)
            .where(*conditions)
            .order_by(
                ReportLogisticsOrderRow.operation_date_end.desc(),
                ReportLogisticsOrderRow.id.desc(),
            )
        )
    )


def _aggregate_logistics_products(
    sku_rows: Iterable[ReportLogisticsSkuRow],
    order_rows: Iterable[ReportLogisticsOrderRow],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in sku_rows:
        bucket = buckets.setdefault(
            row.product_key,
            {
                "productKey": row.product_key,
                "nmId": row.nm_id,
                "sku": row.sku,
                "vendorCode": row.vendor_code,
                "product": row.product,
                "logisticsTotal": Decimal("0"),
                "logisticsForward": Decimal("0"),
                "logisticsReverse": Decimal("0"),
                "logisticsAdjustment": Decimal("0"),
                "logisticsUnclassified": Decimal("0"),
                "revenue": Decimal("0"),
                "revenueKnown": False,
                "profitBeforeTax": Decimal("0"),
                "profitKnown": False,
                "salesQuantity": Decimal("0"),
                "returnQuantity": Decimal("0"),
                "logisticsRowCount": 0,
                "chains": set(),
                "recommendationFlags": set(),
                "classificationStatuses": set(),
                "dataQualityStatuses": set(),
            },
        )
        for target, source in (
            ("logisticsTotal", row.logistics_total),
            ("logisticsForward", row.logistics_forward),
            ("logisticsReverse", row.logistics_reverse),
            ("logisticsAdjustment", row.logistics_adjustment),
            ("logisticsUnclassified", row.logistics_unclassified),
            ("salesQuantity", row.sales_quantity),
            ("returnQuantity", row.return_quantity),
        ):
            bucket[target] += decimal_value(source)
        if row.financial_revenue is not None:
            bucket["revenue"] += decimal_value(row.financial_revenue)
            bucket["revenueKnown"] = True
        if row.profit_before_tax is not None:
            bucket["profitBeforeTax"] += decimal_value(row.profit_before_tax)
            bucket["profitKnown"] = True
        bucket["recommendationFlags"].update(row.recommendation_flags or [])
        bucket["classificationStatuses"].add(row.classification_status)
        bucket["dataQualityStatuses"].add(row.data_quality_status)
        bucket["logisticsRowCount"] += int(row.logistics_row_count or 0)
    for row in order_rows:
        bucket = buckets.get(row.product_key)
        if bucket is not None and row.countable_order and row.chain_key:
            bucket["chains"].add(row.chain_key)

    result: list[dict[str, Any]] = []
    for bucket in buckets.values():
        order_count = len(bucket.pop("chains"))
        profit_known = bool(bucket.pop("profitKnown"))
        revenue_known = bool(bucket.pop("revenueKnown"))
        flags = sorted(bucket.pop("recommendationFlags"))
        classification_statuses = bucket.pop("classificationStatuses")
        quality_statuses = bucket.pop("dataQualityStatuses")
        logistics_total = decimal_value(bucket["logisticsTotal"])
        revenue = decimal_value(bucket["revenue"]) if revenue_known else None
        sales = decimal_value(bucket["salesQuantity"])
        profit = decimal_value(bucket["profitBeforeTax"]) if profit_known else None
        result.append(
            {
                **bucket,
                "profitBeforeTax": profit,
                "profitEffectAmount": -logistics_total if revenue_known else None,
                "profitWithoutLogistics": (
                    profit + logistics_total if profit is not None else None
                ),
                "logisticsSharePct": (
                    _positive_share(logistics_total, revenue)
                    if revenue is not None
                    else None
                ),
                "logisticsPerOrder": (
                    logistics_total / order_count if order_count else None
                ),
                "logisticsPerSale": (logistics_total / sales if sales > 0 else None),
                "orderCount": order_count,
                "lowSample": order_count < LOW_SAMPLE_THRESHOLD,
                "classificationStatus": (
                    "ready" if classification_statuses == {"ready"} else "partial"
                ),
                "dataQualityStatus": (
                    "missing_profit_link"
                    if "missing_profit_link" in quality_statuses
                    else "ready"
                    if quality_statuses == {"ready"}
                    else "partial"
                ),
                "recommendationFlags": flags,
            }
        )
    return result


def _logistics_order_payload(row: ReportLogisticsOrderRow) -> dict[str, Any]:
    return {
        "chainRef": row.chain_key[:12],
        "financialDate": (
            row.financial_date.isoformat() if row.financial_date else None
        ),
        "financialWeekStart": row.financial_week_start.isoformat(),
        "operationDateStart": row.operation_date_start.isoformat(),
        "operationDateEnd": row.operation_date_end.isoformat(),
        "orderDate": row.order_date.isoformat() if row.order_date else None,
        "orderPeriodStatus": row.order_period_status,
        "productRef": row.product_ref,
        "productKey": row.product_key,
        "nmId": row.nm_id,
        "sku": row.sku,
        "vendorCode": row.vendor_code,
        "product": row.product,
        "scheme": row.scheme,
        "warehouse": row.warehouse,
        "warehouseStatus": row.warehouse_status,
        "destination": row.destination,
        "destinationStatus": row.destination_status,
        "logisticsTotal": row.logistics_total,
        "logisticsForward": row.logistics_forward,
        "logisticsReverse": row.logistics_reverse,
        "logisticsAdjustment": row.logistics_adjustment,
        "logisticsUnclassified": row.logistics_unclassified,
        "salesQuantity": row.sales_quantity,
        "returnQuantity": row.return_quantity,
        "netQuantity": row.net_quantity,
        "sourceRevenue": row.source_revenue,
        "sourceRowCount": row.source_row_count,
        "classificationStatus": row.classification_status,
        "coverageStatus": row.coverage_status,
        "dataQualityStatus": row.data_quality_status,
        "valueType": "fact",
    }


def _logistics_recommendations(
    context_state: str,
    context: ReportLogisticsAnalysisContext | None,
    *,
    total_leader: dict[str, Any] | None = None,
    reverse_leader: dict[str, Any] | None = None,
    share_leader: dict[str, Any] | None = None,
    classification_coverage: Decimal | None = None,
    data_quality_issue_count: int = 0,
    data_quality_issue_amount: Decimal = Decimal("0"),
    missing_profit_link_count: int = 0,
    missing_profit_link_amount: Decimal = Decimal("0"),
    unclassified_amount: Decimal = Decimal("0"),
) -> list[dict[str, Any]]:
    if context_state in {
        "missing",
        "outdated_methodology",
        "outdated_chain_key",
        "invalid_status",
        "scope_mismatch",
    }:
        return [
            {
                "code": "rebuild_report",
                "priority": 1,
                "title": "Пересобрать отчёт на новом снимке",
                "message": ("Для этого отчёта ещё нет проверенной витрины логистики."),
                "valueType": "fact",
                "impactAmount": None,
                "evidenceType": "data_quality",
                "actionTarget": None,
                "actionLabel": "",
                "evidence": {"dataStatus": "needs_rebuild"},
            }
        ]
    if context_state == "blocked" and context is not None:
        return [
            {
                "code": "restore_data_gate",
                "priority": 1,
                "title": "Сначала восстановить данные",
                "message": (
                    "Расчёт остановлен: обязательная сверка источника не пройдена."
                ),
                "valueType": "fact",
                "impactAmount": None,
                "evidenceType": "data_quality",
                "actionTarget": None,
                "actionLabel": "",
                "evidence": {
                    "keyCoveragePct": context.key_coverage_pct,
                    "productCoveragePct": context.product_coverage_pct,
                    "crossCabinetCollisions": (context.cross_cabinet_collision_count),
                    "invalidRows": context.invalid_source_row_count,
                    "invalidReportRows": context.invalid_report_row_count,
                    "reportRequiredFieldErrors": (
                        context.report_required_field_error_count
                    ),
                    "chainDimensionConflicts": (context.chain_dimension_conflict_count),
                    "invalidSourcePayloadShapes": (
                        context.invalid_source_payload_shape_count
                    ),
                    "sourceIdentityErrors": (context.source_identity_error_count),
                    "sourceRevisionConflicts": (context.source_revision_conflict_count),
                    "scopeMismatches": context.scope_mismatch_count,
                    "unmatchedSourceDimensions": (
                        context.unmatched_source_dimension_count
                    ),
                    "unmatchedReportDimensions": (
                        context.unmatched_report_dimension_count
                    ),
                    "maxDimensionDelta": context.max_dimension_delta,
                },
            }
        ]
    recommendations: list[dict[str, Any]] = []
    if missing_profit_link_count:
        recommendations.append(
            {
                "code": "restore_profit_link",
                "priority": 1,
                "title": "Восстановить финансовую связь с отчётом",
                "message": (
                    "Финансовые KPI выбранного среза скрыты, пока хотя бы один "
                    "товар логистики не связан со строкой отчёта."
                ),
                "valueType": "fact",
                "impactAmount": missing_profit_link_amount,
                "evidenceType": "data_quality",
                "actionTarget": "source",
                "actionLabel": "Проверить связь с отчётом",
                "evidence": {"affectedSkuRows": missing_profit_link_count},
            }
        )
    if reverse_leader is not None:
        recommendations.append(
            {
                "code": "check_returns",
                "priority": 1,
                "title": "Проверить возвратную логистику",
                "message": (
                    "Начните с товара с наибольшей возвратной частью. "
                    "Причина недоступна в Finance."
                ),
                "valueType": "fact",
                "impactAmount": reverse_leader["logisticsReverse"],
                "evidenceType": "limitation",
                "actionTarget": "products",
                "actionLabel": "Открыть товары",
                "evidence": {
                    "productRef": reverse_leader["productRef"],
                    "productKey": reverse_leader["productKey"],
                    "product": reverse_leader["product"],
                    "reverseLogistics": reverse_leader["logisticsReverse"],
                    "returnQuantity": reverse_leader["returnQuantity"],
                },
            }
        )
    if share_leader is not None:
        recommendations.append(
            {
                "code": "check_margin",
                "priority": 2,
                "title": "Проверить цену, упаковку и маржинальность",
                "message": (
                    "У товара максимальная доля логистики в положительной "
                    "выручке выбранного среза."
                ),
                "valueType": "fact",
                "impactAmount": share_leader["logisticsTotal"],
                "evidenceType": "fact",
                "actionTarget": "products",
                "actionLabel": "Открыть товары",
                "evidence": {
                    "productRef": share_leader["productRef"],
                    "productKey": share_leader["productKey"],
                    "product": share_leader["product"],
                    "logisticsSharePct": share_leader["logisticsSharePct"],
                    "lowSample": share_leader["lowSample"],
                },
            }
        )
    if classification_coverage is not None and classification_coverage != Decimal(
        "100"
    ):
        recommendations.append(
            {
                "code": "restore_classification",
                "priority": 1,
                "title": "Проверить нераспределённые операции",
                "message": (
                    "Часть логистики входит в общий расход, но направление "
                    "операции пока не подтверждено."
                ),
                "valueType": "fact",
                "impactAmount": unclassified_amount,
                "evidenceType": "data_quality",
                "actionTarget": "source",
                "actionLabel": "Проверить операции",
                "evidence": {"classificationCoveragePct": classification_coverage},
            }
        )
    if data_quality_issue_count:
        recommendations.append(
            {
                "code": "review_data_quality",
                "priority": 1,
                "title": "Проверить качество исходных данных",
                "message": (
                    "В выбранном срезе есть товарные цепочки с неполными или "
                    "противоречивыми исходными данными."
                ),
                "valueType": "fact",
                "impactAmount": data_quality_issue_amount,
                "evidenceType": "data_quality",
                "actionTarget": "source",
                "actionLabel": "Открыть исходные данные",
                "evidence": {"affectedOrderRows": data_quality_issue_count},
            }
        )
    if not recommendations and total_leader is not None:
        recommendations.append(
            {
                "code": "check_top_logistics",
                "priority": 2,
                "title": "Проверить товар с максимальной логистикой",
                "message": (
                    "Это крупнейшая сумма логистики в выбранном срезе."
                ),
                "valueType": "fact",
                "impactAmount": total_leader["logisticsTotal"],
                "evidenceType": "fact",
                "actionTarget": "products",
                "actionLabel": "Открыть товары",
                "evidence": {
                    "productRef": total_leader["productRef"],
                    "productKey": total_leader["productKey"],
                    "product": total_leader["product"],
                },
            }
        )
    return sorted(
        recommendations,
        key=lambda item: (
            item["priority"],
            item["impactAmount"] is None,
            -abs(decimal_value(item["impactAmount"]))
            if item["impactAmount"] is not None
            else Decimal("0"),
            item["code"],
        ),
    )


def _sum_decimal(rows: Iterable[Any], field: str) -> Decimal:
    return sum(
        (decimal_value(getattr(row, field)) for row in rows),
        Decimal("0"),
    )


def _positive_share(amount: Decimal, revenue: Decimal) -> Decimal | None:
    return amount / revenue * Decimal("100") if revenue > 0 else None


def _empty_logistics_kpis() -> dict[str, Any]:
    return {
        "logisticsTotal": None,
        "logisticsSharePct": None,
        "profitEffectAmount": None,
        "profitBeforeTax": None,
        "profitWithoutLogistics": None,
        "logisticsPerOrder": None,
        "logisticsPerSale": None,
        "orderCount": 0,
        "salesQuantity": None,
        "returnQuantity": None,
        "revenue": None,
    }


def _empty_logistics_components() -> dict[str, None]:
    return {
        "forward": None,
        "reverse": None,
        "adjustment": None,
        "unclassified": None,
    }


def _logistics_json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _logistics_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_logistics_json_safe(item) for item in value]
    return value


def _row_entity_ids(
    db: Session,
    report: ReportRun,
    item: dict[str, Any],
) -> dict[str, str]:
    client_id = as_text(item.get("clientId")) or report.client_id
    organization = as_text(item.get("organization"))
    cabinet_name = as_text(item.get("cabinet"))
    company_id = as_text(item.get("clientCompanyId"))
    wb_cabinet_id = as_text(item.get("wbCabinetId"))
    wb_cabinet_label = ""
    company = db.get(ClientCompany, company_id) if company_id else None
    if company_id and (company is None or company.client_id != client_id):
        raise ValueError("report row client company does not belong to report client")
    cabinet = db.get(WbCabinet, wb_cabinet_id) if wb_cabinet_id else None
    if wb_cabinet_id and (cabinet is None or cabinet.client_id != client_id):
        raise ValueError("report row WB cabinet does not belong to report client")
    if (
        company is not None
        and cabinet is not None
        and cabinet.client_company_id
        and cabinet.client_company_id != company.id
    ):
        cabinet_company = db.get(ClientCompany, cabinet.client_company_id)
        same_onec_organization = bool(
            cabinet_company is not None
            and cabinet_company.client_id == client_id
            and company.onec_organization_id
            and company.onec_organization_id == cabinet_company.onec_organization_id
        )
        if not same_onec_organization:
            raise ValueError("report row company does not match the WB cabinet company")
        company = cabinet_company
        company_id = cabinet_company.id
    if not company_id and cabinet is not None and cabinet.client_company_id:
        company_id = cabinet.client_company_id
        company = db.get(ClientCompany, company_id)
    if not wb_cabinet_id:
        cabinet = _single_active_wb_provider_cabinet(
            db, client_id=client_id, client_company_id=company_id
        )
        if cabinet is not None and not company_id and cabinet.client_company_id:
            company_id = cabinet.client_company_id
    if not company_id:
        company = ensure_client_company(
            db,
            tenant_id=report.tenant_id,
            client_id=client_id,
            display_name=organization,
        )
        company_id = company.id if company else ""
    if not wb_cabinet_id and cabinet is None and company_id:
        cabinet = _single_active_wb_provider_cabinet(
            db,
            client_id=client_id,
            client_company_id=company_id,
        )
    if cabinet is not None and company_id and not cabinet.client_company_id:
        cabinet.client_company_id = company_id
        cabinet.updated_at = security.utcnow()
    if not wb_cabinet_id:
        if cabinet is not None and company_id and not cabinet.client_company_id:
            cabinet.client_company_id = company_id
            cabinet.updated_at = security.utcnow()
        if cabinet is None:
            cabinet = ensure_wb_cabinet(
                db,
                tenant_id=report.tenant_id,
                client_id=client_id,
                display_name=cabinet_name,
                client_company_id=company_id,
            )
        wb_cabinet_id = cabinet.id if cabinet else ""
        wb_cabinet_label = cabinet.display_name if cabinet else ""
    return {
        "client_id": client_id,
        "client_company_id": company_id,
        "wb_cabinet_id": wb_cabinet_id,
        "wb_cabinet_label": wb_cabinet_label,
    }


def _single_active_wb_provider_cabinet(
    db: Session,
    *,
    client_id: str,
    client_company_id: str = "",
) -> WbCabinet | None:
    candidates = [
        item
        for item in db.scalars(
            select(WbCabinet).where(
                WbCabinet.client_id == client_id,
                WbCabinet.status == "active",
            )
        )
        if integration_provider_base(item.provider) == "wb_api"
    ]
    if client_company_id:
        company_matches = [
            item for item in candidates if item.client_company_id == client_company_id
        ]
        if len(company_matches) == 1:
            return company_matches[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _row_item_with_resolved_cabinet(
    item: dict[str, Any],
    ids: dict[str, str],
) -> dict[str, Any]:
    cabinet_label = ids.get("wb_cabinet_label") or ""
    if not cabinet_label or as_text(item.get("wbCabinetId")):
        return item
    row_item = dict(item)
    row_item["cabinet"] = cabinet_label
    return row_item


def _unit_row(
    report_id: str,
    item: dict[str, Any],
    *,
    client_id: str,
    client_company_id: str,
    wb_cabinet_id: str,
) -> ReportUnitRow:
    week = item.get("week")
    return ReportUnitRow(
        report_run_id=report_id,
        client_id=client_id,
        client_company_id=client_company_id,
        wb_cabinet_id=wb_cabinet_id,
        row_uid=as_text(item.get("id")),
        week=datetime.fromisoformat(week).date() if week else None,
        accounting_period_date=date_or_none(item.get("accountingPeriodDate")),
        accounting_period_source=(
            as_text(item.get("accountingPeriodSource")) or "wb_week_end_fallback"
        ),
        month=as_text(item.get("month")),
        document_report=as_text(item.get("documentReport")),
        wb_report_id=as_text(item.get("wbReportId")),
        wb_report_date=as_text(item.get("wbReportDate")),
        organization=as_text(item.get("organization")),
        cabinet=as_text(item.get("cabinet")),
        product=as_text(item.get("product")),
        nm_id=as_text(item.get("nmId")),
        article_wb=as_text(item.get("articleWb")),
        article_1c=as_text(item.get("article1c")),
        barcode=as_text(item.get("barcode")),
        scheme=as_text(item.get("scheme")),
        sales=decimal_value(item.get("sales")),
        returns=decimal_value(item.get("returns")),
        net_qty=decimal_value(item.get("netQty")),
        return_rate=decimal_or_none(item.get("returnRate")),
        revenue_before_spp=decimal_value(item.get("revenueBeforeSpp")),
        spp=decimal_value(item.get("spp")),
        revenue=decimal_value(item.get("revenue")),
        vat=decimal_value(item.get("vat")),
        vat_output=decimal_value(item.get("vatOutput")),
        vat_input=decimal_value(item.get("vatInput")),
        vat_input_from_wb=decimal_value(item.get("vatInputFromWb")),
        vat_input_from_1c=decimal_value(item.get("vatInputFrom1c")),
        vat_input_from_import_scenario=decimal_value(
            item.get("vatInputFromImportScenario")
        ),
        vat_input_from_wb_scenario=decimal_value(item.get("vatInputFromWbScenario")),
        vat_input_difference=decimal_value(item.get("vatInputDifference")),
        vat_input_completeness=as_text(item.get("vatInputCompleteness")),
        input_vat_mode=as_text(item.get("inputVatMode")) or "accounting_fact",
        vat_input_confirmed=bool(item.get("vatInputConfirmed") or False),
        vat_payable=decimal_value(item.get("vatPayable")),
        revenue_without_vat=decimal_value(item.get("revenueWithoutVat")),
        cost=decimal_value(item.get("cost")),
        unit_cost=decimal_or_none(item.get("unitCost")),
        cost_method=as_text(item.get("costMethod")),
        cost_match_status=as_text(item.get("costMatchStatus")),
        cost_source_kind=as_text(item.get("costSourceKind")),
        cost_source_period_start=date_or_none(item.get("costSourcePeriodStart")),
        cost_source_period_end=date_or_none(item.get("costSourcePeriodEnd")),
        cost_source_document=as_text(item.get("costSourceDocument")),
        commission=decimal_value(item.get("commission")),
        logistics=decimal_value(item.get("logistics")),
        storage=decimal_value(item.get("storage")),
        acceptance=decimal_value(item.get("acceptance")),
        promotion=decimal_value(item.get("promotion")),
        penalties=decimal_value(item.get("penalties")),
        acquiring=decimal_value(item.get("acquiring")),
        usn=decimal_value(item.get("usn")),
        income_tax_kind=as_text(item.get("incomeTaxKind")),
        income_tax_base=decimal_value(item.get("incomeTaxBase")),
        income_tax=decimal_value(item.get("incomeTax")),
        income_tax_included=bool(item.get("incomeTaxIncluded") or False),
        profit_before_tax=decimal_value(item.get("profitBeforeTax")),
        profit=decimal_value(item.get("profit")),
        margin=decimal_or_none(item.get("margin")),
        unit_profit=decimal_or_none(item.get("unitProfit")),
        tax_method=as_text(item.get("taxMethod")),
        tax_profile_source=as_text(item.get("taxProfileSource")),
        tax_completeness=as_text(item.get("taxCompleteness")),
        pnl_vat_mode=as_text(item.get("pnlVatMode")),
        status=as_text(item.get("status")),
        status_reason=as_text(item.get("statusReason")),
        spp_status=as_text(item.get("sppStatus")),
        loss_class=as_text(item.get("lossClass")),
        loss_driver=as_text(item.get("lossDriver")),
        source_snapshot_hashes=item.get("sourceSnapshotHashes") or [],
    )


def _lost_sales_row(
    report_id: str,
    item: dict[str, Any],
    *,
    client_id: str,
    wb_cabinet_id: str,
) -> ReportLostSalesRow:
    return ReportLostSalesRow(
        report_run_id=report_id,
        client_id=client_id,
        wb_cabinet_id=wb_cabinet_id,
        row_uid=as_text(item.get("id")),
        cabinet=as_text(item.get("cabinet")),
        product=as_text(item.get("product")),
        article_1c=as_text(item.get("article1c")),
        barcode=as_text(item.get("barcode")),
        zero_stock_days=decimal_value(item.get("zeroStockDays")),
        onec_stock_quantity=decimal_value(item.get("onecStock")),
        onec_warehouses=as_text(item.get("onecWarehouses")),
        sales=decimal_value(item.get("sales")),
        lost_units=decimal_value(item.get("lostUnits")),
        lost_revenue=decimal_value(item.get("lostRevenue")),
        lost_profit=decimal_value(item.get("lostProfit")),
        note=as_text(item.get("note")),
        calculation_context=(
            dict(item.get("calculationContext"))
            if isinstance(item.get("calculationContext"), Mapping)
            else {}
        ),
    )


def _reconciliation_row(
    report_id: str,
    item: dict[str, Any],
) -> ReportReconciliationMonthly:
    return ReportReconciliationMonthly(
        report_run_id=report_id,
        month=as_text(item.get("month")),
        wb_quantity=decimal_value(item.get("wb_quantity")),
        onec_quantity=decimal_or_none(item.get("onec_quantity")),
        quantity_delta=decimal_or_none(item.get("quantity_delta")),
        wb_cogs=decimal_value(item.get("wb_cogs")),
        onec_cogs=decimal_or_none(item.get("onec_cogs")),
        cogs_delta=decimal_or_none(item.get("cogs_delta")),
        wb_mp_expenses=decimal_value(item.get("wb_mp_expenses")),
        onec_mp_expenses=decimal_or_none(item.get("onec_mp_expenses")),
        mp_expenses_delta=decimal_or_none(item.get("mp_expenses_delta")),
        status=as_text(item.get("status")),
        wb_basis=as_text(item.get("wbBasis") or item.get("wb_basis")),
        onec_basis=as_text(item.get("onecBasis") or item.get("onec_basis")),
        source_run_id=as_text(item.get("sourceRunId") or item.get("source_run_id")),
        comment=as_text(item.get("comment")),
    )


def _marketplace_expense_entity_ids(
    db: Session,
    report: ReportRun,
    item: Mapping[str, Any],
) -> dict[str, str]:
    client_id = as_text(item.get("clientId")) or report.client_id
    organization_id = as_text(item.get("organizationId"))
    company = (
        db.scalar(
            select(ClientCompany).where(
                ClientCompany.client_id == client_id,
                ClientCompany.onec_organization_id == organization_id,
                ClientCompany.status == "active",
            )
        )
        if organization_id
        else None
    )
    if company is None:
        company = ensure_client_company(
            db,
            tenant_id=report.tenant_id,
            client_id=client_id,
            display_name=as_text(item.get("organization")),
        )
    company_id = company.id if company is not None else ""
    match_status = as_text(item.get("matchStatus"))
    if match_status in {"ambiguous_cabinet_allocation", "missing_cabinet_mapping"}:
        return {
            "client_id": client_id,
            "client_company_id": company_id,
            "wb_cabinet_id": "",
        }
    ids = _row_entity_ids(db, report, dict(item))
    return ids


def _marketplace_expense_row(
    report_id: str,
    item: Mapping[str, Any],
    *,
    client_id: str,
    client_company_id: str,
    wb_cabinet_id: str,
) -> ReportMarketplaceExpenseRow:
    return ReportMarketplaceExpenseRow(
        report_run_id=report_id,
        client_id=client_id,
        client_company_id=client_company_id,
        wb_cabinet_id=wb_cabinet_id,
        row_uid=as_text(item.get("id")),
        seller_account_id=as_text(item.get("sellerAccountId")),
        cabinet=as_text(item.get("cabinet")),
        organization_id=as_text(item.get("organizationId")),
        organization=as_text(item.get("organization")),
        counterparty_id=as_text(item.get("counterpartyId")),
        period_start=date_or_none(item.get("periodStart")),
        period_end=date_or_none(item.get("periodEnd")),
        recognition_date=date_or_none(item.get("recognitionDate")),
        document_date=date_or_none(item.get("documentDate")),
        input_date=date_or_none(item.get("inputDate")),
        document_id=as_text(item.get("documentId")),
        document_number=as_text(item.get("documentNumber")),
        input_number=as_text(item.get("inputNumber")),
        document_comment=as_text(item.get("documentComment")),
        service_category=as_text(item.get("serviceCategory")),
        control_group=as_text(item.get("controlGroup")),
        service_name=as_text(item.get("serviceName")),
        amount_without_vat=decimal_value(item.get("amountWithoutVat")),
        vat=decimal_value(item.get("vat")),
        amount_with_vat=decimal_value(item.get("amountWithVat")),
        source_kind=as_text(item.get("sourceKind")),
        match_status=as_text(item.get("matchStatus")),
        source_row_hash=as_text(item.get("sourceRowHash")),
    )


def _document_reconciliation_row(
    report_id: str,
    item: dict[str, Any],
    *,
    client_id: str,
    client_company_id: str,
    wb_cabinet_id: str,
) -> ReportDocumentReconciliationRow:
    return ReportDocumentReconciliationRow(
        report_run_id=report_id,
        client_id=client_id,
        client_company_id=client_company_id,
        wb_cabinet_id=wb_cabinet_id,
        row_uid=as_text(item.get("id")),
        status=as_text(item.get("status")),
        payout_status=as_text(item.get("payoutStatus")),
        period_status=as_text(item.get("periodStatus")),
        document_report=as_text(item.get("documentReport")),
        sales_period=as_text(item.get("salesPeriod")),
        sales_period_start=date_or_none(item.get("salesPeriodStart")),
        sales_period_end=date_or_none(item.get("salesPeriodEnd")),
        expected_document_date=date_or_none(item.get("expectedDocumentDate")),
        document_type=as_text(item.get("documentType")),
        cabinet=as_text(item.get("cabinet")),
        organization=as_text(item.get("organization")),
        summary_report_id=as_text(item.get("summaryReportId")),
        weekly_sales_report_id=as_text(item.get("weeklySalesReportId")),
        weekly_buyout_report_id=as_text(item.get("weeklyBuyoutReportId")),
        wb_report_ids=as_text(item.get("wbReportIds")),
        onec_documents=as_text(item.get("onecDocuments")),
        onec_document_types=as_text(item.get("onecDocumentTypes")),
        onec_document_dates=as_text(item.get("onecDocumentDates")),
        wb_sales_quantity=decimal_or_none(item.get("wbSalesQuantity")),
        wb_return_quantity=decimal_or_none(item.get("wbReturnQuantity")),
        wb_net_quantity=decimal_or_none(item.get("wbNetQuantity")),
        onec_sales_quantity=decimal_or_none(item.get("onecSalesQuantity")),
        onec_return_quantity=decimal_or_none(item.get("onecReturnQuantity")),
        onec_net_quantity=decimal_or_none(item.get("onecNetQuantity")),
        sales_quantity_delta=decimal_or_none(item.get("salesQuantityDelta")),
        return_quantity_delta=decimal_or_none(item.get("returnQuantityDelta")),
        net_quantity_delta=decimal_or_none(item.get("netQuantityDelta")),
        wb_quantity=decimal_or_none(item.get("wbQuantity")),
        onec_quantity=decimal_or_none(item.get("onecQuantity")),
        quantity_delta=decimal_or_none(item.get("quantityDelta")),
        wb_amount=decimal_or_none(item.get("wbAmount")),
        onec_amount=decimal_or_none(item.get("onecAmount")),
        amount_delta=decimal_or_none(item.get("amountDelta")),
        buyout_retail_amount_sum=decimal_or_none(item.get("buyoutRetailAmountSum")),
        buyout_for_pay_sum=decimal_or_none(item.get("buyoutForPaySum")),
        buyout_bank_payment_sum=decimal_or_none(item.get("buyoutBankPaymentSum")),
        buyout_primary_document_id=as_text(item.get("buyoutPrimaryDocumentId")),
        buyout_primary_document_status=as_text(item.get("buyoutPrimaryDocumentStatus")),
        buyout_primary_document_quantity=decimal_or_none(
            item.get("buyoutPrimaryDocumentQuantity")
        ),
        buyout_primary_document_amount=decimal_or_none(
            item.get("buyoutPrimaryDocumentAmount")
        ),
        buyout_primary_document_delta=decimal_or_none(
            item.get("buyoutPrimaryDocumentDelta")
        ),
        onec_expense_invoice_amount=decimal_or_none(
            item.get("onecExpenseInvoiceAmount")
        ),
        buyout_retail_delta=decimal_or_none(item.get("buyoutRetailDelta")),
        buyout_for_pay_delta=decimal_or_none(item.get("buyoutForPayDelta")),
        buyout_bank_delta=decimal_or_none(item.get("buyoutBankDelta")),
        pdf_bank_payment=decimal_or_none(item.get("pdfBankPayment")),
        wb_for_pay_sum=decimal_or_none(item.get("wbForPaySum")),
        onec_settlement_total=decimal_or_none(item.get("onecSettlementTotal")),
        settlement_delta=decimal_or_none(item.get("settlementDelta")),
        onec_vat=decimal_or_none(item.get("onecVat")),
        onec_cogs=decimal_or_none(item.get("onecCogs")),
        onec_cogs_without_vat=decimal_or_none(item.get("onecCogsWithoutVat")),
        onec_gross_profit=decimal_or_none(item.get("onecGrossProfit")),
        onec_source_rows=int_or_none(item.get("onecSourceRows")),
        comment=as_text(item.get("comment")),
    )


def apply_wb_buyout_primary_documents(
    db: Session,
    report: ReportRun,
    refresh_run: SourceRefreshRun,
    *,
    source_runs: Iterable[SourceRefreshRun] = (),
) -> dict[str, int]:
    """Attach persisted WB redeem-notification totals to an immutable report mart."""
    runs_by_id = {item.id: item for item in source_runs}
    runs_by_id[refresh_run.id] = refresh_run
    ordered_runs = sorted(
        (
            item
            for item in runs_by_id.values()
            if any(
                collection.source_type == "wb_redeem_notifications"
                for collection in item.collections
            )
        ),
        key=lambda item: (
            (
                item.created_at.replace(tzinfo=UTC)
                if item.created_at.tzinfo is None
                else item.created_at.astimezone(UTC)
            ),
            item.id,
        ),
        reverse=True,
    )
    source_rows = list(
        db.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.refresh_run_id.in_(runs_by_id),
                SourceSnapshotRow.source_type == "wb_redeem_notifications",
            )
        )
    )
    by_run_key: dict[tuple[str, str, str], SourceSnapshotRow] = {}
    by_run_report_id: dict[tuple[str, str], list[SourceSnapshotRow]] = {}
    for source_row in source_rows:
        payload = source_row.row_payload or {}
        report_id = _normalized_document_number(payload.get("reportId"))
        if not report_id:
            continue
        cabinet_id = str(
            source_row.wb_cabinet_id or payload.get("wbCabinetId") or ""
        ).strip()
        by_run_key[(source_row.refresh_run_id, cabinet_id, report_id)] = source_row
        by_run_report_id.setdefault((source_row.refresh_run_id, report_id), []).append(
            source_row
        )

    rows = list(
        db.scalars(
            select(ReportDocumentReconciliationRow).where(
                ReportDocumentReconciliationRow.report_run_id == report.id,
                ReportDocumentReconciliationRow.document_type == "Уведомление о выкупе",
            )
        )
    )
    verified = 0
    not_loaded = 0
    for row in rows:
        report_id = _normalized_document_number(
            row.weekly_buyout_report_id or row.summary_report_id
        )
        row_period_end = row.sales_period_end or row.expected_document_date
        applicable_runs = [
            run
            for run in ordered_runs
            if row_period_end is None
            or (
                (run.source_window_start or run.period_start)
                <= row_period_end
                <= (run.source_window_end or run.period_end)
            )
        ]
        source_row = None
        if applicable_runs:
            # Only the newest overlay covering the document period is allowed
            # to answer. Absence in that overlay is a real missing document and
            # must not be hidden by stale primary data from the full base.
            source_run = applicable_runs[0]
            source_row = by_run_key.get((source_run.id, row.wb_cabinet_id, report_id))
            if source_row is None:
                candidates = by_run_report_id.get((source_run.id, report_id), [])
                source_row = candidates[0] if len(candidates) == 1 else None
        if source_row is None:
            row.buyout_primary_document_id = report_id
            row.buyout_primary_document_status = "not_loaded"
            row.buyout_primary_document_quantity = None
            row.buyout_primary_document_amount = None
            row.buyout_primary_document_delta = None
            not_loaded += 1
            continue
        payload = source_row.row_payload or {}
        amount = decimal_or_none(payload.get("purchaseAmount"))
        quantity = decimal_or_none(payload.get("quantity"))
        onec_amount = (
            row.onec_expense_invoice_amount
            if row.onec_expense_invoice_amount is not None
            else row.onec_amount
        )
        row.buyout_primary_document_id = report_id
        row.buyout_primary_document_quantity = quantity
        row.buyout_primary_document_amount = amount
        row.buyout_primary_document_delta = (
            amount - onec_amount
            if amount is not None and onec_amount is not None
            else None
        )
        row.buyout_primary_document_status = (
            "verified"
            if row.buyout_primary_document_delta is not None
            else "primary_loaded"
        )
        if row.buyout_primary_document_status == "verified":
            verified += 1
    db.flush()
    return {
        "sourceRows": len(source_rows),
        "reportRows": len(rows),
        "verifiedRows": verified,
        "notLoadedRows": not_loaded,
    }


def _normalized_document_number(value: Any) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())


def report_full_payload(
    db: Session,
    report: ReportRun,
    *,
    include_staff_readiness: bool = False,
) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(ReportUnitRow)
            .where(ReportUnitRow.report_run_id == report.id)
            .order_by(ReportUnitRow.id)
        )
    )
    lost = list(
        db.scalars(
            select(ReportLostSalesRow)
            .where(ReportLostSalesRow.report_run_id == report.id)
            .order_by(ReportLostSalesRow.id)
        )
    )
    reconciliation = list(
        db.scalars(
            select(ReportReconciliationMonthly)
            .where(ReportReconciliationMonthly.report_run_id == report.id)
            .order_by(ReportReconciliationMonthly.id)
        )
    )
    document_reconciliation = _document_reconciliation_rows_for_report(db, report)
    loads = _source_loads_for_report(db, report)
    source_coverage = _source_coverage_for_report(db, report)
    unit_rows = [_row_payload(row) for row in rows]
    liquidity_rows = liquidity_rows_payload(aggregate_liquidity_rows(unit_rows))
    tax_context = _tax_context_payload(db, report, rows)
    tax_profile_sync = tax_profile_sync_payload(
        db,
        report,
        tax_context=tax_context,
        include_staff_details=include_staff_readiness,
    )
    tax_input_reconciliation_rows = _tax_input_reconciliation_payload_from_unit_rows(
        rows,
        tax_context=tax_context,
    )
    onec_calendar_revenue = _onec_calendar_revenue_kpis(
        document_reconciliation,
        period_start=report.period_start,
        period_end=report.period_end,
    )
    document_reconciliation_rows = [
        _document_reconciliation_payload(row) for row in document_reconciliation
    ]
    latest_refresh = _source_refresh_payload_for_report(
        db,
        report,
        include_sensitive=include_staff_readiness,
    )
    lost_sales_coverage = _lost_sales_coverage_payload(db, report)
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in loads
    )
    stats = _report_row_stats(
        db,
        report,
        tax_context=tax_context,
        source_refresh_backed=source_refresh_backed,
    )
    marketplace_expense = (
        query_marketplace_expense_reconciliation(db, report, limit=1)
        if _marketplace_expense_context_supported(report)
        else _legacy_marketplace_expense_reconciliation(stats, report)
    )
    return {
        "meta": _report_meta_payload(report, source_coverage),
        "readiness": report_readiness_payload(
            db,
            report,
            rows=rows,
            loads=loads,
            stats=stats,
            tax_context=tax_context,
            include_staff_checks=include_staff_readiness,
        ),
        "options": options_payload(
            unit_rows,
            liquidity_rows=liquidity_rows,
            document_reconciliation=document_reconciliation_rows,
        ),
        "kpis": {
            **_summary_kpis_payload(
                {**stats, **_lost_sales_stats_for_report(db, report)},
                tax_context=tax_context,
                lost_sales_coverage=lost_sales_coverage,
                onec_calendar_revenue=onec_calendar_revenue,
            ),
            **_wb_payout_kpis(document_reconciliation),
            **marketplace_expense["kpis"],
        },
        "quality": _summary_quality_payload(
            stats,
            loads,
            report,
            document_reconciliation_rows=document_reconciliation,
        ),
        "monthly": monthly_payload(
            unit_rows,
            period_start=report.period_start,
            period_end=report.period_end,
        ),
        "expenses": expense_payload(unit_rows),
        "unitRows": unit_rows,
        "liquidityRows": liquidity_rows,
        "returns": returns_payload(unit_rows, report.return_reason_limitation),
        "lostSales": (
            [_lost_payload(row) for row in lost]
            if lost_sales_coverage.get("calculated") is True
            else []
        ),
        "lostSalesCoverage": lost_sales_coverage,
        "taxContext": tax_context,
        "taxProfileSync": tax_profile_sync,
        "reconciliation": [],
        "reconciliationMonthly": [
            _reconciliation_payload(row) for row in reconciliation
        ],
        "marketplaceExpenseReconciliation": {
            "source": marketplace_expense["source"],
            "groups": marketplace_expense["groups"],
        },
        "documentReconciliation": document_reconciliation_rows,
        "taxInputReconciliation": tax_input_reconciliation_rows,
        "latestSourceRefresh": latest_refresh,
    }


def ozon_draft_report_summary_payload(
    db: Session,
    report: ReportRun,
) -> dict[str, Any]:
    diagnostics = ozon_draft_diagnostics_payload(
        db,
        report,
        limit=OZON_DIAGNOSTIC_PREVIEW_MAX_ROWS,
        preview_max_rows=OZON_DIAGNOSTIC_PREVIEW_MAX_ROWS,
    )
    mart = diagnostics.get("ozonMart") or {}
    issues = diagnostics.get("issues") or {}
    blocking_count = int(issues.get("blockingCount") or 0)
    review_count = int(issues.get("reviewCount") or 0)
    readiness_status = (
        "ready"
        if diagnostics.get("status") == "ready" and not blocking_count
        else "needs_review"
    )
    return {
        "marketplace": "ozon",
        "ozonDiagnostics": diagnostics,
        "meta": {
            "reportId": report.id,
            "clientId": report.client_id,
            "title": report.title,
            "client": report.client_name,
            "periodStart": report.period_start.isoformat(),
            "periodEnd": report.period_end.isoformat(),
            "period": report.period_text,
            "generatedAt": report.generated_at.isoformat(),
            "publicationStatus": report.publication_status,
            "lineageType": report.lineage_type,
            "methodologyVersion": report.methodology_version,
            "sourceSnapshotSetId": report.source_snapshot_set_id,
        },
        "readiness": {
            "status": readiness_status,
            "blockingCount": blocking_count,
            "reviewCount": review_count,
            "blockingReasons": [],
            "reviewReasons": list(issues.get("items") or []),
        },
        "quality": mart.get("summary") or {},
        "kpis": mart.get("totals") or {},
        "options": {
            "periodStart": report.period_start.isoformat(),
            "periodEnd": report.period_end.isoformat(),
            "statuses": [],
            "months": [],
            "cabinets": [],
            "organizations": [],
        },
    }


def report_summary_payload(
    db: Session,
    report: ReportRun,
    *,
    include_staff_readiness: bool = False,
) -> dict[str, Any]:
    if report.report_kind in ACCOUNTING_REPORT_KINDS:
        return scenario_payload_for_report(db, report)
    if report.lineage_type == OZON_DRAFT_LINEAGE_TYPE:
        return ozon_draft_report_summary_payload(db, report)
    loads = _source_loads_for_report(db, report)
    source_coverage = _source_coverage_for_report(db, report)
    tax_context = _report_tax_context_payload(db, report)
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in loads
    )
    stats = _report_row_stats(
        db,
        report,
        tax_context=tax_context,
        source_refresh_backed=source_refresh_backed,
    )
    document_reconciliation_source_rows = _document_reconciliation_rows_for_report(
        db, report
    )
    document_reconciliation_rows = [
        _document_reconciliation_payload(row)
        for row in document_reconciliation_source_rows
    ]
    onec_calendar_revenue = _onec_calendar_revenue_kpis(
        document_reconciliation_source_rows,
        period_start=report.period_start,
        period_end=report.period_end,
    )
    liquidity_rows = _summary_liquidity_rows(db, report)
    tax_profile_sync = tax_profile_sync_payload(
        db,
        report,
        tax_context=tax_context,
        include_staff_details=include_staff_readiness,
    )
    lost_sales_coverage = _lost_sales_coverage_payload(db, report)
    tax_input_reconciliation_rows = _summary_tax_input_reconciliation_payload(
        db,
        report,
        tax_context=tax_context,
    )
    latest_refresh = _source_refresh_payload_for_report(
        db,
        report,
        include_sensitive=include_staff_readiness,
    )
    marketplace_expense = (
        query_marketplace_expense_reconciliation(db, report, limit=1)
        if _marketplace_expense_context_supported(report)
        else _legacy_marketplace_expense_reconciliation(stats, report)
    )
    return {
        "meta": _report_meta_payload(report, source_coverage),
        "readiness": report_readiness_payload(
            db,
            report,
            loads=loads,
            stats=stats,
            tax_context=tax_context,
            include_staff_checks=include_staff_readiness,
        ),
        "options": _summary_options_payload(
            db,
            report,
            liquidity_rows=liquidity_rows,
            document_reconciliation=document_reconciliation_rows,
        ),
        "kpis": {
            **_summary_kpis_payload(
                {**stats, **_lost_sales_stats_for_report(db, report)},
                tax_context=tax_context,
                lost_sales_coverage=lost_sales_coverage,
                onec_calendar_revenue=onec_calendar_revenue,
            ),
            **_wb_payout_kpis(document_reconciliation_source_rows),
            **marketplace_expense["kpis"],
        },
        "quality": _summary_quality_payload(
            stats,
            loads,
            report,
            document_reconciliation_rows=document_reconciliation_source_rows,
        ),
        "monthly": _summary_monthly_payload(db, report),
        "expenses": _summary_expense_payload(db, report),
        "liquidityRows": liquidity_rows,
        "lostSales": (
            _summary_lost_sales_payload(db, report)
            if lost_sales_coverage.get("calculated") is True
            else []
        ),
        "lostSalesCoverage": lost_sales_coverage,
        "taxContext": tax_context,
        "taxProfileSync": tax_profile_sync,
        "reconciliation": [],
        "reconciliationMonthly": [
            _reconciliation_payload(row)
            for row in db.scalars(
                select(ReportReconciliationMonthly)
                .where(ReportReconciliationMonthly.report_run_id == report.id)
                .order_by(ReportReconciliationMonthly.id)
            )
        ],
        "marketplaceExpenseReconciliation": {
            "source": marketplace_expense["source"],
            "groups": marketplace_expense["groups"],
        },
        "documentReconciliation": document_reconciliation_rows,
        "taxInputReconciliation": tax_input_reconciliation_rows,
        "latestSourceRefresh": latest_refresh,
    }


def _report_meta_payload(
    report: ReportRun, source_coverage: tuple[date, date] | None
) -> dict[str, Any]:
    period_status = report.period_status
    end_is_partial = (
        report.period_end.day
        < monthrange(report.period_end.year, report.period_end.month)[1]
    )
    if end_is_partial and period_status.strip().casefold() in {"final", "финальный"}:
        period_status = (
            f"предварительный: {RU_MONTH_NAMES[report.period_end.month].casefold()} "
            "неполный"
        )
    return {
        "reportId": report.id,
        "clientId": report.client_id,
        "tenantId": report.tenant_id,
        "title": report.title,
        "client": report.client_name,
        "period": f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}",
        "reportPeriod": (
            f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}"
        ),
        "periodText": report.period_text,
        "periodStatus": period_status,
        "sourceCoverage": _source_coverage_label(source_coverage),
        "sourceCoverageStart": (
            source_coverage[0].isoformat() if source_coverage else ""
        ),
        "sourceCoverageEnd": source_coverage[1].isoformat() if source_coverage else "",
        "methodologyVersion": report.methodology_version,
        "generatedAt": report.generated_at.strftime("%d.%m.%Y %H:%M"),
        "generatedAtIso": report.generated_at.isoformat(),
        "sourceWorkbook": report.source_workbook,
        "publicationStatus": report.publication_status,
        "isCurrent": report.is_current,
        "lineageType": report.lineage_type,
        "sourceSnapshotSetId": report.source_snapshot_set_id,
        "marketplaceExpenseContextVersion": (
            report.marketplace_expense_context_version
        ),
        "returnReasonLimitation": report.return_reason_limitation,
    }


def _source_refresh_payload_for_report(
    db: Session,
    report: ReportRun,
    *,
    include_sensitive: bool,
) -> dict[str, Any] | None:
    refresh_run_id = db.scalar(
        select(SourceLoad.source_refresh_run_id)
        .where(
            SourceLoad.report_run_id == report.id,
            SourceLoad.source_refresh_run_id.is_not(None),
        )
        .order_by(SourceLoad.id.desc())
        .limit(1)
    )
    if refresh_run_id:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        if refresh_run is not None:
            return source_refresh_run_payload(
                refresh_run,
                include_sensitive=include_sensitive,
            )
    return latest_source_refresh_payload(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        include_sensitive=include_sensitive,
    )


def report_readiness_payload(
    db: Session,
    report: ReportRun,
    *,
    rows: list[ReportUnitRow] | None = None,
    loads: list[SourceLoad] | None = None,
    stats: Mapping[str, Any] | None = None,
    tax_context: Mapping[str, Any] | None = None,
    include_staff_checks: bool = False,
) -> dict[str, Any]:
    source_loads = loads if loads is not None else _source_loads_for_report(db, report)
    resolved_tax_context = tax_context or _report_tax_context_payload(db, report)
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in source_loads
    )
    source_coverage = _source_coverage_for_report(db, report)
    blocking_reasons: list[dict[str, Any]] = []
    review_reasons: list[dict[str, Any]] = []
    score = 100
    lineage_loads = [load for load in source_loads if load.source_refresh_run_id]
    if report.source_snapshot_set_id and not lineage_loads:
        blocking_reasons.append(
            _readiness_reason(
                "source_lineage_missing",
                (
                    "Snapshot отчёта не связан с зарегистрированными "
                    "загрузками источников."
                ),
            )
        )
        score -= 40
    lost_sales_rows = int(
        db.scalar(
            select(func.count())
            .select_from(ReportLostSalesRow)
            .where(ReportLostSalesRow.report_run_id == report.id)
        )
        or 0
    )
    stock_history_lineage = any(
        load.source_type == "wb_stock_history_daily"
        and bool(load.source_refresh_run_id)
        for load in source_loads
    )
    if source_refresh_backed and lost_sales_rows and not stock_history_lineage:
        blocking_reasons.append(
            _readiness_reason(
                "stock_history_lineage_missing",
                "Расчёт упущенных продаж не связан с snapshot истории остатков WB.",
                lost_sales_rows,
            )
        )
        score -= 40
    row_stats = stats
    if rows is None and row_stats is None:
        row_stats = _report_row_stats(
            db,
            report,
            tax_context=resolved_tax_context,
            source_refresh_backed=source_refresh_backed,
        )

    row_count = len(rows) if rows is not None else int(row_stats["row_count"])
    if row_count == 0:
        return _readiness_payload(
            "failed",
            0,
            blocking_reasons=[
                _readiness_reason(
                    "no_rows",
                    "В отчете нет строк расчетной витрины.",
                    0,
                )
            ],
            review_reasons=[],
            next_action=(
                "Пересобрать или импортировать report run: "
                "сейчас нечего отправлять клиенту."
            ),
        )

    logistics_context = db.get(ReportLogisticsAnalysisContext, report.id)
    if report.logistics_analysis_required:
        logistics_state = _logistics_context_state(report, logistics_context)
        if logistics_state == "missing":
            blocking_reasons.append(
                _readiness_reason(
                    "logistics_analysis_missing",
                    (
                        "Обязательный контекст анализа логистики отсутствует; "
                        "нужен новый report run."
                    ),
                    nonOverridable=True,
                )
            )
            score = min(score, 40)
        elif logistics_state == "outdated_methodology":
            blocking_reasons.append(
                _readiness_reason(
                    "logistics_analysis_outdated",
                    (
                        "Контекст анализа логистики построен по устаревшей "
                        "методике; нужен новый report run."
                    ),
                    nonOverridable=True,
                )
            )
            score = min(score, 40)
        elif logistics_state == "outdated_chain_key":
            blocking_reasons.append(
                _readiness_reason(
                    "logistics_analysis_key_outdated",
                    (
                        "Контекст анализа логистики построен с несовместимой "
                        "версией ключа цепочки; нужен новый report run."
                    ),
                    nonOverridable=True,
                )
            )
            score = min(score, 40)
        elif logistics_state == "scope_mismatch":
            blocking_reasons.append(
                _readiness_reason(
                    "logistics_analysis_scope_mismatch",
                    (
                        "Контекст анализа логистики принадлежит другому "
                        "tenant или клиенту; нужен новый report run."
                    ),
                    nonOverridable=True,
                )
            )
            score = min(score, 40)
        elif logistics_state == "invalid_status":
            blocking_reasons.append(
                _readiness_reason(
                    "logistics_analysis_invalid_status",
                    (
                        "Контекст анализа логистики имеет неизвестный статус; "
                        "нужен новый report run."
                    ),
                    nonOverridable=True,
                )
            )
            score = min(score, 40)
        elif logistics_state == "blocked":
            blocking_reasons.append(
                _readiness_reason(
                    "logistics_analysis_blocked",
                    (
                        "Обязательная сверка логистики WB не пройдена; "
                        "логистические витрины не построены."
                    ),
                    nonOverridable=True,
                )
            )
            score = min(score, 40)
        elif logistics_state == "partial":
            review_reasons.append(
                _readiness_reason(
                    "logistics_analysis_partial",
                    (
                        "Итог логистики сверен, но часть операций пока не "
                        "распределена по направлениям."
                    ),
                )
            )
            score -= 10

    dimension_context = db.get(ReportLogisticsDimensionContext, report.id)
    if report.logistics_dimensions_required:
        dimension_state = _logistics_dimension_context_state(
            report, dimension_context
        )
        dimension_blockers = {
            "missing": (
                "logistics_dimensions_missing",
                "Обязательный контекст габаритов отсутствует; нужен новый report run.",
            ),
            "outdated_methodology": (
                "logistics_dimensions_outdated",
                "Контекст габаритов построен по устаревшей методике.",
            ),
            "scope_mismatch": (
                "logistics_dimensions_scope_mismatch",
                "Контекст габаритов принадлежит другому tenant или клиенту.",
            ),
            "invalid_status": (
                "logistics_dimensions_invalid_status",
                "Контекст габаритов имеет неизвестный статус.",
            ),
            "blocked": (
                "logistics_dimensions_blocked",
                "Проверка целостности snapshot габаритов не пройдена.",
            ),
        }
        if dimension_state in dimension_blockers:
            code, message = dimension_blockers[dimension_state]
            blocking_reasons.append(
                _readiness_reason(code, message, nonOverridable=True)
            )
            score = min(score, 40)
        elif dimension_context is not None:
            actual_dimension_rows = int(
                db.scalar(
                    select(func.count())
                    .select_from(ReportLogisticsDimensionRow)
                    .where(ReportLogisticsDimensionRow.report_run_id == report.id)
                )
                or 0
            )
            if actual_dimension_rows != dimension_context.dimension_row_count:
                blocking_reasons.append(
                    _readiness_reason(
                        "logistics_dimensions_row_count_mismatch",
                        "Количество строк витрины габаритов не совпадает с context.",
                        nonOverridable=True,
                    )
                )
                score = min(score, 40)
            elif dimension_state == "partial":
                review_reasons.append(
                    _readiness_reason(
                        "logistics_dimensions_partial",
                        "Часть габаритов отсутствует или требует проверки.",
                    )
                )
                score -= 5

    company_cabinet_mismatch_count = (
        int(row_stats.get("company_cabinet_mismatch_rows") or 0)
        if row_stats is not None
        else _report_company_cabinet_mismatch_count(db, report)
    )
    if company_cabinet_mismatch_count:
        blocking_reasons.append(
            _readiness_reason(
                "company_cabinet_mismatch",
                "Организация строки отчёта не совпадает с организацией WB-кабинета.",
                company_cabinet_mismatch_count,
                nonOverridable=True,
            )
        )
        score = min(score, 40)

    report_status = report.status.strip().lower()
    if report_status in {"failed", "error", "blocked"}:
        blocking_reasons.append(
            _readiness_reason(
                "report_status_blocked",
                "Report run помечен как неуспешный.",
            )
        )
        score -= 40
    elif report_status not in {"final", "ready", "completed", "partial_period"}:
        review_reasons.append(
            _readiness_reason(
                "report_status_review",
                "Статус report run требует ручной проверки.",
            )
        )
        score -= 10

    if _is_partial_period(report):
        review_reasons.append(
            _readiness_reason(
                "partial_period",
                "Период отчета помечен как предварительный или неполный.",
            )
        )
        score -= 5

    if _source_coverage_gap(report, source_coverage):
        review_reasons.append(
            _readiness_reason(
                "source_coverage_gap",
                "Покрытие источников не закрывает выбранный период отчета.",
            )
        )
        score -= 20

    if not source_loads:
        review_reasons.append(
            _readiness_reason(
                "source_loads_missing",
                "В запуске отчёта нет истории загрузок источников.",
            )
        )
        score -= 20
    else:
        review_only_loads = [
            load
            for load in source_loads
            if load.source_type == "sku_mapping"
            and load.status.strip().lower() == "needs_review"
        ]
        review_blocking_loads = [
            load
            for load in source_loads
            if (load.required or load.publication_required)
            and load.status.strip().lower() == "needs_review"
            and load not in review_only_loads
        ]
        blocking_loads = [
            load
            for load in source_loads
            if (load.required or load.publication_required)
            and not _source_load_ok(load)
            and load not in review_blocking_loads
            and load not in review_only_loads
        ]
        if blocking_loads:
            blocking_reasons.append(
                _readiness_reason(
                    "source_load_failed",
                    "Обязательная загрузка или источник публикации не завершены.",
                    len(blocking_loads),
                )
            )
            score -= 40
        if review_blocking_loads:
            blocking_reasons.append(
                _readiness_reason(
                    "source_load_review_required",
                    "Обязательный источник загружен, но требует проверки.",
                    len(review_blocking_loads),
                )
            )
            score -= 30
        incomplete_loads = [
            load
            for load in source_loads
            if load not in blocking_loads
            and load not in review_blocking_loads
            and not _source_load_ok(load)
        ]
        if incomplete_loads:
            review_reasons.append(
                _readiness_reason(
                    "source_load_incomplete",
                    "Есть неполные или требующие проверки загрузки источников.",
                    len(incomplete_loads),
                )
            )
            score -= 20

    if rows is None:
        missing_cost_count = int(row_stats["missing_cost_rows"])
        mapping_count = int(row_stats["mapping_rows"])
        partial_count = int(row_stats["partial_rows"])
        problem_count = int(row_stats["problem_rows"])
        other_problem_count = max(
            0, problem_count - missing_cost_count - mapping_count - partial_count
        )
    else:
        missing_cost_rows = _rows_matching(rows, ("себестоим", "missing_cost"))
        mapping_rows = _rows_matching(
            rows,
            (
                "сопостав",
                "маппинг",
                "mapping",
                "ambiguous_mapping",
                "missing_mapping",
                "неоднознач",
            ),
        )
        missing_cost_ids = {row.id for row in missing_cost_rows}
        mapping_rows = [row for row in mapping_rows if row.id not in missing_cost_ids]
        partial_rows = _rows_matching(rows, ("partial_source", "неполный источник"))
        problem_rows = [row for row in rows if not _row_is_ok(row)]
        classified_ids = {
            row.id for row in [*missing_cost_rows, *mapping_rows, *partial_rows]
        }
        other_problem_rows = [
            row for row in problem_rows if row.id not in classified_ids
        ]
        missing_cost_count = len(missing_cost_rows)
        mapping_count = len(mapping_rows)
        partial_count = len(partial_rows)
        problem_count = len(problem_rows)
        other_problem_count = len(other_problem_rows)
    document_reconciliation_rows = _document_reconciliation_rows_for_report(db, report)
    document_reconciliation_issue_count = len(
        [
            row
            for row in document_reconciliation_rows
            if _document_reconciliation_has_issue(row)
        ]
    )

    if mapping_count:
        review_reasons.append(
            _readiness_reason(
                "mapping_review",
                "Есть строки с отсутствующим или неоднозначным сопоставлением WB-1С.",
                mapping_count,
            )
        )
        score -= 20
    if partial_count:
        review_reasons.append(
            _readiness_reason(
                "partial_source",
                "Есть строки с неполными источниками данных.",
                partial_count,
            )
        )
        score -= 20
    if other_problem_count:
        review_reasons.append(
            _readiness_reason(
                "data_quality_review",
                "Есть строки со статусом, отличным от ОК.",
                other_problem_count,
            )
        )
        score -= 10
    if document_reconciliation_issue_count:
        review_reasons.append(
            _readiness_reason(
                "onec_reconciliation_review",
                "Есть расхождения или ограничения в сверке WB ↔ 1С.",
                document_reconciliation_issue_count,
            )
        )
        score -= 10

    financial_stats = row_stats or _report_row_stats(
        db,
        report,
        tax_context=resolved_tax_context,
        source_refresh_backed=source_refresh_backed,
    )
    if missing_cost_count:
        review_reasons.append(
            _readiness_reason(
                "cogs_reconciliation_failed",
                "Себестоимость 1С требует сверки.",
                missing_cost_count,
                affectedRevenue=float(
                    financial_stats.get("missing_cost_affected_revenue") or 0
                ),
                costRequiresReviewRows=int(
                    financial_stats.get("cost_requires_review_rows") or 0
                ),
                costAbsentRows=int(financial_stats.get("cost_absent_rows") or 0),
            )
        )
        score -= 15
    management_vat_rows = int(
        financial_stats.get("vat_input_management_assumption_rows") or 0
    )
    if management_vat_rows:
        review_reasons.append(
            _readiness_reason(
                "vat_input_management_assumption",
                (
                    "Входящий НДС рассчитан по управленческому допущению и не "
                    "является подтверждённым вычетом книги покупок 1С."
                ),
                management_vat_rows,
                estimatedInputVat=float(financial_stats.get("vat_input") or 0),
                importScenarioVat=float(
                    financial_stats.get("vat_input_from_import_scenario") or 0
                ),
                wbScenarioVat=float(
                    financial_stats.get("vat_input_from_wb_scenario") or 0
                ),
            )
        )
        score -= 5
    monthly_reconciliation_issues = int(
        db.scalar(
            select(func.count())
            .select_from(ReportReconciliationMonthly)
            .where(
                ReportReconciliationMonthly.report_run_id == report.id,
                func.trim(func.coalesce(ReportReconciliationMonthly.status, ""))
                != "",
                ReportReconciliationMonthly.status != "Сходится",
            )
        )
        or 0
    )
    if source_refresh_backed and monthly_reconciliation_issues:
        review_reasons.append(
            _readiness_reason(
                "monthly_reconciliation_unresolved",
                (
                    "Помесячная сверка WB-1С содержит расхождения или "
                    "неполные данные; рассчитанные значения доступны в отчете."
                ),
                monthly_reconciliation_issues,
            )
        )
        score -= 10
    financial_blockers = _financial_integrity_blockers(
        db,
        report,
        source_loads=source_loads,
        stats=financial_stats,
        tax_context=resolved_tax_context,
        document_reconciliation_issue_count=document_reconciliation_issue_count,
    )
    if _has_readiness_reason(
        blocking_reasons,
        "source_load_failed",
        "source_load_review_required",
    ):
        financial_blockers = [
            reason
            for reason in financial_blockers
            if reason.get("code") != "source_lineage_failed"
        ]
    blocking_reasons.extend(financial_blockers)
    if financial_blockers:
        score = min(score, 40)

    if _too_many_problem_rows_count(problem_count, row_count):
        review_reasons.append(
            _readiness_reason(
                "too_many_data_quality_issues",
                "Критичных строк больше 20% отчета.",
                problem_count,
            )
        )
        score = min(score, 50)

    if include_staff_checks:
        latest_draft = latest_client_draft(db, report)
        if latest_draft is None:
            review_reasons.append(
                _readiness_reason(
                    "client_draft_missing",
                    "Клиентский AI-черновик еще не подготовлен.",
                )
            )
            score -= 10
        elif client_draft_contains_forbidden_text(latest_draft.content):
            blocking_reasons.append(
                _readiness_reason(
                    "client_draft_forbidden_text",
                    "Клиентский AI-черновик содержит внутренние labels.",
                )
            )
            score = min(score, 40)
        elif latest_draft.status != "ready":
            review_reasons.append(
                _readiness_reason(
                    "client_draft_not_ready",
                    "Клиентский AI-черновик еще не помечен готовым.",
                )
            )
            score -= 10

    blocking_reasons = _dedupe_readiness_reasons(blocking_reasons)
    review_reasons = _dedupe_readiness_reasons(review_reasons)
    _decorate_readiness_tasks(report, source_loads, blocking_reasons, review_reasons)
    score = max(0, min(100, score))
    if blocking_reasons:
        status = "failed"
        score = min(score, 59)
    elif not review_reasons and score >= 85:
        status = "ready"
    elif _has_readiness_reason(review_reasons, "source_coverage_gap"):
        status = "source_coverage_gap"
    elif _has_readiness_reason(
        review_reasons,
        "partial_source",
        "source_load_incomplete",
    ):
        status = "partial_source"
    elif _has_readiness_reason(review_reasons, "partial_period"):
        status = "partial_period"
    else:
        status = "needs_review"
    return _readiness_payload(
        status,
        score,
        blocking_reasons=blocking_reasons,
        review_reasons=review_reasons,
        next_action=_readiness_next_action(status, blocking_reasons, review_reasons),
    )


def _row_payload(row: ReportUnitRow) -> dict[str, Any]:
    return {
        "id": row.row_uid,
        "clientId": row.client_id,
        "clientCompanyId": row.client_company_id,
        "wbCabinetId": row.wb_cabinet_id,
        "week": row.week.isoformat() if row.week else "",
        "accountingPeriodDate": _date_payload(row.accounting_period_date),
        "accountingPeriodSource": row.accounting_period_source,
        "month": _effective_row_month(row),
        "documentReport": _closing_date_label(
            row.document_report,
            row.accounting_period_date
            or (row.week + timedelta(days=6) if row.week else None),
        ),
        "wbReportId": row.wb_report_id,
        "wbReportDate": row.wb_report_date,
        "organization": row.organization,
        "cabinet": row.cabinet,
        "product": row.product,
        "nmId": row.nm_id,
        "articleWb": row.article_wb,
        "article1c": row.article_1c,
        "barcode": row.barcode,
        "scheme": row.scheme,
        "sales": as_float(row.sales),
        "returns": as_float(row.returns),
        "netQty": as_float(row.net_qty),
        "returnRate": as_float(row.return_rate),
        "revenueBeforeSpp": as_float(row.revenue_before_spp),
        "spp": as_float(row.spp),
        "revenue": as_float(row.revenue),
        "vat": as_float(row.vat),
        "vatOutput": as_float(row.vat_output),
        "vatInput": as_float(row.vat_input),
        "vatInputFromWb": as_float(row.vat_input_from_wb),
        "vatInputFrom1c": as_float(row.vat_input_from_1c),
        "vatInputFromImportScenario": as_float(row.vat_input_from_import_scenario),
        "vatInputFromWbScenario": as_float(row.vat_input_from_wb_scenario),
        "vatInputDifference": as_float(row.vat_input_difference),
        "vatInputCompleteness": row.vat_input_completeness,
        "inputVatMode": row.input_vat_mode,
        "vatInputConfirmed": row.vat_input_confirmed,
        "vatPayable": as_float(row.vat_payable),
        "revenueWithoutVat": as_float(row.revenue_without_vat),
        "cost": as_float(row.cost),
        "unitCost": as_float(row.unit_cost),
        "costMethod": row.cost_method,
        "costMatchStatus": row.cost_match_status,
        "costSourceKind": row.cost_source_kind,
        "costSourcePeriodStart": _date_payload(row.cost_source_period_start),
        "costSourcePeriodEnd": _date_payload(row.cost_source_period_end),
        "costSourceDocument": row.cost_source_document,
        "commission": as_float(row.commission),
        "logistics": as_float(row.logistics),
        "storage": as_float(row.storage),
        "acceptance": as_float(row.acceptance),
        "promotion": as_float(row.promotion),
        "penalties": as_float(row.penalties),
        "acquiring": as_float(row.acquiring),
        "usn": as_float(row.usn),
        "incomeTaxKind": row.income_tax_kind,
        "incomeTaxBase": as_float(row.income_tax_base),
        "incomeTax": as_float(row.income_tax),
        "incomeTaxIncluded": row.income_tax_included,
        "profitBeforeTax": as_float(row.profit_before_tax),
        "profit": as_float(row.profit),
        "margin": as_float(row.margin),
        "unitProfit": as_float(row.unit_profit),
        "taxMethod": row.tax_method,
        "taxProfileSource": row.tax_profile_source,
        "taxCompleteness": row.tax_completeness,
        "pnlVatMode": row.pnl_vat_mode,
        "status": row.status,
        "statusReason": row.status_reason,
        "sppStatus": row.spp_status,
        "lossClass": row.loss_class,
        "lossDriver": row.loss_driver,
    }


def _effective_row_month(row: ReportUnitRow) -> str:
    return _effective_month_label(
        row.week,
        row.month,
        accounting_period_date=row.accounting_period_date,
    )


def _effective_month_label(
    week: date | None,
    stored_month: str,
    *,
    accounting_period_date: date | None = None,
) -> str:
    if accounting_period_date is None and week is None:
        return stored_month
    closing_date = accounting_period_date or (week + timedelta(days=6))
    label = f"{RU_MONTH_NAMES[closing_date.month]} {closing_date.year}"
    if stored_month.casefold().startswith(label.casefold()):
        return stored_month
    return label


def _closing_date_label(value: str, closing_date: date | None) -> str:
    if not value or closing_date is None:
        return value
    return re.sub(
        r"закрытие\s+\d{2}\.\d{2}\.\d{4}",
        f"закрытие {closing_date:%d.%m.%Y}",
        value,
    )


def _tax_input_reconciliation_payload_from_unit_rows(
    rows: list[ReportUnitRow],
    *,
    tax_context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        week = row.week.isoformat() if row.week else ""
        key = (week, row.cabinet, row.organization)
        bucket = buckets.setdefault(
            key,
            {
                "week": week,
                "weekEnd": "",
                "cabinet": row.cabinet,
                "organization": row.organization,
                "vatInputFromWb": 0.0,
                "vatInputFromWbCharges": 0.0,
                "vatInputFromWbReversals": 0.0,
                "vatInputFrom1c": 0.0,
                "vatInputFrom1cCharges": 0.0,
                "vatInputFrom1cReversals": 0.0,
                "sourceRowCount": 0,
                "statuses": set(),
            },
        )
        wb_value = float(row.vat_input_from_wb or 0)
        onec_value = float(row.vat_input_from_1c or 0)
        bucket["vatInputFromWb"] += wb_value
        bucket["vatInputFrom1c"] += onec_value
        bucket["sourceRowCount"] += 1
        if row.vat_input_completeness:
            bucket["statuses"].add(row.vat_input_completeness)
    result = []
    deduction_status = str((tax_context or {}).get("vatDeductionMode") or "unknown")
    deduction_status_by_organization = _tax_input_deduction_status_by_organization(
        tax_context
    )
    for bucket in buckets.values():
        vat_from_wb = bucket["vatInputFromWb"]
        vat_from_1c = bucket["vatInputFrom1c"]
        bucket["vatInputFromWbCharges"] = max(vat_from_wb, 0.0)
        bucket["vatInputFromWbReversals"] = min(vat_from_wb, 0.0)
        bucket["vatInputFrom1cCharges"] = max(vat_from_1c, 0.0)
        bucket["vatInputFrom1cReversals"] = min(vat_from_1c, 0.0)
        statuses = bucket.pop("statuses")
        bucket["vatInputDifference"] = round(vat_from_1c - vat_from_wb, 2)
        onec_has_documents = bool(
            bucket["vatInputFrom1cCharges"] or bucket["vatInputFrom1cReversals"]
        )
        bucket["vatInputCompleteness"] = (
            _worse_tax_input_status(statuses) if onec_has_documents else "missing"
        )
        bucket["wbEvidenceStatus"] = "confirmed" if vat_from_wb else "missing"
        bucket["onecEvidenceStatus"] = "confirmed" if onec_has_documents else "missing"
        bucket["vatDeductionMode"] = deduction_status_by_organization.get(
            str(bucket["organization"]), deduction_status
        )
        bucket["wbSource"] = "WB weekly realization report"
        bucket["onecSource"] = (
            "1C confirming documents" if onec_has_documents else "missing"
        )
        result.append(bucket)
    result.sort(
        key=lambda item: (
            abs(float(item["vatInputDifference"])),
            str(item["week"]),
        ),
        reverse=True,
    )
    for index, bucket in enumerate(result, start=1):
        bucket["id"] = f"tax-input-reconciliation-{index}"
    return result


def _tax_input_deduction_status_by_organization(
    tax_context: Mapping[str, Any] | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for profile in (tax_context or {}).get("profiles") or []:
        if not isinstance(profile, Mapping):
            continue
        organization = str(profile.get("organization") or "").strip()
        if not organization:
            continue
        modes = {
            str(check.get("vatDeductionMode") or "unknown")
            for check in profile.get("checks") or []
            if isinstance(check, Mapping)
        }
        modes.discard("")
        if not modes:
            result[organization] = "unknown"
        elif len(modes) == 1:
            result[organization] = next(iter(modes))
        else:
            result[organization] = "mixed"
    return result


def _summary_tax_input_reconciliation_payload(
    db: Session,
    report: ReportRun,
    *,
    tax_context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    grouped_rows = db.execute(
        select(
            ReportUnitRow.week,
            ReportUnitRow.cabinet,
            ReportUnitRow.organization,
            ReportUnitRow.vat_input_completeness,
            func.coalesce(func.sum(ReportUnitRow.vat_input_from_wb), 0),
            func.coalesce(func.sum(ReportUnitRow.vat_input_from_1c), 0),
            func.count(),
        )
        .where(ReportUnitRow.report_run_id == report.id)
        .group_by(
            ReportUnitRow.week,
            ReportUnitRow.cabinet,
            ReportUnitRow.organization,
            ReportUnitRow.vat_input_completeness,
        )
    )
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for (
        week_value,
        cabinet,
        organization,
        status,
        wb_value,
        onec_value,
        count,
    ) in grouped_rows:
        week = week_value.isoformat() if week_value else ""
        key = (week, cabinet or "", organization or "")
        bucket = buckets.setdefault(
            key,
            {
                "week": week,
                "weekEnd": "",
                "cabinet": cabinet or "",
                "organization": organization or "",
                "vatInputFromWb": 0.0,
                "vatInputFromWbCharges": 0.0,
                "vatInputFromWbReversals": 0.0,
                "vatInputFrom1c": 0.0,
                "vatInputFrom1cCharges": 0.0,
                "vatInputFrom1cReversals": 0.0,
                "sourceRowCount": 0,
                "statuses": set(),
            },
        )
        bucket["vatInputFromWb"] += float(wb_value or 0)
        bucket["vatInputFrom1c"] += float(onec_value or 0)
        bucket["sourceRowCount"] += int(count or 0)
        if status:
            bucket["statuses"].add(status)

    result = []
    deduction_status = str((tax_context or {}).get("vatDeductionMode") or "unknown")
    deduction_status_by_organization = _tax_input_deduction_status_by_organization(
        tax_context
    )
    for bucket in buckets.values():
        vat_from_wb = bucket["vatInputFromWb"]
        vat_from_1c = bucket["vatInputFrom1c"]
        bucket["vatInputFromWbCharges"] = max(vat_from_wb, 0.0)
        bucket["vatInputFromWbReversals"] = min(vat_from_wb, 0.0)
        bucket["vatInputFrom1cCharges"] = max(vat_from_1c, 0.0)
        bucket["vatInputFrom1cReversals"] = min(vat_from_1c, 0.0)
        statuses = bucket.pop("statuses")
        bucket["vatInputDifference"] = round(vat_from_1c - vat_from_wb, 2)
        onec_has_documents = bool(
            bucket["vatInputFrom1cCharges"] or bucket["vatInputFrom1cReversals"]
        )
        bucket["vatInputCompleteness"] = (
            _worse_tax_input_status(statuses) if onec_has_documents else "missing"
        )
        bucket["wbEvidenceStatus"] = "confirmed" if vat_from_wb else "missing"
        bucket["onecEvidenceStatus"] = "confirmed" if onec_has_documents else "missing"
        bucket["vatDeductionMode"] = deduction_status_by_organization.get(
            str(bucket["organization"]), deduction_status
        )
        bucket["wbSource"] = "WB weekly realization report"
        bucket["onecSource"] = (
            "1C confirming documents" if onec_has_documents else "missing"
        )
        result.append(bucket)
    result.sort(
        key=lambda item: (
            abs(float(item["vatInputDifference"])),
            str(item["week"]),
        ),
        reverse=True,
    )
    for index, bucket in enumerate(result, start=1):
        bucket["id"] = f"tax-input-reconciliation-{index}"
    return result


def _worse_tax_input_status(statuses: set[str]) -> str:
    priority = {
        "mismatch": 30,
        "partial": 20,
        "missing": 10,
        "confirmed": 0,
    }
    if not statuses:
        return "missing"
    return max(statuses, key=lambda status: priority.get(status, 0))


def _row_filter_period_date(
    *,
    week: date | None,
    accounting_period_date: date | None,
    wb_report_date: Any = None,
) -> date | None:
    if week is not None:
        return week + timedelta(days=6)
    if accounting_period_date is not None:
        return accounting_period_date
    return date_or_none(wb_report_date)


def options_payload(
    rows: list[dict[str, Any]],
    *,
    liquidity_rows: list[dict[str, Any]] | None = None,
    document_reconciliation: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def unique(key: str) -> list[str]:
        return sorted({as_text(row.get(key)) for row in rows if row.get(key)})

    def unique_entities(id_key: str, label_key: str) -> list[dict[str, str]]:
        entities: dict[str, str] = {}
        for row in rows:
            label = as_text(row.get(label_key))
            entity_id = as_text(row.get(id_key))
            if not label and not entity_id:
                continue
            stable_id = entity_id or label
            entities.setdefault(stable_id, label or stable_id)
        return [
            {"id": entity_id, "label": label}
            for entity_id, label in sorted(
                entities.items(), key=lambda item: item[1].lower()
            )
        ]

    document_reconciliation = document_reconciliation or []
    liquidity_rows = liquidity_rows or []
    month_values = {as_text(row.get("month")) for row in rows if row.get("month")}
    months = _ordered_values(list(month_values))
    period_dates = sorted(
        period_date
        for row in rows
        if (
            period_date := _row_filter_period_date(
                week=date_or_none(row.get("week")),
                accounting_period_date=date_or_none(row.get("accountingPeriodDate")),
                wb_report_date=row.get("wbReportDate"),
            )
        )
        is not None
    )
    return {
        "months": months,
        "periodStart": period_dates[0].isoformat() if period_dates else "",
        "periodEnd": period_dates[-1].isoformat() if period_dates else "",
        "cabinets": unique_entities("wbCabinetId", "cabinet"),
        "organizations": unique_entities("clientCompanyId", "organization"),
        "schemes": unique("scheme"),
        "statuses": sorted(
            {
                *unique("status"),
                *(
                    as_text(row.get("status"))
                    for row in document_reconciliation
                    if row.get("status")
                ),
            }
        ),
        "lossClasses": unique("lossClass"),
        "liquidityStatuses": liquidity_statuses(liquidity_rows),
        "documentReconciliationStatuses": sorted(
            {
                as_text(row.get("status"))
                for row in document_reconciliation
                if row.get("status")
            }
        ),
        "documentTypes": sorted(
            {
                as_text(row.get("documentType"))
                for row in document_reconciliation
                if row.get("documentType")
            }
        ),
        "documentReports": sorted(
            {
                *unique("documentReport"),
                *(
                    as_text(row.get("documentReport"))
                    for row in document_reconciliation
                    if row.get("documentReport")
                ),
            }
        ),
    }


def monthly_payload(
    rows: list[dict[str, Any]],
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        month = as_text(row.get("month"))
        if not month:
            continue
        month_start = _month_start_from_row_payload(row) or _month_start_from_label(
            month
        )
        month_key = month_start.isoformat() if month_start else month
        bucket = buckets.setdefault(
            month_key,
            {
                "month": month,
                "monthStart": month_start.isoformat() if month_start else "",
                "sales": 0.0,
                "returns": 0.0,
                "revenue": 0.0,
                "profit": 0.0,
            },
        )
        bucket["sales"] += float(row.get("sales") or 0)
        bucket["returns"] += float(row.get("returns") or 0)
        bucket["revenue"] += float(_payload_management_revenue(row))
        bucket["profit"] += float(_payload_management_profit(row))
    for bucket in buckets.values():
        metadata = _month_period_metadata(
            date_or_none(bucket.get("monthStart")),
            period_start=period_start,
            period_end=period_end,
            fallback_partial="непол" in str(bucket.get("month") or "").casefold(),
        )
        bucket.update(metadata)
        bucket["status"] = "неполный месяц" if bucket["isPartial"] else "полный месяц"
        bucket["return_rate"] = (
            bucket["returns"] / bucket["sales"] if bucket["sales"] else None
        )
        bucket["margin"] = (
            bucket["profit"] / bucket["revenue"] if bucket["revenue"] else None
        )
    return sorted(
        buckets.values(),
        key=lambda item: str(item.get("monthStart") or item.get("month") or ""),
    )


def _pnl_payload_decimal(row: Mapping[str, Any], key: str) -> Decimal:
    value = row.get(key)
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _pnl_payload_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)


def _payload_uses_osno_without_vat_pnl(row: Mapping[str, Any]) -> bool:
    return _payload_has_explicit_without_vat_pnl_mode(
        row
    ) or _payload_has_osno_tax_method(row)


def _payload_has_explicit_without_vat_pnl_mode(row: Mapping[str, Any]) -> bool:
    return _pnl_payload_text(row, "pnlVatMode") == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO


def _payload_has_osno_tax_method(row: Mapping[str, Any]) -> bool:
    return "ОСНО" in _pnl_payload_text(row, "taxMethod").upper()


def _payload_management_revenue(row: Mapping[str, Any]) -> Decimal:
    if _payload_uses_osno_without_vat_pnl(row):
        return _pnl_payload_decimal(row, "revenueWithoutVat")
    return _pnl_payload_decimal(row, "revenue")


def _payload_management_profit(row: Mapping[str, Any]) -> Decimal:
    if _payload_has_explicit_without_vat_pnl_mode(row):
        return _pnl_payload_decimal(row, "profitBeforeTax")
    return _pnl_payload_decimal(row, "profit")


def _payload_service_gross(row: Mapping[str, Any]) -> Decimal:
    return sum(
        (_pnl_payload_decimal(row, key) for key in SERVICE_EXPENSE_FIELDS),
        Decimal("0"),
    )


def _payload_service_vat_in_pnl(row: Mapping[str, Any]) -> Decimal:
    if not _payload_uses_osno_without_vat_pnl(row):
        return Decimal("0")
    service_gross = _payload_service_gross(row)
    if service_gross == 0:
        return Decimal("0")
    # For OSNO P&L: profit = revenue_without_vat - cost - services_gross + service_vat.
    return (
        _payload_management_profit(row)
        - _payload_management_revenue(row)
        + _pnl_payload_decimal(row, "cost")
        + service_gross
    )


def _payload_pnl_expense(row: Mapping[str, Any], key: str) -> Decimal:
    amount = _pnl_payload_decimal(row, key)
    if key not in VAT_ELIGIBLE_SERVICE_EXPENSE_FIELDS:
        return amount
    vat_base = sum(
        (
            _pnl_payload_decimal(row, field)
            for field in VAT_ELIGIBLE_SERVICE_EXPENSE_FIELDS
        ),
        Decimal("0"),
    )
    if vat_base == 0:
        return amount
    return amount - (_payload_service_vat_in_pnl(row) * amount / vat_base)


def expense_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    revenue = sum((_payload_management_revenue(row) for row in rows), Decimal("0"))
    result = []
    for label, key in EXPENSE_FIELD_LABELS:
        amount_decimal = sum(
            (_payload_pnl_expense(row, key) for row in rows),
            Decimal("0"),
        )
        amount = float(amount_decimal)
        if amount:
            result.append(
                {
                    "expense": label,
                    "amount": amount,
                    "share": float(amount_decimal / revenue) if revenue else None,
                }
            )
    return result


def returns_payload(
    rows: list[dict[str, Any]], limitation: str
) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if not float(row.get("returns") or 0):
            continue
        result.append(
            {
                "id": f"return-{row['id']}",
                "clientId": row.get("clientId"),
                "clientCompanyId": row.get("clientCompanyId"),
                "wbCabinetId": row.get("wbCabinetId"),
                "week": row.get("week"),
                "month": row.get("month"),
                "cabinet": row.get("cabinet"),
                "organization": row.get("organization"),
                "product": row.get("product"),
                "nmId": row.get("nmId"),
                "articleWb": row.get("articleWb"),
                "article1c": row.get("article1c"),
                "barcode": row.get("barcode"),
                "sales": row.get("sales"),
                "returns": row.get("returns"),
                "returnRate": row.get("returnRate"),
                "returnAmount": abs(float(row.get("revenue") or 0))
                * float(row.get("returnRate") or 0),
                "profit": row.get("profit"),
                "status": row.get("status"),
                "driver": row.get("lossDriver"),
                "returnReason": limitation,
            }
        )
    return result


def _report_row_stats(
    db: Session,
    report: ReportRun,
    *,
    tax_context: Mapping[str, Any] | None = None,
    source_refresh_backed: bool = False,
) -> dict[str, Any]:
    return _row_stats_for_conditions(
        db,
        ReportUnitRow.report_run_id == report.id,
        tax_context=tax_context,
        source_refresh_backed=source_refresh_backed,
    )


def _lost_sales_stats_for_report(
    db: Session,
    report: ReportRun,
    *,
    query: str = "",
    cabinet: str = "",
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    return _lost_sales_stats_for_conditions(
        db,
        *_lost_sales_conditions_for_report(
            report,
            query=query,
            cabinet=cabinet,
            wb_cabinet_id=wb_cabinet_id,
        ),
    )


def _lost_sales_conditions_for_report(
    report: ReportRun,
    *,
    query: str = "",
    cabinet: str = "",
    wb_cabinet_id: str = "",
) -> list[Any]:
    conditions: list[Any] = [ReportLostSalesRow.report_run_id == report.id]
    if cabinet:
        conditions.append(ReportLostSalesRow.cabinet == cabinet)
    if wb_cabinet_id:
        conditions.append(
            or_(
                ReportLostSalesRow.wb_cabinet_id == wb_cabinet_id,
                ReportLostSalesRow.cabinet == wb_cabinet_id,
            )
        )
    if query:
        like = f"%{query}%"
        conditions.append(
            or_(
                ReportLostSalesRow.product.ilike(like),
                ReportLostSalesRow.article_1c.ilike(like),
                ReportLostSalesRow.barcode.ilike(like),
                ReportLostSalesRow.cabinet.ilike(like),
            )
        )
    return conditions


def _lost_sales_stats_for_conditions(db: Session, *conditions: Any) -> dict[str, Any]:
    return {
        "lost_sales_rows": _count_lost_sales_rows(db, *conditions),
        "lost_sales_units": _sum_column(db, ReportLostSalesRow.lost_units, *conditions),
        "lost_sales_revenue": _sum_column(
            db, ReportLostSalesRow.lost_revenue, *conditions
        ),
        "lost_sales_profit": _sum_column(
            db, ReportLostSalesRow.lost_profit, *conditions
        ),
    }


def _row_stats_for_conditions(
    db: Session,
    *conditions: Any,
    tax_context: Mapping[str, Any] | None = None,
    source_refresh_backed: bool = False,
) -> dict[str, Any]:
    def conditional_count(condition: Any) -> Any:
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    source_text = func.lower(
        func.trim(func.coalesce(ReportUnitRow.tax_profile_source, ""))
    )
    tax_profile_missing = or_(
        source_text.in_({"missing", "unknown", "unconfirmed", "not_confirmed"}),
        func.lower(func.coalesce(ReportUnitRow.tax_completeness, "")).like(
            "%missing_tax_profile%"
        ),
        func.lower(func.coalesce(ReportUnitRow.tax_method, "")).like(
            "%налоговый профиль не найден%"
        ),
        ReportUnitRow.tax_method.like("%Налоговый профиль не найден%"),
    )
    if source_refresh_backed:
        tax_profile_missing = or_(tax_profile_missing, source_text == "")
    osno_markers: list[Any] = [_pnl_without_vat_condition()]
    osno_company_ids = _tax_context_osno_company_ids(tax_context or {})
    if osno_company_ids:
        osno_markers.append(ReportUnitRow.client_company_id.in_(osno_company_ids))
    osno_condition = or_(*osno_markers)
    report_type_fallback_condition = _quality_condition(
        "тип отчета wb определен эвристикой",
        "report_type_fallback",
    )
    missing_cost_condition = and_(
        ReportUnitRow.status != "ОК",
        _missing_cost_condition(),
    )
    company_cabinet_mismatch = and_(
        ReportUnitRow.client_company_id != "",
        ReportUnitRow.wb_cabinet_id != "",
        or_(
            WbCabinet.id.is_(None),
            WbCabinet.client_company_id.is_(None),
            WbCabinet.client_company_id != ReportUnitRow.client_company_id,
        ),
    )
    statement = (
        select(
            func.count().label("row_count"),
            func.coalesce(func.sum(_pnl_revenue_expression()), 0).label("revenue"),
            func.coalesce(func.sum(ReportUnitRow.revenue), 0).label("revenue_with_vat"),
            func.coalesce(func.sum(ReportUnitRow.revenue_without_vat), 0).label(
                "revenue_without_vat"
            ),
            func.coalesce(func.sum(ReportUnitRow.cost), 0).label("cost"),
            conditional_count(_pnl_without_vat_condition()).label(
                "pnl_without_vat_rows"
            ),
            func.coalesce(func.sum(_pnl_profit_expression()), 0).label("profit"),
            func.coalesce(func.sum(ReportUnitRow.profit_before_tax), 0).label(
                "profit_before_tax"
            ),
            func.coalesce(func.sum(_pnl_tax_deduction_expression()), 0).label(
                "pnl_tax_deduction"
            ),
            func.coalesce(func.sum(ReportUnitRow.vat_output), 0).label("vat_output"),
            func.coalesce(func.sum(ReportUnitRow.vat_input), 0).label("vat_input"),
            func.coalesce(
                func.sum(ReportUnitRow.vat_input_from_import_scenario), 0
            ).label("vat_input_from_import_scenario"),
            func.coalesce(func.sum(ReportUnitRow.vat_input_from_wb_scenario), 0).label(
                "vat_input_from_wb_scenario"
            ),
            func.coalesce(func.sum(ReportUnitRow.vat_payable), 0).label("vat_payable"),
            func.coalesce(func.sum(ReportUnitRow.income_tax), 0).label("income_tax"),
            func.coalesce(func.sum(ReportUnitRow.usn), 0).label("revenue_tax"),
            conditional_count(ReportUnitRow.income_tax_included.is_(True)).label(
                "income_tax_included_rows"
            ),
            func.coalesce(func.sum(ReportUnitRow.sales), 0).label("sales"),
            func.coalesce(func.sum(ReportUnitRow.returns), 0).label("returns"),
            conditional_count(
                and_(ReportUnitRow.profit < 0, ~_penalty_only_condition())
            ).label("loss_rows"),
            conditional_count(_penalty_only_condition()).label("penalty_only_rows"),
            conditional_count(ReportUnitRow.status == "ОК").label("ok_rows"),
            conditional_count(
                and_(ReportUnitRow.status != "ОК", _missing_cost_condition())
            ).label("missing_cost_rows"),
            conditional_count(
                and_(ReportUnitRow.status != "ОК", _missing_cost_review_condition())
            ).label("cost_requires_review_rows"),
            conditional_count(
                and_(ReportUnitRow.status != "ОК", _missing_cost_absent_condition())
            ).label("cost_absent_rows"),
            conditional_count(
                and_(ReportUnitRow.status != "ОК", _mapping_issue_condition())
            ).label("mapping_rows"),
            conditional_count(
                and_(
                    ReportUnitRow.status != "ОК",
                    _quality_condition("partial_source", "неполный источник"),
                )
            ).label("partial_rows"),
            conditional_count(ReportUnitRow.status != "ОК").label("problem_rows"),
            conditional_count(tax_profile_missing).label("tax_profile_issue_rows"),
            conditional_count(osno_condition).label("osno_rows"),
            conditional_count(
                and_(
                    osno_condition,
                    ReportUnitRow.pnl_vat_mode != PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
                )
            ).label("pnl_method_mismatch_rows"),
            conditional_count(
                and_(
                    osno_condition,
                    ReportUnitRow.income_tax_included.is_(False),
                    func.abs(ReportUnitRow.profit - ReportUnitRow.profit_before_tax)
                    > 1,
                )
            ).label("profit_semantics_mismatch_rows"),
            conditional_count(
                and_(
                    osno_condition,
                    func.lower(
                        func.coalesce(ReportUnitRow.vat_input_completeness, "")
                    ).not_in({"confirmed", "management_assumption"}),
                )
            ).label("vat_input_unconfirmed_rows"),
            conditional_count(
                and_(
                    osno_condition,
                    func.lower(func.coalesce(ReportUnitRow.vat_input_completeness, ""))
                    == "management_assumption",
                )
            ).label("vat_input_management_assumption_rows"),
            func.coalesce(
                func.sum(
                    case(
                        (missing_cost_condition, ReportUnitRow.revenue),
                        else_=0,
                    )
                ),
                0,
            ).label("missing_cost_affected_revenue"),
            conditional_count(
                and_(
                    ReportUnitRow.revenue != 0,
                    report_type_fallback_condition,
                )
            ).label("report_type_fallback_rows"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                ReportUnitRow.revenue != 0,
                                report_type_fallback_condition,
                            ),
                            ReportUnitRow.revenue,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("report_type_fallback_revenue"),
            func.coalesce(
                func.sum(ReportUnitRow.storage + ReportUnitRow.acceptance),
                0,
            ).label("storage_and_acceptance"),
            conditional_count(company_cabinet_mismatch).label(
                "company_cabinet_mismatch_rows"
            ),
        )
        .select_from(ReportUnitRow)
        .outerjoin(
            WbCabinet,
            WbCabinet.id == ReportUnitRow.wb_cabinet_id,
        )
        .where(*conditions)
    )
    stats = db.execute(statement).mappings().one()
    return {
        "row_count": int(stats["row_count"] or 0),
        "revenue": float(stats["revenue"] or 0),
        "revenue_with_vat": float(stats["revenue_with_vat"] or 0),
        "revenue_without_vat": float(stats["revenue_without_vat"] or 0),
        "cost": float(stats["cost"] or 0),
        "pnl_without_vat_rows": int(stats["pnl_without_vat_rows"] or 0),
        "profit": float(stats["profit"] or 0),
        "profit_before_tax": float(stats["profit_before_tax"] or 0),
        "pnl_tax_deduction": float(stats["pnl_tax_deduction"] or 0),
        "vat_output": float(stats["vat_output"] or 0),
        "vat_input": float(stats["vat_input"] or 0),
        "vat_input_from_import_scenario": float(
            stats["vat_input_from_import_scenario"] or 0
        ),
        "vat_input_from_wb_scenario": float(stats["vat_input_from_wb_scenario"] or 0),
        "vat_payable": float(stats["vat_payable"] or 0),
        "income_tax": float(stats["income_tax"] or 0),
        "revenue_tax": float(stats["revenue_tax"] or 0),
        "income_tax_included_rows": int(stats["income_tax_included_rows"] or 0),
        "sales": float(stats["sales"] or 0),
        "returns": float(stats["returns"] or 0),
        "loss_rows": int(stats["loss_rows"] or 0),
        "penalty_only_rows": int(stats["penalty_only_rows"] or 0),
        "ok_rows": int(stats["ok_rows"] or 0),
        "missing_cost_rows": int(stats["missing_cost_rows"] or 0),
        "cost_requires_review_rows": int(stats["cost_requires_review_rows"] or 0),
        "cost_absent_rows": int(stats["cost_absent_rows"] or 0),
        "mapping_rows": int(stats["mapping_rows"] or 0),
        "partial_rows": int(stats["partial_rows"] or 0),
        "problem_rows": int(stats["problem_rows"] or 0),
        "tax_profile_issue_rows": int(stats["tax_profile_issue_rows"] or 0),
        "osno_rows": int(stats["osno_rows"] or 0),
        "pnl_method_mismatch_rows": int(stats["pnl_method_mismatch_rows"] or 0),
        "profit_semantics_mismatch_rows": int(
            stats["profit_semantics_mismatch_rows"] or 0
        ),
        "vat_input_unconfirmed_rows": int(stats["vat_input_unconfirmed_rows"] or 0),
        "vat_input_management_assumption_rows": int(
            stats["vat_input_management_assumption_rows"] or 0
        ),
        "missing_cost_affected_revenue": float(
            stats["missing_cost_affected_revenue"] or 0
        ),
        "report_type_fallback_rows": int(stats["report_type_fallback_rows"] or 0),
        "report_type_fallback_revenue": float(
            stats["report_type_fallback_revenue"] or 0
        ),
        "storage_and_acceptance": float(stats["storage_and_acceptance"] or 0),
        "company_cabinet_mismatch_rows": int(
            stats["company_cabinet_mismatch_rows"] or 0
        ),
    }


def _count_rows(db: Session, *conditions: Any) -> int:
    statement = select(func.count()).select_from(ReportUnitRow)
    for condition in conditions:
        statement = statement.where(condition)
    return int(db.scalar(statement) or 0)


def _count_lost_sales_rows(db: Session, *conditions: Any) -> int:
    statement = select(func.count()).select_from(ReportLostSalesRow)
    for condition in conditions:
        statement = statement.where(condition)
    return int(db.scalar(statement) or 0)


def _sum_column(db: Session, column: Any, *conditions: Any) -> float:
    statement = select(func.coalesce(func.sum(column), 0))
    for condition in conditions:
        statement = statement.where(condition)
    return float(db.scalar(statement) or 0)


def _pnl_revenue_expression() -> Any:
    return case(
        (
            _pnl_without_vat_condition(),
            ReportUnitRow.revenue_without_vat,
        ),
        else_=ReportUnitRow.revenue,
    )


def _pnl_profit_expression() -> Any:
    return case(
        (
            ReportUnitRow.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
            ReportUnitRow.profit_before_tax,
        ),
        else_=ReportUnitRow.profit,
    )


def _pnl_tax_deduction_expression() -> Any:
    """Return taxes that reduce the product P&L, not all tax obligations."""

    included_income_tax = case(
        (ReportUnitRow.income_tax_included.is_(True), ReportUnitRow.income_tax),
        else_=0,
    )
    return case(
        (_pnl_without_vat_condition(), 0),
        else_=(ReportUnitRow.vat_payable + ReportUnitRow.usn + included_income_tax),
    )


def _pnl_without_vat_condition() -> Any:
    return or_(
        ReportUnitRow.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
        ReportUnitRow.tax_method.ilike("%ОСНО%"),
    )


def _pnl_expense_expression(key: str) -> Any:
    amount = getattr(ReportUnitRow, key)
    if key not in VAT_ELIGIBLE_SERVICE_EXPENSE_FIELDS:
        return amount
    service_gross = sum(
        (getattr(ReportUnitRow, field) for field in SERVICE_EXPENSE_FIELDS),
        0,
    )
    vat_base = sum(
        (
            getattr(ReportUnitRow, field)
            for field in VAT_ELIGIBLE_SERVICE_EXPENSE_FIELDS
        ),
        0,
    )
    service_vat = case(
        (
            and_(_pnl_without_vat_condition(), service_gross != 0),
            _pnl_profit_expression()
            - _pnl_revenue_expression()
            + ReportUnitRow.cost
            + service_gross,
        ),
        else_=0,
    )
    allocated_vat = case(
        (vat_base != 0, service_vat * amount / vat_base),
        else_=0,
    )
    return amount - allocated_vat


def _penalty_only_condition() -> Any:
    return and_(
        ReportUnitRow.sales == 0,
        ReportUnitRow.returns == 0,
        ReportUnitRow.net_qty == 0,
        ReportUnitRow.revenue == 0,
        ReportUnitRow.cost == 0,
        ReportUnitRow.commission == 0,
        ReportUnitRow.logistics == 0,
        ReportUnitRow.storage == 0,
        ReportUnitRow.acceptance == 0,
        ReportUnitRow.promotion == 0,
        ReportUnitRow.acquiring == 0,
        ReportUnitRow.penalties != 0,
    )


def _lost_sales_coverage_payload(
    db: Session,
    report: ReportRun,
    *,
    requested_period_start: date | None = None,
    requested_period_end: date | None = None,
    cabinet: str = "",
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    request_start = max(
        requested_period_start or report.period_start,
        report.period_start,
    )
    request_end = min(requested_period_end or report.period_end, report.period_end)
    total_days = max(0, (request_end - request_start).days + 1)
    filtered_request = bool(
        requested_period_start or requested_period_end or cabinet or wb_cabinet_id
    )
    load = db.scalar(
        select(SourceLoad)
        .where(
            SourceLoad.report_run_id == report.id,
            SourceLoad.source_type == "wb_stock_history_daily",
        )
        .order_by(SourceLoad.id.desc())
    )
    if load is None or not load.source_refresh_run_id:
        return {
            "status": "not_loaded",
            "calculated": False,
            "providerWindowCalculated": False,
            "fullCoverage": False,
            "coveredDays": 0,
            "totalDays": total_days,
            "requestedPeriodStart": request_start.isoformat(),
            "requestedPeriodEnd": request_end.isoformat(),
            "calculationPeriodStart": None,
            "calculationPeriodEnd": None,
            "calculationContextVersion": None,
            "extrapolated": False,
            "message": "Не рассчитано: история остатков для этого отчета не загружена.",
            "accounts": [],
        }
    collections = list(
        db.scalars(
            select(SourceRefreshCollection)
            .where(
                SourceRefreshCollection.refresh_run_id == load.source_refresh_run_id,
                SourceRefreshCollection.source_type == "wb_stock_history_daily",
            )
            .order_by(SourceRefreshCollection.id)
        )
    )
    accounts: list[dict[str, Any]] = []
    for collection in collections:
        payload = collection.payload or {}
        context_version = str(payload.get("calculationContextVersion") or "")
        calculation_period_start = payload.get("calculationPeriodStart") or payload.get(
            "actualPeriodStart"
        )
        calculation_period_end = payload.get("calculationPeriodEnd") or payload.get(
            "actualPeriodEnd"
        )
        source_accounts = payload.get("accounts")
        if isinstance(source_accounts, list):
            for item in source_accounts:
                if isinstance(item, Mapping):
                    account = dict(item)
                    account.setdefault(
                        "calculationPeriodStart", calculation_period_start
                    )
                    account.setdefault("calculationPeriodEnd", calculation_period_end)
                    account.setdefault("fullCoverage", False)
                    account.setdefault("extrapolated", False)
                    account.setdefault("calculationContextVersion", context_version)
                    account["providerWindowCalculated"] = bool(
                        account.get("providerWindowCalculated")
                        if "providerWindowCalculated" in account
                        else account.get("calculated")
                    )
                    account["calculated"] = bool(
                        account.get("providerWindowCalculated")
                    )
                    accounts.append(account)
            continue
        accounts.append(
            {
                "sellerAccountId": payload.get("sellerAccountId") or "",
                "cabinet": payload.get("cabinet") or collection.source_label,
                "status": payload.get("status") or collection.status,
                "coveredDays": int(payload.get("coveredDays") or 0),
                "totalDays": int(payload.get("totalDays") or total_days),
                "calculated": bool(
                    payload.get("providerWindowCalculated")
                    if "providerWindowCalculated" in payload
                    else payload.get("calculated")
                ),
                "providerWindowCalculated": bool(
                    payload.get("providerWindowCalculated")
                    if "providerWindowCalculated" in payload
                    else payload.get("calculated")
                ),
                "fullCoverage": bool(payload.get("fullCoverage")),
                "calculationPeriodStart": calculation_period_start,
                "calculationPeriodEnd": calculation_period_end,
                "calculationContextVersion": context_version,
                "extrapolated": False,
            }
        )
    if cabinet:
        accounts = [
            item for item in accounts if str(item.get("cabinet") or "") == cabinet
        ]
    if wb_cabinet_id:
        accounts = [
            item
            for item in accounts
            if wb_cabinet_id
            in {
                str(item.get("wbCabinetId") or ""),
                str(item.get("sellerAccountId") or ""),
                str(item.get("cabinet") or ""),
            }
        ]
    provider_window_calculated = bool(accounts) and all(
        bool(item.get("providerWindowCalculated")) for item in accounts
    )
    statuses = {str(item.get("status") or "incomplete") for item in accounts}
    calculation_starts = [
        date_or_none(item.get("calculationPeriodStart")) for item in accounts
    ]
    calculation_ends = [
        date_or_none(item.get("calculationPeriodEnd")) for item in accounts
    ]
    valid_starts = [item for item in calculation_starts if item is not None]
    valid_ends = [item for item in calculation_ends if item is not None]
    provider_start = max(valid_starts) if len(valid_starts) == len(accounts) else None
    provider_end = min(valid_ends) if len(valid_ends) == len(accounts) else None
    calculation_period_start = (
        max(request_start, provider_start) if provider_start is not None else None
    )
    calculation_period_end = (
        min(request_end, provider_end) if provider_end is not None else None
    )
    covered_days = (
        (calculation_period_end - calculation_period_start).days + 1
        if calculation_period_start is not None
        and calculation_period_end is not None
        and calculation_period_start <= calculation_period_end
        else 0
    )
    context_version = (
        "lost-sales-filter-v1"
        if collections
        and all(
            str((item.payload or {}).get("calculationContextVersion") or "")
            == "lost-sales-filter-v1"
            for item in collections
        )
        else None
    )
    filter_supported = not filtered_request or context_version is not None
    calculated = bool(provider_window_calculated and covered_days and filter_supported)
    full_coverage = bool(calculated and covered_days == total_days)
    status = (
        "complete"
        if full_coverage
        else "partial_provider_window"
        if calculated
        else "incomplete"
    )
    if "missing_scope" in statuses or "access_error" in statuses:
        status = "missing_scope"
    return {
        "status": status,
        "calculated": calculated,
        "providerWindowCalculated": provider_window_calculated,
        "fullCoverage": full_coverage,
        "coveredDays": covered_days,
        "totalDays": total_days,
        "requestedPeriodStart": request_start.isoformat(),
        "requestedPeriodEnd": request_end.isoformat(),
        "calculationPeriodStart": (
            calculation_period_start.isoformat() if calculated else None
        ),
        "calculationPeriodEnd": (
            calculation_period_end.isoformat() if calculated else None
        ),
        "calculationContextVersion": context_version,
        "extrapolated": False,
        "message": (
            "Покрытие истории остатков полное."
            if full_coverage
            else (
                "Рассчитано за доступный период: история остатков покрывает "
                f"{covered_days} из {total_days} дней, без экстраполяции."
            )
            if calculated
            else (
                "Не рассчитано: история остатков покрывает "
                f"{covered_days} из {total_days} дней."
            )
        ),
        "accounts": accounts,
    }


def _tax_context_payload(
    db: Session,
    report: ReportRun,
    rows: Iterable[ReportUnitRow],
) -> dict[str, Any]:
    report_rows = list(rows)
    return _tax_context_payload_from_row_markers(
        db,
        report,
        row_count=len(report_rows),
        sources={
            str(row.tax_profile_source or "").strip()
            for row in report_rows
            if str(row.tax_profile_source or "").strip()
        },
        company_ids={
            row.client_company_id for row in report_rows if row.client_company_id
        },
    )


def _report_tax_context_payload(
    db: Session,
    report: ReportRun,
    *,
    row_count: int | None = None,
) -> dict[str, Any]:
    markers = db.execute(
        select(
            ReportUnitRow.client_company_id,
            ReportUnitRow.tax_profile_source,
        )
        .where(ReportUnitRow.report_run_id == report.id)
        .distinct()
    )
    company_ids: set[str] = set()
    sources: set[str] = set()
    has_rows = False
    for company_id, source in markers:
        has_rows = True
        if company_id:
            company_ids.add(company_id)
        source_text = str(source or "").strip()
        if source_text:
            sources.add(source_text)
    if row_count is None:
        row_count = 1 if has_rows else 0
    return _tax_context_payload_from_row_markers(
        db,
        report,
        row_count=row_count,
        sources=sources,
        company_ids=company_ids,
    )


def _tax_context_osno_company_ids(tax_context: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for profile in tax_context.get("profiles") or []:
        if not isinstance(profile, Mapping) or profile.get("status") != "ready":
            continue
        checks = [
            check
            for check in profile.get("checks") or []
            if isinstance(check, Mapping) and check.get("taxSystem")
        ]
        if checks and all(
            "осно" in str(check["taxSystem"]).casefold()
            or "общ" in str(check["taxSystem"]).casefold()
            for check in checks
        ):
            company_id = str(profile.get("clientCompanyId") or "")
            if company_id:
                result.add(company_id)
    return result


def _tax_context_payload_from_row_markers(
    db: Session,
    report: ReportRun,
    *,
    row_count: int,
    sources: set[str],
    company_ids: set[str],
) -> dict[str, Any]:
    missing_markers = ("не найден", "missing", "unknown", "не подтверж")
    row_context_missing = not sources or any(
        any(marker in source.casefold() for marker in missing_markers)
        for source in sources
    )
    profiles: list[TaxProfile] = []
    profile_statuses: list[dict[str, Any]] = []
    company_profiles_ready: list[bool] = []
    for company_id in sorted(company_ids):
        company = db.get(ClientCompany, company_id)
        company_profiles, checks, company_ready = _company_tax_profiles_for_period(
            db,
            company=company,
            period_start=report.period_start,
            period_end=report.period_end,
        )
        company_profiles_ready.append(company_ready)
        profiles.extend(company_profiles)
        profile_statuses.append(
            {
                "clientCompanyId": company_id,
                "organization": company.display_name if company is not None else "",
                "organizationId": (
                    company.onec_organization_id if company is not None else ""
                ),
                "status": "ready" if company_ready else "unconfirmed",
                "periodStart": report.period_start.isoformat(),
                "periodEnd": report.period_end.isoformat(),
                "checks": checks,
            }
        )
    all_profiles_ready = bool(company_ids) and all(company_profiles_ready)
    calculated = row_count > 0 and all_profiles_ready and not row_context_missing
    if not calculated:
        return {
            "status": "missing",
            "calculated": False,
            "taxSystem": None,
            "vatRate": None,
            "vatMode": None,
            "vatDeductionMode": "unknown",
            "revenueTaxRate": None,
            "incomeTaxKind": None,
            "source": "missing",
            "rateBasisKind": None,
            "basisDocument": None,
            "confirmedBy": None,
            "sourceObjectIds": [],
            "message": (
                "Настройки налогообложения организации из 1С не загружены "
                "или не применены к этому отчёту."
            ),
            "profiles": profile_statuses,
        }
    tax_systems = {profile.tax_system for profile in profiles}
    vat_rates = {profile.vat_rate for profile in profiles}
    vat_modes = {profile.vat_mode.value for profile in profiles}
    deduction_modes = {profile.vat_deduction_mode.value for profile in profiles}
    revenue_rates = {profile.revenue_tax_rate for profile in profiles}
    income_tax_kinds = {profile.income_tax_kind for profile in profiles}
    rate_basis_kinds = {profile.rate_basis_kind for profile in profiles}
    basis_documents = {profile.basis_document for profile in profiles}
    confirmed_by_values = {profile.confirmed_by for profile in profiles}
    source_object_ids = sorted(
        {value for profile in profiles for value in profile.source_object_ids}
    )
    mixed = any(
        len(values) > 1
        for values in (
            tax_systems,
            vat_rates,
            vat_modes,
            deduction_modes,
            revenue_rates,
            income_tax_kinds,
        )
    )
    return {
        "status": "mixed" if mixed else "ready",
        "calculated": True,
        "taxSystem": next(iter(tax_systems)) if len(tax_systems) == 1 else "mixed",
        "vatRate": float(next(iter(vat_rates))) if len(vat_rates) == 1 else None,
        "vatMode": next(iter(vat_modes)) if len(vat_modes) == 1 else "mixed",
        "vatDeductionMode": (
            next(iter(deduction_modes)) if len(deduction_modes) == 1 else "mixed"
        ),
        "revenueTaxRate": (
            float(next(iter(revenue_rates))) if len(revenue_rates) == 1 else None
        ),
        "incomeTaxKind": (
            next(iter(income_tax_kinds)) if len(income_tax_kinds) == 1 else "mixed"
        ),
        "source": "mixed" if len(sources) > 1 else next(iter(sources), "profile"),
        "rateBasisKind": (
            next(iter(rate_basis_kinds)) if len(rate_basis_kinds) == 1 else "mixed"
        ),
        "basisDocument": (
            next(iter(basis_documents)) if len(basis_documents) == 1 else "mixed"
        ),
        "confirmedBy": (
            next(iter(confirmed_by_values))
            if len(confirmed_by_values) == 1
            else "mixed"
        ),
        "sourceObjectIds": source_object_ids,
        "message": (
            "Данные 1С и основание региональной льготной ставки применены."
            if rate_basis_kinds == {"regional_preference"} and all(basis_documents)
            else ("Налоговый профиль и сохраненная в настройках ставка применены.")
            if any(profile.revenue_tax_rate > 0 for profile in profiles)
            else "Налоговые настройки организации из 1С применены."
        ),
        "profiles": profile_statuses,
    }


def tax_profile_sync_payload(
    db: Session,
    report: ReportRun,
    *,
    tax_context: Mapping[str, Any] | None = None,
    include_staff_details: bool = False,
) -> dict[str, Any]:
    """Separate the live 1C profile state from the immutable report state."""

    if tax_context is None:
        tax_context = _report_tax_context_payload(db, report)

    latest_collection = db.scalar(
        select(SourceRefreshCollection)
        .join(
            SourceRefreshRun,
            SourceRefreshRun.id == SourceRefreshCollection.refresh_run_id,
        )
        .where(
            SourceRefreshRun.tenant_id == report.tenant_id,
            SourceRefreshRun.client_id == report.client_id,
            SourceRefreshCollection.source_type == "onec_tax_profiles",
        )
        .order_by(
            SourceRefreshRun.created_at.desc(),
            SourceRefreshCollection.id.desc(),
        )
    )
    report_load = db.scalar(
        select(SourceLoad)
        .where(
            SourceLoad.report_run_id == report.id,
            SourceLoad.source_type == "onec_tax_profiles",
        )
        .order_by(SourceLoad.loaded_at.desc(), SourceLoad.id.desc())
    )

    collection_payload = latest_collection.payload if latest_collection else {}
    live_profile_count = int(collection_payload.get("profileCount") or 0)
    aggregate_live_ready = bool(
        latest_collection is not None
        and latest_collection.status in SOURCE_LOAD_OK_STATUSES
        and live_profile_count > 0
        and int(collection_payload.get("missingProfileCount") or 0) == 0
        and int(collection_payload.get("unconfirmedProfileCount") or 0) == 0
    )
    scope_status = "not_ready"
    if aggregate_live_ready and latest_collection is not None:
        latest_refresh = db.get(SourceRefreshRun, latest_collection.refresh_run_id)
        report_company_ids = {
            company_id
            for company_id in db.scalars(
                select(ReportUnitRow.client_company_id)
                .where(
                    ReportUnitRow.report_run_id == report.id,
                    ReportUnitRow.client_company_id != "",
                )
                .distinct()
            )
            if company_id
        }
        scope_ready = bool(report_company_ids and latest_refresh is not None)
        scope_mismatch = False
        for company_id in sorted(report_company_ids):
            company = db.get(ClientCompany, company_id)
            _profiles, _checks, company_ready = _company_tax_profiles_for_period(
                db,
                company=company,
                period_start=report.period_start,
                period_end=report.period_end,
                refresh_run=latest_refresh,
            )
            if company_ready:
                continue
            scope_ready = False
            if company is None or not company.onec_organization_id:
                continue
            alternate = db.scalar(
                select(OrganizationTaxProfile.id).where(
                    OrganizationTaxProfile.source_refresh_run_id
                    == latest_collection.refresh_run_id,
                    OrganizationTaxProfile.client_id == report.client_id,
                    OrganizationTaxProfile.organization_id
                    == company.onec_organization_id,
                    OrganizationTaxProfile.client_company_id != company.id,
                    OrganizationTaxProfile.status == "active",
                )
            )
            scope_mismatch = scope_mismatch or alternate is not None
        scope_status = (
            "ready"
            if scope_ready
            else "scope_mismatch"
            if scope_mismatch
            else "missing"
        )
    live_ready = aggregate_live_ready and scope_status == "ready"
    report_calculated = bool(tax_context.get("calculated"))
    hashes_match = bool(
        latest_collection is not None
        and report_load is not None
        and latest_collection.snapshot_hash
        and report_load.snapshot_hash == latest_collection.snapshot_hash
    )

    if report_calculated and (
        latest_collection is None or (hashes_match and scope_status == "ready")
    ):
        report_status = "applied"
        message = "Налоговый профиль применён в текущем отчёте."
    elif report_calculated and live_ready:
        report_status = "stale"
        message = "Налоговый профиль обновлён после расчёта текущего отчёта."
    elif live_ready:
        report_status = "confirmed_not_applied"
        message = "Подтверждён в 1С, но ещё не применён в текущем отчёте."
    elif aggregate_live_ready and scope_status == "scope_mismatch":
        report_status = "scope_mismatch"
        message = "Профиль 1С связан с другой карточкой организации отчёта."
    else:
        report_status = "missing"
        message = str(
            tax_context.get("message")
            or "Настройки налогообложения из 1С не применены к отчёту."
        )

    needs_rebuild = live_ready and report_status != "applied"
    if not include_staff_details:
        client_applied = report_status == "applied"
        return {
            "reportStatus": "applied" if client_applied else "not_applied",
            "needsRebuild": needs_rebuild,
            "message": (
                "Налоговый профиль применён в текущем отчёте."
                if client_applied
                else "Налоговый профиль ещё не применён в расчёте текущего отчёта."
            ),
        }
    return {
        "liveStatus": "ready" if live_ready else "not_ready",
        "scopeStatus": scope_status,
        "reportStatus": report_status,
        "needsRebuild": needs_rebuild,
        "liveProfileCount": live_profile_count,
        "sourceRefreshRunId": (
            latest_collection.refresh_run_id if latest_collection else None
        ),
        "message": message,
    }


def _company_tax_profiles_for_period(
    db: Session,
    *,
    company: ClientCompany | None,
    period_start: date,
    period_end: date,
    refresh_run: SourceRefreshRun | None = None,
) -> tuple[list[TaxProfile], list[dict[str, Any]], bool]:
    check_dates = _tax_profile_period_check_dates(
        db,
        company=company,
        period_start=period_start,
        period_end=period_end,
        refresh_run=refresh_run,
    )
    profiles_by_signature: dict[tuple[Any, ...], TaxProfile] = {}
    checks: list[dict[str, Any]] = []
    ready = True
    for calculation_date in check_dates:
        profile, profile_status = resolve_company_tax_profile(
            db,
            company=company,
            calculation_date=calculation_date,
            refresh_run=refresh_run,
        )
        check = dict(profile_status)
        check["date"] = calculation_date.isoformat()
        if profile is None:
            ready = False
            checks.append(check)
            continue
        check["vatDeductionMode"] = profile.vat_deduction_mode.value
        check["taxSystem"] = profile.tax_system
        check["validFrom"] = (
            profile.valid_from.isoformat() if profile.valid_from else None
        )
        check["validTo"] = profile.valid_to.isoformat() if profile.valid_to else None
        check["rateBasisKind"] = profile.rate_basis_kind
        check["basisDocument"] = profile.basis_document
        check["confirmedBy"] = profile.confirmed_by
        check["sourceObjectIds"] = profile.source_object_ids
        confirmed = tax_profile_is_confirmed(profile)
        check["confirmed"] = confirmed
        if not confirmed:
            check["status"] = "unconfirmed"
            ready = False
        profiles_by_signature.setdefault(_tax_profile_signature(profile), profile)
        checks.append(check)
    profiles = list(profiles_by_signature.values())
    if not profiles:
        ready = False
    tax_system_kinds = {tax_profile_is_osno(profile) for profile in profiles}
    if len(tax_system_kinds) > 1:
        ready = False
        checks.append(
            {
                "status": "unconfirmed",
                "message": "Налоговая система меняется внутри периода отчета.",
            }
        )
    return profiles, checks, ready


def _tax_profile_period_check_dates(
    db: Session,
    *,
    company: ClientCompany | None,
    period_start: date,
    period_end: date,
    refresh_run: SourceRefreshRun | None = None,
) -> list[date]:
    dates = {period_start, period_end}
    if company is None or not company.onec_organization_id:
        return sorted(dates)
    source_conditions = [
        OrganizationTaxProfile.client_company_id == company.id,
        OrganizationTaxProfile.organization_id == company.onec_organization_id,
        OrganizationTaxProfile.status == "active",
        or_(
            OrganizationTaxProfile.valid_to.is_(None),
            OrganizationTaxProfile.valid_to >= period_start,
        ),
        or_(
            OrganizationTaxProfile.valid_from.is_(None),
            OrganizationTaxProfile.valid_from <= period_end,
        ),
    ]
    if refresh_run is not None:
        source_conditions.append(
            OrganizationTaxProfile.source_refresh_run_id == refresh_run.id
        )
    source_profiles = list(
        db.scalars(select(OrganizationTaxProfile).where(*source_conditions))
    )
    overrides = list(
        db.scalars(
            select(OrganizationTaxProfileOverride).where(
                OrganizationTaxProfileOverride.client_company_id == company.id,
                OrganizationTaxProfileOverride.organization_id
                == company.onec_organization_id,
                OrganizationTaxProfileOverride.status == "active",
                or_(
                    OrganizationTaxProfileOverride.valid_to.is_(None),
                    OrganizationTaxProfileOverride.valid_to >= period_start,
                ),
                OrganizationTaxProfileOverride.valid_from <= period_end,
            )
        )
    )
    for profile in [*source_profiles, *overrides]:
        if (
            profile.valid_from is not None
            and period_start <= profile.valid_from <= period_end
        ):
            dates.add(profile.valid_from)
        if (
            profile.valid_to is not None
            and period_start <= profile.valid_to < period_end
        ):
            dates.add(profile.valid_to + timedelta(days=1))
    return sorted(dates)


def _tax_profile_signature(profile: TaxProfile) -> tuple[Any, ...]:
    return (
        profile.organization_id,
        profile.tax_system,
        profile.tax_object,
        profile.tax_rate,
        profile.elevated_tax_rate,
        profile.vat_rate,
        profile.vat_mode.value,
        profile.vat_deduction_mode.value,
        profile.revenue_tax_rate,
        profile.income_tax_kind,
        profile.valid_from,
        profile.valid_to,
        profile.source,
        profile.rate_basis_kind,
        profile.basis_document,
        profile.confirmed_by,
        tuple(profile.source_object_ids),
    )


def _quality_condition(*markers: str) -> Any:
    haystack = func.lower(
        func.coalesce(ReportUnitRow.status, "")
        + " "
        + func.coalesce(ReportUnitRow.status_reason, "")
        + " "
        + func.coalesce(ReportUnitRow.loss_driver, "")
    )
    return or_(*(haystack.like(f"%{marker.lower()}%") for marker in markers))


def _missing_cost_condition() -> Any:
    status = func.lower(func.trim(func.coalesce(ReportUnitRow.status, "")))
    reason = func.lower(func.trim(func.coalesce(ReportUnitRow.status_reason, "")))
    return and_(
        ReportUnitRow.net_qty != 0,
        or_(
            status == "нет себестоимости 1с",
            ReportUnitRow.status == "Нет себестоимости 1С",
            reason.like("%себестоим%"),
            ReportUnitRow.status_reason.like("%Себестоим%"),
            and_(status == "себестоимость 1с требует сверки", reason == ""),
            and_(
                ReportUnitRow.status == "Себестоимость 1С требует сверки",
                ReportUnitRow.status_reason == "",
            ),
        ),
    )


def _missing_cost_absent_condition() -> Any:
    status = func.lower(func.trim(func.coalesce(ReportUnitRow.status, "")))
    return or_(
        status == "нет себестоимости 1с",
        ReportUnitRow.status == "Нет себестоимости 1С",
    )


def _missing_cost_review_condition() -> Any:
    return and_(
        _missing_cost_condition(),
        ~_missing_cost_absent_condition(),
    )


def _mapping_issue_condition() -> Any:
    return and_(
        _quality_condition(
            "сопостав",
            "маппинг",
            "mapping",
            "ambiguous_mapping",
            "missing_mapping",
            "неоднознач",
        ),
        ~_missing_cost_condition(),
    )


def _summary_kpis_payload(
    stats: dict[str, Any],
    *,
    tax_context: Mapping[str, Any] | None = None,
    lost_sales_coverage: Mapping[str, Any] | None = None,
    onec_calendar_revenue: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    revenue = float(stats["revenue"])
    revenue_without_vat = float(stats.get("revenue_without_vat", revenue))
    revenue_with_vat = float(stats.get("revenue_with_vat", revenue))
    profit = float(stats["profit"])
    profit_management = float(stats.get("profit_before_tax", stats["profit"]))
    vat_payable = float(stats.get("vat_payable") or 0)
    management_vat_rows = int(stats.get("vat_input_management_assumption_rows") or 0)
    revenue_tax = float(stats.get("revenue_tax") or 0)
    income_tax = float(stats.get("income_tax") or 0)
    income_tax_included = int(stats.get("income_tax_included_rows") or 0) > 0
    total_tax = vat_payable + revenue_tax + (income_tax if income_tax_included else 0)
    if "pnl_tax_deduction" in stats:
        pnl_tax_deduction = float(stats.get("pnl_tax_deduction") or 0)
    elif int(stats.get("pnl_without_vat_rows") or 0) > 0 and int(
        stats.get("pnl_without_vat_rows") or 0
    ) == int(stats.get("row_count") or 0):
        pnl_tax_deduction = 0.0
    else:
        pnl_tax_deduction = total_tax
    tax_calculated = bool((tax_context or {}).get("calculated"))
    tax_bridge_calculated = bool(
        tax_calculated and abs(profit_management - pnl_tax_deduction - profit) <= 1.0
    )
    lost_sales_calculated = bool((lost_sales_coverage or {}).get("calculated"))
    onec_revenue = dict(onec_calendar_revenue or {})
    return {
        "revenue": revenue,
        "revenueWithoutVat": revenue_without_vat,
        "revenueWithVat": revenue_with_vat,
        "cogs": float(stats.get("cost") or 0),
        "costIssueRows": int(stats.get("missing_cost_rows") or 0),
        "onecRevenueWithVat": onec_revenue.get("revenueWithVat"),
        "onecRevenueDocumentCount": int(onec_revenue.get("documentCount") or 0),
        "onecCommissionerRevenueWithVat": onec_revenue.get(
            "commissionerRevenueWithVat"
        ),
        "onecBuyoutRevenueWithVat": onec_revenue.get("buyoutRevenueWithVat"),
        "onecOtherRevenueWithVat": onec_revenue.get("otherRevenueWithVat"),
        "onecSalesQuantity": onec_revenue.get("salesQuantity"),
        "onecCommissionerQuantity": onec_revenue.get("commissionerQuantity"),
        "onecBuyoutQuantity": onec_revenue.get("buyoutQuantity"),
        "onecOtherQuantity": onec_revenue.get("otherQuantity"),
        "onecCogs": onec_revenue.get("cogs"),
        "onecCommissionerCogs": onec_revenue.get("commissionerCogs"),
        "onecBuyoutCogs": onec_revenue.get("buyoutCogs"),
        "onecOtherCogs": onec_revenue.get("otherCogs"),
        "onecCogsWithoutVat": onec_revenue.get("cogsWithoutVat"),
        "onecGrossProfit": onec_revenue.get("grossProfit"),
        "onecCostAdjustmentRows": int(onec_revenue.get("costAdjustmentRows") or 0),
        "pnlCogs": float(stats.get("cost") or 0),
        "wbDocumentRevenueWithVat": onec_revenue.get("wbRevenueWithVat"),
        "wbCommissionerRevenueWithVat": onec_revenue.get(
            "wbCommissionerRevenueWithVat"
        ),
        "wbBuyoutRetailRevenueWithVat": onec_revenue.get(
            "wbBuyoutRetailRevenueWithVat"
        ),
        "commissionerRevenueDelta": onec_revenue.get("commissionerRevenueDelta"),
        "buyoutRevenueDelta": onec_revenue.get("buyoutRevenueDelta"),
        "buyoutPrimaryDocumentAmount": onec_revenue.get("buyoutPrimaryDocumentAmount"),
        "buyoutPrimaryDocumentDelta": onec_revenue.get("buyoutPrimaryDocumentDelta"),
        "buyoutPrimaryDocumentStatus": onec_revenue.get("buyoutPrimaryDocumentStatus"),
        "buyoutUnverifiedPrimaryRows": int(
            onec_revenue.get("buyoutUnverifiedPrimaryRows") or 0
        ),
        "wbDocumentRevenueDeltaVsOnec": onec_revenue.get("wbRevenueDeltaVsOnec"),
        "accountingReconciliationWbAmount": onec_revenue.get(
            "accountingReconciliationWbAmount"
        ),
        "accountingReconciliationOnecAmount": onec_revenue.get(
            "accountingReconciliationOnecAmount"
        ),
        "accountingReconciliationDelta": onec_revenue.get(
            "accountingReconciliationDelta"
        ),
        "accountingReconciliationStatus": onec_revenue.get(
            "accountingReconciliationStatus"
        ),
        "accountingReconciliationBuyoutBasis": onec_revenue.get(
            "accountingReconciliationBuyoutBasis"
        ),
        "pnlWithoutVat": int(stats.get("pnl_without_vat_rows") or 0) > 0,
        "profit": profit if tax_calculated else None,
        "profitBeforeTax": profit_management,
        "profitManagement": profit_management,
        "profitAfterTax": profit if tax_calculated else None,
        "profitAfterIncomeTax": profit if tax_calculated else None,
        "marginAfterTax": (
            profit / revenue if tax_bridge_calculated and revenue else None
        ),
        "incomeTaxIncluded": (
            int(stats.get("income_tax_included_rows") or 0) > 0
            if tax_calculated
            else False
        ),
        "incomeTax": income_tax if tax_calculated else None,
        "revenueTax": revenue_tax if tax_calculated else None,
        "totalTax": total_tax if tax_calculated else None,
        "taxBridgeCalculated": tax_bridge_calculated,
        "vatOutput": float(stats.get("vat_output") or 0) if tax_calculated else None,
        "vatInput": float(stats.get("vat_input") or 0) if tax_calculated else None,
        "vatPayable": vat_payable if tax_calculated else None,
        "vatInputEstimated": (
            float(stats.get("vat_input") or 0)
            if tax_calculated and management_vat_rows
            else None
        ),
        "vatPayableEstimated": (
            vat_payable if tax_calculated and management_vat_rows else None
        ),
        "vatInputFromImportScenario": float(
            stats.get("vat_input_from_import_scenario") or 0
        ),
        "vatInputFromWbScenario": float(stats.get("vat_input_from_wb_scenario") or 0),
        "inputVatMode": (
            "management_assumption" if management_vat_rows else "accounting_fact"
        ),
        "vatInputConfirmed": bool(
            tax_calculated
            and int(stats.get("osno_rows") or 0) > 0
            and not management_vat_rows
            and int(stats.get("vat_input_unconfirmed_rows") or 0) == 0
        ),
        "margin": profit / revenue if revenue and tax_calculated else None,
        "marginManagement": profit_management / revenue if revenue else None,
        "sales": float(stats["sales"]),
        "returns": float(stats["returns"]),
        "lossRows": int(stats["loss_rows"]),
        "penaltyOnlyRows": int(stats.get("penalty_only_rows") or 0),
        "lostSalesRows": int(stats.get("lost_sales_rows") or 0),
        "lostSalesUnits": (
            float(stats.get("lost_sales_units") or 0) if lost_sales_calculated else None
        ),
        "lostSalesRevenue": (
            float(stats.get("lost_sales_revenue") or 0)
            if lost_sales_calculated
            else None
        ),
        "lostSalesProfit": (
            float(stats.get("lost_sales_profit") or 0)
            if lost_sales_calculated
            else None
        ),
        "lostContributionMargin": (
            float(stats.get("lost_sales_profit") or 0)
            if lost_sales_calculated
            else None
        ),
        "rowCount": int(stats["row_count"]),
    }


def _summary_quality_payload(
    stats: dict[str, Any],
    loads: list[SourceLoad],
    report: ReportRun,
    *,
    document_reconciliation_rows: list[ReportDocumentReconciliationRow] | None = None,
) -> dict[str, Any]:
    row_count = int(stats["row_count"])
    ok_rows = int(stats["ok_rows"])
    incomplete_sources = sum(
        1
        for load in loads
        if not _source_load_ok(load) and not _source_load_failed(load)
    )
    document_kpis = _document_reconciliation_kpis(document_reconciliation_rows or [])
    return {
        "okRows": ok_rows,
        "okShare": ok_rows / row_count if row_count else 0,
        "missingCostRows": int(stats["missing_cost_rows"]),
        "mappingRows": int(stats["mapping_rows"]),
        "partialPeriod": _is_partial_period(report),
        "incompleteSources": incomplete_sources,
        "rowCount": row_count,
        "documentReconciliationRows": document_kpis["documentCount"],
        "documentReconciliationIssues": document_kpis["issueRows"],
        "documentReconciliationDeltaAmount": document_kpis["amountDelta"],
        "documentReconciliationMissingOnec": document_kpis["missingOnecRows"],
    }


def _summary_options_payload(
    db: Session,
    report: ReportRun,
    *,
    liquidity_rows: list[dict[str, Any]],
    document_reconciliation: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = db.execute(
        select(
            ReportUnitRow.week,
            ReportUnitRow.accounting_period_date,
            ReportUnitRow.month,
            ReportUnitRow.wb_cabinet_id,
            ReportUnitRow.cabinet,
            ReportUnitRow.client_company_id,
            ReportUnitRow.organization,
            ReportUnitRow.scheme,
            ReportUnitRow.status,
            ReportUnitRow.loss_class,
            ReportUnitRow.document_report,
        ).where(ReportUnitRow.report_run_id == report.id)
    )
    months: set[str] = set()
    period_dates: set[date] = set()
    cabinets: dict[str, str] = {}
    organizations: dict[str, str] = {}
    schemes: set[str] = set()
    statuses: set[str] = set()
    loss_classes: set[str] = set()
    document_reports: set[str] = set()
    for row in rows:
        (
            week,
            accounting_period_date,
            stored_month,
            cabinet_id,
            cabinet,
            company_id,
            organization,
            scheme,
            status,
            loss_class,
            document_report,
        ) = row
        month = _effective_month_label(
            week,
            stored_month or "",
            accounting_period_date=accounting_period_date,
        )
        if month:
            months.add(month)
        period_date = _row_filter_period_date(
            week=week,
            accounting_period_date=accounting_period_date,
        )
        if period_date is not None:
            period_dates.add(period_date)
        cabinet_key = as_text(cabinet_id) or as_text(cabinet)
        if cabinet_key:
            cabinets.setdefault(cabinet_key, as_text(cabinet) or cabinet_key)
        company_key = as_text(company_id) or as_text(organization)
        if company_key:
            organizations.setdefault(
                company_key,
                as_text(organization) or company_key,
            )
        if scheme:
            schemes.add(as_text(scheme))
        if status:
            statuses.add(as_text(status))
        if loss_class:
            loss_classes.add(as_text(loss_class))
        if document_report:
            document_reports.add(as_text(document_report))

    statuses.update(
        as_text(row.get("status"))
        for row in document_reconciliation
        if row.get("status")
    )
    document_reports = {
        *document_reports,
        *(
            as_text(row.get("documentReport"))
            for row in document_reconciliation
            if row.get("documentReport")
        ),
    }
    document_statuses = {
        as_text(row.get("status"))
        for row in document_reconciliation
        if row.get("status")
    }
    document_types = {
        as_text(row.get("documentType"))
        for row in document_reconciliation
        if row.get("documentType")
    }
    return {
        "months": _ordered_values(list(months)),
        "periodStart": min(period_dates).isoformat() if period_dates else "",
        "periodEnd": max(period_dates).isoformat() if period_dates else "",
        "cabinets": [
            {"id": item_id, "label": label}
            for item_id, label in sorted(
                cabinets.items(), key=lambda item: item[1].lower()
            )
        ],
        "organizations": [
            {"id": item_id, "label": label}
            for item_id, label in sorted(
                organizations.items(), key=lambda item: item[1].lower()
            )
        ],
        "schemes": sorted(schemes),
        "statuses": sorted(status for status in statuses if status),
        "lossClasses": sorted(loss_classes),
        "liquidityStatuses": liquidity_statuses(liquidity_rows),
        "documentReconciliationStatuses": sorted(
            status for status in document_statuses if status
        ),
        "documentTypes": sorted(item for item in document_types if item),
        "documentReports": sorted(item for item in document_reports if item),
    }


def _distinct_unit_values(
    db: Session, report: ReportRun, column: Any, *, skip_empty: bool = True
) -> list[Any]:
    conditions = [ReportUnitRow.report_run_id == report.id, column.is_not(None)]
    if skip_empty:
        conditions.append(column != "")
    values = db.scalars(select(column).where(*conditions).distinct().order_by(column))
    return list(values)


def _distinct_effective_months(db: Session, report: ReportRun) -> list[str]:
    rows = db.execute(
        select(
            ReportUnitRow.week,
            ReportUnitRow.accounting_period_date,
            ReportUnitRow.month,
        )
        .where(ReportUnitRow.report_run_id == report.id)
        .distinct()
    )
    return sorted(
        {
            month
            for week, accounting_period_date, stored_month in rows
            if (
                month := _effective_month_label(
                    week,
                    stored_month,
                    accounting_period_date=accounting_period_date,
                )
            )
        }
    )


def _distinct_entities(
    db: Session, report: ReportRun, id_column: Any, label_column: Any
) -> list[dict[str, str]]:
    rows = db.execute(
        select(id_column, label_column)
        .where(
            ReportUnitRow.report_run_id == report.id,
            or_(id_column != "", label_column != ""),
        )
        .distinct()
        .order_by(label_column, id_column)
    )
    entities: dict[str, str] = {}
    for entity_id, label in rows:
        entity_id_text = as_text(entity_id)
        label_text = as_text(label)
        stable_id = entity_id_text or label_text
        if stable_id:
            entities.setdefault(stable_id, label_text or stable_id)
    return [
        {"id": entity_id, "label": label}
        for entity_id, label in sorted(
            entities.items(), key=lambda item: item[1].lower()
        )
    ]


def _ordered_values(values: list[str]) -> list[str]:
    return sorted(
        (item for item in values if item),
        key=lambda item: (_month_start_from_label(item) or date.max, item),
    )


def _month_start_from_label(value: str) -> date | None:
    match = re.match(r"^([А-Яа-яЁё]+)\s+(\d{4})", value.strip())
    if match is None:
        return None
    month_number = RU_MONTH_NUMBERS.get(match.group(1).casefold())
    if month_number is None:
        return None
    return date(int(match.group(2)), month_number, 1)


def _month_start_from_row_payload(row: Mapping[str, Any]) -> date | None:
    accounting_period_date = date_or_none(row.get("accountingPeriodDate"))
    if accounting_period_date is not None:
        return accounting_period_date.replace(day=1)
    week = date_or_none(row.get("week"))
    if week is None:
        return None
    closing_date = week + timedelta(days=6)
    return closing_date.replace(day=1)


def _month_period_metadata(
    month_start: date | None,
    *,
    period_start: date | None,
    period_end: date | None,
    fallback_partial: bool = False,
) -> dict[str, Any]:
    if month_start is None:
        return {
            "isPartial": fallback_partial,
            "daysElapsed": 0,
            "daysInMonth": 0,
        }
    days_in_month = monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=days_in_month)
    if period_start is None or period_end is None:
        return {
            "isPartial": fallback_partial,
            "daysElapsed": 0 if fallback_partial else days_in_month,
            "daysInMonth": days_in_month,
        }
    covered_start = max(month_start, period_start)
    covered_end = min(month_end, period_end)
    days_elapsed = max(0, (covered_end - covered_start).days + 1)
    return {
        "isPartial": days_elapsed < days_in_month,
        "daysElapsed": days_elapsed,
        "daysInMonth": days_in_month,
    }


def _summary_monthly_payload(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    return _monthly_payload_for_conditions(
        db,
        ReportUnitRow.report_run_id == report.id,
        report=report,
    )


def _monthly_payload_for_conditions(
    db: Session, *conditions: Any, report: ReportRun | None = None
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            ReportUnitRow.week,
            ReportUnitRow.accounting_period_date,
            ReportUnitRow.month,
            func.coalesce(func.sum(ReportUnitRow.sales), 0),
            func.coalesce(func.sum(ReportUnitRow.returns), 0),
            func.coalesce(func.sum(_pnl_revenue_expression()), 0),
            func.coalesce(func.sum(_pnl_profit_expression()), 0),
        )
        .where(*conditions)
        .group_by(
            ReportUnitRow.week,
            ReportUnitRow.accounting_period_date,
            ReportUnitRow.month,
        )
    )
    buckets: dict[str, dict[str, Any]] = {}
    for (
        week,
        accounting_period_date,
        stored_month,
        sales,
        returns,
        revenue,
        profit,
    ) in rows:
        month = _effective_month_label(
            week,
            stored_month,
            accounting_period_date=accounting_period_date,
        )
        if not month:
            continue
        month_start = (
            accounting_period_date.replace(day=1)
            if accounting_period_date is not None
            else (week + timedelta(days=6)).replace(day=1)
            if week is not None
            else _month_start_from_label(month)
        )
        month_key = month_start.isoformat() if month_start else month
        sales_float = float(sales or 0)
        returns_float = float(returns or 0)
        revenue_float = float(revenue or 0)
        profit_float = float(profit or 0)
        bucket = buckets.setdefault(
            month_key,
            {
                "month": month,
                "monthStart": month_start.isoformat() if month_start else "",
                "sales": 0.0,
                "returns": 0.0,
                "revenue": 0.0,
                "profit": 0.0,
            },
        )
        bucket["sales"] += sales_float
        bucket["returns"] += returns_float
        bucket["revenue"] += revenue_float
        bucket["profit"] += profit_float
    for bucket in buckets.values():
        metadata = _month_period_metadata(
            date_or_none(bucket.get("monthStart")),
            period_start=report.period_start if report else None,
            period_end=report.period_end if report else None,
            fallback_partial="непол" in str(bucket.get("month") or "").casefold(),
        )
        bucket.update(metadata)
        bucket["status"] = "неполный месяц" if bucket["isPartial"] else "полный месяц"
        bucket["return_rate"] = (
            bucket["returns"] / bucket["sales"] if bucket["sales"] else None
        )
        bucket["margin"] = (
            bucket["profit"] / bucket["revenue"] if bucket["revenue"] else None
        )
    return sorted(
        buckets.values(),
        key=lambda item: str(item.get("monthStart") or item.get("month") or ""),
    )


def _summary_expense_payload(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    return _expense_payload_for_conditions(db, ReportUnitRow.report_run_id == report.id)


def _expense_payload_for_conditions(
    db: Session, *conditions: Any
) -> list[dict[str, Any]]:
    statement = select(
        func.coalesce(func.sum(_pnl_revenue_expression()), 0).label("revenue"),
        *(
            func.coalesce(func.sum(_pnl_expense_expression(key)), 0).label(key)
            for _, key in EXPENSE_FIELD_LABELS
        ),
    ).where(*conditions)
    aggregates = db.execute(statement).mappings().one()
    revenue = Decimal(str(aggregates["revenue"] or 0))
    result = []
    for label, key in EXPENSE_FIELD_LABELS:
        amount_decimal = Decimal(str(aggregates[key] or 0))
        amount = float(amount_decimal)
        if amount:
            result.append(
                {
                    "expense": label,
                    "amount": amount,
                    "share": float(amount_decimal / revenue) if revenue else None,
                }
            )
    return result


def _summary_liquidity_rows(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    return _top_liquidity_rows_for_conditions(
        db,
        ReportUnitRow.report_run_id == report.id,
        limit=100,
    )


def _top_liquidity_rows_for_conditions(
    db: Session,
    *conditions: Any,
    limit: int,
) -> list[dict[str, Any]]:
    group_columns = {
        field: getattr(ReportUnitRow, _unit_row_column_name(field))
        for field in GROUP_FIELDS
    }
    sum_columns = {
        "sales": ReportUnitRow.sales,
        "returns": ReportUnitRow.returns,
        "netQty": ReportUnitRow.net_qty,
        "revenue": ReportUnitRow.revenue,
        "cost": ReportUnitRow.cost,
        "commission": ReportUnitRow.commission,
        "storage": ReportUnitRow.storage,
        "logistics": ReportUnitRow.logistics,
        "acceptance": ReportUnitRow.acceptance,
        "promotion": ReportUnitRow.promotion,
        "penalties": ReportUnitRow.penalties,
        "acquiring": ReportUnitRow.acquiring,
        "vat": ReportUnitRow.vat,
        "usn": ReportUnitRow.usn,
    }
    sums = {
        field: func.coalesce(func.sum(column), 0)
        for field, column in sum_columns.items()
    }
    row_count = func.count()
    profit_before_tax_count = func.count(ReportUnitRow.profit_before_tax)
    profit_count = func.count(ReportUnitRow.profit)
    profit_before_tax_total = func.coalesce(
        func.sum(ReportUnitRow.profit_before_tax),
        0,
    )
    profit_total = func.coalesce(func.sum(ReportUnitRow.profit), 0)
    diagnostic_before_tax = (
        sums["revenue"]
        - sums["cost"]
        - sums["commission"]
        - sums["storage"]
        - sums["logistics"]
        - sums["acceptance"]
        - sums["promotion"]
        - sums["penalties"]
        - sums["acquiring"]
    )
    effective_before_tax = case(
        (profit_before_tax_count == row_count, profit_before_tax_total),
        else_=diagnostic_before_tax,
    )
    effective_profit = case(
        (profit_count == row_count, profit_total),
        else_=effective_before_tax - sums["vat"] - sums["usn"],
    )
    aggregate_rows = list(
        db.execute(
            select(
                *(column.label(field) for field, column in group_columns.items()),
                *(expression.label(field) for field, expression in sums.items()),
                row_count.label("rowCount"),
                profit_before_tax_count.label("profitBeforeTaxCount"),
                profit_count.label("profitCount"),
                profit_before_tax_total.label("profitBeforeTax"),
                profit_total.label("profit"),
                effective_profit.label("effectiveProfit"),
            )
            .where(*conditions)
            .group_by(*group_columns.values())
            .order_by(
                effective_profit,
                group_columns["month"],
                group_columns["product"],
            )
            .limit(limit)
        ).mappings()
    )
    if not aggregate_rows:
        return []

    key_conditions = []
    for row in aggregate_rows:
        key_conditions.append(
            and_(
                *(
                    func.coalesce(column, "") == as_text(row[field])
                    for field, column in group_columns.items()
                )
            )
        )
    metadata_rows = db.execute(
        select(
            *(column.label(field) for field, column in group_columns.items()),
            ReportUnitRow.nm_id,
            ReportUnitRow.status,
            ReportUnitRow.status_reason,
            ReportUnitRow.spp_status,
        ).where(*conditions, or_(*key_conditions))
    ).mappings()
    metadata_by_key: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in metadata_rows:
        key = tuple(as_text(row[field]) for field in GROUP_FIELDS)
        metadata_by_key[key].append(row)

    liquidity_input: list[dict[str, Any]] = []
    for aggregate in aggregate_rows:
        key = tuple(as_text(aggregate[field]) for field in GROUP_FIELDS)
        metadata = metadata_by_key.get(key) or [{}]
        has_profit_before_tax = int(aggregate["profitBeforeTaxCount"] or 0) == int(
            aggregate["rowCount"] or 0
        )
        has_profit = int(aggregate["profitCount"] or 0) == int(
            aggregate["rowCount"] or 0
        )
        for index, item in enumerate(metadata):
            first = index == 0
            payload = {field: aggregate[field] for field in GROUP_FIELDS}
            payload.update(
                {field: aggregate[field] if first else 0 for field in sum_columns}
            )
            payload.update(
                {
                    "profitBeforeTax": (aggregate["profitBeforeTax"] if first else 0)
                    if has_profit_before_tax
                    else None,
                    "profit": (aggregate["profit"] if first else 0)
                    if has_profit
                    else None,
                    "nmId": item.get("nm_id") or "",
                    "status": item.get("status") or "",
                    "statusReason": item.get("status_reason") or "",
                    "sppStatus": item.get("spp_status") or "",
                }
            )
            liquidity_input.append(payload)
    return liquidity_rows_payload(aggregate_liquidity_rows(liquidity_input))


def _liquidity_rows_for_conditions(
    db: Session, *conditions: Any
) -> list[dict[str, Any]]:
    group_columns = [
        getattr(ReportUnitRow, _unit_row_column_name(field)) for field in GROUP_FIELDS
    ]
    sum_columns = {
        "sales": ReportUnitRow.sales,
        "returns": ReportUnitRow.returns,
        "netQty": ReportUnitRow.net_qty,
        "revenue": ReportUnitRow.revenue,
        "cost": ReportUnitRow.cost,
        "commission": ReportUnitRow.commission,
        "storage": ReportUnitRow.storage,
        "logistics": ReportUnitRow.logistics,
        "acceptance": ReportUnitRow.acceptance,
        "promotion": ReportUnitRow.promotion,
        "penalties": ReportUnitRow.penalties,
        "acquiring": ReportUnitRow.acquiring,
        "vat": ReportUnitRow.vat,
        "vatOutput": ReportUnitRow.vat_output,
        "vatInput": ReportUnitRow.vat_input,
        "vatInputFromWb": ReportUnitRow.vat_input_from_wb,
        "vatInputFrom1c": ReportUnitRow.vat_input_from_1c,
        "vatInputFromImportScenario": ReportUnitRow.vat_input_from_import_scenario,
        "vatInputFromWbScenario": ReportUnitRow.vat_input_from_wb_scenario,
        "vatInputDifference": ReportUnitRow.vat_input_difference,
        "vatPayable": ReportUnitRow.vat_payable,
        "usn": ReportUnitRow.usn,
        "incomeTaxBase": ReportUnitRow.income_tax_base,
        "incomeTax": ReportUnitRow.income_tax,
        "profitBeforeTax": ReportUnitRow.profit_before_tax,
        "profit": ReportUnitRow.profit,
    }
    rows = db.execute(
        select(
            *group_columns,
            ReportUnitRow.nm_id,
            ReportUnitRow.status,
            ReportUnitRow.status_reason,
            ReportUnitRow.spp_status,
            *(func.coalesce(func.sum(column), 0) for column in sum_columns.values()),
        )
        .where(*conditions)
        .group_by(
            *group_columns,
            ReportUnitRow.nm_id,
            ReportUnitRow.status,
            ReportUnitRow.status_reason,
            ReportUnitRow.spp_status,
        )
    )
    liquidity_input = []
    for row in rows:
        values = list(row)
        item = {field: values[index] for index, field in enumerate(GROUP_FIELDS)}
        offset = len(GROUP_FIELDS)
        item["nmId"] = values[offset]
        item["status"] = values[offset + 1]
        item["statusReason"] = values[offset + 2]
        item["sppStatus"] = values[offset + 3]
        for index, field in enumerate(sum_columns, start=offset + 4):
            item[field] = values[index]
        liquidity_input.append(item)
    return liquidity_rows_payload(aggregate_liquidity_rows(liquidity_input)[:100])


def _unit_row_column_name(payload_field: str) -> str:
    overrides = {
        "article1c": "article_1c",
    }
    if payload_field in overrides:
        return overrides[payload_field]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", payload_field).lower()


def _summary_lost_sales_payload(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    return _lost_sales_payload_for_conditions(
        db, ReportLostSalesRow.report_run_id == report.id
    )


def _lost_sales_payload_for_conditions(
    db: Session, *conditions: Any
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ReportLostSalesRow)
        .where(*conditions)
        .order_by(ReportLostSalesRow.lost_profit.desc(), ReportLostSalesRow.id)
        .limit(30)
    )
    return [_lost_payload(row) for row in rows]


def _filtered_lost_sales_payload_and_stats(
    db: Session,
    *conditions: Any,
    coverage: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    empty_stats = {
        "lost_sales_rows": 0,
        "lost_sales_units": Decimal("0"),
        "lost_sales_revenue": Decimal("0"),
        "lost_sales_profit": Decimal("0"),
    }
    if coverage.get("calculated") is not True:
        return [], empty_stats, True
    if coverage.get("calculationContextVersion") != "lost-sales-filter-v1":
        return [], empty_stats, False
    calculation_start = date_or_none(coverage.get("calculationPeriodStart"))
    calculation_end = date_or_none(coverage.get("calculationPeriodEnd"))
    if calculation_start is None or calculation_end is None:
        return [], empty_stats, False
    rows = list(db.scalars(select(ReportLostSalesRow).where(*conditions)))
    calculated_rows: list[tuple[dict[str, Any], dict[str, Decimal]]] = []
    for row in rows:
        calculated = _recalculate_lost_sales_row(
            row,
            period_start=calculation_start,
            period_end=calculation_end,
        )
        if calculated is None:
            return [], empty_stats, False
        payload, values = calculated
        if values["zero_stock_days"] > 0:
            calculated_rows.append((payload, values))
    calculated_rows.sort(
        key=lambda item: (item[1]["lost_profit"], item[1]["lost_revenue"]),
        reverse=True,
    )
    stats = {
        "lost_sales_rows": len(calculated_rows),
        "lost_sales_units": sum(
            (item[1]["lost_units"] for item in calculated_rows), Decimal("0")
        ),
        "lost_sales_revenue": sum(
            (item[1]["lost_revenue"] for item in calculated_rows), Decimal("0")
        ),
        "lost_sales_profit": sum(
            (item[1]["lost_profit"] for item in calculated_rows), Decimal("0")
        ),
    }
    return [item[0] for item in calculated_rows[:30]], stats, True


def _recalculate_lost_sales_row(
    row: ReportLostSalesRow,
    *,
    period_start: date,
    period_end: date,
) -> tuple[dict[str, Any], dict[str, Decimal]] | None:
    context = row.calculation_context or {}
    if context.get("version") != "lost-sales-filter-v1":
        return None
    stock_by_date = context.get("stockByDate")
    finance_periods = context.get("financePeriods")
    if not isinstance(stock_by_date, Mapping) or not isinstance(finance_periods, list):
        return None
    dates: list[date] = []
    current = period_start
    while current <= period_end:
        dates.append(current)
        current += timedelta(days=1)
    try:
        stock_values = [Decimal(str(stock_by_date[item.isoformat()])) for item in dates]
    except (KeyError, InvalidOperation, TypeError, ValueError):
        return None
    zero_stock_days = sum(1 for value in stock_values if value <= 0)
    sales_quantity = Decimal("0")
    net_revenue = Decimal("0")
    contribution_margin = Decimal("0")
    for item in finance_periods:
        if not isinstance(item, Mapping):
            return None
        source_start = date_or_none(item.get("periodStart"))
        source_end = date_or_none(item.get("periodEnd"))
        if source_start is None or source_end is None or source_start > source_end:
            return None
        overlap_start = max(source_start, period_start)
        overlap_end = min(source_end, period_end)
        if overlap_start > overlap_end:
            continue
        source_days = (source_end - source_start).days + 1
        overlap_days = (overlap_end - overlap_start).days + 1
        weight = Decimal(overlap_days) / Decimal(source_days)
        try:
            sales_quantity += Decimal(str(item.get("salesQuantity") or "0")) * weight
            net_revenue += Decimal(str(item.get("netRevenue") or "0")) * weight
            contribution_margin += (
                Decimal(str(item.get("contributionMargin") or "0")) * weight
            )
        except (InvalidOperation, TypeError, ValueError):
            return None
    period_days = len(dates)
    in_stock_days = max(0, period_days - zero_stock_days)
    avg_daily_sales = (
        sales_quantity / Decimal(in_stock_days)
        if in_stock_days > 0 and sales_quantity > 0
        else sales_quantity / Decimal(period_days)
        if period_days > 0 and sales_quantity > 0
        else Decimal("0")
    )
    lost_units = (
        avg_daily_sales * Decimal(zero_stock_days)
        if sales_quantity > 0 and zero_stock_days > 0
        else Decimal("0")
    )
    revenue_per_sale = net_revenue / sales_quantity if sales_quantity else Decimal("0")
    contribution_per_sale = (
        contribution_margin / sales_quantity if sales_quantity else Decimal("0")
    )
    lost_revenue = lost_units * revenue_per_sale
    lost_profit = max(lost_units * contribution_per_sale, Decimal("0"))
    values = {
        "zero_stock_days": Decimal(zero_stock_days),
        "sales": sales_quantity,
        "lost_units": lost_units,
        "lost_revenue": lost_revenue,
        "lost_profit": lost_profit,
    }
    return (
        {
            "id": row.row_uid,
            "clientId": row.client_id,
            "wbCabinetId": row.wb_cabinet_id,
            "cabinet": row.cabinet,
            "product": row.product,
            "article1c": row.article_1c,
            "barcode": row.barcode,
            "zeroStockDays": as_float(values["zero_stock_days"]),
            "onecStock": as_float(row.onec_stock_quantity),
            "onecWarehouses": row.onec_warehouses,
            "sales": as_float(sales_quantity),
            "lostUnits": as_float(lost_units),
            "lostRevenue": as_float(lost_revenue),
            "lostContributionMargin": as_float(lost_profit),
            "lostProfit": as_float(lost_profit),
            "note": row.note,
        },
        values,
    )


def _lost_payload(row: ReportLostSalesRow) -> dict[str, Any]:
    return {
        "id": row.row_uid,
        "clientId": row.client_id,
        "wbCabinetId": row.wb_cabinet_id,
        "cabinet": row.cabinet,
        "product": row.product,
        "article1c": row.article_1c,
        "barcode": row.barcode,
        "zeroStockDays": as_float(row.zero_stock_days),
        "onecStock": as_float(row.onec_stock_quantity),
        "onecWarehouses": row.onec_warehouses,
        "sales": as_float(row.sales),
        "lostUnits": as_float(row.lost_units),
        "lostRevenue": as_float(row.lost_revenue),
        "lostContributionMargin": as_float(row.lost_profit),
        "lostProfit": as_float(row.lost_profit),
        "note": row.note,
    }


def _reconciliation_payload(row: ReportReconciliationMonthly) -> dict[str, Any]:
    return {
        "month": row.month,
        "wb_quantity": as_float(row.wb_quantity),
        "onec_quantity": as_float(row.onec_quantity),
        "quantity_delta": as_float(row.quantity_delta),
        "wb_cogs": as_float(row.wb_cogs),
        "onec_cogs": as_float(row.onec_cogs),
        "cogs_delta": as_float(row.cogs_delta),
        "wb_mp_expenses": as_float(row.wb_mp_expenses),
        "onec_mp_expenses": as_float(row.onec_mp_expenses),
        "mp_expenses_delta": as_float(row.mp_expenses_delta),
        "status": row.status,
        "quantityStatus": (
            "loaded" if row.onec_quantity is not None else "missing_source"
        ),
        "cogsStatus": "loaded" if row.onec_cogs is not None else "missing_source",
        "marketplaceExpenseStatus": (
            "loaded" if row.onec_mp_expenses is not None else "missing_source"
        ),
        "wbBasis": row.wb_basis,
        "onecBasis": row.onec_basis,
        "sourceRunId": row.source_run_id,
        "comment": row.comment,
    }


def _date_payload(value: date | None) -> str:
    return value.isoformat() if value else ""


def _document_reconciliation_payload(
    row: ReportDocumentReconciliationRow,
) -> dict[str, Any]:
    return {
        "id": row.row_uid,
        "clientId": row.client_id,
        "clientCompanyId": row.client_company_id,
        "wbCabinetId": row.wb_cabinet_id,
        "status": row.status,
        "payoutStatus": row.payout_status,
        "periodStatus": row.period_status,
        "documentReport": row.document_report,
        "salesPeriod": row.sales_period,
        "salesPeriodStart": _date_payload(row.sales_period_start),
        "salesPeriodEnd": _date_payload(row.sales_period_end),
        "expectedDocumentDate": _date_payload(row.expected_document_date),
        "documentType": row.document_type,
        "cabinet": row.cabinet,
        "organization": row.organization,
        "summaryReportId": row.summary_report_id,
        "weeklySalesReportId": row.weekly_sales_report_id,
        "weeklyBuyoutReportId": row.weekly_buyout_report_id,
        "wbReportIds": row.wb_report_ids,
        "onecDocuments": row.onec_documents,
        "onecDocumentTypes": row.onec_document_types,
        "onecDocumentDates": row.onec_document_dates,
        "wbSalesQuantity": as_float(row.wb_sales_quantity),
        "wbReturnQuantity": as_float(row.wb_return_quantity),
        "wbNetQuantity": as_float(row.wb_net_quantity),
        "onecSalesQuantity": as_float(row.onec_sales_quantity),
        "onecReturnQuantity": as_float(row.onec_return_quantity),
        "onecNetQuantity": as_float(row.onec_net_quantity),
        "salesQuantityDelta": as_float(row.sales_quantity_delta),
        "returnQuantityDelta": as_float(row.return_quantity_delta),
        "netQuantityDelta": as_float(row.net_quantity_delta),
        "wbQuantity": as_float(row.wb_quantity),
        "onecQuantity": as_float(row.onec_quantity),
        "quantityDelta": as_float(row.quantity_delta),
        "wbAmount": as_float(row.wb_amount),
        "onecAmount": as_float(row.onec_amount),
        "amountDelta": as_float(row.amount_delta),
        "buyoutRetailAmountSum": as_float(row.buyout_retail_amount_sum),
        "buyoutForPaySum": as_float(row.buyout_for_pay_sum),
        "buyoutBankPaymentSum": as_float(row.buyout_bank_payment_sum),
        "buyoutPrimaryDocumentId": row.buyout_primary_document_id,
        "buyoutPrimaryDocumentStatus": row.buyout_primary_document_status,
        "buyoutPrimaryDocumentQuantity": as_float(row.buyout_primary_document_quantity),
        "buyoutPrimaryDocumentAmount": as_float(row.buyout_primary_document_amount),
        "buyoutPrimaryDocumentDelta": as_float(row.buyout_primary_document_delta),
        "onecExpenseInvoiceAmount": as_float(row.onec_expense_invoice_amount),
        "buyoutRetailDelta": as_float(row.buyout_retail_delta),
        "buyoutForPayDelta": as_float(row.buyout_for_pay_delta),
        "buyoutBankDelta": as_float(row.buyout_bank_delta),
        "pdfBankPayment": as_float(row.pdf_bank_payment),
        "wbForPaySum": as_float(row.wb_for_pay_sum),
        "onecSettlementTotal": as_float(row.onec_settlement_total),
        "settlementDelta": as_float(row.settlement_delta),
        "onecVat": as_float(row.onec_vat),
        "onecCogs": as_float(row.onec_cogs),
        "onecCogsWithoutVat": as_float(row.onec_cogs_without_vat),
        "onecGrossProfit": as_float(row.onec_gross_profit),
        "onecSourceRows": row.onec_source_rows,
        "comment": row.comment,
    }


def _decimal_as_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _document_reconciliation_has_delta(
    row: ReportDocumentReconciliationRow,
) -> bool:
    if _document_reconciliation_is_buyout(row):
        return abs(_decimal_as_float(row.quantity_delta)) > 0.000001
    return any(
        abs(_decimal_as_float(getattr(row, field))) > 0.000001
        for field in DOCUMENT_RECONCILIATION_DELTA_FIELDS
    )


def _document_reconciliation_is_buyout(
    row: ReportDocumentReconciliationRow,
) -> bool:
    return as_text(row.document_type).strip().casefold() == (
        "Уведомление о выкупе".casefold()
    )


def _document_reconciliation_is_commissioner(
    row: ReportDocumentReconciliationRow,
) -> bool:
    return as_text(row.document_type).strip().casefold() == (
        "Отчет комиссионера".casefold()
    )


def _document_reconciliation_missing_onec(
    row: ReportDocumentReconciliationRow,
) -> bool:
    return not as_text(row.onec_documents)


def _document_reconciliation_is_informational_adjustment(
    row: ReportDocumentReconciliationRow,
) -> bool:
    document_type = as_text(row.document_type).strip().casefold()
    status = as_text(row.status).strip().casefold()
    adjustment_types = {
        "Корректировка 1С".casefold(),
        "Корректировка себестоимости 1С".casefold(),
    }
    return bool(
        document_type in adjustment_types
        and status == document_type
        and as_text(row.period_status).strip().casefold() == "период 1с".casefold()
        and not _document_reconciliation_missing_onec(row)
        and not _document_reconciliation_has_delta(row)
    )


def _document_reconciliation_is_visible_for_report(
    row: ReportDocumentReconciliationRow,
    report: ReportRun,
) -> bool:
    unmatched_statuses = {
        "Лишний документ в 1С".casefold(),
        "Корректировка 1С".casefold(),
        "Корректировка себестоимости 1С".casefold(),
    }
    if as_text(row.status).strip().casefold() not in unmatched_statuses:
        return True
    if any(
        as_text(value)
        for value in (
            row.summary_report_id,
            row.weekly_sales_report_id,
            row.weekly_buyout_report_id,
            row.wb_report_ids,
        )
    ):
        return True
    document_date = _onec_calendar_document_date(row)
    if document_date is None:
        return True
    return report.period_start <= document_date <= report.period_end


def _document_reconciliation_has_issue(
    row: ReportDocumentReconciliationRow,
) -> bool:
    if _document_reconciliation_is_informational_adjustment(row):
        return False
    status = as_text(row.status).lower()
    period_status = as_text(row.period_status).lower()
    accepted_statuses = {"ok"}
    if _document_reconciliation_is_buyout(row):
        accepted_statuses.update({"документ найден", "сверено по количеству"})
    return any(
        (
            status not in accepted_statuses,
            period_status not in {"", "ok", "полный период"},
            _document_reconciliation_missing_onec(row),
            _document_reconciliation_has_delta(row),
        )
    )


def _document_reconciliation_kpis(
    rows: list[ReportDocumentReconciliationRow],
) -> dict[str, Any]:
    issue_rows = [row for row in rows if _document_reconciliation_has_issue(row)]
    ok_rows = [row for row in rows if not _document_reconciliation_has_issue(row)]
    missing_onec = [row for row in rows if _document_reconciliation_missing_onec(row)]
    quantity_delta = sum(_decimal_as_float(row.quantity_delta) for row in rows)
    commissioner_rows = [
        row for row in rows if not _document_reconciliation_is_buyout(row)
    ]
    buyout_rows = [row for row in rows if _document_reconciliation_is_buyout(row)]
    comparable_revenue_wb = sum(
        _decimal_as_float(row.wb_amount) for row in commissioner_rows
    )
    comparable_revenue_onec = sum(
        _decimal_as_float(row.onec_amount) for row in commissioner_rows
    )
    amount_delta = sum(_decimal_as_float(row.amount_delta) for row in commissioner_rows)
    buyout_retail_wb = sum(
        _decimal_as_float(row.buyout_retail_amount_sum or row.wb_amount)
        for row in buyout_rows
    )
    buyout_net_onec = sum(
        _decimal_as_float(row.onec_expense_invoice_amount or row.onec_amount)
        for row in buyout_rows
    )
    verified_primary_rows = [
        row
        for row in buyout_rows
        if row.buyout_primary_document_status == "verified"
        and row.buyout_primary_document_amount is not None
    ]
    buyout_unverified_primary_rows = len(buyout_rows) - len(verified_primary_rows)
    buyout_primary_document_amount = sum(
        _decimal_as_float(row.buyout_primary_document_amount)
        for row in verified_primary_rows
    )
    buyout_primary_document_delta = (
        sum(
            _decimal_as_float(row.buyout_primary_document_delta)
            for row in verified_primary_rows
        )
        if buyout_rows and not buyout_unverified_primary_rows
        else None
    )
    return {
        "documentCount": len(rows),
        "okRows": len(ok_rows),
        "issueRows": len(issue_rows),
        "quantityDelta": quantity_delta,
        "amountDelta": amount_delta,
        "comparableRevenueWb": comparable_revenue_wb,
        "comparableRevenueOnec": comparable_revenue_onec,
        "comparableRevenueDelta": amount_delta,
        "buyoutRetailWb": buyout_retail_wb,
        "buyoutNetOnec": buyout_net_onec,
        "buyoutAmountsComparable": False,
        "buyoutPrimaryDocumentAmount": (
            buyout_primary_document_amount if verified_primary_rows else None
        ),
        "buyoutPrimaryDocumentDelta": buyout_primary_document_delta,
        "buyoutPrimaryDocumentStatus": (
            "verified"
            if buyout_rows and not buyout_unverified_primary_rows
            else "partial"
            if verified_primary_rows
            else "not_loaded"
            if buyout_rows
            else "not_applicable"
        ),
        "buyoutUnverifiedPrimaryRows": buyout_unverified_primary_rows,
        "missingOnecRows": len(missing_onec),
    }


def _wb_payout_kpis(
    rows: Iterable[ReportDocumentReconciliationRow],
) -> dict[str, Any]:
    """Aggregate WB ``forPaySum`` without presenting it as a bank payment."""

    values = [
        Decimal(row.wb_for_pay_sum) for row in rows if row.wb_for_pay_sum is not None
    ]
    return {
        "wbForPaySum": as_float(sum(values, Decimal("0"))) if values else None,
        "wbForPayRowCount": len(values),
    }


def _document_reconciliation_conditions_for_report(
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    cabinet: str = "",
    organization: str = "",
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    document_report: str = "",
) -> list[Any]:
    conditions: list[Any] = [ReportDocumentReconciliationRow.report_run_id == report.id]
    closing_date = func.coalesce(
        ReportDocumentReconciliationRow.sales_period_end,
        ReportDocumentReconciliationRow.expected_document_date,
    )
    if period_start is not None:
        conditions.append(closing_date >= period_start)
    if period_end is not None:
        conditions.append(closing_date <= period_end)
    if cabinet:
        conditions.append(ReportDocumentReconciliationRow.cabinet == cabinet)
    if organization:
        conditions.append(ReportDocumentReconciliationRow.organization == organization)
    if wb_cabinet_id:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.wb_cabinet_id == wb_cabinet_id,
                ReportDocumentReconciliationRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.client_company_id == client_company_id,
                ReportDocumentReconciliationRow.organization == client_company_id,
            )
        )
    if document_report:
        conditions.append(
            ReportDocumentReconciliationRow.document_report == document_report
        )
    return conditions


def _document_reconciliation_rows_for_conditions(
    db: Session, *conditions: Any
) -> list[ReportDocumentReconciliationRow]:
    return list(
        db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(*conditions)
            .order_by(ReportDocumentReconciliationRow.id)
        )
    )


def _unit_rows_for_report(db: Session, report: ReportRun) -> list[ReportUnitRow]:
    return list(
        db.scalars(
            select(ReportUnitRow)
            .where(ReportUnitRow.report_run_id == report.id)
            .order_by(ReportUnitRow.id)
        )
    )


def _document_reconciliation_rows_for_report(
    db: Session, report: ReportRun
) -> list[ReportDocumentReconciliationRow]:
    rows = list(
        db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(ReportDocumentReconciliationRow.report_run_id == report.id)
            .order_by(ReportDocumentReconciliationRow.id)
        )
    )
    return [
        row
        for row in rows
        if _document_reconciliation_is_visible_for_report(row, report)
    ]


def _source_loads_for_report(db: Session, report: ReportRun) -> list[SourceLoad]:
    return list(
        db.scalars(
            select(SourceLoad)
            .where(SourceLoad.report_run_id == report.id)
            .order_by(SourceLoad.loaded_at.desc())
        )
    )


def _report_company_cabinet_mismatch_count(
    db: Session,
    report: ReportRun,
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ReportUnitRow)
            .join(
                WbCabinet,
                WbCabinet.id == ReportUnitRow.wb_cabinet_id,
                isouter=True,
            )
            .where(
                ReportUnitRow.report_run_id == report.id,
                ReportUnitRow.client_company_id != "",
                ReportUnitRow.wb_cabinet_id != "",
                or_(
                    WbCabinet.id.is_(None),
                    WbCabinet.client_company_id.is_(None),
                    WbCabinet.client_company_id != ReportUnitRow.client_company_id,
                ),
            )
        )
        or 0
    )


def _source_coverage_for_report(
    db: Session,
    report: ReportRun,
) -> tuple[date, date] | None:
    if (
        report.source_coverage_start is not None
        and report.source_coverage_end is not None
    ):
        return report.source_coverage_start, report.source_coverage_end
    refresh_run = db.scalar(
        select(SourceRefreshRun)
        .where(SourceRefreshRun.new_report_run_id == report.id)
        .order_by(SourceRefreshRun.created_at.desc())
    )
    if refresh_run is None:
        return None
    return refresh_run.period_start, refresh_run.period_end


def _source_coverage_label(coverage: tuple[date, date] | None) -> str:
    if coverage is None:
        return ""
    start, end = coverage
    return f"{start:%d.%m.%Y} - {end:%d.%m.%Y}"


def _source_coverage_gap(
    report: ReportRun,
    coverage: tuple[date, date] | None,
) -> bool:
    if coverage is None:
        return False
    start, end = coverage
    return start > report.period_start or end < report.period_end


def _readiness_payload(
    status: str,
    score: int,
    *,
    blocking_reasons: list[dict[str, Any]],
    review_reasons: list[dict[str, Any]],
    next_action: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "score": int(score),
        "label": READINESS_LABELS[status],
        "blockingReasons": blocking_reasons,
        "reviewReasons": review_reasons,
        "nextAction": next_action,
        "checkedBy": "system",
    }


def _readiness_reason(
    code: str,
    message: str,
    count: int | None = None,
    **details: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if count is not None:
        payload["count"] = int(count)
    payload.update(details)
    return payload


def _dedupe_readiness_reasons(
    reasons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}
    for reason in reasons:
        code = as_text(reason.get("code"))
        if not code or code not in by_code:
            item = dict(reason)
            result.append(item)
            if code:
                by_code[code] = item
            continue
        existing = by_code[code]
        existing["count"] = max(
            int(existing.get("count") or 0),
            int(reason.get("count") or 0),
        )
        existing["affectedRevenue"] = max(
            float(existing.get("affectedRevenue") or 0),
            float(reason.get("affectedRevenue") or 0),
        )
    return result


def _decorate_readiness_tasks(
    report: ReportRun,
    source_loads: list[SourceLoad],
    *reason_groups: list[dict[str, Any]],
) -> None:
    refresh_run_id = next(
        (
            load.source_refresh_run_id
            for load in reversed(source_loads)
            if load.source_refresh_run_id
        ),
        None,
    )
    for reasons in reason_groups:
        for reason in reasons:
            fingerprint_source = "|".join(
                (
                    report.client_id,
                    report.id,
                    as_text(reason.get("code")),
                    refresh_run_id or "",
                )
            )
            reason["fingerprint"] = hashlib.sha256(
                fingerprint_source.encode("utf-8")
            ).hexdigest()
            reason["clientId"] = report.client_id
            reason["reportId"] = report.id
            reason["refreshRunId"] = refresh_run_id


def _has_readiness_reason(
    reasons: list[dict[str, Any]],
    *codes: str,
) -> bool:
    wanted = set(codes)
    return any(as_text(reason.get("code")) in wanted for reason in reasons)


def _readiness_next_action(
    status: str,
    blocking_reasons: list[dict[str, Any]],
    review_reasons: list[dict[str, Any]],
) -> str:
    if status == "ready":
        return "Можно отправлять клиенту."
    first_code = ""
    if blocking_reasons:
        first_code = as_text(blocking_reasons[0].get("code"))
    elif review_reasons:
        first_code = as_text(review_reasons[0].get("code"))
    actions = {
        "no_rows": "Пересобрать или импортировать report run.",
        "report_status_blocked": "Проверить ошибку report run и пересобрать отчет.",
        "source_load_failed": "Проверить загрузку источников и пересобрать report run.",
        "source_load_review_required": (
            "Проверить обязательный источник и подтвердить результат."
        ),
        "source_loads_missing": "Проверить историю загрузок перед отправкой.",
        "source_load_incomplete": "Проверить неполные загрузки источников.",
        "source_coverage_gap": (
            "Дозагрузить источники или явно отметить неполное покрытие в отчете."
        ),
        "partial_period": (
            "Указать клиенту, что период предварительный, или дождаться "
            "полного периода."
        ),
        "missing_cost": (
            "Проверить себестоимость 1С и при необходимости пересобрать отчет."
        ),
        "mapping_review": "Проверить сопоставление WB-1С и пересобрать отчет.",
        "onec_reconciliation_review": (
            "Сверить документы WB ↔ 1С и пересобрать отчет при исправлениях."
        ),
        "partial_source": (
            "Дозагрузить недостающие источники или явно описать ограничение."
        ),
        "data_quality_review": "Проверить строки со статусом, отличным от ОК.",
        "too_many_data_quality_issues": (
            "Исправить качество данных перед отправкой клиенту."
        ),
        "tax_profile_unconfirmed": (
            "Обновить настройки налогообложения организаций из 1С и пересобрать отчёт."
        ),
        "company_cabinet_mismatch": (
            "Исправить каноническую привязку организации и пересобрать отчёт."
        ),
        "tax_rate_basis_unconfirmed": (
            "Добавить документ-основание и период региональной ставки УСН."
        ),
        "wb_report_type_unconfirmed": (
            "Связать строки с официальным ID и типом отчёта WB."
        ),
        "pnl_method_mismatch": (
            "Пересчитать прибыли и убытки по единой методике ОСНО без НДС."
        ),
        "profit_semantics_mismatch": (
            "Устранить расхождение profit и profitBeforeTax до НДФЛ."
        ),
        "vat_input_unconfirmed": "Подтвердить входящий НДС документами 1С.",
        "vat_input_management_assumption": (
            "Сверить управленческий входящий НДС с книгой покупок 1С."
        ),
        "cogs_reconciliation_failed": (
            "Сверить себестоимость 1С; Excel можно формировать и публиковать "
            "с явным предупреждением."
        ),
        "source_lineage_failed": "Повторить обязательные загрузки источников.",
        "logistics_analysis_blocked": (
            "Повторить test-снимок WB и пройти сверку логистики."
        ),
        "logistics_analysis_partial": (
            "Проверить нераспределённые операции логистики."
        ),
        "required_wb_expense_source_missing": (
            "Загрузить контроль хранения и приемки WB."
        ),
        "monthly_reconciliation_unresolved": (
            "Закрыть независимую месячную сверку WB-1С."
        ),
        "document_reconciliation_unresolved": (
            "Расшифровать документные расхождения WB-1С."
        ),
        "client_draft_missing": "Подготовить клиентский AI-черновик.",
        "client_draft_not_ready": (
            "Проверить и пометить клиентский AI-черновик готовым."
        ),
        "client_draft_forbidden_text": (
            "Пересобрать клиентский черновик без внутренних labels."
        ),
    }
    return actions.get(first_code, "Проверить причины перед отправкой клиенту.")


def _source_load_ok(load: SourceLoad) -> bool:
    return load.status.strip().lower() in SOURCE_LOAD_OK_STATUSES


def _source_load_failed(load: SourceLoad) -> bool:
    status = load.status.strip().lower()
    return any(marker in status for marker in SOURCE_LOAD_FAILED_MARKERS)


def _tax_rate_basis_issue_count(db: Session, report: ReportRun) -> int:
    """Keep the legacy check hook without blocking a saved tax setting.

    The confirmed profile gate already validates the tax method, rate and
    effective period.  Legal-basis metadata is optional audit context.
    """

    return 0


def _financial_integrity_blockers(
    db: Session,
    report: ReportRun,
    *,
    source_loads: list[SourceLoad],
    stats: Mapping[str, Any],
    tax_context: Mapping[str, Any],
    document_reconciliation_issue_count: int,
) -> list[dict[str, Any]]:
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in source_loads
    )
    explicit_tax_issues = int(stats["tax_profile_issue_rows"])
    profile_rows = [
        profile
        for profile in tax_context.get("profiles") or []
        if isinstance(profile, Mapping)
    ]
    company_tax_issues = sum(
        1 for profile in profile_rows if profile.get("status") != "ready"
    )
    if not source_refresh_backed and explicit_tax_issues == 0:
        company_tax_issues = 0
    elif source_refresh_backed and not profile_rows:
        company_tax_issues = max(company_tax_issues, 1)
    tax_profile_issue_count = max(explicit_tax_issues, company_tax_issues)
    osno_rows = int(stats["osno_rows"])

    blockers: list[dict[str, Any]] = []
    if tax_profile_issue_count:
        blockers.append(
            _readiness_reason(
                "tax_profile_unconfirmed",
                (
                    "Настройки налогообложения из 1С не загружены или не "
                    "применены для всех организаций и дат отчёта."
                ),
                tax_profile_issue_count,
            )
        )

    if osno_rows:
        method_mismatch = int(stats["pnl_method_mismatch_rows"])
        if method_mismatch:
            blockers.append(
                _readiness_reason(
                    "pnl_method_mismatch",
                    "Смешаны несовместимые методы прибыли и НДС.",
                    method_mismatch,
                )
            )

        profit_mismatch = int(stats["profit_semantics_mismatch_rows"])
        if profit_mismatch:
            blockers.append(
                _readiness_reason(
                    "profit_semantics_mismatch",
                    (
                        "Прибыль до налогов расходится между полями "
                        "profit и profitBeforeTax."
                    ),
                    profit_mismatch,
                )
            )

        vat_unconfirmed = int(stats["vat_input_unconfirmed_rows"])
        if vat_unconfirmed:
            blockers.append(
                _readiness_reason(
                    "vat_input_unconfirmed",
                    "Входящий НДС не подтвержден независимым источником 1С.",
                    vat_unconfirmed,
                )
            )

    report_type_fallback_count = int(stats["report_type_fallback_rows"])
    if report_type_fallback_count:
        blockers.append(
            _readiness_reason(
                "wb_report_type_unconfirmed",
                "Для выручки не подтверждён официальный тип отчёта WB.",
                report_type_fallback_count,
                affected_revenue=float(stats["report_type_fallback_revenue"]),
            )
        )

    required_bad_loads = [
        load
        for load in source_loads
        if (load.required or load.publication_required)
        and not (
            load.source_type == "sku_mapping"
            and load.status.strip().lower() == "needs_review"
        )
        and (
            not _source_load_ok(load)
            or _source_load_failed(load)
            or not _source_load_covers_report(db, load, report)
        )
    ]
    if required_bad_loads:
        blockers.append(
            _readiness_reason(
                "source_lineage_failed",
                "Обязательный источник не завершён или требует проверки.",
                len(required_bad_loads),
            )
        )

    sales = float(stats["sales"])
    storage_and_acceptance = float(stats["storage_and_acceptance"])
    expense_control_loaded = any(
        load.source_type in {"wb_sales_report_list", "wb_paid_storage"}
        and _source_load_ok(load)
        and (
            load.row_count > 0
            or (
                load.source_type == "wb_paid_storage"
                and load.status.strip().lower() == "empty_expected"
            )
        )
        and _source_load_covers_report(db, load, report)
        for load in source_loads
    )
    if (
        source_refresh_backed
        and sales > 0
        and storage_and_acceptance == 0
        and not expense_control_loaded
    ):
        blockers.append(
            _readiness_reason(
                "required_wb_expense_source_missing",
                "Нулевые хранение и приемка не подтверждены контрольным источником WB.",
            )
        )

    if source_refresh_backed and document_reconciliation_issue_count:
        blockers.append(
            _readiness_reason(
                "document_reconciliation_unresolved",
                "Есть недокументированные расхождения по документам WB-1С.",
                document_reconciliation_issue_count,
            )
        )
    return blockers


def _source_load_covers_report(
    db: Session,
    load: SourceLoad,
    report: ReportRun,
) -> bool:
    if not load.source_refresh_run_id:
        return False
    refresh_run = db.get(SourceRefreshRun, load.source_refresh_run_id)
    if refresh_run is None:
        return False
    coverage_start = refresh_run.period_start
    coverage_end = refresh_run.period_end
    required_start = report.period_start
    required_end = report.period_end
    if load.source_type == "wb_finance_detail":
        required_start -= timedelta(days=required_start.weekday())
        required_end -= timedelta(days=(required_end.weekday() + 1) % 7)
        scalar = getattr(db, "scalar", None)
        if callable(scalar):
            collection = scalar(
                select(SourceRefreshCollection)
                .where(
                    SourceRefreshCollection.refresh_run_id == refresh_run.id,
                    SourceRefreshCollection.source_type == "wb_finance_detail",
                )
                .order_by(SourceRefreshCollection.id.desc())
            )
            payload = collection.payload if collection is not None else {}
            try:
                coverage_start = date.fromisoformat(
                    str((payload or {}).get("sourceCoverageStart") or "")
                )
                coverage_end = date.fromisoformat(
                    str((payload or {}).get("sourceCoverageEnd") or "")
                )
            except ValueError:
                pass
    return coverage_start <= required_start and coverage_end >= required_end


def report_publication_blockers(
    db: Session,
    report: ReportRun,
) -> list[dict[str, Any]]:
    readiness = report_readiness_payload(db, report)
    return list(readiness.get("blockingReasons") or [])


def _is_partial_period(report: ReportRun) -> bool:
    text = f"{report.period_status} {report.period_text}".lower()
    return "непол" in text or "предвар" in text


def _row_is_ok(row: ReportUnitRow) -> bool:
    return row.status.strip().lower() in {"ок", "reliable"}


def _row_quality_text(row: ReportUnitRow) -> str:
    return " ".join(
        [
            row.status,
            row.status_reason,
            row.loss_class,
            row.loss_driver,
        ]
    ).lower()


def _rows_matching(
    rows: list[ReportUnitRow],
    markers: tuple[str, ...],
) -> list[ReportUnitRow]:
    return [
        row
        for row in rows
        if not _row_is_ok(row)
        and any(marker in _row_quality_text(row) for marker in markers)
    ]


def _too_many_problem_rows(rows: list[ReportUnitRow], row_count: int) -> bool:
    return _too_many_problem_rows_count(len(rows), row_count)


def _too_many_problem_rows_count(problem_count: int, row_count: int) -> bool:
    if row_count <= 0 or problem_count < READINESS_REVIEW_MIN_ROWS:
        return False
    return problem_count / row_count > READINESS_REVIEW_RATIO


def _filtered_report_analytics_payload(
    db: Session,
    report: ReportRun,
    *,
    unit_conditions: list[Any],
    lost_sales_payload: list[dict[str, Any]],
    lost_sales_coverage: Mapping[str, Any],
    document_reconciliation_conditions: list[Any],
    onec_calendar_revenue: Mapping[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    document_reconciliation_rows = _document_reconciliation_rows_for_conditions(
        db, *document_reconciliation_conditions
    )
    document_reconciliation_rows = [
        row
        for row in document_reconciliation_rows
        if _document_reconciliation_is_visible_for_report(row, report)
    ]
    filtered_rows = list(db.scalars(select(ReportUnitRow).where(*unit_conditions)))
    tax_context = _tax_context_payload(db, report, filtered_rows)
    return {
        "kpis": {
            **_summary_kpis_payload(
                stats,
                tax_context=tax_context,
                lost_sales_coverage=lost_sales_coverage,
                onec_calendar_revenue=onec_calendar_revenue,
            ),
            **_wb_payout_kpis(document_reconciliation_rows),
        },
        "quality": _summary_quality_payload(
            stats,
            _source_loads_for_report(db, report),
            report,
            document_reconciliation_rows=document_reconciliation_rows,
        ),
        "monthly": _monthly_payload_for_conditions(db, *unit_conditions, report=report),
        "expenses": _expense_payload_for_conditions(db, *unit_conditions),
        "liquidityRows": _liquidity_rows_for_conditions(db, *unit_conditions),
        "lostSales": lost_sales_payload,
        "lostSalesCoverage": dict(lost_sales_coverage),
        "taxContext": tax_context,
        "taxInputReconciliation": _tax_input_reconciliation_payload_from_unit_rows(
            filtered_rows,
            tax_context=tax_context,
        ),
    }


def _report_row_sort_expressions() -> dict[str, Any]:
    def sortable_text(column: Any) -> Any:
        return func.nullif(func.lower(func.trim(column)), "")

    pnl_revenue = _pnl_revenue_expression()
    direct_expenses = (
        ReportUnitRow.commission
        + ReportUnitRow.logistics
        + ReportUnitRow.storage
        + ReportUnitRow.acceptance
        + ReportUnitRow.promotion
        + ReportUnitRow.penalties
        + ReportUnitRow.acquiring
    )
    return {
        "product": sortable_text(ReportUnitRow.product),
        "articleWb": sortable_text(ReportUnitRow.article_wb),
        "article1c": sortable_text(ReportUnitRow.article_1c),
        "barcode": sortable_text(ReportUnitRow.barcode),
        "nmId": sortable_text(ReportUnitRow.nm_id),
        "cabinet": sortable_text(ReportUnitRow.cabinet),
        "organization": sortable_text(ReportUnitRow.organization),
        "scheme": sortable_text(ReportUnitRow.scheme),
        "status": sortable_text(ReportUnitRow.status),
        "month": func.coalesce(
            ReportUnitRow.accounting_period_date,
            ReportUnitRow.week,
        ),
        "sales": ReportUnitRow.sales,
        "returns": ReportUnitRow.returns,
        "netQty": ReportUnitRow.net_qty,
        "revenueBeforeSpp": ReportUnitRow.revenue_before_spp,
        "spp": ReportUnitRow.spp,
        "revenue": ReportUnitRow.revenue,
        "pnlRevenue": pnl_revenue,
        "cost": ReportUnitRow.cost,
        "commission": ReportUnitRow.commission,
        "logistics": ReportUnitRow.logistics,
        "storage": ReportUnitRow.storage,
        "acceptance": ReportUnitRow.acceptance,
        "promotion": ReportUnitRow.promotion,
        "penalties": ReportUnitRow.penalties,
        "acquiring": ReportUnitRow.acquiring,
        "pnlVatAdjustment": (
            ReportUnitRow.profit_before_tax
            - (pnl_revenue - ReportUnitRow.cost - direct_expenses)
        ),
        "profitBeforeTax": ReportUnitRow.profit_before_tax,
        "vatOutput": ReportUnitRow.vat_output,
        "vatInput": ReportUnitRow.vat_input,
        "vatPayable": ReportUnitRow.vat_payable,
        "incomeTaxBase": ReportUnitRow.income_tax_base,
        "incomeTax": ReportUnitRow.income_tax,
        "includedTaxes": ReportUnitRow.profit_before_tax - ReportUnitRow.profit,
        "profit": ReportUnitRow.profit,
        "margin": ReportUnitRow.margin,
        "unitProfit": ReportUnitRow.unit_profit,
        "accountingPeriodDate": ReportUnitRow.accounting_period_date,
        "documentReport": sortable_text(ReportUnitRow.document_report),
        "wbReportId": sortable_text(ReportUnitRow.wb_report_id),
        "wbReportDate": sortable_text(ReportUnitRow.wb_report_date),
    }


def query_report_rows(
    db: Session,
    report: ReportRun,
    *,
    query: str = "",
    status: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
    month: str = "",
    cabinet: str = "",
    organization: str = "",
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    scheme: str = "",
    loss_class: str = "",
    document_report: str = "",
    preset: str = "",
    sort_by: str = "",
    sort_direction: str = "",
    limit: int = 250,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, REPORT_ROWS_MAX_LIMIT))
    offset = max(0, offset)
    conditions: list[Any] = [ReportUnitRow.report_run_id == report.id]
    if status:
        conditions.append(ReportUnitRow.status == status)
    period_condition = _row_period_condition(report, period_start, period_end)
    if period_condition is not None:
        conditions.append(period_condition)
    if month:
        month_period = _month_filter_period(month)
        month_condition = (
            _row_period_condition(report, *month_period) if month_period else None
        )
        conditions.append(
            month_condition
            if month_condition is not None
            else ReportUnitRow.month == month
        )
    if cabinet:
        conditions.append(ReportUnitRow.cabinet == cabinet)
    if organization:
        conditions.append(ReportUnitRow.organization == organization)
    if wb_cabinet_id:
        conditions.append(
            or_(
                ReportUnitRow.wb_cabinet_id == wb_cabinet_id,
                ReportUnitRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        conditions.append(
            or_(
                ReportUnitRow.client_company_id == client_company_id,
                ReportUnitRow.organization == client_company_id,
            )
        )
    if scheme:
        conditions.append(ReportUnitRow.scheme == scheme)
    if loss_class:
        conditions.append(ReportUnitRow.loss_class == loss_class)
    if document_report:
        conditions.append(ReportUnitRow.document_report == document_report)
    if preset == "losses":
        conditions.extend((ReportUnitRow.profit < 0, ~_penalty_only_condition()))
    if preset == "penaltyOnly":
        conditions.append(_penalty_only_condition())
    if preset == "missingCost":
        conditions.extend((ReportUnitRow.status != "ОК", _missing_cost_condition()))
    if preset == "missingMapping":
        conditions.append(ReportUnitRow.status.ilike("%сопостав%"))
    if preset == "review":
        conditions.append(ReportUnitRow.status != "ОК")
    if preset == "returns":
        conditions.append(
            or_(
                ReportUnitRow.returns > 0,
                ReportUnitRow.return_rate > 0,
            )
        )
    if query:
        like = f"%{query}%"
        conditions.append(
            or_(
                ReportUnitRow.product.ilike(like),
                ReportUnitRow.nm_id.ilike(like),
                ReportUnitRow.article_wb.ilike(like),
                ReportUnitRow.article_1c.ilike(like),
                ReportUnitRow.barcode.ilike(like),
                ReportUnitRow.document_report.ilike(like),
            )
        )
    statement = select(ReportUnitRow).where(*conditions)
    total = _count_rows(db, *conditions)
    if sort_by:
        sort_expressions = _report_row_sort_expressions()
        if sort_by not in sort_expressions:
            raise ValueError(f"unsupported report row sort key: {sort_by}")
        sort_expression = sort_expressions[sort_by]
        direction = (
            sort_expression.desc()
            if sort_direction.casefold() == "desc"
            else sort_expression.asc()
        )
        ordering = (
            case((sort_expression.is_(None), 1), else_=0),
            direction,
            ReportUnitRow.id.asc(),
        )
    else:
        order_column = (
            func.abs(ReportUnitRow.revenue).desc()
            if preset == "missingCost"
            else ReportUnitRow.profit.asc()
        )
        ordering = (order_column, ReportUnitRow.id.asc())
    rows = list(db.scalars(statement.order_by(*ordering).offset(offset).limit(limit)))
    stats = _row_stats_for_conditions(db, *conditions)
    requested_lost_sales_start = period_start
    requested_lost_sales_end = period_end
    if month:
        month_period = _month_filter_period(month)
        if month_period:
            month_start, month_end = month_period
            requested_lost_sales_start = max(
                requested_lost_sales_start or report.period_start,
                month_start,
            )
            requested_lost_sales_end = min(
                requested_lost_sales_end or report.period_end,
                month_end,
            )
    lost_sales_conditions = _lost_sales_conditions_for_report(
        report,
        query=query,
        cabinet=cabinet,
        wb_cabinet_id=wb_cabinet_id,
    )
    lost_sales_coverage = _lost_sales_coverage_payload(
        db,
        report,
        requested_period_start=requested_lost_sales_start,
        requested_period_end=requested_lost_sales_end,
        cabinet=cabinet,
        wb_cabinet_id=wb_cabinet_id,
    )
    lost_sales_payload, lost_sales_stats, context_supported = (
        _filtered_lost_sales_payload_and_stats(
            db,
            *lost_sales_conditions,
            coverage=lost_sales_coverage,
        )
    )
    if lost_sales_coverage.get("calculated") is True and not context_supported:
        lost_sales_coverage = {
            **lost_sales_coverage,
            "status": "incomplete",
            "calculated": False,
            "fullCoverage": False,
            "calculationPeriodStart": None,
            "calculationPeriodEnd": None,
            "message": (
                "Не рассчитано: текущий отчёт не содержит контекст для "
                "пересчёта истории остатков по выбранным датам."
            ),
        }
        lost_sales_payload = []
        lost_sales_stats = {
            "lost_sales_rows": 0,
            "lost_sales_units": Decimal("0"),
            "lost_sales_revenue": Decimal("0"),
            "lost_sales_profit": Decimal("0"),
        }
    stats.update(lost_sales_stats)
    document_reconciliation_conditions = _document_reconciliation_conditions_for_report(
        report,
        period_start=period_start,
        period_end=period_end,
        cabinet=cabinet,
        organization=organization,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        document_report=document_report,
    )
    calendar_period_start, calendar_period_end = _calendar_period_for_row_filters(
        report,
        period_start=period_start,
        period_end=period_end,
        month=month,
    )
    calendar_document_conditions = _document_reconciliation_conditions_for_report(
        report,
        cabinet=cabinet,
        organization=organization,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        document_report=document_report,
    )
    onec_calendar_revenue = _onec_calendar_revenue_kpis(
        _document_reconciliation_rows_for_conditions(db, *calendar_document_conditions),
        period_start=calendar_period_start,
        period_end=calendar_period_end,
    )
    analytics = _filtered_report_analytics_payload(
        db,
        report,
        unit_conditions=conditions,
        lost_sales_payload=lost_sales_payload,
        lost_sales_coverage=lost_sales_coverage,
        document_reconciliation_conditions=document_reconciliation_conditions,
        onec_calendar_revenue=onec_calendar_revenue,
        stats=stats,
    )
    marketplace_expense = query_marketplace_expense_reconciliation(
        db,
        report,
        period_start=period_start,
        period_end=period_end,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
        limit=1,
    )
    analytics["kpis"].update(marketplace_expense["kpis"])
    analytics["marketplaceExpenseReconciliation"] = {
        "source": marketplace_expense["source"],
        "groups": marketplace_expense["groups"],
    }
    payload = {
        "items": [_row_payload(row) for row in rows],
        "total": total,
        "kpis": dict(analytics["kpis"]),
        "analytics": analytics,
    }
    if preset == "missingCost":
        payload["costIssueBreakdown"] = {
            "totalRows": int(stats["missing_cost_rows"]),
            "requiresReviewRows": int(stats["cost_requires_review_rows"]),
            "absentRows": int(stats["cost_absent_rows"]),
            "affectedRevenue": float(stats["missing_cost_affected_revenue"]),
            "byReason": _missing_cost_reason_breakdown(db, *conditions),
        }
    return payload


def _missing_cost_reason_breakdown(
    db: Session, *conditions: Any
) -> list[dict[str, Any]]:
    """Split the "требует сверки" bucket by the actual root cause.

    `status_reason` already encodes the distinct root cause (nearest-week
    substitution, provisional cost, cost without VAT, etc. — see
    `_status_reason()` in excel.py), so grouping by it lets the UI show
    which causes dominate instead of one opaque count.
    """
    reason_expr = func.coalesce(
        func.nullif(func.trim(func.coalesce(ReportUnitRow.status_reason, "")), ""),
        ReportUnitRow.status,
    )
    statement = (
        select(
            reason_expr.label("reason"),
            func.count().label("row_count"),
            func.coalesce(func.sum(ReportUnitRow.revenue), 0).label("affected_revenue"),
        )
        .where(*conditions)
        .group_by(reason_expr)
        .order_by(func.count().desc(), reason_expr.asc())
    )
    rows = db.execute(statement).mappings().all()
    return [
        {
            "reason": as_text(row["reason"]),
            "rows": int(row["row_count"] or 0),
            "affectedRevenue": float(row["affected_revenue"] or 0),
        }
        for row in rows
        if as_text(row["reason"])
    ]


def _marketplace_expense_context_supported(report: ReportRun) -> bool:
    return (
        report.marketplace_expense_context_version
        == MARKETPLACE_EXPENSE_CONTEXT_VERSION
    )


def _legacy_marketplace_expense_reconciliation(
    stats: Mapping[str, Any],
    report: ReportRun,
) -> dict[str, Any]:
    """Expose WB P&L expenses without guessing absent immutable 1C context."""

    wb_pnl_expenses = (
        Decimal(str(stats.get("revenue") or 0))
        - Decimal(str(stats.get("cost") or 0))
        - Decimal(str(stats.get("profit_before_tax") or 0))
    )
    status = "legacy_rebuild_required"
    return {
        "period": {
            "start": report.period_start.isoformat(),
            "end": report.period_end.isoformat(),
            "wbBasis": "accounting_period_date; P&L basis",
            "onecBasis": None,
        },
        "kpis": {
            "wbMarketplacePnlExpenses": as_float(wb_pnl_expenses),
            "wbMarketplaceDocumentExpensesWithVat": None,
            "onecMarketplaceExpensesWithoutVat": None,
            "onecMarketplaceVat": None,
            "onecMarketplaceExpensesWithVat": None,
            "marketplaceExpenseDeltaWithVat": None,
            "marketplaceExpenseReconciliationStatus": status,
            "marketplaceExpenseIssueGroups": 0,
            "marketplaceExpenseMappingIssueRows": 0,
            "marketplaceExpenseSourceKind": "",
        },
        "groups": [],
        "items": [],
        "total": 0,
        "source": {
            "status": status,
            "kind": "",
            "rowCount": 0,
            "message": _marketplace_expense_status_message(status),
            "contextVersion": report.marketplace_expense_context_version,
        },
    }


def query_marketplace_expense_reconciliation(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    control_group: str = "",
    status: str = "",
    delta_only: bool = False,
    limit: int = 250,
    offset: int = 0,
) -> dict[str, Any]:
    """Reconcile WB marketplace expenses with immutable normalized 1C services."""

    limit = max(1, min(limit, REPORT_ROWS_MAX_LIMIT))
    offset = max(0, offset)
    selected_start = period_start or report.period_start
    selected_end = period_end or report.period_end
    if selected_start > selected_end:
        selected_start, selected_end = selected_end, selected_start

    unit_conditions: list[Any] = [ReportUnitRow.report_run_id == report.id]
    unit_period = _row_period_condition(report, selected_start, selected_end)
    if unit_period is not None:
        unit_conditions.append(unit_period)
    if wb_cabinet_id:
        unit_conditions.append(ReportUnitRow.wb_cabinet_id == wb_cabinet_id)
    if client_company_id:
        unit_conditions.append(ReportUnitRow.client_company_id == client_company_id)
    pnl_revenue_expression = case(
        (
            ReportUnitRow.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
            ReportUnitRow.revenue_without_vat,
        ),
        else_=ReportUnitRow.revenue,
    )
    direct_expense_expression = (
        ReportUnitRow.commission
        + ReportUnitRow.logistics
        + ReportUnitRow.storage
        + ReportUnitRow.acceptance
        + ReportUnitRow.promotion
        + ReportUnitRow.penalties
        + ReportUnitRow.acquiring
    )
    pnl_expense_expression = case(
        (
            ReportUnitRow.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
            pnl_revenue_expression
            - ReportUnitRow.cost
            - ReportUnitRow.profit_before_tax,
        ),
        else_=direct_expense_expression,
    )
    unit_rows = list(
        db.execute(
            select(
                ReportUnitRow.week,
                ReportUnitRow.accounting_period_date,
                ReportUnitRow.client_company_id,
                ReportUnitRow.wb_cabinet_id,
                ReportUnitRow.cabinet,
                ReportUnitRow.organization,
                func.coalesce(func.sum(ReportUnitRow.promotion), 0).label("promotion"),
                func.coalesce(func.sum(ReportUnitRow.penalties), 0).label("penalties"),
                func.coalesce(
                    func.sum(
                        ReportUnitRow.commission
                        + ReportUnitRow.logistics
                        + ReportUnitRow.storage
                        + ReportUnitRow.acceptance
                        + ReportUnitRow.acquiring
                    ),
                    0,
                ).label("core_services"),
                func.coalesce(
                    func.sum(pnl_expense_expression),
                    0,
                ).label("pnl_expenses"),
            )
            .where(*unit_conditions)
            .group_by(
                ReportUnitRow.week,
                ReportUnitRow.accounting_period_date,
                ReportUnitRow.client_company_id,
                ReportUnitRow.wb_cabinet_id,
                ReportUnitRow.cabinet,
                ReportUnitRow.organization,
            )
        ).mappings()
    )

    service_conditions: list[Any] = [
        ReportMarketplaceExpenseRow.report_run_id == report.id,
        ReportMarketplaceExpenseRow.recognition_date >= selected_start,
        ReportMarketplaceExpenseRow.recognition_date <= selected_end,
    ]
    if wb_cabinet_id:
        service_conditions.append(
            ReportMarketplaceExpenseRow.wb_cabinet_id == wb_cabinet_id
        )
    if client_company_id:
        service_conditions.append(
            ReportMarketplaceExpenseRow.client_company_id == client_company_id
        )
    if control_group:
        service_conditions.append(
            ReportMarketplaceExpenseRow.control_group == control_group
        )
    service_rows = list(
        db.scalars(
            select(ReportMarketplaceExpenseRow)
            .where(*service_conditions)
            .order_by(
                ReportMarketplaceExpenseRow.recognition_date,
                ReportMarketplaceExpenseRow.document_date,
                ReportMarketplaceExpenseRow.id,
            )
        )
    )

    wb_groups: dict[tuple[Any, ...], Decimal] = defaultdict(Decimal)
    group_labels: dict[tuple[Any, ...], dict[str, str]] = {}
    wb_document_total = Decimal("0")
    wb_pnl_total = Decimal("0")
    for row in unit_rows:
        week_start = row["week"] or row["accounting_period_date"] or selected_start
        week_end = week_start + timedelta(days=6) if row["week"] else week_start
        base_key = (
            week_start,
            week_end,
            row["client_company_id"],
            row["wb_cabinet_id"],
        )
        amounts = {
            "promotion": row["promotion"],
            "penalties": row["penalties"],
            "core_services": row["core_services"],
        }
        for group_name, amount in amounts.items():
            if control_group and control_group != group_name:
                continue
            if Decimal(amount) == 0:
                continue
            wb_groups[(*base_key, group_name)] += Decimal(amount)
            group_labels.setdefault(
                (*base_key, group_name),
                {"cabinet": row["cabinet"], "organization": row["organization"]},
            )
            wb_document_total += Decimal(amount)
        wb_pnl_total += Decimal(row["pnl_expenses"])

    onec_groups: dict[tuple[Any, ...], Decimal] = defaultdict(Decimal)
    onec_without_vat = Decimal("0")
    onec_vat = Decimal("0")
    onec_with_vat = Decimal("0")
    matched_service_rows: list[ReportMarketplaceExpenseRow] = []
    mapping_issue_rows = 0
    for row in service_rows:
        if row.match_status != "matched_marketplace_pair":
            mapping_issue_rows += 1
            continue
        matched_service_rows.append(row)
        period_start_value = row.period_start or row.recognition_date or selected_start
        period_end_value = row.period_end or row.recognition_date or period_start_value
        key = (
            period_start_value,
            period_end_value,
            row.client_company_id,
            row.wb_cabinet_id,
            row.control_group,
        )
        onec_groups[key] += row.amount_with_vat
        group_labels.setdefault(
            key,
            {"cabinet": row.cabinet, "organization": row.organization},
        )
        onec_without_vat += row.amount_without_vat
        onec_vat += row.vat
        onec_with_vat += row.amount_with_vat

    context_supported = _marketplace_expense_context_supported(report)
    source_row_count = int(
        db.scalar(
            select(func.count(ReportMarketplaceExpenseRow.id)).where(
                ReportMarketplaceExpenseRow.report_run_id == report.id
            )
        )
        or 0
    )
    source_loaded = source_row_count > 0
    source_kinds = sorted({row.source_kind for row in service_rows if row.source_kind})
    groups: list[dict[str, Any]] = []
    all_keys = sorted(
        set(wb_groups) | set(onec_groups),
        key=lambda key: tuple(str(value) for value in key),
    )
    for key in all_keys:
        week_start, week_end, company_id, cabinet_id, group_name = key
        wb_amount = wb_groups.get(key, Decimal("0"))
        onec_amount = onec_groups.get(key)
        if not context_supported:
            group_status = "legacy_rebuild_required"
            delta = None
        elif not source_loaded:
            group_status = "missing_source"
            delta = None
        elif onec_amount is None:
            group_status = "missing_onec_document"
            delta = None
        else:
            delta = onec_amount - wb_amount
            group_status = (
                "matched" if abs(delta) <= MARKETPLACE_EXPENSE_TOLERANCE else "mismatch"
            )
        labels = group_labels.get(key, {})
        groups.append(
            {
                "periodStart": week_start.isoformat(),
                "periodEnd": week_end.isoformat(),
                "clientCompanyId": company_id,
                "wbCabinetId": cabinet_id,
                "cabinet": labels.get("cabinet", ""),
                "organization": labels.get("organization", ""),
                "controlGroup": group_name,
                "controlGroupLabel": MARKETPLACE_EXPENSE_GROUP_LABELS.get(
                    group_name, group_name
                ),
                "wbAmountWithVat": as_float(wb_amount),
                "onecAmountWithVat": as_float(onec_amount),
                "delta": as_float(delta),
                "status": group_status,
                "message": _marketplace_expense_status_message(group_status),
            }
        )

    issue_groups = sum(item["status"] != "matched" for item in groups)
    if not context_supported:
        overall_status = "legacy_rebuild_required"
    elif not source_loaded:
        overall_status = "missing_source"
    elif mapping_issue_rows:
        overall_status = "ambiguous_mapping"
    elif issue_groups:
        overall_status = "mismatch"
    else:
        overall_status = "matched"
    delta_total = (
        onec_with_vat - wb_document_total
        if source_loaded and context_supported
        else None
    )

    items = [_marketplace_expense_payload(row) for row in service_rows]
    for group in groups:
        if group["status"] == "missing_onec_document":
            items.append(
                {
                    "id": (
                        f"missing:{group['periodStart']}:{group['wbCabinetId']}:"
                        f"{group['controlGroup']}"
                    ),
                    "rowType": "missing_onec_document",
                    **group,
                    "amountWithoutVat": None,
                    "vat": None,
                    "amountWithVat": None,
                    "nextAction": "Найти или провести документ услуг WB в 1С.",
                }
            )
    if status:
        items = [
            item
            for item in items
            if item.get("status") == status or item.get("matchStatus") == status
        ]
    if delta_only:
        items = [
            item
            for item in items
            if item.get("rowType") == "missing_onec_document"
            or item.get("matchStatus") != "matched_marketplace_pair"
        ]
    items.sort(
        key=lambda item: (
            0 if item.get("rowType") == "missing_onec_document" else 1,
            item.get("recognitionDate") or item.get("periodStart") or "",
            item.get("documentNumber") or "",
        )
    )
    total_items = len(items)
    source_status = (
        "legacy_rebuild_required"
        if not context_supported
        else "loaded"
        if source_loaded
        else "missing"
    )
    return {
        "period": {
            "start": selected_start.isoformat(),
            "end": selected_end.isoformat(),
            "wbBasis": "accounting_period_date; document amounts with VAT",
            "onecBasis": "service week; penalties by incoming document date",
        },
        "kpis": {
            "wbMarketplacePnlExpenses": as_float(wb_pnl_total),
            "wbMarketplaceDocumentExpensesWithVat": as_float(wb_document_total),
            "onecMarketplaceExpensesWithoutVat": (
                as_float(onec_without_vat) if source_loaded else None
            ),
            "onecMarketplaceVat": as_float(onec_vat) if source_loaded else None,
            "onecMarketplaceExpensesWithVat": (
                as_float(onec_with_vat) if source_loaded else None
            ),
            "marketplaceExpenseDeltaWithVat": as_float(delta_total),
            "marketplaceExpenseReconciliationStatus": overall_status,
            "marketplaceExpenseIssueGroups": issue_groups,
            "marketplaceExpenseMappingIssueRows": mapping_issue_rows,
            "marketplaceExpenseSourceKind": ",".join(source_kinds),
        },
        "groups": groups,
        "items": items[offset : offset + limit],
        "total": total_items,
        "source": {
            "status": source_status,
            "kind": ",".join(source_kinds),
            "rowCount": source_row_count,
            "message": _marketplace_expense_status_message(overall_status),
            "contextVersion": report.marketplace_expense_context_version,
        },
    }


def _marketplace_expense_status_message(status: str) -> str:
    return {
        "matched": "Сверено по каждой контрольной группе.",
        "mismatch": "Есть расхождения по одной или нескольким контрольным группам.",
        "missing_source": "Не проверено: расходы 1С не загружены.",
        "missing_onec_document": "Для расходов WB не найден документ услуг 1С.",
        "ambiguous_mapping": "Нужна проверка сопоставления организации и кабинета.",
        "legacy_rebuild_required": "Нужна пересборка отчёта с контекстом расходов 1С.",
    }.get(status, status)


def _marketplace_expense_payload(row: ReportMarketplaceExpenseRow) -> dict[str, Any]:
    return {
        "id": row.row_uid,
        "rowType": "onec_service",
        "clientCompanyId": row.client_company_id,
        "wbCabinetId": row.wb_cabinet_id,
        "cabinet": row.cabinet,
        "organization": row.organization,
        "periodStart": _date_payload(row.period_start),
        "periodEnd": _date_payload(row.period_end),
        "recognitionDate": _date_payload(row.recognition_date),
        "documentDate": _date_payload(row.document_date),
        "inputDate": _date_payload(row.input_date),
        "documentNumber": row.document_number,
        "inputNumber": row.input_number,
        "serviceCategory": row.service_category,
        "controlGroup": row.control_group,
        "controlGroupLabel": MARKETPLACE_EXPENSE_GROUP_LABELS.get(
            row.control_group, row.control_group
        ),
        "serviceName": row.service_name,
        "amountWithoutVat": as_float(row.amount_without_vat),
        "vat": as_float(row.vat),
        "amountWithVat": as_float(row.amount_with_vat),
        "sourceKind": row.source_kind,
        "matchStatus": row.match_status,
        "status": (
            "matched"
            if row.match_status == "matched_marketplace_pair"
            else row.match_status
        ),
        "nextAction": (
            "Документ включён в сверку."
            if row.match_status == "matched_marketplace_pair"
            else "Проверить организацию, контрагента и привязку кабинета."
        ),
    }


def query_document_reconciliation_rows(
    db: Session,
    report: ReportRun,
    *,
    query: str = "",
    status: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    document_type: str = "",
    document_report: str = "",
    delta_only: bool = False,
    limit: int = 250,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, REPORT_ROWS_MAX_LIMIT))
    offset = max(0, offset)
    conditions: list[Any] = [ReportDocumentReconciliationRow.report_run_id == report.id]
    if status:
        conditions.append(ReportDocumentReconciliationRow.status == status)
    period_condition = _document_reconciliation_period_condition(
        period_start, period_end
    )
    if period_condition is not None:
        conditions.append(period_condition)
    if wb_cabinet_id:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.wb_cabinet_id == wb_cabinet_id,
                ReportDocumentReconciliationRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.client_company_id == client_company_id,
                ReportDocumentReconciliationRow.organization == client_company_id,
            )
        )
    if document_type:
        conditions.append(
            ReportDocumentReconciliationRow.document_type == document_type
        )
    if document_report:
        conditions.append(
            ReportDocumentReconciliationRow.document_report == document_report
        )
    if query:
        like = f"%{query}%"
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.document_report.ilike(like),
                ReportDocumentReconciliationRow.cabinet.ilike(like),
                ReportDocumentReconciliationRow.organization.ilike(like),
                ReportDocumentReconciliationRow.document_type.ilike(like),
                ReportDocumentReconciliationRow.wb_report_ids.ilike(like),
                ReportDocumentReconciliationRow.onec_documents.ilike(like),
                ReportDocumentReconciliationRow.comment.ilike(like),
            )
        )
    rows = list(
        db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(*conditions)
            .order_by(
                ReportDocumentReconciliationRow.sales_period_start,
                ReportDocumentReconciliationRow.id,
            )
        )
    )
    rows = [
        row
        for row in rows
        if _document_reconciliation_is_visible_for_report(row, report)
    ]
    if delta_only:
        rows = [row for row in rows if _document_reconciliation_has_issue(row)]
    page_rows = rows[offset : offset + limit]
    return {
        "items": [_document_reconciliation_payload(row) for row in page_rows],
        "total": len(rows),
        "kpis": _document_reconciliation_kpis(rows),
    }


def query_buyout_reconciliation(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
) -> dict[str, Any]:
    """Explain buyouts without presenting retail-vs-1C as a document mismatch."""
    selected_start = period_start or report.period_start
    selected_end = period_end or report.period_end
    if selected_start > selected_end:
        selected_start, selected_end = selected_end, selected_start

    conditions: list[Any] = [
        ReportDocumentReconciliationRow.report_run_id == report.id,
        ReportDocumentReconciliationRow.document_type == "Уведомление о выкупе",
    ]
    if wb_cabinet_id:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.wb_cabinet_id == wb_cabinet_id,
                ReportDocumentReconciliationRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.client_company_id == client_company_id,
                ReportDocumentReconciliationRow.organization == client_company_id,
            )
        )
    source_rows = list(
        db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(*conditions)
            .order_by(
                ReportDocumentReconciliationRow.sales_period_start,
                ReportDocumentReconciliationRow.id,
            )
        )
    )
    rows: list[dict[str, Any]] = []
    for row in source_rows:
        document_date = _onec_calendar_document_date(row)
        effective_date = (
            document_date or row.expected_document_date or row.sales_period_end
        )
        if effective_date is None or not _date_in_period(
            effective_date,
            period_start=selected_start,
            period_end=selected_end,
        ):
            continue
        missing_onec = _document_reconciliation_missing_onec(row)
        quantity_issue = not missing_onec and _document_reconciliation_has_issue(row)
        primary_status = row.buyout_primary_document_status or "not_loaded"
        primary_amount = row.buyout_primary_document_amount
        primary_delta = row.buyout_primary_document_delta
        if missing_onec:
            quantity_status = "Нет накладной 1С"
            reason = (
                "По уведомлению WB не найдена расходная накладная 1С. "
                "Найдите или загрузите документ, затем пересоберите отчёт."
            )
        elif quantity_issue:
            quantity_status = "Проверить количество"
            reason = (
                "Количество продаж WB не подтверждено расходной накладной 1С. "
                "Сверьте товарные строки и документ выкупа."
            )
        elif primary_status != "verified":
            quantity_status = "Сверено по количеству"
            reason = (
                "Накладная 1С и количество найдены. Денежная сверка не "
                "выполнена: в immutable report нет первичного уведомления WB "
                "с полем «Сумма выкупа»."
            )
        else:
            quantity_status = "Сверено по количеству"
            reason = "Сумма выкупа из первичного уведомления WB и накладная 1С " + (
                "совпадают."
                if abs(primary_delta or Decimal("0"))
                <= FINANCIAL_RECONCILIATION_TOLERANCE
                else "не совпадают: проверьте первичный документ 1С."
            )
        wb_retail = row.buyout_retail_amount_sum or row.wb_amount or Decimal("0")
        onec_net = (
            row.onec_expense_invoice_amount
            if row.onec_expense_invoice_amount is not None
            else row.onec_amount
        )
        rows.append(
            {
                "salesPeriod": row.sales_period,
                "salesPeriodStart": _date_payload(row.sales_period_start),
                "salesPeriodEnd": _date_payload(row.sales_period_end),
                "onecDocumentDate": _date_payload(document_date),
                "expectedDocumentDate": _date_payload(row.expected_document_date),
                "cabinet": row.cabinet,
                "organization": row.organization,
                "wbReports": row.wb_report_ids,
                "onecDocuments": row.onec_documents,
                "wbRetailAmount": _json_number(wb_retail),
                "onecNetAmount": _json_number(onec_net),
                "informationalDelta": _json_number(
                    (onec_net - wb_retail) if onec_net is not None else None
                ),
                "nonComparableDifference": _json_number(
                    (onec_net - wb_retail) if onec_net is not None else None
                ),
                "primaryDocumentId": row.buyout_primary_document_id,
                "primaryDocumentAmount": _json_number(primary_amount),
                "primaryDocumentQuantity": _json_number(
                    row.buyout_primary_document_quantity
                ),
                "primaryDocumentDelta": _json_number(primary_delta),
                "primaryDocumentStatus": primary_status,
                "wbSalesQuantity": _json_number(row.wb_sales_quantity),
                "onecSalesQuantity": _json_number(row.onec_sales_quantity),
                "quantityDelta": _json_number(row.quantity_delta),
                "quantityStatus": quantity_status,
                "reason": reason,
                "missingOnec": missing_onec,
                "quantityIssue": quantity_issue,
            }
        )
    rows.sort(
        key=lambda item: (
            0
            if item["missingOnec"]
            else 1
            if item["quantityIssue"]
            else 2
            if item["primaryDocumentStatus"] != "verified"
            else 3,
            item["onecDocumentDate"] or item["expectedDocumentDate"],
            item["salesPeriodStart"],
        )
    )
    wb_retail_total = sum(
        (Decimal(str(item["wbRetailAmount"] or 0)) for item in rows), Decimal("0")
    )
    onec_net_total = sum(
        (Decimal(str(item["onecNetAmount"] or 0)) for item in rows), Decimal("0")
    )
    missing_rows = sum(1 for item in rows if item["missingOnec"])
    quantity_issue_rows = sum(1 for item in rows if item["quantityIssue"])
    unverified_primary_rows = sum(
        1 for item in rows if item["primaryDocumentStatus"] != "verified"
    )
    verified_primary_rows = len(rows) - unverified_primary_rows
    primary_document_total = sum(
        (
            Decimal(str(item["primaryDocumentAmount"] or 0))
            for item in rows
            if item["primaryDocumentStatus"] == "verified"
        ),
        Decimal("0"),
    )
    primary_document_delta_total = sum(
        (
            Decimal(str(item["primaryDocumentDelta"] or 0))
            for item in rows
            if item["primaryDocumentStatus"] == "verified"
        ),
        Decimal("0"),
    )
    return {
        "period": {
            "start": selected_start.isoformat(),
            "end": selected_end.isoformat(),
            "basis": "1c_posting_date; wb_redeem_notification_required",
        },
        "summary": {
            "wbRetailAmount": _json_number(wb_retail_total),
            "onecNetAmount": _json_number(onec_net_total),
            "informationalDelta": _json_number(onec_net_total - wb_retail_total),
            "nonComparableDifference": _json_number(onec_net_total - wb_retail_total),
            "primaryDocumentAmount": (
                _json_number(primary_document_total) if verified_primary_rows else None
            ),
            "primaryDocumentDelta": (
                _json_number(primary_document_delta_total)
                if verified_primary_rows and not unverified_primary_rows
                else None
            ),
            "primaryDocumentStatus": (
                "verified"
                if rows and not unverified_primary_rows
                else "partial"
                if verified_primary_rows
                else "not_loaded"
                if rows
                else "not_applicable"
            ),
            "unverifiedPrimaryRows": unverified_primary_rows,
            "documentCount": len(rows),
            "missingOnecRows": missing_rows,
            "quantityIssueRows": quantity_issue_rows,
            "matchedRows": len(rows) - missing_rows - quantity_issue_rows,
        },
        "items": rows,
        "total": len(rows),
    }


def query_cogs_reconciliation(
    db: Session,
    report: ReportRun,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    wb_cabinet_id: str = "",
    client_company_id: str = "",
) -> dict[str, Any]:
    """Explain the different WB-week and 1C-calendar COGS bases."""
    selected_start = period_start or report.period_start
    selected_end = period_end or report.period_end
    if selected_start > selected_end:
        selected_start, selected_end = selected_end, selected_start

    unit_conditions: list[Any] = [ReportUnitRow.report_run_id == report.id]
    document_conditions: list[Any] = [
        ReportDocumentReconciliationRow.report_run_id == report.id
    ]
    if wb_cabinet_id:
        unit_conditions.append(
            or_(
                ReportUnitRow.wb_cabinet_id == wb_cabinet_id,
                ReportUnitRow.cabinet == wb_cabinet_id,
            )
        )
        document_conditions.append(
            or_(
                ReportDocumentReconciliationRow.wb_cabinet_id == wb_cabinet_id,
                ReportDocumentReconciliationRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        unit_conditions.append(
            or_(
                ReportUnitRow.client_company_id == client_company_id,
                ReportUnitRow.organization == client_company_id,
            )
        )
        document_conditions.append(
            or_(
                ReportDocumentReconciliationRow.client_company_id == client_company_id,
                ReportDocumentReconciliationRow.organization == client_company_id,
            )
        )

    all_unit_rows = list(db.scalars(select(ReportUnitRow).where(*unit_conditions)))
    pnl_rows = [
        row
        for row in all_unit_rows
        if _date_in_period(
            _unit_row_accounting_date(row),
            period_start=selected_start,
            period_end=selected_end,
        )
    ]
    document_rows = list(
        db.scalars(select(ReportDocumentReconciliationRow).where(*document_conditions))
    )

    pnl_by_kind = {"commissioner": Decimal("0"), "buyout": Decimal("0")}
    for row in pnl_rows:
        pnl_by_kind[_unit_row_cogs_kind(row)] += Decimal(row.cost or 0)

    same_scope_by_kind = {"commissioner": Decimal("0"), "buyout": Decimal("0")}
    calendar_by_kind = {"commissioner": Decimal("0"), "buyout": Decimal("0")}
    adjustment_delta = Decimal("0")
    comparable_document_rows = 0
    for row in document_rows:
        if row.onec_cogs is None:
            continue
        comparable_document_rows += 1
        amount = Decimal(row.onec_cogs)
        kind = _document_cogs_kind(row)
        if kind in same_scope_by_kind and _date_in_period(
            _onec_calendar_document_date(row)
            or row.expected_document_date
            or row.sales_period_end,
            period_start=selected_start,
            period_end=selected_end,
        ):
            same_scope_by_kind[kind] += amount
        if not _date_in_period(
            _onec_calendar_document_date(row),
            period_start=selected_start,
            period_end=selected_end,
        ):
            continue
        if kind in calendar_by_kind:
            calendar_by_kind[kind] += amount
        else:
            adjustment_delta += amount

    commissioner_boundary_delta = (
        calendar_by_kind["commissioner"] - same_scope_by_kind["commissioner"]
    )
    commissioner_same_scope_delta = (
        same_scope_by_kind["commissioner"] - pnl_by_kind["commissioner"]
    )
    buyout_boundary_delta = calendar_by_kind["buyout"] - same_scope_by_kind["buyout"]
    buyout_same_scope_delta = same_scope_by_kind["buyout"] - pnl_by_kind["buyout"]
    pnl_cogs = pnl_by_kind["commissioner"] + pnl_by_kind["buyout"]
    onec_cogs = (
        calendar_by_kind["commissioner"] + calendar_by_kind["buyout"] + adjustment_delta
    )
    delta = onec_cogs - pnl_cogs
    explained_delta = (
        commissioner_boundary_delta
        + commissioner_same_scope_delta
        + buyout_boundary_delta
        + buyout_same_scope_delta
        + adjustment_delta
    )
    unexplained_delta = delta - explained_delta

    cost_review_rows = [row for row in pnl_rows if _unit_row_cost_requires_review(row)]
    cost_absent_rows = [row for row in pnl_rows if _unit_row_cost_absent(row)]
    context_supported = bool(pnl_rows) and all(
        bool(row.cost_match_status) or row.net_qty == 0 for row in pnl_rows
    )
    source_missing = not pnl_rows or comparable_document_rows == 0
    if source_missing:
        status = "missing_source"
    elif (
        abs(unexplained_delta) > FINANCIAL_RECONCILIATION_TOLERANCE
        or cost_review_rows
        or cost_absent_rows
    ):
        status = "needs_review"
    else:
        status = "explained"

    return {
        "period": {
            "start": selected_start.isoformat(),
            "end": selected_end.isoformat(),
            "pnlBasis": "accounting_period_date",
            "onecBasis": "onec_document_date",
        },
        "supported": context_supported,
        "supportMessage": (
            "Контекст себестоимости сохранён в immutable report."
            if context_supported
            else (
                "Агрегатная сверка доступна, но строки отчёта не содержат "
                "источник себестоимости. Пересоберите immutable report."
            )
        ),
        "summary": {
            "status": status,
            "pnlPeriodBasis": "accounting_period_date",
            "onecPeriodBasis": "onec_document_date",
            "pnlCogs": _json_number(pnl_cogs),
            "pnlCommissionerCogs": _json_number(pnl_by_kind["commissioner"]),
            "pnlBuyoutCogs": _json_number(pnl_by_kind["buyout"]),
            "onecCogs": _json_number(onec_cogs),
            "onecCommissionerCogs": _json_number(calendar_by_kind["commissioner"]),
            "onecBuyoutCogs": _json_number(calendar_by_kind["buyout"]),
            "onecAdjustments": _json_number(adjustment_delta),
            "delta": _json_number(delta),
            "commissionerBoundaryDelta": _json_number(commissioner_boundary_delta),
            "commissionerSameScopeDelta": _json_number(commissioner_same_scope_delta),
            "buyoutBoundaryDelta": _json_number(buyout_boundary_delta),
            "buyoutSameScopeDelta": _json_number(buyout_same_scope_delta),
            "adjustmentDelta": _json_number(adjustment_delta),
            "explainedDelta": _json_number(explained_delta),
            "unexplainedDelta": _json_number(unexplained_delta),
            "costReviewRows": len(cost_review_rows),
            "costAbsentRows": len(cost_absent_rows),
            "costReviewCogs": _json_number(
                sum((Decimal(row.cost or 0) for row in cost_review_rows), Decimal("0"))
            ),
            "affectedRevenue": _json_number(
                sum(
                    (Decimal(row.revenue or 0) for row in cost_review_rows),
                    Decimal("0"),
                )
            ),
        },
        "items": _cogs_reconciliation_items(
            pnl_rows,
            document_rows,
            period_start=selected_start,
            period_end=selected_end,
        ),
        "costItems": [_cogs_cost_issue_payload(row) for row in cost_review_rows],
    }


def _unit_row_cogs_kind(row: ReportUnitRow) -> str:
    value = f"{row.document_report} {row.wb_report_id}".casefold()
    return "buyout" if "уведомление о выкупе" in value else "commissioner"


def _unit_row_accounting_date(row: ReportUnitRow) -> date | None:
    return row.accounting_period_date or (
        row.week + timedelta(days=6) if row.week else None
    )


def _document_cogs_kind(row: ReportDocumentReconciliationRow) -> str:
    if _document_reconciliation_is_commissioner(row):
        return "commissioner"
    if _document_reconciliation_is_buyout(row):
        return "buyout"
    return "adjustment"


def _unit_row_cost_absent(row: ReportUnitRow) -> bool:
    return row.net_qty != 0 and row.status.strip().casefold() == (
        "Нет себестоимости 1С".casefold()
    )


def _unit_row_cost_requires_review(row: ReportUnitRow) -> bool:
    return row.net_qty != 0 and (
        row.status.strip().casefold()
        in {
            "Себестоимость 1С требует сверки".casefold(),
            "Нет себестоимости 1С".casefold(),
        }
        or row.cost_match_status in {"nearest_week", "cross_kind", "missing"}
    )


def _cogs_cost_issue_payload(row: ReportUnitRow) -> dict[str, Any]:
    return {
        "id": row.row_uid,
        "weekStart": _date_payload(row.week),
        "weekEnd": _date_payload(row.week + timedelta(days=6) if row.week else None),
        "accountingPeriodDate": _date_payload(row.accounting_period_date),
        "accountingPeriodSource": row.accounting_period_source,
        "cabinet": row.cabinet,
        "organization": row.organization,
        "product": row.product,
        "articleWb": row.article_wb,
        "article1c": row.article_1c,
        "netQuantity": _json_number(Decimal(row.net_qty or 0)),
        "cogs": _json_number(Decimal(row.cost or 0)),
        "unitCost": _json_number(Decimal(row.unit_cost)) if row.unit_cost else None,
        "costMethod": row.cost_method,
        "costMatchStatus": row.cost_match_status,
        "costSourceKind": row.cost_source_kind,
        "costSourcePeriodStart": _date_payload(row.cost_source_period_start),
        "costSourcePeriodEnd": _date_payload(row.cost_source_period_end),
        "costSourceDocument": row.cost_source_document,
        "status": row.status,
        "reason": row.status_reason,
    }


def _cogs_reconciliation_items(
    pnl_rows: list[ReportUnitRow],
    document_rows: list[ReportDocumentReconciliationRow],
    *,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[date | None, date | None, str], dict[str, Any]] = {}
    for row in pnl_rows:
        kind = _unit_row_cogs_kind(row)
        week_end = row.week + timedelta(days=6) if row.week else None
        bucket = buckets.setdefault(
            (row.week, week_end, kind),
            _new_cogs_reconciliation_bucket(kind),
        )
        bucket["pnlQuantity"] += Decimal(row.net_qty or 0)
        bucket["pnlCogs"] += Decimal(row.cost or 0)
        if row.wb_report_id:
            bucket["wbReportIds"].add(row.wb_report_id)

    for row in document_rows:
        if row.onec_cogs is None:
            continue
        kind = _document_cogs_kind(row)
        key = (row.sales_period_start, row.sales_period_end, kind)
        bucket = buckets.setdefault(key, _new_cogs_reconciliation_bucket(kind))
        amount = Decimal(row.onec_cogs)
        document_date = _onec_calendar_document_date(row)
        if kind != "adjustment" and _date_in_period(
            document_date or row.expected_document_date or row.sales_period_end,
            period_start=period_start,
            period_end=period_end,
        ):
            bucket["onecSameScopeCogs"] += amount
        if _date_in_period(
            document_date,
            period_start=period_start,
            period_end=period_end,
        ):
            bucket["onecCalendarCogs"] += amount
        if row.onec_quantity is not None:
            bucket["onecQuantity"] += Decimal(row.onec_quantity)
        if row.wb_report_ids:
            bucket["wbReportIds"].add(row.wb_report_ids)
        if row.onec_documents:
            bucket["onecDocuments"].add(row.onec_documents)
        if document_date is not None:
            bucket["onecDocumentDates"].add(document_date)

    items: list[dict[str, Any]] = []
    for (week_start, week_end, kind), bucket in sorted(
        buckets.items(),
        key=lambda item: (
            item[0][1] or date.min,
            item[0][0] or date.min,
            item[0][2],
        ),
    ):
        pnl_cogs = Decimal(bucket["pnlCogs"])
        same_scope_cogs = Decimal(bucket["onecSameScopeCogs"])
        calendar_cogs = Decimal(bucket["onecCalendarCogs"])
        same_scope_delta = same_scope_cogs - pnl_cogs
        boundary_delta = (
            calendar_cogs - same_scope_cogs if kind != "adjustment" else Decimal("0")
        )
        if kind == "adjustment":
            status = "Корректировка 1С"
            reason = (
                "Закрытие месяца меняет календарную себестоимость 1С без "
                "товарного количества WB."
            )
            action = "Проверить документ закрытия месяца; строки WB не изменять."
        elif boundary_delta:
            status = "Переходящая неделя"
            reason = (
                "В строках отчёта нет подтвержденной учетной даты 1С, поэтому "
                "периодическая база еще различается."
            )
            action = (
                "Пересобрать immutable report с accounting_period_date; "
                "документ 1С вручную не переносить."
            )
        elif abs(same_scope_delta) > FINANCIAL_RECONCILIATION_TOLERANCE:
            status = "Проверить стоимость"
            reason = (
                "Себестоимость совпадающей недели WB отличается от итога документа 1С."
            )
            action = "Открыть строки себестоимости и проверить цену/допрасходы 1С."
        else:
            status = "Сходится"
            reason = (
                "Себестоимость недели воспроизводится на одинаковой периодической базе."
            )
            action = "Действий не требуется."
        items.append(
            {
                "component": kind,
                "salesPeriodStart": _date_payload(week_start),
                "salesPeriodEnd": _date_payload(week_end),
                "onecDocumentDate": ", ".join(
                    value.isoformat() for value in sorted(bucket["onecDocumentDates"])
                ),
                "documentType": {
                    "commissioner": "Отчет комиссионера",
                    "buyout": "Уведомление о выкупе",
                    "adjustment": "Корректировка себестоимости 1С",
                }[kind],
                "wbReportIds": ", ".join(sorted(bucket["wbReportIds"])),
                "onecDocuments": ", ".join(sorted(bucket["onecDocuments"])),
                "pnlQuantity": _json_number(Decimal(bucket["pnlQuantity"])),
                "onecQuantity": _json_number(Decimal(bucket["onecQuantity"])),
                "pnlCogs": _json_number(pnl_cogs),
                "onecSameScopeCogs": _json_number(same_scope_cogs),
                "onecCalendarCogs": _json_number(calendar_cogs),
                "sameScopeDelta": _json_number(same_scope_delta),
                "boundaryDelta": _json_number(boundary_delta),
                "status": status,
                "reason": reason,
                "action": action,
            }
        )
    return items


def _new_cogs_reconciliation_bucket(kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "pnlQuantity": Decimal("0"),
        "onecQuantity": Decimal("0"),
        "pnlCogs": Decimal("0"),
        "onecSameScopeCogs": Decimal("0"),
        "onecCalendarCogs": Decimal("0"),
        "wbReportIds": set(),
        "onecDocuments": set(),
        "onecDocumentDates": set(),
    }


FINANCIAL_RECONCILIATION_TYPES = {
    "revenue_with_vat": "Выручка с НДС",
    "penalties": "Штрафы",
}
FINANCIAL_RECONCILIATION_TOLERANCE = Decimal("1")


def query_financial_document_reconciliation(
    db: Session,
    report: ReportRun,
    *,
    query: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
    control_type: str = "",
    wb_cabinet_id: str = "",
    client_company_id: str = "",
    document_type: str = "",
    delta_only: bool = False,
) -> dict[str, Any]:
    """Reconcile comparable WB and 1C facts by the same WB sales week.

    Commissioner revenue is comparable with the 1C sales register. Buyout
    retail revenue and the net expense-invoice amount use different monetary
    bases, so they are exposed separately and never turned into a revenue
    delta.
    """

    selected_start = period_start or report.period_start
    selected_end = period_end or report.period_end
    if selected_start and selected_end and selected_start > selected_end:
        selected_start, selected_end = selected_end, selected_start

    unit_conditions: list[Any] = [ReportUnitRow.report_run_id == report.id]
    document_conditions: list[Any] = [
        ReportDocumentReconciliationRow.report_run_id == report.id
    ]
    if wb_cabinet_id:
        unit_conditions.append(
            or_(
                ReportUnitRow.wb_cabinet_id == wb_cabinet_id,
                ReportUnitRow.cabinet == wb_cabinet_id,
            )
        )
        document_conditions.append(
            or_(
                ReportDocumentReconciliationRow.wb_cabinet_id == wb_cabinet_id,
                ReportDocumentReconciliationRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        unit_conditions.append(
            or_(
                ReportUnitRow.client_company_id == client_company_id,
                ReportUnitRow.organization == client_company_id,
            )
        )
        document_conditions.append(
            or_(
                ReportDocumentReconciliationRow.client_company_id == client_company_id,
                ReportDocumentReconciliationRow.organization == client_company_id,
            )
        )
    if document_type:
        document_conditions.append(
            ReportDocumentReconciliationRow.document_type == document_type
        )
    unit_rows = list(db.scalars(select(ReportUnitRow).where(*unit_conditions)))
    document_rows = list(
        db.scalars(select(ReportDocumentReconciliationRow).where(*document_conditions))
    )
    refresh_run = _latest_financial_onec_refresh_run(db, report)
    source_rows = _financial_onec_source_rows(db, report, refresh_run)
    source_statuses = _financial_onec_source_statuses(db, refresh_run)
    sales_available = bool(document_rows) and any(
        as_text(row.onec_documents) for row in document_rows
    )
    if not sales_available:
        sales_available = _financial_source_available(
            source_statuses.get("onec_sales_register", "")
        )
    penalties_available = _financial_source_available(
        source_statuses.get("onec_incoming_invoices", "")
    )

    wb_revenue, wb_revenue_total = _wb_revenue_document_buckets(
        document_rows,
        unit_rows,
        period_start=selected_start,
        period_end=selected_end,
    )
    onec_revenue, onec_revenue_total = _onec_revenue_report_buckets(
        document_rows,
        period_start=selected_start,
        period_end=selected_end,
    )
    onec_calendar_revenue = _onec_calendar_revenue_report_buckets(
        document_rows,
        period_start=selected_start,
        period_end=selected_end,
    )
    wb_penalties, wb_penalties_total = _wb_penalty_document_buckets(
        unit_rows,
        period_start=selected_start,
        period_end=selected_end,
    )
    organization_ids = _financial_selected_organization_ids(
        db,
        report,
        wb_cabinet_id=wb_cabinet_id,
        client_company_id=client_company_id,
    )
    onec_penalties, onec_penalties_total = _onec_penalty_document_buckets(
        source_rows.get("onec_incoming_invoices", []),
        period_start=selected_start,
        period_end=selected_end,
        organization_ids=organization_ids,
    )

    rows: list[dict[str, Any]] = []
    rows.extend(
        _financial_reconciliation_rows(
            control_type="revenue_with_vat",
            wb_buckets=wb_revenue,
            onec_buckets=onec_revenue,
            source_available=sales_available,
        )
    )
    rows.extend(
        _financial_reconciliation_rows(
            control_type="penalties",
            wb_buckets=wb_penalties,
            onec_buckets=onec_penalties,
            source_available=penalties_available,
        )
    )

    if control_type in FINANCIAL_RECONCILIATION_TYPES:
        rows = [row for row in rows if row["controlType"] == control_type]
    if query:
        needle = query.casefold()
        rows = [
            row
            for row in rows
            if needle
            in " ".join(
                str(row.get(key) or "")
                for key in (
                    "controlLabel",
                    "period",
                    "wbDocument",
                    "onecDocuments",
                    "status",
                    "comment",
                )
            ).casefold()
        ]
    if delta_only:
        rows = [row for row in rows if row["status"] not in {"Сходится", "Справочно"}]

    rows.sort(
        key=lambda row: (
            0 if row["controlType"] == "revenue_with_vat" else 1,
            row.get("periodStart") or "",
            row.get("documentType") or "",
        )
    )
    revenue_onec = onec_revenue_total if sales_available else None
    buyout_wb = _financial_bucket_total(
        wb_revenue, document_type="Уведомление о выкупе"
    )
    buyout_onec = (
        _financial_bucket_total(
            onec_revenue,
            document_type="Уведомление о выкупе",
            documents_only=True,
        )
        if sales_available
        else None
    )
    onec_calendar_commissioner_revenue = _financial_bucket_total(
        onec_calendar_revenue,
        document_type="Отчет комиссионера",
        documents_only=True,
    )
    onec_calendar_buyout_revenue = _financial_bucket_total(
        onec_calendar_revenue,
        document_type="Уведомление о выкупе",
        documents_only=True,
    )
    onec_calendar_revenue_total = sum(
        (
            Decimal(bucket.get("amount", Decimal("0")))
            for bucket in onec_calendar_revenue.values()
        ),
        Decimal("0"),
    )
    onec_calendar_document_count = sum(
        len(bucket.get("documents", [])) for bucket in onec_calendar_revenue.values()
    )
    penalties_onec = onec_penalties_total if penalties_available else None
    return {
        "items": rows,
        "total": len(rows),
        "period": {
            "start": selected_start.isoformat() if selected_start else "",
            "end": selected_end.isoformat() if selected_end else "",
            "wbBasis": "week_end",
            "onecBasis": (
                "sales_week_end_for_wb_comparison; "
                "actual_date_for_1c_calendar_and_penalties"
            ),
        },
        "kpis": {
            "revenueWb": _json_number(wb_revenue_total),
            "revenueOnec": _json_number(revenue_onec),
            "revenueDelta": _json_number(
                revenue_onec - wb_revenue_total if revenue_onec is not None else None
            ),
            "buyoutRetailWb": _json_number(buyout_wb),
            "buyoutNetOnec": _json_number(buyout_onec),
            "buyoutAmountsComparable": False,
            "onecCalendarRevenue": _json_number(onec_calendar_revenue_total),
            "onecCalendarCommissionerRevenue": _json_number(
                onec_calendar_commissioner_revenue
            ),
            "onecCalendarBuyoutRevenue": _json_number(onec_calendar_buyout_revenue),
            "onecCalendarDocumentCount": onec_calendar_document_count,
            "penaltiesWb": _json_number(wb_penalties_total),
            "penaltiesOnec": _json_number(penalties_onec),
            "penaltiesDelta": _json_number(
                penalties_onec - wb_penalties_total
                if penalties_onec is not None
                else None
            ),
            "issueRows": sum(
                row["status"] not in {"Сходится", "Справочно"} for row in rows
            ),
        },
        "source": {
            "refreshRunId": refresh_run.id if refresh_run else "",
            "status": refresh_run.status if refresh_run else "missing",
            "snapshotSetId": refresh_run.snapshot_set_id if refresh_run else "",
            "loadedAt": (refresh_run.finished_at or refresh_run.updated_at).isoformat()
            if refresh_run
            else "",
            "salesRegisterRows": len(source_rows.get("onec_sales_register", [])),
            "incomingInvoiceRows": len(source_rows.get("onec_incoming_invoices", [])),
        },
    }


def _latest_financial_onec_refresh_run(
    db: Session, report: ReportRun
) -> SourceRefreshRun | None:
    candidates = list(
        db.scalars(
            select(SourceRefreshRun)
            .where(
                SourceRefreshRun.tenant_id == report.tenant_id,
                SourceRefreshRun.client_id == report.client_id,
            )
            .order_by(SourceRefreshRun.created_at.desc())
            .limit(30)
        )
    )
    if report.source_snapshot_set_id:
        candidates.sort(
            key=lambda item: item.snapshot_set_id == report.source_snapshot_set_id,
            reverse=True,
        )
    fallback = None
    required_types = {"onec_sales_register", "onec_incoming_invoices"}
    for refresh_run in candidates:
        source_types = set(
            db.scalars(
                select(SourceRefreshCollection.source_type).where(
                    SourceRefreshCollection.refresh_run_id == refresh_run.id,
                    SourceRefreshCollection.source_type.in_(
                        {
                            "onec_sales_register",
                            "onec_incoming_invoices",
                        }
                    ),
                )
            )
        )
        if required_types.issubset(source_types):
            return refresh_run
        if source_types and fallback is None:
            fallback = refresh_run
    return fallback


def _financial_onec_source_rows(
    db: Session,
    report: ReportRun,
    refresh_run: SourceRefreshRun | None,
) -> dict[str, list[SourceSnapshotRow]]:
    result: dict[str, list[SourceSnapshotRow]] = {}
    if refresh_run is None:
        return result
    for source_type in (
        "onec_sales_register",
        "onec_incoming_invoices",
        "onec_expense_invoices",
    ):
        result[source_type] = list(
            db.scalars(
                _source_snapshot_rows_select(
                    tenant_id=report.tenant_id,
                    refresh_run=refresh_run,
                    source_type=source_type,
                ).order_by(SourceSnapshotRow.row_number)
            )
        )
    return result


def _financial_onec_source_statuses(
    db: Session, refresh_run: SourceRefreshRun | None
) -> dict[str, str]:
    if refresh_run is None:
        return {}
    collections = list(
        db.scalars(
            select(SourceRefreshCollection).where(
                SourceRefreshCollection.refresh_run_id == refresh_run.id,
                SourceRefreshCollection.source_type.in_(
                    {
                        "onec_sales_register",
                        "onec_incoming_invoices",
                        "onec_expense_invoices",
                    }
                ),
            )
        )
    )
    return {item.source_type: item.status for item in collections}


def _financial_source_available(status: str) -> bool:
    return status.strip().lower() in SOURCE_LOAD_OK_STATUSES


def _wb_revenue_document_buckets(
    document_rows: list[ReportDocumentReconciliationRow],
    unit_rows: list[ReportUnitRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> tuple[dict[tuple[date, str], dict[str, Any]], Decimal]:
    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    for row in document_rows:
        week = row.sales_period_start
        if week is None or not _date_in_period(
            week + timedelta(days=6),
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        document_type = row.document_type or "Документ WB"
        bucket = buckets.setdefault(
            (week, document_type),
            {"amount": Decimal("0"), "documents": set()},
        )
        bucket["amount"] += row.wb_amount or Decimal("0")
        for label in (
            row.wb_report_ids,
            _closing_date_label(row.document_report, row.sales_period_end),
        ):
            if label:
                bucket["documents"].add(label)
    # ``unit_rows`` remains in the signature for API compatibility. The
    # document mart is the source of truth here because it separates
    # commissioner revenue from buyout retail revenue.
    _ = unit_rows
    total = _financial_bucket_total(
        buckets,
        document_type="Отчет комиссионера",
    )
    return buckets, total


def _onec_revenue_report_buckets(
    document_rows: list[ReportDocumentReconciliationRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> tuple[dict[tuple[date, str], dict[str, Any]], Decimal]:
    """Use the immutable report's matched 1C facts on the WB sales-week key."""
    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    for row in document_rows:
        week = row.sales_period_start
        if week is None or not _date_in_period(
            week + timedelta(days=6),
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        if not as_text(row.onec_documents):
            continue
        document_type = row.document_type or "Документ WB"
        bucket = buckets.setdefault(
            (week, document_type),
            {
                "amount": Decimal("0"),
                "documents": [],
                "outsideDocuments": [],
            },
        )
        amount = row.onec_amount or Decimal("0")
        bucket["amount"] += amount
        document_date = row.expected_document_date or week + timedelta(days=6)
        bucket["documents"].append(
            {
                "label": row.onec_documents,
                "date": document_date,
                "amount": amount,
            }
        )
    total = _financial_bucket_total(
        buckets,
        document_type="Отчет комиссионера",
        documents_only=True,
    )
    return buckets, total


def _onec_calendar_revenue_report_buckets(
    document_rows: list[ReportDocumentReconciliationRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[tuple[date, str], dict[str, Any]]:
    """Aggregate the same persisted 1C documents by their posting date.

    This is the basis of the 1C ``Валовая прибыль по номенклатуре`` report:
    both commissioner reports and expense invoices for buyouts enter the
    calendar month in which 1C posted them.
    """
    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    for row in document_rows:
        if not as_text(row.onec_documents):
            continue
        document_date = _onec_calendar_document_date(row)
        if document_date is None or not _date_in_period(
            document_date,
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        document_type = row.document_type or "Документ 1С"
        if document_type == "Корректировка себестоимости 1С":
            continue
        bucket = buckets.setdefault(
            (document_date, document_type),
            {
                "amount": Decimal("0"),
                "documents": [],
            },
        )
        amount = row.onec_amount or Decimal("0")
        bucket["amount"] += amount
        bucket["documents"].append(
            {
                "label": row.onec_documents,
                "date": document_date,
                "amount": amount,
            }
        )
    return buckets


def _onec_calendar_revenue_kpis(
    document_rows: list[ReportDocumentReconciliationRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    """Return the 1C calendar total that matches its gross-profit report.

    The KPI deliberately uses the posting date of each matched 1C document,
    rather than the WB sales-week key.  It therefore includes commissioner
    reports, buyout invoices and separately posted 1C corrections on the same
    basis as the 1C ``Валовая прибыль по номенклатуре`` report.
    """
    buckets = _onec_calendar_revenue_report_buckets(
        document_rows,
        period_start=period_start,
        period_end=period_end,
    )
    calendar_rows: list[ReportDocumentReconciliationRow] = []
    for row in document_rows:
        if not as_text(row.onec_documents):
            continue
        document_date = _onec_calendar_document_date(row)
        if document_date is None or not _date_in_period(
            document_date,
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        calendar_rows.append(row)
    revenue_document_rows = [
        row
        for row in calendar_rows
        if as_text(row.document_type) != "Корректировка себестоимости 1С"
    ]
    document_count = len(revenue_document_rows)
    if not calendar_rows:
        return {
            "revenueWithVat": None,
            "documentCount": 0,
            "commissionerRevenueWithVat": None,
            "buyoutRevenueWithVat": None,
            "otherRevenueWithVat": None,
            "salesQuantity": None,
            "commissionerQuantity": None,
            "buyoutQuantity": None,
            "otherQuantity": None,
            "cogs": None,
            "commissionerCogs": None,
            "buyoutCogs": None,
            "otherCogs": None,
            "cogsWithoutVat": None,
            "grossProfit": None,
            "costAdjustmentRows": 0,
            "wbRevenueWithVat": None,
            "wbCommissionerRevenueWithVat": None,
            "wbBuyoutRetailRevenueWithVat": None,
            "commissionerRevenueDelta": None,
            "buyoutRevenueDelta": None,
            "buyoutPrimaryDocumentAmount": None,
            "buyoutPrimaryDocumentDelta": None,
            "buyoutPrimaryDocumentStatus": "not_applicable",
            "buyoutUnverifiedPrimaryRows": 0,
            "wbRevenueDeltaVsOnec": None,
            "accountingReconciliationWbAmount": None,
            "accountingReconciliationOnecAmount": None,
            "accountingReconciliationDelta": None,
            "accountingReconciliationStatus": "Нет документов 1С",
            "accountingReconciliationBuyoutBasis": "not_applicable",
        }
    total = sum(
        (Decimal(bucket.get("amount", Decimal("0"))) for bucket in buckets.values()),
        Decimal("0"),
    )
    commissioner = _financial_bucket_total(
        buckets,
        document_type="Отчет комиссионера",
        documents_only=True,
    )
    buyout = _financial_bucket_total(
        buckets,
        document_type="Уведомление о выкупе",
        documents_only=True,
    )
    commissioner_rows = [
        row for row in calendar_rows if _document_reconciliation_is_commissioner(row)
    ]
    buyout_rows = [
        row for row in calendar_rows if _document_reconciliation_is_buyout(row)
    ]
    other_rows = [
        row
        for row in calendar_rows
        if row not in commissioner_rows and row not in buyout_rows
    ]
    onec_quantity = _sum_optional_document_decimal(calendar_rows, "onec_quantity")
    commissioner_quantity = _sum_optional_document_decimal(
        commissioner_rows, "onec_quantity"
    )
    buyout_quantity = _sum_optional_document_decimal(buyout_rows, "onec_quantity")
    other_quantity = _sum_optional_document_decimal(other_rows, "onec_quantity")
    onec_cogs = _sum_optional_document_decimal(calendar_rows, "onec_cogs")
    commissioner_cogs = _sum_optional_document_decimal(commissioner_rows, "onec_cogs")
    buyout_cogs = _sum_optional_document_decimal(buyout_rows, "onec_cogs")
    other_cogs = _sum_optional_document_decimal(other_rows, "onec_cogs")
    onec_cogs_without_vat = _sum_optional_document_decimal(
        calendar_rows, "onec_cogs_without_vat"
    )
    onec_gross_profit = _sum_optional_document_decimal(
        calendar_rows, "onec_gross_profit"
    )
    cost_adjustment_rows = sum(
        as_text(row.document_type) == "Корректировка себестоимости 1С"
        for row in calendar_rows
    )
    wb_commissioner = sum(
        (Decimal(str(row.wb_amount or 0)) for row in commissioner_rows),
        Decimal("0"),
    )
    wb_buyout_retail = sum(
        (
            Decimal(str(row.buyout_retail_amount_sum or row.wb_amount or 0))
            for row in buyout_rows
        ),
        Decimal("0"),
    )
    wb_total = wb_commissioner + wb_buyout_retail
    commissioner_decimal = Decimal(commissioner)
    buyout_decimal = Decimal(buyout)
    buyout_review_rows = sum(
        _document_reconciliation_has_issue(row) for row in buyout_rows
    )
    verified_primary_rows = [
        row
        for row in buyout_rows
        if row.buyout_primary_document_status == "verified"
        and row.buyout_primary_document_amount is not None
    ]
    buyout_unverified_primary_rows = len(buyout_rows) - len(verified_primary_rows)
    buyout_primary_document_status = (
        "verified"
        if buyout_rows and not buyout_unverified_primary_rows
        else "partial"
        if verified_primary_rows
        else "not_loaded"
        if buyout_rows
        else "not_applicable"
    )
    buyout_primary_document_amount = sum(
        (
            Decimal(str(row.buyout_primary_document_amount or 0))
            for row in verified_primary_rows
        ),
        Decimal("0"),
    )
    buyout_primary_document_delta = (
        buyout_primary_document_amount - buyout_decimal
        if buyout_rows and not buyout_unverified_primary_rows
        else None
    )
    accounting_wb_amount = (
        wb_commissioner + buyout_primary_document_amount
        if not buyout_unverified_primary_rows
        else None
    )
    accounting_onec_amount = commissioner_decimal + buyout_decimal
    accounting_delta = (
        accounting_onec_amount - accounting_wb_amount
        if accounting_wb_amount is not None and not buyout_review_rows
        else None
    )
    accounting_status = (
        "Нужна проверка выкупов"
        if buyout_review_rows
        else (
            "Не проверена первичка выкупов WB"
            if buyout_unverified_primary_rows
            else (
                "Сходится"
                if abs(accounting_delta or Decimal("0"))
                <= FINANCIAL_RECONCILIATION_TOLERANCE
                else "Расхождение комиссионера"
            )
        )
    )
    return {
        "revenueWithVat": _json_number(total),
        "documentCount": document_count,
        "commissionerRevenueWithVat": _json_number(commissioner_decimal),
        "buyoutRevenueWithVat": _json_number(buyout_decimal),
        "otherRevenueWithVat": _json_number(
            total - commissioner_decimal - buyout_decimal
        ),
        "salesQuantity": _json_number(onec_quantity),
        "commissionerQuantity": _json_number(commissioner_quantity),
        "buyoutQuantity": _json_number(buyout_quantity),
        "otherQuantity": _json_number(other_quantity),
        "cogs": _json_number(onec_cogs),
        "commissionerCogs": _json_number(commissioner_cogs),
        "buyoutCogs": _json_number(buyout_cogs),
        "otherCogs": _json_number(other_cogs),
        "cogsWithoutVat": _json_number(onec_cogs_without_vat),
        "grossProfit": _json_number(onec_gross_profit),
        "costAdjustmentRows": cost_adjustment_rows,
        "wbRevenueWithVat": _json_number(wb_total),
        "wbCommissionerRevenueWithVat": _json_number(wb_commissioner),
        "wbBuyoutRetailRevenueWithVat": _json_number(wb_buyout_retail),
        "commissionerRevenueDelta": _json_number(
            commissioner_decimal - wb_commissioner
        ),
        "buyoutRevenueDelta": _json_number(buyout_decimal - wb_buyout_retail),
        "buyoutPrimaryDocumentAmount": (
            _json_number(buyout_primary_document_amount)
            if verified_primary_rows
            else None
        ),
        "buyoutPrimaryDocumentDelta": _json_number(buyout_primary_document_delta),
        "buyoutPrimaryDocumentStatus": buyout_primary_document_status,
        "buyoutUnverifiedPrimaryRows": buyout_unverified_primary_rows,
        "wbRevenueDeltaVsOnec": _json_number(total - wb_total),
        "accountingReconciliationWbAmount": _json_number(accounting_wb_amount),
        "accountingReconciliationOnecAmount": _json_number(accounting_onec_amount),
        "accountingReconciliationDelta": _json_number(accounting_delta),
        "accountingReconciliationStatus": accounting_status,
        "accountingReconciliationBuyoutBasis": (
            "wb_redeem_notification_purchase_amount"
            if buyout_rows and not buyout_unverified_primary_rows
            else "wb_redeem_notification_required"
            if buyout_rows
            else "not_applicable"
        ),
    }


def _sum_optional_document_decimal(
    rows: Iterable[ReportDocumentReconciliationRow],
    field_name: str,
) -> Decimal | None:
    values = [getattr(row, field_name) for row in rows]
    available = [Decimal(value) for value in values if value is not None]
    return sum(available, Decimal("0")) if available else None


def _onec_calendar_document_date(
    row: ReportDocumentReconciliationRow,
) -> date | None:
    for value in as_text(row.onec_document_dates).split(","):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            continue
    return row.expected_document_date


def _financial_selected_organization_ids(
    db: Session,
    report: ReportRun,
    *,
    wb_cabinet_id: str,
    client_company_id: str,
) -> set[str]:
    company_ids: set[str] = set()
    if client_company_id:
        company_ids.add(client_company_id)
    if wb_cabinet_id:
        cabinet = db.scalar(
            select(WbCabinet).where(
                WbCabinet.client_id == report.client_id,
                or_(
                    WbCabinet.id == wb_cabinet_id,
                    WbCabinet.display_name == wb_cabinet_id,
                ),
            )
        )
        if cabinet is not None and cabinet.client_company_id:
            company_ids.add(cabinet.client_company_id)
    if not company_ids:
        return set()
    return {
        value
        for value in db.scalars(
            select(ClientCompany.onec_organization_id).where(
                ClientCompany.client_id == report.client_id,
                ClientCompany.id.in_(company_ids),
            )
        )
        if value
    }


def _onec_revenue_document_buckets(
    source_rows: dict[str, list[SourceSnapshotRow]],
    *,
    period_start: date | None,
    period_end: date | None,
) -> tuple[dict[tuple[date, str], dict[str, Any]], Decimal]:
    expense_headers = {
        _safe_payload_text(row.row_payload or {}, "Ref_Key"): row.row_payload or {}
        for row in source_rows.get("onec_expense_invoices", [])
        if _safe_payload_text(row.row_payload or {}, "Ref_Key")
    }
    documents: dict[tuple[date, str, str, date], dict[str, Any]] = {}
    total = Decimal("0")
    for row in source_rows.get("onec_sales_register", []):
        for item in _iter_onec_recordset_items(row.row_payload or {}):
            if item.get("Active") is False:
                continue
            actual_date = _payload_date_or_none(
                _safe_payload_text(item, "Period", "Период", "Date", "Дата")
            )
            document_id = _safe_payload_text(item, "Документ", "document_id")
            document_type = _financial_revenue_document_type(
                _safe_payload_text(item, "Документ_Type", "document_type")
            )
            if actual_date is None or not document_type:
                continue
            logical_week = _financial_document_week(actual_date, document_type)
            key = (logical_week, document_type, document_id, actual_date)
            document = documents.setdefault(
                key,
                {
                    "amount": Decimal("0"),
                    "label": _financial_onec_revenue_document_label(
                        document_type,
                        actual_date,
                        document_id,
                        expense_headers.get(document_id),
                    ),
                },
            )
            amount = _payload_decimal(item, "Сумма", "amount")
            document["amount"] += amount

    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    for (week, document_type, _document_id, actual_date), document in documents.items():
        if document["amount"] == 0:
            continue
        bucket = buckets.setdefault(
            (week, document_type),
            {
                "amount": Decimal("0"),
                "documents": [],
                "outsideDocuments": [],
            },
        )
        entry = {
            "label": document["label"],
            "date": actual_date,
            "amount": document["amount"],
        }
        if _date_in_period(
            week + timedelta(days=6),
            period_start=period_start,
            period_end=period_end,
        ):
            bucket["amount"] += document["amount"]
            bucket["documents"].append(entry)
        else:
            bucket["outsideDocuments"].append(entry)
    total = _financial_bucket_total(
        buckets,
        document_type="Отчет комиссионера",
        documents_only=True,
    )
    return buckets, total


def _financial_bucket_total(
    buckets: dict[tuple[date, str], dict[str, Any]],
    *,
    document_type: str,
    documents_only: bool = False,
) -> Decimal:
    total = Decimal("0")
    for (_week, current_type), bucket in buckets.items():
        if current_type != document_type:
            continue
        if documents_only and not bucket.get("documents"):
            continue
        total += Decimal(bucket.get("amount", Decimal("0")))
    return total


def _financial_revenue_document_type(value: str) -> str:
    normalized = value.casefold()
    if "отчеткомиссионера" in normalized:
        return "Отчет комиссионера"
    if "расходнаянакладная" in normalized:
        return "Уведомление о выкупе"
    return ""


def _financial_document_week(actual_date: date, document_type: str) -> date:
    week = actual_date - timedelta(days=actual_date.weekday())
    if document_type == "Уведомление о выкупе":
        week -= timedelta(days=7)
    return week


def _financial_onec_revenue_document_label(
    document_type: str,
    actual_date: date,
    document_id: str,
    header: dict[str, Any] | None,
) -> str:
    if header:
        number = _safe_payload_text(header, "Number", "Номер")
        if number:
            return f"Расходная накладная {number} от {_ru_short_date(actual_date)}"
    short_id = document_id[:8] if document_id else "без номера"
    return f"{document_type} {short_id} от {_ru_short_date(actual_date)}"


def _wb_penalty_document_buckets(
    unit_rows: list[ReportUnitRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> tuple[dict[tuple[date, str], dict[str, Any]], Decimal]:
    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    total = Decimal("0")
    for row in unit_rows:
        week = row.week
        if week is None or not _date_in_period(
            _unit_row_accounting_date(row),
            period_start=period_start,
            period_end=period_end,
        ):
            continue
        amount = row.penalties or Decimal("0")
        total += amount
        bucket = buckets.setdefault(
            (week, "Штрафы WB"),
            {"amount": Decimal("0"), "documents": set()},
        )
        bucket["amount"] += amount
        label = (
            _closing_date_label(row.document_report, week + timedelta(days=6))
            or row.wb_report_id
        )
        if label:
            bucket["documents"].add(label)
    return buckets, total


def _onec_penalty_document_buckets(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date | None,
    period_end: date | None,
    organization_ids: set[str] | None = None,
) -> tuple[dict[tuple[date, str], dict[str, Any]], Decimal]:
    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    total = Decimal("0")
    for row in rows:
        payload = row.row_payload or {}
        if payload.get("DeletionMark") is True or payload.get("Posted") is False:
            continue
        if organization_ids:
            organization_id = _safe_payload_text(
                payload,
                "Организация_Key",
                "Организация",
                "organization_id",
                "Organization_Key",
            )
            if organization_id not in organization_ids:
                continue
        actual_date = _payload_date_or_none(_safe_payload_text(payload, "Date", "Дата"))
        if actual_date is None:
            continue
        amount = _onec_penalty_invoice_amount(payload)
        if amount == 0:
            continue
        week = actual_date - timedelta(days=actual_date.weekday())
        bucket = buckets.setdefault(
            (week, "Штрафы WB"),
            {
                "amount": Decimal("0"),
                "documents": [],
                "outsideDocuments": [],
            },
        )
        entry = {
            "label": _financial_penalty_document_label(payload, actual_date),
            "date": actual_date,
            "amount": amount,
        }
        if _date_in_period(
            actual_date, period_start=period_start, period_end=period_end
        ):
            bucket["amount"] += amount
            bucket["documents"].append(entry)
            total += amount
        else:
            bucket["outsideDocuments"].append(entry)
    return buckets, total


def _onec_penalty_invoice_amount(payload: dict[str, Any]) -> Decimal:
    amount = Decimal("0")
    for table_name in ("Расходы", "Запасы"):
        table = payload.get(table_name)
        if not isinstance(table, list):
            continue
        for item in table:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                _safe_payload_text(
                    item,
                    "Содержание",
                    "Номенклатура",
                    "Комментарий",
                    "Наименование",
                    "description",
                )
                for _ in (0,)
            ).casefold()
            if "штраф" in text:
                amount += _payload_decimal(item, "Сумма", "Всего", "amount")
    return amount


def _financial_penalty_document_label(
    payload: dict[str, Any], actual_date: date
) -> str:
    number = _safe_payload_text(payload, "Number", "Номер") or "без номера"
    incoming = _safe_payload_text(payload, "НомерВходящегоДокумента", "incoming_number")
    incoming_text = f" (вх. {incoming})" if incoming else ""
    return (
        f"Приходная накладная {number}{incoming_text} от {_ru_short_date(actual_date)}"
    )


def _financial_reconciliation_rows(
    *,
    control_type: str,
    wb_buckets: dict[tuple[date, str], dict[str, Any]],
    onec_buckets: dict[tuple[date, str], dict[str, Any]],
    source_available: bool,
) -> list[dict[str, Any]]:
    rows = []
    onec_period_keys = {
        key for key, bucket in onec_buckets.items() if bucket.get("documents")
    }
    for week, document_type in sorted(set(wb_buckets) | onec_period_keys):
        wb = wb_buckets.get((week, document_type))
        onec = onec_buckets.get((week, document_type), {})
        wb_amount = wb["amount"] if wb else Decimal("0")
        onec_amount = onec.get("amount", Decimal("0")) if source_available else None
        in_documents = onec.get("documents", [])
        outside_documents = onec.get("outsideDocuments", [])
        amounts_comparable = not (
            control_type == "revenue_with_vat"
            and document_type == "Уведомление о выкупе"
        )
        delta = (
            onec_amount - wb_amount
            if onec_amount is not None and amounts_comparable
            else None
        )
        status, comment = _financial_reconciliation_status(
            wb_present=wb is not None,
            onec_documents=in_documents,
            outside_documents=outside_documents,
            delta=delta,
            source_available=source_available,
            amounts_comparable=amounts_comparable,
        )
        rows.append(
            {
                "controlType": control_type,
                "controlLabel": (
                    "Выкуп: WB розница / 1С нетто"
                    if not amounts_comparable
                    else FINANCIAL_RECONCILIATION_TYPES[control_type]
                ),
                "period": (
                    f"{_ru_short_date(week)}–{_ru_short_date(week + timedelta(days=6))}"
                ),
                "periodStart": week.isoformat(),
                "periodEnd": (week + timedelta(days=6)).isoformat(),
                "documentType": document_type,
                "wbDocument": _financial_wb_documents(wb),
                "onecDocuments": _financial_onec_documents(
                    in_documents, outside_documents
                ),
                "wbAmount": _json_number(wb_amount),
                "onecAmount": _json_number(onec_amount),
                "delta": _json_number(delta),
                "amountsComparable": amounts_comparable,
                "status": status,
                "comment": comment,
            }
        )
    return rows


def _financial_wb_documents(bucket: dict[str, Any] | None) -> str:
    if not bucket:
        return "Неделя WB вне выбранного периода"
    documents = sorted(str(item) for item in bucket.get("documents", set()) if item)
    if len(documents) > 4:
        hidden_count = len(documents) - 4
        documents = [*documents[:4], f"ещё {hidden_count}"]
    return "; ".join(documents) or "Свод прибылей и убытков за неделю WB"


def _financial_onec_documents(
    in_documents: list[dict[str, Any]], outside_documents: list[dict[str, Any]]
) -> str:
    labels = [document["label"] for document in in_documents]
    labels.extend(f"Вне периода: {document['label']}" for document in outside_documents)
    return "; ".join(labels) or "—"


def _financial_reconciliation_status(
    *,
    wb_present: bool,
    onec_documents: list[dict[str, Any]],
    outside_documents: list[dict[str, Any]],
    delta: Decimal | None,
    source_available: bool,
    amounts_comparable: bool = True,
) -> tuple[str, str]:
    if not source_available:
        return "Нет источника 1С", "Источник 1С не загружен; сумма не заменена нулем."
    if not wb_present and onec_documents:
        return (
            "Есть только в 1С периода",
            "Документ 1С входит в период, а связанная неделя WB начинается "
            "за его пределами.",
        )
    if wb_present and not onec_documents and outside_documents:
        dates = ", ".join(_ru_short_date(item["date"]) for item in outside_documents)
        return (
            "Документ 1С вне периода",
            f"Связанный документ 1С датирован {dates} и не включен в сумму периода.",
        )
    if wb_present and not onec_documents:
        return "Нет документа 1С", "Для недели WB не найден документ 1С."
    if not amounts_comparable:
        return (
            "Справочно",
            "WB показывает розничную сумму выкупа, а расходная накладная 1С "
            "— сумму нетто после удержаний. Эти суммы не образуют дельту; "
            "корректность выкупа проверяется по количеству ниже.",
        )
    if delta is not None and abs(delta) <= FINANCIAL_RECONCILIATION_TOLERANCE:
        return "Сходится", "Суммы сходятся в пределах допуска 1 ₽."
    return "Расхождение", "Проверьте состав, сумму и дату документов этой недели."


def _ru_short_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _document_reconciliation_period_condition(
    period_start: date | None,
    period_end: date | None,
) -> Any | None:
    if period_start is None and period_end is None:
        return None
    conditions = []
    closing_date = func.coalesce(
        ReportDocumentReconciliationRow.sales_period_end,
        ReportDocumentReconciliationRow.expected_document_date,
    )
    if period_start is not None:
        conditions.append(closing_date >= period_start)
    if period_end is not None:
        conditions.append(closing_date <= period_end)
    return and_(*conditions) if conditions else None


def _row_period_condition(
    report: ReportRun, period_start: date | None, period_end: date | None
) -> Any | None:
    if period_start is None and period_end is None:
        return None
    accounting_conditions = [ReportUnitRow.accounting_period_date.is_not(None)]
    if period_start:
        accounting_conditions.append(
            ReportUnitRow.accounting_period_date >= period_start
        )
    if period_end:
        accounting_conditions.append(ReportUnitRow.accounting_period_date <= period_end)
    week_conditions = [
        ReportUnitRow.accounting_period_date.is_(None),
        ReportUnitRow.week.is_not(None),
    ]
    if period_start:
        week_conditions.append(ReportUnitRow.week >= period_start - timedelta(days=6))
    if period_end:
        week_conditions.append(ReportUnitRow.week <= period_end - timedelta(days=6))
    row_date_conditions = [and_(*accounting_conditions), and_(*week_conditions)]
    iso_date_conditions = [
        ReportUnitRow.accounting_period_date.is_(None),
        ReportUnitRow.week.is_(None),
        ReportUnitRow.wb_report_date.like("____-__-__"),
    ]
    if period_start:
        iso_date_conditions.append(
            ReportUnitRow.wb_report_date >= period_start.isoformat()
        )
    if period_end:
        iso_date_conditions.append(
            ReportUnitRow.wb_report_date <= period_end.isoformat()
        )
    row_date_conditions.append(and_(*iso_date_conditions))
    month_condition = _row_period_month_condition(report, period_start, period_end)
    if month_condition is not None:
        row_date_conditions.append(
            and_(
                ReportUnitRow.accounting_period_date.is_(None),
                ReportUnitRow.week.is_(None),
                month_condition,
            )
        )
    return or_(*row_date_conditions)


def _month_filter_period(value: str) -> tuple[date, date] | None:
    normalized = value.replace("(неполный месяц)", "").strip().casefold()
    for month_number, month_name in RU_MONTH_NAMES.items():
        prefix = f"{month_name.casefold()} "
        if not normalized.startswith(prefix):
            continue
        try:
            year = int(normalized.removeprefix(prefix).strip())
            start = date(year, month_number, 1)
        except ValueError:
            return None
        if month_number == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month_number + 1, 1)
        return start, next_month - timedelta(days=1)
    return None


def _calendar_period_for_row_filters(
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
    month: str,
) -> tuple[date | None, date | None]:
    month_period = _month_filter_period(month) if month else None
    if month_period is not None:
        return month_period
    return period_start or report.period_start, period_end or report.period_end


def _row_period_month_condition(
    report: ReportRun, period_start: date | None, period_end: date | None
) -> Any | None:
    start = period_start or report.period_start
    end = period_end or report.period_end
    if start is None or end is None:
        return None
    if start > end:
        return None
    month_conditions = []
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while current <= last:
        label = f"{RU_MONTH_NAMES[current.month]} {current.year}"
        month_conditions.extend(
            [
                ReportUnitRow.month == label,
                ReportUnitRow.month.ilike(f"{label}%"),
            ]
        )
        year = current.year + (current.month // 12)
        month = current.month % 12 + 1
        current = date(year, month, 1)
    if not month_conditions:
        return None
    return or_(*month_conditions)


def find_sku(db: Session, report: ReportRun, sku: str) -> dict[str, Any] | None:
    like = f"%{sku}%"
    row = db.scalar(
        select(ReportUnitRow)
        .where(
            ReportUnitRow.report_run_id == report.id,
            or_(
                ReportUnitRow.nm_id == sku,
                ReportUnitRow.article_wb.ilike(like),
                ReportUnitRow.article_1c.ilike(like),
                ReportUnitRow.barcode.ilike(like),
                ReportUnitRow.product.ilike(like),
            ),
        )
        .order_by(ReportUnitRow.id)
    )
    return _row_payload(row) if row else None


def create_ai_thread(
    db: Session,
    *,
    user: User,
    tenant_id: str,
    client_id: str,
    report_id: str,
    title: str,
    scope: dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> AiThread:
    normalized_scope = scope or {}
    thread = AiThread(
        id=thread_id or new_id("thread"),
        tenant_id=tenant_id,
        client_id=client_id,
        user_id=user.id,
        report_run_id=report_id,
        title=title[:200],
        scope=normalized_scope,
        scope_hash=hashlib.sha256(
            json.dumps(
                normalized_scope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        created_at=security.utcnow(),
    )
    db.add(thread)
    audit(
        db,
        action="ai_thread_created",
        user=user,
        tenant_id=tenant_id,
        entity_type="ai_thread",
        entity_id=thread.id,
    )
    return thread


def list_ai_threads(
    db: Session,
    *,
    user: User,
    report_id: str,
    limit: int = 20,
) -> list[AiThread]:
    """Return the current user's active threads for one accessible report."""

    statement = (
        select(AiThread)
        .where(
            AiThread.user_id == user.id,
            AiThread.report_run_id == report_id,
            AiThread.tenant_id.in_(allowed_tenant_ids(user)),
            AiThread.archived_at.is_(None),
        )
        .order_by(AiThread.created_at.desc(), AiThread.id.desc())
        .limit(max(1, min(limit, 20)))
    )
    return list(db.scalars(statement))


def require_thread(db: Session, user: User, thread_id: str) -> AiThread:
    thread = db.get(AiThread, thread_id)
    if (
        thread is None
        or thread.tenant_id not in allowed_tenant_ids(user)
        or thread.user_id != user.id
        or thread.archived_at is not None
    ):
        raise PermissionError("thread access denied")
    return thread


def thread_messages(
    db: Session, thread: AiThread, *, limit: int | None = None
) -> list[AiMessage]:
    statement = (
        select(AiMessage)
        .where(AiMessage.thread_id == thread.id)
        .order_by(AiMessage.created_at.desc(), AiMessage.id.desc())
    )
    if limit is not None:
        statement = statement.limit(max(1, min(limit, 100)))
    messages = list(db.scalars(statement))
    messages.reverse()
    return messages


def add_ai_message(
    db: Session,
    *,
    thread: AiThread,
    role: str,
    content: str,
    chatkit_item_id: str = "",
    tool_name: str = "",
    citations: list[Any] | None = None,
) -> AiMessage:
    message = AiMessage(
        thread_id=thread.id,
        role=role,
        content=content,
        chatkit_item_id=chatkit_item_id,
        tool_name=tool_name,
        citations=citations or [],
        created_at=security.utcnow(),
    )
    db.add(message)
    return message


def add_ai_tool_call(
    db: Session,
    *,
    thread: AiThread,
    user: User,
    tool_name: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    status: str = "ok",
) -> None:
    db.add(
        AiToolCall(
            thread_id=thread.id,
            user_id=user.id,
            tool_name=tool_name,
            input_payload=input_payload,
            output_payload=output_payload,
            status=status,
            created_at=security.utcnow(),
        )
    )
    audit(
        db,
        action="ai_tool_called",
        user=user,
        tenant_id=thread.tenant_id,
        entity_type="ai_thread",
        entity_id=thread.id,
        payload={"tool": tool_name, "status": status},
    )


def add_ai_event(
    db: Session,
    *,
    thread: AiThread,
    user: User | None = None,
    event_type: str,
    title: str = "",
    message: str = "",
    status: str = "ok",
    tool_name: str = "",
    payload: dict[str, Any] | None = None,
    visibility: str = "client",
) -> AiEvent:
    event = AiEvent(
        thread_id=thread.id,
        user_id=user.id if user else None,
        event_type=event_type[:80],
        title=title[:240],
        message=message[:2000],
        status=status[:80],
        tool_name=tool_name[:120],
        visibility=visibility if visibility in {"client", "staff"} else "client",
        payload=payload or {},
        created_at=security.utcnow(),
    )
    db.add(event)
    return event


def thread_events(db: Session, user: User, thread: AiThread) -> list[dict[str, Any]]:
    staff = has_role(user, STAFF_ROLES, thread.tenant_id)
    statement = select(AiEvent).where(AiEvent.thread_id == thread.id)
    if not staff:
        statement = statement.where(AiEvent.visibility == "client")
    events = list(db.scalars(statement.order_by(AiEvent.created_at, AiEvent.id)))
    return [ai_event_payload(event, staff=staff) for event in events]


def ai_event_payload(event: AiEvent, *, staff: bool = False) -> dict[str, Any]:
    payload = event.payload or {}
    if not staff:
        payload = _client_safe_event_payload(payload)
    result = {
        "id": event.id,
        "type": event.event_type,
        "title": event.title,
        "message": event.message,
        "status": event.status,
        "toolName": event.tool_name if staff else _tool_label(event.tool_name),
        "payload": payload,
        "createdAt": event.created_at.isoformat(),
    }
    if staff:
        result["visibility"] = event.visibility
    return result


def _client_safe_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "summary",
        "evidence",
        "limitations",
        "lookup",
        "query",
        "status",
        "reviewStatus",
        "sourceType",
        "checkType",
        "message",
        "newReportRunId",
        "answerSource",
        "model",
        "toolNames",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _tool_label(tool_name: str) -> str:
    labels = {
        "get_report_summary": "Сводка KPI",
        "search_sku": "Поиск SKU",
        "get_loss_drivers": "Драйверы убыточности",
        "get_data_quality_issues": "Качество данных",
        "compare_periods": "Сравнение периодов",
        "draft_management_report": "Черновик отчета",
        "verify_onec_cost": "Проверка 1С",
        "verify_wb_card": "Проверка WB",
        "verify_wb_stock": "Остатки WB",
        "refresh_onec_and_rebuild_report": "Обновление 1С",
    }
    return labels.get(tool_name, tool_name)


def record_report_artifact(
    db: Session,
    report: ReportRun,
    *,
    artifact_type: str,
    path: str | Path,
    sha256: str,
    byte_size: int,
    status: str = "ready",
) -> ReportArtifact:
    resolved = str(Path(path).resolve())
    existing = db.scalar(
        select(ReportArtifact).where(
            ReportArtifact.report_run_id == report.id,
            ReportArtifact.artifact_type == artifact_type,
            ReportArtifact.path == resolved,
        )
    )
    if existing is None:
        existing = ReportArtifact(
            tenant_id=report.tenant_id,
            report_run_id=report.id,
            artifact_type=artifact_type,
            path=resolved,
            sha256=sha256,
            byte_size=byte_size,
            status=status,
            created_at=security.utcnow(),
        )
        db.add(existing)
    else:
        existing.sha256 = sha256
        existing.byte_size = byte_size
        existing.status = status
        existing.created_at = security.utcnow()
    if artifact_type == "excel" and status == "ready":
        report.source_workbook = Path(resolved).name
        report.source_workbook_path = resolved
    db.flush()
    return existing


def report_artifact_path(
    db: Session,
    report: ReportRun,
    artifact_type: str,
    allowed_root: Path,
) -> Path | None:
    artifact = db.scalar(
        select(ReportArtifact)
        .where(
            ReportArtifact.report_run_id == report.id,
            ReportArtifact.artifact_type == artifact_type,
            ReportArtifact.status == "ready",
        )
        .order_by(ReportArtifact.created_at.desc(), ReportArtifact.id.desc())
    )
    if artifact is None:
        return None
    return _safe_allowed_path(artifact.path, allowed_root)


def report_file_path(report: ReportRun, allowed_root: Path) -> Path | None:
    if not report.source_workbook_path:
        return None
    return _safe_allowed_path(report.source_workbook_path, allowed_root)


def _safe_allowed_path(value: str | Path, allowed_root: Path) -> Path | None:
    path = Path(value).resolve()
    allowed = allowed_root.resolve()
    if path == allowed or allowed in path.parents:
        return path
    return None


def report_freshness_payload(
    db: Session,
    report: ReportRun,
    *,
    include_staff_readiness: bool = False,
) -> dict[str, Any]:
    loads = _source_loads_for_report(db, report)
    tax_context = _report_tax_context_payload(db, report)
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in loads
    )
    stats = _report_row_stats(
        db,
        report,
        tax_context=tax_context,
        source_refresh_backed=source_refresh_backed,
    )
    row_count = int(stats["row_count"])
    generated_at = _as_aware(report.generated_at)
    age_hours = (security.utcnow() - generated_at).total_seconds() / 3600
    latest_refresh = latest_source_refresh_payload(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        include_sensitive=include_staff_readiness,
    )
    tax_profile_sync = tax_profile_sync_payload(
        db,
        report,
        tax_context=tax_context,
        include_staff_details=include_staff_readiness,
    )
    partial_months = [
        row["month"]
        for row in _summary_monthly_payload(db, report)
        if row.get("isPartial")
    ]
    warnings = [
        report.return_reason_limitation
        or "Причины возвратов не передаются текущими источниками.",
        "Упущенные продажи являются управленческой оценкой, не прогнозом.",
    ]
    if partial_months:
        warnings.insert(
            0,
            f"Неполный месяц ({', '.join(partial_months)}): "
            "его нельзя сравнивать как полный.",
        )
    return {
        "reportId": report.id,
        "tenantId": report.tenant_id,
        "clientId": report.client_id,
        "generatedAt": report.generated_at.isoformat(),
        "ageHours": round(max(age_hours, 0), 2),
        "period": f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}",
        "periodStatus": report.period_status,
        "methodologyVersion": report.methodology_version,
        "sourceWorkbook": report.source_workbook,
        "publicationStatus": report.publication_status,
        "isCurrent": report.is_current,
        "lineageType": report.lineage_type,
        "sourceSnapshotSetId": report.source_snapshot_set_id,
        "status": report.status,
        "rowCount": int(row_count),
        "readiness": report_readiness_payload(
            db,
            report,
            loads=loads,
            stats=stats,
            tax_context=tax_context,
            include_staff_checks=include_staff_readiness,
        ),
        "sourceLoads": [
            {
                "sourceType": item.source_type,
                "sourceLabel": item.source_label,
                "clientId": item.client_id,
                "wbCabinetId": item.wb_cabinet_id,
                "status": item.status,
                "rowCount": item.row_count,
                "snapshotHash": item.snapshot_hash,
                "sourceRefreshRunId": item.source_refresh_run_id,
                "required": item.required,
                "publicationRequired": item.publication_required,
                "coverageStart": (
                    item.coverage_start.isoformat() if item.coverage_start else None
                ),
                "coverageEnd": (
                    item.coverage_end.isoformat() if item.coverage_end else None
                ),
                "lineageRole": item.lineage_role,
                "loadedAt": item.loaded_at.isoformat(),
            }
            for item in loads
        ],
        "latestSourceRefresh": latest_refresh,
        "taxProfileSync": tax_profile_sync,
        "warnings": warnings,
    }


def audit_events_for_staff(
    db: Session, user: User, *, limit: int = 100
) -> list[dict[str, Any]]:
    require_staff(user)
    tenant_ids = allowed_tenant_ids(user)
    if not tenant_ids:
        return []
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id.in_(tenant_ids))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(max(1, min(limit, 500)))
        )
    )
    user_ids = {event.user_id for event in events if event.user_id}
    users_by_id = {}
    if user_ids:
        users_by_id = {
            item.id: item
            for item in db.scalars(select(User).where(User.id.in_(user_ids)))
        }
    return [
        {
            "id": event.id,
            "tenantId": event.tenant_id,
            "userId": event.user_id,
            "userEmail": users_by_id[event.user_id].email
            if event.user_id in users_by_id
            else "",
            "action": event.action,
            "entityType": event.entity_type,
            "entityId": event.entity_id,
            "payload": event.payload,
            "createdAt": event.created_at.isoformat(),
        }
        for event in events
    ]


def live_check_payload(
    db: Session,
    *,
    user: User,
    report: ReportRun,
    source_type: str,
    check_type: str,
    lookup_key: str,
    enabled: bool,
    cache_ttl_minutes: int,
) -> dict[str, Any]:
    normalized_lookup = lookup_key.strip()
    if not normalized_lookup:
        raise ValueError("lookup is required")
    cached = _latest_live_check_cache(db, report, check_type, normalized_lookup)
    if cached is not None:
        audit(
            db,
            action="live_check_cached",
            user=user,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={"check_type": check_type, "source_type": source_type},
        )
        result = dict(cached.payload)
        result["cached"] = True
        return result

    if enabled:
        status = "needs_configuration"
        message = (
            "Проверка без изменения данных разрешена, но рабочий коннектор ещё не "
            "подключен в этом контуре. Нужен отдельный smoke внешнего источника."
        )
    else:
        status = "disabled"
        message = (
            "Live checks сейчас выключены настройкой SHUMEYKO_LIVE_CHECKS_ENABLED. "
            "Расчет остается по сохраненному снимку, внешние системы не опрашивались."
        )
    result = {
        "status": status,
        "reviewStatus": "needs_review",
        "sourceType": source_type,
        "checkType": check_type,
        "lookup": normalized_lookup,
        "cached": False,
        "message": message,
        "limitations": [
            "Проверка выполняется строго без изменения данных.",
            "При ошибке источника значение не заменяется нулем.",
            "Все проверки подключений записываются в журнал и кешируются.",
        ],
    }
    now = security.utcnow()
    db.add(
        LiveCheckCache(
            tenant_id=report.tenant_id,
            report_run_id=report.id,
            source_type=source_type,
            check_type=check_type,
            lookup_key=normalized_lookup,
            status=status,
            payload=result,
            created_at=now,
            expires_at=now + timedelta(minutes=max(cache_ttl_minutes, 1)),
        )
    )
    audit(
        db,
        action="live_check_requested",
        user=user,
        tenant_id=report.tenant_id,
        entity_type="report_run",
        entity_id=report.id,
        payload={
            "check_type": check_type,
            "source_type": source_type,
            "status": status,
        },
    )
    return result


def _latest_live_check_cache(
    db: Session, report: ReportRun, check_type: str, lookup_key: str
) -> LiveCheckCache | None:
    return db.scalar(
        select(LiveCheckCache)
        .where(
            LiveCheckCache.tenant_id == report.tenant_id,
            LiveCheckCache.report_run_id == report.id,
            LiveCheckCache.check_type == check_type,
            LiveCheckCache.lookup_key == lookup_key,
            LiveCheckCache.expires_at > security.utcnow(),
        )
        .order_by(LiveCheckCache.created_at.desc(), LiveCheckCache.id.desc())
    )


def management_report_text(summary: dict[str, Any]) -> str:
    return management_report_summary_text(summary)


def management_report_summary_text(summary: dict[str, Any]) -> str:
    kpis = summary.get("kpis") or {}
    quality = summary.get("quality") or {}

    def money(value: Any) -> str:
        return "не рассчитано" if value is None else f"{float(value):,.0f} ₽"

    margin = kpis.get("margin")
    margin_text = "не рассчитано" if margin is None else f"{float(margin):.1%}"
    limitations = client_draft_limitations(summary)
    return (
        f"Период: {summary['meta']['period']}\n"
        f"Выручка после СПП: {money(kpis.get('revenue'))}\n"
        f"Прибыль до налогов: {money(kpis.get('profit'))}\n"
        f"Управленческая прибыль WB: {money(kpis.get('profitBeforeTax'))}\n"
        f"Маржинальность до налогов: {margin_text}\n"
        f"Убыточных строк: {int(kpis.get('lossRows') or 0)}\n"
        f"Строк в расчете: {int(kpis.get('rowCount') or 0)}\n"
        f"Качество данных: {json.dumps(quality, ensure_ascii=False)}\n"
        f"Ограничения: {'; '.join(limitations)}"
    )


def _next_client_draft_revision(db: Session, report: ReportRun) -> int:
    latest_revision = (
        db.scalar(
            select(func.max(AiClientDraft.revision)).where(
                AiClientDraft.tenant_id == report.tenant_id,
                AiClientDraft.report_run_id == report.id,
            )
        )
        or 0
    )
    return int(latest_revision) + 1


def _client_draft_payload(draft: AiClientDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "tenantId": draft.tenant_id,
        "reportId": draft.report_run_id,
        "threadId": draft.thread_id,
        "authorUserId": draft.author_user_id,
        "revision": draft.revision,
        "status": draft.status,
        "source": draft.source,
        "content": draft.content,
        "instruction": draft.instruction,
        "evidence": draft.evidence,
        "limitations": draft.limitations,
        "createdAt": draft.created_at.isoformat(),
        "updatedAt": draft.updated_at.isoformat(),
    }


def integration_provider_base(provider: str) -> str:
    return providers.provider_base(provider)


def integration_connection_key(provider: str) -> str:
    return providers.connection_key(provider)


def integration_is_primary_provider(provider: str) -> bool:
    return providers.is_primary_provider(provider)


def new_integration_provider_id(base_provider: str) -> str:
    _validate_integration_provider(base_provider)
    if not integration_is_primary_provider(base_provider):
        base_provider = integration_provider_base(base_provider)
    return f"{base_provider}:{uuid.uuid4().hex[:12]}"


def _validate_integration_provider(provider: str) -> None:
    providers.validate_provider(provider)


def _tenant_integration(
    db: Session, tenant_id: str, provider: str
) -> TenantIntegration | None:
    return db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == provider,
        )
    )


def _ensure_empty_integration(
    db: Session, tenant_id: str, provider: str
) -> TenantIntegration:
    integration = _tenant_integration(db, tenant_id, provider)
    if integration is not None:
        return integration
    now = security.utcnow()
    integration = TenantIntegration(
        tenant_id=tenant_id,
        provider=provider,
        label=providers.provider_label(provider),
        status="not_configured",
        secret_hash="",
        secret_hint="",
        config_payload={
            "storage": "hash_only",
            "readOnly": True,
            "providerBase": integration_provider_base(provider),
            "connectionKey": integration_connection_key(provider),
            "connectionRole": _normalize_integration_role(
                integration_provider_base(provider), ""
            ),
            "cabinetName": "",
            "organizationName": "",
            "isPrimary": integration_is_primary_provider(provider),
        },
        created_at=now,
        updated_at=now,
    )
    db.add(integration)
    db.flush()
    return integration


def _normalize_integration_role(provider_base: str, connection_role: str) -> str:
    return providers.normalize_role(provider_base, connection_role)


def _integration_payload_sort_key(payload: dict[str, Any]) -> tuple[int, int, str, str]:
    provider_base = str(payload.get("providerBase") or payload.get("provider") or "")
    base_order = (
        providers.PROVIDER_ORDER.index(provider_base)
        if provider_base in providers.PROVIDER_ORDER
        else len(providers.PROVIDER_ORDER)
    )
    primary_order = 0 if payload.get("isPrimary") else 1
    label = str(payload.get("label") or "")
    provider = str(payload.get("provider") or "")
    return (base_order, primary_order, label.lower(), provider)


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _secret_hint(secret: str) -> str:
    tail = secret[-4:] if len(secret) >= 4 else secret
    return f"***{tail}"


def _highest_role(roles: set[str]) -> str:
    for role in ("admin", "consultant", "client"):
        if role in roles:
            return role
    return ""


def _stable_entity_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _safe_identifier(value: str) -> str:
    candidate = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        return candidate
    return ""


def _stable_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9а-яё]+", "_", value.strip().lower())
    return normalized.strip("_")


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
