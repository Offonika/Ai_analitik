from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from wb_unit_economics.liquidity import (
    GROUP_FIELDS,
    aggregate_liquidity_rows,
    liquidity_rows_payload,
    liquidity_statuses,
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

MONTH_ORDER = [
    "Март 2026",
    "Апрель 2026",
    "Май 2026",
    "Июнь 2026 (неполный месяц)",
]


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
        clients.append(
            ensure_client_for_tenant(db, tenant_id=tenant.id, name=tenant.name)
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
    }


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
        cabinet_label = (cabinet_name or label).strip()
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
        }
    config_payload = integration.config_payload or {}
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
    return list(
        db.scalars(
            select(ReportRun)
            .where(ReportRun.tenant_id.in_(tenant_ids))
            .order_by(ReportRun.is_current.desc(), ReportRun.generated_at.desc())
        )
    )


def list_reports_for_client(db: Session, user: User, client_id: str) -> list[ReportRun]:
    client = require_client_access(db, user, client_id)
    return list(
        db.scalars(
            select(ReportRun)
            .where(
                ReportRun.tenant_id == client.tenant_id,
                ReportRun.client_id == client.id,
            )
            .order_by(ReportRun.is_current.desc(), ReportRun.generated_at.desc())
        )
    )


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
    if report is None or report.tenant_id not in allowed_tenant_ids(user):
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
    ):
        raise PermissionError("report access denied")
    return report


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
    return db.scalar(
        statement.order_by(SourceRefreshRun.created_at.desc())
    )


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
) -> SourceRefreshRun | None:
    statement = select(SourceRefreshRun).where(SourceRefreshRun.tenant_id == tenant_id)
    if client_id:
        statement = statement.where(SourceRefreshRun.client_id == client_id)
    return db.scalar(
        statement.order_by(SourceRefreshRun.created_at.desc())
    )


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
            SourceSnapshotRow.raw_payload_hash == raw_payload_hash,
        )
    )
    if existing is not None:
        return existing
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
        db.add(
            _unit_row(
                report.id,
                item,
                client_id=ids["client_id"],
                client_company_id=ids["client_company_id"],
                wb_cabinet_id=ids["wb_cabinet_id"],
            )
        )
    for item in payload.get("lostSales", []):
        ids = _row_entity_ids(db, report, item)
        db.add(
            _lost_sales_row(
                report.id,
                item,
                client_id=ids["client_id"],
                wb_cabinet_id=ids["wb_cabinet_id"],
            )
        )
    for item in payload.get("reconciliationMonthly", []):
        db.add(_reconciliation_row(report.id, item))
    for item in payload.get("documentReconciliation", []):
        ids = _row_entity_ids(db, report, item)
        db.add(
            _document_reconciliation_row(
                report.id,
                item,
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


def publish_report(db: Session, report: ReportRun) -> ReportRun:
    db.flush()
    db.execute(
        update(ReportRun)
        .where(
            ReportRun.tenant_id == report.tenant_id,
            ReportRun.client_id == report.client_id,
            ReportRun.id != report.id,
        )
        .values(is_current=False)
    )
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
    if not wb_cabinet_id:
        cabinet = ensure_wb_cabinet(
            db,
            tenant_id=report.tenant_id,
            client_id=client_id,
            display_name=cabinet_name,
            client_company_id=company_id,
        )
        wb_cabinet_id = cabinet.id if cabinet else ""
    return {
        "client_id": client_id,
        "client_company_id": company_id,
        "wb_cabinet_id": wb_cabinet_id,
    }


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
        profit_before_tax=decimal_value(item.get("profitBeforeTax")),
        profit=decimal_value(item.get("profit")),
        margin=decimal_or_none(item.get("margin")),
        unit_profit=decimal_or_none(item.get("unitProfit")),
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
        onec_quantity=decimal_value(item.get("onec_quantity")),
        quantity_delta=decimal_value(item.get("quantity_delta")),
        wb_cogs=decimal_value(item.get("wb_cogs")),
        onec_cogs=decimal_value(item.get("onec_cogs")),
        cogs_delta=decimal_value(item.get("cogs_delta")),
        wb_mp_expenses=decimal_value(item.get("wb_mp_expenses")),
        onec_mp_expenses=decimal_value(item.get("onec_mp_expenses")),
        mp_expenses_delta=decimal_value(item.get("mp_expenses_delta")),
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
        buyout_retail_amount_sum=decimal_or_none(
            item.get("buyoutRetailAmountSum")
        ),
        buyout_for_pay_sum=decimal_or_none(item.get("buyoutForPaySum")),
        buyout_bank_payment_sum=decimal_or_none(
            item.get("buyoutBankPaymentSum")
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
    document_reconciliation_rows = [
        _document_reconciliation_payload(row) for row in document_reconciliation
    ]
    latest_refresh = latest_source_refresh_payload(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        include_sensitive=include_staff_readiness,
    )
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
        "monthly": monthly_payload(unit_rows),
        "expenses": expense_payload(unit_rows),
        "unitRows": unit_rows,
        "liquidityRows": liquidity_rows,
        "returns": returns_payload(unit_rows, report.return_reason_limitation),
        "lostSales": [_lost_payload(row) for row in lost],
        "reconciliation": [],
        "reconciliationMonthly": [
            _reconciliation_payload(row) for row in reconciliation
        ],
        "documentReconciliation": document_reconciliation_rows,
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
    document_reconciliation_rows = [
        _document_reconciliation_payload(row)
        for row in db.scalars(
            select(ReportDocumentReconciliationRow)
            .where(ReportDocumentReconciliationRow.report_run_id == report.id)
            .order_by(ReportDocumentReconciliationRow.id)
        )
    ]
    liquidity_rows = _summary_liquidity_rows(db, report)
    latest_refresh = latest_source_refresh_payload(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
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
        "kpis": _summary_kpis_payload(stats),
        "quality": _summary_quality_payload(stats, loads, report),
        "monthly": _summary_monthly_payload(db, report),
        "expenses": _summary_expense_payload(db, report),
        "liquidityRows": liquidity_rows,
        "lostSales": _summary_lost_sales_payload(db, report),
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
        "sourceWorkbook": report.source_workbook,
        "publicationStatus": report.publication_status,
        "isCurrent": report.is_current,
        "lineageType": report.lineage_type,
        "sourceSnapshotSetId": report.source_snapshot_set_id,
        "returnReasonLimitation": report.return_reason_limitation,
    }


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
        failed_loads = [load for load in source_loads if _source_load_failed(load)]
        if failed_loads:
            blocking_reasons.append(
                _readiness_reason(
                    "source_load_failed",
                    "Есть неуспешные загрузки источников.",
                    len(failed_loads),
                )
            )
            score -= 40
        incomplete_loads = [
            load
            for load in source_loads
            if load not in failed_loads and not _source_load_ok(load)
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
        "month": row.month,
        "documentReport": row.document_report,
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
        "profitBeforeTax": as_float(row.profit_before_tax),
        "profit": as_float(row.profit),
        "margin": as_float(row.margin),
        "unitProfit": as_float(row.unit_profit),
        "status": row.status,
        "statusReason": row.status_reason,
        "sppStatus": row.spp_status,
        "lossClass": row.loss_class,
        "lossDriver": row.loss_driver,
    }


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
    month_values = {row.get("month") for row in rows}
    months = [month for month in MONTH_ORDER if month in month_values]
    extra_months = sorted(
        as_text(item) for item in month_values if item and item not in months
    )
    weeks = sorted(as_text(row.get("week")) for row in rows if row.get("week"))
    return {
        "months": months + extra_months,
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


def monthly_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        month = as_text(row.get("month"))
        if not month:
            continue
        bucket = buckets.setdefault(
            month,
            {
                "month": month,
                "status": "неполный месяц"
                if "непол" in month.lower()
                else "полный месяц",
                "sales": 0.0,
                "returns": 0.0,
                "revenue": 0.0,
                "profit": 0.0,
            },
        )
        bucket["sales"] += float(row.get("sales") or 0)
        bucket["returns"] += float(row.get("returns") or 0)
        bucket["revenue"] += float(row.get("revenue") or 0)
        bucket["profit"] += float(row.get("profit") or 0)
    for bucket in buckets.values():
        bucket["return_rate"] = (
            bucket["returns"] / bucket["sales"] if bucket["sales"] else None
        )
        bucket["margin"] = (
            bucket["profit"] / bucket["revenue"] if bucket["revenue"] else None
        )
    return [
        buckets[month] for month in options_payload(rows)["months"] if month in buckets
    ]


def expense_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = [
        ("Себестоимость 1С", "cost"),
        ("Комиссия WB", "commission"),
        ("Логистика WB", "logistics"),
        ("Хранение WB", "storage"),
        ("Приемка WB", "acceptance"),
        ("WB Продвижение", "promotion"),
        ("Штрафы/доплаты WB", "penalties"),
        ("Эквайринг WB", "acquiring"),
        ("НДС 5%", "vat"),
        ("УСН 1%", "usn"),
    ]
    revenue = sum(float(row.get("revenue") or 0) for row in rows)
    result = []
    for label, key in labels:
        amount = sum(float(row.get(key) or 0) for row in rows)
        if amount:
            result.append(
                {
                    "expense": label,
                    "amount": amount,
                    "share": amount / revenue if revenue else None,
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
    base = ReportUnitRow.report_run_id == report.id
    row_count = _count_rows(db, base)
    revenue = _sum_column(db, ReportUnitRow.revenue, base)
    profit = _sum_column(db, ReportUnitRow.profit, base)
    sales = _sum_column(db, ReportUnitRow.sales, base)
    returns = _sum_column(db, ReportUnitRow.returns, base)
    return {
        "row_count": row_count,
        "revenue": revenue,
        "profit": profit,
        "sales": sales,
        "returns": returns,
        "loss_rows": _count_rows(db, base, ReportUnitRow.profit < 0),
        "ok_rows": _count_rows(db, base, ReportUnitRow.status == "ОК"),
        "missing_cost_rows": _count_rows(
            db, base, ReportUnitRow.status != "ОК", _quality_condition("себестоим")
        ),
        "mapping_rows": _count_rows(
            db,
            base,
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
            base,
            ReportUnitRow.status != "ОК",
            _quality_condition("partial_source", "неполный источник"),
        ),
        "problem_rows": _count_rows(db, base, ReportUnitRow.status != "ОК"),
    }


def _count_rows(db: Session, *conditions: Any) -> int:
    statement = select(func.count()).select_from(ReportUnitRow)
    for condition in conditions:
        statement = statement.where(condition)
    return int(db.scalar(statement) or 0)


def _sum_column(db: Session, column: Any, *conditions: Any) -> float:
    statement = select(func.coalesce(func.sum(column), 0))
    for condition in conditions:
        statement = statement.where(condition)
    return float(db.scalar(statement) or 0)


def _quality_condition(*markers: str) -> Any:
    haystack = func.lower(
        func.coalesce(ReportUnitRow.status, "")
        + " "
        + func.coalesce(ReportUnitRow.status_reason, "")
        + " "
        + func.coalesce(ReportUnitRow.loss_driver, "")
    )
    return or_(*(haystack.like(f"%{marker.lower()}%") for marker in markers))


def _summary_kpis_payload(stats: dict[str, Any]) -> dict[str, Any]:
    revenue = float(stats["revenue"])
    profit = float(stats["profit"])
    return {
        "revenue": revenue,
        "profit": profit,
        "margin": profit / revenue if revenue else None,
        "sales": float(stats["sales"]),
        "returns": float(stats["returns"]),
        "lossRows": int(stats["loss_rows"]),
        "rowCount": int(stats["row_count"]),
    }


def _summary_quality_payload(
    stats: dict[str, Any], loads: list[SourceLoad], report: ReportRun
) -> dict[str, Any]:
    row_count = int(stats["row_count"])
    ok_rows = int(stats["ok_rows"])
    incomplete_sources = sum(
        1
        for load in loads
        if not _source_load_ok(load) and not _source_load_failed(load)
    )
    return {
        "okRows": ok_rows,
        "okShare": ok_rows / row_count if row_count else 0,
        "missingCostRows": int(stats["missing_cost_rows"]),
        "mappingRows": int(stats["mapping_rows"]),
        "partialPeriod": _is_partial_period(report),
        "incompleteSources": incomplete_sources,
        "rowCount": row_count,
    }


def _summary_options_payload(
    db: Session,
    report: ReportRun,
    *,
    liquidity_rows: list[dict[str, Any]],
    document_reconciliation: list[dict[str, Any]],
) -> dict[str, Any]:
    months = _ordered_values(_distinct_unit_values(db, report, ReportUnitRow.month))
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
        "documentReports": sorted(item for item in document_reports if item),
    }


def _distinct_unit_values(
    db: Session, report: ReportRun, column: Any, *, skip_empty: bool = True
) -> list[Any]:
    conditions = [ReportUnitRow.report_run_id == report.id, column.is_not(None)]
    if skip_empty:
        conditions.append(column != "")
    values = db.scalars(
        select(column)
        .where(*conditions)
        .distinct()
        .order_by(column)
    )
    return list(values)


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
    value_set = set(values)
    ordered = [month for month in MONTH_ORDER if month in value_set]
    return ordered + sorted(item for item in values if item and item not in ordered)


def _summary_monthly_payload(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            ReportUnitRow.month,
            func.coalesce(func.sum(ReportUnitRow.sales), 0),
            func.coalesce(func.sum(ReportUnitRow.returns), 0),
            func.coalesce(func.sum(ReportUnitRow.revenue), 0),
            func.coalesce(func.sum(ReportUnitRow.profit), 0),
        )
        .where(ReportUnitRow.report_run_id == report.id, ReportUnitRow.month != "")
        .group_by(ReportUnitRow.month)
    )
    buckets = {}
    for month, sales, returns, revenue, profit in rows:
        sales_float = float(sales or 0)
        returns_float = float(returns or 0)
        revenue_float = float(revenue or 0)
        profit_float = float(profit or 0)
        buckets[month] = {
            "month": month,
            "status": "неполный месяц" if "непол" in month.lower() else "полный месяц",
            "sales": sales_float,
            "returns": returns_float,
            "revenue": revenue_float,
            "profit": profit_float,
            "return_rate": returns_float / sales_float if sales_float else None,
            "margin": profit_float / revenue_float if revenue_float else None,
        }
    return [
        buckets[month] for month in _ordered_values(list(buckets)) if month in buckets
    ]


def _summary_expense_payload(db: Session, report: ReportRun) -> list[dict[str, Any]]:
    labels = [
        ("Себестоимость 1С", ReportUnitRow.cost),
        ("Комиссия WB", ReportUnitRow.commission),
        ("Логистика WB", ReportUnitRow.logistics),
        ("Хранение WB", ReportUnitRow.storage),
        ("Приемка WB", ReportUnitRow.acceptance),
        ("WB Продвижение", ReportUnitRow.promotion),
        ("Штрафы/доплаты WB", ReportUnitRow.penalties),
        ("Эквайринг WB", ReportUnitRow.acquiring),
        ("НДС 5%", ReportUnitRow.vat),
        ("УСН 1%", ReportUnitRow.usn),
    ]
    base = ReportUnitRow.report_run_id == report.id
    revenue = _sum_column(db, ReportUnitRow.revenue, base)
    result = []
    for label, column in labels:
        amount = _sum_column(db, column, base)
        if amount:
            result.append(
                {
                    "expense": label,
                    "amount": amount,
                    "share": amount / revenue if revenue else None,
                }
            )
    return result


def _summary_liquidity_rows(db: Session, report: ReportRun) -> list[dict[str, Any]]:
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
        "usn": ReportUnitRow.usn,
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
        .where(ReportUnitRow.report_run_id == report.id)
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
    rows = db.scalars(
        select(ReportLostSalesRow)
        .where(ReportLostSalesRow.report_run_id == report.id)
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


def _unit_rows_for_report(db: Session, report: ReportRun) -> list[ReportUnitRow]:
    return list(
        db.scalars(
            select(ReportUnitRow)
            .where(ReportUnitRow.report_run_id == report.id)
            .order_by(ReportUnitRow.id)
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
        "partial_source": (
            "Дозагрузить недостающие источники или явно описать ограничение."
        ),
        "data_quality_review": "Проверить строки со статусом, отличным от ОК.",
        "too_many_data_quality_issues": (
            "Исправить качество данных перед отправкой клиенту."
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
    statement = select(ReportUnitRow).where(ReportUnitRow.report_run_id == report.id)
    if status:
        statement = statement.where(ReportUnitRow.status == status)
    if period_start:
        statement = statement.where(ReportUnitRow.week >= period_start)
    if period_end:
        statement = statement.where(ReportUnitRow.week <= period_end)
    if month:
        statement = statement.where(ReportUnitRow.month == month)
    if cabinet:
        statement = statement.where(ReportUnitRow.cabinet == cabinet)
    if organization:
        statement = statement.where(ReportUnitRow.organization == organization)
    if wb_cabinet_id:
        statement = statement.where(
            or_(
                ReportUnitRow.wb_cabinet_id == wb_cabinet_id,
                ReportUnitRow.cabinet == wb_cabinet_id,
            )
        )
    if client_company_id:
        statement = statement.where(
            or_(
                ReportUnitRow.client_company_id == client_company_id,
                ReportUnitRow.organization == client_company_id,
            )
        )
    if scheme:
        statement = statement.where(ReportUnitRow.scheme == scheme)
    if loss_class:
        statement = statement.where(ReportUnitRow.loss_class == loss_class)
    if document_report:
        statement = statement.where(ReportUnitRow.document_report == document_report)
    if preset == "losses":
        statement = statement.where(ReportUnitRow.profit < 0)
    if preset == "missingCost":
        statement = statement.where(ReportUnitRow.status.ilike("%себестоим%"))
    if preset == "missingMapping":
        statement = statement.where(ReportUnitRow.status.ilike("%сопостав%"))
    if preset == "review":
        statement = statement.where(ReportUnitRow.status != "ОК")
    if query:
        like = f"%{query}%"
        statement = statement.where(
            or_(
                ReportUnitRow.product.ilike(like),
                ReportUnitRow.nm_id.ilike(like),
                ReportUnitRow.article_wb.ilike(like),
                ReportUnitRow.article_1c.ilike(like),
                ReportUnitRow.barcode.ilike(like),
                ReportUnitRow.document_report.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(
        db.scalars(
            statement.order_by(ReportUnitRow.profit.asc()).offset(offset).limit(limit)
        )
    )
    return {"items": [_row_payload(row) for row in rows], "total": total}


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
        f"Маржинальный доход WB после налогов: {totals['profit']:,.0f} ₽\n"
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
