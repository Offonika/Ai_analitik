from __future__ import annotations

import csv
import hashlib
import re
import uuid
from calendar import monthrange
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any

from sqlalchemy import and_, case, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

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
    TaxProfile,
    VatDeductionMode,
    VatMode,
)
from wb_unit_economics.liquidity import (
    GROUP_FIELDS,
    aggregate_liquidity_rows,
    liquidity_rows_payload,
    liquidity_statuses,
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
    ConsultingFirm,
    DataRefreshJob,
    LiveCheckCache,
    Marketplace1cCurrentMapping,
    MarketplaceMappingItem,
    OnecMappingItem,
    OrganizationTaxProfile,
    OrganizationTaxProfileOverride,
    ReportArtifact,
    ReportDocumentReconciliationRow,
    ReportLostSalesRow,
    ReportReconciliationMonthly,
    ReportRun,
    ReportUnitRow,
    SessionToken,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
    Tenant,
    TenantIntegration,
    User,
    UserTenantAccess,
    WbCabinet,
)

VALID_ROLES = {"client", "consultant", "admin"}
DEFAULT_CONSULTING_FIRM_ID = "firm_shumeyko_partners"
DEFAULT_CONSULTING_FIRM_NAME = "Шумейко и Партнеры"
STAFF_ROLES = {"consultant", "admin"}
ACTIVE_REFRESH_STATUSES = {"queued", "running", "source_loaded", "rebuilding"}
ACTIVE_SOURCE_REFRESH_STATUSES = {"queued", "running", "source_loaded", "rebuilding"}
BLOCKED_SOURCE_REFRESH_STATUSES = {"blocked_active_refresh", "blocked_low_disk"}
READINESS_REVIEW_RATIO = 0.20
READINESS_REVIEW_MIN_ROWS = 3
REPORT_ROWS_MAX_LIMIT = 1000
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
OZON_MAPPING_CHECK_MAX_ROWS = 1000
OZON_ONEC_COUNTERPARTY_LABEL = "ООО Интернет Решения"
OZON_BUYOUT_REPORT_RE = re.compile(
    r"(?:отчет[а]?\s+о\s+выкуп(?:ленных\s+товаров|е)?|"
    r"выкупленных\s+товарах)[^\d№#]{0,80}[№#]?\s*([0-9][0-9\s-]{3,})",
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
    return company


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
    company.onec_organization_id = organization_id
    company.updated_at = security.utcnow()
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
        latest_profile_run_id = source_profiles[0].source_refresh_run_id
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
    overrides = list(
        db.scalars(
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
    )
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
    return TaxProfile(
        client_id=client_id,
        organization_id=item.organization_id,
        tax_system=item.tax_system,
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
    )


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
    db: Session, user: User, *, client_id: str | None = None
) -> list[ReportRun]:
    if client_id:
        return list_reports_for_client(db, user, client_id)
    tenant_ids = allowed_tenant_ids(user)
    if not tenant_ids:
        return []
    reports = list(
        db.scalars(
            select(ReportRun)
            .where(ReportRun.tenant_id.in_(tenant_ids))
            .order_by(ReportRun.is_current.desc(), ReportRun.generated_at.desc())
        )
    )
    return [report for report in reports if _report_visible_to_user(user, report)]


def list_reports_for_client(db: Session, user: User, client_id: str) -> list[ReportRun]:
    client = require_client_access(db, user, client_id)
    reports = list(
        db.scalars(
            select(ReportRun)
            .where(
                ReportRun.tenant_id == client.tenant_id,
                ReportRun.client_id == client.id,
            )
            .order_by(ReportRun.is_current.desc(), ReportRun.generated_at.desc())
        )
    )
    return [report for report in reports if _report_visible_to_user(user, report)]


def latest_report_for_user(
    db: Session, user: User, *, client_id: str | None = None
) -> ReportRun | None:
    if client_id:
        return latest_report_for_client(db, user, client_id)
    tenant_ids = allowed_tenant_ids(user)
    if not tenant_ids:
        return None
    current = db.scalar(
        select(ReportRun)
        .where(
            ReportRun.tenant_id.in_(tenant_ids),
            ReportRun.publication_status == "published",
            ReportRun.is_current.is_(True),
        )
        .order_by(ReportRun.generated_at.desc())
    )
    if current is not None:
        return current
    reports = list_reports_for_user(db, user)
    return reports[0] if reports else None


def latest_report_for_client(
    db: Session,
    user: User,
    client_id: str,
) -> ReportRun | None:
    client = require_client_access(db, user, client_id)
    current = db.scalar(
        select(ReportRun)
        .where(
            ReportRun.tenant_id == client.tenant_id,
            ReportRun.client_id == client.id,
            ReportRun.publication_status == "published",
            ReportRun.is_current.is_(True),
        )
        .order_by(ReportRun.generated_at.desc())
    )
    if current is not None:
        return current
    reports = list_reports_for_client(db, user, client_id)
    return reports[0] if reports else None


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
    mode: str,
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(
        SourceRefreshRun.tenant_id == tenant_id,
        SourceRefreshRun.mode == mode,
        SourceRefreshRun.status.in_(ACTIVE_SOURCE_REFRESH_STATUSES),
        SourceRefreshRun.finished_at.is_(None),
    )
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    return db.scalar(statement.order_by(SourceRefreshRun.created_at.desc()))


def active_conflicting_source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    mode: str,
) -> SourceRefreshRun | None:
    modes = {mode}
    if mode == "daily":
        modes.add("full")
    return db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.tenant_id == tenant_id,
            SourceRefreshRun.mode.in_(modes),
            SourceRefreshRun.status.in_(ACTIVE_SOURCE_REFRESH_STATUSES),
            SourceRefreshRun.finished_at.is_(None),
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )


def latest_source_refresh_run(
    db: Session,
    *,
    tenant_id: str,
    client_id: str | None = None,
    mode: str | None = None,
    include_dry_run: bool = True,
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(SourceRefreshRun.tenant_id == tenant_id)
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    if mode:
        statement = statement.where(SourceRefreshRun.mode == mode)
    if not include_dry_run:
        statement = statement.where(SourceRefreshRun.dry_run.is_(False))
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
    client_id: str | None = None,
    user: User | None = None,
    source_report: ReportRun | None = None,
    resumed_from_run: SourceRefreshRun | None = None,
    reason: str = "",
    enforce_active_check: bool = True,
) -> SourceRefreshRun:
    if user is not None:
        require_staff(user, tenant_id)
    existing = (
        active_conflicting_source_refresh_run(db, tenant_id=tenant_id, mode=mode)
        if enforce_active_check
        else None
    )
    if existing is not None:
        raise ValueError("source refresh already active for this tenant")
    now = security.utcnow()
    resolved_client_id = client_id or (
        source_report.client_id if source_report else client_id_for_tenant(tenant_id)
    )
    refresh_run = SourceRefreshRun(
        id=new_id("source_refresh"),
        tenant_id=tenant_id,
        client_id=resolved_client_id,
        requested_by_user_id=user.id if user else None,
        source_report_run_id=source_report.id if source_report else None,
        new_report_run_id=None,
        resumed_from_run_id=resumed_from_run.id if resumed_from_run else None,
        mode=mode,
        credential_source=credential_source,
        dry_run=dry_run,
        status="queued",
        reason=reason.strip()[:4000],
        snapshot_set_id=snapshot_set_id,
        period_start=period_start,
        period_end=period_end,
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
            "resumedFromRunId": resumed_from_run.id if resumed_from_run else None,
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
    if started_at is not None:
        refresh_run.started_at = started_at
    if finished_at is not None:
        refresh_run.finished_at = finished_at
    refresh_run.updated_at = security.utcnow()
    db.flush()
    return refresh_run


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
    organizations = {
        _safe_payload_text(row.row_payload or {}, "Ref_Key"): row
        for row in organization_rows
        if _safe_payload_text(row.row_payload or {}, "Ref_Key")
    }
    companies = list(
        db.scalars(
            select(ClientCompany)
            .where(
                ClientCompany.client_id == refresh_run.client_id,
                ClientCompany.status == "active",
            )
            .order_by(ClientCompany.id)
        )
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
    for company in companies:
        if company.onec_organization_id in organizations:
            linked_count += 1
            continue
        if company.source_key in organizations:
            company.onec_organization_id = company.source_key
            company.updated_at = security.utcnow()
            linked_count += 1
            auto_linked_count += 1
            audit(
                db,
                action="client_company_onec_organization_auto_linked",
                user=user,
                tenant_id=refresh_run.tenant_id,
                entity_type="client_company",
                entity_id=company.id,
                payload={
                    "organizationId": company.source_key,
                    "refreshRunId": refresh_run.id,
                    "method": "saved_ref_key",
                },
            )
            continue
        candidates = organization_name_index.get(
            _organization_match_key(company.display_name), []
        )
        if len(candidates) != 1:
            continue
        company.onec_organization_id = candidates[0]
        company.updated_at = security.utcnow()
        linked_count += 1
        auto_linked_count += 1
        audit(
            db,
            action="client_company_onec_organization_auto_linked",
            user=user,
            tenant_id=refresh_run.tenant_id,
            entity_type="client_company",
            entity_id=company.id,
            payload={
                "organizationId": candidates[0],
                "refreshRunId": refresh_run.id,
                "method": "unique_exact_normalized_name",
            },
        )
    _auto_link_single_ozon_cabinet(
        db,
        refresh_run=refresh_run,
        companies=companies,
        user=user,
    )
    notice_payloads = [row.row_payload or {} for row in notice_rows]
    source_profile_count = 0
    company_diagnostics: list[dict[str, Any]] = []
    for company in companies:
        organization_id = company.onec_organization_id
        organization_row = organizations.get(organization_id)
        diagnostic = tax_profile_source_diagnostic(
            organization_id,
            organization=(organization_row.row_payload or {})
            if organization_row is not None
            else None,
            special_tax_mode_rows=notice_payloads,
        )
        company_diagnostics.append(
            {
                "clientCompanyId": company.id,
                "companyLabel": company.display_name,
                "organizationId": organization_id,
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
        profiles = tax_profiles_from_account_org_mapping(
            refresh_run.client_id,
            [mapping],
            onec_organization_rows=[organization_row.row_payload or {}],
            special_tax_mode_rows=notice_payloads,
        )
        if not profiles:
            continue
        profile = profiles[0]
        source_hashes = [organization_row.raw_payload_hash]
        source_hashes.extend(
            row.raw_payload_hash
            for row in notice_rows
            if _safe_payload_text(row.row_payload or {}, "Организация_Key")
            == organization_id
        )
        source_snapshot_hash = hashlib.sha256(
            "|".join(sorted(source_hashes)).encode("utf-8")
        ).hexdigest()
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
                    vat_rate=profile.vat_rate,
                    vat_mode=profile.vat_mode.value,
                    vat_deduction_mode=profile.vat_deduction_mode.value,
                    revenue_tax_rate=profile.revenue_tax_rate,
                    income_tax_kind=profile.income_tax_kind,
                    valid_from=profile.valid_from,
                    valid_to=profile.valid_to,
                    source=profile.source,
                    source_refresh_run_id=refresh_run.id,
                    source_snapshot_hash=source_snapshot_hash,
                    methodology_version="ozon-tax-profile-v2",
                    status="active",
                    created_at=security.utcnow(),
                )
            )
        source_profile_count += 1
    db.flush()
    _effective_profiles, resolution = _source_refresh_tax_profile_resolution(
        db,
        refresh_run,
        companies=companies,
    )
    profile_count = int(resolution["profileCount"])
    missing_count = int(resolution["missingProfileCount"])
    unconfirmed_count = int(resolution["unconfirmedProfileCount"])
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
            "Справочник организаций загружен из 1С, но для части организаций "
            "OData не опубликовала полный налоговый профиль."
        )
    )
    digest = hashlib.sha256(
        (
            f"{refresh_run.id}:{source_profile_count}:{profile_count}:"
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
            "methodologyVersion": "ozon-tax-profile-v2",
            "companyCount": len(companies),
            "linkedCompanyCount": linked_count,
            "autoLinkedCompanyCount": auto_linked_count,
            "profileCount": profile_count,
            "sourceProfileCount": source_profile_count,
            "manualOverrideCount": resolution["manualOverrideCount"],
            "missingProfileCount": missing_count,
            "unconfirmedProfileCount": unconfirmed_count,
            "fallbackPolicy": "explicit_1c_then_audited_manual_override_then_missing",
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


def source_refresh_run_payload(
    refresh_run: SourceRefreshRun,
    *,
    include_sensitive: bool = True,
) -> dict[str, Any]:
    collections = [
        source_refresh_collection_payload(item, include_sensitive=include_sensitive)
        for item in sorted(
            refresh_run.collections,
            key=lambda value: (value.required is False, value.source_type, value.id),
        )
    ]
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
        "mode": refresh_run.mode,
        "credentialSource": refresh_run.credential_source if include_sensitive else "",
        "dryRun": refresh_run.dry_run,
        "status": refresh_run.status,
        "reason": refresh_run.reason if include_sensitive else "",
        "snapshotSetId": refresh_run.snapshot_set_id,
        "periodStart": refresh_run.period_start.isoformat(),
        "periodEnd": refresh_run.period_end.isoformat(),
        "rootDir": refresh_run.root_dir if include_sensitive else "",
        "workbookPath": refresh_run.workbook_path if include_sensitive else "",
        "errorMessage": (
            refresh_run.error_message
            if include_sensitive
            else _safe_source_refresh_message(refresh_run)
        ),
        "safeMessage": _safe_source_refresh_message(refresh_run),
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
    refresh_run = latest_source_refresh_run(
        db, tenant_id=tenant_id, client_id=client_id
    )
    if refresh_run is None:
        return None
    return source_refresh_run_payload(
        refresh_run,
        include_sensitive=include_sensitive,
    )


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
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


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
) -> dict[str, Any]:
    row_limit = max(1, min(int(limit), max(1, int(preview_max_rows))))
    wb_cabinet_id = wb_cabinet_id.strip()
    refresh_run = latest_source_refresh_run(
        db,
        tenant_id=tenant_id,
        client_id=client_id,
        mode="ozon-only",
        include_dry_run=False,
    )
    if refresh_run is None:
        return {
            "status": "not_started",
            "message": "Запустите Ozon + 1C, чтобы увидеть диагностику источников.",
            "latestRun": None,
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
    finance_snapshot_rows = list(
        db.scalars(
            _source_snapshot_rows_select(
                tenant_id=tenant_id,
                refresh_run=refresh_run,
                source_type=OZON_DIAGNOSTIC_FINANCE_SOURCE,
                wb_cabinet_id=wb_cabinet_id,
            )
            .order_by(SourceSnapshotRow.row_number.asc(), SourceSnapshotRow.id.asc())
            .limit(max(row_limit, OZON_PNL_MAX_SOURCE_ROWS))
        )
    )
    finance_rows = [
        _ozon_finance_preview_row(row) for row in finance_snapshot_rows[:row_limit]
    ]
    mutual_settlement_rows = list(
        db.scalars(
            _source_snapshot_rows_select(
                tenant_id=tenant_id,
                refresh_run=refresh_run,
                source_type=OZON_MUTUAL_SETTLEMENT_SOURCE,
                wb_cabinet_id=wb_cabinet_id,
            )
        )
    )
    mutual_settlement_pnl_rows = _ozon_rows_matching_period(
        mutual_settlement_rows,
        collections=collections,
        source_type=OZON_MUTUAL_SETTLEMENT_SOURCE,
        period_start=period_start,
        period_end=period_end,
    )
    realization_snapshot_rows = list(
        db.scalars(
            _source_snapshot_rows_select(
                tenant_id=tenant_id,
                refresh_run=refresh_run,
                source_type=OZON_REALIZATION_SOURCE,
                wb_cabinet_id=wb_cabinet_id,
            ).limit(OZON_PNL_MAX_SOURCE_ROWS)
        )
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
    ozon_buyout_rows = list(
        db.scalars(
            _source_snapshot_rows_select(
                tenant_id=tenant_id,
                refresh_run=refresh_run,
                source_type=OZON_BUYOUT_API_SOURCE,
                wb_cabinet_id=wb_cabinet_id,
            )
        )
    )
    ozon_mapping = _ozon_mapping_diagnostics_payload(
        db,
        tenant_id=tenant_id,
        refresh_run=refresh_run,
        limit=row_limit,
        wb_cabinet_id=wb_cabinet_id,
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
        "Legacy Ozon P&L сохранен только для технической диагностики; "
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
            sales_register_rows,
            period_start=month_start,
            period_end=month_end,
            organization_id=organization_id,
        )
        reference_unit_costs = _onec_previous_closed_month_costs(
            sales_register_rows,
            commissioner_rows=organization_commissioner_rows,
            before_month=month_start,
            organization_id=organization_id,
        )
        direct_1c_cost_control = _onec_direct_cost_control(
            sales_register_rows,
            period_start=month_start,
            period_end=month_end,
            organization_id=organization_id,
            counterparty_ids=ozon_counterparty_ids,
        )
        monthly_input_vat = _onec_sales_input_vat_index(
            sales_register_rows,
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
            preview_limit=OZON_PNL_MAX_SOURCE_ROWS,
            tax_profile=tax_profile,
            tax_profile_required=True,
            input_vat_by_item=monthly_input_vat,
            reference_unit_costs=reference_unit_costs,
            direct_1c_cost_control=direct_1c_cost_control,
        )
        monthly_mart["taxProfile"].update(tax_profile_status)
        monthly_mart["periodExpenseSource"] = monthly_expenses
        monthly_marts.append(monthly_mart)
    ozon_mart = combine_ozon_monthly_marts(
        monthly_marts,
        preview_limit=row_limit,
    )
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
        "latestRun": {
            "id": refresh_run.id,
            "status": refresh_run.status,
            "mode": refresh_run.mode,
            "snapshotSetId": refresh_run.snapshot_set_id,
            "periodStart": refresh_run.period_start.isoformat(),
            "periodEnd": refresh_run.period_end.isoformat(),
            "createdAt": refresh_run.created_at.isoformat(),
            "startedAt": refresh_run.started_at.isoformat()
            if refresh_run.started_at
            else None,
            "finishedAt": refresh_run.finished_at.isoformat()
            if refresh_run.finished_at
            else None,
            "safeMessage": _safe_source_refresh_message(refresh_run),
        },
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
        return rows
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
                "title": "Файл mapping",
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
                "detail": "В Ozon catalog нет ключа для автоматической проверки.",
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
                        "Себестоимость посчитана только по preview-части Ozon "
                        "realization; для финальной прибыли нужен полный расчет."
                        if has_partial_cogs
                        else (
                            "Проверьте mapping и себестоимость 1C по товарным строкам."
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
    if onec_ozon.get("status") != "loaded":
        return {
            "status": "missing",
            "message": "Нет 1C регистра продаж для сверки Ozon.",
        }
    register_amount = _decimal_from_payload_value(
        sales_register.get("amount")
    ) or Decimal("0")
    commissioner_amount = _decimal_from_payload_value(
        onec_ozon.get("netSalesAmount")
    ) or Decimal("0")
    buyout_summary = ozon_buyouts.get("summary") or {}
    buyout_amount = _decimal_from_payload_value(
        buyout_summary.get("ozonApiAmount")
    ) or Decimal("0")
    buyout_quantity = _decimal_from_payload_value(
        buyout_summary.get("ozonApiQuantity")
    ) or Decimal("0")
    ozon_total = commissioner_amount + buyout_amount
    delta = register_amount - ozon_total
    matched_buyouts = int(buyout_summary.get("foundInOzonApi") or 0)
    missing_buyouts = int(buyout_summary.get("missingInOzonApi") or 0)
    matched_without_number = int(buyout_summary.get("matchedByPeriodTotal") or 0)
    status = (
        "matched"
        if _decimal_close(delta, Decimal("0"), Decimal("0.01")) and not missing_buyouts
        else "review"
    )
    message = (
        "Ozon realization плюс Ozon buyout сходятся с 1C регистром продаж."
        if status == "matched"
        else "Ozon realization плюс Ozon buyout пока не сходятся с 1C."
    )
    return {
        "status": status,
        "message": message,
        "commissionerAmount": _json_number(commissioner_amount),
        "buyoutAmount": _json_number(buyout_amount),
        "ozonTotalAmount": _json_number(ozon_total),
        "onecSalesRegisterAmount": _json_number(register_amount),
        "deltaAmount": _json_number(delta),
        "buyoutQuantity": _json_number(buyout_quantity),
        "matchedBuyouts": matched_buyouts,
        "missingBuyouts": missing_buyouts,
        "matchedWithoutReportNumber": matched_without_number,
    }


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
            "Расходы Ozon взяты из Seller API cash-flow за выбранный период."
            if status == "loaded"
            else "Нет Ozon cash-flow расходов за выбранный период."
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
                    "это контроль взаиморасчетов, не дополнительный расход P&L."
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
                    "mutual settlement или отдельный отчет услуг Ozon."
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
            "label": "Контроль расходов Ozon detail ↔ mutual settlement",
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
        return "Проверить, можно ли получить SKU-detail расходы вместо fallback."
    if status == "sku_detail_above_period":
        return (
            "Проверить период mutual settlement и состав detail; отрицательный "
            "остаток не распределен."
        )
    if status == "sku_direct":
        return "Действие не требуется: SKU-detail покрывает расходы периода."
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
            "Проверить соседний месяц mutual settlement или отдельный отчет услуг Ozon."
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
                    "note": "Денежный cash-flow Ozon, справочно; не база P&L.",
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
            "по preview-части товарных строк Ozon."
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
    totals: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "direct_quantity": Decimal("0"),
            "direct_cost": Decimal("0"),
            "total_quantity": Decimal("0"),
            "total_cost": Decimal("0"),
        }
    )
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
            quantity = _payload_decimal(item, "Количество", "quantity", "qty")
            cost_keys = (
                ("СебестоимостьБезНДС", "cost_without_vat")
                if without_vat
                else ("Себестоимость", "cost", "cost_amount")
            )
            cost = _payload_decimal(item, *cost_keys)
            if quantity:
                totals[onec_item_id]["total_quantity"] += quantity
            if cost:
                totals[onec_item_id]["total_cost"] += cost
            if quantity and cost:
                totals[onec_item_id]["direct_quantity"] += quantity
                totals[onec_item_id]["direct_cost"] += cost
    result: dict[str, Decimal] = {}
    for onec_item_id, values in totals.items():
        direct_quantity = values["direct_quantity"]
        direct_cost = values["direct_cost"]
        if direct_quantity and direct_cost:
            result[onec_item_id] = direct_cost / direct_quantity
            continue
        total_quantity = values["total_quantity"]
        if total_quantity and values["total_cost"]:
            result[onec_item_id] = values["total_cost"] / total_quantity
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


def _onec_direct_cost_control(
    rows: list[SourceSnapshotRow],
    *,
    period_start: date,
    period_end: date,
    organization_id: str = "",
    counterparty_ids: tuple[str, ...] = (),
) -> dict[str, Decimal | None]:
    if not counterparty_ids:
        return {"quantity": None, "cogs": None}
    counterparties = set(counterparty_ids)
    quantity = Decimal("0")
    cogs = Decimal("0")
    matched = False
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
            if not _onec_payload_matches_period(
                item,
                period_start=period_start,
                period_end=period_end,
            ):
                continue
            counterparty_id = _safe_payload_text(
                item,
                "Контрагент_Key",
                "counterparty_id",
                "counterpartyId",
            )
            if counterparty_id not in counterparties:
                continue
            matched = True
            quantity += _payload_decimal(item, "Количество", "quantity", "qty")
            cogs += _payload_decimal(item, "Себестоимость", "cost", "cost_amount")
    return {
        "quantity": quantity if matched else None,
        "cogs": cogs if matched else None,
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
    if not matched_payloads:
        return _empty_ozon_onec_commissioner_payload()

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
        "salesRegister": sales_register,
    }


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
        payload["summary"]["ozonApiRows"] = len(ozon_buyout_rows)
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
            "ozonApiRows": len(ozon_buyout_rows),
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
    collection_id = str(getattr(row, "collection_id", "") or "")
    collection_period = periods.get((f"collection:{collection_id}", row.row_number))
    if collection_period is not None:
        return collection_period
    row_number_period = periods.get(("row_number", row.row_number))
    if row_number_period is not None:
        return row_number_period
    if page_index is None:
        return None
    return periods.get((seller_id, page_index)) or periods.get(
        (str(page_index), page_index)
    )


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
                    "Ozon catalog еще не загружался. Запустите Ozon + 1C после "
                    "добавления доступа «Товары и каталог» или full read-only."
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
                    "Не удалось загрузить Ozon catalog. Для проверки "
                    "сопоставления нужен доступ к товарам Ozon."
                ),
                "rowCount": product_collection.row_count,
            }
        )
        return payload

    product_rows = list(
        db.scalars(
            _source_snapshot_rows_select(
                tenant_id=tenant_id,
                refresh_run=refresh_run,
                source_type=OZON_DIAGNOSTIC_PRODUCT_SOURCE,
                wb_cabinet_id=wb_cabinet_id,
            )
            .order_by(SourceSnapshotRow.row_number.asc(), SourceSnapshotRow.id.asc())
            .limit(OZON_MAPPING_CHECK_MAX_ROWS)
        )
    )
    product_row_count = (
        len(product_rows) if wb_cabinet_id else product_collection.row_count
    )
    candidates = list(
        _iter_ozon_mapping_candidates(
            product_rows,
            max_rows=OZON_MAPPING_CHECK_MAX_ROWS,
        )
    )
    if not candidates:
        payload = _empty_ozon_mapping_payload(limit)
        payload.update(
            {
                "status": "not_ready",
                "message": "Ozon catalog загружен, но в нем нет товарных ключей.",
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
        "Ozon mapping проверен: все preview-строки нашли связь с 1С."
        if status == "ready"
        else (
            "Ozon mapping требует проверки: есть строки без связи или "
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
    max_rows: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        for payload in _iter_product_like_payloads(row.row_payload or {}):
            candidate = _ozon_mapping_candidate(row, payload)
            if candidate:
                candidates.append(candidate)
                if len(candidates) >= max_rows:
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
                "Артикул Seller",
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
        "Артикул Seller",
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
        return "Последний refresh обновил отчет."
    if (
        refresh_run.status in {"queued", "running", "source_loaded", "rebuilding"}
        and refresh_run.finished_at is None
    ):
        return "Refresh выполняется."
    if refresh_run.status == "source_loaded":
        return "Источники обновлены без публикации нового отчета."
    if refresh_run.status == "needs_configuration":
        return "Последний refresh не обновил отчет: нужно настроить источники."
    if refresh_run.status == "needs_review":
        return "Последний refresh требует проверки источников."
    if refresh_run.status == "blocked_active_refresh":
        return "Refresh не запущен: уже выполняется конфликтующий refresh."
    if refresh_run.status == "blocked_low_disk":
        return "Refresh не запущен: недостаточно свободного места для снапшота."
    if refresh_run.status == "failed":
        return (
            "Последний refresh не обновил отчет: "
            "один из обязательных источников не прошел проверку."
        )
    if refresh_run.status == "dry_run_ready":
        return "Проверка refresh прошла без публикации отчета."
    return "Последний refresh не обновил отчет."


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
    revenue = sum(float(row.get("revenue") or 0) for row in rows)
    profit = sum(float(row.get("profit") or 0) for row in rows)
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
            "margin": profit / revenue if revenue else None,
            "rows": len(rows),
            "lossRows": len(losses),
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
    return [
        "Июнь неполный, поэтому динамику июня нельзя читать как полный месяц.",
        summary["meta"].get("returnReasonLimitation")
        or "Причины возвратов не передаются текущими источниками.",
        "Упущенные продажи являются управленческой оценкой, не финальным прогнозом.",
        "AI не меняет данные WB/1C и не выполняет отправку клиенту.",
    ]


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
    return import_dashboard_payload(
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


def replace_source_loads_from_refresh(
    db: Session,
    report: ReportRun,
    refresh_run: SourceRefreshRun,
) -> None:
    if (
        refresh_run.tenant_id != report.tenant_id
        or refresh_run.client_id != report.client_id
    ):
        raise ValueError("source refresh does not belong to report client")
    db.execute(delete(SourceLoad).where(SourceLoad.report_run_id == report.id))
    for item in refresh_run.collections:
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
    previous_reports = list(
        db.scalars(
            select(ReportRun).where(
                ReportRun.tenant_id == report.tenant_id,
                ReportRun.client_id == report.client_id,
                ReportRun.id != report.id,
                ReportRun.is_current.is_(True),
            )
        )
    )
    for previous in previous_reports:
        previous.is_current = False
        if previous.publication_status == "published":
            previous.publication_status = "superseded"
    report.publication_status = "published"
    report.is_current = True
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


def _clear_report_payload(db: Session, report_id: str) -> None:
    for model in (
        ReportUnitRow,
        ReportLostSalesRow,
        ReportReconciliationMonthly,
        ReportDocumentReconciliationRow,
        ReportArtifact,
        SourceLoad,
        LiveCheckCache,
    ):
        db.execute(delete(model).where(model.report_run_id == report_id))


def _row_entity_ids(
    db: Session,
    report: ReportRun,
    item: dict[str, Any],
) -> dict[str, str]:
    client_id = as_text(item.get("clientId")) or report.client_id
    organization = as_text(item.get("organization"))
    cabinet_name = as_text(item.get("cabinet"))
    company_id = as_text(item.get("clientCompanyId"))
    if not company_id:
        company = ensure_client_company(
            db,
            tenant_id=report.tenant_id,
            client_id=client_id,
            display_name=organization,
        )
        company_id = company.id if company else ""
    wb_cabinet_id = as_text(item.get("wbCabinetId"))
    wb_cabinet_label = ""
    if not wb_cabinet_id:
        cabinet = _single_active_wb_provider_cabinet(
            db, client_id=client_id, client_company_id=company_id
        )
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
        vat_input_difference=decimal_value(item.get("vatInputDifference")),
        vat_input_completeness=as_text(item.get("vatInputCompleteness")),
        vat_payable=decimal_value(item.get("vatPayable")),
        revenue_without_vat=decimal_value(item.get("revenueWithoutVat")),
        cost=decimal_value(item.get("cost")),
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
        onec_source_rows=int_or_none(item.get("onecSourceRows")),
        comment=as_text(item.get("comment")),
    )


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
    document_reconciliation = list(
        db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(ReportDocumentReconciliationRow.report_run_id == report.id)
            .order_by(ReportDocumentReconciliationRow.id)
        )
    )
    loads = _source_loads_for_report(db, report)
    source_coverage = _source_coverage_for_report(db, report)
    unit_rows = [_row_payload(row) for row in rows]
    liquidity_rows = liquidity_rows_payload(aggregate_liquidity_rows(unit_rows))
    tax_context = _tax_context_payload(db, report, rows)
    tax_input_reconciliation_rows = _tax_input_reconciliation_payload_from_unit_rows(
        rows,
        tax_context=tax_context,
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
    return {
        "meta": _report_meta_payload(report, source_coverage),
        "readiness": report_readiness_payload(
            db,
            report,
            rows=rows,
            loads=loads,
            include_staff_checks=include_staff_readiness,
        ),
        "options": options_payload(
            unit_rows,
            liquidity_rows=liquidity_rows,
            document_reconciliation=document_reconciliation_rows,
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
        "lostSales": [_lost_payload(row) for row in lost],
        "lostSalesCoverage": lost_sales_coverage,
        "taxContext": tax_context,
        "reconciliation": [],
        "reconciliationMonthly": [
            _reconciliation_payload(row) for row in reconciliation
        ],
        "documentReconciliation": document_reconciliation_rows,
        "taxInputReconciliation": tax_input_reconciliation_rows,
        "latestSourceRefresh": latest_refresh,
    }


def report_summary_payload(
    db: Session,
    report: ReportRun,
    *,
    include_staff_readiness: bool = False,
) -> dict[str, Any]:
    loads = _source_loads_for_report(db, report)
    source_coverage = _source_coverage_for_report(db, report)
    stats = _report_row_stats(db, report)
    document_reconciliation_source_rows = _document_reconciliation_rows_for_report(
        db, report
    )
    document_reconciliation_rows = [
        _document_reconciliation_payload(row)
        for row in document_reconciliation_source_rows
    ]
    liquidity_rows = _summary_liquidity_rows(db, report)
    report_rows = list(
        db.scalars(
            select(ReportUnitRow)
            .where(ReportUnitRow.report_run_id == report.id)
            .order_by(ReportUnitRow.id)
        )
    )
    tax_context = _tax_context_payload(db, report, report_rows)
    lost_sales_coverage = _lost_sales_coverage_payload(db, report)
    tax_input_reconciliation_rows = _tax_input_reconciliation_payload_from_unit_rows(
        report_rows,
        tax_context=tax_context,
    )
    latest_refresh = _source_refresh_payload_for_report(
        db,
        report,
        include_sensitive=include_staff_readiness,
    )
    return {
        "meta": _report_meta_payload(report, source_coverage),
        "readiness": report_readiness_payload(
            db,
            report,
            loads=loads,
            include_staff_checks=include_staff_readiness,
        ),
        "options": _summary_options_payload(
            db,
            report,
            liquidity_rows=liquidity_rows,
            document_reconciliation=document_reconciliation_rows,
        ),
        "kpis": _summary_kpis_payload(
            {**stats, **_lost_sales_stats_for_report(db, report)},
            tax_context=tax_context,
            lost_sales_coverage=lost_sales_coverage,
        ),
        "quality": _summary_quality_payload(
            stats,
            loads,
            report,
            document_reconciliation_rows=document_reconciliation_source_rows,
        ),
        "monthly": _summary_monthly_payload(db, report),
        "expenses": _summary_expense_payload(db, report),
        "liquidityRows": liquidity_rows,
        "lostSales": _summary_lost_sales_payload(db, report),
        "lostSalesCoverage": lost_sales_coverage,
        "taxContext": tax_context,
        "reconciliation": [],
        "reconciliationMonthly": [
            _reconciliation_payload(row)
            for row in db.scalars(
                select(ReportReconciliationMonthly)
                .where(ReportReconciliationMonthly.report_run_id == report.id)
                .order_by(ReportReconciliationMonthly.id)
            )
        ],
        "documentReconciliation": document_reconciliation_rows,
        "taxInputReconciliation": tax_input_reconciliation_rows,
        "latestSourceRefresh": latest_refresh,
    }


def _report_meta_payload(
    report: ReportRun, source_coverage: tuple[date, date] | None
) -> dict[str, Any]:
    return {
        "clientId": report.client_id,
        "tenantId": report.tenant_id,
        "title": report.title,
        "client": report.client_name,
        "period": f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}",
        "reportPeriod": (
            f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}"
        ),
        "periodText": report.period_text,
        "periodStatus": report.period_status,
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
    include_staff_checks: bool = False,
) -> dict[str, Any]:
    source_loads = loads if loads is not None else _source_loads_for_report(db, report)
    source_coverage = _source_coverage_for_report(db, report)
    blocking_reasons: list[dict[str, Any]] = []
    review_reasons: list[dict[str, Any]] = []
    score = 100
    stats = _report_row_stats(db, report) if rows is None else None

    row_count = len(rows) if rows is not None else int(stats["row_count"])
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
                "В report run нет lineage по загрузкам источников.",
            )
        )
        score -= 20
    else:
        blocking_loads = [
            load
            for load in source_loads
            if (load.required or load.publication_required)
            and not _source_load_ok(load)
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
        incomplete_loads = [
            load
            for load in source_loads
            if load not in blocking_loads and not _source_load_ok(load)
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
        missing_cost_count = int(stats["missing_cost_rows"])
        mapping_count = int(stats["mapping_rows"])
        partial_count = int(stats["partial_rows"])
        problem_count = int(stats["problem_rows"])
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

    if missing_cost_count:
        review_reasons.append(
            _readiness_reason(
                "missing_cost",
                "Есть строки без подтвержденной себестоимости 1С.",
                missing_cost_count,
            )
        )
        score -= 15
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

    financial_blockers = _financial_integrity_blockers(
        db,
        report,
        source_loads=source_loads,
        missing_cost_count=missing_cost_count,
        mapping_count=mapping_count,
        document_reconciliation_issue_count=document_reconciliation_issue_count,
    )
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
        "month": _effective_row_month(row),
        "documentReport": _closing_date_label(
            row.document_report,
            row.week + timedelta(days=6) if row.week else None,
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
        "vatInputDifference": as_float(row.vat_input_difference),
        "vatInputCompleteness": row.vat_input_completeness,
        "vatPayable": as_float(row.vat_payable),
        "revenueWithoutVat": as_float(row.revenue_without_vat),
        "cost": as_float(row.cost),
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
    return _effective_month_label(row.week, row.month)


def _effective_month_label(week: date | None, stored_month: str) -> str:
    if week is None:
        return stored_month
    closing_date = week + timedelta(days=6)
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
        bucket["vatDeductionMode"] = deduction_status
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
    weeks = sorted(as_text(row.get("week")) for row in rows if row.get("week"))
    return {
        "months": months,
        "periodStart": weeks[0] if weeks else "",
        "periodEnd": weeks[-1] if weeks else "",
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


def _report_row_stats(db: Session, report: ReportRun) -> dict[str, Any]:
    return _row_stats_for_conditions(db, ReportUnitRow.report_run_id == report.id)


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


def _row_stats_for_conditions(db: Session, *conditions: Any) -> dict[str, Any]:
    row_count = _count_rows(db, *conditions)
    revenue = _sum_column(db, _pnl_revenue_expression(), *conditions)
    revenue_with_vat = _sum_column(db, ReportUnitRow.revenue, *conditions)
    profit = _sum_column(db, _pnl_profit_expression(), *conditions)
    profit_before_tax = _sum_column(db, ReportUnitRow.profit_before_tax, *conditions)
    sales = _sum_column(db, ReportUnitRow.sales, *conditions)
    returns = _sum_column(db, ReportUnitRow.returns, *conditions)
    return {
        "row_count": row_count,
        "revenue": revenue,
        "revenue_with_vat": revenue_with_vat,
        "pnl_without_vat_rows": _count_rows(
            db, *conditions, _pnl_without_vat_condition()
        ),
        "profit": profit,
        "profit_before_tax": profit_before_tax,
        "vat_output": _sum_column(db, ReportUnitRow.vat_output, *conditions),
        "vat_input": _sum_column(db, ReportUnitRow.vat_input, *conditions),
        "vat_payable": _sum_column(db, ReportUnitRow.vat_payable, *conditions),
        "income_tax": _sum_column(db, ReportUnitRow.income_tax, *conditions),
        "income_tax_included_rows": _count_rows(
            db, *conditions, ReportUnitRow.income_tax_included.is_(True)
        ),
        "sales": sales,
        "returns": returns,
        "loss_rows": _count_rows(
            db,
            *conditions,
            ReportUnitRow.profit < 0,
            ~_penalty_only_condition(),
        ),
        "penalty_only_rows": _count_rows(db, *conditions, _penalty_only_condition()),
        "ok_rows": _count_rows(db, *conditions, ReportUnitRow.status == "ОК"),
        "missing_cost_rows": _count_rows(
            db,
            *conditions,
            ReportUnitRow.status != "ОК",
            _missing_cost_condition(),
        ),
        "mapping_rows": _count_rows(
            db,
            *conditions,
            ReportUnitRow.status != "ОК",
            _quality_condition(
                "сопостав",
                "маппинг",
                "mapping",
                "ambiguous_mapping",
                "missing_mapping",
                "неоднознач",
            ),
        ),
        "partial_rows": _count_rows(
            db,
            *conditions,
            ReportUnitRow.status != "ОК",
            _quality_condition("partial_source", "неполный источник"),
        ),
        "problem_rows": _count_rows(db, *conditions, ReportUnitRow.status != "ОК"),
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


def _pnl_without_vat_condition() -> Any:
    return or_(
        ReportUnitRow.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
        ReportUnitRow.tax_method.ilike("%ОСНО%"),
    )


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


def _lost_sales_coverage_payload(db: Session, report: ReportRun) -> dict[str, Any]:
    total_days = (report.period_end - report.period_start).days + 1
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
            "coveredDays": 0,
            "totalDays": total_days,
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
        source_accounts = payload.get("accounts")
        if isinstance(source_accounts, list):
            for item in source_accounts:
                if isinstance(item, Mapping):
                    accounts.append(dict(item))
            continue
        accounts.append(
            {
                "sellerAccountId": payload.get("sellerAccountId") or "",
                "cabinet": payload.get("cabinet") or collection.source_label,
                "status": payload.get("status") or collection.status,
                "coveredDays": int(payload.get("coveredDays") or 0),
                "totalDays": int(payload.get("totalDays") or total_days),
                "calculated": bool(payload.get("calculated")),
            }
        )
    calculated = bool(accounts) and all(
        bool(item.get("calculated")) for item in accounts
    )
    covered_days = min(
        (int(item.get("coveredDays") or 0) for item in accounts),
        default=0,
    )
    statuses = {str(item.get("status") or "incomplete") for item in accounts}
    status = "complete" if calculated else "incomplete"
    if "missing_scope" in statuses or "access_error" in statuses:
        status = "missing_scope"
    return {
        "status": status,
        "calculated": calculated,
        "coveredDays": covered_days,
        "totalDays": total_days,
        "message": (
            "Покрытие истории остатков полное."
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
    missing_markers = ("не найден", "missing", "unknown", "не подтверж")
    sources = {
        str(row.tax_profile_source or "").strip()
        for row in report_rows
        if str(row.tax_profile_source or "").strip()
    }
    row_context_missing = not sources or any(
        any(marker in source.casefold() for marker in missing_markers)
        for source in sources
    )
    company_ids = {
        row.client_company_id for row in report_rows if row.client_company_id
    }
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
                "status": "ready" if company_ready else "unconfirmed",
                "periodStart": report.period_start.isoformat(),
                "periodEnd": report.period_end.isoformat(),
                "checks": checks,
            }
        )
    all_profiles_ready = bool(company_ids) and all(company_profiles_ready)
    calculated = bool(report_rows) and all_profiles_ready and not row_context_missing
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
            "message": "Налоговый профиль не подтверждён.",
            "profiles": profile_statuses,
        }
    tax_systems = {profile.tax_system for profile in profiles}
    vat_rates = {profile.vat_rate for profile in profiles}
    vat_modes = {profile.vat_mode.value for profile in profiles}
    deduction_modes = {profile.vat_deduction_mode.value for profile in profiles}
    revenue_rates = {profile.revenue_tax_rate for profile in profiles}
    income_tax_kinds = {profile.income_tax_kind for profile in profiles}
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
        "message": "Налоговый профиль подтверждён.",
        "profiles": profile_statuses,
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
        profile.vat_rate,
        profile.vat_mode.value,
        profile.vat_deduction_mode.value,
        profile.revenue_tax_rate,
        profile.income_tax_kind,
        profile.valid_from,
        profile.valid_to,
        profile.source,
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
            reason.like("%себестоим%"),
            and_(status == "себестоимость 1с требует сверки", reason == ""),
        ),
    )


def _summary_kpis_payload(
    stats: dict[str, Any],
    *,
    tax_context: Mapping[str, Any] | None = None,
    lost_sales_coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    revenue = float(stats["revenue"])
    revenue_with_vat = float(stats.get("revenue_with_vat", revenue))
    profit = float(stats["profit"])
    profit_management = float(stats.get("profit_before_tax", stats["profit"]))
    tax_calculated = bool((tax_context or {}).get("calculated"))
    lost_sales_calculated = bool((lost_sales_coverage or {}).get("calculated"))
    return {
        "revenue": revenue,
        "revenueWithoutVat": revenue,
        "revenueWithVat": revenue_with_vat,
        "pnlWithoutVat": int(stats.get("pnl_without_vat_rows") or 0) > 0,
        "profit": profit if tax_calculated else None,
        "profitBeforeTax": profit_management,
        "profitManagement": profit_management,
        "profitAfterIncomeTax": profit if tax_calculated else None,
        "incomeTaxIncluded": (
            int(stats.get("income_tax_included_rows") or 0) > 0
            if tax_calculated
            else False
        ),
        "incomeTax": float(stats.get("income_tax") or 0) if tax_calculated else None,
        "vatOutput": float(stats.get("vat_output") or 0) if tax_calculated else None,
        "vatInput": float(stats.get("vat_input") or 0) if tax_calculated else None,
        "vatPayable": float(stats.get("vat_payable") or 0) if tax_calculated else None,
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
    months = _ordered_values(_distinct_effective_months(db, report))
    weeks = _distinct_unit_values(db, report, ReportUnitRow.week, skip_empty=False)
    statuses = {
        *_distinct_unit_values(db, report, ReportUnitRow.status),
        *(
            as_text(row.get("status"))
            for row in document_reconciliation
            if row.get("status")
        ),
    }
    document_reports = {
        *_distinct_unit_values(db, report, ReportUnitRow.document_report),
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
        "months": months,
        "periodStart": min(weeks).isoformat() if weeks else "",
        "periodEnd": max(weeks).isoformat() if weeks else "",
        "cabinets": _distinct_entities(
            db, report, ReportUnitRow.wb_cabinet_id, ReportUnitRow.cabinet
        ),
        "organizations": _distinct_entities(
            db,
            report,
            ReportUnitRow.client_company_id,
            ReportUnitRow.organization,
        ),
        "schemes": _distinct_unit_values(db, report, ReportUnitRow.scheme),
        "statuses": sorted(status for status in statuses if status),
        "lossClasses": _distinct_unit_values(db, report, ReportUnitRow.loss_class),
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
        select(ReportUnitRow.week, ReportUnitRow.month)
        .where(ReportUnitRow.report_run_id == report.id)
        .distinct()
    )
    return sorted(
        {
            month
            for week, stored_month in rows
            if (month := _effective_month_label(week, stored_month))
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
            ReportUnitRow.month,
            func.coalesce(func.sum(ReportUnitRow.sales), 0),
            func.coalesce(func.sum(ReportUnitRow.returns), 0),
            func.coalesce(func.sum(_pnl_revenue_expression()), 0),
            func.coalesce(func.sum(_pnl_profit_expression()), 0),
        )
        .where(*conditions)
        .group_by(ReportUnitRow.week, ReportUnitRow.month)
    )
    buckets: dict[str, dict[str, Any]] = {}
    for week, stored_month, sales, returns, revenue, profit in rows:
        month = _effective_month_label(week, stored_month)
        if not month:
            continue
        month_start = (
            (week + timedelta(days=6)).replace(day=1)
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
    rows = list(
        db.execute(
            select(
                ReportUnitRow.pnl_vat_mode.label("pnlVatMode"),
                ReportUnitRow.tax_method.label("taxMethod"),
                ReportUnitRow.revenue.label("revenue"),
                ReportUnitRow.revenue_without_vat.label("revenueWithoutVat"),
                ReportUnitRow.profit_before_tax.label("profitBeforeTax"),
                ReportUnitRow.profit.label("profit"),
                ReportUnitRow.cost.label("cost"),
                ReportUnitRow.commission.label("commission"),
                ReportUnitRow.logistics.label("logistics"),
                ReportUnitRow.storage.label("storage"),
                ReportUnitRow.acceptance.label("acceptance"),
                ReportUnitRow.promotion.label("promotion"),
                ReportUnitRow.penalties.label("penalties"),
                ReportUnitRow.acquiring.label("acquiring"),
            ).where(*conditions)
        ).mappings()
    )
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


def _summary_liquidity_rows(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    return _liquidity_rows_for_conditions(db, ReportUnitRow.report_run_id == report.id)


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
        "onecExpenseInvoiceAmount": as_float(row.onec_expense_invoice_amount),
        "buyoutRetailDelta": as_float(row.buyout_retail_delta),
        "buyoutForPayDelta": as_float(row.buyout_for_pay_delta),
        "buyoutBankDelta": as_float(row.buyout_bank_delta),
        "pdfBankPayment": as_float(row.pdf_bank_payment),
        "wbForPaySum": as_float(row.wb_for_pay_sum),
        "onecSettlementTotal": as_float(row.onec_settlement_total),
        "settlementDelta": as_float(row.settlement_delta),
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
    return any(
        abs(_decimal_as_float(getattr(row, field))) > 0.000001
        for field in DOCUMENT_RECONCILIATION_DELTA_FIELDS
    )


def _document_reconciliation_missing_onec(
    row: ReportDocumentReconciliationRow,
) -> bool:
    return not as_text(row.onec_documents)


def _document_reconciliation_has_issue(
    row: ReportDocumentReconciliationRow,
) -> bool:
    status = as_text(row.status).lower()
    period_status = as_text(row.period_status).lower()
    return any(
        (
            status != "ok",
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
    amount_delta = sum(_decimal_as_float(row.amount_delta) for row in rows)
    return {
        "documentCount": len(rows),
        "okRows": len(ok_rows),
        "issueRows": len(issue_rows),
        "quantityDelta": quantity_delta,
        "amountDelta": amount_delta,
        "missingOnecRows": len(missing_onec),
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
    if period_start is not None:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.sales_period_end.is_(None),
                ReportDocumentReconciliationRow.sales_period_end >= period_start,
            )
        )
    if period_end is not None:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.sales_period_start.is_(None),
                ReportDocumentReconciliationRow.sales_period_start <= period_end,
            )
        )
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
    return list(
        db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(ReportDocumentReconciliationRow.report_run_id == report.id)
            .order_by(ReportDocumentReconciliationRow.id)
        )
    )


def _source_loads_for_report(db: Session, report: ReportRun) -> list[SourceLoad]:
    return list(
        db.scalars(
            select(SourceLoad)
            .where(SourceLoad.report_run_id == report.id)
            .order_by(SourceLoad.loaded_at.desc())
        )
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
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if count is not None:
        payload["count"] = int(count)
    return payload


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
        "source_loads_missing": "Проверить lineage загрузок перед отправкой.",
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
        "pnl_method_mismatch": "Пересчитать P&L по единой методике ОСНО без НДС.",
        "profit_semantics_mismatch": (
            "Устранить расхождение profit и profitBeforeTax до НДФЛ."
        ),
        "vat_input_unconfirmed": "Подтвердить входящий НДС документами 1С.",
        "cogs_reconciliation_failed": (
            "Закрыть себестоимость без НДС и сопоставление WB-1С."
        ),
        "source_lineage_failed": "Повторить обязательные загрузки источников.",
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


def _report_tax_profile_publication_context(
    db: Session,
    report: ReportRun,
    *,
    source_loads: list[SourceLoad],
) -> tuple[int, set[str]]:
    report_condition = ReportUnitRow.report_run_id == report.id
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in source_loads
    )
    source_text = func.lower(
        func.trim(func.coalesce(ReportUnitRow.tax_profile_source, ""))
    )
    explicit_missing = or_(
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
        explicit_missing = or_(explicit_missing, source_text == "")
    explicit_issue_count = _count_rows(db, report_condition, explicit_missing)
    if not source_refresh_backed and not explicit_issue_count:
        return 0, set()

    company_ids = set(
        db.scalars(
            select(ReportUnitRow.client_company_id)
            .where(
                report_condition,
                ReportUnitRow.client_company_id != "",
            )
            .distinct()
        )
    )
    company_issue_count = 0
    osno_company_ids: set[str] = set()
    for company_id in sorted(company_ids):
        company = db.get(ClientCompany, company_id)
        profiles, _checks, ready = _company_tax_profiles_for_period(
            db,
            company=company,
            period_start=report.period_start,
            period_end=report.period_end,
        )
        if not ready:
            company_issue_count += 1
            continue
        profile_is_osno = {tax_profile_is_osno(profile) for profile in profiles}
        if len(profile_is_osno) != 1:
            company_issue_count += 1
            continue
        if profile_is_osno == {True}:
            osno_company_ids.add(company_id)
    if source_refresh_backed and not company_ids:
        company_issue_count = max(company_issue_count, 1)
    return max(explicit_issue_count, company_issue_count), osno_company_ids


def _financial_integrity_blockers(
    db: Session,
    report: ReportRun,
    *,
    source_loads: list[SourceLoad],
    missing_cost_count: int,
    mapping_count: int,
    document_reconciliation_issue_count: int,
) -> list[dict[str, Any]]:
    report_condition = ReportUnitRow.report_run_id == report.id
    tax_profile_issue_count, osno_company_ids = _report_tax_profile_publication_context(
        db,
        report,
        source_loads=source_loads,
    )
    osno_markers: list[Any] = [
        ReportUnitRow.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
        ReportUnitRow.tax_method.ilike("%ОСНО%"),
    ]
    if osno_company_ids:
        osno_markers.append(ReportUnitRow.client_company_id.in_(osno_company_ids))
    osno_condition = and_(report_condition, or_(*osno_markers))
    osno_rows = _count_rows(db, osno_condition)
    source_refresh_backed = bool(report.source_snapshot_set_id) or any(
        bool(load.source_refresh_run_id) for load in source_loads
    )

    blockers: list[dict[str, Any]] = []
    if tax_profile_issue_count:
        blockers.append(
            _readiness_reason(
                "tax_profile_unconfirmed",
                ("Налоговый профиль не подтвержден для всех организаций и дат отчета."),
                tax_profile_issue_count,
            )
        )

    if osno_rows:
        method_mismatch = _count_rows(
            db,
            osno_condition,
            ReportUnitRow.pnl_vat_mode != PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
        )
        if method_mismatch:
            blockers.append(
                _readiness_reason(
                    "pnl_method_mismatch",
                    "Смешаны несовместимые методы прибыли и НДС.",
                    method_mismatch,
                )
            )

        profit_mismatch = _count_rows(
            db,
            osno_condition,
            ReportUnitRow.income_tax_included.is_(False),
            func.abs(ReportUnitRow.profit - ReportUnitRow.profit_before_tax) > 1,
        )
        if profit_mismatch:
            blockers.append(
                _readiness_reason(
                    "profit_semantics_mismatch",
                    "Прибыль до НДФЛ расходится между полями profit и profitBeforeTax.",
                    profit_mismatch,
                )
            )

        vat_unconfirmed = _count_rows(
            db,
            osno_condition,
            func.lower(func.coalesce(ReportUnitRow.vat_input_completeness, ""))
            != "confirmed",
        )
        if vat_unconfirmed:
            blockers.append(
                _readiness_reason(
                    "vat_input_unconfirmed",
                    "Входящий НДС не подтвержден независимым источником 1С.",
                    vat_unconfirmed,
                )
            )

    if source_refresh_backed and (missing_cost_count or mapping_count):
        blockers.append(
            _readiness_reason(
                "cogs_reconciliation_failed",
                "Себестоимость без НДС или сопоставление WB-1С не закрыты.",
                missing_cost_count + mapping_count,
            )
        )

    required_bad_loads = [
        load
        for load in source_loads
        if (load.required or load.publication_required)
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
                "Обязательный нижележащий источник не прошел загрузку.",
                len(required_bad_loads),
            )
        )

    sales = _sum_column(db, ReportUnitRow.sales, report_condition)
    storage_and_acceptance = _sum_column(
        db,
        ReportUnitRow.storage + ReportUnitRow.acceptance,
        report_condition,
    )
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
        blockers.append(
            _readiness_reason(
                "monthly_reconciliation_unresolved",
                "Независимая месячная сверка WB-1С не закрыта.",
                monthly_reconciliation_issues,
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
    lost_sales_conditions: list[Any],
    document_reconciliation_conditions: list[Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    document_reconciliation_rows = _document_reconciliation_rows_for_conditions(
        db, *document_reconciliation_conditions
    )
    filtered_rows = list(db.scalars(select(ReportUnitRow).where(*unit_conditions)))
    tax_context = _tax_context_payload(db, report, filtered_rows)
    lost_sales_coverage = _lost_sales_coverage_payload(db, report)
    return {
        "kpis": _summary_kpis_payload(
            stats,
            tax_context=tax_context,
            lost_sales_coverage=lost_sales_coverage,
        ),
        "quality": _summary_quality_payload(
            stats,
            _source_loads_for_report(db, report),
            report,
            document_reconciliation_rows=document_reconciliation_rows,
        ),
        "monthly": _monthly_payload_for_conditions(db, *unit_conditions, report=report),
        "expenses": _expense_payload_for_conditions(db, *unit_conditions),
        "liquidityRows": _liquidity_rows_for_conditions(db, *unit_conditions),
        "lostSales": _lost_sales_payload_for_conditions(db, *lost_sales_conditions),
        "lostSalesCoverage": lost_sales_coverage,
        "taxContext": tax_context,
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
        conditions.append(ReportUnitRow.status.ilike("%себестоим%"))
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
    rows = list(
        db.scalars(
            statement.order_by(ReportUnitRow.profit.asc()).offset(offset).limit(limit)
        )
    )
    stats = _row_stats_for_conditions(db, *conditions)
    lost_sales_conditions = _lost_sales_conditions_for_report(
        report,
        query=query,
        cabinet=cabinet,
        wb_cabinet_id=wb_cabinet_id,
    )
    stats.update(
        _lost_sales_stats_for_conditions(
            db,
            *lost_sales_conditions,
        )
    )
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
    analytics = _filtered_report_analytics_payload(
        db,
        report,
        unit_conditions=conditions,
        lost_sales_conditions=lost_sales_conditions,
        document_reconciliation_conditions=document_reconciliation_conditions,
        stats=stats,
    )
    return {
        "items": [_row_payload(row) for row in rows],
        "total": total,
        "kpis": _summary_kpis_payload(stats),
        "analytics": analytics,
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
    if delta_only:
        rows = [row for row in rows if _document_reconciliation_has_issue(row)]
    page_rows = rows[offset : offset + limit]
    return {
        "items": [_document_reconciliation_payload(row) for row in page_rows],
        "total": len(rows),
        "kpis": _document_reconciliation_kpis(rows),
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
    delta_only: bool = False,
) -> dict[str, Any]:
    """Reconcile cabinet P&L totals with persisted 1C document facts.

    The cabinet side assigns a weekly WB row by its closing Sunday
    (``week + 6 days``). The 1C side follows the actual register/invoice date.
    Keeping those bases explicit makes residual document differences visible
    without moving a cross-month week by its Monday start.
    """

    selected_start = period_start or report.period_start
    selected_end = period_end or report.period_end
    if selected_start and selected_end and selected_start > selected_end:
        selected_start, selected_end = selected_end, selected_start

    unit_rows = list(
        db.scalars(
            select(ReportUnitRow).where(ReportUnitRow.report_run_id == report.id)
        )
    )
    document_rows = list(
        db.scalars(
            select(ReportDocumentReconciliationRow).where(
                ReportDocumentReconciliationRow.report_run_id == report.id
            )
        )
    )
    refresh_run = _latest_financial_onec_refresh_run(db, report)
    source_rows = _financial_onec_source_rows(db, report, refresh_run)
    source_statuses = _financial_onec_source_statuses(db, refresh_run)
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
    onec_revenue, onec_revenue_total = _onec_revenue_document_buckets(
        source_rows,
        period_start=selected_start,
        period_end=selected_end,
    )
    wb_penalties, wb_penalties_total = _wb_penalty_document_buckets(
        unit_rows,
        period_start=selected_start,
        period_end=selected_end,
    )
    onec_penalties, onec_penalties_total = _onec_penalty_document_buckets(
        source_rows.get("onec_incoming_invoices", []),
        period_start=selected_start,
        period_end=selected_end,
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
        rows = [row for row in rows if row["status"] != "Сходится"]

    rows.sort(
        key=lambda row: (
            0 if row["controlType"] == "revenue_with_vat" else 1,
            row.get("periodStart") or "",
            row.get("documentType") or "",
        )
    )
    revenue_onec = onec_revenue_total if sales_available else None
    penalties_onec = onec_penalties_total if penalties_available else None
    return {
        "items": rows,
        "total": len(rows),
        "period": {
            "start": selected_start.isoformat() if selected_start else "",
            "end": selected_end.isoformat() if selected_end else "",
            "wbBasis": "week_end",
            "onecBasis": "actual_document_date",
        },
        "kpis": {
            "revenueWb": _json_number(wb_revenue_total),
            "revenueOnec": _json_number(revenue_onec),
            "revenueDelta": _json_number(
                revenue_onec - wb_revenue_total if revenue_onec is not None else None
            ),
            "penaltiesWb": _json_number(wb_penalties_total),
            "penaltiesOnec": _json_number(penalties_onec),
            "penaltiesDelta": _json_number(
                penalties_onec - wb_penalties_total
                if penalties_onec is not None
                else None
            ),
            "issueRows": sum(row["status"] != "Сходится" for row in rows),
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
    total = sum(
        (
            row.revenue or Decimal("0")
            for row in unit_rows
            if _date_in_period(
                row.week + timedelta(days=6) if row.week else None,
                period_start=period_start,
                period_end=period_end,
            )
        ),
        Decimal("0"),
    )
    return buckets, total


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
            if _date_in_period(
                actual_date, period_start=period_start, period_end=period_end
            ):
                total += amount

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
            actual_date, period_start=period_start, period_end=period_end
        ):
            bucket["amount"] += document["amount"]
            bucket["documents"].append(entry)
        else:
            bucket["outsideDocuments"].append(entry)
    return buckets, total


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
            week + timedelta(days=6),
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
) -> tuple[dict[tuple[date, str], dict[str, Any]], Decimal]:
    buckets: dict[tuple[date, str], dict[str, Any]] = {}
    total = Decimal("0")
    for row in rows:
        payload = row.row_payload or {}
        if payload.get("DeletionMark") is True or payload.get("Posted") is False:
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
        delta = onec_amount - wb_amount if onec_amount is not None else None
        status, comment = _financial_reconciliation_status(
            wb_present=wb is not None,
            onec_documents=in_documents,
            outside_documents=outside_documents,
            delta=delta,
            source_available=source_available,
        )
        rows.append(
            {
                "controlType": control_type,
                "controlLabel": FINANCIAL_RECONCILIATION_TYPES[control_type],
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
    return "; ".join(documents) or "Агрегат P&L по неделе WB"


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
    if period_start is not None:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.sales_period_end >= period_start,
                ReportDocumentReconciliationRow.expected_document_date >= period_start,
            )
        )
    if period_end is not None:
        conditions.append(
            or_(
                ReportDocumentReconciliationRow.sales_period_start <= period_end,
                ReportDocumentReconciliationRow.expected_document_date <= period_end,
            )
        )
    return and_(*conditions) if conditions else None


def _row_period_condition(
    report: ReportRun, period_start: date | None, period_end: date | None
) -> Any | None:
    if period_start is None and period_end is None:
        return None
    week_conditions = [ReportUnitRow.week.is_not(None)]
    if period_start:
        week_conditions.append(ReportUnitRow.week >= period_start - timedelta(days=6))
    if period_end:
        week_conditions.append(ReportUnitRow.week <= period_end - timedelta(days=6))
    row_date_conditions = [and_(*week_conditions)]
    iso_date_conditions = [
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
        row_date_conditions.append(and_(ReportUnitRow.week.is_(None), month_condition))
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
    report_id: str | None,
    title: str,
) -> AiThread:
    thread = AiThread(
        id=new_id("thread"),
        tenant_id=tenant_id,
        user_id=user.id,
        report_run_id=report_id,
        title=title[:200],
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


def require_thread(db: Session, user: User, thread_id: str) -> AiThread:
    thread = db.get(AiThread, thread_id)
    if thread is None or thread.tenant_id not in allowed_tenant_ids(user):
        raise PermissionError("thread access denied")
    return thread


def thread_messages(db: Session, thread: AiThread) -> list[AiMessage]:
    return list(
        db.scalars(
            select(AiMessage)
            .where(AiMessage.thread_id == thread.id)
            .order_by(AiMessage.created_at, AiMessage.id)
        )
    )


def add_ai_message(
    db: Session,
    *,
    thread: AiThread,
    role: str,
    content: str,
    tool_name: str = "",
    citations: list[Any] | None = None,
) -> AiMessage:
    message = AiMessage(
        thread_id=thread.id,
        role=role,
        content=content,
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
    row_count = (
        db.scalar(
            select(func.count())
            .select_from(ReportUnitRow)
            .where(ReportUnitRow.report_run_id == report.id)
        )
        or 0
    )
    loads = _source_loads_for_report(db, report)
    generated_at = _as_aware(report.generated_at)
    age_hours = (security.utcnow() - generated_at).total_seconds() / 3600
    latest_refresh = latest_source_refresh_payload(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        include_sensitive=include_staff_readiness,
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
                "loadedAt": item.loaded_at.isoformat(),
            }
            for item in loads
        ],
        "latestSourceRefresh": latest_refresh,
        "warnings": [
            "Июнь неполный: динамику июня нельзя читать как полный месяц.",
            report.return_reason_limitation
            or "Причины возвратов не передаются текущими источниками.",
            "Упущенные продажи являются управленческой оценкой, не прогнозом.",
        ],
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
            "Read-only live check разрешен, но production-коннектор еще не "
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
            "Проверка строго read-only.",
            "При ошибке источника значение не заменяется нулем.",
            "Все live checks пишутся в audit и кешируются.",
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
    rows = summary["unitRows"]
    totals = defaultdict(float)
    for row in rows:
        totals["revenue"] += float(row.get("revenue") or 0)
        totals["profit"] += float(row.get("profit") or 0)
        totals["losses"] += 1 if float(row.get("profit") or 0) < 0 else 0
        totals["review"] += 1 if row.get("status") != "ОК" else 0
    margin = totals["profit"] / totals["revenue"] if totals["revenue"] else 0
    return (
        f"Период: {summary['meta']['period']}\n"
        f"Выручка после СПП: {totals['revenue']:,.0f} ₽\n"
        f"Управленческая прибыль WB: {totals['profit']:,.0f} ₽\n"
        f"Маржа: {margin:.1%}\n"
        f"Убыточных строк: {int(totals['losses'])}\n"
        f"Строк требуют проверки данных: {int(totals['review'])}\n"
        "Ограничения: июнь неполный; причины возвратов не передаются текущими "
        "источниками; упущенные продажи являются управленческой оценкой."
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
