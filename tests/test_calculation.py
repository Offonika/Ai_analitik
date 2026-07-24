from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from scripts.rebuild_report_from_sources import _wb_snapshots_from_daily_facts
from tests.fixtures import (
    CLIENT_ID,
    account_org_mapping,
    cost_snapshots,
    sku_mappings,
    wb_snapshots,
)
from wb_unit_economics.calculation import (
    _marketplace_finance_daily_facts,
    build_unit_economics_report,
    calculate_progressive_income_tax,
)
from wb_unit_economics.contracts import (
    AdvertisingScope,
    DataQualityStatus,
    InputVatPolicy,
    MappingStatus,
    MarketplaceFinanceDailyFact,
    OnecMarketplaceServiceRow,
    OnecUnfCostSnapshot,
    ReportStatus,
    SalesModel,
    SkuMapping,
    TaxProfile,
    VatDeductionMode,
    VatMode,
    WbExpenseAllocationBase,
    WbSalesReportSummaryRow,
)


def build_report(as_of_date: date = date(2026, 6, 16)):
    return build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=as_of_date,
    )


def cost_snapshots_with_input_vat() -> list[OnecUnfCostSnapshot]:
    costs = cost_snapshots()
    return [
        costs[0].model_copy(
            update={
                "input_vat_value": Decimal("16.50"),
                "input_vat_source": "1c_sales_register",
            }
        ),
        costs[1].model_copy(
            update={
                "input_vat_value": Decimal("33.00"),
                "input_vat_source": "1c_sales_register",
            }
        ),
    ]


def test_report_marks_q2_before_end_as_partial_period() -> None:
    assert build_report().status is ReportStatus.PARTIAL_PERIOD
    assert build_report(date(2026, 7, 1)).status is ReportStatus.FINAL


def test_report_period_filters_source_rows_by_closing_week() -> None:
    march_snapshot = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 3, 31),
            "period_end": date(2026, 3, 31),
            "raw_payload_hash": "march-hash",
        }
    )
    april_snapshot = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 4, 1),
            "period_end": date(2026, 4, 1),
            "raw_payload_hash": "april-hash",
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[march_snapshot, april_snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 6, 17),
    )

    assert len(report.rows) == 1
    assert report.rows[0].source_snapshot_hashes == ("april-hash", "march-hash")
    assert report.rows[0].is_partial_week is True
    assert report.source_coverage_start == date(2026, 3, 31)
    assert report.source_coverage_end == date(2026, 4, 1)


def test_profit_formula_includes_acquiring_and_cost_extra() -> None:
    report = build_report()
    row = next(item for item in report.rows if item.nm_id == 101)
    assert row.sales_model is SalesModel.FBO
    assert row.sales_quantity == Decimal("2")
    assert row.return_quantity == Decimal("0")
    assert row.return_amount == Decimal("0.00")
    assert row.return_rate_by_quantity == Decimal("0.0000")
    assert row.cogs_from_1c_with_extra_costs == Decimal("230.00")
    assert row.unit_cost == Decimal("115")
    assert row.cost_method == "with_extra_costs"
    assert row.cost_match_status == "exact_week_exact_kind"
    assert row.cost_source_period_start == date(2026, 1, 1)
    assert row.cost_source_period_end is None
    assert row.cost_source_document == "fixture"
    assert row.gross_profit == Decimal("570.00")
    assert row.revenue_without_vat == Decimal("952.38")
    assert row.vat_5_from_revenue == Decimal("47.62")
    assert row.usn_1_from_revenue == Decimal("10.00")
    assert row.profit_after_taxes == Decimal("512.38")
    assert row.margin_after_taxes == Decimal("0.5124")
    assert row.profit_after_taxes_per_unit == Decimal("256.19")
    assert row.revenue_after_spp == Decimal("1000.00")
    assert row.revenue_before_spp == Decimal("1000.00")
    assert row.spp_discount == Decimal("0.00")
    assert row.spp_discount_rate == Decimal("0.0000")
    assert row.spp_source_status == "СПП не передается текущим источником"
    assert row.tax_method == "legacy: НДС внутри цены 5/105; налог с выручки 1%"
    assert row.vat_output == Decimal("47.62")
    assert row.vat_input == Decimal("0")
    assert row.vat_payable == Decimal("47.62")
    assert row.tax_completeness == "legacy_complete"
    assert row.data_quality_status is DataQualityStatus.RELIABLE
    assert row.advertising_scope is AdvertisingScope.EXCLUDED_FROM_MVP


def test_osno_tax_profile_uses_vat_22_inside_price_and_input_vat() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots_with_input_vat(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="Catalog_Организации",
            )
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = next(item for item in report.rows if item.nm_id == 101)
    assert row.revenue_without_vat == Decimal("819.67")
    assert row.vat_output == Decimal("180.33")
    assert row.vat_input == Decimal("33.00")
    assert row.vat_payable == Decimal("147.33")
    assert row.vat_5_from_revenue == Decimal("147.33")
    assert row.usn_1_from_revenue == Decimal("0.00")
    assert row.income_tax_base == Decimal("422.67")
    assert row.income_tax == Decimal("0")
    assert row.income_tax_included is False
    assert row.tax_completeness == "vat_input_partial_ndfl_not_allocated"
    assert row.profit_after_taxes == Decimal("422.67")
    assert row.gross_profit == Decimal("422.67")
    assert row.cogs_from_1c_with_extra_costs == Decimal("197.00")
    assert row.margin_after_taxes == Decimal("0.5157")
    assert row.pnl_vat_mode == "without_vat_for_osno"
    assert (
        row.tax_method == "ОСНО; НДС 22% внутри цены; налог с выручки 0%; "
        "входящий НДС учтен; НДФЛ ИП сверху"
    )
    assert row.tax_profile_source == "Catalog_Организации"


def test_management_input_vat_changes_only_tax_bridge_not_pnl() -> None:
    sale = wb_snapshots()[0]
    without_vat_cost = cost_snapshots()[0].model_copy(
        update={
            "cost_method": "sales_register_weighted_average_without_vat",
            "input_vat_value": None,
            "input_vat_source": "",
        }
    )
    scenario_cost = without_vat_cost.model_copy(
        update={
            "input_vat_value": Decimal("16.50"),
            "input_vat_source": "management_assumption:sales_cost_difference",
        }
    )
    tax_profile = TaxProfile(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        source="Catalog_Организации",
    )
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )
    common = {
        "client_id": CLIENT_ID,
        "wb_snapshots": [sale],
        "sku_mappings": sku_mappings(),
        "account_org_mapping": account_org_mapping(),
        "tax_profiles": [tax_profile],
        "generated_at": datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        "as_of_date": date(2026, 6, 16),
    }
    accounting = build_unit_economics_report(
        **common,
        cost_snapshots=[without_vat_cost],
    ).rows[0]
    scenario = build_unit_economics_report(
        **common,
        cost_snapshots=[scenario_cost],
        input_vat_policies=[policy],
    ).rows[0]

    assert scenario.net_revenue == accounting.net_revenue
    assert (
        scenario.cogs_from_1c_with_extra_costs
        == accounting.cogs_from_1c_with_extra_costs
    )
    assert scenario.gross_profit == accounting.gross_profit
    assert scenario.vat_input_from_import_scenario == Decimal("33.00")
    assert scenario.vat_input_from_wb_scenario == Decimal("35.16")
    assert scenario.vat_input == Decimal("68.16")
    assert accounting.vat_payable - scenario.vat_payable == Decimal("68.16")
    assert scenario.input_vat_mode == "management_assumption"
    assert scenario.vat_input_confirmed is False
    assert scenario.vat_input_completeness == "management_assumption"


def test_confirmed_purchase_book_disables_management_service_scenario() -> None:
    sale = wb_snapshots()[0].model_copy(update={"vat_input_from_wb": Decimal("27.05")})
    actual_cost = cost_snapshots()[0].model_copy(
        update={
            "cost_method": "sales_register_weighted_average_without_vat",
            "input_vat_value": Decimal("16.50"),
            "input_vat_source": "onec_purchase_book_confirmed_cost_difference",
        }
    )
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )
    service_row = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="confirmed-service",
        document_number="1",
        document_date=date(2026, 4, 13),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Комиссия WB",
        service_name="Комиссия WB",
        amount=Decimal("122.95"),
        vat=Decimal("27.05"),
        total=Decimal("150"),
        source_row_hash="confirmed-service-hash",
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale],
        cost_snapshots=[actual_cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="Catalog_Организации",
            )
        ],
        input_vat_policies=[policy],
        confirmed_input_vat_org_ids={"1C_ORG_1"},
        onec_marketplace_service_rows=[service_row],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.vat_input_from_import_scenario == Decimal("0.00")
    assert row.vat_input_from_wb_scenario == Decimal("0.00")
    assert row.input_vat_mode == "accounting_fact"
    assert row.vat_input_completeness == "confirmed"
    assert row.vat_input_confirmed is True
    assert row.vat_input == Decimal("60.05")


def test_management_input_vat_preserves_return_sign_and_zero_goods_quantity() -> None:
    base = wb_snapshots()[0]
    returned = base.model_copy(
        update={
            "operation_type": "return",
            "quantity": Decimal("-1"),
            "net_revenue": Decimal("-500"),
            "wb_commission": Decimal("-50"),
            "logistics": Decimal("30"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "acquiring": Decimal("-7"),
        }
    )
    zero_quantity = base.model_copy(
        update={
            "wb_document_id": "zero-quantity",
            "quantity": Decimal("0"),
            "net_revenue": Decimal("0"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "acquiring": Decimal("0"),
        }
    )
    scenario_cost = cost_snapshots()[0].model_copy(
        update={
            "cost_method": "sales_register_weighted_average_without_vat",
            "input_vat_value": Decimal("16.50"),
            "input_vat_source": "management_assumption:sales_cost_difference",
        }
    )
    profile = TaxProfile(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        source="Catalog_Организации",
    )
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[returned, zero_quantity],
        cost_snapshots=[scenario_cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[profile],
        input_vat_policies=[policy],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.vat_input_from_import_scenario == Decimal("-16.50")
    assert row.vat_input_from_wb_scenario == Decimal("-4.87")
    assert row.vat_input == Decimal("-21.37")


def test_management_input_vat_keeps_partial_mapping_unconfirmed() -> None:
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )
    profile = TaxProfile(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        source="Catalog_Организации",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=[],
        sku_mappings=[],
        account_org_mapping=account_org_mapping(),
        tax_profiles=[profile],
        input_vat_policies=[policy],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.vat_input_from_import_scenario == Decimal("0.00")
    assert row.vat_input_from_wb_scenario == Decimal("35.16")
    assert row.vat_input_completeness == "partial"
    assert row.vat_input_confirmed is False


def test_osno_uses_explicit_wb_input_vat() -> None:
    sale = wb_snapshots()[0].model_copy(update={"vat_input_from_wb": Decimal("4.45")})
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale],
        cost_snapshots=cost_snapshots_with_input_vat(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="Catalog_Организации",
            )
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.vat_input_from_wb == Decimal("4.45")
    assert row.vat_input_from_1c == Decimal("0.00")
    assert row.vat_input == Decimal("37.45")
    assert row.vat_payable == Decimal("142.88")
    assert row.vat_input_completeness == "partial"
    assert row.tax_completeness == "vat_input_partial_ndfl_not_allocated"


def test_osno_calculates_wb_service_vat_and_reconciles_1c_control() -> None:
    service_row = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="service-1",
        document_number="1",
        document_date=date(2026, 4, 13),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Комиссия WB",
        service_name="Комиссия WB",
        amount=Decimal("122.95"),
        vat=Decimal("27.05"),
        total=Decimal("150"),
        source_row_hash="service-hash-1",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=cost_snapshots_with_input_vat(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="Catalog_Организации",
            )
        ],
        onec_marketplace_service_rows=[service_row],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.vat_input_from_wb == Decimal("27.05")
    assert row.vat_input_from_1c == Decimal("27.05")
    assert row.vat_input == Decimal("60.05")
    assert row.vat_payable == Decimal("120.28")
    assert row.gross_profit == Decimal("449.72")
    assert row.profit_after_taxes == Decimal("449.72")
    assert row.vat_input_difference == Decimal("0.00")
    assert row.vat_input_completeness == "confirmed"
    reconciliation = report.tax_input_reconciliation_rows[0]
    assert reconciliation.vat_input_from_wb == Decimal("27.05")
    assert reconciliation.vat_input_from_1c == Decimal("27.05")
    assert reconciliation.vat_input_completeness == "confirmed"


def test_osno_pnl_uses_no_vat_revenue_cogs_and_wb_services() -> None:
    sale = wb_snapshots()[0].model_copy(
        update={
            "quantity": Decimal("1"),
            "net_revenue": Decimal("1220"),
            "wb_commission": Decimal("122"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("0"),
            "raw_payload_hash": "wb-hash-osno-no-vat-pnl",
        }
    )
    cost = cost_snapshots()[0].model_copy(
        update={
            "cost_value": Decimal("500"),
            "extra_costs_value": Decimal("0"),
            "cost_method": (
                "sales_register_weighted_average_without_vat_reconciliation_needs_review"
            ),
            "source_document": "AccumulationRegister_Продажи/СебестоимостьБезНДС",
        }
    )
    service_row = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="service-1",
        document_number="1",
        document_date=date(2026, 4, 13),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Комиссия WB",
        service_name="Комиссия WB",
        amount=Decimal("100"),
        vat=Decimal("22"),
        total=Decimal("122"),
        source_row_hash="service-hash-no-vat-pnl",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale],
        cost_snapshots=[cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="Catalog_Организации",
            )
        ],
        onec_marketplace_service_rows=[service_row],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.revenue_without_vat == Decimal("1000.00")
    assert row.vat_output == Decimal("220.00")
    assert row.vat_input == Decimal("22.00")
    assert row.vat_payable == Decimal("198.00")
    assert row.cogs_from_1c_with_extra_costs == Decimal("500.00")
    assert row.gross_profit == Decimal("400.00")
    assert row.profit_after_taxes == Decimal("400.00")
    assert row.pnl_vat_mode == "without_vat_for_osno"


def test_osno_penalty_is_full_expense_and_has_no_deductible_vat() -> None:
    penalty = wb_snapshots()[0].model_copy(
        update={
            "quantity": Decimal("0"),
            "net_revenue": Decimal("0"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "wb_promotion": Decimal("0"),
            "penalties_and_holdbacks": Decimal("122"),
            "acquiring": Decimal("0"),
            "vat_input_from_wb": Decimal("22"),
            "raw_payload_hash": "wb-penalty-only",
        }
    )
    penalty_document = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="penalty-service",
        document_number="P-1",
        document_date=date(2026, 4, 13),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Штрафы",
        service_name="Штрафы",
        amount=Decimal("122"),
        vat=Decimal("22"),
        total=Decimal("144"),
        source_row_hash="penalty-service-hash",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[penalty],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                source="Catalog_Организации",
            )
        ],
        onec_marketplace_service_rows=[penalty_document],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.penalties_and_holdbacks == Decimal("122.00")
    assert row.vat_input == Decimal("0.00")
    assert row.gross_profit == Decimal("-122.00")
    assert row.profit_after_taxes == Decimal("-122.00")
    assert row.profit_per_unit is None
    assert row.profit_after_taxes_per_unit is None


def test_osno_vat_input_mismatch_marks_needs_review() -> None:
    sale = wb_snapshots()[0].model_copy(update={"vat_input_from_wb": Decimal("4.45")})
    service_row = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="service-1",
        document_number="1",
        document_date=date(2026, 4, 13),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Комиссия WB",
        service_name="Комиссия WB",
        amount=Decimal("100"),
        vat=Decimal("9"),
        total=Decimal("109"),
        source_row_hash="service-hash-1",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale],
        cost_snapshots=cost_snapshots_with_input_vat(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                source="Catalog_Организации",
            )
        ],
        onec_marketplace_service_rows=[service_row],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.vat_input_from_wb == Decimal("4.45")
    assert row.vat_input_from_1c == Decimal("9.00")
    assert row.vat_input_difference == Decimal("4.55")
    assert row.vat_input_completeness == "mismatch"
    assert row.data_quality_status is DataQualityStatus.TAX_REVIEW


def test_osno_missing_input_vat_marks_row_needs_review() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="Catalog_Организации",
            )
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = next(item for item in report.rows if item.nm_id == 101)
    assert row.data_quality_status is DataQualityStatus.TAX_REVIEW
    assert row.vat_output == Decimal("180.33")
    assert row.vat_input == Decimal("0")
    assert row.vat_payable == Decimal("0")
    assert row.vat_5_from_revenue == Decimal("0")
    assert row.profit_after_taxes == row.gross_profit
    assert row.tax_completeness == "input_vat_missing"


def test_tax_profiles_are_selected_by_organization() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots_with_input_vat(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                source="Catalog_Организации",
            ),
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_2",
                tax_system="УСН Доходы",
                vat_rate=Decimal("5"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0.01"),
                source="fixture",
            ),
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    osno_row = next(item for item in report.rows if item.nm_id == 101)
    legacy_row = next(item for item in report.rows if item.nm_id == 202)
    assert osno_row.vat_output == Decimal("180.33")
    assert osno_row.vat_input == Decimal("33.00")
    assert osno_row.vat_5_from_revenue == Decimal("147.33")
    assert osno_row.usn_1_from_revenue == Decimal("0.00")
    assert osno_row.pnl_vat_mode == "without_vat_for_osno"
    assert legacy_row.vat_5_from_revenue == Decimal("-23.81")
    assert legacy_row.usn_1_from_revenue == Decimal("-5.00")


def test_missing_required_tax_profile_marks_row_needs_review() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                source="Catalog_Организации",
            )
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = next(item for item in report.rows if item.nm_id == 202)
    assert row.data_quality_status is DataQualityStatus.TAX_PROFILE_MISSING
    assert row.vat_5_from_revenue == Decimal("0")
    assert row.usn_1_from_revenue == Decimal("0")
    assert row.profit_after_taxes == row.gross_profit
    assert row.tax_method == "Налоговый профиль не найден"
    assert row.tax_profile_source == "missing"


def test_zero_net_sale_and_return_do_not_require_cost() -> None:
    sale = wb_snapshots()[0]
    returned = sale.model_copy(
        update={
            "wb_document_id": "doc-return",
            "operation_type": "return",
            "quantity": Decimal("-2"),
            "net_revenue": Decimal("-1000"),
            "wb_commission": Decimal("-100"),
            "logistics": Decimal("-50"),
            "storage": Decimal("-20"),
            "acceptance": Decimal("-10"),
            "penalties_and_holdbacks": Decimal("-5"),
            "acquiring": Decimal("-15"),
            "raw_payload_hash": "wb-return-hash",
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale, returned],
        cost_snapshots=[],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.quantity == Decimal("0")
    assert row.cogs_from_1c_with_extra_costs == Decimal("0.00")
    assert row.data_quality_status is DataQualityStatus.RELIABLE


def test_zero_net_sale_and_return_keep_applied_cost_review_status() -> None:
    sale = wb_snapshots()[0]
    returned = sale.model_copy(
        update={
            "wb_document_id": "doc-return",
            "operation_type": "return",
            "quantity": Decimal("-2"),
            "net_revenue": Decimal("-1000"),
            "wb_commission": Decimal("-100"),
            "logistics": Decimal("-50"),
            "storage": Decimal("-20"),
            "acceptance": Decimal("-10"),
            "penalties_and_holdbacks": Decimal("-5"),
            "acquiring": Decimal("-15"),
            "raw_payload_hash": "wb-return-hash",
        }
    )
    fallback_cost = cost_snapshots()[0].model_copy(
        update={
            "cost_method": "stock_register_fixed_receipt_fallback_needs_review",
            "source_document": "AccumulationRegister_Запасы fallback",
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale, returned],
        cost_snapshots=[fallback_cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.quantity == Decimal("0")
    assert row.cogs_from_1c_with_extra_costs == Decimal("0.00")
    assert row.cost_method == "stock_register_fixed_receipt_fallback_needs_review"
    assert row.data_quality_status is DataQualityStatus.NEEDS_REVIEW


def test_unconfirmed_or_unsupported_tax_profile_does_not_calculate_taxes() -> None:
    profiles = [
        TaxProfile(
            client_id=CLIENT_ID,
            organization_id="1C_ORG_1",
            tax_system="УСН Доходы",
            vat_rate=Decimal("0"),
            vat_mode=VatMode.NONE,
            vat_deduction_mode=VatDeductionMode.UNKNOWN,
            revenue_tax_rate=Decimal("0.06"),
            source="Catalog_Организации",
        ),
        TaxProfile(
            client_id=CLIENT_ID,
            organization_id="1C_ORG_1",
            tax_system="УСН Доходы минус расходы",
            vat_rate=Decimal("0"),
            vat_mode=VatMode.NONE,
            vat_deduction_mode=VatDeductionMode.NOT_APPLICABLE,
            revenue_tax_rate=Decimal("0.15"),
            source="Catalog_Организации",
        ),
    ]

    for profile in profiles:
        report = build_unit_economics_report(
            client_id=CLIENT_ID,
            wb_snapshots=wb_snapshots(),
            cost_snapshots=cost_snapshots(),
            sku_mappings=sku_mappings(),
            account_org_mapping=account_org_mapping(),
            tax_profiles=[profile],
            generated_at=datetime(
                2026,
                6,
                16,
                12,
                0,
                tzinfo=ZoneInfo("Europe/Moscow"),
            ),
            as_of_date=date(2026, 6, 16),
        )

        row = next(item for item in report.rows if item.nm_id == 101)
        assert row.tax_method == "Налоговый профиль не найден"
        assert row.tax_profile_source == "missing"
        assert row.vat_5_from_revenue == Decimal("0")
        assert row.usn_1_from_revenue == Decimal("0")
        assert row.profit_after_taxes == row.gross_profit


def test_ip_ndfl_progressive_tax_uses_annual_cumulative_base() -> None:
    assert calculate_progressive_income_tax(Decimal("2400000")) == Decimal("312000.00")
    assert calculate_progressive_income_tax(Decimal("5300000")) == Decimal("756000.00")
    assert calculate_progressive_income_tax(Decimal("0")) == Decimal("0.00")


def test_unit_economics_row_keeps_sales_returns_and_net_quantity() -> None:
    sale = wb_snapshots()[0]
    returned = sale.model_copy(
        update={
            "wb_document_id": "doc-return-same-product",
            "operation_type": "return",
            "quantity": Decimal("-1"),
            "net_revenue": Decimal("-400"),
            "wb_commission": Decimal("-40"),
            "logistics": Decimal("25"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("-6"),
            "raw_payload_hash": "wb-hash-return-same-product",
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale, returned],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.sales_quantity == Decimal("2")
    assert row.return_quantity == Decimal("1")
    assert row.quantity == Decimal("1")
    assert row.return_amount == Decimal("400.00")
    assert row.return_rate_by_quantity == Decimal("0.5000")
    assert row.cogs_from_1c_with_extra_costs == Decimal("115.00")


def test_profit_per_unit_is_empty_when_net_quantity_is_not_positive() -> None:
    returned = wb_snapshots()[0].model_copy(
        update={
            "operation_type": "return",
            "quantity": Decimal("-1"),
            "net_revenue": Decimal("-400"),
            "wb_commission": Decimal("-40"),
            "raw_payload_hash": "return-only",
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[returned],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].quantity == Decimal("-1")
    assert report.rows[0].profit_per_unit is None
    assert report.rows[0].profit_after_taxes_per_unit is None


def test_zero_amount_goods_rows_do_not_increase_document_quantity() -> None:
    sale = wb_snapshots()[0].model_copy(
        update={
            "wb_report_id": "ZERO-AMOUNT-WEEK",
            "period_start": date(2026, 4, 6),
            "period_end": date(2026, 4, 6),
            "quantity": Decimal("2"),
            "net_revenue": Decimal("1000"),
            "raw_payload_hash": "nonzero-sale",
        }
    )
    zero_amount_sale = sale.model_copy(
        update={
            "wb_document_id": "zero-amount-sale",
            "quantity": Decimal("1"),
            "net_revenue": Decimal("0"),
            "raw_payload_hash": "zero-amount-sale",
        }
    )
    zero_amount_return = sale.model_copy(
        update={
            "wb_document_id": "zero-amount-return",
            "operation_type": "return",
            "quantity": Decimal("-1"),
            "net_revenue": Decimal("0"),
            "raw_payload_hash": "zero-amount-return",
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[sale, zero_amount_sale, zero_amount_return],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    unit_row = report.rows[0]
    assert unit_row.sales_quantity == Decimal("2")
    assert unit_row.return_quantity == Decimal("0")
    assert unit_row.quantity == Decimal("2")

    document_row = report.onec_report_reconciliation_rows[0]
    assert document_row.sales_quantity == Decimal("2")
    assert document_row.return_quantity == Decimal("0")
    assert document_row.quantity == Decimal("2")


def test_storage_and_promotion_are_scaled_to_weekly_wb_report() -> None:
    snapshot = wb_snapshots()[0].model_copy(
        update={
            "wb_report_id": "726807272",
            "storage": Decimal("20"),
            "wb_promotion": Decimal("10"),
        }
    )
    summary = WbSalesReportSummaryRow(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        account_name="WB_ACCOUNT_1",
        report_id="726807272",
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        create_date=date(2026, 4, 13),
        report_type=1,
        paid_storage_sum="30",
        deduction_sum="15",
        raw_payload_hash="summary-hash-1",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        wb_sales_report_summary_rows=[summary],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.wb_report_id == "726807272"
    assert row.wb_report_date == "2026-04-13"
    assert (
        row.document_report
        == "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
    )
    assert row.storage == Decimal("30.00")
    assert row.wb_promotion == Decimal("15.00")
    assert row.gross_profit == Decimal("545.00")
    allocations = {
        item.expense_category: item for item in report.expense_allocation_rows
    }
    assert allocations["Хранение"].control_amount == Decimal("30.00")
    assert allocations["Хранение"].api_total_amount == Decimal("20.00")
    assert allocations["Хранение"].allocated_amount == Decimal("30.00")
    assert allocations["Хранение"].wb_report_ids == ("726807272",)
    assert (
        allocations["Хранение"].allocation_status
        == "Распределено по API, приведено к фин. отчету WB"
    )
    assert allocations["WB Продвижение"].allocated_amount == Decimal("15.00")


def test_report_type_from_sales_report_list_classifies_document_kind() -> None:
    snapshot = wb_snapshots()[0].model_copy(update={"wb_report_id": "NO-SUFFIX"})
    summary = WbSalesReportSummaryRow(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        account_name="WB_ACCOUNT_1",
        report_id="NO-SUFFIX",
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        create_date=date(2026, 4, 13),
        report_type=2,
        raw_payload_hash="summary-hash-report-type",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        wb_sales_report_summary_rows=[summary],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert "Уведомление о выкупе" in report.rows[0].document_report
    assert report.rows[0].data_quality_status is DataQualityStatus.RELIABLE


def test_report_type_suffix_fallback_marks_review_status() -> None:
    snapshot = wb_snapshots()[0].model_copy(update={"wb_report_id": "535699202604061"})
    unrelated_summary = WbSalesReportSummaryRow(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        account_name="WB_ACCOUNT_1",
        report_id="OTHER-REPORT",
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        create_date=date(2026, 4, 13),
        report_type=1,
        raw_payload_hash="summary-hash-other",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        wb_sales_report_summary_rows=[unrelated_summary],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert "Уведомление о выкупе" in report.rows[0].document_report
    assert report.rows[0].data_quality_status is DataQualityStatus.REPORT_TYPE_FALLBACK


def test_spp_discount_is_allocated_from_weekly_wb_report() -> None:
    summary = WbSalesReportSummaryRow(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        account_name="WB_ACCOUNT_1",
        report_id="726807272",
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        create_date=date(2026, 4, 13),
        report_type=1,
        cashback_discount_sum="100",
        raw_payload_hash="summary-hash-spp",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        wb_sales_report_summary_rows=[summary],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.revenue_after_spp == Decimal("1000.00")
    assert row.spp_discount == Decimal("100.00")
    assert row.revenue_before_spp == Decimal("1100.00")
    assert row.spp_discount_rate == Decimal("0.0909")
    assert row.spp_source_status == "СПП из WB sales-reports/list cashbackDiscountSum"
    reconciliation = report.report_reconciliation_rows[0]
    assert reconciliation.revenue_before_spp == Decimal("1100.00")
    assert reconciliation.spp_discount == Decimal("100.00")


def test_no_sku_storage_and_promotion_allocate_to_products_by_revenue() -> None:
    product_snapshot = wb_snapshots()[0].model_copy(
        update={
            "storage": Decimal("0"),
            "wb_promotion": Decimal("0"),
        }
    )
    expense_snapshot = product_snapshot.model_copy(
        update={
            "wb_document_id": "expense-no-sku",
            "nm_id": 0,
            "vendor_code": "",
            "barcode": "",
            "operation_type": "deduction",
            "quantity": Decimal("0"),
            "net_revenue": Decimal("0"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("30"),
            "acceptance": Decimal("0"),
            "wb_promotion": Decimal("15"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("0"),
            "advertising": Decimal("0"),
            "raw_payload_hash": "expense-no-sku-hash",
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[product_snapshot, expense_snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    product_row = next(item for item in report.rows if item.nm_id == 101)
    expense_row = next(item for item in report.rows if item.nm_id == 0)
    assert product_row.storage == Decimal("30.00")
    assert product_row.wb_promotion == Decimal("15.00")
    assert product_row.gross_profit == Decimal("545.00")
    assert product_row.data_quality_status is DataQualityStatus.RELIABLE
    assert expense_row.storage == Decimal("0.00")
    assert expense_row.wb_promotion == Decimal("0.00")

    product_allocations = {
        item.expense_category: item
        for item in report.expense_allocation_rows
        if item.nm_id == 101
    }
    assert product_allocations["Хранение"].allocated_amount == Decimal("30.00")
    assert (
        product_allocations["Хранение"].allocation_status
        == "Расход без товара распределен по выручке"
    )
    assert product_allocations["WB Продвижение"].allocated_amount == Decimal("15.00")


def test_storage_and_promotion_use_separate_api_base_when_loaded() -> None:
    snapshot = wb_snapshots()[0].model_copy(
        update={
            "storage": Decimal("20"),
            "wb_promotion": Decimal("10"),
        }
    )
    summary = WbSalesReportSummaryRow(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        account_name="WB_ACCOUNT_1",
        report_id="726807272",
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        create_date=date(2026, 4, 13),
        report_type=1,
        paid_storage_sum="30",
        deduction_sum="15",
        raw_payload_hash="summary-hash-1",
    )
    bases = [
        WbExpenseAllocationBase(
            client_id=CLIENT_ID,
            seller_account_id="WB_ACCOUNT_1",
            week_start=date(2026, 4, 6),
            week_end=date(2026, 4, 12),
            expense_category="Хранение",
            nm_id=101,
            amount="60",
            source_endpoint="paid-storage",
            source_row_count=3,
        ),
        WbExpenseAllocationBase(
            client_id=CLIENT_ID,
            seller_account_id="WB_ACCOUNT_1",
            week_start=date(2026, 4, 6),
            week_end=date(2026, 4, 12),
            expense_category="WB Продвижение",
            nm_id=101,
            amount="100",
            source_endpoint="promotion",
            source_row_count=2,
        ),
    ]

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        wb_sales_report_summary_rows=[summary],
        expense_allocation_bases=bases,
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    row = report.rows[0]
    assert row.storage == Decimal("30.00")
    assert row.wb_promotion == Decimal("15.00")
    allocations = {
        item.expense_category: item for item in report.expense_allocation_rows
    }
    assert allocations["Хранение"].api_base_amount == Decimal("60.00")
    assert allocations["Хранение"].api_total_amount == Decimal("60.00")
    assert allocations["Хранение"].distribution_method == "Доля по отдельному API WB"
    assert (
        allocations["Хранение"].allocation_status
        == "Распределено по отдельному API WB, приведено к фин. отчету WB"
    )
    assert allocations["Хранение"].source_row_count == 3
    assert allocations["WB Продвижение"].api_base_amount == Decimal("100.00")
    assert allocations["WB Продвижение"].allocated_amount == Decimal("15.00")


def test_aggregated_wb_snapshot_preserves_raw_source_row_count() -> None:
    snapshot = wb_snapshots()[0].model_copy(update={"source_row_count": 7})
    daily_facts = []

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
        daily_facts_sink=daily_facts,
    )

    assert report.report_reconciliation_rows[0].source_row_count == 7
    assert report.tax_input_reconciliation_rows[0].source_row_count == 7
    assert daily_facts[0].source_row_count == 7


def test_daily_fact_rebuild_preserves_full_financial_calculation() -> None:
    generated_at = datetime(
        2026,
        6,
        16,
        12,
        0,
        tzinfo=ZoneInfo("Europe/Moscow"),
    )
    daily_facts = []
    source_report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=generated_at,
        as_of_date=date(2026, 6, 16),
        daily_facts_sink=daily_facts,
    )
    rebuilt_report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=_wb_snapshots_from_daily_facts(daily_facts),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=generated_at,
        as_of_date=date(2026, 6, 16),
    )

    def financial_payload(report):
        payload = report.model_dump(mode="json")
        payload.pop("source_coverage_end", None)

        def remove_raw_hashes(value):
            if isinstance(value, dict):
                return {
                    key: remove_raw_hashes(item)
                    for key, item in value.items()
                    if key != "source_snapshot_hashes"
                }
            if isinstance(value, list):
                return [remove_raw_hashes(item) for item in value]
            return value

        return remove_raw_hashes(payload)

    assert financial_payload(rebuilt_report) == financial_payload(source_report)


def test_daily_fact_rebuild_uses_preallocated_financial_values() -> None:
    common = {
        "client_id": CLIENT_ID,
        "seller_account_id": "WB_ACCOUNT_1",
        "organization_id": "1C_ORG_1",
        "marketplace_report_id": "726807272",
        "document_kind": "commissioner_report",
        "sales_model": "fbo",
        "operation_group": "sale",
        "quantity": Decimal("1"),
        "sales_quantity": Decimal("1"),
        "net_revenue": Decimal("100"),
        "vat_input_from_marketplace": Decimal("1"),
        "source_row_count": 1,
        "methodology_version": "test-v1",
    }
    facts = [
        MarketplaceFinanceDailyFact(
            **common,
            fact_date=date(2026, 4, 6),
            nm_id=101,
            vendor_code="A-1",
            barcode="111",
            onec_item_id="ONEC-1",
            storage=Decimal("30"),
            marketplace_promotion=Decimal("20"),
            cogs=Decimal("12.34"),
            gross_profit=Decimal("22.13"),
            vat_input_from_1c=Decimal("3"),
            accounting_service_input_vat=Decimal("2.50"),
            spp_discount=Decimal("25"),
            source_hash_digest="a" * 64,
        ),
        MarketplaceFinanceDailyFact(
            **common,
            fact_date=date(2026, 4, 7),
            nm_id=303,
            vendor_code="AMB-3",
            barcode="333",
            onec_item_id="ONEC-3",
            storage=Decimal("70"),
            marketplace_promotion=Decimal("80"),
            cogs=Decimal("56.78"),
            gross_profit=Decimal("-117.31"),
            vat_input_from_1c=Decimal("7"),
            accounting_service_input_vat=Decimal("7.50"),
            spp_discount=Decimal("75"),
            source_hash_digest="b" * 64,
        ),
    ]
    summary = WbSalesReportSummaryRow(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        account_name="WB_ACCOUNT_1",
        report_id="726807272",
        date_from=date(2026, 4, 6),
        date_to=date(2026, 4, 12),
        create_date=date(2026, 4, 13),
        report_type=1,
        paid_storage_sum=Decimal("100"),
        deduction_sum=Decimal("100"),
        cashback_discount_sum=Decimal("100"),
        raw_payload_hash="summary-hash-preallocated",
    )
    service_row = OnecMarketplaceServiceRow(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        counterparty_id="WB",
        document_id="service-preallocated",
        document_number="1",
        document_date=date(2026, 4, 13),
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 12),
        service_category="Комиссия WB",
        service_name="Комиссия WB",
        amount=Decimal("90"),
        vat=Decimal("10"),
        total=Decimal("100"),
        source_row_hash="service-preallocated-hash",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=_wb_snapshots_from_daily_facts(facts),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        wb_sales_report_summary_rows=[summary],
        onec_marketplace_service_rows=[service_row],
        tax_profiles=[
            TaxProfile(
                client_id=CLIENT_ID,
                organization_id="1C_ORG_1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode=VatMode.INCLUDED,
                vat_deduction_mode=VatDeductionMode.ALLOWED,
                revenue_tax_rate=Decimal("0"),
                source="test",
            )
        ],
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )
    rows = {row.nm_id: row for row in report.rows}

    assert rows[101].storage == Decimal("30.00")
    assert rows[303].storage == Decimal("70.00")
    assert rows[101].wb_promotion == Decimal("20.00")
    assert rows[303].wb_promotion == Decimal("80.00")
    assert rows[101].cogs_from_1c_with_extra_costs == Decimal("12.34")
    assert rows[303].cogs_from_1c_with_extra_costs == Decimal("56.78")
    assert rows[101].vat_input_from_1c == Decimal("3.00")
    assert rows[303].vat_input_from_1c == Decimal("7.00")
    assert rows[101].gross_profit == Decimal("22.13")
    assert rows[303].gross_profit == Decimal("-117.31")
    assert rows[101].spp_discount == Decimal("25.00")
    assert rows[303].spp_discount == Decimal("75.00")


def test_product_level_mapping_matches_size_level_wb_sku() -> None:
    product_mapping = SkuMapping(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        organization_id="1C_ORG_1",
        nm_id=101,
        vendor_code="A-1",
        barcode="",
        onec_item_id="ONEC-1",
        onec_article="A-1",
        match_method="article",
        confidence="1",
        status=MappingStatus.MATCHED,
        updated_by="fixture",
        updated_at=datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=cost_snapshots(),
        sku_mappings=[product_mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].onec_item_id == "ONEC-1"
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("230.00")
    assert report.rows[0].data_quality_status is DataQualityStatus.RELIABLE


def test_missing_week_uses_nearest_available_cost_with_review_status() -> None:
    snapshot = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 5, 20),
            "period_end": date(2026, 5, 20),
        }
    )
    cost = OnecUnfCostSnapshot(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        loaded_at=datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        onec_item_id="ONEC-1",
        article="A-1",
        barcode="111",
        name="Product 1",
        cost_value="100",
        extra_costs_value="15",
        cost_method="sales_register_weighted_average_allocated_extra_costs",
        effective_from=date(2026, 4, 6),
        effective_to=date(2026, 4, 12),
        source_document="AccumulationRegister_Продажи 2026-04-06..2026-04-12",
        raw_payload_hash="cost-hash-previous-week",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[snapshot],
        cost_snapshots=[cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("230.00")
    assert report.rows[0].data_quality_status is DataQualityStatus.NEEDS_REVIEW


def test_zero_cost_for_goods_movement_is_missing_cost() -> None:
    zero_cost = cost_snapshots()[0].model_copy(
        update={
            "cost_value": Decimal("0"),
            "extra_costs_value": Decimal("0"),
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=[zero_cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("0.00")
    assert report.rows[0].data_quality_status is DataQualityStatus.MISSING_COST


def test_zero_effective_cost_uses_nearest_nonzero_cost_with_review() -> None:
    base_cost = cost_snapshots()[0]
    older_nonzero_cost = base_cost.model_copy(
        update={
            "cost_value": Decimal("100"),
            "extra_costs_value": Decimal("15"),
            "effective_from": date(2026, 3, 1),
            "effective_to": date(2026, 3, 31),
            "source_document": "older non-zero 1C cost",
        }
    )
    current_zero_cost = base_cost.model_copy(
        update={
            "cost_value": Decimal("0"),
            "extra_costs_value": Decimal("0"),
            "effective_from": date(2026, 4, 6),
            "effective_to": date(2026, 4, 12),
            "source_document": "current zero 1C cost",
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=[older_nonzero_cost, current_zero_cost],
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("230.00")
    assert report.rows[0].data_quality_status is DataQualityStatus.NEEDS_REVIEW


def test_unique_article_cost_fallback_handles_mapping_item_mismatch() -> None:
    mapping = SkuMapping(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        organization_id="1C_ORG_1",
        nm_id=101,
        vendor_code="A-1",
        barcode="111",
        onec_item_id="ONEC-MAPPING",
        onec_article="A-1",
        match_method="onec_marketplace_mapping_sku",
        confidence="1",
        status=MappingStatus.MATCHED,
        updated_by="fixture",
        updated_at=datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    cost = OnecUnfCostSnapshot(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        loaded_at=datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        onec_item_id="ONEC-COST",
        article="A-1",
        barcode="",
        name="Product 1",
        cost_value="100",
        extra_costs_value="0",
        cost_method="sales_register_weighted_average_allocated_extra_costs",
        effective_from=date(2026, 4, 1),
        effective_to=date(2026, 4, 30),
        source_document="AccumulationRegister_Продажи 2026-04-01..2026-04-30",
        raw_payload_hash="cost-hash-article",
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=[cost],
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].onec_item_id == "ONEC-COST"
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("200.00")
    assert report.rows[0].data_quality_status is DataQualityStatus.NEEDS_REVIEW


def test_ambiguous_article_cost_fallback_is_not_used() -> None:
    mapping = SkuMapping(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        organization_id="1C_ORG_1",
        nm_id=101,
        vendor_code="A-1",
        barcode="111",
        onec_item_id="ONEC-MAPPING",
        onec_article="A-1",
        match_method="onec_marketplace_mapping_sku",
        confidence="1",
        status=MappingStatus.MATCHED,
        updated_by="fixture",
        updated_at=datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    costs = [
        OnecUnfCostSnapshot(
            client_id=CLIENT_ID,
            organization_id="1C_ORG_1",
            loaded_at=datetime(2026, 6, 16, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
            onec_item_id=onec_item_id,
            article="A-1",
            barcode="",
            name="Product 1",
            cost_value="100",
            extra_costs_value="0",
            cost_method="sales_register_weighted_average_allocated_extra_costs",
            effective_from=date(2026, 4, 1),
            effective_to=date(2026, 4, 30),
            source_document="AccumulationRegister_Продажи 2026-04-01..2026-04-30",
            raw_payload_hash=f"cost-hash-{onec_item_id}",
        )
        for onec_item_id in ("ONEC-COST-1", "ONEC-COST-2")
    ]

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=costs,
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].onec_item_id == "ONEC-MAPPING"
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("0.00")
    assert report.rows[0].data_quality_status is DataQualityStatus.MISSING_COST


def test_partial_source_does_not_hide_missing_mapping() -> None:
    partial_snapshot = wb_snapshots()[0].model_copy(update={"is_partial_source": True})
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[partial_snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=[],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].data_quality_status is DataQualityStatus.MISSING_MAPPING


def test_partial_source_remains_visible_for_otherwise_complete_rows() -> None:
    partial_snapshot = wb_snapshots()[0].model_copy(update={"is_partial_source": True})
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[partial_snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].data_quality_status is DataQualityStatus.PARTIAL_SOURCE


def test_returns_follow_wb_finance_period_and_keep_negative_quantity() -> None:
    row = next(item for item in build_report().rows if item.nm_id == 202)
    assert row.sales_model is SalesModel.FBS
    assert row.quantity == Decimal("-1")
    assert row.week_start == date(2026, 4, 13)
    assert row.cogs_from_1c_with_extra_costs == Decimal("-225.00")
    assert row.gross_profit == Decimal("-248.00")
    assert row.vat_5_from_revenue == Decimal("-23.81")
    assert row.usn_1_from_revenue == Decimal("-5.00")
    assert row.profit_after_taxes == Decimal("-219.19")


def test_expense_reimbursement_quantity_does_not_create_cogs() -> None:
    expense_snapshot = wb_snapshots()[0].model_copy(
        update={
            "wb_document_id": "expense-1",
            "operation_type": (
                "Возмещение издержек по перевозке/по складским операциям с товаром"
            ),
            "quantity": Decimal("100"),
            "net_revenue": Decimal("0"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("12"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("0"),
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[expense_snapshot],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    assert report.rows[0].quantity == Decimal("0")
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("0.00")
    assert report.rows[0].gross_profit == Decimal("-12.00")


def test_onec_report_packages_split_commissioner_report_and_buyout() -> None:
    base_sale = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 5, 24),
            "period_end": date(2026, 5, 24),
            "wb_report_id": "439356720260524",
            "net_revenue": Decimal("914576"),
            "quantity": Decimal("10"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("0"),
        }
    )
    buyout_sale = wb_snapshots()[0].model_copy(
        update={
            "wb_document_id": "buyout-doc",
            "period_start": date(2026, 5, 24),
            "period_end": date(2026, 5, 24),
            "wb_report_id": "4393567202605241",
            "net_revenue": Decimal("55761.75"),
            "quantity": Decimal("3"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("0"),
            "raw_payload_hash": "wb-hash-buyout",
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[base_sale, buyout_sale],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    rows_by_kind = {
        row.document_label: row for row in report.onec_report_reconciliation_rows
    }
    assert rows_by_kind["Отчет комиссионера"].document_date == date(2026, 5, 24)
    assert rows_by_kind["Отчет комиссионера"].week_start == date(2026, 5, 18)
    assert rows_by_kind["Отчет комиссионера"].week_end == date(2026, 5, 24)
    assert rows_by_kind["Отчет комиссионера"].sales_amount == Decimal("914576.00")
    assert rows_by_kind["Отчет комиссионера"].wb_report_ids == ("439356720260524",)
    assert rows_by_kind["Уведомление о выкупе"].document_date == date(2026, 5, 25)
    assert rows_by_kind["Уведомление о выкупе"].sales_amount == Decimal("55761.75")
    assert rows_by_kind["Уведомление о выкупе"].wb_report_ids == ("4393567202605241",)

    product_rows_by_kind = {
        row.document_label: row for row in report.onec_report_product_rows
    }
    assert product_rows_by_kind["Отчет комиссионера"].nm_id == 101
    assert product_rows_by_kind["Уведомление о выкупе"].nm_id == 101


def test_explicit_report_type_prevents_mixed_commissioner_and_buyout_packages() -> None:
    base_sale = wb_snapshots()[0].model_copy(
        update={
            "period_start": date(2026, 4, 6),
            "period_end": date(2026, 4, 6),
            # Deliberately looks like the legacy buyout suffix. reportType wins.
            "wb_report_id": "535699202604061",
            "report_type": 1,
            "quantity": Decimal("10"),
            "net_revenue": Decimal("1000"),
        }
    )
    buyout_sale = wb_snapshots()[0].model_copy(
        update={
            "wb_document_id": "daily-buyout-doc",
            "period_start": date(2026, 4, 6),
            "period_end": date(2026, 4, 6),
            # Deliberately lacks the legacy buyout suffix. reportType wins.
            "wb_report_id": "53569920260406",
            "report_type": 2,
            "quantity": Decimal("3"),
            "net_revenue": Decimal("300"),
            "raw_payload_hash": "daily-buyout-hash",
        }
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[base_sale, buyout_sale],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )

    rows_by_kind = {
        row.document_label: row for row in report.onec_report_reconciliation_rows
    }
    assert rows_by_kind["Отчет комиссионера"].sales_quantity == Decimal("10")
    assert rows_by_kind["Отчет комиссионера"].wb_report_ids == ("535699202604061",)
    assert rows_by_kind["Уведомление о выкупе"].sales_quantity == Decimal("3")
    assert rows_by_kind["Уведомление о выкупе"].wb_report_ids == ("53569920260406",)

    unit_rows_by_document = {row.document_report: row for row in report.rows}
    assert len(unit_rows_by_document) == 2
    assert unit_rows_by_document[
        "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
    ].sales_quantity == Decimal("10")
    assert unit_rows_by_document[
        "Уведомление о выкупе · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
    ].sales_quantity == Decimal("3")


def test_data_quality_statuses_cover_ambiguous_and_account_org_mismatch() -> None:
    rows = {item.nm_id: item for item in build_report().rows}
    assert rows[303].data_quality_status is DataQualityStatus.AMBIGUOUS_MAPPING
    assert rows[404].data_quality_status is DataQualityStatus.ACCOUNT_ORG_MISMATCH


def test_partial_week_is_visible_for_q2_boundary() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[
            wb_snapshots()[0].model_copy(update={"period_start": date(2026, 4, 1)})
        ],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 6, 17),
    )
    assert report.rows[0].is_partial_week is True


def test_april_report_excludes_week_closing_in_may() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[
            wb_snapshots()[0].model_copy(
                update={
                    "period_start": date(2026, 4, 27),
                    "period_end": date(2026, 4, 27),
                }
            )
        ],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 5, 4, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 5, 4),
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 4, 30),
    )

    assert report.rows == []
    assert report.onec_report_reconciliation_rows == []


def test_april_report_includes_march_days_from_week_closing_in_april() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[
            wb_snapshots()[0].model_copy(
                update={
                    "period_start": date(2026, 3, 30),
                    "period_end": date(2026, 3, 30),
                }
            )
        ],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 5, 4, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 5, 4),
        report_period_start=date(2026, 4, 1),
        report_period_end=date(2026, 4, 30),
    )

    assert report.rows[0].document_report.endswith("закрытие 05.04.2026")
    assert report.onec_report_reconciliation_rows[0].document_date == date(2026, 4, 5)


def test_custom_report_period_controls_status_and_partial_weeks() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[
            wb_snapshots()[0].model_copy(update={"period_start": date(2026, 3, 1)})
        ],
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 18, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 18),
        report_period_start=date(2026, 3, 1),
        report_period_end=date(2026, 6, 17),
    )

    assert report.report_period_start == date(2026, 3, 1)
    assert report.report_period_end == date(2026, 6, 17)
    assert report.status is ReportStatus.FINAL
    assert report.rows[0].is_partial_week is True


def test_daily_fact_money_cents_reconcile_to_weekly_report_grain() -> None:
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for fact_date in (date(2026, 3, 2), date(2026, 3, 3)):
        key = (
            CLIENT_ID,
            "seller-1",
            "organization-1",
            fact_date,
            "report-1",
            "commissioner_report",
            123,
            "vendor-1",
            "barcode-1",
            "onec-item-1",
            "fbo",
            "sale",
        )
        grouped[key] = {
            "sales_quantity": Decimal("1"),
            "return_quantity": Decimal("0"),
            "quantity": Decimal("1"),
            "return_amount": Decimal("0"),
            "net_revenue": Decimal("10"),
            "wb_commission": Decimal("0"),
            "logistics": Decimal("0"),
            "storage": Decimal("0"),
            "acceptance": Decimal("0"),
            "marketplace_promotion": Decimal("0"),
            "penalties_and_holdbacks": Decimal("0"),
            "acquiring": Decimal("0"),
            "cogs": Decimal("1.005"),
            "gross_profit": Decimal("2.005"),
            "vat_input_from_marketplace": Decimal("0"),
            "vat_input_from_1c": Decimal("0"),
            "source_row_count": 1,
            "hashes": [f"hash-{fact_date.isoformat()}"],
            "is_partial_source": False,
        }

    facts = _marketplace_finance_daily_facts(
        grouped,
        methodology_version="test-v1",
    )

    assert [fact.cogs for fact in facts] == [Decimal("1.00"), Decimal("1.01")]
    assert sum((fact.cogs for fact in facts), Decimal("0")) == Decimal("2.01")
    assert [fact.gross_profit for fact in facts] == [
        Decimal("2.00"),
        Decimal("2.01"),
    ]
    assert sum((fact.gross_profit for fact in facts), Decimal("0")) == Decimal("4.01")


def test_daily_fact_cogs_uses_final_report_control_when_decimal_order_differs() -> None:
    base = wb_snapshots()[0]
    first_day = date(2026, 3, 2)
    second_day = date(2026, 3, 3)
    large = Decimal("10000000000000000000000000")
    values = (
        (large, first_day),
        (Decimal("0.005"), second_day),
        (-large, first_day),
    )
    snapshots = [
        base.model_copy(
            update={
                "period_start": fact_date,
                "period_end": fact_date,
                "preallocated_finance": True,
                "precomputed_cogs": cogs,
                "precomputed_gross_profit": Decimal("0"),
                "precomputed_vat_input_from_1c": Decimal("0"),
                "precomputed_accounting_service_input_vat": Decimal("0"),
                "precomputed_spp_discount": Decimal("0"),
                "raw_payload_hash": f"decimal-order-{index}",
            }
        )
        for index, (cogs, fact_date) in enumerate(values)
    ]
    daily_facts = []

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=snapshots,
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 3, 9, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 3, 9),
        daily_facts_sink=daily_facts,
    )

    report_cogs = sum(
        (row.cogs_from_1c_with_extra_costs for row in report.rows),
        Decimal("0"),
    )
    daily_cogs = sum((fact.cogs for fact in daily_facts), Decimal("0"))
    assert report_cogs == Decimal("0.00")
    assert daily_cogs == report_cogs
