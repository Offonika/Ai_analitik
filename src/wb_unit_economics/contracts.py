from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SalesModel(StrEnum):
    FBO = "fbo"
    FBS = "fbs"


class Marketplace(StrEnum):
    WB = "wb"
    OZON = "ozon"


class MappingStatus(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    EXCLUDED = "excluded"


class DataQualityStatus(StrEnum):
    RELIABLE = "reliable"
    MISSING_COST = "missing_cost"
    MISSING_MAPPING = "missing_mapping"
    AMBIGUOUS_MAPPING = "ambiguous_mapping"
    PARTIAL_SOURCE = "partial_source"
    EXPENSE_WITHOUT_SKU = "expense_without_sku"
    ACCOUNT_ORG_MISMATCH = "account_org_mismatch"
    EXCLUDED = "excluded"
    NEEDS_REVIEW = "needs_review"
    WB_DOCUMENT_MISSING = "wb_document_missing"
    WB_DOCUMENT_DOWNLOADED = "wb_document_downloaded"
    REPORT_TYPE_FALLBACK = "report_type_fallback"
    PAYOUT_SOURCE_MISSING = "payout_source_missing"
    OPIU_PILOT_DEFAULTS = "opiu_pilot_defaults"


class ReportStatus(StrEnum):
    FINAL = "final"
    PARTIAL_PERIOD = "partial_period"


class AdvertisingScope(StrEnum):
    EXCLUDED_FROM_MVP = "excluded_from_mvp"


class OnecReportKind(StrEnum):
    COMMISSIONER_REPORT = "commissioner_report"
    BUYOUT_NOTICE = "buyout_notice"


class ProjectModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class AccountOrgMapping(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    seller_account_name: str
    organization_name: str
    is_default: bool = True
    valid_from: date | None = None
    valid_to: date | None = None


class VatMode(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    NONE = "none"


class TaxProfile(ProjectModel):
    client_id: str
    organization_id: str
    tax_system: str
    vat_rate: Decimal = Decimal("0")
    vat_mode: VatMode = VatMode.NONE
    revenue_tax_rate: Decimal = Decimal("0")
    valid_from: date | None = None
    valid_to: date | None = None
    source: str = "config"

    @field_validator("vat_rate", "revenue_tax_rate", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_period(self) -> TaxProfile:
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to must be greater than or equal to valid_from")
        return self


class WbApiSnapshot(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    period_start: date
    period_end: date
    source_endpoint: str
    loaded_at: datetime
    wb_document_id: str
    wb_report_id: str = ""
    nm_id: int | None = None
    vendor_code: str = ""
    barcode: str = ""
    sales_model: SalesModel
    operation_type: str
    quantity: Decimal = Decimal("0")
    net_revenue: Decimal = Decimal("0")
    wb_commission: Decimal = Decimal("0")
    logistics: Decimal = Decimal("0")
    storage: Decimal = Decimal("0")
    acceptance: Decimal = Decimal("0")
    wb_promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal = Decimal("0")
    advertising: Decimal = Decimal("0")
    currency: str = "RUB"
    raw_payload_hash: str
    original_sale_date: date | None = None
    is_partial_source: bool = False

    @field_validator(
        "quantity",
        "net_revenue",
        "wb_commission",
        "logistics",
        "storage",
        "acceptance",
        "wb_promotion",
        "penalties_and_holdbacks",
        "acquiring",
        "advertising",
        mode="before",
    )
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_period(self) -> WbApiSnapshot:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        return self


class OzonApiSnapshot(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str = ""
    period_start: date
    period_end: date
    source_endpoint: str
    loaded_at: datetime
    source_report_code: str = ""
    product_id: str = ""
    ozon_sku: str = ""
    offer_id: str = ""
    vendor_code: str = ""
    barcode: str = ""
    sales_model: str = ""
    operation_type: str = ""
    sales_quantity: Decimal = Decimal("0")
    return_quantity: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    gross_revenue: Decimal = Decimal("0")
    net_revenue: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    logistics: Decimal = Decimal("0")
    storage: Decimal = Decimal("0")
    promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal = Decimal("0")
    payout: Decimal = Decimal("0")
    currency: str = "RUB"
    raw_payload_hash: str
    is_partial_source: bool = False

    @field_validator(
        "sales_quantity",
        "return_quantity",
        "quantity",
        "gross_revenue",
        "net_revenue",
        "commission",
        "logistics",
        "storage",
        "promotion",
        "penalties_and_holdbacks",
        "acquiring",
        "payout",
        mode="before",
    )
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_period(self) -> OzonApiSnapshot:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        return self


class OzonProductSnapshot(ProjectModel):
    client_id: str
    seller_account_id: str
    loaded_at: datetime
    source_endpoint: str
    product_id: str = ""
    ozon_sku: str = ""
    fbo_sku: str = ""
    fbs_sku: str = ""
    offer_id: str = ""
    vendor_code: str = ""
    barcode: str = ""
    name: str = ""
    status: str = ""
    visibility: str = ""
    price: Decimal = Decimal("0")
    old_price: Decimal = Decimal("0")
    currency: str = "RUB"
    raw_payload_hash: str

    @field_validator("price", "old_price", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class OzonStockSnapshot(ProjectModel):
    client_id: str
    seller_account_id: str
    loaded_at: datetime
    source_endpoint: str
    product_id: str = ""
    ozon_sku: str = ""
    offer_id: str = ""
    warehouse_id: str = ""
    warehouse_name: str = ""
    stock_type: str = ""
    present: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")
    in_way_to_client: Decimal = Decimal("0")
    in_way_from_client: Decimal = Decimal("0")
    raw_payload_hash: str

    @field_validator(
        "present",
        "reserved",
        "in_way_to_client",
        "in_way_from_client",
        mode="before",
    )
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class OzonSkuMapping(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str = ""
    product_id: str = ""
    ozon_sku: str = ""
    offer_id: str = ""
    barcode: str = ""
    onec_item_id: str
    onec_article: str
    onec_characteristic: str = ""
    match_method: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    status: MappingStatus
    comment: str = ""
    updated_by: str
    updated_at: datetime

    @field_validator("confidence", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class MarketplaceApiSnapshot(ProjectModel):
    marketplace: Marketplace
    client_id: str
    seller_account_id: str
    organization_id: str = ""
    period_start: date
    period_end: date
    source_endpoint: str
    loaded_at: datetime
    source_document_id: str = ""
    product_id: str = ""
    nm_id: int | None = None
    ozon_sku: str = ""
    offer_id: str = ""
    vendor_code: str = ""
    barcode: str = ""
    sales_model: str = ""
    operation_type: str = ""
    sales_quantity: Decimal = Decimal("0")
    return_quantity: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    gross_revenue: Decimal = Decimal("0")
    net_revenue: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    logistics: Decimal = Decimal("0")
    storage: Decimal = Decimal("0")
    acceptance: Decimal = Decimal("0")
    promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal = Decimal("0")
    payout: Decimal = Decimal("0")
    currency: str = "RUB"
    raw_payload_hash: str
    is_partial_source: bool = False

    @field_validator(
        "sales_quantity",
        "return_quantity",
        "quantity",
        "gross_revenue",
        "net_revenue",
        "commission",
        "logistics",
        "storage",
        "acceptance",
        "promotion",
        "penalties_and_holdbacks",
        "acquiring",
        "payout",
        mode="before",
    )
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @model_validator(mode="after")
    def validate_period(self) -> MarketplaceApiSnapshot:
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        return self


class OnecUnfCostSnapshot(ProjectModel):
    client_id: str
    organization_id: str
    loaded_at: datetime
    onec_item_id: str
    article: str
    barcode: str
    name: str
    characteristic: str = ""
    cost_value: Decimal
    extra_costs_value: Decimal = Decimal("0")
    cost_currency: str = "RUB"
    cost_method: str
    effective_from: date
    effective_to: date | None = None
    source_document: str
    raw_payload_hash: str

    @field_validator("cost_value", "extra_costs_value", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @property
    def cost_with_extra_costs(self) -> Decimal:
        return self.cost_value + self.extra_costs_value

    def is_effective_for(self, period_start: date, period_end: date) -> bool:
        starts_before_period_end = self.effective_from <= period_end
        ends_after_period_start = (
            self.effective_to is None or self.effective_to >= period_start
        )
        return starts_before_period_end and ends_after_period_start


class SkuMapping(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    nm_id: int | None = None
    vendor_code: str = ""
    barcode: str = ""
    onec_item_id: str
    onec_article: str
    onec_characteristic: str = ""
    match_method: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    status: MappingStatus
    comment: str = ""
    updated_by: str
    updated_at: datetime

    @field_validator("confidence", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class UnitEconomicsRow(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    week_start: date
    week_end: date
    is_partial_week: bool
    document_report: str = ""
    wb_report_id: str = ""
    wb_report_date: str = ""
    nm_id: int | None
    vendor_code: str
    barcode: str
    onec_item_id: str | None = None
    sales_model: SalesModel
    quantity: Decimal
    sales_quantity: Decimal = Decimal("0")
    return_quantity: Decimal = Decimal("0")
    return_amount: Decimal = Decimal("0")
    return_rate_by_quantity: Decimal | None = None
    revenue_before_spp: Decimal = Decimal("0")
    spp_discount: Decimal = Decimal("0")
    spp_discount_rate: Decimal | None = None
    revenue_after_spp: Decimal = Decimal("0")
    spp_source_status: str = "СПП не передается текущим источником"
    net_revenue: Decimal
    wb_commission: Decimal
    logistics: Decimal
    storage: Decimal
    acceptance: Decimal
    wb_promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal
    cogs_from_1c_with_extra_costs: Decimal
    revenue_without_vat: Decimal = Decimal("0")
    gross_profit: Decimal
    vat_5_from_revenue: Decimal = Decimal("0")
    usn_1_from_revenue: Decimal = Decimal("0")
    profit_after_taxes: Decimal = Decimal("0")
    margin: Decimal | None
    margin_after_taxes: Decimal | None = None
    profit_per_unit: Decimal | None
    profit_after_taxes_per_unit: Decimal | None = None
    tax_method: str = ""
    tax_profile_source: str = ""
    advertising_scope: AdvertisingScope = AdvertisingScope.EXCLUDED_FROM_MVP
    data_quality_status: DataQualityStatus
    methodology_version: str
    source_snapshot_hashes: tuple[str, ...]


class ReportReconciliationRow(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    week_start: date
    week_end: date
    wb_report_id: str
    sales_quantity: Decimal
    return_quantity: Decimal
    quantity: Decimal
    revenue_before_spp: Decimal = Decimal("0")
    spp_discount: Decimal = Decimal("0")
    spp_discount_rate: Decimal | None = None
    revenue_after_spp: Decimal = Decimal("0")
    spp_source_status: str = "СПП не передается текущим источником"
    net_revenue: Decimal
    wb_commission: Decimal
    logistics: Decimal
    storage: Decimal
    acceptance: Decimal
    wb_promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal
    cogs_from_1c_with_extra_costs: Decimal
    revenue_without_vat: Decimal = Decimal("0")
    gross_profit: Decimal
    vat_5_from_revenue: Decimal = Decimal("0")
    usn_1_from_revenue: Decimal = Decimal("0")
    profit_after_taxes: Decimal = Decimal("0")
    margin: Decimal | None
    margin_after_taxes: Decimal | None = None
    tax_method: str = ""
    tax_profile_source: str = ""
    data_quality_status: DataQualityStatus
    source_row_count: int


class OnecReportReconciliationRow(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    document_date: date
    week_start: date
    week_end: date
    document_kind: OnecReportKind
    document_label: str
    wb_report_ids: tuple[str, ...]
    sales_quantity: Decimal
    return_quantity: Decimal
    quantity: Decimal
    sales_amount: Decimal
    return_amount: Decimal
    revenue_before_spp: Decimal = Decimal("0")
    spp_discount: Decimal = Decimal("0")
    spp_discount_rate: Decimal | None = None
    revenue_after_spp: Decimal = Decimal("0")
    spp_source_status: str = "СПП не передается текущим источником"
    net_revenue: Decimal
    wb_commission: Decimal
    logistics: Decimal
    storage: Decimal
    acceptance: Decimal
    wb_promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal
    cogs_from_1c_with_extra_costs: Decimal
    revenue_without_vat: Decimal = Decimal("0")
    gross_profit: Decimal
    vat_5_from_revenue: Decimal = Decimal("0")
    usn_1_from_revenue: Decimal = Decimal("0")
    profit_after_taxes: Decimal = Decimal("0")
    margin: Decimal | None
    margin_after_taxes: Decimal | None = None
    tax_method: str = ""
    tax_profile_source: str = ""
    data_quality_status: DataQualityStatus
    source_row_count: int


class OnecReportProductRow(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    document_date: date
    week_start: date
    week_end: date
    document_kind: OnecReportKind
    document_label: str
    wb_report_ids: tuple[str, ...]
    nm_id: int | None
    vendor_code: str
    barcode: str
    onec_item_id: str | None = None
    sales_model: SalesModel
    sales_quantity: Decimal
    return_quantity: Decimal
    quantity: Decimal
    sales_amount: Decimal
    return_amount: Decimal
    revenue_before_spp: Decimal = Decimal("0")
    spp_discount: Decimal = Decimal("0")
    spp_discount_rate: Decimal | None = None
    revenue_after_spp: Decimal = Decimal("0")
    spp_source_status: str = "СПП не передается текущим источником"
    net_revenue: Decimal
    wb_commission: Decimal
    logistics: Decimal
    storage: Decimal
    acceptance: Decimal
    wb_promotion: Decimal = Decimal("0")
    penalties_and_holdbacks: Decimal = Decimal("0")
    acquiring: Decimal
    cogs_from_1c_with_extra_costs: Decimal
    revenue_without_vat: Decimal = Decimal("0")
    gross_profit: Decimal
    vat_5_from_revenue: Decimal = Decimal("0")
    usn_1_from_revenue: Decimal = Decimal("0")
    profit_after_taxes: Decimal = Decimal("0")
    margin: Decimal | None
    margin_after_taxes: Decimal | None = None
    profit_per_unit: Decimal | None
    profit_after_taxes_per_unit: Decimal | None = None
    tax_method: str = ""
    tax_profile_source: str = ""
    data_quality_status: DataQualityStatus
    source_row_count: int
    source_snapshot_hashes: tuple[str, ...]


class ExpenseAllocationRow(ProjectModel):
    client_id: str
    seller_account_id: str
    organization_id: str
    week_start: date
    week_end: date
    document_label: str
    wb_report_ids: tuple[str, ...] = ()
    expense_category: str
    nm_id: int | None = None
    vendor_code: str = ""
    barcode: str = ""
    onec_item_id: str | None = None
    api_base_amount: Decimal = Decimal("0")
    distribution_base_amount: Decimal = Decimal("0")
    api_total_amount: Decimal = Decimal("0")
    control_amount: Decimal | None = None
    allocated_amount: Decimal = Decimal("0")
    scaling_coefficient: Decimal | None = None
    distribution_method: str
    allocation_status: str
    source_row_count: int = 0

    @field_validator(
        "api_base_amount",
        "distribution_base_amount",
        "api_total_amount",
        "control_amount",
        "allocated_amount",
        "scaling_coefficient",
        mode="before",
    )
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))


class WbExpenseAllocationBase(ProjectModel):
    client_id: str
    seller_account_id: str
    week_start: date
    week_end: date
    expense_category: str
    nm_id: int | None = None
    vendor_code: str = ""
    barcode: str = ""
    amount: Decimal = Decimal("0")
    source_endpoint: str
    source_row_count: int = 0
    raw_payload_hashes: tuple[str, ...] = ()

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class OnecGrossProfitDocumentRow(ProjectModel):
    client_id: str
    organization_id: str
    counterparty_id: str
    document_id: str
    document_type: str
    document_number: str = ""
    input_number: str = ""
    document_date: date
    week_start: date
    week_end: date
    sales_quantity: Decimal = Decimal("0")
    return_quantity: Decimal = Decimal("0")
    quantity: Decimal
    revenue: Decimal
    vat: Decimal
    cogs: Decimal
    gross_profit: Decimal
    external_report_id: str = ""
    settlement_total: Decimal | None = None
    source_row_count: int

    @model_validator(mode="after")
    def fill_quantity_breakdown(self) -> OnecGrossProfitDocumentRow:
        if self.sales_quantity == 0 and self.return_quantity == 0:
            if self.quantity > 0:
                self.sales_quantity = self.quantity
            elif self.quantity < 0:
                self.return_quantity = abs(self.quantity)
        return self


class WbSalesReportSummaryRow(ProjectModel):
    client_id: str
    seller_account_id: str
    account_name: str
    report_id: str
    seller_finance_name: str = ""
    date_from: date
    date_to: date
    create_date: date
    currency: str = "RUB"
    report_type: int | None = None
    retail_amount_sum: Decimal = Decimal("0")
    for_pay_sum: Decimal = Decimal("0")
    delivery_service_sum: Decimal = Decimal("0")
    paid_storage_sum: Decimal = Decimal("0")
    paid_acceptance_sum: Decimal = Decimal("0")
    deduction_sum: Decimal = Decimal("0")
    penalty_sum: Decimal = Decimal("0")
    additional_payment_sum: Decimal = Decimal("0")
    cashback_amount_sum: Decimal = Decimal("0")
    cashback_discount_sum: Decimal = Decimal("0")
    cashback_commission_change_sum: Decimal = Decimal("0")
    bank_payment_sum: Decimal = Decimal("0")
    raw_payload_hash: str

    @field_validator(
        "retail_amount_sum",
        "for_pay_sum",
        "delivery_service_sum",
        "paid_storage_sum",
        "paid_acceptance_sum",
        "deduction_sum",
        "penalty_sum",
        "additional_payment_sum",
        "cashback_amount_sum",
        "cashback_discount_sum",
        "cashback_commission_change_sum",
        "bank_payment_sum",
        mode="before",
    )
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class OnecMarketplaceServiceRow(ProjectModel):
    client_id: str
    organization_id: str
    counterparty_id: str
    document_id: str
    document_number: str
    input_number: str = ""
    document_comment: str = ""
    document_date: date
    input_date: date | None = None
    week_start: date
    week_end: date
    service_category: str
    service_name: str
    amount: Decimal = Decimal("0")
    vat: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    amount_includes_vat: bool = False
    vat_included_in_cost: bool = False
    include_expenses_in_cost: bool = False
    source_row_hash: str

    @field_validator("amount", "vat", "total", mode="before")
    @classmethod
    def decimal_from_value(cls, value: object) -> Decimal:
        return Decimal(str(value))


class UnitEconomicsReport(ProjectModel):
    client_id: str
    report_period_start: date
    report_period_end: date
    source_coverage_start: date | None = None
    source_coverage_end: date | None = None
    generated_at: datetime
    status: ReportStatus
    methodology_version: str
    rows: list[UnitEconomicsRow]
    report_reconciliation_rows: list[ReportReconciliationRow] = []
    onec_report_reconciliation_rows: list[OnecReportReconciliationRow] = []
    onec_report_product_rows: list[OnecReportProductRow] = []
    expense_allocation_rows: list[ExpenseAllocationRow] = []
    wb_sales_report_summary_rows: list[WbSalesReportSummaryRow] = []

    @property
    def total_gross_profit(self) -> Decimal:
        return sum((row.gross_profit for row in self.rows), Decimal("0"))

    @property
    def total_profit_after_taxes(self) -> Decimal:
        return sum((row.profit_after_taxes for row in self.rows), Decimal("0"))
