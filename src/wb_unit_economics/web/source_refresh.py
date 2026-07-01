from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.build_excel_mvp_from_snapshots import build_excel_mvp_from_args
from wb_unit_economics.onec_odata import (
    DEFAULT_SAMPLE_COLLECTIONS,
    GROSS_PROFIT_SAMPLE_COLLECTIONS,
    SERVICE_SAMPLE_COLLECTIONS,
    OnecODataConfigError,
    OnecODataSettings,
    OnecSampleExportResult,
    export_onec_samples,
)
from wb_unit_economics.wb_finance import (
    WbFinanceConfigError,
    WbFinancePageResult,
    WbFinanceSellerAccount,
    WbFinanceSettings,
    WbSalesReportListPageResult,
    export_wb_finance,
    export_wb_sales_report_list,
)
from wb_unit_economics.web import integrations, repository, security
from wb_unit_economics.web.dashboard_payload import build_dashboard_payload
from wb_unit_economics.web.models import (
    ReportRun,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    Tenant,
    TenantIntegration,
    User,
)
from wb_unit_economics.web.settings import WebSettings

SOURCE_REFRESH_MODES = {"daily", "weekly", "full", "onec-only"}
CREDENTIAL_SOURCES = {"tenant", "env"}
ONEC_REFRESH_COLLECTIONS = (
    *DEFAULT_SAMPLE_COLLECTIONS,
    *GROSS_PROFIT_SAMPLE_COLLECTIONS,
    *SERVICE_SAMPLE_COLLECTIONS,
)
MANDATORY_ONEC_COLLECTION_IDS = {
    "nomenclature",
    "organizations",
    "barcodes",
    "sales_register",
}
MANDATORY_OK_STATUSES = {"loaded", "empty_expected"}
OPTIONAL_OK_STATUSES = {"loaded", "empty_expected"}
REVIEW_STATUSES = {"needs_review", "stale", "partial_source"}
WB_FINANCE_REFRESH_ROLES = {"finance_reports", "full_readonly"}
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class SourceRefreshDisabledError(RuntimeError):
    pass


class SourceRefreshBusyError(RuntimeError):
    pass


class SourceRefreshConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceCredentials:
    wb_settings: WbFinanceSettings | None
    onec_settings: OnecODataSettings | None
    wb_cabinet_ids: dict[str, str]
    issues: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CollectorContext:
    db: Session
    refresh_run: SourceRefreshRun
    credentials: SourceCredentials
    root_dir: Path
    period_start: date
    period_end: date
    mode: str


@dataclass(frozen=True)
class CollectorResult:
    collection: SourceRefreshCollection | None = None
    output_dir: Path | None = None


@dataclass(frozen=True)
class SourceCollector:
    source_type: str
    label: str
    required: bool
    modes: frozenset[str]
    roles: frozenset[str]
    collect: Callable[[SourceRefreshService, CollectorContext], CollectorResult]

    def supports(self, mode: str) -> bool:
        return mode in self.modes


@dataclass(frozen=True)
class CollectorOutputs:
    output_dirs: dict[str, Path]
    mapping_collection: SourceRefreshCollection


class SourceRefreshService:
    def __init__(
        self,
        settings: WebSettings,
        *,
        wb_finance_exporter: Callable[..., list[WbFinancePageResult]] = (
            export_wb_finance
        ),
        wb_report_list_exporter: Callable[
            ..., list[WbSalesReportListPageResult]
        ] = export_wb_sales_report_list,
        onec_exporter: Callable[..., list[OnecSampleExportResult]] = (
            export_onec_samples
        ),
        workbook_builder: Callable[[argparse.Namespace], Any] = (
            build_excel_mvp_from_args
        ),
        dashboard_payload_builder: Callable[[Path], dict[str, Any]] = (
            build_dashboard_payload
        ),
    ) -> None:
        self.settings = settings
        self._wb_finance_exporter = wb_finance_exporter
        self._wb_report_list_exporter = wb_report_list_exporter
        self._onec_exporter = onec_exporter
        self._workbook_builder = workbook_builder
        self._dashboard_payload_builder = dashboard_payload_builder

    def run(
        self,
        db: Session,
        *,
        tenant_id: str,
        mode: str,
        credential_source: str = "tenant",
        dry_run: bool = False,
        user: User | None = None,
        source_report: ReportRun | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        mode = mode.strip()
        credential_source = credential_source.strip()
        if mode not in SOURCE_REFRESH_MODES:
            raise SourceRefreshConfigError(f"unsupported source refresh mode: {mode}")
        if credential_source not in CREDENTIAL_SOURCES:
            raise SourceRefreshConfigError(
                f"unsupported credential source: {credential_source}"
            )
        if not self.settings.source_refresh_enabled and not dry_run:
            raise SourceRefreshDisabledError(
                "Source refresh выключен настройкой SHUMEYKO_SOURCE_REFRESH_ENABLED."
            )
        if db.get(Tenant, tenant_id) is None:
            raise SourceRefreshConfigError(f"tenant not found: {tenant_id}")
        if source_report is not None and source_report.tenant_id != tenant_id:
            raise PermissionError("source report tenant mismatch")

        period_start, period_end = self._period_for_mode(mode)
        snapshot_set_id = self._snapshot_set_id(mode)
        if not dry_run:
            conflict = repository.active_conflicting_source_refresh_run(
                db,
                tenant_id=tenant_id,
                mode=mode,
            )
            if conflict is not None:
                return self._create_blocked_run(
                    db,
                    tenant_id=tenant_id,
                    mode=mode,
                    credential_source=credential_source,
                    dry_run=dry_run,
                    snapshot_set_id=snapshot_set_id,
                    period_start=period_start,
                    period_end=period_end,
                    user=user,
                    source_report=source_report,
                    reason=reason,
                    status="blocked_active_refresh",
                    error_message=(
                        "Conflicting source refresh is active: "
                        f"{conflict.id} ({conflict.mode})."
                    ),
                )
        try:
            refresh_run = repository.create_source_refresh_run(
                db,
                tenant_id=tenant_id,
                mode=mode,
                credential_source=credential_source,
                dry_run=dry_run,
                snapshot_set_id=snapshot_set_id,
                period_start=period_start,
                period_end=period_end,
                user=user,
                source_report=source_report,
                reason=reason,
            )
        except ValueError as exc:
            raise SourceRefreshBusyError(str(exc)) from exc
        db.flush()

        root_dir = (self.settings.source_refresh_root_path / snapshot_set_id).resolve()
        try:
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="running",
                started_at=security.utcnow(),
                root_dir=str(root_dir),
            )
            if not dry_run:
                disk_issue = self._low_disk_issue()
                if disk_issue is not None:
                    return self._finish_without_report(
                        db,
                        refresh_run,
                        status="blocked_low_disk",
                        error_message=disk_issue["error_message"],
                    )
            credentials = self._credentials(
                db,
                tenant_id=tenant_id,
                credential_source=credential_source,
                mode=mode,
            )
            for issue in credentials.issues:
                repository.add_source_refresh_collection(
                    db,
                    refresh_run,
                    source_type=issue["source_type"],
                    source_label=issue["source_label"],
                    required=issue["required"],
                    status=issue["status"],
                    error_message=issue.get("error_message", ""),
                    payload=issue.get("payload", {}),
                )
            outputs = self._run_collectors(
                CollectorContext(
                    db=db,
                    refresh_run=refresh_run,
                    credentials=credentials,
                    root_dir=root_dir,
                    period_start=period_start,
                    period_end=period_end,
                    mode=mode,
                ),
                include_external=False,
            )
            mapping_collection = outputs.mapping_collection
            if credentials.issues:
                return self._finish_without_report(
                    db,
                    refresh_run,
                    status="needs_configuration",
                    error_message=(
                        "Source credentials are not ready for scheduled refresh."
                    ),
                )
            if dry_run:
                if self._mandatory_failed(refresh_run):
                    return self._finish_without_report(
                        db,
                        refresh_run,
                        status="failed",
                        error_message="Mandatory source refresh collection failed.",
                    )
                if self._needs_review(refresh_run, mapping_collection):
                    return self._finish_without_report(
                        db,
                        refresh_run,
                        status="needs_review",
                    )
                return self._finish_without_report(
                    db,
                    refresh_run,
                    status="dry_run_ready",
                )

            outputs = self._run_collectors(
                CollectorContext(
                    db=db,
                    refresh_run=refresh_run,
                    credentials=credentials,
                    root_dir=root_dir,
                    period_start=period_start,
                    period_end=period_end,
                    mode=mode,
                ),
                include_external=True,
            )
            wb_finance_dir = outputs.output_dirs.get("wb_finance_detail")
            wb_report_list_dir = outputs.output_dirs.get("wb_sales_report_list")
            onec_dir = outputs.output_dirs.get("onec_odata")

            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="source_loaded",
            )
            if self._mandatory_failed(refresh_run):
                return self._finish_without_report(
                    db,
                    refresh_run,
                    status="failed",
                    error_message="Mandatory source refresh collection failed.",
                )
            if mode == "daily":
                status = (
                    "needs_review"
                    if self._needs_review(refresh_run, mapping_collection)
                    else "source_loaded"
                )
                return self._finish_without_report(
                    db,
                    refresh_run,
                    status=status,
                )

            repository.update_source_refresh_run(db, refresh_run, status="rebuilding")
            if self.settings.db_first_reports_enabled:
                new_report, workbook_path = self._build_db_first_report(
                    db,
                    refresh_run,
                    source_report=source_report,
                    wb_finance_dir=wb_finance_dir,
                    onec_dir=onec_dir,
                    wb_report_list_dir=wb_report_list_dir,
                )
            else:
                workbook_path = self._build_workbook(
                    refresh_run,
                    wb_finance_dir=wb_finance_dir,
                    onec_dir=onec_dir,
                    wb_report_list_dir=wb_report_list_dir,
                )
                new_report = repository.import_dashboard_payload(
                    db,
                    self._dashboard_payload_builder(workbook_path),
                    tenant_id=tenant_id,
                    tenant_name=self._tenant_name(db, tenant_id),
                    report_id=self._new_report_id(source_report, refresh_run),
                    source_workbook_path=str(workbook_path),
                    lineage_type="legacy_excel_import",
                    publication_status="draft",
                    publish=False,
                )
            self._attach_source_loads(db, new_report, refresh_run)
            final_status = (
                "needs_review"
                if self._needs_review(refresh_run, mapping_collection)
                else "report_created"
            )
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status=final_status,
                new_report_run_id=new_report.id,
                workbook_path=str(workbook_path),
                finished_at=security.utcnow(),
            )
            repository.audit(
                db,
                action="source_refresh_report_created",
                user=user,
                tenant_id=tenant_id,
                entity_type="source_refresh_run",
                entity_id=refresh_run.id,
                payload={
                    "mode": mode,
                    "new_report_run_id": new_report.id,
                    "status": final_status,
                    "snapshotSetId": refresh_run.snapshot_set_id,
                },
            )
            payload = repository.source_refresh_run_payload(refresh_run)
            repository.publish_report(db, new_report)
            return payload
        except Exception as exc:
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="failed",
                error_message=_safe_error(exc),
                finished_at=security.utcnow(),
            )
            repository.audit(
                db,
                action="source_refresh_failed",
                user=user,
                tenant_id=tenant_id,
                entity_type="source_refresh_run",
                entity_id=refresh_run.id,
                payload={
                    "mode": mode,
                    "errorType": exc.__class__.__name__,
                },
            )
            return repository.source_refresh_run_payload(refresh_run)

    def _create_blocked_run(
        self,
        db: Session,
        *,
        tenant_id: str,
        mode: str,
        credential_source: str,
        dry_run: bool,
        snapshot_set_id: str,
        period_start: date,
        period_end: date,
        user: User | None,
        source_report: ReportRun | None,
        reason: str,
        status: str,
        error_message: str,
    ) -> dict[str, Any]:
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=tenant_id,
            mode=mode,
            credential_source=credential_source,
            dry_run=dry_run,
            snapshot_set_id=snapshot_set_id,
            period_start=period_start,
            period_end=period_end,
            user=user,
            source_report=source_report,
            reason=reason,
            enforce_active_check=False,
        )
        return self._finish_without_report(
            db,
            refresh_run,
            status=status,
            error_message=error_message,
        )

    def _run_collectors(
        self,
        context: CollectorContext,
        *,
        include_external: bool,
    ) -> CollectorOutputs:
        output_dirs: dict[str, Path] = {}
        mapping_collection: SourceRefreshCollection | None = None
        for collector in self._collector_plan(context.mode):
            if include_external == (collector.source_type == "sku_mapping"):
                continue
            result = collector.collect(self, context)
            if result.output_dir is not None:
                output_dirs[collector.source_type] = result.output_dir
            if collector.source_type == "sku_mapping":
                mapping_collection = result.collection
        if mapping_collection is None and not include_external:
            raise RuntimeError("mapping collector did not create a collection")
        return CollectorOutputs(
            output_dirs=output_dirs,
            mapping_collection=mapping_collection or context.refresh_run.collections[0],
        )

    def _collector_plan(self, mode: str) -> tuple[SourceCollector, ...]:
        collectors = (
            SourceCollector(
                source_type="sku_mapping",
                label="WB ↔ 1C mapping",
                required=True,
                modes=frozenset(SOURCE_REFRESH_MODES),
                roles=frozenset(),
                collect=_collect_mapping_source,
            ),
            SourceCollector(
                source_type="wb_finance_detail",
                label="WB Finance sales report details",
                required=True,
                modes=frozenset({"daily", "weekly", "full"}),
                roles=frozenset(WB_FINANCE_REFRESH_ROLES),
                collect=_collect_wb_finance,
            ),
            SourceCollector(
                source_type="wb_sales_report_list",
                label="WB Finance sales report list",
                required=False,
                modes=frozenset({"weekly", "full"}),
                roles=frozenset(WB_FINANCE_REFRESH_ROLES),
                collect=_collect_wb_report_list,
            ),
            SourceCollector(
                source_type="onec_odata",
                label="1С OData collections",
                required=True,
                modes=frozenset(SOURCE_REFRESH_MODES),
                roles=frozenset(
                    {"cost_documents", "stocks_warehouses", "full_readonly"}
                ),
                collect=_collect_onec_odata,
            ),
        )
        return tuple(item for item in collectors if item.supports(mode))

    def _low_disk_issue(self) -> dict[str, Any] | None:
        min_free_gb = max(0.0, float(self.settings.source_refresh_min_free_gb))
        if min_free_gb <= 0:
            return None
        probe_path = _existing_path_for_disk_check(
            self.settings.source_refresh_root_path
        )
        usage = shutil.disk_usage(probe_path)
        free_gb = usage.free / (1024**3)
        if free_gb >= min_free_gb:
            return None
        return {
            "error_message": (
                "source_refresh_low_disk: "
                f"free={free_gb:.2f}GiB required={min_free_gb:.2f}GiB"
            ),
            "free_gb": free_gb,
            "required_gb": min_free_gb,
        }

    def _credentials(
        self,
        db: Session,
        *,
        tenant_id: str,
        credential_source: str,
        mode: str,
    ) -> SourceCredentials:
        if credential_source == "env":
            return self._env_credentials(mode)
        return self._tenant_credentials(db, tenant_id=tenant_id, mode=mode)

    def _env_credentials(self, mode: str) -> SourceCredentials:
        issues: list[dict[str, Any]] = []
        wb_settings = None
        onec_settings = None
        if mode != "onec-only":
            try:
                wb_settings = WbFinanceSettings.from_env_file()
            except WbFinanceConfigError as exc:
                issues.append(_credential_issue("wb_api", True, str(exc)))
        try:
            onec_settings = OnecODataSettings.from_env_file()
        except OnecODataConfigError as exc:
            issues.append(_credential_issue("onec_readonly", True, str(exc)))
        return SourceCredentials(wb_settings, onec_settings, {}, tuple(issues))

    def _tenant_credentials(
        self,
        db: Session,
        *,
        tenant_id: str,
        mode: str,
    ) -> SourceCredentials:
        issues: list[dict[str, Any]] = []
        wb_settings = None
        wb_cabinet_ids: dict[str, str] = {}
        onec_settings = None
        if mode != "onec-only":
            wb_integrations = _tenant_integrations_by_base(db, tenant_id, "wb_api")
            if not wb_integrations:
                issues.append(_credential_issue("wb_api", True, "not_configured"))
            else:
                wb_settings, wb_cabinet_ids = self._wb_settings_from_integrations(
                    db,
                    wb_integrations,
                    issues,
                )
        integration = _tenant_integration(db, tenant_id, "onec_readonly")
        if integration is None:
            issues.append(_credential_issue("onec_readonly", True, "not_configured"))
        else:
            onec_settings = self._onec_settings_from_integration(integration, issues)
        return SourceCredentials(
            wb_settings,
            onec_settings,
            wb_cabinet_ids,
            tuple(issues),
        )

    def _wb_settings_from_integrations(
        self,
        db: Session,
        integrations_list: list[TenantIntegration],
        issues: list[dict[str, Any]],
    ) -> tuple[WbFinanceSettings | None, dict[str, str]]:
        accounts: list[WbFinanceSellerAccount] = []
        wb_cabinet_ids: dict[str, str] = {}
        skipped_roles: list[str] = []
        finance_index = 0
        for integration in integrations_list:
            if integration.status == "disabled":
                continue
            role = str(
                (integration.config_payload or {}).get("connectionRole") or ""
            ).strip()
            if role and role not in WB_FINANCE_REFRESH_ROLES:
                skipped_roles.append(integration.provider)
                continue
            finance_index += 1
            settings = self._wb_settings_from_integration(
                integration,
                issues,
                default_account_index=finance_index,
            )
            if settings is not None:
                accounts.extend(settings.accounts)
                cabinet = _ensure_wb_cabinet_for_integration(db, integration)
                if cabinet is not None:
                    for account in settings.accounts:
                        wb_cabinet_ids[account.seller_account_id] = cabinet.id
        if accounts:
            return WbFinanceSettings(accounts=tuple(accounts)), wb_cabinet_ids
        if not any(item["source_type"].startswith("wb_api") for item in issues):
            issues.append(
                _credential_issue(
                    "wb_api",
                    True,
                    "no_finance_report_integrations",
                    payload={"skippedProviders": skipped_roles},
                )
            )
        return None, wb_cabinet_ids

    def _wb_settings_from_integration(
        self,
        integration: TenantIntegration,
        issues: list[dict[str, Any]],
        *,
        default_account_index: int = 1,
    ) -> WbFinanceSettings | None:
        secret = self._encrypted_secret_or_issue(integration, issues)
        if not secret:
            return None
        try:
            return wb_finance_settings_from_secret(
                secret,
                default_name=_integration_account_name(integration),
                default_seller_account_id=f"WB_ACCOUNT_{default_account_index}",
            )
        except integrations.IntegrationSecretError as exc:
            issues.append(_credential_issue(integration.provider, True, str(exc)))
            return None

    def _onec_settings_from_integration(
        self,
        integration: TenantIntegration,
        issues: list[dict[str, Any]],
    ) -> OnecODataSettings | None:
        secret = self._encrypted_secret_or_issue(integration, issues)
        if not secret:
            return None
        try:
            return integrations.onec_odata_settings_from_secret(secret)
        except integrations.IntegrationSecretError as exc:
            issues.append(_credential_issue("onec_readonly", True, str(exc)))
            return None

    def _encrypted_secret_or_issue(
        self,
        integration: TenantIntegration,
        issues: list[dict[str, Any]],
    ) -> str:
        payload = integration.config_payload or {}
        if integration.status == "disabled":
            issues.append(
                _credential_issue(integration.provider, True, "integration_disabled")
            )
            return ""
        if payload.get("storage") != "encrypted":
            issues.append(
                _credential_issue(
                    integration.provider,
                    True,
                    "secret_storage_is_not_encrypted",
                    payload={"storageMode": payload.get("storage", "hash_only")},
                )
            )
            return ""
        try:
            return integrations.decrypt_secret(self.settings, payload)
        except integrations.IntegrationSecretError as exc:
            issues.append(_credential_issue(integration.provider, True, str(exc)))
            return ""

    def _record_mapping_source(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
    ) -> SourceRefreshCollection:
        mapping_dir = self.settings.source_refresh_mapping_path
        status, snapshot_hash, file_count, error_message, payload = (
            inspect_mapping_source(
                mapping_dir,
                stale_after_days=self._mapping_stale_days(),
            )
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="sku_mapping",
            source_label="WB ↔ 1C mapping",
            required=True,
            status=status,
            snapshot_hash=snapshot_hash,
            row_count=file_count,
            raw_path=str(mapping_dir),
            error_message=error_message,
            payload=payload,
        )
        if status in {"loaded", "stale"}:
            _persist_mapping_rows(db, collection, mapping_dir)
        return collection

    def _record_wb_finance(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[WbFinancePageResult],
        *,
        wb_cabinet_ids: dict[str, str],
    ) -> None:
        result_items = list(results)
        payload_items = [
            _wb_result_payload(
                item,
                wb_cabinet_id=wb_cabinet_ids.get(item.seller_account_id, ""),
            )
            for item in result_items
        ]
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB Finance sales report details",
            required=True,
            status=_aggregate_status(payload_items, required=True),
            snapshot_hash=_hash_payload(payload_items),
            row_count=sum(int(item.get("rowCount", 0)) for item in payload_items),
            raw_path=str(output_dir),
            payload={"results": payload_items},
        )
        _persist_wb_finance_rows(
            db,
            collection,
            result_items,
            wb_cabinet_ids=wb_cabinet_ids,
        )

    def _record_wb_report_list(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[WbSalesReportListPageResult],
        *,
        wb_cabinet_ids: dict[str, str],
    ) -> None:
        result_items = list(results)
        payload_items = [
            _wb_report_list_payload(
                item,
                wb_cabinet_id=wb_cabinet_ids.get(item.seller_account_id, ""),
            )
            for item in result_items
        ]
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_sales_report_list",
            source_label="WB Finance sales report list",
            required=False,
            status=_aggregate_status(payload_items, required=False),
            snapshot_hash=_hash_payload(payload_items),
            row_count=sum(int(item.get("rowCount", 0)) for item in payload_items),
            raw_path=str(output_dir),
            payload={"results": payload_items},
        )
        _persist_wb_report_list_rows(
            db,
            collection,
            result_items,
            wb_cabinet_ids=wb_cabinet_ids,
        )

    def _record_onec(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[OnecSampleExportResult],
    ) -> None:
        for item in results:
            required = item.sample_id in MANDATORY_ONEC_COLLECTION_IDS
            status = _onec_status(item, required=required)
            collection = repository.add_source_refresh_collection(
                db,
                refresh_run,
                source_type=f"onec_{item.sample_id}",
                source_label=item.collection_name,
                required=required,
                status=status,
                snapshot_hash=item.raw_payload_hash,
                row_count=item.row_count,
                raw_path=str(item.output_path or output_dir),
                error_message=item.error,
                payload={
                    "sampleId": item.sample_id,
                    "statusCode": item.status_code,
                    "pageCount": item.page_count,
                },
            )
            _persist_onec_rows(db, collection, item)

    def _finish_without_report(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        *,
        status: str,
        error_message: str = "",
    ) -> dict[str, Any]:
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status=status,
            error_message=error_message,
            finished_at=security.utcnow(),
        )
        return repository.source_refresh_run_payload(refresh_run)

    def _build_workbook(
        self,
        refresh_run: SourceRefreshRun,
        *,
        wb_finance_dir: Path | None,
        onec_dir: Path | None,
        wb_report_list_dir: Path | None,
    ) -> Path:
        output_dir = (
            self.settings.export_root_path / "source_refresh" / refresh_run.id
        ).resolve()
        allowed = self.settings.export_root_path.resolve()
        if output_dir != allowed and allowed not in output_dir.parents:
            raise ValueError("source-refresh workbook path is outside reports")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "shumeyko_wb_excel_mvp.xlsx"
        args = argparse.Namespace(
            client_id="shumeyko-partners",
            wb_finance_dir=wb_finance_dir,
            wb_finance_source="files",
            postgres_db_name="shumeyko_wb_unit_economics",
            postgres_host="",
            postgres_port=55433,
            postgres_user="",
            postgres_snapshot_id=None,
            mapping_source="files",
            mapping_snapshot_id=None,
            cost_source="files",
            cost_snapshot_id=None,
            wb_cards_dir=None,
            onec_dir=onec_dir,
            onec_marketplace_mapping_dir=self.settings.source_refresh_mapping_path,
            sales_register_dir=onec_dir,
            wb_report_list_dir=wb_report_list_dir,
            wb_paid_storage_dir=None,
            wb_promotion_stats_dir=None,
            wb_stock_history_dir=None,
            onec_services_dir=onec_dir,
            onec_stock_dir=onec_dir,
            onec_opiu_dir=onec_dir,
            onec_opiu_config=None,
            output=output_path,
            report_period_start=refresh_run.period_start,
            report_period_end=refresh_run.period_end,
            cost_amount_field="Сумма",
            sales_cost_amount_field="Себестоимость",
        )
        self._workbook_builder(args)
        if not output_path.exists():
            raise ValueError("source refresh workbook was not created")
        return output_path

    def _build_db_first_report(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        *,
        source_report: ReportRun | None,
        wb_finance_dir: Path | None,
        onec_dir: Path | None,
        wb_report_list_dir: Path | None,
    ) -> tuple[ReportRun, Path]:
        from scripts.export_report_artifacts import export_report_artifacts
        from scripts.rebuild_report_from_sources import (
            _validate_marts,
            build_db_first_payload,
        )

        output_dir = (
            self.settings.export_root_path / "source_refresh" / refresh_run.id
        ).resolve()
        allowed = self.settings.export_root_path.resolve()
        if output_dir != allowed and allowed not in output_dir.parents:
            raise ValueError("source-refresh artifact path is outside reports")
        output_dir.mkdir(parents=True, exist_ok=True)
        excel_path = output_dir / "shumeyko_wb_excel_mvp.xlsx"
        args = argparse.Namespace(
            client_id="shumeyko-partners",
            wb_finance_dir=wb_finance_dir,
            wb_finance_source="files",
            postgres_db_name="shumeyko_wb_unit_economics",
            postgres_host="",
            postgres_port=55433,
            postgres_user="",
            postgres_snapshot_id=None,
            mapping_source="files",
            mapping_snapshot_id=None,
            cost_source="files",
            cost_snapshot_id=None,
            wb_cards_dir=None,
            onec_dir=onec_dir,
            onec_marketplace_mapping_dir=self.settings.source_refresh_mapping_path,
            sales_register_dir=onec_dir,
            wb_report_list_dir=wb_report_list_dir,
            wb_paid_storage_dir=None,
            wb_promotion_stats_dir=None,
            wb_stock_history_dir=None,
            onec_stock_dir=onec_dir,
            onec_opiu_config=None,
            report_period_start=refresh_run.period_start,
            report_period_end=refresh_run.period_end,
            cost_amount_field="Сумма",
            sales_cost_amount_field="Себестоимость",
            tenant_name=self._tenant_name(db, refresh_run.tenant_id),
        )
        build = build_db_first_payload(args)
        report = repository.save_report_marts(
            db,
            build["payload"],
            tenant_id=refresh_run.tenant_id,
            tenant_name=self._tenant_name(db, refresh_run.tenant_id),
            report_id=self._new_report_id(source_report, refresh_run),
            publication_status="draft",
            publish=False,
            source_snapshot_set_id=refresh_run.snapshot_set_id,
        )
        _validate_marts(build["payload"])
        db.flush()
        records = export_report_artifacts(
            repository.report_full_payload(db, report),
            report_id=report.id,
            output_dir=output_dir,
            excel_path=excel_path,
            excel=True,
            docx=True,
            pdf=False,
            html=True,
            csv=True,
        )
        for artifact_type, record in records:
            repository.record_report_artifact(
                db,
                report,
                artifact_type=artifact_type,
                path=record["path"],
                sha256=record["hash"],
                byte_size=record["byte_size"],
                status=record["status"],
            )
        return report, excel_path

    def _attach_source_loads(
        self,
        db: Session,
        report: ReportRun,
        refresh_run: SourceRefreshRun,
    ) -> None:
        for item in refresh_run.collections:
            db.add(
                SourceLoad(
                    tenant_id=refresh_run.tenant_id,
                    client_id=report.client_id,
                    wb_cabinet_id=item.wb_cabinet_id,
                    report_run_id=report.id,
                    source_type=item.source_type,
                    source_label=item.source_label,
                    status=_source_load_status(item),
                    snapshot_hash=item.snapshot_hash,
                    row_count=item.row_count,
                    loaded_at=item.loaded_at,
                )
            )
        db.flush()

    def _mandatory_failed(self, refresh_run: SourceRefreshRun) -> bool:
        return any(
            item.required and item.status not in MANDATORY_OK_STATUSES | REVIEW_STATUSES
            for item in refresh_run.collections
        )

    def _needs_review(
        self,
        refresh_run: SourceRefreshRun,
        mapping_collection: SourceRefreshCollection,
    ) -> bool:
        return mapping_collection.status == "stale" or any(
            (not item.required and item.status not in OPTIONAL_OK_STATUSES)
            or (item.required and item.status in REVIEW_STATUSES)
            for item in refresh_run.collections
        )

    def _period_for_mode(self, mode: str) -> tuple[date, date]:
        configured_start = date.fromisoformat(self.settings.source_refresh_period_start)
        configured_end = self.settings.source_refresh_period_end.strip()
        if configured_end:
            period_end = date.fromisoformat(configured_end)
        else:
            period_end = datetime.now(tz=MOSCOW_TZ).date() - timedelta(days=1)
        if mode == "daily":
            rolling_start = period_end - timedelta(
                days=max(1, self.settings.source_refresh_rolling_window_days) - 1
            )
            return max(configured_start, rolling_start), period_end
        return configured_start, period_end

    def _snapshot_set_id(self, mode: str) -> str:
        stamp = datetime.now(tz=MOSCOW_TZ).strftime("%Y%m%d-%H%M%S")
        return f"{mode}-{stamp}"

    def _new_report_id(
        self,
        source_report: ReportRun | None,
        refresh_run: SourceRefreshRun,
    ) -> str:
        prefix = source_report.id if source_report else refresh_run.tenant_id
        stamp = security.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_source_refresh_{stamp}"

    def _tenant_name(self, db: Session, tenant_id: str) -> str:
        tenant = db.get(repository.Tenant, tenant_id)
        return tenant.name if tenant is not None else tenant_id

    def _onec_page_size(self) -> int:
        return max(1, min(int(self.settings.source_refresh_onec_page_size), 100000))

    def _onec_max_pages(self) -> int:
        return max(1, min(int(self.settings.source_refresh_onec_max_pages), 10000))

    def _wb_limit(self) -> int:
        return max(1, min(int(self.settings.source_refresh_wb_limit), 100000))

    def _wb_max_pages(self) -> int:
        return max(1, min(int(self.settings.source_refresh_wb_max_pages), 10000))

    def _wb_delay_seconds(self) -> float:
        return max(0.0, float(self.settings.source_refresh_wb_request_delay_seconds))

    def _mapping_stale_days(self) -> int:
        return max(1, int(self.settings.source_refresh_mapping_stale_days))


def _collect_mapping_source(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    collection = service._record_mapping_source(context.db, context.refresh_run)
    return CollectorResult(collection=collection)


def _collect_wb_finance(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.wb_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "wb_finance"
    results = service._wb_finance_exporter(
        context.credentials.wb_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        limit=service._wb_limit(),
        max_pages=service._wb_max_pages(),
        request_delay_seconds=service._wb_delay_seconds(),
        period="daily",
    )
    service._record_wb_finance(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        wb_cabinet_ids=context.credentials.wb_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_wb_report_list(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.wb_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "wb_sales_report_list"
    results = service._wb_report_list_exporter(
        context.credentials.wb_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        limit=1000,
        max_pages=10,
        request_delay_seconds=service._wb_delay_seconds(),
        period="weekly",
    )
    service._record_wb_report_list(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        wb_cabinet_ids=context.credentials.wb_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_onec_odata(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.onec_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "onec"
    results = service._onec_exporter(
        context.credentials.onec_settings,
        ONEC_REFRESH_COLLECTIONS,
        output_dir,
        top=service._onec_page_size(),
        max_pages=service._onec_max_pages(),
    )
    service._record_onec(context.db, context.refresh_run, output_dir, results)
    return CollectorResult(output_dir=output_dir)


def _existing_path_for_disk_check(path: Path) -> Path:
    current = path.resolve()
    while not current.exists() and current.parent != current:
        current = current.parent
    return current


def wb_finance_settings_from_secret(
    secret: str,
    *,
    default_name: str = "Wildberries API",
    default_seller_account_id: str = "WB_ACCOUNT",
) -> WbFinanceSettings:
    raw = secret.strip()
    if not raw:
        raise integrations.IntegrationSecretError("wb_secret_empty")
    accounts_payload: list[dict[str, Any]]
    if raw.startswith("{") or raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise integrations.IntegrationSecretError("wb_secret_json_invalid") from exc
        if isinstance(parsed, list):
            accounts_payload = [item for item in parsed if isinstance(item, dict)]
        elif isinstance(parsed, dict):
            nested = parsed.get("accounts")
            if isinstance(nested, list):
                accounts_payload = [item for item in nested if isinstance(item, dict)]
            else:
                accounts_payload = _accounts_from_wb_env_style_object(parsed)
                if not accounts_payload:
                    accounts_payload = [parsed]
        else:
            raise integrations.IntegrationSecretError("wb_secret_json_must_be_object")
    else:
        accounts_payload = [{"apiKey": raw, "accountName": default_name}]

    accounts: list[WbFinanceSellerAccount] = []
    fallback_id = _safe_wb_account_id(default_seller_account_id)
    for index, item in enumerate(accounts_payload, start=1):
        api_key = _first_text(
            item,
            "apiKey",
            "api_key",
            "token",
            "authorization",
            f"WB_ACCOUNT_{index}_API_KEY",
        )
        if not api_key:
            continue
        seller_account_id = (
            _first_text(
                item,
                "sellerAccountId",
                "seller_account_id",
                "id",
                f"WB_ACCOUNT_{index}_ID",
            )
            or (fallback_id if len(accounts_payload) == 1 else f"{fallback_id}_{index}")
        )
        account_name = (
            _first_text(
                item,
                "accountName",
                "account_name",
                "name",
                f"WB_ACCOUNT_{index}_NAME",
            )
            or seller_account_id
        )
        accounts.append(
            WbFinanceSellerAccount(
                seller_account_id=seller_account_id,
                account_name=account_name,
                api_key=api_key,
            )
        )
    if not accounts:
        raise integrations.IntegrationSecretError("wb_secret_missing_api_key")
    return WbFinanceSettings(accounts=tuple(accounts))


def inspect_mapping_source(
    mapping_dir: Path,
    *,
    stale_after_days: int,
) -> tuple[str, str, int, str, dict[str, Any]]:
    if not mapping_dir.exists():
        return (
            "failed",
            "",
            0,
            "mapping_source_missing",
            {"mappingDir": str(mapping_dir)},
        )
    files = sorted(path for path in mapping_dir.rglob("*") if path.is_file())
    if not files:
        return (
            "failed",
            "",
            0,
            "mapping_source_empty",
            {"mappingDir": str(mapping_dir)},
        )
    digest = hashlib.sha256()
    newest_mtime = 0.0
    for path in files:
        stat = path.stat()
        newest_mtime = max(newest_mtime, stat.st_mtime)
        digest.update(str(path.relative_to(mapping_dir)).encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    newest_at = datetime.fromtimestamp(newest_mtime, tz=MOSCOW_TZ)
    age_days = (datetime.now(tz=MOSCOW_TZ) - newest_at).days
    status = "stale" if age_days > stale_after_days else "loaded"
    return (
        status,
        digest.hexdigest(),
        len(files),
        "",
        {
            "mappingDir": str(mapping_dir),
            "fileCount": len(files),
            "newestMtime": newest_at.isoformat(),
            "ageDays": age_days,
            "staleAfterDays": stale_after_days,
        },
    )


def _tenant_integration(
    db: Session,
    tenant_id: str,
    provider: str,
) -> TenantIntegration | None:
    return db.scalar(
        select(TenantIntegration).where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == provider,
        )
    )


def _tenant_integrations_by_base(
    db: Session,
    tenant_id: str,
    provider_base: str,
) -> list[TenantIntegration]:
    return [
        item
        for item in db.scalars(
            select(TenantIntegration)
            .where(TenantIntegration.tenant_id == tenant_id)
            .order_by(TenantIntegration.provider)
        )
        if repository.integration_provider_base(item.provider) == provider_base
    ]


def _integration_account_name(integration: TenantIntegration) -> str:
    payload = integration.config_payload or {}
    return (
        str(payload.get("cabinetName") or "").strip()
        or str(payload.get("organizationName") or "").strip()
        or integration.label
        or integration.provider
    )


def _ensure_wb_cabinet_for_integration(
    db: Session,
    integration: TenantIntegration,
):
    payload = dict(integration.config_payload or {})
    tenant = db.get(Tenant, integration.tenant_id)
    client = repository.ensure_client_for_tenant(
        db,
        tenant_id=integration.tenant_id,
        name=tenant.name if tenant else integration.tenant_id,
    )
    company = repository.ensure_client_company(
        db,
        tenant_id=integration.tenant_id,
        client_id=client.id,
        display_name=str(payload.get("organizationName") or "").strip(),
    )
    company_id = company.id if company else str(payload.get("clientCompanyId") or "")
    cabinet = repository.ensure_wb_cabinet(
        db,
        tenant_id=integration.tenant_id,
        client_id=client.id,
        display_name=_integration_account_name(integration),
        cabinet_key=str(payload.get("connectionKey") or integration.provider),
        provider=integration.provider,
        client_company_id=company_id,
    )
    if cabinet is None:
        return None
    if payload.get("clientId") != client.id or payload.get("wbCabinetId") != cabinet.id:
        payload["clientId"] = client.id
        payload["clientCompanyId"] = company_id
        payload["wbCabinetId"] = cabinet.id
        integration.config_payload = payload
        integration.updated_at = security.utcnow()
        db.flush()
    return cabinet


def _safe_wb_account_id(value: str) -> str:
    normalized = "".join(
        char if char.isalnum() else "_" for char in value.strip().upper()
    ).strip("_")
    return normalized or "WB_ACCOUNT"


def _accounts_from_wb_env_style_object(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    for index in range(1, 11):
        api_key = _first_text(parsed, f"WB_ACCOUNT_{index}_API_KEY")
        if not api_key:
            continue
        accounts.append(
            {
                "apiKey": api_key,
                "sellerAccountId": f"WB_ACCOUNT_{index}",
                "accountName": _first_text(parsed, f"WB_ACCOUNT_{index}_NAME"),
            }
        )
    return accounts


def _first_text(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _credential_issue(
    provider: str,
    required: bool,
    message: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider_base = repository.integration_provider_base(provider)
    return {
        "source_type": provider,
        "source_label": (
            "Wildberries API" if provider_base == "wb_api" else "1С read-only"
        ),
        "required": required,
        "status": "needs_configuration",
        "error_message": message,
        "payload": payload or {},
    }


def _wb_result_payload(
    item: WbFinancePageResult,
    *,
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    return {
        "sellerAccountId": item.seller_account_id,
        "accountName": item.account_name,
        "wbCabinetId": wb_cabinet_id,
        "pageIndex": item.page_index,
        "status": _wb_status(item),
        "sourceStatus": item.status,
        "ok": item.ok,
        "rowCount": item.row_count,
        "statusCode": item.status_code,
        "rawPayloadHash": item.raw_payload_hash,
        "outputFile": item.output_path.name if item.output_path else None,
        "error": item.error,
    }


def _wb_report_list_payload(
    item: WbSalesReportListPageResult,
    *,
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    return {
        "sellerAccountId": item.seller_account_id,
        "accountName": item.account_name,
        "wbCabinetId": wb_cabinet_id,
        "pageIndex": item.page_index,
        "status": _wb_status(item),
        "sourceStatus": item.status,
        "ok": item.ok,
        "rowCount": item.row_count,
        "statusCode": item.status_code,
        "offset": item.offset,
        "rawPayloadHash": item.raw_payload_hash,
        "outputFile": item.output_path.name if item.output_path else None,
        "error": item.error,
    }


def _wb_status(item: WbFinancePageResult | WbSalesReportListPageResult) -> str:
    if item.ok and item.status == "ok" and item.row_count > 0:
        return "loaded"
    if item.ok and item.status == "ok" and item.row_count == 0:
        return "empty_unexpected"
    if item.ok and item.status == "no_data":
        return "empty_unexpected" if item.page_index == 1 else "empty_expected"
    if item.status in {"access_error"}:
        return "auth_failed"
    if item.status == "rate_limited":
        return "rate_limited"
    if item.status == "transport_or_schema_error":
        return "schema_error"
    return "failed" if not item.ok else "loaded"


def _aggregate_status(items: list[dict[str, Any]], *, required: bool) -> str:
    if not items:
        return "failed" if required else "needs_review"
    statuses = {str(item.get("status")) for item in items}
    if statuses <= MANDATORY_OK_STATUSES:
        return "loaded"
    if required and statuses - MANDATORY_OK_STATUSES:
        return sorted(statuses - MANDATORY_OK_STATUSES)[0]
    return "needs_review"


def _onec_status(item: OnecSampleExportResult, *, required: bool) -> str:
    if not item.ok:
        if not required and item.status_code == 404:
            return "empty_expected"
        if item.status_code in {401, 403}:
            return "auth_failed"
        if item.status_code == 429:
            return "rate_limited"
        return "failed"
    if item.row_count == 0:
        return "empty_unexpected" if required else "empty_expected"
    return "loaded"


def _source_load_status(item: SourceRefreshCollection) -> str:
    if item.required:
        return item.status
    if item.status in OPTIONAL_OK_STATUSES:
        return item.status
    return item.status if item.status == "loaded" else "needs_review"


def _persist_wb_finance_rows(
    db: Session,
    collection: SourceRefreshCollection,
    results: Iterable[WbFinancePageResult],
    *,
    wb_cabinet_ids: dict[str, str],
) -> None:
    try:
        row_number = 1
        for result in results:
            for local_index, row in enumerate(_read_json_list(result.output_path), 1):
                source_row_id = _first_row_id(row, "rrdId", "srid", "orderUid")
                if not source_row_id:
                    source_row_id = f"{result.page_index}:{local_index}"
                repository.add_source_snapshot_row(
                    db,
                    collection,
                    row_number=row_number,
                    raw_payload_hash=_hash_payload(row),
                    row_payload=row,
                    source_row_id=source_row_id,
                    wb_cabinet_id=wb_cabinet_ids.get(result.seller_account_id, ""),
                    loaded_at=collection.loaded_at,
                )
                row_number += 1
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _persist_wb_report_list_rows(
    db: Session,
    collection: SourceRefreshCollection,
    results: Iterable[WbSalesReportListPageResult],
    *,
    wb_cabinet_ids: dict[str, str],
) -> None:
    try:
        row_number = 1
        for result in results:
            for local_index, row in enumerate(_read_json_list(result.output_path), 1):
                source_row_id = _first_row_id(row, "reportId")
                if not source_row_id:
                    source_row_id = f"{result.page_index}:{local_index}"
                repository.add_source_snapshot_row(
                    db,
                    collection,
                    row_number=row_number,
                    raw_payload_hash=_hash_payload(row),
                    row_payload=row,
                    source_row_id=source_row_id,
                    wb_cabinet_id=wb_cabinet_ids.get(result.seller_account_id, ""),
                    loaded_at=collection.loaded_at,
                )
                row_number += 1
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _persist_onec_rows(
    db: Session,
    collection: SourceRefreshCollection,
    result: OnecSampleExportResult,
) -> None:
    if result.output_path is None:
        return
    try:
        rows = _extract_onec_rows(_read_json_object(result.output_path))
        for row_number, row in enumerate(rows, 1):
            source_row_id = _first_row_id(row, "Ref_Key", "LineNumber", "НомерСтроки")
            if not source_row_id:
                source_row_id = f"{result.sample_id}:{row_number}"
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=_hash_payload(row),
                row_payload=row,
                source_row_id=source_row_id,
                loaded_at=collection.loaded_at,
            )
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _persist_mapping_rows(
    db: Session,
    collection: SourceRefreshCollection,
    mapping_dir: Path,
) -> None:
    try:
        row_number = 1
        for path in sorted(item for item in mapping_dir.rglob("*") if item.is_file()):
            stat = path.stat()
            relative_path = str(path.relative_to(mapping_dir))
            row = {
                "path": relative_path,
                "name": path.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(
                    stat.st_mtime,
                    tz=MOSCOW_TZ,
                ).isoformat(),
                "sha256": _file_sha256(path),
            }
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=_hash_payload(row),
                row_payload=row,
                source_row_id=relative_path,
                loaded_at=collection.loaded_at,
            )
            row_number += 1
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _read_json_list(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("raw JSON payload is not a list")
    return [item for item in payload if isinstance(item, dict)]


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("raw JSON payload is not an object")
    return payload


def _extract_onec_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("value")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    data = payload.get("d")
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _first_row_id(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mark_raw_row_persistence_failure(
    db: Session,
    collection: SourceRefreshCollection,
    exc: Exception,
) -> None:
    collection.status = "failed" if collection.required else "needs_review"
    collection.error_message = f"raw_row_persistence_failed:{exc.__class__.__name__}"
    payload = dict(collection.payload or {})
    payload["rawRowPersistence"] = {
        "status": "failed",
        "errorType": exc.__class__.__name__,
    }
    collection.payload = payload
    db.flush()


def _hash_payload(payload: Any) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_error(exc: Exception) -> str:
    if isinstance(
        exc,
        (
            SourceRefreshConfigError,
            WbFinanceConfigError,
            OnecODataConfigError,
            integrations.IntegrationSecretError,
        ),
    ):
        return str(exc)
    message = _safe_error_message(str(exc))
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _safe_error_message(message: str) -> str:
    safe = message.strip().replace("\n", " ")
    if not safe:
        return ""
    safe = re.sub(
        r"(?i)(authorization|api[_-]?key|token|password|secret)=([^\s&]+)",
        r"\1=<redacted>",
        safe,
    )
    safe = re.sub(
        r"(?i)(bearer|basic)\s+[a-z0-9._~+/=-]+",
        r"\1 <redacted>",
        safe,
    )
    safe = re.sub(r"[A-Za-z0-9_-]{32,}", "<redacted>", safe)
    return safe[:500]
