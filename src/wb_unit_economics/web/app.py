from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
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

from scripts.build_client_analytical_report import (
    ClientAnalyticalReportArtifacts,
    build_client_analytical_report,
)
from wb_unit_economics.report_exports import write_ozon_diagnostics_excel
from wb_unit_economics.web import integrations, providers, repository, security
from wb_unit_economics.web.ai import AiAnalyst
from wb_unit_economics.web.dashboard_payload import build_dashboard_payload
from wb_unit_economics.web.database import (
    init_db,
    make_engine,
    make_session_factory,
    schema_version,
)
from wb_unit_economics.web.models import ReportRun, SourceRefreshRun, User
from wb_unit_economics.web.refresh import (
    AutoRefreshBusyError,
    AutoRefreshDisabledError,
    OnecAutoRefreshService,
)
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    SourceRefreshBusyError,
    SourceRefreshConfigError,
    SourceRefreshDisabledError,
    SourceRefreshService,
)

STATIC_DIR = Path(__file__).with_name("static")
MAPPING_UPLOAD_ALLOWED_SUFFIXES = {".csv", ".tsv", ".txt"}
MAPPING_UPLOAD_MAX_BYTES = 20 * 1024 * 1024


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    remember_me: bool = False


class ThreadCreateRequest(BaseModel):
    report_id: str | None = None
    client_id: str | None = None
    title: str = "AI-аналитик"


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


class LiveCheckRequest(BaseModel):
    lookup: str = Field(min_length=1, max_length=240)


class OnecAutoRefreshRequest(BaseModel):
    reason: str = Field(default="Аналитик запросил дозагрузку 1С", max_length=4000)
    thread_id: str | None = None


class AnalyticalReportRequest(BaseModel):
    branded: bool = True


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
        pattern="^(daily|weekly|full|onec-only|ozon-only)$",
    )
    dry_run: bool = False
    reason: str = Field(default="", max_length=4000)


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
    refresh_service = auto_refresh_service or OnecAutoRefreshService(runtime_settings)
    source_refresh_service = getattr(refresh_service, "source_refresh_service", None)
    if source_refresh_service is None:
        source_refresh_service = SourceRefreshService(runtime_settings)
    analyst = AiAnalyst(runtime_settings, auto_refresh_service=refresh_service)
    app = FastAPI(title="Shumeyko WB Unit Economics Cabinet", version="0.2.0")
    app.state.settings = runtime_settings
    app.state.session_factory = session_factory
    app.state.analyst = analyst
    app.state.auto_refresh_service = refresh_service
    app.state.source_refresh_service = source_refresh_service
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

    @app.get("/api/health")
    def health(db: DbSession) -> dict[str, Any]:
        bind = db.get_bind()
        latest_report = db.scalar(
            select(ReportRun)
            .where(
                ReportRun.publication_status == "published",
                ReportRun.is_current.is_(True),
            )
            .order_by(ReportRun.generated_at.desc())
        )
        latest_refresh = db.scalar(
            select(SourceRefreshRun).order_by(SourceRefreshRun.created_at.desc())
        )
        return {
            "status": "ok",
            "databaseType": bind.dialect.name,
            "schemaVersion": schema_version(bind),
            "latestPublishedReportId": latest_report.id if latest_report else "",
            "latestSourceRefreshStatus": latest_refresh.status
            if latest_refresh
            else "",
            "latestSourceRefreshRunId": latest_refresh.id if latest_refresh else "",
            "latestSourceRefreshMode": latest_refresh.mode if latest_refresh else "",
            "latestSourceRefreshCreatedAt": (
                latest_refresh.created_at.isoformat() if latest_refresh else ""
            ),
            "latestSourceRefreshActive": (
                latest_refresh.status in repository.ACTIVE_SOURCE_REFRESH_STATUSES
                and latest_refresh.finished_at is None
            )
            if latest_refresh
            else False,
        }

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
        return me_payload(user, clients)

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
        return me_payload(current, clients)

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
    ) -> dict[str, Any]:
        tenant_id, resolved_client_id = _resolve_client_tenant_or_400(
            db,
            current,
            client_id=client_id,
        )
        _require_staff_or_403(current, tenant_id)
        return {
            "latest": repository.latest_source_refresh_payload(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                include_sensitive=False,
            )
        }

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
            },
        )
        db.commit()
        return {
            "status": "uploaded",
            "fileName": target_name,
            "sizeBytes": size_bytes,
            "latestSourceRefresh": repository.latest_source_refresh_payload(
                db,
                tenant_id=tenant_id,
                client_id=resolved_client_id,
                include_sensitive=False,
            ),
        }

    @app.post("/api/clients/{client_id}/source-refresh")
    def run_client_source_refresh(
        client_id: str,
        payload: SourceRefreshRequest,
        background_tasks: BackgroundTasks,
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
            "Ручная проверка готовности source refresh"
            if payload.dry_run
            else "Ручной full source refresh из web-кабинета"
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
                )
            else:
                refresh_payload = app.state.source_refresh_service.enqueue(
                    db,
                    tenant_id=tenant_id,
                    client_id=resolved_client_id,
                    mode=payload.mode,
                    credential_source="tenant",
                    user=current,
                    reason=reason,
                )
        except SourceRefreshDisabledError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SourceRefreshBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SourceRefreshConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.commit()
        if not payload.dry_run and refresh_payload.get("finishedAt") is None:
            background_tasks.add_task(
                _run_source_refresh_background,
                app.state.session_factory,
                app.state.source_refresh_service,
                refresh_payload["id"],
            )
        refresh_run = db.get(SourceRefreshRun, refresh_payload["id"])
        return {
            "latest": repository.source_refresh_run_payload(
                refresh_run,
                include_sensitive=False,
            )
            if refresh_run is not None
            else refresh_payload,
        }

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
                    "live-check. Сохраните ключ заново после настройки "
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
    ) -> dict[str, Any]:
        reports = repository.list_reports_for_user(db, current, client_id=client_id)
        return {"items": [_report_list_item(report) for report in reports]}

    @app.get("/api/clients/{client_id}/reports")
    def list_client_reports(
        client_id: str,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        try:
            reports = repository.list_reports_for_client(db, current, client_id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        return {"items": [_report_list_item(report) for report in reports]}

    @app.get("/api/reports/latest/summary")
    def latest_summary(
        current: CurrentUser,
        db: DbSession,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_client_id = _resolve_latest_client_id_or_400(db, current, client_id)
        report = repository.latest_report_for_client(db, current, resolved_client_id)
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

    @app.get("/api/reports/{report_id}/summary")
    def report_summary(
        report_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
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

    @app.get("/api/reports/{report_id}/freshness")
    def report_freshness(
        report_id: str, current: CurrentUser, db: DbSession
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
        return repository.report_freshness_payload(
            db,
            report,
            include_staff_readiness=_include_staff_readiness(current, report.tenant_id),
        )

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
        thread_id = _checked_optional_thread_id(db, current, payload.thread_id)
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
        thread_id = _checked_optional_thread_id(db, current, payload.thread_id)
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
        workbook_path = repository.report_file_path(
            report, runtime_settings.export_root_path
        )
        if workbook_path is None or not workbook_path.exists():
            raise HTTPException(status_code=404, detail="workbook not found")
        output_dir = _analytical_report_dir(runtime_settings, report.id)
        artifacts = build_client_analytical_report(
            workbook_path=workbook_path,
            output_dir=output_dir,
            basename=_analytical_report_basename(report, branded=payload.branded),
            branded=payload.branded,
        )
        repository.audit(
            db,
            action="analytical_report_generated",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        return _analytical_report_payload(report.id, artifacts)

    @app.get("/api/reports/{report_id}/analytical-report.{extension}")
    def download_analytical_report(
        report_id: str,
        extension: str,
        current: CurrentUser,
        db: DbSession,
    ) -> FileResponse:
        report = _require_report_or_404(db, current, report_id)
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
        limit: int = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        report = _require_report_or_404(db, current, report_id)
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
        report_id: str, current: CurrentUser, db: DbSession
    ) -> FileResponse:
        report = _require_report_or_404(db, current, report_id)
        path = repository.report_artifact_path(
            db, report, "excel", runtime_settings.export_root_path
        ) or repository.report_file_path(report, runtime_settings.export_root_path)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="export not found")
        repository.audit(
            db,
            action="report_exported",
            user=current,
            tenant_id=report.tenant_id,
            entity_type="report_run",
            entity_id=report.id,
        )
        db.commit()
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=report.source_workbook or "shumeyko_wb_excel_mvp.xlsx",
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
        thread_id = _checked_optional_thread_id(db, current, payload.thread_id)
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

    @app.post("/api/ai/threads")
    def create_thread(
        payload: ThreadCreateRequest,
        current: CurrentUser,
        db: DbSession,
    ) -> dict[str, Any]:
        report_id = payload.report_id
        report = None
        if report_id:
            report = _require_report_or_404(db, current, report_id)
        elif payload.client_id:
            client_id = _resolve_latest_client_id_or_400(
                db, current, payload.client_id
            )
            report = repository.latest_report_for_client(db, current, client_id)
        else:
            client_id = _resolve_latest_client_id_or_400(db, current, None)
            report = repository.latest_report_for_client(db, current, client_id)
        access = repository.primary_access(
            current, report.tenant_id if report else None
        )
        thread = repository.create_ai_thread(
            db,
            user=current,
            tenant_id=access.tenant_id,
            report_id=report.id if report else None,
            title=payload.title,
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
                "и read-only инструментами."
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
            db, thread=thread, role="assistant", content=answer.content
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

        def generate():
            sent_ids: set[int] = set()
            try:
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
                    db, thread=thread, role="assistant", content=answer.content
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


def _run_source_refresh_background(
    session_factory: sessionmaker[Session],
    source_refresh_service: SourceRefreshService,
    refresh_run_id: str,
) -> None:
    with session_factory() as db:
        try:
            source_refresh_service.run_existing(db, refresh_run_id)
            db.commit()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                return
            refresh_run = db.get(SourceRefreshRun, refresh_run_id)
            if refresh_run is None or refresh_run.finished_at is not None:
                return
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="failed",
                error_message=(
                    f"{exc.__class__.__name__}: background source refresh failed"
                ),
                finished_at=security.utcnow(),
            )
            repository.audit(
                db,
                action="source_refresh_failed",
                user=None,
                tenant_id=refresh_run.tenant_id,
                entity_type="source_refresh_run",
                entity_id=refresh_run.id,
                payload={
                    "mode": refresh_run.mode,
                    "errorType": exc.__class__.__name__,
                },
            )
            db.commit()


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
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def me_payload(
    user: User,
    clients: list[dict[str, Any]] | None = None,
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
    }


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
        "reportId": thread.report_run_id,
        "title": thread.title,
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "toolName": message.tool_name,
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
        "title": report.title,
        "client": report.client_name,
        "period": f"{report.period_start:%d.%m.%Y} - {report.period_end:%d.%m.%Y}",
        "periodStatus": report.period_status,
        "generatedAt": report.generated_at.isoformat(),
        "methodologyVersion": report.methodology_version,
        "status": report.status,
        "publicationStatus": report.publication_status,
        "isCurrent": report.is_current,
        "lineageType": report.lineage_type,
    }


def _require_report_or_404(db: Session, user: User, report_id: str):
    try:
        return repository.require_report(db, user, report_id)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc


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


def _run_mapping_upload_refresh(
    app: FastAPI,
    db: Session,
    *,
    current: User,
    report: ReportRun,
    file_name: str,
) -> dict[str, Any]:
    reason = (
        "Автоматическая пересборка после загрузки mapping WB ↔ 1C: "
        f"{file_name}"
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
    return payload


def _include_staff_readiness(user: User, tenant_id: str) -> bool:
    return repository.has_role(user, repository.STAFF_ROLES, tenant_id)


def _checked_optional_thread_id(
    db: Session, user: User, thread_id: str | None
) -> str | None:
    if not thread_id:
        return None
    thread = _require_thread_or_404(db, user, thread_id)
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


def _analytical_report_basename(report, *, branded: bool) -> str:
    period = f"{report.period_start:%d.%m.%Y}-{report.period_end:%d.%m.%Y}"
    if branded:
        return (
            "Фирменный аналитический отчет Шумейко и Партнеры "
            f"по юнит-экономике WB за период {period}"
        )
    return f"Аналитический отчет по юнит-экономике WB за период {period}"


def _analytical_report_payload(
    report_id: str,
    artifacts: ClientAnalyticalReportArtifacts,
) -> dict[str, Any]:
    return {
        "reportId": report_id,
        "status": "ready",
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
            "Июнь неполный.",
            "Причина возврата не передается текущими источниками.",
            "AI и генератор отчета не меняют данные WB, 1С или CRM.",
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
            enabled=settings.live_checks_enabled,
            cache_ttl_minutes=settings.live_check_cache_ttl_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return result


app = create_app()
