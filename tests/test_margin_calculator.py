from decimal import Decimal

from wb_unit_economics.contracts import (
    TaxProfile,
    VatDeductionMode,
    VatMode,
)
from wb_unit_economics.margin_calculator import (
    MarginScenarioInputs,
    calculate_margin_scenario,
    solve_price_for_margin,
)


def _inputs(**updates: Decimal) -> MarginScenarioInputs:
    values = {
        "price_before_spp": Decimal("1000"),
        "spp_rate": Decimal("0.10"),
        "unit_cost": Decimal("300"),
        "commission_rate": Decimal("0.15"),
        "acquiring_rate": Decimal("0.02"),
        "logistics_per_unit": Decimal("50"),
        "storage_per_unit": Decimal("10"),
        "acceptance_per_unit": Decimal("5"),
        "promotion_per_unit": Decimal("20"),
        "penalties_per_unit": Decimal("2"),
    }
    values.update(updates)
    return MarginScenarioInputs(**values)


def _usn_profile() -> TaxProfile:
    return TaxProfile(
        client_id="client-test",
        organization_id="org-test",
        tax_system="УСН доходы",
        tax_object="income",
        tax_rate=Decimal("0.06"),
        vat_rate=Decimal("0"),
        vat_mode=VatMode.NONE,
        vat_deduction_mode=VatDeductionMode.NOT_APPLICABLE,
        revenue_tax_rate=Decimal("0.06"),
        source="1C:test",
    )


def _osno_profile() -> TaxProfile:
    return TaxProfile(
        client_id="client-test",
        organization_id="org-test",
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        source="1C:test",
    )


def test_scenario_uses_price_after_spp_and_fixed_unit_expenses() -> None:
    result = calculate_margin_scenario(
        _inputs(),
        tax_profile=_usn_profile(),
    )

    assert result.price_after_spp == Decimal("900.00")
    assert result.commission == Decimal("135.00")
    assert result.acquiring == Decimal("18.00")
    assert result.profit_before_tax == Decimal("360.00")
    assert result.margin == Decimal("0.4000")
    assert result.revenue_tax == Decimal("54.00")
    assert result.profit_after_taxes == Decimal("306.00")


def test_osno_waterfall_uses_22_122_service_vat() -> None:
    result = calculate_margin_scenario(
        _inputs(
            price_before_spp=Decimal("1220"),
            spp_rate=Decimal("0"),
            unit_cost=Decimal("500"),
            commission_rate=Decimal("0.10"),
            acquiring_rate=Decimal("0"),
            logistics_per_unit=Decimal("122"),
            storage_per_unit=Decimal("0"),
            acceptance_per_unit=Decimal("0"),
            promotion_per_unit=Decimal("0"),
            penalties_per_unit=Decimal("0"),
        ),
        tax_profile=_osno_profile(),
        product_input_vat_per_unit=Decimal("100"),
    )

    assert result.revenue_without_vat == Decimal("1000.00")
    assert result.service_input_vat == Decimal("44.00")
    assert result.profit_before_tax == Decimal("300.00")
    assert result.vat_output == Decimal("220.00")
    assert result.vat_input == Decimal("144.00")
    assert result.vat_payable == Decimal("76.00")
    assert result.tax_status == "review"


def test_target_price_solver_reaches_margin_within_one_basis_point() -> None:
    solution = solve_price_for_margin(
        _inputs(),
        Decimal("0.25"),
        tax_profile=_usn_profile(),
    )

    assert solution.status == "ready"
    assert solution.price is not None
    assert solution.result is not None
    assert solution.result.margin is not None
    assert abs(solution.result.margin - Decimal("0.25")) <= Decimal("0.0001")


def test_target_price_solver_returns_unattainable_without_inventing_price() -> None:
    solution = solve_price_for_margin(
        _inputs(
            unit_cost=Decimal("0"),
            commission_rate=Decimal("0.20"),
            acquiring_rate=Decimal("0"),
            logistics_per_unit=Decimal("0"),
            storage_per_unit=Decimal("0"),
            acceptance_per_unit=Decimal("0"),
            promotion_per_unit=Decimal("0"),
            penalties_per_unit=Decimal("0"),
        ),
        Decimal("0.90"),
        tax_profile=_usn_profile(),
    )

    assert solution.status == "unattainable"
    assert solution.price is None
    assert solution.result is None


def test_target_price_solver_handles_high_spp_with_rounded_low_price() -> None:
    solution = solve_price_for_margin(
        _inputs(spp_rate=Decimal("0.9899")),
        Decimal("0.25"),
        tax_profile=_usn_profile(),
    )

    assert solution.status == "ready"
    assert solution.result is not None
    assert solution.result.margin is not None
    assert abs(solution.result.margin - Decimal("0.25")) <= Decimal("0.0001")


def test_missing_tax_profile_keeps_management_margin_and_nulls_after_tax() -> None:
    result = calculate_margin_scenario(
        _inputs(),
        tax_profile=None,
    )

    assert result.profit_before_tax == Decimal("360.00")
    assert result.margin == Decimal("0.4000")
    assert result.tax_status == "missing"
    assert result.profit_after_taxes is None
    assert result.margin_after_taxes is None
