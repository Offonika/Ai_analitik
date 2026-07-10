from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
from calendar import monthrange
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.build_excel_mvp_from_snapshots import build_excel_mvp_from_args
from wb_unit_economics.onec_odata import (
    DEFAULT_SAMPLE_COLLECTIONS,
    GROSS_PROFIT_SAMPLE_COLLECTIONS,
    SERVICE_SAMPLE_COLLECTIONS,
    OnecODataConfigError,
    OnecODataMetadataCheckResult,
    OnecODataSettings,
    OnecSampleExportResult,
    check_onec_odata_metadata,
    export_onec_samples,
)
from wb_unit_economics.ozon import (
    OzonConfigError,
    OzonPageResult,
    OzonSettings,
    export_ozon_b2b_sales_json,
    export_ozon_cash_flow,
    export_ozon_mutual_settlement,
    export_ozon_products_buyout,
    export_ozon_products_report,
    export_ozon_realization,
    export_ozon_realization_posting,
    export_ozon_returns_report,
    export_ozon_stock_on_warehouses,
    ozon_settings_from_secret,
)
from wb_unit_economics.wb_content import (
    WbContentSettings,
    WbProductCardsPageResult,
    export_wb_product_cards,
)
from wb_unit_economics.wb_content import (
    WbSellerAccount as WbContentSellerAccount,
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
from wb_unit_economics.wb_stocks import (
    WbStockExportResult,
    export_wb_stock_history_daily,
)
from wb_unit_economics.web import integrations, mapping_service, repository, security
from wb_unit_economics.web.dashboard_payload import build_dashboard_payload
from wb_unit_economics.web.models import (
    ReportRun,
    SourceRefreshCollection,
    SourceRefreshRun,
    Tenant,
    TenantIntegration,
    User,
    WbCabinet,
)
from wb_unit_economics.web.settings import WebSettings

SOURCE_REFRESH_MODES = {"daily", "weekly", "full", "onec-only", "ozon-only"}
SOURCE_REFRESH_RESUME_MODES = {"auto", "never"}
ONEC_RESUME_MODES = {"daily", "weekly", "full", "onec-only"}
WB_REQUIRED_MODES = {"daily", "weekly", "full"}
OZON_REQUIRED_MODES = {"ozon-only"}
OZON_OPTIONAL_MODES = {"daily", "weekly", "full"}
CREDENTIAL_SOURCES = {"tenant", "env"}
SOURCE_SNAPSHOT_ROW_CHUNK_SIZE = 1000
ONEC_DATABASE_ROW_PERSIST_MAX_BYTES = 25 * 1024 * 1024
READY_INTEGRATION_STATUSES = {"configured", "check_ok"}
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
PUBLICATION_REQUIRED_ONEC_COLLECTION_IDS = {"commissioner_reports"}
MANDATORY_OK_STATUSES = {"loaded", "empty_expected"}
OPTIONAL_OK_STATUSES = {"loaded", "empty_expected"}
REVIEW_STATUSES = {"needs_review", "stale", "partial_source"}
WB_FINANCE_REFRESH_ROLES = {"finance_reports", "full_readonly"}
WB_STOCK_HISTORY_REFRESH_ROLES = {
    "finance_reports",
    "stocks_analytics",
    "full_readonly",
}
OZON_REFRESH_ROLES = {
    "finance_reports",
    "products_catalog",
    "stocks_analytics",
    "returns_reports",
    "full_readonly",
}
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
WB_FINANCE_MAX_PAGES_ISSUE = "max_pages_reached_with_next_rrd_id"
WB_REPORT_LIST_MAX_PAGES_ISSUE = "max_pages_reached_with_full_report_list_page"
WB_PRODUCT_CARDS_MAX_PAGES_ISSUE = "max_pages_reached_with_full_cards_page"


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
    ozon_settings: OzonSettings | None
    wb_cabinet_ids: dict[str, str]
    ozon_cabinet_ids: dict[str, str]
    issues: tuple[dict[str, Any], ...]
    optional_issues: tuple[dict[str, Any], ...] = ()


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
        wb_product_cards_exporter: Callable[
            ..., list[WbProductCardsPageResult]
        ] = export_wb_product_cards,
        wb_stock_history_exporter: Callable[
            ..., list[WbStockExportResult]
        ] = export_wb_stock_history_daily,
        ozon_cash_flow_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_cash_flow
        ),
        ozon_realization_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_realization
        ),
        ozon_realization_posting_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_realization_posting
        ),
        ozon_products_buyout_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_products_buyout
        ),
        ozon_b2b_sales_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_b2b_sales_json
        ),
        ozon_mutual_settlement_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_mutual_settlement
        ),
        ozon_products_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_products_report
        ),
        ozon_stocks_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_stock_on_warehouses
        ),
        ozon_returns_exporter: Callable[..., list[OzonPageResult]] = (
            export_ozon_returns_report
        ),
        onec_exporter: Callable[..., list[OnecSampleExportResult]] = (
            export_onec_samples
        ),
        onec_metadata_checker: Callable[
            [OnecODataSettings], OnecODataMetadataCheckResult
        ]
        | None = None,
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
        self._wb_product_cards_exporter = wb_product_cards_exporter
        self._wb_stock_history_exporter = wb_stock_history_exporter
        self._ozon_cash_flow_exporter = ozon_cash_flow_exporter
        self._ozon_realization_exporter = ozon_realization_exporter
        self._ozon_realization_posting_exporter = ozon_realization_posting_exporter
        self._ozon_products_buyout_exporter = ozon_products_buyout_exporter
        self._ozon_b2b_sales_exporter = ozon_b2b_sales_exporter
        self._ozon_mutual_settlement_exporter = ozon_mutual_settlement_exporter
        self._ozon_products_exporter = ozon_products_exporter
        self._ozon_stocks_exporter = ozon_stocks_exporter
        self._ozon_returns_exporter = ozon_returns_exporter
        self._onec_exporter = onec_exporter
        self._onec_metadata_checker = onec_metadata_checker or check_onec_odata_metadata
        self._workbook_builder = workbook_builder
        self._dashboard_payload_builder = dashboard_payload_builder

    def run(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str | None = None,
        mode: str,
        credential_source: str = "tenant",
        dry_run: bool = False,
        user: User | None = None,
        source_report: ReportRun | None = None,
        reason: str = "",
        period_start: date | None = None,
        period_end: date | None = None,
        resume_mode: str = "auto",
        resume_from_run_id: str | None = None,
    ) -> dict[str, Any]:
        refresh_run = self._create_refresh_run(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            mode=mode,
            credential_source=credential_source,
            dry_run=dry_run,
            user=user,
            source_report=source_report,
            reason=reason,
            period_start=period_start,
            period_end=period_end,
            resume_mode=resume_mode,
            resume_from_run_id=resume_from_run_id,
        )
        if isinstance(refresh_run, dict):
            return refresh_run
        return self.run_existing(db, refresh_run.id)

    def enqueue(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str | None = None,
        mode: str,
        credential_source: str = "tenant",
        user: User | None = None,
        source_report: ReportRun | None = None,
        reason: str = "",
        period_start: date | None = None,
        period_end: date | None = None,
        resume_mode: str = "auto",
        resume_from_run_id: str | None = None,
    ) -> dict[str, Any]:
        refresh_run = self._create_refresh_run(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            mode=mode,
            credential_source=credential_source,
            dry_run=False,
            user=user,
            source_report=source_report,
            reason=reason,
            period_start=period_start,
            period_end=period_end,
            resume_mode=resume_mode,
            resume_from_run_id=resume_from_run_id,
        )
        if isinstance(refresh_run, dict):
            return refresh_run
        return repository.source_refresh_run_payload(refresh_run)

    def run_existing(
        self,
        db: Session,
        refresh_run_id: str,
    ) -> dict[str, Any]:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        if refresh_run is None:
            raise SourceRefreshConfigError(
                f"source refresh run not found: {refresh_run_id}"
            )
        if refresh_run.finished_at is not None:
            return repository.source_refresh_run_payload(refresh_run)
        user = (
            db.get(User, refresh_run.requested_by_user_id)
            if refresh_run.requested_by_user_id
            else None
        )
        return self._execute_run(db, refresh_run, user=user)

    def _create_refresh_run(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str | None,
        mode: str,
        credential_source: str,
        dry_run: bool,
        user: User | None,
        source_report: ReportRun | None,
        reason: str,
        period_start: date | None,
        period_end: date | None,
        resume_mode: str,
        resume_from_run_id: str | None,
    ) -> SourceRefreshRun | dict[str, Any]:
        mode = mode.strip()
        credential_source = credential_source.strip()
        resume_mode = resume_mode.strip().lower()
        if mode not in SOURCE_REFRESH_MODES:
            raise SourceRefreshConfigError(f"unsupported source refresh mode: {mode}")
        if credential_source not in CREDENTIAL_SOURCES:
            raise SourceRefreshConfigError(
                f"unsupported credential source: {credential_source}"
            )
        if resume_mode not in SOURCE_REFRESH_RESUME_MODES:
            raise SourceRefreshConfigError(
                f"unsupported source refresh resume mode: {resume_mode}"
            )
        if resume_mode == "never" and resume_from_run_id:
            raise SourceRefreshConfigError(
                "resume_from_run_id cannot be used with resume_mode=never"
            )
        if not self.settings.source_refresh_enabled and not dry_run:
            raise SourceRefreshDisabledError(
                "Source refresh выключен настройкой SHUMEYKO_SOURCE_REFRESH_ENABLED."
            )
        if db.get(Tenant, tenant_id) is None:
            raise SourceRefreshConfigError(f"tenant not found: {tenant_id}")
        if source_report is not None and source_report.tenant_id != tenant_id:
            raise PermissionError("source report tenant mismatch")

        default_period_start, default_period_end = self._period_for_mode(mode)
        period_start = period_start or default_period_start
        period_end = period_end or default_period_end
        if period_start > period_end:
            raise SourceRefreshConfigError(
                "source refresh period_start must not be after period_end"
            )
        snapshot_set_id = self._snapshot_set_id(mode)
        resolved_client_id = client_id or (
            source_report.client_id
            if source_report
            else repository.client_id_for_tenant(tenant_id)
        )
        resumed_from_run = self._resolve_resume_run(
            db,
            tenant_id=tenant_id,
            client_id=resolved_client_id,
            mode=mode,
            credential_source=credential_source,
            period_start=period_start,
            period_end=period_end,
            resume_mode=resume_mode,
            resume_from_run_id=resume_from_run_id,
            dry_run=dry_run,
        )
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
                    client_id=client_id,
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
                client_id=client_id,
                user=user,
                source_report=source_report,
                resumed_from_run=resumed_from_run,
                reason=reason,
            )
        except ValueError as exc:
            raise SourceRefreshBusyError(str(exc)) from exc
        db.flush()
        return refresh_run

    def _execute_run(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        *,
        user: User | None,
    ) -> dict[str, Any]:
        tenant_id = refresh_run.tenant_id
        mode = refresh_run.mode
        credential_source = refresh_run.credential_source
        dry_run = refresh_run.dry_run
        period_start = refresh_run.period_start
        period_end = refresh_run.period_end
        source_report = (
            db.get(ReportRun, refresh_run.source_report_run_id)
            if refresh_run.source_report_run_id
            else None
        )
        root_dir = (
            self.settings.source_refresh_root_path / refresh_run.snapshot_set_id
        ).resolve()
        try:
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="running",
                started_at=security.utcnow(),
                root_dir=str(root_dir),
            )
            _commit_source_refresh_progress(db)
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
            for issue in (*credentials.issues, *credentials.optional_issues):
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

            if credentials.onec_settings is not None:
                metadata_result = self._record_onec_metadata_check(
                    db,
                    refresh_run,
                    credentials.onec_settings,
                )
                _commit_source_refresh_progress(db)
                if not metadata_result.ok:
                    return self._finish_without_report(
                        db,
                        refresh_run,
                        status="failed",
                        error_message=(
                            "onec_odata_metadata_unavailable: "
                            f"{metadata_result.error or 'unknown_error'}"
                        ),
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
            self._rebuild_mapping_service(db, refresh_run, mapping_collection, user)
            repository.sync_organization_tax_profiles(
                db,
                refresh_run,
                user=user,
            )
            repository.validate_source_snapshot_duplicates(db, refresh_run)
            _commit_source_refresh_progress(db)
            wb_finance_dir = outputs.output_dirs.get("wb_finance_detail")
            wb_report_list_dir = outputs.output_dirs.get("wb_sales_report_list")
            wb_stock_history_dir = outputs.output_dirs.get("wb_stock_history_daily")
            onec_dir = outputs.output_dirs.get("onec_odata")

            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="source_loaded",
            )
            _commit_source_refresh_progress(db)
            if self._mandatory_failed(refresh_run):
                return self._finish_without_report(
                    db,
                    refresh_run,
                    status="failed",
                    error_message="Mandatory source refresh collection failed.",
                )
            if mode in {"daily", "onec-only", "ozon-only"}:
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
            _commit_source_refresh_progress(db)
            if self.settings.db_first_reports_enabled:
                new_report, workbook_path = self._build_db_first_report(
                    db,
                    refresh_run,
                    source_report=source_report,
                    wb_finance_dir=wb_finance_dir,
                    onec_dir=onec_dir,
                    wb_report_list_dir=wb_report_list_dir,
                    wb_stock_history_dir=wb_stock_history_dir,
                )
            else:
                workbook_path = self._build_workbook(
                    refresh_run,
                    wb_finance_dir=wb_finance_dir,
                    onec_dir=onec_dir,
                    wb_report_list_dir=wb_report_list_dir,
                    wb_stock_history_dir=wb_stock_history_dir,
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
            _commit_source_refresh_progress(db)
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
            publication_blockers = repository.report_publication_blockers(
                db, new_report
            )
            if publication_blockers:
                repository.update_source_refresh_run(
                    db,
                    refresh_run,
                    status="needs_review",
                    finished_at=security.utcnow(),
                )
                repository.audit(
                    db,
                    action="source_refresh_report_kept_draft",
                    user=user,
                    tenant_id=tenant_id,
                    entity_type="source_refresh_run",
                    entity_id=refresh_run.id,
                    payload={
                        "new_report_run_id": new_report.id,
                        "blockers": publication_blockers,
                    },
                )
                payload = repository.source_refresh_run_payload(refresh_run)
                _commit_source_refresh_progress(db)
                return payload
            repository.audit(
                db,
                action="source_refresh_report_kept_draft",
                user=user,
                tenant_id=tenant_id,
                entity_type="source_refresh_run",
                entity_id=refresh_run.id,
                payload={
                    "new_report_run_id": new_report.id,
                    "blockers": [],
                    "reason": "awaiting_staff_financial_acceptance",
                },
            )
            payload = repository.source_refresh_run_payload(refresh_run)
            _commit_source_refresh_progress(db)
            return payload
        except Exception as exc:
            safe_error = _safe_error(exc)
            with suppress(Exception):
                db.rollback()
            refresh_run = db.get(SourceRefreshRun, refresh_run.id) or refresh_run
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="failed",
                error_message=safe_error,
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
            _commit_source_refresh_progress(db)
            with suppress(Exception):
                self._prune_failed_snapshot_directories(db, refresh_run)
            return repository.source_refresh_run_payload(refresh_run)

    def _create_blocked_run(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str | None,
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
            client_id=client_id,
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
            _commit_source_refresh_progress(context.db)
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
                source_type="wb_product_cards",
                label="WB product cards",
                required=True,
                modes=frozenset({"daily", "weekly", "full"}),
                roles=frozenset(WB_FINANCE_REFRESH_ROLES),
                collect=_collect_wb_product_cards,
            ),
            SourceCollector(
                source_type="wb_stock_history_daily",
                label="WB daily stock history",
                required=False,
                modes=frozenset({"weekly", "full"}),
                roles=frozenset(WB_STOCK_HISTORY_REFRESH_ROLES),
                collect=_collect_wb_stock_history,
            ),
            SourceCollector(
                source_type="ozon_finance_cash_flow",
                label="Ozon financial cash-flow statement",
                required=False,
                modes=frozenset({"daily", "weekly", "full", "ozon-only"}),
                roles=frozenset({"finance_reports", "full_readonly"}),
                collect=_collect_ozon_cash_flow,
            ),
            SourceCollector(
                source_type="ozon_realization",
                label="Ozon realization report",
                required=False,
                modes=frozenset({"weekly", "full", "ozon-only"}),
                roles=frozenset({"finance_reports", "full_readonly"}),
                collect=_collect_ozon_realization,
            ),
            SourceCollector(
                source_type="ozon_mutual_settlement",
                label="Ozon mutual settlement report",
                required=False,
                modes=frozenset({"weekly", "full", "ozon-only"}),
                roles=frozenset({"finance_reports", "full_readonly"}),
                collect=_collect_ozon_mutual_settlement,
            ),
            SourceCollector(
                source_type="ozon_realization_posting",
                label="Ozon realization posting report",
                required=False,
                modes=frozenset({"weekly", "full", "ozon-only"}),
                roles=frozenset({"finance_reports", "full_readonly"}),
                collect=_collect_ozon_realization_posting,
            ),
            SourceCollector(
                source_type="ozon_products_buyout",
                label="Ozon products buyout report",
                required=False,
                modes=frozenset({"weekly", "full", "ozon-only"}),
                roles=frozenset({"finance_reports", "full_readonly"}),
                collect=_collect_ozon_products_buyout,
            ),
            SourceCollector(
                source_type="ozon_b2b_sales_json",
                label="Ozon B2B sales JSON",
                required=False,
                modes=frozenset({"weekly", "full", "ozon-only"}),
                roles=frozenset({"finance_reports", "full_readonly"}),
                collect=_collect_ozon_b2b_sales,
            ),
            SourceCollector(
                source_type="ozon_products_report",
                label="Ozon products report",
                required=False,
                modes=frozenset({"weekly", "full", "ozon-only"}),
                roles=frozenset({"products_catalog", "full_readonly"}),
                collect=_collect_ozon_products,
            ),
            SourceCollector(
                source_type="ozon_stock_on_warehouses",
                label="Ozon stock on warehouses",
                required=False,
                modes=frozenset({"weekly", "full"}),
                roles=frozenset({"stocks_analytics", "full_readonly"}),
                collect=_collect_ozon_stocks,
            ),
            SourceCollector(
                source_type="ozon_returns_report",
                label="Ozon returns report",
                required=False,
                modes=frozenset({"weekly", "full"}),
                roles=frozenset({"returns_reports", "full_readonly"}),
                collect=_collect_ozon_returns,
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
        optional_issues: list[dict[str, Any]] = []
        wb_settings = None
        ozon_settings = None
        onec_settings = None
        if mode in WB_REQUIRED_MODES:
            try:
                wb_settings = WbFinanceSettings.from_env_file()
            except WbFinanceConfigError as exc:
                issues.append(_credential_issue("wb_api", True, str(exc)))
        if mode in OZON_REQUIRED_MODES:
            try:
                ozon_settings = OzonSettings.from_env_file()
            except OzonConfigError as exc:
                issues.append(_credential_issue("ozon_api", True, str(exc)))
        elif mode in OZON_OPTIONAL_MODES and _env_has_ozon_credentials():
            try:
                ozon_settings = OzonSettings.from_env_file()
            except OzonConfigError as exc:
                optional_issues.append(_credential_issue("ozon_api", False, str(exc)))
        try:
            onec_settings = OnecODataSettings.from_env_file()
        except OnecODataConfigError as exc:
            issues.append(_credential_issue("onec_readonly", True, str(exc)))
        return SourceCredentials(
            wb_settings,
            onec_settings,
            ozon_settings,
            {},
            {},
            tuple(issues),
            tuple(optional_issues),
        )

    def _tenant_credentials(
        self,
        db: Session,
        *,
        tenant_id: str,
        mode: str,
    ) -> SourceCredentials:
        issues: list[dict[str, Any]] = []
        optional_issues: list[dict[str, Any]] = []
        wb_settings = None
        wb_cabinet_ids: dict[str, str] = {}
        ozon_settings = None
        ozon_cabinet_ids: dict[str, str] = {}
        onec_settings = None
        if mode in WB_REQUIRED_MODES:
            wb_integrations = _tenant_integrations_by_base(db, tenant_id, "wb_api")
            if not wb_integrations:
                issues.append(_credential_issue("wb_api", True, "not_configured"))
            else:
                wb_settings, wb_cabinet_ids = self._wb_settings_from_integrations(
                    db,
                    wb_integrations,
                    issues,
                )
        if mode in OZON_REQUIRED_MODES | OZON_OPTIONAL_MODES:
            ozon_integrations = _tenant_integrations_by_base(db, tenant_id, "ozon_api")
            ozon_required = mode in OZON_REQUIRED_MODES
            if not ozon_integrations and ozon_required:
                issues.append(_credential_issue("ozon_api", True, "not_configured"))
            elif ozon_integrations:
                ozon_settings, ozon_cabinet_ids = self._ozon_settings_from_integrations(
                    db,
                    ozon_integrations,
                    issues if ozon_required else optional_issues,
                    required=ozon_required,
                )
        integration = _tenant_integration(db, tenant_id, "onec_readonly")
        if integration is None:
            issues.append(_credential_issue("onec_readonly", True, "not_configured"))
        else:
            onec_settings = self._onec_settings_from_integration(integration, issues)
        return SourceCredentials(
            wb_settings,
            onec_settings,
            ozon_settings,
            wb_cabinet_ids,
            ozon_cabinet_ids,
            tuple(issues),
            tuple(optional_issues),
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

    def _ozon_settings_from_integrations(
        self,
        db: Session,
        integrations_list: list[TenantIntegration],
        issues: list[dict[str, Any]],
        *,
        required: bool = False,
    ) -> tuple[OzonSettings | None, dict[str, str]]:
        accounts = []
        ozon_cabinet_ids: dict[str, str] = {}
        skipped_roles: list[str] = []
        for integration in integrations_list:
            if integration.status == "disabled":
                continue
            role = str(
                (integration.config_payload or {}).get("connectionRole") or ""
            ).strip()
            if role and role not in OZON_REFRESH_ROLES:
                skipped_roles.append(integration.provider)
                continue
            settings = self._ozon_settings_from_integration(
                integration,
                issues,
                required=required,
            )
            if settings is not None:
                accounts.extend(settings.accounts)
                cabinet = _ensure_wb_cabinet_for_integration(db, integration)
                if cabinet is not None:
                    for account in settings.accounts:
                        ozon_cabinet_ids[account.seller_account_id] = cabinet.id
        if accounts:
            return OzonSettings(accounts=tuple(accounts)), ozon_cabinet_ids
        if skipped_roles:
            issues.append(
                _credential_issue(
                    "ozon_api",
                    required,
                    "no_matching_ozon_refresh_roles",
                    payload={"skippedProviders": skipped_roles},
                )
            )
        return None, ozon_cabinet_ids

    def _ozon_settings_from_integration(
        self,
        integration: TenantIntegration,
        issues: list[dict[str, Any]],
        *,
        required: bool = False,
    ) -> OzonSettings | None:
        secret = self._encrypted_secret_or_issue(integration, issues, required=required)
        if not secret:
            return None
        try:
            return ozon_settings_from_secret(
                secret,
                default_name=_integration_account_name(integration),
                default_seller_account_id=_safe_ozon_account_id(integration.provider),
            )
        except OzonConfigError as exc:
            issues.append(_credential_issue(integration.provider, required, str(exc)))
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
        *,
        required: bool = True,
    ) -> str:
        payload = integration.config_payload or {}
        if integration.status == "disabled":
            issues.append(
                _credential_issue(
                    integration.provider,
                    required,
                    "integration_disabled",
                )
            )
            return ""
        if integration.status not in READY_INTEGRATION_STATUSES:
            issues.append(
                _credential_issue(
                    integration.provider,
                    required,
                    "integration_not_runtime_ready",
                    payload={
                        "status": integration.status,
                        "lastCheckedAt": (
                            integration.last_checked_at.isoformat()
                            if integration.last_checked_at
                            else ""
                        ),
                    },
                )
            )
            return ""
        if payload.get("storage") != "encrypted":
            issues.append(
                _credential_issue(
                    integration.provider,
                    required,
                    "secret_storage_is_not_encrypted",
                    payload={"storageMode": payload.get("storage", "hash_only")},
                )
            )
            return ""
        try:
            return integrations.decrypt_secret(self.settings, payload)
        except integrations.IntegrationSecretError as exc:
            issues.append(_credential_issue(integration.provider, required, str(exc)))
            return ""

    def _record_mapping_source(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
    ) -> SourceRefreshCollection:
        mapping_dir = self.settings.source_refresh_mapping_path
        status, snapshot_hash, item_count, error_message, payload = (
            mapping_service.inspect_mapping_service(
                db,
                tenant_id=refresh_run.tenant_id,
                client_id=refresh_run.client_id,
                stale_after_days=self._mapping_stale_days(),
            )
        )
        file_status, file_hash, file_count, file_error, file_payload = (
            inspect_mapping_source(
                mapping_dir,
                stale_after_days=self._mapping_stale_days(),
            )
        )
        payload = {
            **payload,
            "legacyFileSource": {
                "status": file_status,
                "snapshotHash": file_hash,
                "fileCount": file_count,
                "errorMessage": file_error,
                **file_payload,
            },
        }
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="sku_mapping",
            source_label="Marketplace ↔ 1C mapping service",
            required=True,
            status=status,
            snapshot_hash=snapshot_hash,
            row_count=item_count,
            raw_path="mapping_service",
            error_message=error_message,
            payload=payload,
        )
        if file_status in {"loaded", "stale"}:
            _persist_mapping_rows(db, collection, mapping_dir)
        return collection

    def _rebuild_mapping_service(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        mapping_collection: SourceRefreshCollection,
        user: User | None,
    ) -> None:
        result = mapping_service.rebuild_candidates(
            db,
            tenant_id=refresh_run.tenant_id,
            client_id=refresh_run.client_id,
            user=user,
            refresh_run_id=refresh_run.id,
        )
        import_result = mapping_service.import_mapping_directory(
            db,
            tenant_id=refresh_run.tenant_id,
            client_id=refresh_run.client_id,
            mapping_dir=self.settings.source_refresh_mapping_path,
            user=user,
        )
        status, snapshot_hash, item_count, error_message, payload = (
            mapping_service.inspect_mapping_service(
                db,
                tenant_id=refresh_run.tenant_id,
                client_id=refresh_run.client_id,
                stale_after_days=self._mapping_stale_days(),
            )
        )
        legacy_file_source = (mapping_collection.payload or {}).get(
            "legacyFileSource",
            {},
        )
        mapping_collection.status = status
        mapping_collection.snapshot_hash = snapshot_hash
        mapping_collection.row_count = item_count
        mapping_collection.error_message = error_message
        mapping_collection.payload = {
            **payload,
            "rebuild": result,
            "mappingFileImport": import_result,
            "legacyFileSource": legacy_file_source,
        }
        mapping_collection.loaded_at = security.utcnow()
        db.flush()

    def _record_wb_finance(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[WbFinancePageResult],
        *,
        wb_cabinet_ids: dict[str, str],
        source_coverage_start: date,
        source_coverage_end: date,
    ) -> None:
        result_items = list(results)
        payload_items = [
            _wb_result_payload(
                item,
                wb_cabinet_id=wb_cabinet_ids.get(item.seller_account_id, ""),
            )
            for item in result_items
        ]
        max_pages = self._wb_max_pages()
        max_pages_exhausted = _mark_wb_finance_max_pages_issue(
            result_items,
            payload_items,
            max_pages=max_pages,
        )
        row_count = sum(int(item.get("rowCount", 0)) for item in payload_items)
        persist_row_limit = max(
            0,
            int(self.settings.source_refresh_wb_persist_row_limit),
        )
        skip_row_persistence = row_count > persist_row_limit
        payload: dict[str, Any] = {
            "results": payload_items,
            "sourceCoverageStart": source_coverage_start.isoformat(),
            "sourceCoverageEnd": source_coverage_end.isoformat(),
        }
        if skip_row_persistence:
            payload["rowPersistence"] = {
                "status": "skipped_large_snapshot",
                "limit": persist_row_limit,
                "rawFilesAuthoritative": True,
            }
        error_message = ""
        if max_pages_exhausted:
            error_message = (
                "WB finance reached max_pages with a next rrd_id; "
                "source snapshot is incomplete and cannot be published safely."
            )
            payload.update(
                {
                    "completenessIssue": WB_FINANCE_MAX_PAGES_ISSUE,
                    "maxPages": max_pages,
                    "safeMessage": error_message,
                }
            )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB Finance sales report details",
            required=True,
            status=_aggregate_status(payload_items, required=True),
            snapshot_hash=_hash_payload(payload_items),
            row_count=row_count,
            raw_path=str(output_dir),
            error_message=error_message,
            payload=payload,
        )
        if max_pages_exhausted or skip_row_persistence:
            return
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
        max_pages_exhausted = _page_limit_exhausted(
            result_items,
            max_pages=10,
            page_limit=1000,
            row_count_attribute="row_count",
        )
        payload: dict[str, Any] = {"results": payload_items}
        if max_pages_exhausted:
            payload["completenessIssue"] = WB_REPORT_LIST_MAX_PAGES_ISSUE
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_sales_report_list",
            source_label="WB Finance sales report list",
            required=False,
            status=(
                "partial_source"
                if max_pages_exhausted
                else _aggregate_status(payload_items, required=False)
            ),
            snapshot_hash=_hash_payload(payload_items),
            row_count=sum(int(item.get("rowCount", 0)) for item in payload_items),
            raw_path=str(output_dir),
            error_message=(
                "WB report list reached max_pages on a full page; "
                "source may be incomplete."
                if max_pages_exhausted
                else ""
            ),
            payload=payload,
        )
        _persist_wb_report_list_rows(
            db,
            collection,
            result_items,
            wb_cabinet_ids=wb_cabinet_ids,
        )

    def _record_wb_product_cards(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[WbProductCardsPageResult],
        *,
        wb_cabinet_ids: dict[str, str],
    ) -> None:
        result_items = list(results)
        payload_items = [
            _wb_product_cards_payload(
                item,
                wb_cabinet_id=wb_cabinet_ids.get(item.seller_account_id, ""),
            )
            for item in result_items
        ]
        max_pages_exhausted = _page_limit_exhausted(
            result_items,
            max_pages=self._wb_max_pages(),
            page_limit=min(self._wb_limit(), 100),
            row_count_attribute="card_count",
            group_attributes=("seller_account_id", "cards_source"),
        )
        payload: dict[str, Any] = {"results": payload_items}
        if max_pages_exhausted:
            payload["completenessIssue"] = WB_PRODUCT_CARDS_MAX_PAGES_ISSUE
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_product_cards",
            source_label="WB product cards",
            required=True,
            status=(
                "partial_source"
                if max_pages_exhausted
                else _aggregate_status(payload_items, required=True)
            ),
            snapshot_hash=_hash_payload(payload_items),
            row_count=sum(int(item.get("rowCount", 0)) for item in payload_items),
            raw_path=str(output_dir),
            error_message=(
                "WB product cards reached max_pages on a full page; "
                "source may be incomplete."
                if max_pages_exhausted
                else ""
            ),
            payload=payload,
        )
        _persist_wb_product_card_rows(
            db,
            collection,
            result_items,
            wb_cabinet_ids=wb_cabinet_ids,
        )

    def _record_wb_stock_history(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[WbStockExportResult],
        *,
        wb_cabinet_ids: dict[str, str],
        period_start: date,
        period_end: date,
        actual_period_start: date | None = None,
        actual_period_end: date | None = None,
    ) -> SourceRefreshCollection:
        actual_period_start = actual_period_start or period_start
        actual_period_end = actual_period_end or period_end
        total_days = (period_end - period_start).days + 1
        accounts: list[dict[str, Any]] = []
        for item in results:
            source_status = (
                "missing_scope" if item.status == "access_error" else item.status
            )
            covered_days = (
                _stock_history_zip_covered_days(
                    item.output_path,
                    period_start=period_start,
                    period_end=period_end,
                )
                if item.ok and item.output_path is not None
                else 0
            )
            calculated = bool(item.ok and covered_days == total_days)
            status = "complete" if calculated else source_status
            if item.ok and not calculated:
                status = (
                    "partial_provider_window"
                    if actual_period_start > period_start
                    else "incomplete"
                )
            accounts.append(
                {
                    "sellerAccountId": item.seller_account_id,
                    "wbCabinetId": wb_cabinet_ids.get(item.seller_account_id, ""),
                    "cabinet": item.account_name,
                    "status": status,
                    "coveredDays": covered_days,
                    "totalDays": total_days,
                    "calculated": calculated,
                    "statusCode": item.status_code,
                    "error": item.error,
                }
            )
        all_complete = bool(accounts) and all(
            bool(item["calculated"]) for item in accounts
        )
        collection_status = "loaded" if all_complete else "needs_review"
        error_message = ""
        if not all_complete:
            error_message = (
                "WB stock history is incomplete or Seller Analytics scope is missing; "
                "lost contribution margin is not calculated."
            )
        return repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_stock_history_daily",
            source_label="WB daily stock history",
            required=False,
            status=collection_status,
            snapshot_hash=_hash_payload(accounts),
            row_count=len(accounts),
            raw_path=str(output_dir),
            error_message=error_message,
            payload={
                "periodStart": period_start.isoformat(),
                "periodEnd": period_end.isoformat(),
                "actualPeriodStart": actual_period_start.isoformat(),
                "actualPeriodEnd": actual_period_end.isoformat(),
                "stockType": "wb",
                "calculated": all_complete,
                "accounts": accounts,
            },
        )

    def _record_ozon_results(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        output_dir: Path,
        results: Iterable[OzonPageResult],
        *,
        source_type: str,
        source_label: str,
        ozon_cabinet_ids: dict[str, str],
        required: bool = False,
    ) -> None:
        result_items = list(results)
        payload_items = [
            _ozon_result_payload(
                item,
                ozon_cabinet_id=ozon_cabinet_ids.get(item.seller_account_id, ""),
            )
            for item in result_items
        ]
        row_count = _ozon_collection_row_count(result_items)
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type=source_type,
            source_label=source_label,
            required=required,
            status=_ozon_collection_status(
                result_items,
                payload_items,
                row_count=row_count,
                required=required,
            ),
            snapshot_hash=_hash_payload(payload_items),
            row_count=row_count,
            raw_path=str(output_dir),
            payload={
                "marketplace": "ozon",
                "results": payload_items,
            },
        )
        _persist_ozon_rows(
            db,
            collection,
            result_items,
            ozon_cabinet_ids=ozon_cabinet_ids,
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
            publication_required = (
                item.sample_id in PUBLICATION_REQUIRED_ONEC_COLLECTION_IDS
            )
            status = _onec_status(item, required=required)
            collection = repository.add_source_refresh_collection(
                db,
                refresh_run,
                source_type=f"onec_{item.sample_id}",
                source_label=item.collection_name,
                required=required,
                publication_required=publication_required,
                status=status,
                snapshot_hash=item.raw_payload_hash,
                row_count=item.row_count,
                raw_path=str(item.output_path or item.checkpoint_path or output_dir),
                error_message=item.error,
                payload={
                    "sampleId": item.sample_id,
                    "statusCode": item.status_code,
                    "pageCount": item.page_count,
                    "checkpointPath": str(item.checkpoint_path or ""),
                    "retryable": item.retryable,
                    "nextCursor": item.next_cursor,
                    "reusedPageCount": item.reused_page_count,
                    "effectivePageSize": item.effective_page_size,
                    "detailMode": item.detail_mode,
                    "publicationRequired": publication_required,
                },
            )
            _persist_onec_rows(db, collection, item)

    def _record_onec_metadata_check(
        self,
        db: Session,
        refresh_run: SourceRefreshRun,
        onec_settings: OnecODataSettings,
    ) -> OnecODataMetadataCheckResult:
        result = self._onec_metadata_checker(onec_settings)
        checked_at = security.utcnow().isoformat()
        status = "loaded" if result.ok else "failed"
        message = (
            "1С OData metadata доступна в read-only режиме."
            if result.ok
            else "1С OData metadata недоступна для автоматического обновления."
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_odata_metadata",
            source_label="1С OData metadata",
            required=True,
            status=status,
            error_message=result.error,
            payload={
                "endpointCategory": "odata_metadata",
                "statusCode": result.status_code,
                "metadataValid": result.ok,
                "checkedAt": checked_at,
            },
        )
        if refresh_run.credential_source == "tenant":
            repository.record_tenant_integration_runtime_check(
                db,
                tenant_id=refresh_run.tenant_id,
                provider="onec_readonly",
                status="check_ok" if result.ok else "check_failed",
                message=message,
                check_payload={
                    "checkMode": "source_refresh_preflight",
                    "endpointCategory": "odata_metadata",
                    "httpStatus": result.status_code,
                    "metadataValid": result.ok,
                    "errorType": result.error,
                },
            )
        return result

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
        if status == "failed":
            with suppress(Exception):
                self._prune_failed_snapshot_directories(db, refresh_run)
        return repository.source_refresh_run_payload(refresh_run)

    def _prune_failed_snapshot_directories(
        self,
        db: Session,
        current_run: SourceRefreshRun,
    ) -> list[Path]:
        keep = max(2, int(self.settings.source_refresh_failed_snapshot_keep))
        failed_runs = list(
            db.scalars(
                select(SourceRefreshRun)
                .where(
                    SourceRefreshRun.tenant_id == current_run.tenant_id,
                    SourceRefreshRun.status == "failed",
                    SourceRefreshRun.finished_at.is_not(None),
                )
                .order_by(
                    SourceRefreshRun.created_at.desc(),
                    SourceRefreshRun.id.desc(),
                )
            )
        )
        protected_snapshot_ids = {
            str(value)
            for value in db.scalars(
                select(ReportRun.source_snapshot_set_id).where(
                    ReportRun.tenant_id == current_run.tenant_id,
                    ReportRun.publication_status == "published",
                    ReportRun.source_snapshot_set_id != "",
                )
            )
            if value
        }
        source_root = self.settings.source_refresh_root_path.resolve()
        removed: list[Path] = []
        for failed_run in failed_runs[keep:]:
            snapshot_set_id = failed_run.snapshot_set_id
            if (
                failed_run.new_report_run_id
                or snapshot_set_id in protected_snapshot_ids
                or not snapshot_set_id
                or Path(snapshot_set_id).name != snapshot_set_id
            ):
                continue
            candidate = source_root / snapshot_set_id
            if candidate.parent != source_root or candidate.is_symlink():
                continue
            if candidate.is_dir():
                shutil.rmtree(candidate)
                removed.append(candidate)
        return removed

    def _build_workbook(
        self,
        refresh_run: SourceRefreshRun,
        *,
        wb_finance_dir: Path | None,
        onec_dir: Path | None,
        wb_report_list_dir: Path | None,
        wb_stock_history_dir: Path | None,
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
            client_id=(
                refresh_run.client_id
                or repository.client_id_for_tenant(refresh_run.tenant_id)
            ),
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
            onec_services_dir=onec_dir,
            wb_report_list_dir=wb_report_list_dir,
            wb_paid_storage_dir=None,
            wb_promotion_stats_dir=None,
            wb_stock_history_dir=wb_stock_history_dir,
            onec_stock_dir=onec_dir,
            onec_opiu_dir=onec_dir,
            onec_opiu_config=None,
            output=output_path,
            report_period_start=refresh_run.period_start,
            report_period_end=refresh_run.period_end,
            cost_amount_field="Сумма",
            sales_cost_amount_field="СебестоимостьБезНДС",
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
        wb_stock_history_dir: Path | None,
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
        client_name = self._client_name(db, refresh_run.tenant_id)
        args = argparse.Namespace(
            client_id=(
                refresh_run.client_id
                or (
                    source_report.client_id
                    if source_report
                    else repository.client_id_for_tenant(refresh_run.tenant_id)
                )
            ),
            wb_finance_dir=wb_finance_dir,
            wb_finance_source="files-stream",
            stream_cache_dir=Path("data/.cache/source_refresh_stream") / refresh_run.id,
            keep_stream_cache=False,
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
            onec_services_dir=onec_dir,
            wb_report_list_dir=wb_report_list_dir,
            wb_paid_storage_dir=None,
            wb_promotion_stats_dir=None,
            wb_stock_history_dir=wb_stock_history_dir,
            onec_stock_dir=onec_dir,
            onec_opiu_config=None,
            report_period_start=refresh_run.period_start,
            report_period_end=refresh_run.period_end,
            cost_amount_field="Сумма",
            sales_cost_amount_field="auto",
            source_refresh_run_id=refresh_run.id,
            tenant_name=client_name,
        )
        build = build_db_first_payload(
            args,
            tax_profiles=repository.tax_profiles_for_source_refresh(
                db,
                refresh_run,
            ),
        )
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
        repository.replace_source_loads_from_refresh(db, report, refresh_run)
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
        repository.replace_source_loads_from_refresh(db, report, refresh_run)

    def _mandatory_failed(self, refresh_run: SourceRefreshRun) -> bool:
        return any(
            item.required
            and (
                item.status not in MANDATORY_OK_STATUSES | REVIEW_STATUSES
                or (
                    (
                        item.source_type == "wb_finance_detail"
                        or item.source_type.startswith("onec_")
                    )
                    and item.status == "partial_source"
                )
            )
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

    def _resolve_resume_run(
        self,
        db: Session,
        *,
        tenant_id: str,
        client_id: str,
        mode: str,
        credential_source: str,
        period_start: date,
        period_end: date,
        resume_mode: str,
        resume_from_run_id: str | None,
        dry_run: bool,
    ) -> SourceRefreshRun | None:
        if dry_run or resume_mode == "never":
            return None
        if mode not in ONEC_RESUME_MODES:
            if resume_from_run_id:
                raise SourceRefreshConfigError(
                    "explicit resume is available only for modes with 1C OData"
                )
            return None

        candidate: SourceRefreshRun | None
        if resume_from_run_id:
            candidate = db.get(SourceRefreshRun, resume_from_run_id)
            if candidate is None:
                raise SourceRefreshConfigError(
                    f"resume source refresh not found: {resume_from_run_id}"
                )
        else:
            candidates = list(
                db.scalars(
                select(SourceRefreshRun)
                .where(
                    SourceRefreshRun.tenant_id == tenant_id,
                    SourceRefreshRun.client_id == client_id,
                    SourceRefreshRun.credential_source == credential_source,
                    SourceRefreshRun.period_start == period_start,
                    SourceRefreshRun.period_end == period_end,
                    SourceRefreshRun.mode.in_(ONEC_RESUME_MODES),
                    SourceRefreshRun.finished_at.is_not(None),
                    SourceRefreshRun.status.in_({"failed", "needs_review"}),
                )
                .order_by(SourceRefreshRun.created_at.desc())
                .limit(20)
                )
            )
            candidate = next(
                (
                    item
                    for item in candidates
                    if self._run_has_onec_checkpoint(item)
                ),
                None,
            )
            if candidate is None:
                return None

        compatible = (
            candidate.tenant_id == tenant_id
            and candidate.client_id == client_id
            and candidate.credential_source == credential_source
            and candidate.period_start == period_start
            and candidate.period_end == period_end
            and candidate.mode in ONEC_RESUME_MODES
            and candidate.finished_at is not None
        )
        root_dir = Path(candidate.root_dir).resolve() if candidate.root_dir else None
        allowed_root = self.settings.source_refresh_root_path.resolve()
        has_safe_onec_dir = bool(
            root_dir
            and root_dir.is_relative_to(allowed_root)
            and (root_dir / "onec").is_dir()
        )
        if not compatible or not has_safe_onec_dir:
            if resume_from_run_id:
                raise SourceRefreshConfigError(
                    "resume source refresh is incompatible or has no safe 1C snapshot"
                )
            return None
        return candidate

    def _run_has_onec_checkpoint(self, refresh_run: SourceRefreshRun) -> bool:
        if not refresh_run.root_dir:
            return False
        root_dir = Path(refresh_run.root_dir).resolve()
        allowed_root = self.settings.source_refresh_root_path.resolve()
        onec_dir = root_dir / "onec"
        if not root_dir.is_relative_to(allowed_root) or not onec_dir.is_dir():
            return False
        return any(path.is_file() for path in onec_dir.glob("*/manifest.json"))

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

    def _client_name(self, db: Session, tenant_id: str) -> str:
        client = db.scalar(
            select(repository.Client).where(repository.Client.tenant_id == tenant_id)
        )
        if client is not None and client.name:
            return client.name
        return self._tenant_name(db, tenant_id)

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

    def _wb_content_delay_seconds(self) -> float:
        return max(
            0.0,
            float(self.settings.source_refresh_wb_content_request_delay_seconds),
        )

    def _ozon_page_size(self) -> int:
        return max(1, min(int(self.settings.source_refresh_ozon_page_size), 1000))

    def _ozon_max_pages(self) -> int:
        return max(1, min(int(self.settings.source_refresh_ozon_max_pages), 10000))

    def _ozon_delay_seconds(self) -> float:
        return max(0.0, float(self.settings.source_refresh_ozon_request_delay_seconds))

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
    source_coverage_start = context.period_start - timedelta(
        days=context.period_start.weekday()
    )
    results = service._wb_finance_exporter(
        context.credentials.wb_settings,
        output_dir,
        period_start=source_coverage_start,
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
        source_coverage_start=source_coverage_start,
        source_coverage_end=context.period_end,
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


def _collect_wb_product_cards(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.wb_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "wb_product_cards"
    content_settings = WbContentSettings(
        accounts=tuple(
            WbContentSellerAccount(
                seller_account_id=item.seller_account_id,
                account_name=item.account_name,
                api_key=item.api_key,
            )
            for item in context.credentials.wb_settings.accounts
        ),
        timeout_seconds=30.0,
    )
    results = service._wb_product_cards_exporter(
        content_settings,
        output_dir,
        limit=min(service._wb_limit(), 100),
        max_pages=service._wb_max_pages(),
        request_delay_seconds=service._wb_content_delay_seconds(),
    )
    service._record_wb_product_cards(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        wb_cabinet_ids=context.credentials.wb_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_wb_stock_history(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.wb_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "wb_stock_history_daily"
    provider_period_start = max(
        context.period_start,
        _subtract_calendar_months(context.period_end, 3),
    )
    results = service._wb_stock_history_exporter(
        context.credentials.wb_settings,
        output_dir,
        period_start=provider_period_start,
        period_end=context.period_end,
        stock_type="wb",
    )
    collection = service._record_wb_stock_history(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        wb_cabinet_ids=context.credentials.wb_cabinet_ids,
        period_start=context.period_start,
        period_end=context.period_end,
        actual_period_start=provider_period_start,
        actual_period_end=context.period_end,
    )
    return CollectorResult(collection=collection, output_dir=output_dir)


def _collect_ozon_cash_flow(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_finance_cash_flow"
    results = service._ozon_cash_flow_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        page_size=service._ozon_page_size(),
        max_pages=service._ozon_max_pages(),
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_finance_cash_flow",
        source_label="Ozon financial cash-flow statement",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
        required=context.mode == "ozon-only",
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_realization(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_realization"
    results = service._ozon_realization_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_realization",
        source_label="Ozon realization report",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_mutual_settlement(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_mutual_settlement"
    results = service._ozon_mutual_settlement_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_mutual_settlement",
        source_label="Ozon mutual settlement report",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_realization_posting(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_realization_posting"
    results = service._ozon_realization_posting_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        max_pages=min(service._ozon_max_pages(), 3),
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_realization_posting",
        source_label="Ozon realization posting report",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_products_buyout(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_products_buyout"
    results = service._ozon_products_buyout_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_products_buyout",
        source_label="Ozon products buyout report",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_b2b_sales(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_b2b_sales_json"
    results = service._ozon_b2b_sales_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_b2b_sales_json",
        source_label="Ozon B2B sales JSON",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_products(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_products_report"
    results = service._ozon_products_exporter(
        context.credentials.ozon_settings,
        output_dir,
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_products_report",
        source_label="Ozon products report",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_stocks(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_stock_on_warehouses"
    results = service._ozon_stocks_exporter(
        context.credentials.ozon_settings,
        output_dir,
        limit=service._ozon_page_size(),
        max_pages=service._ozon_max_pages(),
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_stock_on_warehouses",
        source_label="Ozon stock on warehouses",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_ozon_returns(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.ozon_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "ozon_returns_report"
    results = service._ozon_returns_exporter(
        context.credentials.ozon_settings,
        output_dir,
        period_start=context.period_start,
        period_end=context.period_end,
        request_delay_seconds=service._ozon_delay_seconds(),
    )
    service._record_ozon_results(
        context.db,
        context.refresh_run,
        output_dir,
        results,
        source_type="ozon_returns_report",
        source_label="Ozon returns report",
        ozon_cabinet_ids=context.credentials.ozon_cabinet_ids,
    )
    return CollectorResult(output_dir=output_dir)


def _collect_onec_odata(
    service: SourceRefreshService,
    context: CollectorContext,
) -> CollectorResult:
    if context.credentials.onec_settings is None:
        return CollectorResult()
    output_dir = context.root_dir / "onec"
    resume_from_dir: Path | None = None
    if context.refresh_run.resumed_from_run_id:
        resumed_from = context.db.get(
            SourceRefreshRun, context.refresh_run.resumed_from_run_id
        )
        if resumed_from is not None and resumed_from.root_dir:
            candidate = Path(resumed_from.root_dir).resolve() / "onec"
            allowed_root = service.settings.source_refresh_root_path.resolve()
            if candidate.is_relative_to(allowed_root) and candidate.is_dir():
                resume_from_dir = candidate
    source_identity = hashlib.sha256(
        context.credentials.onec_settings.base_url.encode("utf-8")
    ).hexdigest()
    _commit_source_refresh_progress(context.db)
    results = service._onec_exporter(
        context.credentials.onec_settings,
        ONEC_REFRESH_COLLECTIONS,
        output_dir,
        top=service._onec_page_size(),
        max_pages=service._onec_max_pages(),
        period_start=context.period_start,
        period_end=context.period_end,
        resume_from_dir=resume_from_dir,
        source_identity=source_identity,
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
        seller_account_id = _first_text(
            item,
            "sellerAccountId",
            "seller_account_id",
            "id",
            f"WB_ACCOUNT_{index}_ID",
        ) or (fallback_id if len(accounts_payload) == 1 else f"{fallback_id}_{index}")
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
    account_name = _integration_account_name(integration)
    tenant = db.get(Tenant, integration.tenant_id)
    client = repository.ensure_client_for_tenant(
        db,
        tenant_id=integration.tenant_id,
        name=tenant.name if tenant else integration.tenant_id,
    )
    cabinet = db.scalar(
        select(WbCabinet)
        .where(
            WbCabinet.client_id == client.id,
            WbCabinet.display_name == account_name,
        )
        .order_by((WbCabinet.provider == "").desc(), WbCabinet.id)
    )
    if cabinet is not None:
        company_id = cabinet.client_company_id or str(
            payload.get("clientCompanyId") or ""
        )
        if integration.provider and not cabinet.provider:
            cabinet.provider = integration.provider
            cabinet.updated_at = security.utcnow()
    else:
        company = repository.ensure_client_company(
            db,
            tenant_id=integration.tenant_id,
            client_id=client.id,
            display_name=str(payload.get("organizationName") or "").strip(),
        )
        company_id = (
            company.id if company else str(payload.get("clientCompanyId") or "")
        )
        cabinet = repository.ensure_wb_cabinet(
            db,
            tenant_id=integration.tenant_id,
            client_id=client.id,
            display_name=account_name,
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


def _safe_ozon_account_id(value: str) -> str:
    normalized = "".join(
        char if char.isalnum() else "_" for char in value.strip().upper()
    ).strip("_")
    return normalized or "OZON_ACCOUNT"


def _env_has_ozon_credentials(env_file: Path = Path(".env")) -> bool:
    env_keys = set(os.environ)
    if any(
        key.startswith("OZON_ACCOUNT_") and key.endswith(("_CLIENT_ID", "_API_KEY"))
        for key in env_keys
    ):
        return True
    if not env_file.exists():
        return False
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if (
                stripped.startswith("OZON_ACCOUNT_")
                and ("_CLIENT_ID=" in stripped or "_API_KEY=" in stripped)
                and stripped.partition("=")[2].strip().strip('"').strip("'")
            ):
                return True
    except OSError:
        return False
    return False


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
    labels = {
        "wb_api": "Wildberries API",
        "ozon_api": "Ozon Seller API",
        "onec_readonly": "1С read-only",
    }
    return {
        "source_type": provider,
        "source_label": labels.get(provider_base, provider),
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
        "rrdIdStart": item.rrd_id_start,
        "rrdIdNext": item.rrd_id_next,
        "statusCode": item.status_code,
        "rawPayloadHash": item.raw_payload_hash,
        "outputFile": item.output_path.name if item.output_path else None,
        "error": item.error,
    }


def _mark_wb_finance_max_pages_issue(
    results: list[WbFinancePageResult],
    payload_items: list[dict[str, Any]],
    *,
    max_pages: int,
) -> bool:
    exhausted = False
    for item, payload in zip(results, payload_items, strict=False):
        if not _wb_finance_has_next_page_after_limit(item, max_pages=max_pages):
            continue
        exhausted = True
        payload["status"] = "partial_source"
        payload["maxPagesReached"] = True
        payload["completenessIssue"] = WB_FINANCE_MAX_PAGES_ISSUE
    return exhausted


def _wb_finance_has_next_page_after_limit(
    item: WbFinancePageResult,
    *,
    max_pages: int,
) -> bool:
    return (
        item.ok
        and item.status == "ok"
        and item.page_index >= max_pages
        and item.rrd_id_next is not None
        and item.rrd_id_next != item.rrd_id_start
    )


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


def _wb_product_cards_payload(
    item: WbProductCardsPageResult,
    *,
    wb_cabinet_id: str = "",
) -> dict[str, Any]:
    return {
        "sellerAccountId": item.seller_account_id,
        "accountName": item.account_name,
        "wbCabinetId": wb_cabinet_id,
        "cardsSource": item.cards_source,
        "pageIndex": item.page_index,
        "status": _wb_product_cards_status(item),
        "ok": item.ok,
        "rowCount": item.flat_row_count,
        "cardCount": item.card_count,
        "statusCode": item.status_code,
        "rawPayloadHash": item.raw_payload_hash,
        "outputFile": item.output_path.name if item.output_path else None,
        "flatOutputFile": item.flat_output_path.name if item.flat_output_path else None,
        "error": item.error,
    }


def _ozon_result_payload(
    item: OzonPageResult,
    *,
    ozon_cabinet_id: str = "",
) -> dict[str, Any]:
    return {
        "marketplace": "ozon",
        "sellerAccountId": item.seller_account_id,
        "accountName": item.account_name,
        "wbCabinetId": ozon_cabinet_id,
        "pageIndex": item.page_index,
        "status": _ozon_status(item),
        "sourceStatus": item.status,
        "ok": item.ok,
        "rowCount": item.row_count,
        "statusCode": item.status_code,
        "sourceEndpoint": item.source_endpoint,
        "rawPayloadHash": item.raw_payload_hash,
        "outputFile": item.output_path.name if item.output_path else None,
        "reportCode": item.report_code,
        "error": item.error,
    }


def _ozon_status(item: OzonPageResult) -> str:
    if item.ok and item.status == "ok" and item.row_count > 0:
        return "loaded"
    if item.ok and item.status == "ok" and item.row_count == 0:
        return "empty_expected"
    if item.ok and item.status == "empty_expected":
        return "empty_expected"
    if item.status == "access_error":
        return "auth_failed"
    if item.status == "rate_limited":
        return "rate_limited"
    if item.status == "transport_error":
        return "schema_error"
    return "failed" if not item.ok else "loaded"


def _ozon_collection_row_count(results: list[OzonPageResult]) -> int:
    has_report_info = any(item.source_type.endswith("_info") for item in results)
    if has_report_info:
        return sum(
            item.row_count for item in results if item.source_type.endswith("_file")
        )
    return sum(item.row_count for item in results)


def _ozon_collection_status(
    results: list[OzonPageResult],
    payload_items: list[dict[str, Any]],
    *,
    row_count: int,
    required: bool,
) -> str:
    has_report_info = any(item.source_type.endswith("_info") for item in results)
    has_file_result = any(item.source_type.endswith("_file") for item in results)
    if has_report_info and (not has_file_result or row_count == 0):
        return "failed" if required else "needs_review"
    return _aggregate_status(payload_items, required=required)


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


def _wb_product_cards_status(item: WbProductCardsPageResult) -> str:
    if item.ok and item.flat_row_count > 0:
        return "loaded"
    if item.ok and item.card_count == 0:
        return "empty_unexpected" if item.page_index == 1 else "empty_expected"
    if item.status_code in {401, 403}:
        return "auth_failed"
    if item.status_code == 429:
        return "rate_limited"
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


def _page_limit_exhausted(
    results: Iterable[Any],
    *,
    max_pages: int,
    page_limit: int,
    row_count_attribute: str,
    group_attributes: tuple[str, ...] = ("seller_account_id",),
) -> bool:
    latest_by_group: dict[tuple[str, ...], Any] = {}
    for item in results:
        group = tuple(
            str(getattr(item, attribute, "")) for attribute in group_attributes
        )
        previous = latest_by_group.get(group)
        if previous is None or int(item.page_index) > int(previous.page_index):
            latest_by_group[group] = item
    return any(
        bool(getattr(item, "ok", False))
        and int(getattr(item, "page_index", 0)) >= max_pages
        and int(getattr(item, row_count_attribute, 0)) >= page_limit
        for item in latest_by_group.values()
    )


def _onec_status(item: OnecSampleExportResult, *, required: bool) -> str:
    if item.status == "partial_source" or (not item.ok and item.page_count > 0):
        return "partial_source"
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


def _commit_source_refresh_progress(db: Session) -> None:
    db.commit()


def _persist_wb_finance_rows(
    db: Session,
    collection: SourceRefreshCollection,
    results: Iterable[WbFinancePageResult],
    *,
    wb_cabinet_ids: dict[str, str],
) -> None:
    try:
        row_number = 1
        batch: list[dict[str, Any]] = []
        for result in results:
            for local_index, row in enumerate(_read_json_list(result.output_path), 1):
                source_row_id = _first_row_id(row, "rrdId", "srid", "orderUid")
                if not source_row_id:
                    source_row_id = f"{result.page_index}:{local_index}"
                batch.append(
                    {
                        "row_number": row_number,
                        "raw_payload_hash": _hash_payload(row),
                        "row_payload": row,
                        "source_row_id": source_row_id,
                        "wb_cabinet_id": wb_cabinet_ids.get(
                            result.seller_account_id,
                            "",
                        ),
                        "loaded_at": collection.loaded_at,
                    }
                )
                row_number += 1
                _flush_snapshot_batch(db, collection, batch)
        _flush_snapshot_batch(db, collection, batch, force=True)
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
        batch: list[dict[str, Any]] = []
        for result in results:
            for local_index, row in enumerate(_read_json_list(result.output_path), 1):
                source_row_id = _first_row_id(row, "reportId")
                if not source_row_id:
                    source_row_id = f"{result.page_index}:{local_index}"
                batch.append(
                    {
                        "row_number": row_number,
                        "raw_payload_hash": _hash_payload(row),
                        "row_payload": row,
                        "source_row_id": source_row_id,
                        "wb_cabinet_id": wb_cabinet_ids.get(
                            result.seller_account_id,
                            "",
                        ),
                        "loaded_at": collection.loaded_at,
                    }
                )
                row_number += 1
                _flush_snapshot_batch(db, collection, batch)
        _flush_snapshot_batch(db, collection, batch, force=True)
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _persist_wb_product_card_rows(
    db: Session,
    collection: SourceRefreshCollection,
    results: Iterable[WbProductCardsPageResult],
    *,
    wb_cabinet_ids: dict[str, str],
) -> None:
    try:
        row_number = 1
        batch: list[dict[str, Any]] = []
        for result in results:
            if result.flat_output_path is None:
                continue
            for local_index, row in enumerate(
                _read_json_list(result.flat_output_path),
                1,
            ):
                source_row_id = _first_row_id(
                    row,
                    "nm_id",
                    "barcode",
                    "vendor_code",
                    "chrt_id",
                )
                if not source_row_id:
                    source_row_id = f"{result.page_index}:{local_index}"
                row_payload = {
                    **row,
                    "marketplace": "wb",
                    "seller_account_id": result.seller_account_id,
                    "source_page_index": result.page_index,
                    "source_cards_source": result.cards_source,
                    "source_output_file": result.flat_output_path.name,
                }
                batch.append(
                    {
                        "row_number": row_number,
                        "raw_payload_hash": _hash_payload(row_payload),
                        "row_payload": row_payload,
                        "source_row_id": source_row_id,
                        "wb_cabinet_id": wb_cabinet_ids.get(
                            result.seller_account_id,
                            "",
                        ),
                        "loaded_at": collection.loaded_at,
                    }
                )
                row_number += 1
                _flush_snapshot_batch(db, collection, batch)
        _flush_snapshot_batch(db, collection, batch, force=True)
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _persist_ozon_rows(
    db: Session,
    collection: SourceRefreshCollection,
    results: Iterable[OzonPageResult],
    *,
    ozon_cabinet_ids: dict[str, str],
) -> None:
    try:
        row_number = 1
        batch: list[dict[str, Any]] = []
        for result in results:
            if _is_ozon_report_control_result(result):
                continue
            for local_index, row in enumerate(_read_ozon_rows(result.output_path), 1):
                source_row_id = _first_row_id(
                    row,
                    "id",
                    "operation_id",
                    "posting_number",
                    "product_id",
                    "offer_id",
                    "sku",
                    "code",
                    "ID товара",
                    "Идентификатор товара",
                    "Артикул",
                    "Артикул продавца",
                    "SKU",
                    "Штрихкод",
                    "Баркод",
                )
                if not source_row_id:
                    source_row_id = (
                        f"{result.source_type}:{result.page_index}:{local_index}"
                    )
                row_payload = {
                    **row,
                    "marketplace": "ozon",
                    "seller_account_id": result.seller_account_id,
                    "source_endpoint": result.source_endpoint,
                    "source_page_index": result.page_index,
                    "source_output_file": (
                        result.output_path.name if result.output_path else ""
                    ),
                }
                batch.append(
                    {
                        "row_number": row_number,
                        "raw_payload_hash": _hash_payload(row_payload),
                        "row_payload": row_payload,
                        "source_row_id": source_row_id,
                        "wb_cabinet_id": ozon_cabinet_ids.get(
                            result.seller_account_id,
                            "",
                        ),
                        "loaded_at": collection.loaded_at,
                    }
                )
                row_number += 1
                _flush_snapshot_batch(db, collection, batch)
        _flush_snapshot_batch(db, collection, batch, force=True)
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _is_ozon_report_control_result(result: OzonPageResult) -> bool:
    if result.source_type.endswith("_info"):
        return True
    if result.source_type.endswith("_file"):
        return False
    endpoint = str(result.source_endpoint or "")
    return endpoint.startswith("/v1/report/") or endpoint == "/v1/report/info"


def _persist_onec_rows(
    db: Session,
    collection: SourceRefreshCollection,
    result: OnecSampleExportResult,
) -> None:
    if result.output_path is None:
        return
    try:
        byte_size = result.output_path.stat().st_size
    except OSError as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)
        return
    if byte_size > ONEC_DATABASE_ROW_PERSIST_MAX_BYTES:
        collection.payload = {
            **(collection.payload or {}),
            "rowPersistence": {
                "status": "skipped_large_snapshot",
                "limitBytes": ONEC_DATABASE_ROW_PERSIST_MAX_BYTES,
                "byteSize": byte_size,
                "rawFilesAuthoritative": True,
            },
        }
        db.flush()
        return
    try:
        rows = _extract_onec_rows(_read_json_object(result.output_path))
        batch: list[dict[str, Any]] = []
        for row_number, row in enumerate(rows, 1):
            source_row_id = _first_row_id(row, "Ref_Key", "LineNumber", "НомерСтроки")
            if not source_row_id:
                source_row_id = f"{result.sample_id}:{row_number}"
            batch.append(
                {
                    "row_number": row_number,
                    "raw_payload_hash": _hash_payload(row),
                    "row_payload": row,
                    "source_row_id": source_row_id,
                    "loaded_at": collection.loaded_at,
                }
            )
            _flush_snapshot_batch(db, collection, batch)
        _flush_snapshot_batch(db, collection, batch, force=True)
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _persist_mapping_rows(
    db: Session,
    collection: SourceRefreshCollection,
    mapping_dir: Path,
) -> None:
    try:
        row_number = 1
        batch: list[dict[str, Any]] = []
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
            batch.append(
                {
                    "row_number": row_number,
                    "raw_payload_hash": _hash_payload(row),
                    "row_payload": row,
                    "source_row_id": relative_path,
                    "loaded_at": collection.loaded_at,
                }
            )
            row_number += 1
            _flush_snapshot_batch(db, collection, batch)
        _flush_snapshot_batch(db, collection, batch, force=True)
    except (OSError, ValueError, TypeError) as exc:
        _mark_raw_row_persistence_failure(db, collection, exc)


def _flush_snapshot_batch(
    db: Session,
    collection: SourceRefreshCollection,
    batch: list[dict[str, Any]],
    *,
    force: bool = False,
) -> None:
    if not batch or (not force and len(batch) < SOURCE_SNAPSHOT_ROW_CHUNK_SIZE):
        return
    repository.add_source_snapshot_rows(db, collection, batch)
    batch.clear()
    _commit_source_refresh_progress(db)


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


def _read_ozon_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    if _path_has_xlsx_signature(path):
        return _read_ozon_xlsx_rows(path)
    if path.suffix.lower() == ".xlsx":
        return _read_ozon_xlsx_rows(path)
    if path.suffix.lower() in {".csv", ".tsv", ".txt"}:
        return _read_ozon_tabular_rows(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        for key in ("items", "rows", "data"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        details = result.get("details")
        if isinstance(details, dict):
            return [details]
        return [result]
    for key in ("items", "rows", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def _read_ozon_tabular_rows(path: Path) -> list[dict[str, Any]]:
    text = _read_text_with_encoding_fallback(path)
    delimiter = _tabular_delimiter(text)
    reader = csv.DictReader(StringIO(text, newline=""), delimiter=delimiter)
    return [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in reader
    ]


def _read_ozon_xlsx_rows(path: Path) -> list[dict[str, Any]]:
    workbook = load_workbook(
        BytesIO(path.read_bytes()),
        read_only=True,
        data_only=True,
    )
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    return _rows_from_table_values(rows)


def _rows_from_table_values(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    normalized_rows = [
        [_cell_text(value) for value in values]
        for values in rows
        if any(_cell_text(value) for value in values)
    ]
    if not normalized_rows:
        return []
    header_index = max(
        range(len(normalized_rows)),
        key=lambda index: (sum(1 for value in normalized_rows[index] if value), -index),
    )
    header_values = normalized_rows[header_index]
    header: list[str] = [
        value if value else f"column_{index}"
        for index, value in enumerate(header_values, start=1)
    ]
    data_rows: list[dict[str, Any]] = []
    for text_values in normalized_rows[header_index + 1 :]:
        data_rows.append(
            {
                header[index]: text_values[index]
                for index in range(min(len(header), len(text_values)))
            }
        )
    return data_rows


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _path_has_xlsx_signature(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"PK\x03\x04"
    except OSError:
        return False


def _read_text_with_encoding_fallback(path: Path) -> str:
    content = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _tabular_delimiter(text: str) -> str:
    sample = text[:4096]
    candidates = {
        "\t": sample.count("\t"),
        ";": sample.count(";"),
        ",": sample.count(","),
    }
    return max(candidates, key=candidates.get)


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


def _stock_history_zip_covered_days(
    path: Path | None,
    *,
    period_start: date,
    period_end: date,
) -> int:
    if path is None or not path.exists():
        return 0
    expected = {
        date.fromordinal(day)
        for day in range(period_start.toordinal(), period_end.toordinal() + 1)
    }
    covered: set[date] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                text = archive.read(name).decode("utf-8-sig", errors="replace")
                reader = csv.reader(StringIO(text))
                headers = next(reader, [])
                for header in headers:
                    try:
                        parsed = datetime.strptime(header.strip(), "%d.%m.%Y").date()
                    except ValueError:
                        continue
                    if parsed in expected:
                        covered.add(parsed)
    except (OSError, zipfile.BadZipFile):
        return 0
    return len(covered)


def _subtract_calendar_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 - max(0, months)
    year, zero_based_month = divmod(absolute_month, 12)
    month = zero_based_month + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


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
