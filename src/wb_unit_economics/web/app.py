from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from chatkit.server import NonStreamingResult, StreamingResult
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from wb_unit_economics.client_report import (
    CLIENT_REPORT_CONTRACT_VERSION,
    ClientAnalyticalReportArtifacts,
    build_client_analytical_report,
)
from wb_unit_economics.report_exports import (
    artifact_record,
    write_ozon_diagnostics_excel,
)
from wb_unit_economics.web import (
    accounting_workflow,
    integrations,
    mapping_service,
    providers,
    repository,
    security,
)
from wb_unit_economics.web.ai import AiAnalyst
from wb_unit_economics.web.chatkit_server import (
    CabinetChatKitContext,
    CabinetChatKitServer,
    CabinetChatKitStore,
)
from wb_unit_economics.web.dashboard_payload import build_dashboard_payload
from wb_unit_economics.web.database import (
    init_db,
    make_engine,
    make_session_factory,
    schema_version,
)
from wb_unit_economics.web.models import (
    ClientCompany,
    ReportRun,
    SourceRefreshRun,
    User,
)
from wb_unit_economics.web.refresh import (
    AutoRefreshBusyError,
    AutoRefreshDisabledError,
    AutoRefreshUnavailableError,
    OnecAutoRefreshService,
)
from wb_unit_economics.web.report_kinds import (
    ACCOUNTING_REPORT_KINDS,
    MARKETPLACE_UNIT_ECONOMICS,
    require_report_kind,
)
from wb_unit_economics.web.report_scope import (
    last_closed_week_period,
    report_summary_for_last_closed_week,
    report_summary_for_period,
)
from wb_unit_economics.web.reports.excel import write_scenario_excel
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    SourceRefreshBusyError,
    SourceRefreshConfigError,
    SourceRefreshDisabledError,
    SourceRefreshService,
    default_period_for_mode,
    source_refresh_progress_payload,
)
from wb_unit_economics.web.source_refresh_worker import (
    SourceRefreshWorkerLaunchError,
    enqueue_source_refresh_worker,
    launch_source_refresh_worker,
    production_source_refresh_worker_launcher,
)

STATIC_DIR = Path(__file__).with_name("static")
WEB_BUILD_ID = "20260724-runtime-contours-cleanup-v1"
MAPPING_UPLOAD_ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt"}
MAPPING_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
REPORT_ENDPOINT_SLOW_SECONDS = 5.0
logger = logging.getLogger(__name__)
LOGISTICS_PERIOD_ERROR_OPENAPI = {
    400: {
        "description": "Некорректный период анализа логистики.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "invalid_logistics_period",
                        "message": "Период должен находиться внутри отчёта.",
                        "reportPeriodStart": "2026-04-06",
                        "reportPeriodEnd": "2026-04-12",
                    }
                }
            }
        },
    }
}


def _logistics_period(
    report: ReportRun,
    period_start: date | None,
    period_end: date | None,
) -> tuple[date, date]:
    effective_start = period_start or report.period_start
    effective_end = period_end or report.period_end
    if (
        effective_start > effective_end
        or effective_start < report.period_start
        or effective_end > report.period_end
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_logistics_period",
                "message": (
                    "Период логистики должен находиться внутри периода отчёта, "
                    "а дата начала не может быть позже даты окончания."
                ),
                "reportPeriodStart": report.period_start.isoformat(),
                "reportPeriodEnd": report.period_end.isoformat(),
            },
        )
    return effective_start, effective_end


def _run_report_generation_background(
    session_factory: sessionmaker[Session],
    source_refresh_service: SourceRefreshService,
    generation_run_id: str,
) -> None:
    with session_factory() as db:
        source_refresh_service.run_existing(
            db,
            generation_run_id,
            worker_id=f"background:{generation_run_id}",
        )
        db.commit()


def _log_report_endpoint_timing(
    *,
    endpoint: str,
    report_id: str,
    started_at: float,
    outcome: str,
) -> None:
    duration_seconds = time.perf_counter() - started_at
    log = (
        logger.warning
        if duration_seconds > REPORT_ENDPOINT_SLOW_SECONDS
        else logger.info
    )
    log(
        "report_endpoint_timing endpoint=%s report_id=%s outcome=%s duration_ms=%.1f",
        endpoint,
        report_id,
        outcome,
        duration_seconds * 1000,
    )


def _require_enabled_report_kind_or_404(
    user: User,
    *,
    tenant_id: str,
    report_kind: str,
    settings: WebSettings,
) -> None:
    try:
        definition = require_report_kind(report_kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="report kind not found") from exc
    if report_kind not in settings.enabled_report_kind_set:
        raise HTTPException(status_code=404, detail="report kind not found")
    if not repository.roles_for_tenant(user, tenant_id).intersection(definition.roles):
        raise HTTPException(status_code=404, detail="report kind not found")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    remember_me: bool = False


class ThreadCreateRequest(BaseModel):
    report_id: str | None = None
    client_id: str | None = None
    title: str = "AI-аналитик"
    scope: dict[str, Any] = Field(default_factory=dict)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class ClientDraftSaveRequest(BaseModel):
    content: str = Field(min_length=1, max_length=40000)
    instruction: str = Field(default="", max_length=8000)
    thread_id: str | None = None


class ClientDraftRefineRequest(BaseModel):
    instruction: str = Field(default="Собрать черновик", max_length=8000)
    action: str = Field(default="assemble", max_length=80)
    thread_id: str | None = None


class ClientDraftFinalizeRequest(BaseModel):
    revision: int | None = None


class AdminUserCreateRequest(BaseModel):
    email: EmailStr
    name: str = ""
    role: str = Field(pattern="^(client|consultant|admin)$")
    client_id: str | None = None
    tenant_id: str | None = None
    password: str | None = Field(default=None, min_length=10)


class ClientCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tenant_id: str = Field(default="", max_length=120)
    client_id: str = Field(default="", max_length=120)
    companies: list[str] = Field(default_factory=list)
    cabinets: list[str] = Field(default_factory=list)


class WbCabinetSaveRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(default="", max_length=200)
    status: str = Field(default="active", pattern="^(active|disabled)$")


class OnecOrganizationLinkRequest(BaseModel):
    onec_organization_id: str = Field(default="", max_length=120)


class TaxProfileOverrideCreateRequest(BaseModel):
    tax_system: str = Field(min_length=1, max_length=120)
    vat_rate: Decimal = Field(ge=0, le=100)
    vat_mode: str = Field(pattern="^(included|excluded|none)$")
    vat_deduction_mode: str = Field(
        default="unknown",
        pattern="^(allowed|not_allowed|not_applicable|unknown)$",
    )
    revenue_tax_rate: Decimal = Field(ge=0, le=1)
    income_tax_kind: str = Field(default="", max_length=120)
    valid_from: date
    valid_to: date | None = None
    reason: str = Field(min_length=1, max_length=2000)
    rate_basis_kind: str = Field(default="", max_length=120)
    basis_document: str = Field(default="", max_length=1000)
    source_object_ids: list[str] = Field(default_factory=list, max_length=100)


class TaxRateBasisConfirmRequest(BaseModel):
    rate_basis_kind: str = Field(pattern="^regional_preference$")
    basis_document: str = Field(min_length=1, max_length=1000)
    source_object_ids: list[str] = Field(default_factory=list, max_length=100)


class InputVatPolicyCreateRequest(BaseModel):
    mode: str = Field(pattern="^(accounting_fact|management_assumption)$")
    product_vat_basis: str = Field(
        default="sales_cost_difference",
        pattern="^sales_cost_difference$",
    )
    service_vat_basis: str = Field(
        default="wb_gross_22_122",
        pattern="^wb_gross_22_122$",
    )
    valid_from: date
    valid_to: date | None = None
    reason: str = Field(min_length=1, max_length=2000)


class AdminUserPatchRequest(BaseModel):
    name: str | None = None
    role: str | None = Field(default=None, pattern="^(client|consultant|admin)$")
    is_active: bool | None = None
    client_id: str | None = None
    tenant_id: str | None = None


class PasswordResetRequest(BaseModel):
    client_id: str | None = None
    tenant_id: str | None = None


class ReportImportRequest(BaseModel):
    workbook_path: str | None = None
    report_id: str | None = None
    client_id: str | None = None
    tenant_id: str | None = None
    tenant_name: str | None = None


class ReportGenerateRequest(BaseModel):
    reportKind: str = Field(pattern="^(month_close_control|tax_load)$")
    organizationId: str = Field(min_length=1, max_length=240)
    periodMonth: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class LiveCheckRequest(BaseModel):
    lookup: str = Field(min_length=1, max_length=240)


class OnecAutoRefreshRequest(BaseModel):
    reason: str = Field(default="Аналитик запросил дозагрузку 1С", max_length=4000)
    thread_id: str | None = None


class AnalyticalReportRequest(BaseModel):
    branded: bool = True
    scope: str = Field(
        default="last_closed_week",
        pattern="^(last_closed_week|full|custom)$",
    )
    periodStart: date | None = None
    periodEnd: date | None = None


class PublishWithTasksRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    confirm_blocking_tasks: bool = False


class TenantIntegrationSaveRequest(BaseModel):
    client_id: str | None = None
    tenant_id: str | None = None
    label: str = Field(default="", max_length=200)
    connection_role: str = Field(default="", max_length=80)
    cabinet_name: str = Field(default="", max_length=200)
    organization_name: str = Field(default="", max_length=200)
    secret: str = Field(min_length=1, max_length=8000)


class TenantIntegrationCreateRequest(TenantIntegrationSaveRequest):
    provider: str = Field(min_length=1, max_length=120)


class TenantIntegrationActionRequest(BaseModel):
    client_id: str | None = None
    tenant_id: str | None = None


class SourceRefreshRequest(BaseModel):
    mode: str = Field(
        default="full",
        pattern="^(daily|incremental|weekly|full|onec-only|ozon-only)$",
    )
    dry_run: bool = False
    reason: str = Field(default="", max_length=4000)
    period_start: date | None = None
    period_end: date | None = None
    resume_mode: str = Field(default="auto", pattern="^(auto|never)$")
    resume_from_run_id: str | None = Field(default=None, max_length=160)


class MappingRebuildRequest(BaseModel):
    refresh_run_id: str | None = None


class MappingAcceptRequest(BaseModel):
    candidate_id: str = Field(default="", max_length=160)
    onec_mapping_item_id: str = Field(default="", max_length=160)
    reason: str = Field(default="", max_length=2000)


class MappingRejectRequest(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(default="", max_length=2000)


class MappingReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AccountingWorkflowMonthlyRunRequest(BaseModel):
    tenantId: str = Field(min_length=1, max_length=120)
    periodMonth: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    responsibleUserId: str | None = Field(default=None, max_length=160)
    supervisorUserId: str | None = Field(default=None, max_length=160)


class AccountingWorkflowCorrectionRequest(BaseModel):
    supersedesCardId: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2000)


class AccountingWorkflowTransitionRequest(BaseModel):
    targetStage: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=2000)
    responsibleUserId: str | None = Field(default=None, max_length=160)
    supervisorUserId: str | None = Field(default=None, max_length=160)


class AccountingWorkflowTaskActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    reportId: str | None = Field(default=None, max_length=160)
    payloadSha256: str | None = Field(default=None, max_length=128)
    reason: str = Field(default="", max_length=2000)


class AccountingWorkflowDeliveryRequest(BaseModel):
    sentAt: datetime
    channel: str = Field(min_length=1, max_length=80)
    channelDetail: str = Field(default="", max_length=500)
    maskedRecipient: str = Field(min_length=3, max_length=240)
    attachmentId: str = Field(min_length=1, max_length=160)
    contactResult: str = Field(default="", max_length=2000)
    preliminary: bool = False


class AccountingWorkflowCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class AccountingWorkflowSupervisorRequest(BaseModel):
    tenantId: str = Field(min_length=1, max_length=120)
    userId: str = Field(min_length=1, max_length=160)
    active: bool = True


class AccountingWorkflowFollowupActionRequest(BaseModel):
    action: str = Field(pattern="^(repeat|complete)$")
    result: str = Field(min_length=1, max_length=2000)


class AccountingWorkflowDueRunRequest(BaseModel):
    tenantId: str = Field(min_length=1, max_length=120)


def create_app(
    settings: WebSettings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    auto_refresh_service: Any | None = None,
) -> FastAPI:
    runtime_settings = settings or WebSettings()
    if session_factory is None:
        engine = make_engine(
            runtime_settings.database_url,
            statement_timeout_ms=runtime_settings.postgres_statement_timeout_ms,
        )
        init_db(engine, run_backfill=False)
        session_factory = make_session_factory(engine)
    worker_launcher = production_source_refresh_worker_launcher(runtime_settings)
    refresh_service = auto_refresh_service or OnecAutoRefreshService(
        runtime_settings,
        worker_launcher=worker_launcher,
    )
    source_refresh_service = getattr(refresh_service, "source_refresh_service", None)
    if source_refresh_service is None:
        source_refresh_service = SourceRefreshService(runtime_settings)
    analyst = AiAnalyst(runtime_settings, auto_refresh_service=refresh_service)
    app = FastAPI(title="Shumeyko WB Unit Economics Cabinet", version="0.2.0")
    app.state.settings = runtime_settings
    app.state.session_factory = session_factory
    app.state.analyst = analyst
    app.state.chatkit_server = CabinetChatKitServer(CabinetChatKitStore())
    app.state.auto_refresh_service = refresh_service
    app.state.source_refresh_service = source_refresh_service
    app.state.source_refresh_worker_launcher = worker_launcher
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def cabinet_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/cabinet")
    def cabinet() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/ai")
    def ai_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/integrations")
    def integrations_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/accounting-workflows")
    def accounting_workflows_page(current: CurrentUser) -> FileResponse:
        if not runtime_settings.accounting_workflow_enabled:
            raise HTTPException(status_code=404, detail="page not found")
        if not repository.has_role(current, repository.STAFF_ROLES):
            raise HTTPException(status_code=404, detail="page not found")
        return FileResponse(STATIC_DIR / "accounting-workflows.html")

    @app.get("/api/health")
    def health(db: DbSession) -> dict[str, Any]:
        bind = db.get_bind()
        health_tenant_id = runtime_settings.source_refresh_tenant.strip()
        report_conditions = [
            ReportRun.report_kind == MARKETPLACE_UNIT_ECONOMICS,
            ReportRun.publication_status == "published",
            ReportRun.is_current.is_(True),
        ]
        if health_tenant_id:
            report_conditions.append(ReportRun.tenant_id == health_tenant_id)
        latest_report = db.scalar(
            select(ReportRun)
            .where(*report_conditions)
            .order_by(ReportRun.generated_at.desc())
        )
        if not health_tenant_id and latest_report is not None:
            health_tenant_id = latest_report.tenant_id
        refresh_conditions = [SourceRefreshRun.mode != "report-generation"]
        if health_tenant_id:
            refresh_conditions.append(SourceRefreshRun.tenant_id == health_tenant_id)
        latest_refresh = db.scalar(
            select(SourceRefreshRun)
            .where(*refresh_conditions)
            .order_by(SourceRefreshRun.created_at.desc())
        )
        active_refresh = db.scalar(
            select(SourceRefreshRun)
            .where(
                *refresh_conditions,
                SourceRefreshRun.status.in_(repository.ACTIVE_SOURCE_REFRESH_STATUSES),
                SourceRefreshRun.finished_at.is_(None),
            )
            .order_by(SourceRefreshRun.created_at.desc())
        )
        latest_completed_refresh = db.scalar(
            select(SourceRefreshRun)
            .where(
                *refresh_conditions,
                SourceRefreshRun.finished_at.is_not(None),
                SourceRefreshRun.status != "blocked_active_refresh",
            )
            .order_by(
                SourceRefreshRun.finished_at.desc(),
                SourceRefreshRun.created_at.desc(),
            )
        )
        displayed_refresh = active_refresh or latest_refresh
        degraded_statuses = {
            "failed",
            "needs_configuration",
            "blocked_active_refresh",
            "blocked_low_disk",
            "needs_full_refresh",
        }
        expected_disabled_statuses = (
            {"needs_configuration", "needs_full_refresh"}
            if runtime_settings.runtime_environment == "test"
            and not runtime_settings.external_integrations_enabled
            else set()
        )
        health_refresh = (
            latest_completed_refresh
            if latest_completed_refresh is not None
            and latest_completed_refresh.status in degraded_statuses
            else active_refresh or latest_completed_refresh or latest_refresh
        )
        health_status = (
            "degraded"
            if health_refresh is not None
            and health_refresh.status in degraded_statuses
            and health_refresh.status not in expected_disabled_statuses
            else "ok"
        )
        return {
            "status": health_status,
            "backendBuildId": WEB_BUILD_ID,
            "staticBuildId": WEB_BUILD_ID,
            "runtimeEnvironment": runtime_settings.runtime_environment,
            "maintenanceMessage": runtime_settings.maintenance_message.strip()[:500],
            "databaseType": bind.dialect.name,
            "schemaVersion": schema_version(bind),
            "aiConfigured": bool(runtime_settings.resolved_openai_api_key),
            "aiModel": runtime_settings.openai_model,
            "chatkitEnabled": runtime_settings.chatkit_enabled,
            "sourceRefreshTenantId": health_tenant_id,
            "latestPublishedReportId": latest_report.id if latest_report else "",
            "latestSourceRefreshStatus": displayed_refresh.status
            if displayed_refresh
            else "",
            "latestSourceRefreshRunId": displayed_refresh.id
            if displayed_refresh
            else "",
            "latestSourceRefreshMode": displayed_refresh.mode
            if displayed_refresh
            else "",
            "latestSourceRefreshCreatedAt": (
                displayed_refresh.created_at.isoformat() if displayed_refresh else ""
            ),
            "latestSourceRefreshActive": active_refresh is not None,
            "latestSourceRefreshHeartbeatAt": (
                active_refresh.heartbeat_at.isoformat()
                if active_refresh is not None and active_refresh.heartbeat_at
                else ""
            ),
            "latestCompletedSourceRefreshStatus": (
                latest_completed_refresh.status if latest_completed_refresh else ""
            ),
            "sourceRefreshHealthStatus": (
                health_refresh.status if health_refresh else ""
            ),
        }

    @app.get("/api/ai/config")
    def ai_config(current: CurrentUser) -> dict[str, Any]:
        return {
            "transport": "chatkit" if runtime_settings.chatkit_enabled else "sse",
            "chatkitEnabled": runtime_settings.chatkit_enabled,
            "attachmentsEnabled": False,
            "externalActionsEnabled": False,
            "historyLimit": 20,
        }

    @app.post("/api/chatkit")
    async def chatkit_protocol(
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> Response:
        if not runtime_settings.chatkit_enabled:
            raise HTTPException(status_code=404, detail="ChatKit is disabled")
        origin = request.headers.get("origin", "")
        host = request.headers.get("host", "")
        if origin and urlparse(origin).netloc != host:
            raise HTTPException(status_code=403, detail="cross-origin request denied")
        raw_request = await request.body()
        try:
            protocol_request = json.loads(raw_request)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="invalid ChatKit request"
            ) from exc
        metadata = protocol_request.get("metadata") or {}
        report_id = str(metadata.get("reportId") or "")
        client_id = str(metadata.get("clientId") or "")
        scope = metadata.get("scope") or {}
        if not isinstance(scope, dict):
            raise HTTPException(status_code=400, detail="invalid ChatKit scope")
        if protocol_request.get("type") == "threads.create":
            if not report_id:
                raise HTTPException(status_code=409, detail="reportId is required")
            report = _require_report_or_404(db, current, report_id)
            if client_id and client_id != report.client_id:
                raise HTTPException(
                    status_code=409, detail="report/client scope mismatch"
                )
            client_id = report.client_id
        context = CabinetChatKitContext(
            db=db,
            user=current,
            analyst=app.state.analyst,
            report_id=report_id,
            client_id=client_id,
            scope=scope,
        )
        try:
            result = await app.state.chatkit_server.process(raw_request, context)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="thread not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if isinstance(result, NonStreamingResult):
            db.commit()
            return Response(content=result.json, media_type="application/json")

        assert isinstance(result, StreamingResult)

        async def stream_chatkit():
            try:
                async for chunk in result:
                    yield chunk
                db.commit()
            except Exception:
                db.rollback()
                raise

        return StreamingResponse(
            stream_chatkit(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/auth/login")
    def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
        db: DbSession,
    ) -> dict[str, Any]:
        email = payload.email.lower()
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not security.verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not runtime_settings.client_login_enabled and not repository.has_role(
            user, repository.STAFF_ROLES
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        ttl_hours = (
            runtime_settings.remember_me_session_ttl_hours
            if payload.remember_me
            else runtime_settings.session_ttl_hours
        )
        token = repository.create_session(
            db,
            user,
            ttl_hours=ttl_hours,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=request.client.host if request.client else "",
        )
        repository.audit(
            db, action="login", user=user, tenant_id=_first_tenant_id(user)
        )
        clients = repository.list_clients_for_user(db, user)
        db.commit()
        response.set_cookie(
            runtime_settings.session_cookie_name,
            token,
            max_age=ttl_hours * 3600,
            httponly=True,
            secure=runtime_settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return me_payload(
            user,
            clients,
            accounting_workflow_enabled=runtime_settings.accounting_workflow_enabled,
            logistics_analysis_enabled=(runtime_settings.logistics_analysis_enabled),
            logistics_analysis_client_enabled=(
                runtime_settings.logistics_analysis_client_enabled
            ),
            logistics_factors_enabled=runtime_settings.logistics_factors_enabled,
            logistics_factors_client_enabled=(
                runtime_settings.logistics_factors_client_enabled
            ),
            logistics_tariffs_enabled=runtime_settings.logistics_tariffs_enabled,
            logistics_tariffs_client_enabled=(
                runtime_settings.logistics_tariffs_client_enabled
            ),
            logistics_routes_enabled=runtime_settings.logistics_routes_enabled,
            logistics_routes_client_enabled=(
                runtime_settings.logistics_routes_client_enabled
            ),
            logistics_measurements_enabled=(
                runtime_settings.logistics_measurements_enabled
            ),
            logistics_measurements_client_enabled=(
                runtime_settings.logistics_measurements_client_enabled
            ),
            logistics_return_reasons_enabled=(
                runtime_settings.logistics_return_reasons_enabled
            ),
            logistics_return_reasons_client_enabled=(
                runtime_settings.logistics_return_reasons_client_enabled
            ),
        )

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, db: DbSession) -> dict[str, str]:
        token = request.cookies.get(runtime_settings.session_cookie_name)
        if token:
            user = repository.get_user_by_session(db, token)
            repository.delete_session(db, token)
            if user:
                repository.audit(
                    db,
                    action="logout",
                    user=user,
                    tenant_id=_first_tenant_id(user),
                )
            db.commit()
        response.delete_cookie(runtime_settings.session_cookie_name, path="/")
        return {"status": "ok"}

    @app.get("/api/me")
    def me(current: CurrentUser, db: DbSession) -> dict[str, Any]:
        clients = repository.list_clients_for_user(db, current)
        db.commit()
        return me_payload(
            current,
            clients,
            accounting_workflow_enabled=runtime_settings.accounting_workflow_enabled,
            logistics_analysis_enabled=(runtime_settings.logistics_analysis_enabled),
            logistics_analysis_client_enabled=(
                runtime_settings.logistics_analysis_client_enabled
            ),
            logistics_factors_enabled=runtime_settings.logistics_factors_enabled,
            logistics_factors_client_enabled=(
                runtime_settings.logistics_factors_client_enabled
            ),
            logistics_tariffs_enabled=runtime_settings.logistics_tariffs_enabled,
            logistics_tariffs_client_enabled=(
                runtime_settings.logistics_tariffs_client_enabled
            ),
            logistics_routes_enabled=runtime_settings.logistics_routes_enabled,
            logistics_routes_client_enabled=(
                runtime_settings.logistics_routes_client_enabled
            ),
            logistics_measurements_enabled=(
                runtime_settings.logistics_measurements_enabled
            ),
            logistics_measurements_client_enabled=(
                runtime_settings.logistics_measurements_client_enabled
            ),
            logistics_return_reasons_enabled=(
                runtime_settings.logistics_return_reasons_enabled
            ),
            logistics_return_reasons_client_enabled=(
                runtime_settings.logistics_return_reasons_client_enabled
            ),
        )

    @app.get("/api/accounting-workflows/config")
    def accounting_workflow_config(
        request: Request,
        current: CurrentUser,
        db: DbSession,
        tenantId: str | None = None,
    ) -> dict[str, Any]:
        try:
            accounting_workflow.require_enabled(runtime_settings)
            tenant_id = _workflow_tenant_id(current, tenantId)
            accounting_workflow.require_staff(current, tenant_id)
            return {
                "enabled": True,
                "tenantId": tenant_id,
                "isSupervisor": accounting_workflow.is_supervisor(
                    db, current, tenant_id
                ),
                "csrfToken": _workflow_csrf_token(request, runtime_settings),
                "stages": sorted(accounting_workflow.CARD_STAGES),
                "deliveryChannels": sorted(accounting_workflow.DELIVERY_CHANNELS),
                "evidenceContentTypes": sorted(
                    accounting_workflow.ALLOWED_EVIDENCE_TYPES
                ),
                "evidenceMaxBytes": (
                    runtime_settings.accounting_workflow_evidence_max_bytes
                ),
                "staffUsers": accounting_workflow.list_staff_users(
                    db, current, tenant_id
                ),
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.get("/api/accounting-workflows/supervisors")
    def accounting_workflow_supervisors(
        current: CurrentUser,
        db: DbSession,
        tenantId: str,
    ) -> dict[str, Any]:
        try:
            accounting_workflow.require_enabled(runtime_settings)
            return {
                "items": accounting_workflow.list_supervisors(db, current, tenantId)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.get("/api/accounting-workflows")
    def accounting_workflow_cards(
        current: CurrentUser,
        db: DbSession,
        tenantId: str | None = None,
        clientId: str | None = None,
        organizationId: str | None = None,
        periodMonth: str | None = None,
        stage: str | None = None,
        responsibleUserId: str | None = None,
        supervisorUserId: str | None = None,
        overdue: bool | None = None,
    ) -> dict[str, Any]:
        try:
            accounting_workflow.require_enabled(runtime_settings)
            items = accounting_workflow.list_cards(
                db,
                user=current,
                tenant_id=tenantId,
                client_id=clientId,
                organization_id=organizationId,
                report_period=(_workflow_period(periodMonth) if periodMonth else None),
                stage=stage,
                responsible_user_id=responsibleUserId,
                supervisor_user_id=supervisorUserId,
                overdue=overdue,
            )
            return {"items": items}
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.get("/api/accounting-workflows/{card_id}")
    def accounting_workflow_card(
        card_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            accounting_workflow.require_enabled(runtime_settings)
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card_id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/monthly-runs")
    def accounting_workflow_monthly_run(
        payload: AccountingWorkflowMonthlyRunRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            result = accounting_workflow.create_month_cards(
                db,
                settings=runtime_settings,
                tenant_id=payload.tenantId,
                report_period=_workflow_period(payload.periodMonth),
                user=current,
                creation_kind="manual_catch_up",
                responsible_user_id=payload.responsibleUserId,
                supervisor_user_id=payload.supervisorUserId,
            )
            db.commit()
            return result
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/corrections")
    def accounting_workflow_correction(
        payload: AccountingWorkflowCorrectionRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            card = accounting_workflow.create_correction_card(
                db,
                settings=runtime_settings,
                user=current,
                supersedes_card_id=payload.supersedesCardId,
                reason=payload.reason,
            )
            db.commit()
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card.id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/{card_id}/transitions")
    def accounting_workflow_transition(
        card_id: str,
        payload: AccountingWorkflowTransitionRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            card = accounting_workflow.transition_card(
                db,
                user=current,
                card_id=card_id,
                target_stage=payload.targetStage,
                reason=payload.reason,
                responsible_user_id=payload.responsibleUserId,
                supervisor_user_id=payload.supervisorUserId,
            )
            db.commit()
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card.id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/{card_id}/tasks/{task_id}/actions")
    def accounting_workflow_task_action(
        card_id: str,
        task_id: str,
        payload: AccountingWorkflowTaskActionRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            accounting_workflow.task_action(
                db,
                user=current,
                card_id=card_id,
                task_id=task_id,
                action=payload.action,
                report_id=payload.reportId,
                payload_sha256=payload.payloadSha256,
                reason=payload.reason,
            )
            db.commit()
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card_id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/{card_id}/evidence")
    async def accounting_workflow_evidence_upload(
        card_id: str,
        request: Request,
        current: CurrentUser,
        db: DbSession,
        evidence: Annotated[UploadFile, File()],
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            accounting_workflow.require_enabled(runtime_settings)
            content = await evidence.read(
                runtime_settings.accounting_workflow_evidence_max_bytes + 1
            )
            item = accounting_workflow.save_attachment(
                db,
                settings=runtime_settings,
                user=current,
                card_id=card_id,
                filename=evidence.filename or "evidence",
                content_type=evidence.content_type or "",
                content=content,
            )
            db.commit()
            return {
                "attachment": {
                    "id": item.id,
                    "name": item.original_name,
                    "contentType": item.content_type,
                    "byteSize": item.byte_size,
                    "sha256": item.sha256,
                }
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.get("/api/accounting-workflows/evidence/{attachment_id}")
    def accounting_workflow_evidence_download(
        attachment_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> FileResponse:
        try:
            accounting_workflow.require_enabled(runtime_settings)
            item = accounting_workflow.require_attachment(db, current, attachment_id)
            path = accounting_workflow.attachment_path(runtime_settings, item)
            return FileResponse(
                path,
                media_type=item.content_type,
                filename=item.original_name,
                headers={"Cache-Control": "no-store"},
            )
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/{card_id}/deliveries")
    def accounting_workflow_delivery(
        card_id: str,
        payload: AccountingWorkflowDeliveryRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            accounting_workflow.require_enabled(runtime_settings)
            accounting_workflow.record_delivery(
                db,
                settings=runtime_settings,
                user=current,
                card_id=card_id,
                sent_at=payload.sentAt,
                delivery_channel=payload.channel,
                channel_detail=payload.channelDetail,
                masked_recipient=payload.maskedRecipient,
                attachment_id=payload.attachmentId,
                contact_result=payload.contactResult,
                preliminary=payload.preliminary,
            )
            db.commit()
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card_id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/{card_id}/comments")
    def accounting_workflow_comment(
        card_id: str,
        payload: AccountingWorkflowCommentRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            accounting_workflow.require_enabled(runtime_settings)
            accounting_workflow.add_comment(
                db, user=current, card_id=card_id, body=payload.body
            )
            db.commit()
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card_id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/{card_id}/followups/{followup_id}/actions")
    def accounting_workflow_followup_action(
        card_id: str,
        followup_id: str,
        payload: AccountingWorkflowFollowupActionRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            accounting_workflow.require_enabled(runtime_settings)
            accounting_workflow.followup_action(
                db,
                settings=runtime_settings,
                user=current,
                card_id=card_id,
                followup_id=followup_id,
                action=payload.action,
                result=payload.result,
            )
            db.commit()
            return {
                "item": accounting_workflow.card_detail_payload(db, current, card_id)
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/followups/run-due")
    def accounting_workflow_followups_run_due(
        payload: AccountingWorkflowDueRunRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, int]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            result = accounting_workflow.process_due_followups(
                db,
                settings=runtime_settings,
                user=current,
                tenant_id=payload.tenantId,
            )
            db.commit()
            return result
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.post("/api/accounting-workflows/supervisors")
    def accounting_workflow_supervisor_save(
        payload: AccountingWorkflowSupervisorRequest,
        request: Request,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        _require_workflow_csrf(request, runtime_settings)
        try:
            accounting_workflow.require_enabled(runtime_settings)
            item = accounting_workflow.grant_supervisor(
                db,
                admin=current,
                tenant_id=payload.tenantId,
                user_id=payload.userId,
                active=payload.active,
            )
            db.commit()
            return {
                "item": {
                    "userId": item.user_id,
                    "active": item.is_active,
                    "grantedAt": item.granted_at.isoformat(),
                    "revokedAt": item.revoked_at.isoformat()
                    if item.revoked_at
                    else None,
                }
            }
        except accounting_workflow.WorkflowError as exc:
            _raise_workflow_http_error(db, exc)

    @app.get("/api/clients")
    def list_clients(current: CurrentUser, db: DbSession) -> dict[str, Any]:
        items = repository.list_clients_for_user(db, current)
        db.commit()
        return {"items": items}

    @app.post("/api/clients")
    def create_client(
        payload: ClientCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            client = repository.create_client_workspace(
                db,
                user=current,
                name=payload.name,
                tenant_id=payload.tenant_id,
                client_id=payload.client_id,
                companies=payload.companies,
                cabinets=payload.cabinets,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"client": repository.client_payload(db, current, client)}

    @app.post("/api/clients/{client_id}/cabinets")
    def create_client_cabinet(
        client_id: str,
        payload: WbCabinetSaveRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            client = repository.upsert_client_wb_cabinet(
                db,
                user=current,
                client_id=client_id,
                display_name=payload.label,
                organization_name=payload.organization_name,
                status=payload.status,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"client": repository.client_payload(db, current, client)}

    @app.get("/api/clients/{client_id}/source-refresh/latest")
    def client_source_refresh_latest(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        mode: str | None = None,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        if mode and mode not in {
            "daily",
            "incremental",
            "weekly",
            "full",
            "onec-only",
            "ozon-only",
        }:
            raise HTTPException(
                status_code=400,
                detail="unsupported source refresh mode",
            )
        payload = repository.source_refresh_status_payload(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            mode=mode,
            include_sensitive=False,
        )
        for key in ("latest", "activeRun", "latestAttempt", "latestCompleted"):
            item = payload.get(key)
            if not item or not item.get("id"):
                continue
            refresh_run = db.get(SourceRefreshRun, item["id"])
            if refresh_run is not None:
                item["progress"] = source_refresh_progress_payload(
                    refresh_run,
                    source_root=runtime_settings.source_refresh_root_path,
                )
        payload["incrementalEnabled"] = bool(
            runtime_settings.source_refresh_incremental_enabled
            and runtime_settings.marketplace_daily_facts_enabled
            and runtime_settings.db_first_reports_enabled
        )
        payload["incrementalWindowDays"] = int(
            runtime_settings.source_refresh_incremental_window_days
        )
        default_period_start, default_period_end = (
            default_period_for_mode(runtime_settings, "full")
        )
        payload["defaultFullPeriod"] = {
            "periodStart": default_period_start.isoformat(),
            "periodEnd": default_period_end.isoformat(),
        }
        return payload

    @app.get("/api/reports/{report_id}/ozon-diagnostics")
    def report_ozon_diagnostics(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        limit: int = 50,
        period_start: date | None = None,
        period_end: date | None = None,
        wb_cabinet_id: str = "",
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        if report.lineage_type != repository.OZON_DRAFT_LINEAGE_TYPE:
            raise HTTPException(status_code=404, detail="Ozon draft not found")
        return repository.ozon_draft_diagnostics_payload(
            db,
            report,
            limit=limit,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
        )

    @app.get("/api/clients/{client_id}/ozon-diagnostics")
    def client_ozon_diagnostics(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        limit: int = 50,
        period_start: date | None = None,
        period_end: date | None = None,
        wb_cabinet_id: str = "",
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        return repository.latest_ozon_diagnostics_payload(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            limit=limit,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
        )

    @app.get("/api/clients/{client_id}/ozon-diagnostics/export.xlsx")
    def client_ozon_diagnostics_export(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        period_start: date | None = None,
        period_end: date | None = None,
        wb_cabinet_id: str = "",
    ) -> FileResponse:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        diagnostics = repository.latest_ozon_diagnostics_payload(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            limit=repository.OZON_PNL_MAX_SOURCE_ROWS,
            preview_max_rows=repository.OZON_PNL_MAX_SOURCE_ROWS,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
        )
        output_dir = (
            runtime_settings.export_root_path
            / "ozon_diagnostics"
            / _safe_path_segment(resolved_client_id)
        ).resolve()
        allowed = runtime_settings.export_root_path.resolve()
        if output_dir != allowed and allowed not in output_dir.parents:
            raise HTTPException(
                status_code=400,
                detail="export path is outside reports",
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        period_label = _ozon_export_period_label(
            diagnostics,
            period_start=period_start,
            period_end=period_end,
        )
        stamp = security.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"ozon_unit_economics_{period_label}_{stamp}.xlsx"
        path = output_dir / filename
        write_ozon_diagnostics_excel(diagnostics, path)
        repository.audit(
            db,
            action="ozon_diagnostics_excel_exported",
            user=current,
            tenant_id=tenant_id,
            entity_type="client",
            entity_id=resolved_client_id,
            payload={
                "periodStart": period_start.isoformat() if period_start else None,
                "periodEnd": period_end.isoformat() if period_end else None,
                "wbCabinetId": wb_cabinet_id,
                "path": str(path.relative_to(allowed)),
            },
        )
        db.commit()
        return FileResponse(
            path,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            filename=filename,
        )

    @app.post("/api/clients/{client_id}/mapping-file")
    async def upload_client_mapping_file(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        file: Annotated[UploadFile, File(...)],
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        target_name, size_bytes = await _save_mapping_upload(
            runtime_settings,
            file,
        )
        import_payload = mapping_service.import_mapping_file(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            path=runtime_settings.source_refresh_mapping_path / target_name,
            user=current,
        )
        repository.audit(
            db,
            action="mapping_file_uploaded",
            user=current,
            tenant_id=tenant_id,
            entity_type="client",
            entity_id=resolved_client_id,
            payload={
                "fileName": target_name,
                "sizeBytes": size_bytes,
                "candidateImport": import_payload,
            },
        )
        db.commit()
        return {
            "status": "uploaded",
            "fileName": target_name,
            "sizeBytes": size_bytes,
            "candidateImport": import_payload,
            "latestSourceRefresh": repository.latest_source_refresh_payload(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                include_sensitive=False,
            ),
        }

    @app.get("/api/clients/{client_id}/mapping/items")
    def client_mapping_items(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        marketplace: str = "",
        status: str = "",
        search: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        return mapping_service.list_mapping_items(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            marketplace=marketplace,
            status=status,
            search=search,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/clients/{client_id}/mapping/items/{item_id}/candidates")
    def client_mapping_candidates(
        client_id: str,
        item_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            return mapping_service.mapping_candidates_payload(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                item_id=item_id,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)

    @app.get("/api/clients/{client_id}/mapping/onec-search")
    def client_mapping_onec_search(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        query: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        return mapping_service.search_onec_items(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            query=query,
            limit=limit,
        )

    @app.post("/api/clients/{client_id}/mapping/items/{item_id}/accept")
    def client_mapping_accept(
        client_id: str,
        item_id: str,
        payload: MappingAcceptRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            result = mapping_service.accept_mapping(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                item_id=item_id,
                user=current,
                candidate_id=payload.candidate_id,
                onec_mapping_item_id=payload.onec_mapping_item_id,
                reason=payload.reason,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)
        db.commit()
        return result

    @app.post("/api/clients/{client_id}/mapping/items/{item_id}/reject")
    def client_mapping_reject(
        client_id: str,
        item_id: str,
        payload: MappingRejectRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            result = mapping_service.reject_candidate(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                item_id=item_id,
                user=current,
                candidate_id=payload.candidate_id,
                reason=payload.reason,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)
        db.commit()
        return result

    @app.post("/api/clients/{client_id}/mapping/items/{item_id}/revoke")
    def client_mapping_revoke(
        client_id: str,
        item_id: str,
        payload: MappingReasonRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            result = mapping_service.revoke_mapping(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                item_id=item_id,
                user=current,
                reason=payload.reason,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)
        db.commit()
        return result

    @app.post("/api/clients/{client_id}/mapping/items/{item_id}/exclude")
    def client_mapping_exclude(
        client_id: str,
        item_id: str,
        payload: MappingReasonRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            result = mapping_service.exclude_item(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                item_id=item_id,
                user=current,
                reason=payload.reason,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)
        db.commit()
        return result

    @app.get("/api/clients/{client_id}/mapping/items/{item_id}/history")
    def client_mapping_history(
        client_id: str,
        item_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            return mapping_service.mapping_history_payload(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                item_id=item_id,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)

    @app.post("/api/clients/{client_id}/mapping/rebuild-candidates")
    def client_mapping_rebuild_candidates(
        client_id: str,
        payload: MappingRebuildRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        try:
            result = mapping_service.rebuild_candidates(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                user=current,
                refresh_run_id=payload.refresh_run_id,
            )
        except mapping_service.MappingServiceError as exc:
            _raise_mapping_error(exc)
        db.commit()
        return result

    @app.get("/api/clients/{client_id}/mapping/export/sku-mapping")
    def client_mapping_export_sku_mapping(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        return mapping_service.export_sku_mapping(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
        )

    @app.post("/api/clients/{client_id}/source-refresh")
    def run_client_source_refresh(
        client_id: str,
        payload: SourceRefreshRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        reason = payload.reason.strip() or (
            "Ручная проверка готовности обновления источников"
            if payload.dry_run
            else (
                "Ручное инкрементальное обновление источников из веб-кабинета"
                if payload.mode == "incremental"
                else "Ручное полное обновление источников из веб-кабинета"
            )
        )
        try:
            if payload.dry_run:
                refresh_payload = app.state.source_refresh_service.run(
                    db,
                    tenant_id=tenant_id,
                    client_id=resolved_client_id,
                    mode=payload.mode,
                    credential_source="tenant",
                    dry_run=True,
                    user=current,
                    reason=reason,
                    period_start=payload.period_start,
                    period_end=payload.period_end,
                    resume_mode=payload.resume_mode,
                    resume_from_run_id=payload.resume_from_run_id,
                )
            else:
                refresh_payload = enqueue_source_refresh_worker(
                    db,
                    source_refresh_service=app.state.source_refresh_service,
                    worker_launcher=app.state.source_refresh_worker_launcher,
                    tenant_id=tenant_id,
                    client_id=resolved_client_id,
                    mode=payload.mode,
                    credential_source="tenant",
                    user=current,
                    reason=reason,
                    period_start=payload.period_start,
                    period_end=payload.period_end,
                    resume_mode=payload.resume_mode,
                    resume_from_run_id=payload.resume_from_run_id,
                )
        except SourceRefreshDisabledError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SourceRefreshBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SourceRefreshConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SourceRefreshWorkerLaunchError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Не удалось запустить отдельный процесс обновления. "
                    "Источники не изменялись."
                ),
            ) from exc
        db.commit()
        refresh_run = db.get(SourceRefreshRun, refresh_payload["id"])
        response = {
            "latest": repository.source_refresh_run_payload(
                refresh_run,
                include_sensitive=False,
            )
            if refresh_run is not None
            else refresh_payload,
        }
        response["incrementalEnabled"] = bool(
            runtime_settings.source_refresh_incremental_enabled
            and runtime_settings.marketplace_daily_facts_enabled
            and runtime_settings.db_first_reports_enabled
        )
        if refresh_run is not None:
            response["latest"]["progress"] = source_refresh_progress_payload(
                refresh_run,
                source_root=runtime_settings.source_refresh_root_path,
            )
        return response

    @app.patch("/api/clients/{client_id}/cabinets/{cabinet_id}")
    def update_client_cabinet(
        client_id: str,
        cabinet_id: str,
        payload: WbCabinetSaveRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            client = repository.upsert_client_wb_cabinet(
                db,
                user=current,
                client_id=client_id,
                cabinet_id=cabinet_id,
                display_name=payload.label,
                organization_name=payload.organization_name,
                status=payload.status,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="cabinet not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"client": repository.client_payload(db, current, client)}

    @app.patch("/api/clients/{client_id}/companies/{company_id}/onec-organization")
    def update_client_company_onec_organization(
        client_id: str,
        company_id: str,
        payload: OnecOrganizationLinkRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            company = repository.set_client_company_onec_organization(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
                onec_organization_id=payload.onec_organization_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        client = repository.require_client_access(db, current, client_id)
        return {
            "companyId": company.id,
            "client": repository.client_payload(db, current, client),
        }

    @app.get("/api/clients/{client_id}/onec-organizations")
    def list_client_onec_organizations(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            return repository.onec_organizations_payload(
                db,
                user=current,
                client_id=client_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc

    @app.post("/api/clients/{client_id}/companies/{company_id}/tax-profile-overrides")
    def create_client_company_tax_profile_override(
        client_id: str,
        company_id: str,
        payload: TaxProfileOverrideCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            override = repository.create_tax_profile_override(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
                tax_system=payload.tax_system,
                vat_rate=payload.vat_rate,
                vat_mode=payload.vat_mode,
                vat_deduction_mode=payload.vat_deduction_mode,
                revenue_tax_rate=payload.revenue_tax_rate,
                income_tax_kind=payload.income_tax_kind,
                valid_from=payload.valid_from,
                valid_to=payload.valid_to,
                reason=payload.reason,
                rate_basis_kind=payload.rate_basis_kind,
                basis_document=payload.basis_document,
                source_object_ids=payload.source_object_ids,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        client = repository.require_client_access(db, current, client_id)
        return {
            "overrideId": override.id,
            "client": repository.client_payload(db, current, client),
        }

    @app.patch(
        "/api/clients/{client_id}/companies/{company_id}/tax-profile-overrides/"
        "{override_id}/disable"
    )
    def disable_client_company_tax_profile_override(
        client_id: str,
        company_id: str,
        override_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            override = repository.disable_tax_profile_override(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
                override_id=override_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        db.commit()
        client = repository.require_client_access(db, current, client_id)
        return {
            "overrideId": override.id,
            "client": repository.client_payload(db, current, client),
        }

    @app.patch(
        "/api/clients/{client_id}/companies/{company_id}/tax-profile-overrides/"
        "{override_id}/rate-basis"
    )
    def confirm_client_company_tax_rate_basis(
        client_id: str,
        company_id: str,
        override_id: str,
        payload: TaxRateBasisConfirmRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            override = repository.confirm_tax_rate_basis(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
                override_id=override_id,
                rate_basis_kind=payload.rate_basis_kind,
                basis_document=payload.basis_document,
                source_object_ids=payload.source_object_ids,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"overrideId": override.id, "status": "confirmed"}

    @app.get("/api/clients/{client_id}/companies/{company_id}/input-vat-policies")
    def list_client_company_input_vat_policies(
        client_id: str,
        company_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            items = repository.list_input_vat_policies(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        return {"items": [repository.input_vat_policy_payload(item) for item in items]}

    @app.post("/api/clients/{client_id}/companies/{company_id}/input-vat-policies")
    def create_client_company_input_vat_policy(
        client_id: str,
        company_id: str,
        payload: InputVatPolicyCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            policy = repository.create_input_vat_policy(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
                mode=payload.mode,
                product_vat_basis=payload.product_vat_basis,
                service_vat_basis=payload.service_vat_basis,
                valid_from=payload.valid_from,
                valid_to=payload.valid_to,
                reason=payload.reason,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"item": repository.input_vat_policy_payload(policy)}

    @app.patch(
        "/api/clients/{client_id}/companies/{company_id}/input-vat-policies/"
        "{policy_id}/disable"
    )
    def disable_client_company_input_vat_policy(
        client_id: str,
        company_id: str,
        policy_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            policy = repository.disable_input_vat_policy(
                db,
                user=current,
                client_id=client_id,
                company_id=company_id,
                policy_id=policy_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        db.commit()
        return {"item": repository.input_vat_policy_payload(policy)}

    @app.get("/api/admin/users")
    def admin_users(current: CurrentUser, db: DbSession) -> dict[str, Any]:
        try:
            users = repository.list_users_for_admin(db, current)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="admin role required") from exc
        return {"items": [user_payload(user, current) for user in users]}

    @app.post("/api/admin/users")
    def admin_create_user(
        payload: AdminUserCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        password = payload.password or security.new_temporary_password()
        try:
            user = repository.create_managed_user(
                db,
                admin=current,
                email=payload.email,
                name=payload.name,
                tenant_id=tenant_id,
                role=payload.role,
                password=password,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="admin role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"user": user_payload(user, current), "temporaryPassword": password}

    @app.patch("/api/admin/users/{user_id}")
    def admin_update_user(
        user_id: str,
        payload: AdminUserPatchRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        try:
            user = repository.update_managed_user(
                db,
                admin=current,
                target_user_id=user_id,
                tenant_id=tenant_id,
                name=payload.name,
                role=payload.role,
                is_active=payload.is_active,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="admin role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {"user": user_payload(user, current)}

    @app.post("/api/admin/users/{user_id}/reset-password")
    def admin_reset_password(
        user_id: str,
        payload: PasswordResetRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        password = security.new_temporary_password()
        try:
            user = repository.reset_managed_user_password(
                db,
                admin=current,
                target_user_id=user_id,
                tenant_id=tenant_id,
                password=password,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="admin role required") from exc
        db.commit()
        return {"user": user_payload(user, current), "temporaryPassword": password}

    @app.get("/api/admin/audit")
    def admin_audit(
        current: CurrentUser, db: DbSession, limit: int = 100
    ) -> dict[str, Any]:
        try:
            items = repository.audit_events_for_staff(db, current, limit=limit)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        return {"items": items}

    @app.get("/api/integrations")
    def list_integrations(
        current: CurrentUser,
        db: DbSession,
        tenant_id: str | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
            tenant_id=tenant_id,
        )
        try:
            items = repository.list_tenant_integrations(
                db, current, tenant_id=resolved_tenant_id
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        return {"items": items, "providers": providers.public_provider_metadata()}

    @app.get("/api/clients/{client_id}/integrations")
    def list_client_integrations(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        resolved_tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        try:
            items = repository.list_tenant_integrations(
                db, current, tenant_id=resolved_tenant_id
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        return {"items": items, "providers": providers.public_provider_metadata()}

    @app.post("/api/integrations")
    def create_integration(
        payload: TenantIntegrationCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        resolved_tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        try:
            provider = repository.new_integration_provider_id(payload.provider)
            secret_storage = integrations.secret_storage_payload(
                runtime_settings, payload.secret
            )
            integration = repository.save_tenant_integration(
                db,
                user=current,
                tenant_id=resolved_tenant_id,
                provider=provider,
                secret=payload.secret,
                label=payload.label,
                connection_role=payload.connection_role,
                cabinet_name=payload.cabinet_name,
                organization_name=payload.organization_name,
                secret_storage=secret_storage.payload,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return repository.tenant_integration_payload(
            integration, resolved_tenant_id, integration.provider
        )

    @app.put("/api/integrations/{provider}")
    def save_integration(
        provider: str,
        payload: TenantIntegrationSaveRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        resolved_tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        try:
            secret_storage = integrations.secret_storage_payload(
                runtime_settings, payload.secret
            )
            integration = repository.save_tenant_integration(
                db,
                user=current,
                tenant_id=resolved_tenant_id,
                provider=provider,
                secret=payload.secret,
                label=payload.label,
                connection_role=payload.connection_role,
                cabinet_name=payload.cabinet_name,
                organization_name=payload.organization_name,
                secret_storage=secret_storage.payload,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return repository.tenant_integration_payload(
            integration, resolved_tenant_id, provider
        )

    @app.post("/api/integrations/{provider}/check")
    def check_integration(
        provider: str,
        payload: TenantIntegrationActionRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        if not runtime_settings.external_integrations_enabled:
            raise HTTPException(
                status_code=409,
                detail="Внешние проверки отключены для этого контура.",
            )
        resolved_tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        try:
            provider_base = repository.integration_provider_base(provider)
            integration = repository.get_tenant_integration_for_staff(
                db,
                user=current,
                tenant_id=resolved_tenant_id,
                provider=provider,
            )
            if integration.status == "disabled":
                check_result = integrations.IntegrationCheckResult(
                    status="check_failed",
                    message=(
                        "Интеграция отключена. Включите ее повторным сохранением ключа."
                    ),
                    payload={
                        "provider": provider,
                        "checkedAt": security.utcnow().isoformat(),
                        "checkMode": "configuration",
                    },
                )
            elif not integration.secret_hash:
                check_result = integrations.IntegrationCheckResult(
                    status="check_failed",
                    message="Секрет еще не сохранен.",
                    payload={
                        "provider": provider,
                        "checkedAt": security.utcnow().isoformat(),
                        "checkMode": "configuration",
                    },
                )
            else:
                secret = integrations.decrypt_secret(
                    runtime_settings, integration.config_payload or {}
                )
                check_result = integrations.run_provider_check(
                    runtime_settings,
                    provider=provider_base,
                    secret=secret,
                )
            integration = repository.record_tenant_integration_check(
                db,
                user=current,
                tenant_id=resolved_tenant_id,
                provider=provider,
                status=check_result.status,
                message=check_result.message,
                check_payload=check_result.payload,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except integrations.IntegrationSecretError as exc:
            check_result = integrations.IntegrationCheckResult(
                status="check_failed",
                message=(
                    "Секрет сохранен в режиме, который нельзя использовать для "
                    "проверки подключения. Сохраните ключ заново после настройки "
                    "SHUMEYKO_INTEGRATION_SECRET_KEY."
                ),
                payload={
                    "provider": provider,
                    "checkedAt": security.utcnow().isoformat(),
                    "checkMode": "configuration",
                    "errorType": exc.args[0] if exc.args else "secret_error",
                },
            )
            integration = repository.record_tenant_integration_check(
                db,
                user=current,
                tenant_id=resolved_tenant_id,
                provider=provider,
                status=check_result.status,
                message=check_result.message,
                check_payload=check_result.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return repository.tenant_integration_payload(
            integration, resolved_tenant_id, provider
        )

    @app.post("/api/integrations/{provider}/disable")
    def disable_integration(
        provider: str,
        payload: TenantIntegrationActionRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        resolved_tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        try:
            integration = repository.disable_tenant_integration(
                db,
                user=current,
                tenant_id=resolved_tenant_id,
                provider=provider,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return repository.tenant_integration_payload(
            integration, resolved_tenant_id, provider
        )

    @app.get("/api/reports")
    def list_reports(
        current: CurrentUser,
        db: DbSession,
        client_id: str | None = None,
        report_kind: str = MARKETPLACE_UNIT_ECONOMICS,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            require_report_kind(report_kind)
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail="report kind not found"
            ) from exc
        if report_kind not in runtime_settings.enabled_report_kind_set:
            raise HTTPException(status_code=404, detail="report kind not found")
        if client_id:
            client = repository.require_client_access(db, current, client_id)
            _require_enabled_report_kind_or_404(
                current,
                tenant_id=client.tenant_id,
                report_kind=report_kind,
                settings=runtime_settings,
            )
        reports = repository.list_reports_for_user(
            db,
            current,
            client_id=client_id,
            report_kind=report_kind,
            organization_id=organization_id,
        )
        return {"items": [_report_list_item(report) for report in reports]}

    @app.get("/api/clients/{client_id}/report-kinds")
    def list_client_report_kinds(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            client = repository.require_client_access(db, current, client_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        return {
            "reportKinds": repository.report_kinds_for_user(
                current,
                tenant_id=client.tenant_id,
                enabled_kinds=runtime_settings.enabled_report_kind_set,
            )
        }

    @app.get("/api/clients/{client_id}/reports")
    def list_client_reports(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
        report_kind: str = MARKETPLACE_UNIT_ECONOMICS,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            client = repository.require_client_access(db, current, client_id)
            _require_enabled_report_kind_or_404(
                current,
                tenant_id=client.tenant_id,
                report_kind=report_kind,
                settings=runtime_settings,
            )
            if report_kind in ACCOUNTING_REPORT_KINDS and not organization_id:
                raise HTTPException(
                    status_code=400, detail="organization_id is required"
                )
            reports = repository.list_reports_for_client(
                db,
                current,
                client_id,
                report_kind=report_kind,
                organization_id=organization_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        repository.audit(
            db,
            action="report_kind_viewed",
            user=current,
            tenant_id=client.tenant_id,
            entity_type="client",
            entity_id=client.id,
            payload={
                "reportKind": report_kind,
                "organizationId": organization_id,
            },
        )
        db.commit()
        return {"items": [_report_list_item(report) for report in reports]}

    @app.get("/api/reports/latest/summary")
    def latest_summary(
        current: CurrentUser,
        db: DbSession,
        client_id: str | None = None,
        report_kind: str = MARKETPLACE_UNIT_ECONOMICS,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_client_id = _resolve_latest_client_id_or_400(db, current, client_id)
        try:
            client = repository.require_client_access(db, current, resolved_client_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        _require_enabled_report_kind_or_404(
            current,
            tenant_id=client.tenant_id,
            report_kind=report_kind,
            settings=runtime_settings,
        )
        if report_kind in ACCOUNTING_REPORT_KINDS and not organization_id:
            raise HTTPException(status_code=400, detail="organization_id is required")
        report = repository.latest_report_for_client(
            db,
            current,
            resolved_client_id,
            report_kind=report_kind,
            organization_id=organization_id,
        )
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        repository.audit(
            db,
            action="report_viewed",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        return repository.report_summary_payload(
            db,
            report,
            include_staff_readiness=_include_staff_readiness(current, report.tenant_id),
        )

    @app.post("/api/clients/{client_id}/reports/generate", status_code=202)
    def generate_client_report(
        client_id: str,
        payload: ReportGenerateRequest,
        background_tasks: BackgroundTasks,
        current: CurrentUser,
        db: DbSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=1, max_length=160)
        ],
    ) -> dict[str, Any]:
        try:
            client = repository.require_client_access(db, current, client_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        _require_enabled_report_kind_or_404(
            current,
            tenant_id=client.tenant_id,
            report_kind=payload.reportKind,
            settings=runtime_settings,
        )
        try:
            year, month = (int(value) for value in payload.periodMonth.split("-"))
            period_start = date(year, month, 1)
            period_end = date(year, month, monthrange(year, month)[1])
            run, deduplicated = repository.generate_accounting_report(
                db,
                user=current,
                client_id=client_id,
                report_kind=payload.reportKind,
                organization_id=payload.organizationId,
                period_start=period_start,
                period_end=period_end,
                idempotency_key=idempotency_key,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="organization not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            db.rollback()
            repository.audit(
                db,
                action="report_generation_failed",
                user=current,
                tenant_id=client.tenant_id,
                entity_type="client",
                entity_id=client.id,
                payload={
                    "reportKind": payload.reportKind,
                    "organizationId": payload.organizationId,
                    "periodMonth": payload.periodMonth,
                },
            )
            db.commit()
            raise HTTPException(
                status_code=500,
                detail="Не удалось сформировать отчет; исходные данные не изменялись.",
            ) from exc
        db.commit()
        if not deduplicated and run.status == "queued":
            if app.state.source_refresh_worker_launcher is None:
                background_tasks.add_task(
                    _run_report_generation_background,
                    app.state.session_factory,
                    app.state.source_refresh_service,
                    run.id,
                )
            else:
                try:
                    launch_source_refresh_worker(
                        db,
                        refresh_run_id=run.id,
                        worker_launcher=app.state.source_refresh_worker_launcher,
                        user=current,
                        fallback_payload=repository.generation_run_payload(run),
                    )
                except SourceRefreshWorkerLaunchError as exc:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "Не удалось запустить отдельный процесс формирования; "
                            "исходные данные не изменялись."
                        ),
                    ) from exc
        result = repository.generation_run_payload(run)
        result["deduplicated"] = deduplicated
        return result

    @app.get("/api/report-generations/{generation_run_id}")
    def report_generation_status(
        generation_run_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        run = db.get(SourceRefreshRun, generation_run_id)
        if run is None or run.mode != "report-generation":
            raise HTTPException(status_code=404, detail="generation not found")
        try:
            client = repository.require_client_access(db, current, run.client_id)
            repository.require_staff(current, client.tenant_id)
        except (LookupError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail="generation not found") from exc
        _require_enabled_report_kind_or_404(
            current,
            tenant_id=client.tenant_id,
            report_kind=run.target_report_kind,
            settings=runtime_settings,
        )
        return repository.generation_run_payload(run)

    @app.get("/api/reports/{report_id}/summary")
    def report_summary(
        report_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        started_at = time.perf_counter()
        repository.audit(
            db,
            action="report_viewed",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        try:
            payload = repository.report_summary_payload(
                db,
                report,
                include_staff_readiness=_include_staff_readiness(
                    current, report.tenant_id
                ),
            )
        except Exception:
            _log_report_endpoint_timing(
                endpoint="summary",
                report_id=report.id,
                started_at=started_at,
                outcome="error",
            )
            raise
        _log_report_endpoint_timing(
            endpoint="summary",
            report_id=report.id,
            started_at=started_at,
            outcome="ok",
        )
        return payload

    @app.get(
        "/api/reports/{report_id}/logistics/summary",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_summary(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(
            report, periodStart, periodEnd
        )
        return repository.report_logistics_summary_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
        )

    @app.get(
        "/api/reports/{report_id}/logistics/products",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_products(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
        sortBy: str = "logisticsTotal",
        sortOrder: str = "desc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_PRODUCT_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        return repository.report_logistics_products_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get(
        "/api/reports/{report_id}/logistics/dimensions",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_dimensions(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
        sortBy: str = "product",
        sortOrder: str = "asc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_factors_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_DIMENSION_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        return repository.report_logistics_dimensions_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get(
        "/api/reports/{report_id}/logistics/tariffs",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_tariffs(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        warehouse: str = "",
        tariffType: str = "",
        sortBy: str = "requestedDate",
        sortOrder: str = "asc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_tariffs_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_TARIFF_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        if tariffType.casefold() not in {"", "box", "pallet"}:
            raise HTTPException(status_code=400, detail="unsupported tariffType")
        return repository.report_logistics_tariffs_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            warehouse=warehouse,
            tariff_type=tariffType,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get(
        "/api/reports/{report_id}/logistics/measurements",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_measurements(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
        eventKind: str = "",
        hasPenalty: bool | None = None,
        sortBy: str = "eventDate",
        sortOrder: str = "desc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_measurements_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_MEASUREMENT_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        if eventKind not in {
            "",
            "measurement_penalty",
            "warehouse_measurement",
            "merged",
        }:
            raise HTTPException(status_code=400, detail="unsupported eventKind")
        return repository.report_logistics_measurements_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
            event_kind=eventKind,
            has_penalty=hasPenalty,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get(
        "/api/reports/{report_id}/logistics/return-reasons",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_return_reasons(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
        reasonSource: str = "",
        evidenceType: str = "",
        matchStatus: str = "",
        sortBy: str = "eventDate",
        sortOrder: str = "desc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_return_reasons_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_RETURN_REASON_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        return repository.report_logistics_return_reasons_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
            reason_source=reasonSource,
            evidence_type=evidenceType,
            match_status=matchStatus,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get(
        "/api/reports/{report_id}/logistics/routes",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_routes(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
        warehouse: str = "",
        destination: str = "",
        sortBy: str = "logisticsTotal",
        sortOrder: str = "desc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_routes_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_ROUTE_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        return repository.report_logistics_routes_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
            warehouse=warehouse,
            destination=destination,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get(
        "/api/reports/{report_id}/logistics/orders",
        responses=LOGISTICS_PERIOD_ERROR_OPENAPI,
    )
    def report_logistics_orders(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        periodStart: date | None = None,
        periodEnd: date | None = None,
        wbCabinetId: str = "",
        clientCompanyId: str = "",
        scheme: str = "",
        product: str = "",
        productRef: str = "",
        sortBy: str = "operationDateEnd",
        sortOrder: str = "desc",
        offset: int = 0,
        limit: int = 250,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_logistics_access_or_404(
            current,
            report.tenant_id,
            runtime_settings,
            staff_only=True,
        )
        period_start, period_end = _logistics_period(report, periodStart, periodEnd)
        if sortBy not in repository.LOGISTICS_ORDER_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sortBy")
        if sortOrder not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sortOrder")
        return repository.report_logistics_orders_payload(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wbCabinetId,
            client_company_id=clientCompanyId,
            scheme=scheme,
            product_query=product,
            product_ref=productRef,
            sort_by=sortBy,
            sort_order=sortOrder,
            offset=max(offset, 0),
            limit=min(max(limit, 1), 1000),
        )

    @app.get("/api/reports/{report_id}/scenario")
    def report_scenario(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        if report.report_kind not in ACCOUNTING_REPORT_KINDS:
            raise HTTPException(status_code=404, detail="scenario not found")
        _require_staff_or_403(current, report.tenant_id)
        try:
            payload = repository.scenario_payload_for_report(db, report)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="scenario not found") from exc
        repository.audit(
            db,
            action="report_viewed",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={"reportKind": report.report_kind, "surface": "scenario"},
        )
        db.commit()
        return payload

    @app.get("/api/reports/{report_id}/freshness")
    def report_freshness(
        report_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        started_at = time.perf_counter()
        try:
            payload = repository.report_freshness_payload(
                db,
                report,
                include_staff_readiness=_include_staff_readiness(
                    current, report.tenant_id
                ),
            )
        except Exception:
            _log_report_endpoint_timing(
                endpoint="freshness",
                report_id=report.id,
                started_at=started_at,
                outcome="error",
            )
            raise
        _log_report_endpoint_timing(
            endpoint="freshness",
            report_id=report.id,
            started_at=started_at,
            outcome="ok",
        )
        return payload

    @app.post("/api/reports/{report_id}/publish-with-tasks")
    def publish_report_with_tasks(
        report_id: str,
        payload: PublishWithTasksRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        if not payload.confirm_blocking_tasks:
            raise HTTPException(
                status_code=400,
                detail="explicit blocking task confirmation required",
            )
        try:
            report, tasks = repository.publish_report_with_tasks(
                db,
                report,
                user=current,
                reason=payload.reason,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="staff role required") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        return {
            "reportId": report.id,
            "publicationStatus": report.publication_status,
            "isCurrent": report.is_current,
            "blockingTasks": tasks,
            "readiness": repository.report_readiness_payload(db, report),
        }

    @app.post("/api/reports/{report_id}/mapping-file")
    async def upload_mapping_file(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        file: Annotated[UploadFile, File(...)],
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        target_name, size_bytes = await _save_mapping_upload(
            runtime_settings,
            file,
        )
        repository.audit(
            db,
            action="mapping_file_uploaded",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={
                "fileName": target_name,
                "sizeBytes": size_bytes,
            },
        )
        refresh_payload = _run_mapping_upload_refresh(
            app,
            db,
            current=current,
            report=report,
            file_name=target_name,
        )
        db.commit()
        return {
            "status": "uploaded",
            "fileName": target_name,
            "sizeBytes": size_bytes,
            "autoRefresh": refresh_payload,
        }

    @app.get("/api/reports/{report_id}/management-report")
    def report_management_report(
        report_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _reject_client_report_recommendations(db, current, report)
        summary = repository.report_full_payload(db, report)
        repository.audit(
            db,
            action="management_report_generated",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        return {
            "reportId": report.id,
            "markdown": repository.management_report_text(summary),
        }

    @app.get("/api/reports/{report_id}/client-draft")
    def report_client_draft(
        report_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        return repository.client_draft_payload(db, report)

    @app.put("/api/reports/{report_id}/client-draft")
    def save_client_draft(
        report_id: str,
        payload: ClientDraftSaveRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        thread_id = _checked_optional_thread_id(
            db, current, payload.thread_id, report_id=report.id
        )
        summary = repository.report_full_payload(db, report)
        try:
            draft = repository.create_client_draft_revision(
                db,
                user=current,
                report=report,
                thread_id=thread_id,
                source="manual",
                content=payload.content,
                instruction=payload.instruction or "Ручная правка аналитика",
                evidence=repository.client_draft_evidence_payload(summary),
                limitations=repository.client_draft_limitations(summary),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        result = repository.client_draft_payload(db, report)
        result["latest"] = result["latest"] or {}
        result["message"] = f"Версия v{draft.revision} сохранена."
        result["changed"] = True
        return result

    @app.post("/api/reports/{report_id}/client-draft/refine")
    def refine_client_draft(
        report_id: str,
        payload: ClientDraftRefineRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        thread_id = _checked_optional_thread_id(
            db, current, payload.thread_id, report_id=report.id
        )
        latest = repository.latest_client_draft(db, report)
        instruction = _client_draft_instruction(payload)
        result = app.state.analyst.refine_client_draft(
            db,
            user=current,
            report=report,
            instruction=instruction,
            latest_draft=latest.content if latest else "",
        )
        if not result["changed"]:
            repository.audit(
                db,
                action="ai_client_draft_refine_unavailable",
                user=current,
                tenant_id=report.tenant_id,
                entity_type="report_run",
                entity_id=report.id,
                payload={
                    "action": payload.action,
                    "revision": latest.revision if latest else None,
                },
            )
            db.commit()
            response = repository.client_draft_payload(db, report)
            response["changed"] = False
            response["message"] = result["message"]
            response["aiAvailable"] = False
            return response
        try:
            draft = repository.create_client_draft_revision(
                db,
                user=current,
                report=report,
                thread_id=thread_id,
                source=result["source"],
                content=result["content"],
                instruction=instruction,
                evidence=result["evidence"],
                limitations=result["limitations"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        response = repository.client_draft_payload(db, report)
        response["changed"] = True
        response["message"] = result["message"]
        response["aiAvailable"] = result["source"] == "ai"
        response["revision"] = draft.revision
        return response

    @app.post("/api/reports/{report_id}/client-draft/finalize")
    def finalize_client_draft(
        report_id: str,
        payload: ClientDraftFinalizeRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        try:
            draft = repository.finalize_client_draft(
                db,
                user=current,
                report=report,
                revision=payload.revision,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="client draft not found"
            ) from exc
        db.commit()
        response = repository.client_draft_payload(db, report)
        response["message"] = f"Версия v{draft.revision} помечена готовой."
        response["changed"] = True
        return response

    @app.post("/api/reports/{report_id}/analytical-report")
    def build_analytical_report(
        report_id: str,
        payload: AnalyticalReportRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _reject_client_report_recommendations(db, current, report)
        requested_period_start: date
        requested_period_end: date
        period_fallback = False
        try:
            if payload.scope == "last_closed_week":
                if payload.periodStart is not None or payload.periodEnd is not None:
                    raise ValueError(
                        "Для последней закрытой недели даты определяются автоматически."
                    )
                period_start, period_end, summary = report_summary_for_last_closed_week(
                    db, report
                )
                summary_meta = summary.get("meta") or {}
                requested_period_start = date.fromisoformat(
                    str(summary_meta["requestedPeriodStart"])
                )
                requested_period_end = date.fromisoformat(
                    str(summary_meta["requestedPeriodEnd"])
                )
                period_fallback = bool(summary_meta.get("periodFallback"))
            else:
                period_start, period_end = _analytical_report_period(report, payload)
                requested_period_start = period_start
                requested_period_end = period_end
                summary = report_summary_for_period(
                    db,
                    report,
                    period_start=(None if payload.scope == "full" else period_start),
                    period_end=(None if payload.scope == "full" else period_end),
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        output_dir = _analytical_report_dir(runtime_settings, report.id)
        artifacts = build_client_analytical_report(
            summary=summary,
            output_dir=output_dir,
            basename=_analytical_report_basename(
                report,
                branded=payload.branded,
                period_start=period_start,
                period_end=period_end,
            ),
            branded=payload.branded,
        )
        artifact_paths = {
            "analytical_markdown": artifacts.markdown_path,
            "analytical_docx": artifacts.docx_path,
        }
        if artifacts.pdf_path is not None:
            artifact_paths["analytical_pdf"] = artifacts.pdf_path
        for artifact_type, path in artifact_paths.items():
            record = artifact_record(path)
            repository.record_report_artifact(
                db,
                report,
                artifact_type=artifact_type,
                path=path,
                sha256=record["hash"],
                byte_size=record["byte_size"],
                status=record["status"],
            )
        repository.audit(
            db,
            action="analytical_report_generated",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
            payload={
                "scope": payload.scope,
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
                "requestedPeriodStart": requested_period_start.isoformat(),
                "requestedPeriodEnd": requested_period_end.isoformat(),
                "periodFallback": period_fallback,
            },
        )
        db.commit()
        return _analytical_report_payload(
            report.id,
            artifacts,
            scope=payload.scope,
            period_start=period_start,
            period_end=period_end,
            requested_period_start=requested_period_start,
            requested_period_end=requested_period_end,
            period_fallback=period_fallback,
        )

    @app.get("/api/reports/{report_id}/analytical-report.{extension}")
    def download_analytical_report(
        report_id: str,
        extension: str,
        current: CurrentUser,
        db: DbSession,
    ) -> FileResponse:
        report = _require_report_or_404(db, current, report_id)
        _reject_client_report_recommendations(db, current, report)
        path = _latest_analytical_report_path(
            runtime_settings,
            report.id,
            extension,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="report artifact not found")
        repository.audit(
            db,
            action=f"analytical_report_{extension}_downloaded",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        return FileResponse(
            path,
            media_type=_analytical_report_media_type(extension),
            filename=path.name,
        )

    @app.get("/api/reports/{report_id}/rows")
    def report_rows(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        query: str = "",
        status_filter: str = "",
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
        report = _require_report_or_404(db, current, report_id)
        if sort_by and sort_by not in repository.REPORT_ROW_SORT_KEYS:
            raise HTTPException(status_code=400, detail="unsupported sort_by")
        if sort_direction and sort_direction not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="unsupported sort_direction")
        return repository.query_report_rows(
            db,
            report,
            query=query,
            status=status_filter,
            period_start=period_start,
            period_end=period_end,
            month=month,
            cabinet=cabinet,
            organization=organization,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            scheme=scheme,
            loss_class=loss_class,
            document_report=document_report,
            preset=preset,
            sort_by=sort_by,
            sort_direction=sort_direction,
            limit=min(max(limit, 1), 1000),
            offset=max(offset, 0),
        )

    @app.get("/api/reports/{report_id}/document-reconciliation")
    def report_document_reconciliation(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
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
        report = _require_report_or_404(db, current, report_id)
        return repository.query_document_reconciliation_rows(
            db,
            report,
            query=query,
            status=status,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            document_type=document_type,
            document_report=document_report,
            delta_only=delta_only,
            limit=min(max(limit, 1), 1000),
            offset=max(offset, 0),
        )

    @app.get("/api/reports/{report_id}/financial-document-reconciliation")
    def report_financial_document_reconciliation(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        query: str = "",
        period_start: date | None = None,
        period_end: date | None = None,
        control_type: str = "",
        wb_cabinet_id: str = "",
        client_company_id: str = "",
        document_type: str = "",
        delta_only: bool = False,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        return repository.query_financial_document_reconciliation(
            db,
            report,
            query=query,
            period_start=period_start,
            period_end=period_end,
            control_type=control_type,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            document_type=document_type,
            delta_only=delta_only,
        )

    @app.get("/api/reports/{report_id}/buyout-reconciliation")
    def report_buyout_reconciliation(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        period_start: date | None = None,
        period_end: date | None = None,
        wb_cabinet_id: str = "",
        client_company_id: str = "",
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        return repository.query_buyout_reconciliation(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
        )

    @app.get("/api/reports/{report_id}/cogs-reconciliation")
    def report_cogs_reconciliation(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        period_start: date | None = None,
        period_end: date | None = None,
        wb_cabinet_id: str = "",
        client_company_id: str = "",
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        return repository.query_cogs_reconciliation(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
        )

    @app.get("/api/reports/{report_id}/marketplace-expense-reconciliation")
    def report_marketplace_expense_reconciliation(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
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
        report = _require_report_or_404(db, current, report_id)
        return repository.query_marketplace_expense_reconciliation(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            wb_cabinet_id=wb_cabinet_id,
            client_company_id=client_company_id,
            control_group=control_group,
            status=status,
            delta_only=delta_only,
            limit=min(max(limit, 1), 1000),
            offset=max(offset, 0),
        )

    @app.get("/api/reports/{report_id}/sku/{sku}")
    def sku_card(
        report_id: str, sku: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        item = repository.find_sku(db, report, sku)
        if item is None:
            raise HTTPException(status_code=404, detail="sku not found")
        return item

    @app.get("/api/reports/{report_id}/export.xlsx")
    def export_excel(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        period_start: date | None = None,
        period_end: date | None = None,
        wb_cabinet_id: str = "",
    ) -> FileResponse:
        report = _require_report_or_404(db, current, report_id)
        if report.report_kind in ACCOUNTING_REPORT_KINDS:
            _require_staff_or_403(current, report.tenant_id)
            payload = repository.scenario_payload_for_report(db, report)
            contract_revision = _contract_revision_token(
                str(payload.get("contractVersion") or report.methodology_version)
            )
            payload_sha256 = str(payload.pop("payloadSha256"))
            output_dir = (
                runtime_settings.export_root_path
                / "accounting_reports"
                / _safe_path_segment(report.client_id)
            ).resolve()
            allowed = runtime_settings.export_root_path.resolve()
            if output_dir != allowed and allowed not in output_dir.parents:
                raise HTTPException(
                    status_code=400, detail="export path is outside reports"
                )
            path = output_dir / f"{_safe_path_segment(report.id)}.xlsx"
            company = db.scalar(
                select(ClientCompany)
                .where(
                    ClientCompany.tenant_id == report.tenant_id,
                    ClientCompany.client_id == report.client_id,
                    ClientCompany.onec_organization_id == report.organization_id,
                )
                .order_by(ClientCompany.status != "active", ClientCompany.id)
                .limit(1)
            )
            write_scenario_excel(
                payload,
                payload_sha256,
                path,
                export_context={
                    "clientName": report.client_name,
                    "organizationName": company.display_name if company else "",
                },
            )
            repository.audit(
                db,
                action="report_exported",
                user=current,
                tenant_id=report.tenant_id,
                entity_type="report_run",
                entity_id=report.id,
                payload={
                    "reportKind": report.report_kind,
                    "payloadSha256": payload_sha256,
                },
            )
            db.commit()
            return FileResponse(
                path,
                media_type=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                filename=(
                    f"Налоговая_нагрузка_{report.period_start:%Y_%m}"
                    f"{f'_{contract_revision}' if contract_revision else ''}.xlsx"
                    if report.report_kind == "tax_load"
                    else f"{report.report_kind}_{report.period_start:%Y_%m}.xlsx"
                ),
            )
        if report.lineage_type == repository.OZON_DRAFT_LINEAGE_TYPE:
            _require_staff_or_403(current, report.tenant_id)
            diagnostics = repository.ozon_draft_diagnostics_payload(
                db,
                report,
                limit=repository.OZON_PNL_MAX_SOURCE_ROWS,
                preview_max_rows=repository.OZON_PNL_MAX_SOURCE_ROWS,
                period_start=period_start,
                period_end=period_end,
                wb_cabinet_id=wb_cabinet_id,
            )
            output_dir = (
                runtime_settings.export_root_path
                / "ozon_drafts"
                / _safe_path_segment(report.client_id)
            ).resolve()
            allowed = runtime_settings.export_root_path.resolve()
            if output_dir != allowed and allowed not in output_dir.parents:
                raise HTTPException(
                    status_code=400,
                    detail="export path is outside reports",
                )
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{_safe_path_segment(report.id)}.xlsx"
            path = output_dir / filename
            write_ozon_diagnostics_excel(diagnostics, path)
            repository.audit(
                db,
                action="ozon_draft_excel_exported",
                user=current,
                tenant_id=report.tenant_id,
                entity_type="report_run",
                entity_id=report.id,
            )
            db.commit()
            return FileResponse(
                path,
                media_type=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                filename=f"ozon_unit_economics_{report.period_start:%Y%m%d}_"
                f"{report.period_end:%Y%m%d}.xlsx",
            )
        export_report = report
        path = _report_excel_export_path(db, export_report, runtime_settings)
        if report.publication_status != "published":
            _require_staff_or_403(current, report.tenant_id)
        if (
            report.publication_status in {"published", "superseded"}
            and not report.is_current
        ):
            latest_report = repository.latest_report_for_client(
                db,
                current,
                report.client_id,
            )
            if latest_report is not None and latest_report.id != report.id:
                latest_path = _report_excel_export_path(
                    db,
                    latest_report,
                    runtime_settings,
                )
                if latest_path is not None and latest_path.exists():
                    export_report = latest_report
                    path = latest_path
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="export not found")
        repository.audit(
            db,
            action="report_exported",
            user=current,
            tenant_id=export_report.tenant_id,
            entity_type="report_run",
            entity_id=export_report.id,
            payload=(
                {"requestedReportId": report.id}
                if export_report.id != report.id
                else None
            ),
        )
        db.commit()
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=export_report.source_workbook or "shumeyko_wb_excel_mvp.xlsx",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/admin/reports/import")
    def admin_import_report(
        payload: ReportImportRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        tenant_id, _client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=payload.client_id,
            tenant_id=payload.tenant_id,
        )
        try:
            repository.require_admin(current, tenant_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="admin role required") from exc
        workbook = _resolve_report_workbook(
            payload.workbook_path,
            runtime_settings.default_report_workbook_path,
            runtime_settings.export_root_path,
        )
        if not workbook.exists():
            raise HTTPException(status_code=404, detail="workbook not found")
        report_id = payload.report_id or _report_id_from_workbook(workbook)
        access = repository.primary_access(current, tenant_id)
        tenant_name = payload.tenant_name or access.tenant.name
        report = repository.import_dashboard_payload(
            db,
            build_dashboard_payload(workbook),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            report_id=report_id,
            source_workbook_path=str(workbook),
            lineage_type="legacy_excel_import",
        )
        repository.audit(
            db,
            action="report_import_requested",
            user=current,
            tenant_id=tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        return repository.report_freshness_payload(
            db,
            report,
            include_staff_readiness=_include_staff_readiness(current, report.tenant_id),
        )

    @app.post("/api/reports/{report_id}/live-checks/onec-cost")
    def live_check_onec_cost(
        report_id: str,
        payload: LiveCheckRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        return _live_check(
            db,
            current,
            _require_report_or_404(db, current, report_id),
            source_type="1c",
            check_type="onec_cost",
            lookup=payload.lookup,
            settings=runtime_settings,
        )

    @app.post("/api/reports/{report_id}/refresh/onec-auto")
    def refresh_onec_auto(
        report_id: str,
        payload: OnecAutoRefreshRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        _require_staff_or_403(current, report.tenant_id)
        thread_id = _checked_optional_thread_id(
            db, current, payload.thread_id, report_id=report.id
        )
        try:
            result = app.state.auto_refresh_service.run(
                db,
                user=current,
                report=report,
                reason=payload.reason,
                thread_id=thread_id,
            )
        except AutoRefreshDisabledError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AutoRefreshBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AutoRefreshUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        db.commit()
        return result

    @app.get("/api/reports/{report_id}/refresh-jobs/{job_id}")
    def get_refresh_job(
        report_id: str,
        job_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        try:
            job = repository.require_data_refresh_job(
                db,
                user=current,
                report=report,
                job_id=job_id,
            )
            return repository.data_refresh_job_payload(job)
        except PermissionError:
            try:
                refresh_run = repository.require_source_refresh_run(
                    db,
                    user=current,
                    report=report,
                    refresh_run_id=job_id,
                )
            except PermissionError as source_exc:
                raise HTTPException(
                    status_code=404, detail="refresh job not found"
                ) from source_exc
            return repository.source_refresh_run_payload(
                refresh_run,
                include_sensitive=_include_staff_readiness(current, report.tenant_id),
            )

    @app.post("/api/reports/{report_id}/live-checks/wb-card")
    def live_check_wb_card(
        report_id: str,
        payload: LiveCheckRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        return _live_check(
            db,
            current,
            _require_report_or_404(db, current, report_id),
            source_type="wb",
            check_type="wb_card",
            lookup=payload.lookup,
            settings=runtime_settings,
        )

    @app.post("/api/reports/{report_id}/live-checks/wb-stock")
    def live_check_wb_stock(
        report_id: str,
        payload: LiveCheckRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        return _live_check(
            db,
            current,
            _require_report_or_404(db, current, report_id),
            source_type="wb",
            check_type="wb_stock",
            lookup=payload.lookup,
            settings=runtime_settings,
        )

    @app.get("/api/ai/threads")
    def list_threads(
        report_id: str,
        current: CurrentUser,
        db: DbSession,
        limit: int = 1,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        threads = repository.list_ai_threads(
            db,
            user=current,
            report_id=report.id,
            limit=limit,
        )
        return {
            "items": [
                thread_payload(
                    thread,
                    repository.thread_messages(db, thread, limit=100),
                    repository.thread_events(db, current, thread),
                )
                for thread in threads
            ]
        }

    @app.post("/api/ai/threads")
    def create_thread(
        payload: ThreadCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        if not payload.report_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Для AI-аналитика нужно выбрать конкретный расчет отчета.",
            )
        report = _require_report_or_404(db, current, payload.report_id)
        if payload.client_id and payload.client_id != report.client_id:
            raise HTTPException(status_code=409, detail="report/client scope mismatch")
        thread = repository.create_ai_thread(
            db,
            user=current,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            report_id=report.id,
            title=payload.title,
            scope=payload.scope,
        )
        db.commit()
        return thread_payload(thread, [], [])

    @app.get("/api/ai/threads/{thread_id}")
    def get_thread(
        thread_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        thread = _require_thread_or_404(db, current, thread_id)
        return thread_payload(
            thread,
            repository.thread_messages(db, thread),
            repository.thread_events(db, current, thread),
        )

    @app.get("/api/ai/threads/{thread_id}/events")
    def get_thread_events(
        thread_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        thread = _require_thread_or_404(db, current, thread_id)
        return {"items": repository.thread_events(db, current, thread)}

    @app.post("/api/ai/threads/{thread_id}/messages")
    def send_message(
        thread_id: str,
        payload: MessageRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        thread = _require_thread_or_404(db, current, thread_id)
        _reject_client_financial_recommendations(db, current, thread)
        repository.add_ai_message(
            db, thread=thread, role="user", content=payload.content
        )
        repository.add_ai_event(
            db,
            thread=thread,
            user=current,
            event_type="status",
            title="Вопрос принят",
            message=(
                "AI-аналитик работает только с расчетной витриной "
                "и инструментами только для чтения."
            ),
            status="running",
        )
        answer = app.state.analyst.answer(
            db,
            user=current,
            thread=thread,
            question=payload.content,
        )
        repository.add_ai_message(
            db,
            thread=thread,
            role="assistant",
            content=answer.content,
            citations=list(answer.citations),
        )
        repository.add_ai_event(
            db,
            thread=thread,
            user=current,
            event_type="assistant_done",
            title="Ответ готов",
            message="Ответ сохранен в истории чата.",
            status="ok",
            payload=_answer_event_payload(answer),
        )
        repository.audit(
            db,
            action="ai_message_answered",
            user=current,
            tenant_id=thread.tenant_id,
            entity_type="ai_thread",
            entity_id=thread.id,
        )
        db.commit()
        return thread_payload(
            thread,
            repository.thread_messages(db, thread),
            repository.thread_events(db, current, thread),
        )

    @app.post("/api/ai/threads/{thread_id}/messages/stream")
    def stream_message(
        thread_id: str,
        payload: MessageRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> StreamingResponse:
        thread = _require_thread_or_404(db, current, thread_id)
        _reject_client_financial_recommendations(db, current, thread)

        def generate():
            sent_ids: set[int] = set()
            try:
                sent_ids.update(
                    item["id"] for item in repository.thread_events(db, current, thread)
                )
                repository.add_ai_message(
                    db, thread=thread, role="user", content=payload.content
                )
                start = repository.add_ai_event(
                    db,
                    thread=thread,
                    user=current,
                    event_type="status",
                    title="Вопрос принят",
                    message=(
                        "Смотрю расчетную витрину. Внешние системы не изменяются."
                    ),
                    status="running",
                )
                db.flush()
                sent_ids.add(start.id)
                yield _sse(
                    "status",
                    repository.ai_event_payload(
                        start,
                        staff=repository.has_role(
                            current, repository.STAFF_ROLES, thread.tenant_id
                        ),
                    ),
                )
                answer = app.state.analyst.answer(
                    db,
                    user=current,
                    thread=thread,
                    question=payload.content,
                )
                repository.add_ai_message(
                    db,
                    thread=thread,
                    role="assistant",
                    content=answer.content,
                    citations=list(answer.citations),
                )
                done = repository.add_ai_event(
                    db,
                    thread=thread,
                    user=current,
                    event_type="assistant_done",
                    title="Ответ готов",
                    message="Ответ сохранен в истории чата.",
                    status="ok",
                    payload=_answer_event_payload(answer),
                )
                repository.audit(
                    db,
                    action="ai_message_answered",
                    user=current,
                    tenant_id=thread.tenant_id,
                    entity_type="ai_thread",
                    entity_id=thread.id,
                )
                db.flush()
                for item in repository.thread_events(db, current, thread):
                    if item["id"] in sent_ids:
                        continue
                    sent_ids.add(item["id"])
                    yield _sse(item["type"], item)
                yield _sse(
                    "final",
                    {
                        "content": answer.content,
                        "eventId": done.id,
                        **_answer_event_payload(answer),
                    },
                )
                db.commit()
            except Exception:
                db.rollback()
                yield _sse(
                    "error",
                    {
                        "message": (
                            "Не удалось получить ответ. Данные WB/1C не менялись."
                        )
                    },
                )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def get_db(request: Request):
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    settings: WebSettings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = repository.get_user_by_session(db, token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user._enabled_report_kind_set = settings.enabled_report_kind_set
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def me_payload(
    user: User,
    clients: list[dict[str, Any]] | None = None,
    *,
    accounting_workflow_enabled: bool = False,
    logistics_analysis_enabled: bool = False,
    logistics_analysis_client_enabled: bool = False,
    logistics_factors_enabled: bool = False,
    logistics_factors_client_enabled: bool = False,
    logistics_tariffs_enabled: bool = False,
    logistics_tariffs_client_enabled: bool = False,
    logistics_routes_enabled: bool = False,
    logistics_routes_client_enabled: bool = False,
    logistics_measurements_enabled: bool = False,
    logistics_measurements_client_enabled: bool = False,
    logistics_return_reasons_enabled: bool = False,
    logistics_return_reasons_client_enabled: bool = False,
) -> dict[str, Any]:
    tenants = [
        {
            "id": item.tenant_id,
            "name": item.tenant.name,
            "role": item.role,
        }
        for item in user.access
    ]
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "tenants": tenants,
        "clients": clients or [],
        "accountingWorkflowEnabled": accounting_workflow_enabled
        and any(item.role in repository.STAFF_ROLES for item in user.access),
        "logisticsAnalysisEnabled": logistics_analysis_enabled
        and (
            logistics_analysis_client_enabled
            or any(item.role in repository.STAFF_ROLES for item in user.access)
        ),
        "logisticsAnalysisClientEnabled": (
            logistics_analysis_enabled and logistics_analysis_client_enabled
        ),
        "logisticsOrdersEnabled": logistics_analysis_enabled
        and any(item.role in repository.STAFF_ROLES for item in user.access),
        "logisticsFactorsEnabled": logistics_analysis_enabled
        and logistics_factors_enabled
        and (
            any(item.role in repository.STAFF_ROLES for item in user.access)
            or (
                logistics_analysis_client_enabled
                and logistics_factors_client_enabled
            )
        ),
        "logisticsFactorsClientEnabled": logistics_analysis_enabled
        and logistics_analysis_client_enabled
        and logistics_factors_enabled
        and logistics_factors_client_enabled,
        "logisticsTariffsEnabled": logistics_analysis_enabled
        and logistics_factors_enabled
        and logistics_tariffs_enabled
        and (
            any(item.role in repository.STAFF_ROLES for item in user.access)
            or (
                logistics_analysis_client_enabled
                and logistics_factors_client_enabled
                and logistics_tariffs_client_enabled
            )
        ),
        "logisticsTariffsClientEnabled": logistics_analysis_enabled
        and logistics_analysis_client_enabled
        and logistics_factors_enabled
        and logistics_factors_client_enabled
        and logistics_tariffs_enabled
        and logistics_tariffs_client_enabled,
        "logisticsRoutesEnabled": logistics_analysis_enabled
        and logistics_factors_enabled
        and logistics_routes_enabled
        and (
            any(item.role in repository.STAFF_ROLES for item in user.access)
            or (
                logistics_analysis_client_enabled
                and logistics_factors_client_enabled
                and logistics_routes_client_enabled
            )
        ),
        "logisticsRoutesClientEnabled": logistics_analysis_enabled
        and logistics_analysis_client_enabled
        and logistics_factors_enabled
        and logistics_factors_client_enabled
        and logistics_routes_enabled
        and logistics_routes_client_enabled,
        "logisticsMeasurementsEnabled": logistics_analysis_enabled
        and logistics_factors_enabled
        and logistics_measurements_enabled
        and (
            any(item.role in repository.STAFF_ROLES for item in user.access)
            or (
                logistics_analysis_client_enabled
                and logistics_factors_client_enabled
                and logistics_measurements_client_enabled
            )
        ),
        "logisticsMeasurementsClientEnabled": logistics_analysis_enabled
        and logistics_analysis_client_enabled
        and logistics_factors_enabled
        and logistics_factors_client_enabled
        and logistics_measurements_enabled
        and logistics_measurements_client_enabled,
        "logisticsReturnReasonsEnabled": logistics_analysis_enabled
        and logistics_factors_enabled
        and logistics_return_reasons_enabled
        and (
            any(item.role in repository.STAFF_ROLES for item in user.access)
            or (
                logistics_analysis_client_enabled
                and logistics_factors_client_enabled
                and logistics_return_reasons_client_enabled
            )
        ),
        "logisticsReturnReasonsClientEnabled": logistics_analysis_enabled
        and logistics_analysis_client_enabled
        and logistics_factors_enabled
        and logistics_factors_client_enabled
        and logistics_return_reasons_enabled
        and logistics_return_reasons_client_enabled,
    }


def _workflow_period(value: str) -> date:
    try:
        year, month = (int(item) for item in value.split("-", 1))
        return date(year, month, 1)
    except (TypeError, ValueError) as exc:
        raise accounting_workflow.WorkflowError("invalid periodMonth") from exc


def _workflow_tenant_id(user: User, requested: str | None) -> str:
    if requested:
        return requested
    for item in user.access:
        if item.role in repository.STAFF_ROLES:
            return item.tenant_id
    raise accounting_workflow.WorkflowPermissionError("staff role required")


def _workflow_csrf_token(request: Request, settings: WebSettings) -> str:
    session_token = request.cookies.get(settings.session_cookie_name, "")
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _require_workflow_csrf(request: Request, settings: WebSettings) -> None:
    if not settings.accounting_workflow_enabled:
        raise HTTPException(status_code=404, detail="accounting workflow is disabled")
    expected = _workflow_csrf_token(request, settings)
    actual = request.headers.get("X-CSRF-Token", "")
    if not actual or not security.constant_time_equal(actual, expected):
        raise HTTPException(status_code=403, detail="invalid CSRF token")


def _raise_workflow_http_error(
    db: Session, exc: accounting_workflow.WorkflowError
) -> None:
    if getattr(exc, "persist_changes", False):
        db.commit()
    else:
        db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def user_payload(user: User, viewer: User) -> dict[str, Any]:
    visible_tenants = set(repository.allowed_tenant_ids(viewer))
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "isActive": user.is_active,
        "createdAt": user.created_at.isoformat(),
        "tenants": [
            {
                "id": item.tenant_id,
                "name": item.tenant.name,
                "role": item.role,
            }
            for item in user.access
            if item.tenant_id in visible_tenants
        ],
    }


def thread_payload(
    thread, messages, events: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": thread.id,
        "tenantId": thread.tenant_id,
        "clientId": thread.client_id,
        "reportId": thread.report_run_id,
        "title": thread.title,
        "scope": thread.scope or {},
        "scopeHash": thread.scope_hash,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "toolName": message.tool_name,
                "citations": message.citations or [],
                "createdAt": message.created_at.isoformat(),
            }
            for message in messages
        ],
        "events": events or [],
    }


def _answer_event_payload(answer) -> dict[str, Any]:
    return {
        "answerSource": answer.answer_source,
        "model": answer.model,
        "fallbackReason": answer.fallback_reason,
        "toolNames": list(answer.tool_names),
    }


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _mapping_upload_target_name(file_name: str) -> str:
    safe_name = Path(file_name).name.strip()
    suffix = Path(safe_name).suffix.lower()
    if suffix not in MAPPING_UPLOAD_ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="mapping file must be TXT, TSV or CSV",
        )
    stem = Path(safe_name).stem.strip()
    safe_stem = re.sub(r"[^\w .-]+", "_", stem, flags=re.UNICODE)
    safe_stem = re.sub(r"\s+", "_", safe_stem, flags=re.UNICODE).strip("._-")
    if not safe_stem:
        raise HTTPException(status_code=400, detail="mapping file name is empty")
    return f"{safe_stem}.txt"


async def _save_mapping_upload(
    settings: WebSettings,
    file: UploadFile,
) -> tuple[str, int]:
    target_name = _mapping_upload_target_name(file.filename or "")
    mapping_dir = settings.source_refresh_mapping_path
    mapping_dir.mkdir(parents=True, exist_ok=True)
    target_path = mapping_dir / target_name
    size_bytes = await _write_upload_file(file, target_path)
    return target_name, size_bytes


async def _write_upload_file(file: UploadFile, target_path: Path) -> int:
    size_bytes = 0
    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > MAPPING_UPLOAD_MAX_BYTES:
                    output.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail="mapping file is too large",
                    )
                output.write(chunk)
    finally:
        await file.close()
    if size_bytes == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="mapping file is empty")
    return size_bytes


def _first_tenant_id(user: User) -> str | None:
    return user.access[0].tenant_id if user.access else None


def _resolve_client_tenant_or_400(
    db: Session,
    user: User,
    *,
    client_id: str | None = None,
    tenant_id: str | None = None,
) -> tuple[str, str]:
    if client_id:
        try:
            client = repository.require_client_access(db, user, client_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        if tenant_id and tenant_id != client.tenant_id:
            raise HTTPException(status_code=400, detail="client tenant mismatch")
        return client.tenant_id, client.id
    if tenant_id:
        if tenant_id not in repository.allowed_tenant_ids(user):
            raise HTTPException(status_code=404, detail="tenant not found")
        tenant = db.get(repository.Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="tenant not found")
        client = repository.ensure_client_for_tenant(
            db,
            tenant_id=tenant.id,
            name=tenant.name,
        )
        return tenant.id, client.id
    clients = repository.list_clients_for_user(db, user)
    if len(clients) == 1:
        return str(clients[0]["tenantId"]), str(clients[0]["clientId"])
    raise HTTPException(status_code=400, detail="client is required")


def _resolve_latest_client_id_or_400(
    db: Session,
    user: User,
    client_id: str | None,
) -> str:
    if client_id:
        try:
            repository.require_client_access(db, user, client_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        return client_id
    clients = repository.list_clients_for_user(db, user)
    if len(clients) == 1:
        return str(clients[0]["clientId"])
    raise HTTPException(status_code=400, detail="client is required")


def _report_list_item(report: ReportRun) -> dict[str, Any]:
    return {
        "id": report.id,
        "tenantId": report.tenant_id,
        "clientId": report.client_id,
        "reportKind": report.report_kind,
        "organizationId": report.organization_id,
        "title": report.title,
        "client": report.client_name,
        "period": f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}",
        "periodStart": report.period_start.isoformat(),
        "periodEnd": report.period_end.isoformat(),
        "periodStatus": report.period_status,
        "generatedAt": report.generated_at.isoformat(),
        "methodologyVersion": report.methodology_version,
        "status": report.status,
        "publicationStatus": report.publication_status,
        "isCurrent": report.is_current,
        "lineageType": report.lineage_type,
    }


def _report_excel_export_path(
    db: Session,
    report: ReportRun,
    settings: WebSettings,
) -> Path | None:
    return repository.report_artifact_path(
        db,
        report,
        "excel",
        settings.export_root_path,
    ) or repository.report_file_path(report, settings.export_root_path)


def _contract_revision_token(value: str) -> str:
    match = re.search(r"(?:^|-)(v\d+)$", value.strip(), flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _require_report_or_404(db: Session, user: User, report_id: str):
    try:
        report = repository.require_report(db, user, report_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    enabled = getattr(user, "_enabled_report_kind_set", {MARKETPLACE_UNIT_ECONOMICS})
    if report.report_kind not in enabled:
        raise HTTPException(status_code=404, detail="report not found")
    return report


def _require_thread_or_404(db: Session, user: User, thread_id: str):
    try:
        return repository.require_thread(db, user, thread_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="thread not found") from exc


def _require_staff_or_403(user: User, tenant_id: str) -> None:
    try:
        repository.require_staff(user, tenant_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="staff role required") from exc


def _require_logistics_access_or_404(
    user: User,
    tenant_id: str,
    settings: WebSettings,
    *,
    staff_only: bool = False,
) -> None:
    is_staff = repository.has_role(user, repository.STAFF_ROLES, tenant_id)
    allowed = settings.logistics_analysis_enabled and (
        is_staff or (settings.logistics_analysis_client_enabled and not staff_only)
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="logistics analysis not found")


def _require_logistics_factors_access_or_404(
    user: User,
    tenant_id: str,
    settings: WebSettings,
) -> None:
    is_staff = repository.has_role(user, repository.STAFF_ROLES, tenant_id)
    allowed = (
        settings.logistics_analysis_enabled
        and settings.logistics_factors_enabled
        and (
            is_staff
            or (
                settings.logistics_analysis_client_enabled
                and settings.logistics_factors_client_enabled
            )
        )
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="logistics factors not found")


def _require_logistics_tariffs_access_or_404(
    user: User,
    tenant_id: str,
    settings: WebSettings,
) -> None:
    is_staff = repository.has_role(user, repository.STAFF_ROLES, tenant_id)
    allowed = (
        settings.logistics_analysis_enabled
        and settings.logistics_factors_enabled
        and settings.logistics_tariffs_enabled
        and (
            is_staff
            or (
                settings.logistics_analysis_client_enabled
                and settings.logistics_factors_client_enabled
                and settings.logistics_tariffs_client_enabled
            )
        )
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="logistics tariffs not found")


def _require_logistics_routes_access_or_404(
    user: User,
    tenant_id: str,
    settings: WebSettings,
) -> None:
    is_staff = repository.has_role(user, repository.STAFF_ROLES, tenant_id)
    allowed = (
        settings.logistics_analysis_enabled
        and settings.logistics_factors_enabled
        and settings.logistics_routes_enabled
        and (
            is_staff
            or (
                settings.logistics_analysis_client_enabled
                and settings.logistics_factors_client_enabled
                and settings.logistics_routes_client_enabled
            )
        )
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="logistics routes not found")


def _require_logistics_measurements_access_or_404(
    user: User,
    tenant_id: str,
    settings: WebSettings,
) -> None:
    is_staff = repository.has_role(user, repository.STAFF_ROLES, tenant_id)
    allowed = (
        settings.logistics_analysis_enabled
        and settings.logistics_factors_enabled
        and settings.logistics_measurements_enabled
        and (
            is_staff
            or (
                settings.logistics_analysis_client_enabled
                and settings.logistics_factors_client_enabled
                and settings.logistics_measurements_client_enabled
            )
        )
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="logistics measurements not found")


def _require_logistics_return_reasons_access_or_404(
    user: User,
    tenant_id: str,
    settings: WebSettings,
) -> None:
    is_staff = repository.has_role(user, repository.STAFF_ROLES, tenant_id)
    allowed = (
        settings.logistics_analysis_enabled
        and settings.logistics_factors_enabled
        and settings.logistics_return_reasons_enabled
        and (
            is_staff
            or (
                settings.logistics_analysis_client_enabled
                and settings.logistics_factors_client_enabled
                and settings.logistics_return_reasons_client_enabled
            )
        )
    )
    if not allowed:
        raise HTTPException(
            status_code=404,
            detail="logistics return reasons not found",
        )


def _reject_client_financial_recommendations(db: Session, user: User, thread) -> None:
    if repository.has_role(user, repository.STAFF_ROLES, thread.tenant_id):
        return
    if not thread.report_run_id:
        return
    report = db.get(ReportRun, thread.report_run_id)
    if report is None:
        return
    _reject_client_report_recommendations(db, user, report)


def _reject_client_report_recommendations(
    db: Session,
    user: User,
    report: ReportRun,
) -> None:
    if repository.has_role(user, repository.STAFF_ROLES, report.tenant_id):
        return
    if repository.report_publication_blockers(db, report):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Финансовая проверка не пройдена. Клиентские рекомендации "
                "заблокированы до подтверждения расчёта прибылей и убытков."
            ),
        )


def _raise_mapping_error(exc: mapping_service.MappingServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _run_mapping_upload_refresh(
    app: FastAPI,
    db: Session,
    *,
    current: User,
    report: ReportRun,
    file_name: str,
) -> dict[str, Any]:
    reason = (
        f"Автоматическая пересборка после загрузки сопоставления WB ↔ 1C: {file_name}"
    )
    try:
        payload = app.state.auto_refresh_service.run(
            db,
            user=current,
            report=report,
            reason=reason,
        )
    except AutoRefreshDisabledError as exc:
        return {
            "status": "disabled",
            "safeMessage": str(exc),
        }
    except AutoRefreshBusyError as exc:
        return {
            "status": "busy",
            "safeMessage": str(exc),
        }
    except AutoRefreshUnavailableError as exc:
        return {
            "status": "failed",
            "reviewStatus": "needs_review",
            "safeMessage": str(exc),
        }
    return payload


def _include_staff_readiness(user: User, tenant_id: str) -> bool:
    return repository.has_role(user, repository.STAFF_ROLES, tenant_id)


def _checked_optional_thread_id(
    db: Session,
    user: User,
    thread_id: str | None,
    *,
    report_id: str,
) -> str | None:
    if not thread_id:
        return None
    thread = _require_thread_or_404(db, user, thread_id)
    if thread.report_run_id != report_id:
        raise HTTPException(status_code=409, detail="thread/report scope mismatch")
    return thread.id


def _client_draft_instruction(payload: ClientDraftRefineRequest) -> str:
    quick_actions = {
        "assemble": "Собрать чистый клиентский черновик по расчетной витрине.",
        "shorten": "Сократить текст, оставить главный вывод, факты и следующий шаг.",
        "soften": "Сделать формулировки мягче и осторожнее для клиента.",
        "add_checks": "Добавить, что именно нужно проверить перед финальным выводом.",
        "clarify_limits": "Уточнить ограничения данных и не делать лишних выводов.",
        "fact_check": (
            "Проверить текст по фактам расчетной витрины и убрать неподтвержденное."
        ),
    }
    parts = [quick_actions.get(payload.action, payload.action).strip()]
    if payload.instruction.strip():
        parts.append(payload.instruction.strip())
    return "\n".join(part for part in parts if part)


def _resolve_report_workbook(
    requested_path: str | None, default_path: Path, allowed_root: Path
) -> Path:
    path = Path(requested_path).resolve() if requested_path else default_path.resolve()
    allowed = allowed_root.resolve()
    if path != allowed and allowed not in path.parents:
        raise HTTPException(status_code=400, detail="workbook path is outside reports")
    return path


def _report_id_from_workbook(workbook: Path) -> str:
    stamp = security.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_stem = "".join(
        char.lower() if char.isalnum() else "_" for char in workbook.stem
    ).strip("_")
    return f"{safe_stem or 'excel_mvp'}_{stamp}"


def _ozon_export_period_label(
    diagnostics: dict[str, Any],
    *,
    period_start: date | None,
    period_end: date | None,
) -> str:
    latest = diagnostics.get("latestRun") or {}
    start = period_start.isoformat() if period_start else latest.get("periodStart")
    end = period_end.isoformat() if period_end else latest.get("periodEnd")
    if start or end:
        return _safe_path_segment(f"{start or 'from'}_{end or 'to'}")
    return "latest"


def _analytical_report_dir(settings: WebSettings, report_id: str) -> Path:
    output_dir = (
        settings.export_root_path / "analytical_reports" / _safe_path_segment(report_id)
    ).resolve()
    allowed = settings.export_root_path.resolve()
    if output_dir != allowed and allowed not in output_dir.parents:
        raise HTTPException(status_code=400, detail="report path is outside reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _safe_path_segment(value: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in value
    )
    return safe.strip("_") or "report"


def _analytical_report_period(
    report: ReportRun,
    payload: AnalyticalReportRequest,
) -> tuple[date, date]:
    if payload.scope == "full":
        if payload.periodStart is not None or payload.periodEnd is not None:
            raise ValueError("Для полного периода отдельные даты не указываются.")
        return report.period_start, report.period_end
    if payload.scope == "last_closed_week":
        if payload.periodStart is not None or payload.periodEnd is not None:
            raise ValueError(
                "Для последней закрытой недели даты определяются автоматически."
            )
        return last_closed_week_period(report)
    if payload.periodStart is None or payload.periodEnd is None:
        raise ValueError("Для произвольного периода укажите дату начала и конца.")
    if payload.periodStart > payload.periodEnd:
        raise ValueError("Дата начала не может быть позже даты конца.")
    if (
        payload.periodStart < report.period_start
        or payload.periodEnd > report.period_end
    ):
        raise ValueError(
            "Выбранный период должен находиться внутри периода report_id "
            f"{report.period_start}..{report.period_end}."
        )
    return payload.periodStart, payload.periodEnd


def _analytical_report_basename(
    report: ReportRun,
    *,
    branded: bool,
    period_start: date | None = None,
    period_end: date | None = None,
) -> str:
    start = period_start or report.period_start
    end = period_end or report.period_end
    period = f"{start:%d.%m.%Y}-{end:%d.%m.%Y}"
    if branded:
        return (
            "Фирменный аналитический отчёт Шумейко и Партнеры "
            f"по юнит-экономике WB за период {period}"
        )
    return f"Аналитический отчёт по юнит-экономике WB за период {period}"


def _analytical_report_payload(
    report_id: str,
    artifacts: ClientAnalyticalReportArtifacts,
    *,
    scope: str,
    period_start: date,
    period_end: date,
    requested_period_start: date,
    requested_period_end: date,
    period_fallback: bool,
) -> dict[str, Any]:
    return {
        "reportId": report_id,
        "status": "ready",
        "contractVersion": CLIENT_REPORT_CONTRACT_VERSION,
        "scope": scope,
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "requestedPeriodStart": requested_period_start.isoformat(),
        "requestedPeriodEnd": requested_period_end.isoformat(),
        "actualPeriodStart": period_start.isoformat(),
        "actualPeriodEnd": period_end.isoformat(),
        "periodFallback": period_fallback,
        "period": f"{period_start:%d.%m.%Y} - {period_end:%d.%m.%Y}",
        "sourceSha256": getattr(artifacts, "source_sha256", ""),
        "files": {
            "markdown": {
                "status": "ok",
                "url": f"/api/reports/{report_id}/analytical-report.md",
                "filename": artifacts.markdown_path.name,
            },
            "docx": {
                "status": "ok",
                "url": f"/api/reports/{report_id}/analytical-report.docx",
                "filename": artifacts.docx_path.name,
            },
            "pdf": {
                "status": artifacts.pdf_status,
                "url": (
                    f"/api/reports/{report_id}/analytical-report.pdf"
                    if artifacts.pdf_path is not None
                    else None
                ),
                "filename": artifacts.pdf_path.name if artifacts.pdf_path else None,
                "message": artifacts.pdf_message,
            },
        },
        "limitations": [
            "Ограничения конкретного периода и источников включены в документ.",
            "Генератор отчёта не меняет данные WB, 1С или CRM.",
        ],
    }


def _latest_analytical_report_path(
    settings: WebSettings,
    report_id: str,
    extension: str,
) -> Path | None:
    normalized_extension = extension.lower().lstrip(".")
    if normalized_extension not in {"md", "docx", "pdf"}:
        return None
    report_dir = _analytical_report_dir(settings, report_id)
    candidates = sorted(
        report_dir.glob(f"*.{normalized_extension}"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    path = candidates[0].resolve()
    allowed = settings.export_root_path.resolve()
    if path != allowed and allowed not in path.parents:
        return None
    return path


def _analytical_report_media_type(extension: str) -> str:
    return {
        "docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "pdf": "application/pdf",
        "md": "text/markdown; charset=utf-8",
    }.get(extension.lower().lstrip("."), "application/octet-stream")


def _live_check(
    db: Session,
    user: User,
    report,
    *,
    source_type: str,
    check_type: str,
    lookup: str,
    settings: WebSettings,
) -> dict[str, Any]:
    try:
        result = repository.live_check_payload(
            db,
            user=user,
            report=report,
            source_type=source_type,
            check_type=check_type,
            lookup_key=lookup,
            enabled=(
                settings.external_integrations_enabled and settings.live_checks_enabled
            ),
            cache_ttl_minutes=settings.live_check_cache_ttl_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return result


app = create_app()
