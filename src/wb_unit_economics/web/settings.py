from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SHUMEYKO_",
        extra="ignore",
    )

    database_url: str = "sqlite:///data/web/shumeyko_web.sqlite3"
    runtime_environment: Literal["development", "production", "test"] = "development"
    session_secret: str = "dev-only-change-me"
    session_cookie_name: str = "shumeyko_session"
    session_ttl_hours: int = 12
    remember_me_session_ttl_hours: int = 24 * 30
    cookie_secure: bool = True
    allowed_export_root: str = "reports"
    default_report_workbook: str = "reports/shumeyko_wb_excel_mvp.xlsx"
    openai_model: str = "gpt-5.5"
    openai_api_key: str = ""
    openai_timeout_seconds: float = 60.0
    chatkit_enabled: bool = False
    integration_secret_key: str = ""
    client_login_enabled: bool = True
    external_integrations_enabled: bool = True
    maintenance_message: str = ""
    integration_check_timeout_seconds: float = 10.0
    live_checks_enabled: bool = False
    onec_live_check_mode: str = "odata"
    live_check_cache_ttl_minutes: int = 30
    auto_refresh_enabled: bool = False
    auto_refresh_root: str = "data/onec_auto_refresh"
    auto_refresh_row_limit: int = 5000
    source_refresh_enabled: bool = False
    source_refresh_tenant: str = "shumeyko"
    source_refresh_root: str = "data/source_refresh"
    source_refresh_period_start: str = "2026-03-01"
    source_refresh_period_end: str = ""
    source_refresh_rolling_window_days: int = 14
    source_refresh_incremental_enabled: bool = False
    source_refresh_incremental_window_days: int = 28
    source_refresh_onec_page_size: int = 5000
    source_refresh_onec_max_pages: int = 1000
    accounting_recordtype_page_size: int = 10000
    source_refresh_wb_limit: int = 100000
    source_refresh_wb_max_pages: int = 50
    source_refresh_wb_request_delay_seconds: float = 61.0
    source_refresh_wb_content_request_delay_seconds: float = 0.65
    source_refresh_wb_persist_row_limit: int = 250000
    source_refresh_raw_db_mode: Literal["legacy", "files_only"] = "legacy"
    marketplace_daily_facts_enabled: bool = False
    source_refresh_ozon_typed_facts_enabled: bool = False
    source_refresh_ozon_files_only_enabled: bool = False
    source_refresh_ozon_page_size: int = 1000
    source_refresh_ozon_max_pages: int = 50
    source_refresh_ozon_request_delay_seconds: float = 1.0
    source_refresh_ozon_report_poll_timeout_seconds: float = 300.0
    source_refresh_ozon_report_poll_interval_seconds: float = 5.0
    source_refresh_mapping_dir: str = "data/onec_marketplace_mapping"
    source_refresh_mapping_stale_days: int = 7
    source_refresh_min_free_gb: float = 8.0
    source_refresh_retention_daily_runs: int = 3
    source_refresh_retention_full_runs: int = 2
    source_refresh_failed_snapshot_keep: int = 2
    source_refresh_worker_backend: str = "auto"
    source_refresh_worker_unit_prefix: str = "shumeiko-source-refresh-worker"
    db_first_reports_enabled: bool = False
    enabled_report_kinds: str = "marketplace_unit_economics"
    unit_economics_calculator_enabled: bool = False
    unit_economics_calculator_client_enabled: bool = False
    logistics_analysis_enabled: bool = False
    logistics_analysis_client_enabled: bool = False
    logistics_factors_enabled: bool = False
    logistics_factors_client_enabled: bool = False
    logistics_tariffs_enabled: bool = False
    logistics_tariffs_client_enabled: bool = False
    logistics_routes_enabled: bool = False
    logistics_routes_client_enabled: bool = False
    logistics_measurements_enabled: bool = False
    logistics_measurements_client_enabled: bool = False
    logistics_return_reasons_enabled: bool = False
    logistics_return_reasons_client_enabled: bool = False
    accounting_workflow_enabled: bool = False
    accounting_workflow_scheduler_enabled: bool = False
    accounting_workflow_calendar_configured: bool = False
    accounting_workflow_non_working_dates: str = ""
    accounting_workflow_working_dates: str = ""
    accounting_workflow_evidence_root: str = "data/accounting_workflow_evidence"
    accounting_workflow_evidence_max_bytes: int = 5 * 1024 * 1024
    postgres_statement_timeout_ms: int = 15000
    cors_allow_origins: list[str] = Field(default_factory=list)

    @property
    def resolved_openai_api_key(self) -> str:
        return os.getenv("OPENAI_API_KEY") or self.openai_api_key

    @property
    def export_root_path(self) -> Path:
        return Path(self.allowed_export_root).resolve()

    @property
    def default_report_workbook_path(self) -> Path:
        return Path(self.default_report_workbook).resolve()

    @property
    def auto_refresh_root_path(self) -> Path:
        return Path(self.auto_refresh_root).resolve()

    @property
    def source_refresh_root_path(self) -> Path:
        return Path(self.source_refresh_root).resolve()

    @property
    def source_refresh_mapping_path(self) -> Path:
        return Path(self.source_refresh_mapping_dir).resolve()

    @property
    def enabled_report_kind_set(self) -> set[str]:
        from wb_unit_economics.web.report_kinds import enabled_report_kind_set

        return enabled_report_kind_set(self.enabled_report_kinds)

    @property
    def accounting_workflow_evidence_path(self) -> Path:
        return Path(self.accounting_workflow_evidence_root).resolve()
