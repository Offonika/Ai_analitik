from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from wb_unit_economics.web.models import ReportRun, User
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    SourceRefreshBusyError,
    SourceRefreshDisabledError,
    SourceRefreshService,
)


class AutoRefreshDisabledError(RuntimeError):
    pass


class AutoRefreshBusyError(RuntimeError):
    pass


class OnecAutoRefreshService:
    """Compatibility wrapper for the legacy 1C refresh button and AI tool."""

    def __init__(
        self,
        settings: WebSettings,
        *,
        source_refresh_service: SourceRefreshService | None = None,
    ) -> None:
        self.settings = settings
        self.source_refresh_service = source_refresh_service or SourceRefreshService(
            settings
        )

    def run(
        self,
        db: Session,
        *,
        user: User,
        report: ReportRun,
        reason: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            payload = self.source_refresh_service.run(
                db,
                tenant_id=report.tenant_id,
                mode="onec-only",
                credential_source="tenant",
                dry_run=False,
                user=user,
                source_report=report,
                reason=reason,
            )
        except SourceRefreshDisabledError as exc:
            raise AutoRefreshDisabledError(str(exc)) from exc
        except SourceRefreshBusyError as exc:
            raise AutoRefreshBusyError(str(exc)) from exc

        payload["jobType"] = "source_refresh"
        payload["sourceRefreshRunId"] = payload["id"]
        if thread_id:
            payload["threadId"] = thread_id
        return payload
