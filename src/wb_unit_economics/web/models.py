from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    reports: Mapped[list[ReportRun]] = relationship(back_populates="tenant")


class ConsultingFirm(Base):
    __tablename__ = "consulting_firms"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_clients_tenant"),
        Index("ix_clients_firm_status", "firm_id", "status"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    firm_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.consulting_firms.id")
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    default_report_settings: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    firm: Mapped[ConsultingFirm] = relationship()
    tenant: Mapped[Tenant] = relationship()


class ClientCompany(Base):
    __tablename__ = "client_companies"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "source_key",
            name="uq_client_company_source_key",
        ),
        Index("ix_client_companies_client", "client_id", "status"),
        Index(
            "uq_client_companies_active_onec_organization",
            "client_id",
            "onec_organization_id",
            unique=True,
            postgresql_where=text("onec_organization_id <> '' AND status = 'active'"),
            sqlite_where=text("onec_organization_id <> '' AND status = 'active'"),
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    source_key: Mapped[str] = mapped_column(String, nullable=False)
    onec_organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    client: Mapped[Client] = relationship()


class ClientCompanyAlias(Base):
    __tablename__ = "client_company_aliases"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "client_company_id",
            "alias_key",
            name="uq_client_company_alias_target",
        ),
        Index(
            "ix_client_company_alias_lookup",
            "client_id",
            "alias_key",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    client_company_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.client_companies.id", ondelete="CASCADE")
    )
    alias_key: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="display_name")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OrganizationTaxProfile(Base):
    __tablename__ = "organization_tax_profiles"
    __table_args__ = (
        UniqueConstraint(
            "source_refresh_run_id",
            "organization_id",
            "valid_from",
            "source",
            name="uq_organization_tax_profile_snapshot",
        ),
        Index(
            "ix_organization_tax_profiles_lookup",
            "client_id",
            "organization_id",
            "valid_from",
            "valid_to",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    client_company_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.client_companies.id")
    )
    organization_id: Mapped[str] = mapped_column(String, nullable=False)
    tax_system: Mapped[str] = mapped_column(String, nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    vat_mode: Mapped[str] = mapped_column(String, nullable=False, default="none")
    vat_deduction_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="unknown"
    )
    revenue_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    income_tax_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String, nullable=False)
    rate_basis_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    basis_document: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_by: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_object_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_refresh_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    source_snapshot_hash: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    methodology_version: Mapped[str] = mapped_column(
        String, nullable=False, default="ozon-tax-profile-v2"
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OrganizationTaxProfileOverride(Base):
    __tablename__ = "organization_tax_profile_overrides"
    __table_args__ = (
        Index(
            "ix_organization_tax_profile_overrides_lookup",
            "client_company_id",
            "status",
            "valid_from",
            "valid_to",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    client_company_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.client_companies.id")
    )
    organization_id: Mapped[str] = mapped_column(String, nullable=False)
    tax_system: Mapped[str] = mapped_column(String, nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    vat_mode: Mapped[str] = mapped_column(String, nullable=False, default="none")
    vat_deduction_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="unknown"
    )
    revenue_tax_rate: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    income_tax_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rate_basis_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    basis_document: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_by: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_object_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OrganizationInputVatPolicy(Base):
    __tablename__ = "organization_input_vat_policies"
    __table_args__ = (
        Index(
            "ix_organization_input_vat_policies_lookup",
            "client_company_id",
            "status",
            "valid_from",
            "valid_to",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    client_company_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.client_companies.id")
    )
    organization_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False, default="accounting_fact")
    product_vat_basis: Mapped[str] = mapped_column(
        String, nullable=False, default="sales_cost_difference"
    )
    service_vat_basis: Mapped[str] = mapped_column(
        String, nullable=False, default="wb_gross_22_122"
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WbCabinet(Base):
    __tablename__ = "wb_cabinets"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "cabinet_key",
            name="uq_wb_cabinet_client_key",
        ),
        Index("ix_wb_cabinets_client", "client_id", "status"),
        Index("ix_wb_cabinets_provider", "tenant_id", "provider"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_company_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.client_companies.id")
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    cabinet_key: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    client: Mapped[Client] = relationship()
    client_company: Mapped[ClientCompany | None] = relationship()


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    access: Mapped[list[UserTenantAccess]] = relationship(back_populates="user")


class UserTenantAccess(Base):
    __tablename__ = "user_tenant_access"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant_access"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.users.id"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="access")
    tenant: Mapped[Tenant] = relationship()


class TenantIntegration(Base):
    __tablename__ = "tenant_integrations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", name="uq_tenant_integration_provider"
        ),
        Index("ix_tenant_integrations_tenant", "tenant_id", "provider"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    provider: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="not_configured"
    )
    secret_hash: Mapped[str] = mapped_column(String, nullable=False, default="")
    secret_hint: Mapped[str] = mapped_column(String, nullable=False, default="")
    config_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    tenant: Mapped[Tenant] = relationship()


class SessionToken(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.users.id"))
    token_hash: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String, nullable=False, default="")
    ip_address: Mapped[str] = mapped_column(String, nullable=False, default="")

    user: Mapped[User] = relationship()


class ReportRun(Base):
    __tablename__ = "report_runs"
    __table_args__ = (
        Index(
            "ix_report_runs_tenant_period", "tenant_id", "period_start", "period_end"
        ),
        Index(
            "ix_report_runs_client_period",
            "client_id",
            "period_start",
            "period_end",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    client_name: Mapped[str] = mapped_column(String, nullable=False)
    report_kind: Mapped[str] = mapped_column(
        String, nullable=False, default="marketplace_unit_economics"
    )
    organization_id: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    source_coverage_start: Mapped[date | None] = mapped_column(Date)
    source_coverage_end: Mapped[date | None] = mapped_column(Date)
    period_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    period_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    publication_status: Mapped[str] = mapped_column(
        String, nullable=False, default="published"
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lineage_type: Mapped[str] = mapped_column(
        String, nullable=False, default="legacy_excel_import"
    )
    source_snapshot_set_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    marketplace_expense_context_version: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    source_workbook: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_workbook_path: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    return_reason_limitation: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    logistics_analysis_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    logistics_dimensions_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="reports")
    client: Mapped[Client] = relationship()
    unit_rows: Mapped[list[ReportUnitRow]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )
    document_reconciliation_rows: Mapped[list[ReportDocumentReconciliationRow]] = (
        relationship(
            back_populates="report",
            cascade="all, delete-orphan",
        )
    )
    artifacts: Mapped[list[ReportArtifact]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )
    logistics_context: Mapped[ReportLogisticsAnalysisContext | None] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        uselist=False,
    )
    logistics_order_rows: Mapped[list[ReportLogisticsOrderRow]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )
    logistics_sku_rows: Mapped[list[ReportLogisticsSkuRow]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )
    logistics_dimension_rows: Mapped[list[ReportLogisticsDimensionRow]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )
    logistics_dimension_context: Mapped[
        ReportLogisticsDimensionContext | None
    ] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        uselist=False,
    )
    logistics_route_rows: Mapped[list[ReportLogisticsRouteRow]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )


class MonthCloseControlReport(Base):
    __tablename__ = "month_close_control_reports"
    __table_args__ = {"schema": "wb_unit_economics"}

    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(String, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class TaxLoadReport(Base):
    __tablename__ = "tax_load_reports"
    __table_args__ = {"schema": "wb_unit_economics"}

    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(String, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ReportArtifact(Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "artifact_type",
            "path",
            name="uq_report_artifact_path",
        ),
        Index(
            "ix_report_artifacts_lookup",
            "tenant_id",
            "report_run_id",
            "artifact_type",
            "status",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False, default="")
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    report: Mapped[ReportRun] = relationship(back_populates="artifacts")


class ReportUnitRow(Base):
    __tablename__ = "report_unit_rows"
    __table_args__ = (
        UniqueConstraint("report_run_id", "row_uid", name="uq_report_unit_row_uid"),
        Index(
            "ix_report_unit_rows_filter",
            "report_run_id",
            "month",
            "document_report",
            "cabinet",
            "organization",
            "scheme",
            "status",
            "loss_class",
        ),
        Index(
            "ix_report_unit_rows_product",
            "report_run_id",
            "product",
            "nm_id",
            "article_wb",
            "article_1c",
            "barcode",
        ),
        Index(
            "ix_report_unit_rows_accounting_period",
            "report_run_id",
            "accounting_period_date",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    week: Mapped[date | None] = mapped_column(Date)
    accounting_period_date: Mapped[date | None] = mapped_column(Date)
    accounting_period_source: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    month: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_report: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_report_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_report_date: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization: Mapped[str] = mapped_column(String, nullable=False, default="")
    cabinet: Mapped[str] = mapped_column(String, nullable=False, default="")
    product: Mapped[str] = mapped_column(String, nullable=False, default="")
    nm_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    article_wb: Mapped[str] = mapped_column(String, nullable=False, default="")
    article_1c: Mapped[str] = mapped_column(String, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String, nullable=False, default="")
    scheme: Mapped[str] = mapped_column(String, nullable=False, default="")
    sales: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    returns: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    net_qty: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    return_rate: Mapped[Decimal | None] = mapped_column(Numeric)
    revenue_before_spp: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    spp: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    revenue: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    vat: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    vat_output: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    vat_input: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    vat_input_from_wb: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    vat_input_from_1c: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    vat_input_from_import_scenario: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    vat_input_from_wb_scenario: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    vat_input_difference: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    vat_input_completeness: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    input_vat_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="accounting_fact"
    )
    vat_input_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    vat_payable: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    revenue_without_vat: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    cost: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric)
    cost_method: Mapped[str] = mapped_column(String, nullable=False, default="")
    cost_match_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    cost_source_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    cost_source_period_start: Mapped[date | None] = mapped_column(Date)
    cost_source_period_end: Mapped[date | None] = mapped_column(Date)
    cost_source_document: Mapped[str] = mapped_column(Text, nullable=False, default="")
    commission: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    logistics: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    storage: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    acceptance: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    promotion: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    penalties: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    acquiring: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    usn: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    income_tax_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    income_tax_base: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    income_tax: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    income_tax_included: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    profit_before_tax: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    profit: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    margin: Mapped[Decimal | None] = mapped_column(Numeric)
    unit_profit: Mapped[Decimal | None] = mapped_column(Numeric)
    tax_method: Mapped[str] = mapped_column(String, nullable=False, default="")
    tax_profile_source: Mapped[str] = mapped_column(String, nullable=False, default="")
    tax_completeness: Mapped[str] = mapped_column(String, nullable=False, default="")
    pnl_vat_mode: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="")
    status_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    spp_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    loss_class: Mapped[str] = mapped_column(String, nullable=False, default="")
    loss_driver: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_snapshot_hashes: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )

    report: Mapped[ReportRun] = relationship(back_populates="unit_rows")


class ReportLogisticsAnalysisContext(Base):
    __tablename__ = "report_logistics_analysis_contexts"
    __table_args__ = (
        Index(
            "ix_report_logistics_context_status",
            "tenant_id",
            "data_status",
        ),
        {"schema": "wb_unit_economics"},
    )

    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False
    )
    source_snapshot_set_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    data_status: Mapped[str] = mapped_column(String, nullable=False)
    source_quality_status: Mapped[str] = mapped_column(
        String, nullable=False, default="ready"
    )
    methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    chain_key_version: Mapped[str] = mapped_column(String, nullable=False)
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    logistics_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    keyed_logistics_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    product_logistics_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    invalid_source_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    required_field_error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    invalid_report_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    report_required_field_error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    chain_dimension_conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    invalid_source_payload_shape_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    source_identity_error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    source_revision_conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    source_revision_discarded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    scope_mismatch_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    key_coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    product_coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    classification_row_coverage_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 4)
    )
    cross_cabinet_collision_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    raw_order_uid_cross_cabinet_reuse_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    unmatched_source_dimension_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    unmatched_report_dimension_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    dimension_delta_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    max_dimension_delta: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    raw_logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    order_logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    sku_logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    report_logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    order_delta: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    sku_delta: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    blocking_reasons: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )
    review_reasons: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    report: Mapped[ReportRun] = relationship(back_populates="logistics_context")


class ReportLogisticsDimensionContext(Base):
    """Версионированный F-1 context выбора Content snapshot и dimension mart."""

    __tablename__ = "report_logistics_dimension_contexts"
    __table_args__ = (
        Index(
            "ix_report_logistics_dimension_context_status",
            "tenant_id",
            "data_status",
        ),
        {"schema": "wb_unit_economics"},
    )

    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False
    )
    factor_methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    data_status: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    source_loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dimension_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    matched_product_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    missing_product_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    invalid_product_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    conflicting_product_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    signal_product_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    blocking_reasons: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )
    review_reasons: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    report: Mapped[ReportRun] = relationship(
        back_populates="logistics_dimension_context"
    )


class ReportLogisticsOrderRow(Base):
    __tablename__ = "report_logistics_order_rows"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "chain_segment_key",
            name="uq_report_logistics_order_segment",
        ),
        Index(
            "ix_report_logistics_orders_filter",
            "report_run_id",
            "financial_week_start",
            "wb_cabinet_id",
            "client_company_id",
            "scheme",
        ),
        Index(
            "ix_report_logistics_orders_product",
            "report_run_id",
            "product_ref",
            "product_key",
            "nm_id",
            "sku",
        ),
        Index(
            "ix_report_logistics_orders_calendar_filter",
            "report_run_id",
            "financial_date",
            "wb_cabinet_id",
            "client_company_id",
            "scheme",
            "product_ref",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False
    )
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    chain_key: Mapped[str] = mapped_column(String, nullable=False)
    chain_segment_key: Mapped[str] = mapped_column(String, nullable=False)
    countable_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    financial_date: Mapped[date | None] = mapped_column(Date)
    financial_week_start: Mapped[date] = mapped_column(Date, nullable=False)
    operation_date_start: Mapped[date] = mapped_column(Date, nullable=False)
    operation_date_end: Mapped[date] = mapped_column(Date, nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date)
    order_period_status: Mapped[str] = mapped_column(
        String, nullable=False, default="unknown"
    )
    product_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    nm_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    sku: Mapped[str] = mapped_column(String, nullable=False, default="")
    vendor_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    product: Mapped[str] = mapped_column(String, nullable=False, default="")
    scheme: Mapped[str] = mapped_column(String, nullable=False, default="")
    warehouse: Mapped[str] = mapped_column(String, nullable=False, default="")
    warehouse_status: Mapped[str] = mapped_column(
        String, nullable=False, default="missing"
    )
    destination: Mapped[str] = mapped_column(String, nullable=False, default="")
    destination_status: Mapped[str] = mapped_column(
        String, nullable=False, default="missing"
    )
    logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_forward: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_reverse: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_unclassified: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    sales_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    return_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    net_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    source_revenue: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    logistics_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    classified_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    source_hash_digest: Mapped[str] = mapped_column(String, nullable=False)
    classification_status: Mapped[str] = mapped_column(String, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String, nullable=False)
    data_quality_status: Mapped[str] = mapped_column(String, nullable=False)

    report: Mapped[ReportRun] = relationship(back_populates="logistics_order_rows")


class ReportLogisticsSkuRow(Base):
    __tablename__ = "report_logistics_sku_rows"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "row_uid",
            name="uq_report_logistics_sku_row",
        ),
        Index(
            "ix_report_logistics_sku_filter",
            "report_run_id",
            "financial_week_start",
            "wb_cabinet_id",
            "client_company_id",
            "scheme",
        ),
        Index(
            "ix_report_logistics_sku_product",
            "report_run_id",
            "product_ref",
            "product_key",
            "nm_id",
            "sku",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False, default=""
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False, default=""
    )
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    financial_week_start: Mapped[date] = mapped_column(Date, nullable=False)
    financial_week_end: Mapped[date | None] = mapped_column(Date)
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    scheme: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    nm_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    sku: Mapped[str] = mapped_column(String, nullable=False, default="")
    vendor_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    product: Mapped[str] = mapped_column(String, nullable=False, default="")
    logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_forward: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_reverse: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_unclassified: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    revenue: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    financial_revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    profit_before_tax: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    profit_without_logistics: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    profit_effect_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    logistics_share_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    logistics_per_order: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    logistics_per_sale: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    sales_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    return_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    chain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    logistics_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    classified_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    low_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    classification_status: Mapped[str] = mapped_column(String, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String, nullable=False)
    data_quality_status: Mapped[str] = mapped_column(String, nullable=False)
    recommendation_flags: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source_hash_digest: Mapped[str] = mapped_column(String, nullable=False)

    report: Mapped[ReportRun] = relationship(back_populates="logistics_sku_rows")


class ReportLogisticsDimensionRow(Base):
    """Витрина габаритов/веса товара (F-1 факторы), additive и неизменяемая.

    Габариты/вес/объём и штраф nullable: отсутствие остаётся явным, а не нулём.
    `dimensions_valid` — сигнал расхождения карточки, не факт замера WB.
    """

    __tablename__ = "report_logistics_dimension_rows"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "row_uid",
            name="uq_report_logistics_dimension_row",
        ),
        Index(
            "ix_report_logistics_dimension_filter",
            "report_run_id",
            "wb_cabinet_id",
            "client_company_id",
            "scheme",
        ),
        Index(
            "ix_report_logistics_dimension_product",
            "report_run_id",
            "product_ref",
            "nm_id",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False, default=""
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False, default=""
    )
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    scheme: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_ref: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    nm_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    sku: Mapped[str] = mapped_column(String, nullable=False, default="")
    vendor_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    product: Mapped[str] = mapped_column(String, nullable=False, default="")
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    weight_brutto_kg: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    volume_l: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    dimensions_valid: Mapped[bool | None] = mapped_column(Boolean)
    measured_penalty_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    evidence_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    coverage_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    data_quality_status: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    source_hash_digest: Mapped[str] = mapped_column(String, nullable=False, default="")

    report: Mapped[ReportRun] = relationship(
        back_populates="logistics_dimension_rows"
    )


class ReportLogisticsRouteRow(Base):
    """Витрина склад/направление (F-3 факторы), additive и неизменяемая.

    Создаётся при достаточном покрытии полей склада/направления. Коэффициент
    недели nullable; несколько значений в цепочке дают `mixed`, а не первое.
    """

    __tablename__ = "report_logistics_route_rows"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "row_uid",
            name="uq_report_logistics_route_row",
        ),
        Index(
            "ix_report_logistics_route_filter",
            "report_run_id",
            "wb_cabinet_id",
            "client_company_id",
            "scheme",
        ),
        Index(
            "ix_report_logistics_route_place",
            "report_run_id",
            "warehouse",
            "destination",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False, default=""
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False, default=""
    )
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    scheme: Mapped[str] = mapped_column(String, nullable=False, default="")
    warehouse: Mapped[str] = mapped_column(String, nullable=False, default="")
    warehouse_status: Mapped[str] = mapped_column(
        String, nullable=False, default="missing"
    )
    destination: Mapped[str] = mapped_column(String, nullable=False, default="")
    destination_status: Mapped[str] = mapped_column(
        String, nullable=False, default="missing"
    )
    logistics_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    chain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    week_coefficient: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    evidence_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    coverage_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_hash_digest: Mapped[str] = mapped_column(String, nullable=False, default="")

    report: Mapped[ReportRun] = relationship(back_populates="logistics_route_rows")


class ReportLostSalesRow(Base):
    __tablename__ = "report_lost_sales_rows"
    __table_args__ = (
        UniqueConstraint("report_run_id", "row_uid", name="uq_report_lost_row_uid"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    cabinet: Mapped[str] = mapped_column(String, nullable=False, default="")
    product: Mapped[str] = mapped_column(String, nullable=False, default="")
    article_1c: Mapped[str] = mapped_column(String, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String, nullable=False, default="")
    zero_stock_days: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    onec_stock_quantity: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    onec_warehouses: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sales: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    lost_units: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    lost_revenue: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    lost_profit: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    calculation_context: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )


class ReportReconciliationMonthly(Base):
    __tablename__ = "report_reconciliation_monthly"
    __table_args__ = (
        UniqueConstraint("report_run_id", "month", name="uq_report_recon_month"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    month: Mapped[str] = mapped_column(String, nullable=False)
    wb_quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    onec_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_cogs: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    onec_cogs: Mapped[Decimal | None] = mapped_column(Numeric)
    cogs_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_mp_expenses: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    onec_mp_expenses: Mapped[Decimal | None] = mapped_column(Numeric)
    mp_expenses_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    onec_basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_run_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ReportMarketplaceExpenseRow(Base):
    __tablename__ = "report_marketplace_expense_rows"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id", "row_uid", name="uq_report_marketplace_expense_row_uid"
        ),
        Index(
            "ix_report_marketplace_expense_filter",
            "report_run_id",
            "recognition_date",
            "wb_cabinet_id",
            "client_company_id",
            "control_group",
            "match_status",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    seller_account_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    cabinet: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization: Mapped[str] = mapped_column(String, nullable=False, default="")
    counterparty_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    recognition_date: Mapped[date | None] = mapped_column(Date)
    document_date: Mapped[date | None] = mapped_column(Date)
    input_date: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_number: Mapped[str] = mapped_column(String, nullable=False, default="")
    input_number: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    service_category: Mapped[str] = mapped_column(String, nullable=False, default="")
    control_group: Mapped[str] = mapped_column(String, nullable=False, default="")
    service_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    amount_without_vat: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, default=0
    )
    vat: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    amount_with_vat: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    match_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_row_hash: Mapped[str] = mapped_column(String, nullable=False, default="")


class ReportDocumentReconciliationRow(Base):
    __tablename__ = "report_document_reconciliation_rows"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "row_uid",
            name="uq_report_document_recon_row_uid",
        ),
        Index(
            "ix_report_document_reconciliation_filter",
            "report_run_id",
            "document_report",
            "cabinet",
            "organization",
            "status",
            "document_type",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    client_company_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_uid: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="")
    payout_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    period_status: Mapped[str] = mapped_column(String, nullable=False, default="")
    document_report: Mapped[str] = mapped_column(String, nullable=False, default="")
    sales_period: Mapped[str] = mapped_column(String, nullable=False, default="")
    sales_period_start: Mapped[date | None] = mapped_column(Date)
    sales_period_end: Mapped[date | None] = mapped_column(Date)
    expected_document_date: Mapped[date | None] = mapped_column(Date)
    document_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    cabinet: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization: Mapped[str] = mapped_column(String, nullable=False, default="")
    summary_report_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    weekly_sales_report_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    weekly_buyout_report_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    wb_report_ids: Mapped[str] = mapped_column(Text, nullable=False, default="")
    onec_documents: Mapped[str] = mapped_column(Text, nullable=False, default="")
    onec_document_types: Mapped[str] = mapped_column(Text, nullable=False, default="")
    onec_document_dates: Mapped[str] = mapped_column(Text, nullable=False, default="")
    wb_sales_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_return_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_net_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_sales_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_return_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_net_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    sales_quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    return_quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    net_quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    quantity_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    amount_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_retail_amount_sum: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_bank_payment_sum: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_primary_document_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    buyout_primary_document_status: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    buyout_primary_document_quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_primary_document_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_primary_document_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_expense_invoice_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_retail_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_for_pay_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    buyout_bank_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    pdf_bank_payment: Mapped[Decimal | None] = mapped_column(Numeric)
    wb_for_pay_sum: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_settlement_total: Mapped[Decimal | None] = mapped_column(Numeric)
    settlement_delta: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_vat: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_cogs: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_cogs_without_vat: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_gross_profit: Mapped[Decimal | None] = mapped_column(Numeric)
    onec_source_rows: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")

    report: Mapped[ReportRun] = relationship(
        back_populates="document_reconciliation_rows"
    )


class SourceLoad(Base):
    __tablename__ = "source_loads"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    report_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    source_refresh_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publication_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_label: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_start: Mapped[date | None] = mapped_column(Date)
    coverage_end: Mapped[date | None] = mapped_column(Date)
    lineage_role: Mapped[str] = mapped_column(String, nullable=False, default="current")
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceRefreshRun(Base):
    __tablename__ = "source_refresh_runs"
    __table_args__ = (
        Index(
            "ix_source_refresh_runs_active",
            "tenant_id",
            "mode",
            "status",
        ),
        Index(
            "ix_source_refresh_runs_snapshot",
            "tenant_id",
            "snapshot_set_id",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    target_report_kind: Mapped[str] = mapped_column(
        String, nullable=False, default="marketplace_unit_economics"
    )
    organization_id: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    generation_stage: Mapped[str] = mapped_column(String, nullable=False, default="")
    requested_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    source_report_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    new_report_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    resumed_from_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    base_source_refresh_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    blocked_by_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    worker_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    failure_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String, nullable=False)
    credential_source: Mapped[str] = mapped_column(String, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snapshot_set_id: Mapped[str] = mapped_column(String, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    source_window_start: Mapped[date | None] = mapped_column(Date)
    source_window_end: Mapped[date | None] = mapped_column(Date)
    root_dir: Mapped[str] = mapped_column(String, nullable=False, default="")
    workbook_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    collections: Mapped[list[SourceRefreshCollection]] = relationship(
        back_populates="refresh_run",
        cascade="all, delete-orphan",
    )


class ReportGenerationRequest(Base):
    __tablename__ = "report_generation_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "client_id",
            "idempotency_key",
            name="uq_report_generation_request_key",
        ),
        Index(
            "ix_report_generation_requests_run",
            "generation_run_id",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    generation_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SourceRefreshCollection(Base):
    __tablename__ = "source_refresh_collections"
    __table_args__ = (
        Index(
            "ix_source_refresh_collections_run",
            "refresh_run_id",
            "source_type",
            "status",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refresh_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization_id: Mapped[str | None] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_label: Mapped[str] = mapped_column(String, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    publication_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    refresh_run: Mapped[SourceRefreshRun] = relationship(back_populates="collections")


class SourceSnapshotRow(Base):
    __tablename__ = "source_snapshot_rows"
    __table_args__ = (
        UniqueConstraint(
            "refresh_run_id",
            "collection_id",
            "row_number",
            name="uq_source_snapshot_row_position",
        ),
        Index(
            "ix_source_snapshot_rows_lookup",
            "tenant_id",
            "source_type",
            "source_row_id",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refresh_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_collections.id")
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_label: Mapped[str] = mapped_column(String, nullable=False)
    source_row_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    row_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketplaceFinanceDailyFact(Base):
    __tablename__ = "marketplace_finance_daily_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "marketplace",
            "grain_hash",
            name="uq_marketplace_finance_daily_fact_grain",
        ),
        Index(
            "ix_marketplace_finance_daily_facts_window",
            "tenant_id",
            "client_id",
            "marketplace",
            "fact_date",
        ),
        Index(
            "ix_marketplace_finance_daily_facts_product",
            "tenant_id",
            "marketplace",
            "nm_id",
            "barcode",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    marketplace: Mapped[str] = mapped_column(String, nullable=False)
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    seller_account_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    fact_date: Mapped[date] = mapped_column(Date, nullable=False)
    marketplace_report_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    document_kind: Mapped[str] = mapped_column(String, nullable=False, default="")
    nm_id: Mapped[int | None] = mapped_column(Integer)
    vendor_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String, nullable=False, default="")
    onec_item_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    sales_model: Mapped[str] = mapped_column(String, nullable=False, default="")
    operation_group: Mapped[str] = mapped_column(String, nullable=False, default="")
    sales_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    return_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), nullable=False, default=0
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    return_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    spp_discount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    net_revenue: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    wb_commission: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    logistics: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    storage: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    acceptance: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    marketplace_promotion: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    penalties_and_holdbacks: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    acquiring: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    cogs: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    gross_profit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    vat_input_from_marketplace: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    vat_input_from_1c: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    accounting_service_input_vat: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_hash_digest: Mapped[str] = mapped_column(String, nullable=False)
    grain_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_partial_source: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    source_snapshot_set_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    source_refresh_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketplaceOperationFact(Base):
    __tablename__ = "marketplace_operation_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "marketplace",
            "source_type",
            "source_key",
            name="uq_marketplace_operation_fact_source",
        ),
        Index(
            "ix_marketplace_operation_facts_window",
            "tenant_id",
            "client_id",
            "marketplace",
            "operation_date",
        ),
        Index(
            "ix_marketplace_operation_facts_product",
            "tenant_id",
            "marketplace",
            "product_id",
            "offer_id",
            "sku",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    marketplace: Mapped[str] = mapped_column(String, nullable=False)
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    seller_account_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_key: Mapped[str] = mapped_column(String, nullable=False)
    source_row_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operation_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    posting_number: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    offer_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    sku: Mapped[str] = mapped_column(String, nullable=False, default="")
    service_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    service_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    operation_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    operation_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    income: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    expense: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    debit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    commission: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    service_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    logistics: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    storage: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    promotion: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    compensation: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    other_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    expenses_loaded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_partial_source: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    currency: Mapped[str] = mapped_column(String, nullable=False, default="RUB")
    source_endpoint: Mapped[str] = mapped_column(String, nullable=False, default="")
    raw_payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    source_snapshot_set_id: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    source_refresh_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.source_refresh_runs.id")
    )
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketplaceFactStaging(Base):
    __tablename__ = "marketplace_fact_staging"
    __table_args__ = (
        UniqueConstraint(
            "load_id",
            "grain_hash",
            name="uq_marketplace_fact_staging_load_grain",
        ),
        Index(
            "ix_marketplace_fact_staging_load",
            "load_id",
            "fact_kind",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    load_id: Mapped[str] = mapped_column(String, nullable=False)
    fact_kind: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    client_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    marketplace: Mapped[str] = mapped_column(String, nullable=False)
    grain_hash: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MarketplaceMappingItem(Base):
    __tablename__ = "marketplace_mapping_items"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "marketplace",
            "source_item_key",
            name="uq_marketplace_mapping_item_key",
        ),
        Index(
            "ix_marketplace_mapping_items_client_status",
            "client_id",
            "marketplace",
            "status",
            "updated_at",
        ),
        Index(
            "ix_marketplace_mapping_items_lookup",
            "tenant_id",
            "marketplace",
            "seller_account_id",
            "vendor_code",
            "barcode",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    marketplace: Mapped[str] = mapped_column(String, nullable=False)
    source_item_key: Mapped[str] = mapped_column(String, nullable=False)
    seller_account_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    organization_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    wb_cabinet_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    product_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    nm_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    ozon_sku: Mapped[str] = mapped_column(String, nullable=False, default="")
    offer_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    vendor_code: Mapped[str] = mapped_column(String, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_row_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_snapshot_hash: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="missing")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class OnecMappingItem(Base):
    __tablename__ = "onec_mapping_items"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "source_item_key",
            name="uq_onec_mapping_item_key",
        ),
        Index(
            "ix_onec_mapping_items_client_lookup",
            "client_id",
            "onec_item_id",
            "onec_article",
            "barcode",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    source_item_key: Mapped[str] = mapped_column(String, nullable=False)
    onec_item_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    onec_article: Mapped[str] = mapped_column(String, nullable=False, default="")
    onec_characteristic: Mapped[str] = mapped_column(String, nullable=False, default="")
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_row_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    source_snapshot_hash: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Marketplace1cMappingCandidate(Base):
    __tablename__ = "marketplace_1c_mapping_candidates"
    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "candidate_key",
            name="uq_marketplace_1c_mapping_candidate_key",
        ),
        Index(
            "ix_marketplace_1c_candidates_item",
            "item_id",
            "status",
            "confidence",
        ),
        Index(
            "ix_marketplace_1c_candidates_client",
            "client_id",
            "method",
            "source",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    item_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.marketplace_mapping_items.id")
    )
    onec_mapping_item_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.onec_mapping_items.id")
    )
    candidate_key: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rejected_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Marketplace1cCurrentMapping(Base):
    __tablename__ = "marketplace_1c_current_mappings"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_marketplace_1c_current_item"),
        Index(
            "ix_marketplace_1c_current_client_status",
            "client_id",
            "status",
            "updated_at",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    item_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.marketplace_mapping_items.id")
    )
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.marketplace_1c_mapping_candidates.id")
    )
    onec_mapping_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.onec_mapping_items.id")
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    match_method: Mapped[str] = mapped_column(String, nullable=False, default="")
    confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False, default=0)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Marketplace1cMappingDecision(Base):
    __tablename__ = "marketplace_1c_mapping_decisions"
    __table_args__ = (
        Index(
            "ix_marketplace_1c_decisions_item_created",
            "item_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_marketplace_1c_decisions_client_created",
            "client_id",
            "created_at",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.clients.id"))
    item_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.marketplace_1c_mapping_candidates.id")
    )
    onec_mapping_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.onec_mapping_items.id")
    )
    previous_mapping_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    new_mapping_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    action: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class LiveCheckCache(Base):
    __tablename__ = "live_check_cache"
    __table_args__ = (
        Index(
            "ix_live_check_cache_lookup",
            "tenant_id",
            "report_run_id",
            "check_type",
            "lookup_key",
            "created_at",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    check_type: Mapped[str] = mapped_column(String, nullable=False)
    lookup_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DataRefreshJob(Base):
    __tablename__ = "data_refresh_jobs"
    __table_args__ = (
        Index(
            "ix_data_refresh_jobs_active",
            "tenant_id",
            "source_report_run_id",
            "status",
        ),
        Index(
            "ix_data_refresh_jobs_report_created",
            "tenant_id",
            "source_report_run_id",
            "created_at",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    source_report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    new_report_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.ai_threads.id")
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    collections: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    snapshot_dir: Mapped[str] = mapped_column(String, nullable=False, default="")
    workbook_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id")
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    entity_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowCard(Base):
    __tablename__ = "accounting_workflow_cards"
    __table_args__ = (
        Index(
            "uq_accounting_workflow_base_card",
            "tenant_id",
            "client_id",
            "organization_id",
            "report_period",
            unique=True,
            postgresql_where=text("supersedes_card_id IS NULL"),
            sqlite_where=text("supersedes_card_id IS NULL"),
        ),
        Index(
            "uq_accounting_workflow_active_card",
            "tenant_id",
            "client_id",
            "organization_id",
            "report_period",
            unique=True,
            postgresql_where=text("stage NOT IN ('closed_payroll', 'cancelled')"),
            sqlite_where=text("stage NOT IN ('closed_payroll', 'cancelled')"),
        ),
        Index(
            "ix_accounting_workflow_cards_board",
            "tenant_id",
            "report_period",
            "stage",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(String, nullable=False)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False, default="new")
    previous_stage: Mapped[str] = mapped_column(String, nullable=False, default="")
    creation_kind: Mapped[str] = mapped_column(
        String, nullable=False, default="scheduled"
    )
    responsible_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    supervisor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    target_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    hard_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    blocking_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cancellation_reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    cancellation_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supersedes_card_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.accounting_workflow_cards.id")
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountingWorkflowTask(Base):
    __tablename__ = "accounting_workflow_tasks"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "report_kind", name="uq_accounting_workflow_task_kind"
        ),
        Index("ix_accounting_workflow_tasks_card", "card_id", "status"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_cards.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    report_kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    current_report_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    current_payload_sha256: Mapped[str] = mapped_column(
        String, nullable=False, default=""
    )
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    facts_confirmed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    facts_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text_approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    text_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocking_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowReportRevision(Base):
    __tablename__ = "accounting_workflow_report_revisions"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "report_id", name="uq_accounting_workflow_task_report"
        ),
        Index(
            "ix_accounting_workflow_revisions_task",
            "task_id",
            "is_current_for_task",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_tasks.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), nullable=False
    )
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current_for_task: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    attached_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowAttachment(Base):
    __tablename__ = "accounting_workflow_attachments"
    __table_args__ = (
        Index("ix_accounting_workflow_attachments_card", "card_id", "created_at"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    card_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_cards.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    original_name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowDelivery(Base):
    __tablename__ = "accounting_workflow_deliveries"
    __table_args__ = (
        Index("ix_accounting_workflow_deliveries_card", "card_id", "sent_at"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_cards.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_tasks.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id"), nullable=False
    )
    payload_sha256: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_channel: Mapped[str] = mapped_column(String, nullable=False)
    channel_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    masked_recipient: Mapped[str] = mapped_column(String, nullable=False)
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.accounting_workflow_attachments.id"),
        nullable=False,
    )
    contact_result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_preliminary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id"), nullable=False
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowFollowup(Base):
    __tablename__ = "accounting_workflow_followups"
    __table_args__ = (
        Index("ix_accounting_workflow_followups_due", "status", "due_at"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_cards.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_deliveries.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="scheduled")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    repeated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supervisor_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowSupervisor(Base):
    __tablename__ = "accounting_workflow_supervisors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", name="uq_accounting_workflow_supervisor"
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountingWorkflowComment(Base):
    __tablename__ = "accounting_workflow_comments"
    __table_args__ = (
        Index("ix_accounting_workflow_comments_card", "card_id", "created_at"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    card_id: Mapped[str] = mapped_column(
        ForeignKey(
            "wb_unit_economics.accounting_workflow_cards.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AccountingWorkflowAuditEvent(Base):
    __tablename__ = "accounting_workflow_audit_events"
    __table_args__ = (
        Index("ix_accounting_workflow_audit_card", "card_id", "created_at"),
        Index("ix_accounting_workflow_audit_tenant", "tenant_id", "created_at"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.tenants.id"), nullable=False
    )
    card_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.accounting_workflow_cards.id")
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    entity_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AiThread(Base):
    __tablename__ = "ai_threads"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.clients.id")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.users.id"))
    report_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    scope_hash: Mapped[str] = mapped_column(String, nullable=False, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AiMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.ai_threads.id")
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chatkit_item_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    tool_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    citations: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AiToolCall(Base):
    __tablename__ = "ai_tool_calls"
    __table_args__ = {"schema": "wb_unit_economics"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.ai_threads.id")
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    output_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AiEvent(Base):
    __tablename__ = "ai_events"
    __table_args__ = (
        Index("ix_ai_events_thread_created", "thread_id", "created_at", "id"),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.ai_threads.id")
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="ok")
    tool_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String, nullable=False, default="client")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AiClientDraft(Base):
    __tablename__ = "ai_client_drafts"
    __table_args__ = (
        UniqueConstraint(
            "report_run_id",
            "revision",
            name="uq_ai_client_draft_report_revision",
        ),
        Index(
            "ix_ai_client_drafts_report_revision",
            "tenant_id",
            "report_run_id",
            "revision",
        ),
        {"schema": "wb_unit_economics"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("wb_unit_economics.tenants.id"))
    report_run_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.report_runs.id")
    )
    thread_id: Mapped[str | None] = mapped_column(
        ForeignKey("wb_unit_economics.ai_threads.id")
    )
    author_user_id: Mapped[str] = mapped_column(
        ForeignKey("wb_unit_economics.users.id")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    limitations: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
