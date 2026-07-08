#!/usr/bin/env python3
"""Preflight source refresh readiness without external source reads."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun, Tenant, TenantIntegration
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    OZON_REFRESH_ROLES,
    SOURCE_REFRESH_MODES,
    WB_FINANCE_REFRESH_ROLES,
    inspect_mapping_source,
)

READY_INTEGRATION_STATUSES = {"configured", "check_ok"}


def main() -> int:
    args = _parse_args()
    settings = _settings(args)
    blockers: list[str] = []
    warnings: list[str] = []

    try:
        engine = make_engine(settings.database_url)
        session_factory = make_session_factory(engine)
        print(f"Database type: {engine.dialect.name}")
        print(f"Tenant: {args.tenant}")
        print(f"Mode: {args.mode}")
        print(f"Source refresh enabled: {settings.source_refresh_enabled}")
        with session_factory() as db:
            if db.get(Tenant, args.tenant) is None:
                blockers.append(f"tenant not found: {args.tenant}")
            integrations = list(
                db.scalars(
                    select(TenantIntegration)
                    .where(TenantIntegration.tenant_id == args.tenant)
                    .order_by(TenantIntegration.provider)
                )
            )
            _check_integrations(args.mode, integrations, blockers, warnings)
            _print_latest_refresh(db, tenant_id=args.tenant, mode=args.mode)
    except SQLAlchemyError as exc:
        print(f"Source refresh preflight failed: {exc.__class__.__name__}")
        return 2

    if not settings.source_refresh_enabled:
        message = "source refresh is disabled for non-dry-run execution"
        if args.require_enabled:
            blockers.append(message)
        else:
            warnings.append(message)
    _check_mapping(settings, blockers, warnings)
    _check_disk(settings, blockers)

    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")
    if blockers:
        print("Blockers:")
        for item in blockers:
            print(f"- {item}")
        print("Health: blocked")
        return 1
    print("Health: ready_with_warnings" if warnings else "Health: ready")
    return 0


def _check_integrations(
    mode: str,
    integrations: list[TenantIntegration],
    blockers: list[str],
    warnings: list[str],
) -> None:
    print(f"Tenant integrations: {len(integrations)}")
    for item in integrations:
        payload = item.config_payload or {}
        storage = str(payload.get("storage") or "hash_only")
        role = str(payload.get("connectionRole") or "")
        print(
            "- "
            f"{item.provider}: status={item.status}, "
            f"storage={storage}, role={role or 'default'}"
        )
    if mode != "onec-only":
        _check_wb_integrations(integrations, blockers, warnings)
        _check_ozon_integrations(integrations, warnings)
    _check_onec_integration(integrations, blockers)


def _check_wb_integrations(
    integrations: list[TenantIntegration],
    blockers: list[str],
    warnings: list[str],
) -> None:
    wb_items = [
        item
        for item in integrations
        if repository.integration_provider_base(item.provider) == "wb_api"
    ]
    if not wb_items:
        blockers.append("wb_api tenant integration is not configured")
        return
    ready = []
    skipped_roles = []
    for item in wb_items:
        payload = item.config_payload or {}
        role = str(payload.get("connectionRole") or "").strip()
        if role and role not in WB_FINANCE_REFRESH_ROLES:
            skipped_roles.append(item.provider)
            continue
        if _integration_ready(item):
            ready.append(item.provider)
    if ready:
        print(f"WB API ready integrations: {len(ready)}")
        return
    blockers.append("wb_api tenant integrations are not runtime-ready")
    if skipped_roles:
        warnings.append(
            "wb_api integrations skipped by role: " + ", ".join(skipped_roles)
        )


def _check_onec_integration(
    integrations: list[TenantIntegration],
    blockers: list[str],
) -> None:
    integration = next(
        (item for item in integrations if item.provider == "onec_readonly"),
        None,
    )
    if integration is None:
        blockers.append("onec_readonly tenant integration is not configured")
        return
    if not _integration_ready(integration):
        blockers.append("onec_readonly tenant integration is not runtime-ready")
        return
    print("1C read-only integration: runtime-ready")


def _check_ozon_integrations(
    integrations: list[TenantIntegration],
    warnings: list[str],
) -> None:
    ozon_items = [
        item
        for item in integrations
        if repository.integration_provider_base(item.provider) == "ozon_api"
    ]
    if not ozon_items:
        print("Ozon API integrations: not configured (optional)")
        return
    ready = []
    skipped_roles = []
    for item in ozon_items:
        payload = item.config_payload or {}
        role = str(payload.get("connectionRole") or "").strip()
        if role and role not in OZON_REFRESH_ROLES:
            skipped_roles.append(item.provider)
            continue
        if _integration_ready(item):
            ready.append(item.provider)
    if ready:
        print(f"Ozon API ready integrations: {len(ready)}")
    else:
        warnings.append("ozon_api integrations are configured but not runtime-ready")
    if skipped_roles:
        warnings.append(
            "ozon_api integrations skipped by role: " + ", ".join(skipped_roles)
        )


def _integration_ready(item: TenantIntegration) -> bool:
    payload = item.config_payload or {}
    if item.status == "disabled":
        return False
    return (
        item.status in READY_INTEGRATION_STATUSES
        and payload.get("storage") == "encrypted"
    )


def _print_latest_refresh(db: Any, *, tenant_id: str, mode: str) -> None:
    refresh = db.scalar(
        select(SourceRefreshRun)
        .where(
            SourceRefreshRun.tenant_id == tenant_id,
            SourceRefreshRun.mode == mode,
        )
        .order_by(SourceRefreshRun.created_at.desc())
    )
    if refresh is None:
        print("Latest source refresh: none")
        return
    print(
        "Latest source refresh: "
        f"{refresh.mode} {refresh.status} {refresh.created_at.isoformat()}"
    )


def _check_mapping(
    settings: WebSettings,
    blockers: list[str],
    warnings: list[str],
) -> None:
    status, _snapshot_hash, file_count, error_message, payload = inspect_mapping_source(
        settings.source_refresh_mapping_path,
        stale_after_days=max(1, int(settings.source_refresh_mapping_stale_days)),
    )
    age_days = payload.get("ageDays", "")
    print(f"Mapping source: {status}, files={file_count}, ageDays={age_days}")
    if status == "failed":
        blockers.append(f"mapping source is not ready: {error_message}")
    elif status == "stale":
        warnings.append("mapping source is stale")


def _check_disk(settings: WebSettings, blockers: list[str]) -> None:
    min_free_gb = max(0.0, float(settings.source_refresh_min_free_gb))
    if min_free_gb <= 0:
        print("Source refresh root free GiB: not checked")
        return
    probe_path = _existing_path_for_disk_check(settings.source_refresh_root_path)
    free_gb = shutil.disk_usage(probe_path).free / (1024**3)
    print(
        "Source refresh root free GiB: "
        f"{free_gb:.2f} (required {min_free_gb:.2f})"
    )
    if free_gb < min_free_gb:
        blockers.append(
            f"source refresh low disk: free={free_gb:.2f}GiB "
            f"required={min_free_gb:.2f}GiB"
        )


def _existing_path_for_disk_check(path: Path) -> Path:
    current = path.resolve()
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def _settings(args: argparse.Namespace) -> WebSettings:
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL", "")
    values: dict[str, object] = {}
    if database_url:
        values["database_url"] = database_url
    if args.source_refresh_root:
        values["source_refresh_root"] = args.source_refresh_root
    if args.mapping_dir:
        values["source_refresh_mapping_dir"] = args.mapping_dir
    if args.min_free_gb is not None:
        values["source_refresh_min_free_gb"] = args.min_free_gb
    if args.mapping_stale_days is not None:
        values["source_refresh_mapping_stale_days"] = args.mapping_stale_days
    return WebSettings(_env_file=None, **values)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--tenant", default="shumeyko")
    parser.add_argument(
        "--mode",
        choices=sorted(SOURCE_REFRESH_MODES),
        default="daily",
    )
    parser.add_argument("--source-refresh-root", default="")
    parser.add_argument("--mapping-dir", default="")
    parser.add_argument("--min-free-gb", type=float, default=None)
    parser.add_argument("--mapping-stale-days", type=int, default=None)
    parser.add_argument("--require-enabled", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
