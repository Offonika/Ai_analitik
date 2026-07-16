from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.models import (
    AccountingWorkflowAttachment,
    AccountingWorkflowAuditEvent,
    AccountingWorkflowCard,
    AccountingWorkflowComment,
    AccountingWorkflowDelivery,
    AccountingWorkflowFollowup,
    AccountingWorkflowReportRevision,
    AccountingWorkflowSupervisor,
    AccountingWorkflowTask,
    Client,
    ClientCompany,
    MonthCloseControlReport,
    ReportRun,
    TaxLoadReport,
    User,
    UserTenantAccess,
)
from wb_unit_economics.web.report_kinds import (
    MONTH_CLOSE_CONTROL,
    TAX_LOAD,
)
from wb_unit_economics.web.settings import WebSettings

MOSCOW = ZoneInfo("Europe/Moscow")
REPORT_KINDS = (MONTH_CLOSE_CONTROL, TAX_LOAD)
ACTIVE_STAGES = {
    "new",
    "data_collection",
    "reports_in_progress",
    "internal_review",
    "ready_to_send",
    "sent_to_client",
    "ready_for_payroll_close",
    "rework",
    "blocked",
}
TERMINAL_STAGES = {"closed_payroll", "cancelled"}
CARD_STAGES = ACTIVE_STAGES | TERMINAL_STAGES
TASK_STATUSES = {
    "pending",
    "in_progress",
    "in_review",
    "completed",
    "rework",
    "blocked",
}
DELIVERY_CHANNELS = {"email", "messenger", "meeting", "other_approved"}
ALLOWED_EVIDENCE_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
SAFE_TEXT_FORBIDDEN = re.compile(
    r"(?i)(authorization\s*:\s*bearer|password\s*[=:]|token\s*[=:]|api[_-]?key)"
)
EVIDENCE_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}

_FORWARD_TRANSITIONS = {
    "new": {"data_collection", "blocked", "cancelled"},
    "data_collection": {"reports_in_progress", "blocked", "cancelled"},
    "reports_in_progress": {"internal_review", "rework", "blocked", "cancelled"},
    "internal_review": {"ready_to_send", "rework", "blocked", "cancelled"},
    "ready_to_send": {"rework", "blocked", "cancelled"},
    "sent_to_client": {"rework", "blocked", "cancelled"},
    "ready_for_payroll_close": {"closed_payroll", "rework", "blocked"},
    "rework": {"reports_in_progress", "blocked", "cancelled"},
    "blocked": {"data_collection", "reports_in_progress", "rework", "cancelled"},
    "closed_payroll": set(),
    "cancelled": set(),
}


class WorkflowError(ValueError):
    status_code = 400
    persist_changes = False


class WorkflowNotFoundError(WorkflowError):
    status_code = 404


class WorkflowPermissionError(WorkflowError):
    status_code = 403


class WorkflowConflictError(WorkflowError):
    status_code = 409

    def __init__(self, message: str, *, persist_changes: bool = False) -> None:
        super().__init__(message)
        self.persist_changes = persist_changes


class WorkflowConfigurationError(WorkflowError):
    status_code = 503


class BusinessCalendar:
    def __init__(self, settings: WebSettings) -> None:
        self.settings = settings
        self.non_working_dates = _parse_date_set(
            settings.accounting_workflow_non_working_dates
        )
        self.working_dates = _parse_date_set(settings.accounting_workflow_working_dates)

    def require_configured(self) -> None:
        if (
            self.settings.runtime_environment == "production"
            and not self.settings.accounting_workflow_calendar_configured
        ):
            raise WorkflowConfigurationError("production calendar is not configured")

    def is_working_day(self, value: date) -> bool:
        if value in self.working_dates:
            return True
        if value in self.non_working_dates:
            return False
        return value.weekday() < 5

    def add_working_days(self, value: datetime, days: int) -> datetime:
        current = _as_utc(value).astimezone(MOSCOW)
        remaining = days
        while remaining > 0:
            current += timedelta(days=1)
            if self.is_working_day(current.date()):
                remaining -= 1
        return current.astimezone(UTC)


def _parse_date_set(raw: str) -> set[date]:
    values: set[date] = set()
    for item in raw.split(","):
        normalized = item.strip()
        if normalized:
            values.add(date.fromisoformat(normalized))
    return values


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def require_enabled(settings: WebSettings) -> None:
    if not settings.accounting_workflow_enabled:
        raise WorkflowNotFoundError("accounting workflow is disabled")


def is_supervisor(db: Session, user: User, tenant_id: str) -> bool:
    if tenant_id not in repository.allowed_tenant_ids(user):
        return False
    return (
        db.scalar(
            select(AccountingWorkflowSupervisor.id).where(
                AccountingWorkflowSupervisor.tenant_id == tenant_id,
                AccountingWorkflowSupervisor.user_id == user.id,
                AccountingWorkflowSupervisor.is_active.is_(True),
            )
        )
        is not None
    )


def require_supervisor(db: Session, user: User, tenant_id: str) -> None:
    if not is_supervisor(db, user, tenant_id):
        raise WorkflowPermissionError("workflow supervisor permission required")


def require_staff(user: User, tenant_id: str) -> None:
    try:
        repository.require_staff(user, tenant_id)
    except PermissionError as exc:
        raise WorkflowPermissionError("staff role required") from exc


def grant_supervisor(
    db: Session,
    *,
    admin: User,
    tenant_id: str,
    user_id: str,
    active: bool,
) -> AccountingWorkflowSupervisor:
    try:
        repository.require_admin(admin, tenant_id)
    except PermissionError as exc:
        raise WorkflowPermissionError("admin role required") from exc
    target = db.get(User, user_id)
    if target is None or tenant_id not in repository.allowed_tenant_ids(target):
        raise WorkflowNotFoundError("user not found")
    now = security.utcnow()
    item = db.scalar(
        select(AccountingWorkflowSupervisor).where(
            AccountingWorkflowSupervisor.tenant_id == tenant_id,
            AccountingWorkflowSupervisor.user_id == user_id,
        )
    )
    if item is None:
        item = AccountingWorkflowSupervisor(
            id=repository.new_id("workflow_supervisor"),
            tenant_id=tenant_id,
            user_id=user_id,
            is_active=active,
            granted_by_user_id=admin.id,
            granted_at=now,
            revoked_by_user_id=None if active else admin.id,
            revoked_at=None if active else now,
        )
        db.add(item)
    else:
        item.is_active = active
        if active:
            item.granted_by_user_id = admin.id
            item.granted_at = now
            item.revoked_by_user_id = None
            item.revoked_at = None
        else:
            item.revoked_by_user_id = admin.id
            item.revoked_at = now
    _audit(
        db,
        tenant_id=tenant_id,
        card_id=None,
        user=admin,
        action="workflow_supervisor_granted"
        if active
        else "workflow_supervisor_revoked",
        entity_type="user",
        entity_id=user_id,
        payload={"active": active},
    )
    db.flush()
    return item


def list_supervisors(
    db: Session, user: User, tenant_id: str
) -> list[dict[str, object]]:
    require_staff(user, tenant_id)
    rows = list(
        db.execute(
            select(AccountingWorkflowSupervisor, User)
            .join(User, User.id == AccountingWorkflowSupervisor.user_id)
            .where(AccountingWorkflowSupervisor.tenant_id == tenant_id)
            .order_by(User.name, User.email)
        )
    )
    return [
        {
            "userId": item.user_id,
            "name": target.name,
            "email": target.email,
            "active": item.is_active,
            "grantedAt": item.granted_at.isoformat(),
            "revokedAt": item.revoked_at.isoformat() if item.revoked_at else None,
        }
        for item, target in rows
    ]


def list_staff_users(
    db: Session, user: User, tenant_id: str
) -> list[dict[str, object]]:
    require_staff(user, tenant_id)
    rows = list(
        db.execute(
            select(User, UserTenantAccess.role)
            .join(UserTenantAccess, UserTenantAccess.user_id == User.id)
            .where(
                UserTenantAccess.tenant_id == tenant_id,
                UserTenantAccess.role.in_(repository.STAFF_ROLES),
                User.is_active.is_(True),
            )
            .order_by(User.name, User.email)
        )
    )
    return [
        {
            "id": target.id,
            "name": target.name,
            "email": target.email,
            "role": role,
            "workflowSupervisor": is_supervisor(db, target, tenant_id),
        }
        for target, role in rows
    ]


def create_month_cards(
    db: Session,
    *,
    settings: WebSettings,
    tenant_id: str,
    report_period: date,
    user: User | None,
    creation_kind: str,
    responsible_user_id: str | None = None,
    supervisor_user_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    require_enabled(settings)
    if creation_kind not in {"scheduled", "manual_catch_up"}:
        raise WorkflowError("invalid creation kind")
    if report_period.day != 1:
        raise WorkflowError("report period must be the first day of a month")
    if user is not None:
        require_supervisor(db, user, tenant_id)
    if not set(REPORT_KINDS).issubset(settings.enabled_report_kind_set):
        raise WorkflowConfigurationError(
            "month_close_control and tax_load must both be enabled"
        )
    calendar = BusinessCalendar(settings)
    calendar.require_configured()
    created_at = now or security.utcnow()
    responsible = _validate_responsible(
        db, tenant_id=tenant_id, user_id=responsible_user_id
    )
    supervisor = _validate_supervisor_assignment(
        db,
        tenant_id=tenant_id,
        user_id=supervisor_user_id or (user.id if user is not None else None),
    )
    clients = list(
        db.scalars(
            select(Client).where(
                Client.tenant_id == tenant_id,
                Client.status == "active",
            )
        )
    )
    if not clients:
        raise WorkflowConfigurationError("active client is not configured")
    created: list[AccountingWorkflowCard] = []
    existing: list[AccountingWorkflowCard] = []
    gaps: list[dict[str, str]] = []
    for client in clients:
        companies = list(
            db.scalars(
                select(ClientCompany).where(
                    ClientCompany.tenant_id == tenant_id,
                    ClientCompany.client_id == client.id,
                    ClientCompany.status == "active",
                    ClientCompany.onec_organization_id != "",
                )
            )
        )
        if not companies:
            gaps.append(
                {
                    "clientId": client.id,
                    "reason": "active organization is not configured",
                }
            )
            continue
        for company in companies:
            _lock_card_scope(
                db,
                tenant_id=tenant_id,
                client_id=client.id,
                organization_id=company.onec_organization_id,
                report_period=report_period,
            )
            current = _current_chain_card(
                db,
                tenant_id=tenant_id,
                client_id=client.id,
                organization_id=company.onec_organization_id,
                report_period=report_period,
            )
            if current is not None:
                existing.append(current)
                continue
            try:
                with db.begin_nested():
                    card = _create_card(
                        db,
                        tenant_id=tenant_id,
                        client_id=client.id,
                        organization_id=company.onec_organization_id,
                        report_period=report_period,
                        creation_kind=creation_kind,
                        responsible_user_id=responsible.id if responsible else None,
                        supervisor_user_id=supervisor.id if supervisor else None,
                        created_by_user_id=user.id if user else None,
                        created_at=created_at,
                        calendar=calendar,
                    )
                created.append(card)
            except IntegrityError:
                current = _current_chain_card(
                    db,
                    tenant_id=tenant_id,
                    client_id=client.id,
                    organization_id=company.onec_organization_id,
                    report_period=report_period,
                )
                if current is None:
                    raise
                existing.append(current)
    _audit(
        db,
        tenant_id=tenant_id,
        card_id=None,
        user=user,
        action="accounting_workflow_monthly_run",
        entity_type="report_period",
        entity_id=report_period.strftime("%Y-%m"),
        payload={
            "created": len(created),
            "deduplicated": len(existing),
            "gaps": gaps,
            "creationKind": creation_kind,
        },
    )
    db.flush()
    return {
        "created": [card_summary_payload(db, item) for item in created],
        "existing": [card_summary_payload(db, item) for item in existing],
        "gaps": gaps,
    }


def create_correction_card(
    db: Session,
    *,
    settings: WebSettings,
    user: User,
    supersedes_card_id: str,
    reason: str,
    now: datetime | None = None,
) -> AccountingWorkflowCard:
    require_enabled(settings)
    previous = require_card(db, user, supersedes_card_id)
    require_supervisor(db, user, previous.tenant_id)
    if previous.stage not in TERMINAL_STAGES:
        raise WorkflowConflictError("only a terminal card can be corrected")
    current = _current_chain_card(
        db,
        tenant_id=previous.tenant_id,
        client_id=previous.client_id,
        organization_id=previous.organization_id,
        report_period=previous.report_period,
    )
    if current is None or current.id != previous.id:
        raise WorkflowConflictError(
            "only the latest card in the chain can be corrected"
        )
    if _active_scope_card(db, previous) is not None:
        raise WorkflowConflictError("an active correction already exists")
    _safe_text(reason, field="reason", min_length=1, max_length=2000)
    calendar = BusinessCalendar(settings)
    calendar.require_configured()
    created_at = now or security.utcnow()
    card = _create_card(
        db,
        tenant_id=previous.tenant_id,
        client_id=previous.client_id,
        organization_id=previous.organization_id,
        report_period=previous.report_period,
        creation_kind="correction",
        responsible_user_id=previous.responsible_user_id,
        supervisor_user_id=previous.supervisor_user_id or user.id,
        created_by_user_id=user.id,
        created_at=created_at,
        calendar=calendar,
        supersedes_card_id=previous.id,
    )
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action="accounting_workflow_correction_created",
        entity_type="accounting_workflow_card",
        entity_id=card.id,
        payload={"supersedesCardId": previous.id, "reason": reason},
    )
    db.flush()
    return card


def _create_card(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    organization_id: str,
    report_period: date,
    creation_kind: str,
    responsible_user_id: str | None,
    supervisor_user_id: str | None,
    created_by_user_id: str | None,
    created_at: datetime,
    calendar: BusinessCalendar,
    supersedes_card_id: str | None = None,
) -> AccountingWorkflowCard:
    card = AccountingWorkflowCard(
        id=repository.new_id("accounting_workflow_card"),
        tenant_id=tenant_id,
        client_id=client_id,
        organization_id=organization_id,
        report_period=report_period,
        stage="new",
        previous_stage="",
        creation_kind=creation_kind,
        responsible_user_id=responsible_user_id,
        supervisor_user_id=supervisor_user_id,
        target_due_at=calendar.add_working_days(created_at, 5),
        hard_due_at=_hard_due_at(report_period),
        blocking_reason="",
        cancellation_reason="",
        cancellation_detail="",
        supersedes_card_id=supersedes_card_id,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
        updated_at=created_at,
        closed_at=None,
        cancelled_at=None,
    )
    db.add(card)
    db.flush()
    for report_kind in REPORT_KINDS:
        db.add(
            AccountingWorkflowTask(
                id=repository.new_id("accounting_workflow_task"),
                card_id=card.id,
                report_kind=report_kind,
                status="pending",
                current_report_id=None,
                current_payload_sha256="",
                is_final=False,
                reviewed_by_user_id=None,
                reviewed_at=None,
                facts_confirmed_by_user_id=None,
                facts_confirmed_at=None,
                text_approved_by_user_id=None,
                text_approved_at=None,
                blocking_reason="",
                created_at=created_at,
                updated_at=created_at,
            )
        )
    _audit(
        db,
        tenant_id=tenant_id,
        card_id=card.id,
        user=db.get(User, created_by_user_id) if created_by_user_id else None,
        action="accounting_workflow_card_created",
        entity_type="accounting_workflow_card",
        entity_id=card.id,
        payload={
            "clientId": client_id,
            "organizationId": organization_id,
            "periodMonth": report_period.strftime("%Y-%m"),
            "creationKind": creation_kind,
            "supersedesCardId": supersedes_card_id,
        },
    )
    db.flush()
    return card


def _hard_due_at(report_period: date) -> datetime:
    year = report_period.year + (1 if report_period.month == 12 else 0)
    month = 1 if report_period.month == 12 else report_period.month + 1
    local = datetime.combine(date(year, month, 15), time(23, 59, 59), MOSCOW)
    return local.astimezone(UTC)


def _validate_responsible(
    db: Session, *, tenant_id: str, user_id: str | None
) -> User | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or "consultant" not in repository.roles_for_tenant(user, tenant_id):
        raise WorkflowError("responsible user must be a consultant of the tenant")
    return user


def _validate_supervisor_assignment(
    db: Session, *, tenant_id: str, user_id: str | None
) -> User | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not is_supervisor(db, user, tenant_id):
        raise WorkflowError("supervisor permission is required for assignee")
    return user


def _lock_card_scope(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    organization_id: str,
    report_period: date,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {
            "lock_key": (
                f"accounting-workflow:{tenant_id}:{client_id}:"
                f"{organization_id}:{report_period:%Y-%m}"
            )
        },
    )


def _current_chain_card(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    organization_id: str,
    report_period: date,
) -> AccountingWorkflowCard | None:
    return db.scalar(
        select(AccountingWorkflowCard)
        .where(
            AccountingWorkflowCard.tenant_id == tenant_id,
            AccountingWorkflowCard.client_id == client_id,
            AccountingWorkflowCard.organization_id == organization_id,
            AccountingWorkflowCard.report_period == report_period,
        )
        .order_by(AccountingWorkflowCard.created_at.desc())
    )


def _active_scope_card(
    db: Session, card: AccountingWorkflowCard
) -> AccountingWorkflowCard | None:
    return db.scalar(
        select(AccountingWorkflowCard).where(
            AccountingWorkflowCard.tenant_id == card.tenant_id,
            AccountingWorkflowCard.client_id == card.client_id,
            AccountingWorkflowCard.organization_id == card.organization_id,
            AccountingWorkflowCard.report_period == card.report_period,
            AccountingWorkflowCard.stage.in_(ACTIVE_STAGES),
        )
    )


def list_cards(
    db: Session,
    *,
    user: User,
    tenant_id: str | None = None,
    client_id: str | None = None,
    organization_id: str | None = None,
    report_period: date | None = None,
    stage: str | None = None,
    responsible_user_id: str | None = None,
    supervisor_user_id: str | None = None,
    overdue: bool | None = None,
) -> list[dict[str, object]]:
    tenant_ids = repository.allowed_tenant_ids(user)
    if tenant_id:
        require_staff(user, tenant_id)
        tenant_ids = [tenant_id]
    else:
        tenant_ids = [
            item
            for item in tenant_ids
            if repository.roles_for_tenant(user, item).intersection(
                repository.STAFF_ROLES
            )
        ]
    if not tenant_ids:
        raise WorkflowPermissionError("staff role required")
    conditions = [AccountingWorkflowCard.tenant_id.in_(tenant_ids)]
    if client_id:
        conditions.append(AccountingWorkflowCard.client_id == client_id)
    if organization_id:
        conditions.append(AccountingWorkflowCard.organization_id == organization_id)
    if report_period:
        conditions.append(AccountingWorkflowCard.report_period == report_period)
    if stage:
        if stage not in CARD_STAGES:
            raise WorkflowError("invalid card stage")
        conditions.append(AccountingWorkflowCard.stage == stage)
    if responsible_user_id:
        conditions.append(
            AccountingWorkflowCard.responsible_user_id == responsible_user_id
        )
    if supervisor_user_id:
        conditions.append(
            AccountingWorkflowCard.supervisor_user_id == supervisor_user_id
        )
    now = security.utcnow()
    if overdue is True:
        conditions.extend(
            [
                AccountingWorkflowCard.target_due_at < now,
                AccountingWorkflowCard.stage.in_(ACTIVE_STAGES),
            ]
        )
    if overdue is False:
        conditions.append(
            (AccountingWorkflowCard.target_due_at >= now)
            | AccountingWorkflowCard.stage.in_(TERMINAL_STAGES)
        )
    cards = list(
        db.scalars(
            select(AccountingWorkflowCard)
            .where(*conditions)
            .order_by(
                AccountingWorkflowCard.report_period.desc(),
                AccountingWorkflowCard.created_at.desc(),
            )
        )
    )
    return [card_summary_payload(db, card, now=now) for card in cards]


def require_card(db: Session, user: User, card_id: str) -> AccountingWorkflowCard:
    card = db.get(AccountingWorkflowCard, card_id)
    if card is None:
        raise WorkflowNotFoundError("workflow card not found")
    require_staff(user, card.tenant_id)
    return card


def card_detail_payload(db: Session, user: User, card_id: str) -> dict[str, object]:
    card = require_card(db, user, card_id)
    payload = card_summary_payload(db, card)
    payload.update(
        {
            "deliveries": [
                _delivery_payload(db, item) for item in _deliveries(db, card.id)
            ],
            "followups": [_followup_payload(item) for item in _followups(db, card.id)],
            "comments": [_comment_payload(db, item) for item in _comments(db, card.id)],
            "auditEvents": [
                _audit_payload(db, item) for item in _audit_events(db, card.id)
            ],
        }
    )
    return payload


def card_summary_payload(
    db: Session,
    card: AccountingWorkflowCard,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    current_time = now or security.utcnow()
    client = db.get(Client, card.client_id)
    company = db.scalar(
        select(ClientCompany).where(
            ClientCompany.client_id == card.client_id,
            ClientCompany.onec_organization_id == card.organization_id,
        )
    )
    responsible = (
        db.get(User, card.responsible_user_id) if card.responsible_user_id else None
    )
    supervisor = (
        db.get(User, card.supervisor_user_id) if card.supervisor_user_id else None
    )
    tasks = list(
        db.scalars(
            select(AccountingWorkflowTask)
            .where(AccountingWorkflowTask.card_id == card.id)
            .order_by(AccountingWorkflowTask.report_kind)
        )
    )
    return {
        "id": card.id,
        "tenantId": card.tenant_id,
        "clientId": card.client_id,
        "clientName": client.name if client else card.client_id,
        "organizationId": card.organization_id,
        "organizationName": company.display_name if company else card.organization_id,
        "periodMonth": card.report_period.strftime("%Y-%m"),
        "stage": card.stage,
        "previousStage": card.previous_stage,
        "creationKind": card.creation_kind,
        "responsibleUserId": card.responsible_user_id,
        "responsibleName": responsible.name if responsible else "",
        "supervisorUserId": card.supervisor_user_id,
        "supervisorName": supervisor.name if supervisor else "",
        "targetDueAt": card.target_due_at.isoformat(),
        "hardDueAt": card.hard_due_at.isoformat(),
        "overdue": card.stage in ACTIVE_STAGES
        and _as_utc(card.target_due_at) < _as_utc(current_time),
        "hardOverdue": card.stage in ACTIVE_STAGES
        and _as_utc(card.hard_due_at) < _as_utc(current_time),
        "blockingReason": card.blocking_reason,
        "cancellationReason": card.cancellation_reason,
        "cancellationDetail": card.cancellation_detail,
        "supersedesCardId": card.supersedes_card_id,
        "createdAt": card.created_at.isoformat(),
        "updatedAt": card.updated_at.isoformat(),
        "closedAt": card.closed_at.isoformat() if card.closed_at else None,
        "tasks": [_task_payload(item) for item in tasks],
    }


def transition_card(
    db: Session,
    *,
    user: User,
    card_id: str,
    target_stage: str,
    reason: str = "",
    responsible_user_id: str | None = None,
    supervisor_user_id: str | None = None,
) -> AccountingWorkflowCard:
    card = require_card(db, user, card_id)
    if target_stage not in CARD_STAGES:
        raise WorkflowError("invalid card stage")
    if target_stage in {"sent_to_client", "ready_for_payroll_close"}:
        raise WorkflowConflictError("target stage is set automatically")
    if target_stage not in _FORWARD_TRANSITIONS[card.stage]:
        raise WorkflowConflictError(
            f"transition from {card.stage} to {target_stage} is not allowed"
        )
    supervisor = is_supervisor(db, user, card.tenant_id)
    if target_stage in {"closed_payroll", "cancelled"} or card.stage == "new":
        if not supervisor:
            raise WorkflowPermissionError("workflow supervisor permission required")
    else:
        _require_responsible_or_supervisor(db, user, card)
    now = security.utcnow()
    if target_stage == "data_collection":
        responsible = _validate_responsible(
            db,
            tenant_id=card.tenant_id,
            user_id=responsible_user_id or card.responsible_user_id,
        )
        assigned_supervisor = _validate_supervisor_assignment(
            db,
            tenant_id=card.tenant_id,
            user_id=supervisor_user_id or card.supervisor_user_id or user.id,
        )
        if responsible is None or assigned_supervisor is None:
            raise WorkflowConflictError("responsible and supervisor are required")
        card.responsible_user_id = responsible.id
        card.supervisor_user_id = assigned_supervisor.id
    if target_stage == "internal_review":
        statuses = {task.status for task in _tasks(db, card.id)}
        if not statuses.issubset({"in_review", "completed"}):
            raise WorkflowConflictError("both tasks must be submitted for review")
    if target_stage == "ready_to_send":
        _require_ready_to_send(db, card, user)
    if target_stage == "closed_payroll":
        _require_ready_for_close(db, card, user)
        card.closed_at = now
    if target_stage in {"rework", "blocked", "cancelled"}:
        _safe_text(reason, field="reason", min_length=1, max_length=2000)
        card.previous_stage = card.stage
    if target_stage == "rework":
        _invalidate_deliveries(db, card, user, reason=reason)
    if target_stage == "blocked":
        card.blocking_reason = reason
    elif card.stage == "blocked":
        card.blocking_reason = ""
    if target_stage == "cancelled":
        card.cancellation_reason = reason
        card.cancellation_detail = reason
        card.cancelled_at = now
    previous = card.stage
    card.stage = target_stage
    card.updated_at = now
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action="accounting_workflow_transition",
        entity_type="accounting_workflow_card",
        entity_id=card.id,
        payload={"from": previous, "to": target_stage, "reason": reason},
    )
    db.flush()
    return card


def task_action(
    db: Session,
    *,
    user: User,
    card_id: str,
    task_id: str,
    action: str,
    report_id: str | None = None,
    payload_sha256: str | None = None,
    reason: str = "",
) -> AccountingWorkflowTask:
    card = require_card(db, user, card_id)
    task = db.get(AccountingWorkflowTask, task_id)
    if task is None or task.card_id != card.id:
        raise WorkflowNotFoundError("workflow task not found")
    _require_responsible(db, user, card)
    if card.stage in TERMINAL_STAGES:
        raise WorkflowConflictError("terminal card cannot be changed")
    now = security.utcnow()
    if action == "start":
        if task.status not in {"pending", "rework", "blocked"}:
            raise WorkflowConflictError("task cannot be started")
        task.status = "in_progress"
        task.blocking_reason = ""
    elif action == "submit_review":
        if task.status != "in_progress" or not task.current_report_id:
            raise WorkflowConflictError("current report revision is required")
        _require_current_revision(db, card, task, user)
        task.status = "in_review"
    elif action == "attach_revision":
        if not report_id:
            raise WorkflowError("reportId is required")
        _attach_revision(
            db,
            user=user,
            card=card,
            task=task,
            report_id=report_id,
            expected_hash=payload_sha256,
        )
        task.status = "in_progress"
    elif action == "confirm_facts":
        _require_tax_task(task)
        _require_current_revision(db, card, task, user)
        task.facts_confirmed_by_user_id = user.id
        task.facts_confirmed_at = now
        _task_audit(db, card, task, user, "tax_facts_confirmed")
    elif action == "approve_text":
        _require_tax_task(task)
        _require_current_revision(db, card, task, user)
        task.text_approved_by_user_id = user.id
        task.text_approved_at = now
        _task_audit(db, card, task, user, "tax_client_text_approved")
    elif action == "mark_final":
        _require_tax_task(task)
        _require_current_revision(db, card, task, user)
        if not task.facts_confirmed_at or not task.text_approved_at:
            raise WorkflowConflictError(
                "facts and client text must be approved separately"
            )
        task.is_final = True
        revision = _current_task_revision(db, task)
        if revision is None:
            raise WorkflowConflictError("current report revision is required")
        revision.is_final = True
    elif action == "complete":
        _complete_task(db, card=card, task=task, user=user)
    elif action == "block":
        _safe_text(reason, field="reason", min_length=1, max_length=2000)
        task.status = "blocked"
        task.blocking_reason = reason
        if card.stage not in TERMINAL_STAGES:
            card.previous_stage = card.stage
            card.stage = "blocked"
            card.blocking_reason = reason
    elif action == "rework":
        _safe_text(reason, field="reason", min_length=1, max_length=2000)
        task.status = "rework"
        task.is_final = False
        task.blocking_reason = reason
        card.previous_stage = card.stage
        card.stage = "rework"
        _invalidate_deliveries(db, card, user, reason=reason)
    else:
        raise WorkflowError("unsupported task action")
    task.updated_at = now
    card.updated_at = now
    _task_audit(
        db,
        card,
        task,
        user,
        "accounting_workflow_task_action",
        {"action": action, "reason": reason},
    )
    db.flush()
    return task


def _complete_task(
    db: Session,
    *,
    card: AccountingWorkflowCard,
    task: AccountingWorkflowTask,
    user: User,
) -> None:
    if task.status != "in_review":
        raise WorkflowConflictError("task must be submitted for review")
    _require_current_revision(db, card, task, user)
    now = security.utcnow()
    if task.report_kind == MONTH_CLOSE_CONTROL:
        report = db.get(ReportRun, task.current_report_id)
        if report is None or report.status != "ready_to_close":
            raise WorkflowConflictError(
                "month close recommendation must be ready_to_close"
            )
        task.reviewed_by_user_id = user.id
        task.reviewed_at = now
        _task_audit(db, card, task, user, "month_close_review_completed")
    elif task.report_kind == TAX_LOAD:
        if (
            not task.facts_confirmed_at
            or not task.text_approved_at
            or not task.is_final
        ):
            raise WorkflowConflictError(
                "tax facts, client text and final revision are required"
            )
        task.reviewed_by_user_id = user.id
        task.reviewed_at = now
    else:
        raise WorkflowError("unsupported report kind")
    task.status = "completed"


def _attach_revision(
    db: Session,
    *,
    user: User,
    card: AccountingWorkflowCard,
    task: AccountingWorkflowTask,
    report_id: str,
    expected_hash: str | None,
) -> AccountingWorkflowReportRevision:
    report = db.get(ReportRun, report_id)
    if report is None:
        raise WorkflowNotFoundError("report not found")
    if (
        report.tenant_id != card.tenant_id
        or report.client_id != card.client_id
        or report.organization_id != card.organization_id
        or report.report_kind != task.report_kind
        or report.period_start.replace(day=1) != card.report_period
    ):
        raise WorkflowConflictError("report scope does not match workflow task")
    if not report.is_current:
        raise WorkflowConflictError("report revision is not current")
    stored_hash = _report_payload_hash(db, report)
    if expected_hash and expected_hash != stored_hash:
        raise WorkflowConflictError("payloadSha256 does not match report")
    db.execute(
        update(AccountingWorkflowReportRevision)
        .where(AccountingWorkflowReportRevision.task_id == task.id)
        .values(is_current_for_task=False)
    )
    revision = db.scalar(
        select(AccountingWorkflowReportRevision).where(
            AccountingWorkflowReportRevision.task_id == task.id,
            AccountingWorkflowReportRevision.report_id == report.id,
        )
    )
    if revision is None:
        revision = AccountingWorkflowReportRevision(
            id=repository.new_id("workflow_revision"),
            task_id=task.id,
            report_id=report.id,
            payload_sha256=stored_hash,
            is_final=False,
            is_current_for_task=True,
            attached_by_user_id=user.id,
            created_at=security.utcnow(),
        )
        db.add(revision)
    else:
        revision.payload_sha256 = stored_hash
        revision.is_current_for_task = True
        revision.is_final = False
        revision.attached_by_user_id = user.id
    task.current_report_id = report.id
    task.current_payload_sha256 = stored_hash
    task.is_final = False
    task.reviewed_by_user_id = None
    task.reviewed_at = None
    task.facts_confirmed_by_user_id = None
    task.facts_confirmed_at = None
    task.text_approved_by_user_id = None
    task.text_approved_at = None
    return revision


def _report_payload_hash(db: Session, report: ReportRun) -> str:
    if report.report_kind == MONTH_CLOSE_CONTROL:
        stored = db.get(MonthCloseControlReport, report.id)
    elif report.report_kind == TAX_LOAD:
        stored = db.get(TaxLoadReport, report.id)
    else:
        stored = None
    if stored is None:
        raise WorkflowConflictError("report payload is unavailable")
    return stored.payload_sha256


def _require_current_revision(
    db: Session,
    card: AccountingWorkflowCard,
    task: AccountingWorkflowTask,
    user: User,
) -> ReportRun:
    if not task.current_report_id:
        raise WorkflowConflictError("current report revision is required")
    report = db.get(ReportRun, task.current_report_id)
    stale = (
        report is None
        or not report.is_current
        or report.report_kind != task.report_kind
        or report.tenant_id != card.tenant_id
        or report.client_id != card.client_id
        or report.organization_id != card.organization_id
        or (
            report is not None
            and _report_payload_hash(db, report) != task.current_payload_sha256
        )
    )
    if stale:
        task.status = "rework"
        task.is_final = False
        task.updated_at = security.utcnow()
        card.previous_stage = card.stage
        card.stage = "rework"
        card.updated_at = security.utcnow()
        _invalidate_deliveries(
            db,
            card,
            user,
            reason="linked report revision is no longer current",
        )
        _task_audit(db, card, task, user, "workflow_report_revision_stale")
        db.flush()
        raise WorkflowConflictError(
            "linked report revision is no longer current",
            persist_changes=True,
        )
    return report


def _require_ready_to_send(
    db: Session, card: AccountingWorkflowCard, user: User
) -> None:
    tasks = _tasks(db, card.id)
    if len(tasks) != 2 or any(task.status != "completed" for task in tasks):
        raise WorkflowConflictError("both report tasks must be completed")
    tax_task = next((task for task in tasks if task.report_kind == TAX_LOAD), None)
    if tax_task is None or not tax_task.is_final:
        raise WorkflowConflictError("final tax load report is required")
    for task in tasks:
        _require_current_revision(db, card, task, user)


def _require_ready_for_close(
    db: Session, card: AccountingWorkflowCard, user: User
) -> None:
    if card.stage != "ready_for_payroll_close":
        raise WorkflowConflictError("card is not ready for payroll close")
    _require_ready_to_send(db, card, user)
    delivery = _active_final_delivery(db, card.id)
    if delivery is None:
        raise WorkflowConflictError("final delivery evidence is required")


def _require_tax_task(task: AccountingWorkflowTask) -> None:
    if task.report_kind != TAX_LOAD:
        raise WorkflowError("action is available only for tax_load")


def _require_responsible(db: Session, user: User, card: AccountingWorkflowCard) -> None:
    if "consultant" not in repository.roles_for_tenant(user, card.tenant_id):
        raise WorkflowPermissionError("responsible consultant role required")
    if card.responsible_user_id and card.responsible_user_id != user.id:
        raise WorkflowPermissionError("workflow card is assigned to another user")


def _require_responsible_or_supervisor(
    db: Session, user: User, card: AccountingWorkflowCard
) -> None:
    if is_supervisor(db, user, card.tenant_id):
        return
    _require_responsible(db, user, card)


def save_attachment(
    db: Session,
    *,
    settings: WebSettings,
    user: User,
    card_id: str,
    filename: str,
    content_type: str,
    content: bytes,
) -> AccountingWorkflowAttachment:
    card = require_card(db, user, card_id)
    _require_responsible(db, user, card)
    if content_type not in ALLOWED_EVIDENCE_TYPES:
        raise WorkflowError("unsupported evidence content type")
    if not content or len(content) > settings.accounting_workflow_evidence_max_bytes:
        raise WorkflowError("evidence file size is invalid")
    if not any(
        content.startswith(prefix) for prefix in EVIDENCE_SIGNATURES[content_type]
    ):
        raise WorkflowError("evidence file content does not match content type")
    suffix = ALLOWED_EVIDENCE_TYPES[content_type]
    safe_name = Path(filename or f"evidence{suffix}").name[:200]
    if Path(safe_name).suffix.lower() not in {
        suffix,
        ".jpeg" if suffix == ".jpg" else suffix,
    }:
        raise WorkflowError("evidence filename does not match content type")
    item_id = repository.new_id("workflow_attachment")
    storage_key = f"{card.tenant_id}/{card.id}/{item_id}{suffix}"
    root = settings.accounting_workflow_evidence_path
    output = (root / storage_key).resolve()
    if root not in output.parents:
        raise WorkflowError("invalid evidence path")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    item = AccountingWorkflowAttachment(
        id=item_id,
        tenant_id=card.tenant_id,
        card_id=card.id,
        storage_key=storage_key,
        original_name=safe_name,
        content_type=content_type,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by_user_id=user.id,
        created_at=security.utcnow(),
    )
    db.add(item)
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action="accounting_workflow_evidence_uploaded",
        entity_type="accounting_workflow_attachment",
        entity_id=item.id,
        payload={
            "contentType": content_type,
            "byteSize": len(content),
            "sha256": item.sha256,
        },
    )
    db.flush()
    return item


def require_attachment(
    db: Session, user: User, attachment_id: str
) -> AccountingWorkflowAttachment:
    item = db.get(AccountingWorkflowAttachment, attachment_id)
    if item is None:
        raise WorkflowNotFoundError("evidence attachment not found")
    require_card(db, user, item.card_id)
    return item


def attachment_path(settings: WebSettings, item: AccountingWorkflowAttachment) -> Path:
    root = settings.accounting_workflow_evidence_path
    output = (root / item.storage_key).resolve()
    if root not in output.parents or not output.is_file():
        raise WorkflowNotFoundError("evidence attachment file not found")
    return output


def record_delivery(
    db: Session,
    *,
    settings: WebSettings,
    user: User,
    card_id: str,
    sent_at: datetime,
    delivery_channel: str,
    masked_recipient: str,
    attachment_id: str,
    channel_detail: str = "",
    contact_result: str = "",
    preliminary: bool = False,
) -> AccountingWorkflowDelivery:
    card = require_card(db, user, card_id)
    _require_responsible(db, user, card)
    if delivery_channel not in DELIVERY_CHANNELS:
        raise WorkflowError("invalid delivery channel")
    if delivery_channel == "other_approved":
        _safe_text(channel_detail, field="channelDetail", min_length=1, max_length=500)
    _safe_text(masked_recipient, field="maskedRecipient", min_length=3, max_length=240)
    if "*" not in masked_recipient:
        raise WorkflowError("recipient must be masked")
    _safe_text(contact_result, field="contactResult", max_length=2000)
    if sent_at.tzinfo is None:
        raise WorkflowError("sentAt must include timezone")
    if sent_at > security.utcnow() + timedelta(minutes=5):
        raise WorkflowError("sentAt cannot be in the future")
    attachment = require_attachment(db, user, attachment_id)
    if attachment.card_id != card.id:
        raise WorkflowConflictError("evidence belongs to another card")
    tax_task = next(
        (task for task in _tasks(db, card.id) if task.report_kind == TAX_LOAD),
        None,
    )
    if tax_task is None or not tax_task.current_report_id:
        raise WorkflowConflictError("tax load report revision is required")
    report = _require_current_revision(db, card, tax_task, user)
    normalized_sent_at = _as_utc(sent_at)
    if normalized_sent_at < _as_utc(report.created_at):
        raise WorkflowConflictError("sentAt cannot be earlier than report creation")
    if not preliminary:
        if tax_task.status != "completed" or not tax_task.is_final:
            raise WorkflowConflictError("completed final tax load report is required")
        if card.stage != "ready_to_send":
            raise WorkflowConflictError("card is not ready to send")
    now = security.utcnow()
    if not preliminary:
        _invalidate_deliveries(
            db,
            card,
            user,
            reason="superseded by a newer final delivery",
        )
    delivery = AccountingWorkflowDelivery(
        id=repository.new_id("workflow_delivery"),
        card_id=card.id,
        task_id=tax_task.id,
        report_id=tax_task.current_report_id,
        payload_sha256=tax_task.current_payload_sha256,
        sent_at=normalized_sent_at,
        delivery_channel=delivery_channel,
        channel_detail=channel_detail,
        masked_recipient=masked_recipient,
        attachment_id=attachment.id,
        contact_result=contact_result,
        is_preliminary=preliminary,
        created_by_user_id=user.id,
        invalidated_at=None,
        invalidation_reason="",
        created_at=now,
    )
    db.add(delivery)
    db.flush()
    calendar = BusinessCalendar(settings)
    calendar.require_configured()
    evidence_recorded_late = _as_utc(now) > calendar.add_working_days(
        delivery.sent_at, 1
    )
    followup = AccountingWorkflowFollowup(
        id=repository.new_id("workflow_followup"),
        card_id=card.id,
        delivery_id=delivery.id,
        status="scheduled",
        due_at=calendar.add_working_days(delivery.sent_at, 2),
        repeated_at=None,
        escalation_due_at=None,
        supervisor_notified_at=None,
        completed_at=None,
        result="",
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
    db.add(followup)
    if not preliminary:
        card.stage = "sent_to_client"
        card.updated_at = now
        card.stage = "ready_for_payroll_close"
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action="accounting_workflow_delivery_recorded",
        entity_type="accounting_workflow_delivery",
        entity_id=delivery.id,
        payload={
            "reportId": delivery.report_id,
            "payloadSha256": delivery.payload_sha256,
            "deliveryChannel": delivery.delivery_channel,
            "preliminary": preliminary,
            "evidenceRecordedLate": evidence_recorded_late,
        },
    )
    db.flush()
    return delivery


def add_comment(
    db: Session, *, user: User, card_id: str, body: str
) -> AccountingWorkflowComment:
    card = require_card(db, user, card_id)
    _safe_text(body, field="body", min_length=1, max_length=4000)
    item = AccountingWorkflowComment(
        id=repository.new_id("workflow_comment"),
        card_id=card.id,
        user_id=user.id,
        body=body.strip(),
        created_at=security.utcnow(),
    )
    db.add(item)
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action="accounting_workflow_comment_added",
        entity_type="accounting_workflow_comment",
        entity_id=item.id,
    )
    db.flush()
    return item


def followup_action(
    db: Session,
    *,
    settings: WebSettings,
    user: User,
    card_id: str,
    followup_id: str,
    action: str,
    result: str,
) -> AccountingWorkflowFollowup:
    card = require_card(db, user, card_id)
    _require_responsible(db, user, card)
    item = db.get(AccountingWorkflowFollowup, followup_id)
    if item is None or item.card_id != card.id:
        raise WorkflowNotFoundError("follow-up not found")
    _safe_text(result, field="result", min_length=1, max_length=2000)
    now = security.utcnow()
    if action == "repeat":
        if item.status not in {"scheduled", "contact_due"}:
            raise WorkflowConflictError("follow-up cannot be repeated")
        calendar = BusinessCalendar(settings)
        calendar.require_configured()
        item.status = "waiting_after_repeat"
        item.repeated_at = now
        item.escalation_due_at = calendar.add_working_days(now, 5)
        item.result = result
    elif action == "complete":
        if item.status == "completed":
            raise WorkflowConflictError("follow-up is already completed")
        item.status = "completed"
        item.completed_at = now
        item.result = result
    else:
        raise WorkflowError("unsupported follow-up action")
    item.updated_by_user_id = user.id
    item.updated_at = now
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action="accounting_workflow_followup_action",
        entity_type="accounting_workflow_followup",
        entity_id=item.id,
        payload={"action": action, "result": result},
    )
    db.flush()
    return item


def process_due_followups(
    db: Session,
    *,
    settings: WebSettings,
    user: User | None = None,
    tenant_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    require_enabled(settings)
    if user is not None:
        if not tenant_id:
            raise WorkflowError("tenantId is required")
        require_supervisor(db, user, tenant_id)
    current = now or security.utcnow()
    conditions = [AccountingWorkflowFollowup.status != "completed"]
    if tenant_id:
        conditions.append(
            AccountingWorkflowFollowup.card_id.in_(
                select(AccountingWorkflowCard.id).where(
                    AccountingWorkflowCard.tenant_id == tenant_id
                )
            )
        )
    items = list(db.scalars(select(AccountingWorkflowFollowup).where(*conditions)))
    due_count = 0
    escalated_count = 0
    for item in items:
        card = db.get(AccountingWorkflowCard, item.card_id)
        if card is None:
            continue
        if item.status == "scheduled" and _as_utc(item.due_at) <= _as_utc(current):
            item.status = "contact_due"
            item.updated_at = current
            due_count += 1
            _audit(
                db,
                tenant_id=card.tenant_id,
                card_id=card.id,
                user=user,
                action="accounting_workflow_followup_due",
                entity_type="accounting_workflow_followup",
                entity_id=item.id,
            )
        if (
            item.status == "waiting_after_repeat"
            and item.escalation_due_at
            and _as_utc(item.escalation_due_at) <= _as_utc(current)
        ):
            item.status = "escalated"
            item.supervisor_notified_at = current
            item.updated_at = current
            escalated_count += 1
            _audit(
                db,
                tenant_id=card.tenant_id,
                card_id=card.id,
                user=user,
                action="accounting_workflow_supervisor_notified",
                entity_type="accounting_workflow_followup",
                entity_id=item.id,
            )
    db.flush()
    return {"due": due_count, "escalated": escalated_count}


def _invalidate_deliveries(
    db: Session,
    card: AccountingWorkflowCard,
    user: User,
    *,
    reason: str,
) -> None:
    now = security.utcnow()
    for item in _deliveries(db, card.id):
        if item.invalidated_at is not None:
            continue
        item.invalidated_at = now
        item.invalidation_reason = reason
        followups = list(
            db.scalars(
                select(AccountingWorkflowFollowup).where(
                    AccountingWorkflowFollowup.delivery_id == item.id,
                    AccountingWorkflowFollowup.status != "completed",
                )
            )
        )
        for followup in followups:
            followup.status = "completed"
            followup.completed_at = now
            followup.result = f"Delivery invalidated: {reason}"
            followup.updated_by_user_id = user.id
            followup.updated_at = now
            _audit(
                db,
                tenant_id=card.tenant_id,
                card_id=card.id,
                user=user,
                action="accounting_workflow_followup_cancelled",
                entity_type="accounting_workflow_followup",
                entity_id=followup.id,
                payload={"reason": reason},
            )
        _audit(
            db,
            tenant_id=card.tenant_id,
            card_id=card.id,
            user=user,
            action="accounting_workflow_delivery_invalidated",
            entity_type="accounting_workflow_delivery",
            entity_id=item.id,
            payload={"reason": reason},
        )


def _active_final_delivery(
    db: Session, card_id: str
) -> AccountingWorkflowDelivery | None:
    return db.scalar(
        select(AccountingWorkflowDelivery)
        .where(
            AccountingWorkflowDelivery.card_id == card_id,
            AccountingWorkflowDelivery.is_preliminary.is_(False),
            AccountingWorkflowDelivery.invalidated_at.is_(None),
        )
        .order_by(AccountingWorkflowDelivery.sent_at.desc())
    )


def _tasks(db: Session, card_id: str) -> list[AccountingWorkflowTask]:
    return list(
        db.scalars(
            select(AccountingWorkflowTask).where(
                AccountingWorkflowTask.card_id == card_id
            )
        )
    )


def _deliveries(db: Session, card_id: str) -> list[AccountingWorkflowDelivery]:
    return list(
        db.scalars(
            select(AccountingWorkflowDelivery)
            .where(AccountingWorkflowDelivery.card_id == card_id)
            .order_by(AccountingWorkflowDelivery.sent_at.desc())
        )
    )


def _followups(db: Session, card_id: str) -> list[AccountingWorkflowFollowup]:
    return list(
        db.scalars(
            select(AccountingWorkflowFollowup)
            .where(AccountingWorkflowFollowup.card_id == card_id)
            .order_by(AccountingWorkflowFollowup.created_at.desc())
        )
    )


def _comments(db: Session, card_id: str) -> list[AccountingWorkflowComment]:
    return list(
        db.scalars(
            select(AccountingWorkflowComment)
            .where(AccountingWorkflowComment.card_id == card_id)
            .order_by(AccountingWorkflowComment.created_at)
        )
    )


def _audit_events(db: Session, card_id: str) -> list[AccountingWorkflowAuditEvent]:
    return list(
        db.scalars(
            select(AccountingWorkflowAuditEvent)
            .where(AccountingWorkflowAuditEvent.card_id == card_id)
            .order_by(AccountingWorkflowAuditEvent.created_at)
        )
    )


def _current_task_revision(
    db: Session, task: AccountingWorkflowTask
) -> AccountingWorkflowReportRevision | None:
    return db.scalar(
        select(AccountingWorkflowReportRevision).where(
            AccountingWorkflowReportRevision.task_id == task.id,
            AccountingWorkflowReportRevision.is_current_for_task.is_(True),
        )
    )


def _task_payload(task: AccountingWorkflowTask) -> dict[str, object]:
    return {
        "id": task.id,
        "reportKind": task.report_kind,
        "status": task.status,
        "reportId": task.current_report_id,
        "payloadSha256": task.current_payload_sha256,
        "final": task.is_final,
        "reviewedAt": task.reviewed_at.isoformat() if task.reviewed_at else None,
        "factsConfirmedAt": (
            task.facts_confirmed_at.isoformat() if task.facts_confirmed_at else None
        ),
        "textApprovedAt": (
            task.text_approved_at.isoformat() if task.text_approved_at else None
        ),
        "blockingReason": task.blocking_reason,
        "updatedAt": task.updated_at.isoformat(),
    }


def _delivery_payload(
    db: Session, item: AccountingWorkflowDelivery
) -> dict[str, object]:
    attachment = db.get(AccountingWorkflowAttachment, item.attachment_id)
    return {
        "id": item.id,
        "reportId": item.report_id,
        "payloadSha256": item.payload_sha256,
        "sentAt": item.sent_at.isoformat(),
        "channel": item.delivery_channel,
        "channelDetail": item.channel_detail,
        "maskedRecipient": item.masked_recipient,
        "contactResult": item.contact_result,
        "preliminary": item.is_preliminary,
        "invalidatedAt": item.invalidated_at.isoformat()
        if item.invalidated_at
        else None,
        "invalidationReason": item.invalidation_reason,
        "attachment": (
            {
                "id": attachment.id,
                "name": attachment.original_name,
                "contentType": attachment.content_type,
                "byteSize": attachment.byte_size,
                "sha256": attachment.sha256,
            }
            if attachment
            else None
        ),
    }


def _followup_payload(item: AccountingWorkflowFollowup) -> dict[str, object]:
    return {
        "id": item.id,
        "deliveryId": item.delivery_id,
        "status": item.status,
        "dueAt": item.due_at.isoformat(),
        "repeatedAt": item.repeated_at.isoformat() if item.repeated_at else None,
        "escalationDueAt": (
            item.escalation_due_at.isoformat() if item.escalation_due_at else None
        ),
        "supervisorNotifiedAt": (
            item.supervisor_notified_at.isoformat()
            if item.supervisor_notified_at
            else None
        ),
        "completedAt": item.completed_at.isoformat() if item.completed_at else None,
        "result": item.result,
    }


def _comment_payload(db: Session, item: AccountingWorkflowComment) -> dict[str, object]:
    user = db.get(User, item.user_id)
    return {
        "id": item.id,
        "userId": item.user_id,
        "userName": user.name if user else "",
        "body": item.body,
        "createdAt": item.created_at.isoformat(),
    }


def _audit_payload(
    db: Session, item: AccountingWorkflowAuditEvent
) -> dict[str, object]:
    user = db.get(User, item.user_id) if item.user_id else None
    return {
        "id": item.id,
        "userId": item.user_id,
        "userName": user.name if user else "Система",
        "action": item.action,
        "entityType": item.entity_type,
        "entityId": item.entity_id,
        "payload": item.payload,
        "createdAt": item.created_at.isoformat(),
    }


def _task_audit(
    db: Session,
    card: AccountingWorkflowCard,
    task: AccountingWorkflowTask,
    user: User,
    action: str,
    payload: dict[str, object] | None = None,
) -> None:
    _audit(
        db,
        tenant_id=card.tenant_id,
        card_id=card.id,
        user=user,
        action=action,
        entity_type="accounting_workflow_task",
        entity_id=task.id,
        payload={"reportKind": task.report_kind, **(payload or {})},
    )


def _audit(
    db: Session,
    *,
    tenant_id: str,
    card_id: str | None,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object] | None = None,
) -> None:
    values = payload or {}
    db.add(
        AccountingWorkflowAuditEvent(
            id=repository.new_id("workflow_audit"),
            tenant_id=tenant_id,
            card_id=card_id,
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=values,
            created_at=security.utcnow(),
        )
    )
    repository.audit(
        db,
        action=action,
        user=user,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={"workflowCardId": card_id, **values},
    )


def _safe_text(
    value: str,
    *,
    field: str,
    min_length: int = 0,
    max_length: int,
) -> None:
    normalized = value.strip()
    if len(normalized) < min_length or len(normalized) > max_length:
        raise WorkflowError(f"{field} length is invalid")
    if SAFE_TEXT_FORBIDDEN.search(normalized):
        raise WorkflowError(f"{field} contains a forbidden secret marker")
