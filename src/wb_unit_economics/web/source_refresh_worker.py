from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.models import SourceRefreshRun, User
from wb_unit_economics.web.settings import WebSettings

SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


class SourceRefreshWorkerLaunchError(RuntimeError):
    """Raised when a queued source refresh cannot be handed to its worker."""


def enqueue_source_refresh_worker(
    db: Session,
    *,
    source_refresh_service: Any,
    worker_launcher: Any | None,
    user: User | None = None,
    **run_options: Any,
) -> dict[str, Any]:
    """Persist a queued run and hand it to the configured external worker."""
    payload = source_refresh_service.enqueue(db, user=user, **run_options)
    queue_enabled = bool(
        getattr(
            getattr(source_refresh_service, "settings", None),
            "source_refresh_task_queue_enabled",
            False,
        )
    )
    if queue_enabled and payload.get("status") == "queued":
        refresh_run = db.get(SourceRefreshRun, str(payload["id"]))
        if refresh_run is None:
            raise SourceRefreshWorkerLaunchError("queued source refresh was not found")
        repository.ensure_source_refresh_task_chain(db, refresh_run)
        payload = {
            **payload,
            **repository.source_refresh_queue_payload(db, refresh_run),
        }
    db.commit()
    if queue_enabled:
        return payload
    if payload.get("finishedAt") is not None or payload.get("status") != "queued":
        return payload
    return launch_source_refresh_worker(
        db,
        refresh_run_id=str(payload["id"]),
        worker_launcher=worker_launcher,
        user=user,
        fallback_payload=payload,
    )


def launch_source_refresh_worker(
    db: Session,
    *,
    refresh_run_id: str,
    worker_launcher: Any | None,
    user: User | None = None,
    fallback_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hand an existing queued run to a worker and persist its ownership."""
    if worker_launcher is None and fallback_payload is not None:
        return fallback_payload
    refresh_run = db.get(SourceRefreshRun, refresh_run_id)
    if refresh_run is None:
        if fallback_payload is not None:
            return fallback_payload
        raise LookupError("source refresh run not found")
    payload = repository.source_refresh_run_payload(refresh_run)
    if refresh_run.finished_at is not None or refresh_run.status != "queued":
        return payload
    if worker_launcher is None:
        return payload

    try:
        worker_unit = worker_launcher.launch(refresh_run_id)
    except SourceRefreshWorkerLaunchError:
        if refresh_run is not None and refresh_run.finished_at is None:
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="failed",
                failure_code="worker_launch_failed",
                error_message="source refresh worker could not be started",
                finished_at=security.utcnow(),
            )
            repository.audit(
                db,
                action="source_refresh_worker_launch_failed",
                user=user,
                tenant_id=refresh_run.tenant_id,
                entity_type="source_refresh_run",
                entity_id=refresh_run.id,
                payload={"workerAssigned": False},
            )
            db.commit()
        raise

    repository.update_source_refresh_run(
        db,
        refresh_run,
        worker_id=f"systemd:{refresh_run_id}",
        heartbeat_at=security.utcnow(),
    )
    repository.audit(
        db,
        action="source_refresh_worker_started",
        user=user,
        tenant_id=refresh_run.tenant_id,
        entity_type="source_refresh_run",
        entity_id=refresh_run.id,
        payload={"workerAssigned": True, "workerUnit": worker_unit},
    )
    db.commit()
    return repository.source_refresh_run_payload(refresh_run)


@dataclass(frozen=True)
class SystemdSourceRefreshWorkerLauncher:
    settings: WebSettings

    def launch(self, refresh_run_id: str) -> str:
        if not SAFE_RUN_ID.fullmatch(refresh_run_id):
            raise SourceRefreshWorkerLaunchError("invalid_source_refresh_run_id")
        unit = (
            f"{self.settings.source_refresh_worker_unit_prefix}"
            f"@{refresh_run_id}.service"
        )
        try:
            result = subprocess.run(
                ["systemctl", "start", "--no-block", unit],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceRefreshWorkerLaunchError(
                "source_refresh_worker_start_failed"
            ) from exc
        if result.returncode != 0:
            raise SourceRefreshWorkerLaunchError("source_refresh_worker_start_failed")
        return unit


def production_source_refresh_worker_launcher(
    settings: WebSettings,
) -> SystemdSourceRefreshWorkerLauncher | None:
    backend = settings.source_refresh_worker_backend.strip().lower()
    if backend == "background":
        return None
    if backend == "systemd":
        return SystemdSourceRefreshWorkerLauncher(settings)
    if backend != "auto":
        raise ValueError(f"unsupported source refresh worker backend: {backend}")
    if settings.database_url.strip().lower().startswith("sqlite"):
        return None
    return SystemdSourceRefreshWorkerLauncher(settings)
