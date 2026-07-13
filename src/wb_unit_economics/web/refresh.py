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
from wb_unit_economics.web.source_refresh_worker import (
    SourceRefreshWorkerLaunchError,
    enqueue_source_refresh_worker,
    production_source_refresh_worker_launcher,
)


class AutoRefreshDisabledError(RuntimeError):
    pass


class AutoRefreshBusyError(RuntimeError):
    pass


class AutoRefreshUnavailableError(RuntimeError):
    pass


class OnecAutoRefreshService:
    """Compatibility wrapper for the legacy 1C refresh button and AI tool."""

    def __init__(
        self,
        settings: WebSettings,
        *,
        source_refresh_service: SourceRefreshService | None = None,
        worker_launcher: Any | None = None,
    ) -> None:
        self.settings = settings
        self.source_refresh_service = source_refresh_service or SourceRefreshService(
            settings
        )
        self.worker_launcher = (
            production_source_refresh_worker_launcher(settings)
            if worker_launcher is None
            else worker_launcher
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
            payload = enqueue_source_refresh_worker(
                db,
                source_refresh_service=self.source_refresh_service,
                worker_launcher=self.worker_launcher,
                tenant_id=report.tenant_id,
                mode="onec-only",
                credential_source="tenant",
                user=user,
                source_report=report,
                reason=reason,
            )
        except SourceRefreshDisabledError as exc:
            raise AutoRefreshDisabledError(str(exc)) from exc
        except SourceRefreshBusyError as exc:
            raise AutoRefreshBusyError(str(exc)) from exc
        except SourceRefreshWorkerLaunchError as exc:
            raise AutoRefreshUnavailableError(
                "Не удалось запустить отдельный процесс обновления."
            ) from exc

        payload["jobType"] = "source_refresh"
        payload["sourceRefreshRunId"] = payload["id"]
        if thread_id:
            payload["threadId"] = thread_id
        return payload
