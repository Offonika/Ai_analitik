from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from wb_unit_economics.calculation import (
    METHODOLOGY_VERSION,
    VAT_INPUT_CONFIRMED,
    calculate_management_waterfall,
    calculate_tax_amounts,
    money,
    ratio,
    tax_profile_is_confirmed,
)
from wb_unit_economics.contracts import TaxProfile

TARGET_MARGIN_TOLERANCE = Decimal("0.0001")
MIN_PRICE = Decimal("0.01")
MAX_PRICE = Decimal("100000000")
MAX_BISECTION_STEPS = 96
MAX_EXPANSION_STEPS = 64


@dataclass(frozen=True)
class MarginScenarioInputs:
    price_before_spp: Decimal
    spp_rate: Decimal
    unit_cost: Decimal
    commission_rate: Decimal
    acquiring_rate: Decimal
    logistics_per_unit: Decimal
    storage_per_unit: Decimal
    acceptance_per_unit: Decimal
    promotion_per_unit: Decimal
    penalties_per_unit: Decimal


@dataclass(frozen=True)
class MarginScenarioResult:
    price_before_spp: Decimal
    spp_rate: Decimal
    price_after_spp: Decimal
    pnl_revenue: Decimal
    revenue_without_vat: Decimal
    unit_cost: Decimal
    commission: Decimal
    logistics: Decimal
    storage: Decimal
    acceptance: Decimal
    promotion: Decimal
    penalties: Decimal
    acquiring: Decimal
    service_input_vat: Decimal
    profit_before_tax: Decimal
    margin: Decimal | None
    vat_output: Decimal | None
    vat_input: Decimal | None
    vat_payable: Decimal | None
    revenue_tax: Decimal | None
    income_tax: Decimal | None
    profit_after_taxes: Decimal | None
    margin_after_taxes: Decimal | None
    tax_status: str
    tax_completeness: str
    tax_method: str
    pnl_vat_mode: str
    methodology_version: str = METHODOLOGY_VERSION


@dataclass(frozen=True)
class TargetPriceSolution:
    status: str
    price: Decimal | None
    result: MarginScenarioResult | None


def validate_scenario_inputs(inputs: MarginScenarioInputs) -> None:
    if inputs.price_before_spp <= 0:
        raise ValueError("price_before_spp must be positive")
    if inputs.spp_rate < 0 or inputs.spp_rate >= 1:
        raise ValueError("spp_rate must be in range [0, 1)")
    if inputs.unit_cost < 0:
        raise ValueError("unit_cost must be non-negative")
    for name, value in (
        ("commission_rate", inputs.commission_rate),
        ("acquiring_rate", inputs.acquiring_rate),
    ):
        if value < 0 or value >= 1:
            raise ValueError(f"{name} must be in range [0, 1)")
    for name, value in (
        ("logistics_per_unit", inputs.logistics_per_unit),
        ("storage_per_unit", inputs.storage_per_unit),
        ("acceptance_per_unit", inputs.acceptance_per_unit),
        ("promotion_per_unit", inputs.promotion_per_unit),
        ("penalties_per_unit", inputs.penalties_per_unit),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")


def calculate_margin_scenario(
    inputs: MarginScenarioInputs,
    *,
    tax_profile: TaxProfile | None,
    product_input_vat_per_unit: Decimal = Decimal("0"),
    vat_input_available: bool = True,
    vat_input_completeness: str = VAT_INPUT_CONFIRMED,
    methodology_version: str = METHODOLOGY_VERSION,
) -> MarginScenarioResult:
    validate_scenario_inputs(inputs)
    price_before_spp = money(inputs.price_before_spp)
    price_after_spp = money(price_before_spp * (Decimal("1") - inputs.spp_rate))
    commission = money(price_after_spp * inputs.commission_rate)
    acquiring = money(price_after_spp * inputs.acquiring_rate)
    effective_profile = (
        tax_profile
        if tax_profile is not None and tax_profile_is_confirmed(tax_profile)
        else None
    )
    waterfall = calculate_management_waterfall(
        revenue_after_spp=price_after_spp,
        cogs=money(inputs.unit_cost),
        commission=commission,
        logistics=money(inputs.logistics_per_unit),
        storage=money(inputs.storage_per_unit),
        acceptance=money(inputs.acceptance_per_unit),
        promotion=money(inputs.promotion_per_unit),
        penalties=money(inputs.penalties_per_unit),
        acquiring=acquiring,
        tax_profile=effective_profile,
    )
    profit_before_tax = money(waterfall.profit_before_tax)
    service_input_vat = money(waterfall.service_input_vat_for_pnl)
    vat_input = money(product_input_vat_per_unit + service_input_vat)
    tax = calculate_tax_amounts(
        price_after_spp,
        profit_before_tax,
        effective_profile,
        vat_input=vat_input,
        vat_input_available=vat_input_available,
        vat_input_completeness=vat_input_completeness,
        profile_required=True,
    )
    margin_value = ratio(profit_before_tax, waterfall.pnl_revenue)
    tax_ready = effective_profile is not None
    profit_after_taxes = money(tax.profit_after_taxes) if tax_ready else None
    margin_after_taxes = (
        ratio(profit_after_taxes, waterfall.pnl_revenue)
        if profit_after_taxes is not None
        else None
    )
    tax_status = (
        "missing"
        if not tax_ready
        else (
            "ready"
            if tax.tax_completeness == "profile_complete"
            else "review"
        )
    )
    return MarginScenarioResult(
        price_before_spp=price_before_spp,
        spp_rate=inputs.spp_rate,
        price_after_spp=price_after_spp,
        pnl_revenue=money(waterfall.pnl_revenue),
        revenue_without_vat=money(waterfall.revenue_without_vat),
        unit_cost=money(inputs.unit_cost),
        commission=commission,
        logistics=money(inputs.logistics_per_unit),
        storage=money(inputs.storage_per_unit),
        acceptance=money(inputs.acceptance_per_unit),
        promotion=money(inputs.promotion_per_unit),
        penalties=money(inputs.penalties_per_unit),
        acquiring=acquiring,
        service_input_vat=service_input_vat,
        profit_before_tax=profit_before_tax,
        margin=margin_value,
        vat_output=money(tax.vat_output) if tax_ready else None,
        vat_input=money(tax.vat_input) if tax_ready else None,
        vat_payable=money(tax.vat_payable) if tax_ready else None,
        revenue_tax=money(tax.revenue_tax) if tax_ready else None,
        income_tax=money(tax.income_tax) if tax_ready else None,
        profit_after_taxes=profit_after_taxes,
        margin_after_taxes=margin_after_taxes,
        tax_status=tax_status,
        tax_completeness=tax.tax_completeness,
        tax_method=tax.tax_method,
        pnl_vat_mode=tax.pnl_vat_mode,
        methodology_version=methodology_version,
    )


def solve_price_for_margin(
    template: MarginScenarioInputs,
    target_margin: Decimal,
    *,
    tax_profile: TaxProfile | None,
    product_input_vat_per_unit: Decimal = Decimal("0"),
    vat_input_available: bool = True,
    vat_input_completeness: str = VAT_INPUT_CONFIRMED,
    methodology_version: str = METHODOLOGY_VERSION,
) -> TargetPriceSolution:
    if target_margin <= Decimal("-0.99") or target_margin >= Decimal("0.99"):
        raise ValueError("target_margin must be in range (-0.99, 0.99)")
    validate_scenario_inputs(template)

    def calculate(price: Decimal) -> MarginScenarioResult:
        return calculate_margin_scenario(
            replace(template, price_before_spp=price),
            tax_profile=tax_profile,
            product_input_vat_per_unit=product_input_vat_per_unit,
            vat_input_available=vat_input_available,
            vat_input_completeness=vat_input_completeness,
            methodology_version=methodology_version,
        )

    def objective(result: MarginScenarioResult) -> Decimal | None:
        return result.margin - target_margin if result.margin is not None else None

    lower = MIN_PRICE
    lower_result = calculate(lower)
    lower_objective = objective(lower_result)
    for _step in range(MAX_EXPANSION_STEPS):
        if lower_objective is not None:
            break
        if lower >= MAX_PRICE:
            return TargetPriceSolution("unattainable", None, None)
        lower = min(money(lower * Decimal("2")), MAX_PRICE)
        lower_result = calculate(lower)
        lower_objective = objective(lower_result)
    if lower_objective is None:
        return TargetPriceSolution("unattainable", None, None)
    if abs(lower_objective) <= TARGET_MARGIN_TOLERANCE:
        return TargetPriceSolution("ready", lower, lower_result)

    upper = max(money(template.price_before_spp), lower, Decimal("1"))
    upper_result = calculate(upper)
    upper_objective = objective(upper_result)
    for _step in range(MAX_EXPANSION_STEPS):
        if upper_objective is not None and upper_objective >= 0:
            break
        if upper >= MAX_PRICE:
            return TargetPriceSolution("unattainable", None, None)
        upper = min(upper * Decimal("2"), MAX_PRICE)
        upper_result = calculate(upper)
        upper_objective = objective(upper_result)
    if (
        upper_objective is None
        or upper_objective < 0
        or lower_objective > 0
    ):
        return TargetPriceSolution("unattainable", None, None)

    for _step in range(MAX_BISECTION_STEPS):
        midpoint = (lower + upper) / Decimal("2")
        midpoint_result = calculate(midpoint)
        midpoint_objective = objective(midpoint_result)
        if midpoint_objective is None:
            return TargetPriceSolution("unattainable", None, None)
        if midpoint_objective < 0:
            lower = midpoint
        else:
            upper = midpoint
        if upper - lower <= Decimal("0.000001"):
            break

    candidate_prices = {
        candidate
        for candidate in (money(lower), money(upper), money((lower + upper) / 2))
        if candidate > 0
    }
    candidates = [(candidate, calculate(candidate)) for candidate in candidate_prices]
    candidates = [item for item in candidates if item[1].margin is not None]
    if not candidates:
        return TargetPriceSolution("unattainable", None, None)
    price, result = min(
        candidates,
        key=lambda item: abs((item[1].margin or Decimal("0")) - target_margin),
    )
    if (
        result.margin is None
        or abs(result.margin - target_margin) > TARGET_MARGIN_TOLERANCE
    ):
        return TargetPriceSolution("unattainable", None, None)
    return TargetPriceSolution("ready", price, result)


def margin_scenario_payload(result: MarginScenarioResult) -> dict[str, object]:
    def value(item: Decimal | None) -> float | None:
        return float(item) if item is not None else None

    return {
        "priceBeforeSpp": value(result.price_before_spp),
        "sppRate": value(result.spp_rate),
        "priceAfterSpp": value(result.price_after_spp),
        "pnlRevenue": value(result.pnl_revenue),
        "revenueWithoutVat": value(result.revenue_without_vat),
        "unitCost": value(result.unit_cost),
        "commission": value(result.commission),
        "logistics": value(result.logistics),
        "storage": value(result.storage),
        "acceptance": value(result.acceptance),
        "promotion": value(result.promotion),
        "penalties": value(result.penalties),
        "acquiring": value(result.acquiring),
        "serviceInputVat": value(result.service_input_vat),
        "profitBeforeTax": value(result.profit_before_tax),
        "margin": value(result.margin),
        "vatOutput": value(result.vat_output),
        "vatInput": value(result.vat_input),
        "vatPayable": value(result.vat_payable),
        "revenueTax": value(result.revenue_tax),
        "incomeTax": value(result.income_tax),
        "profitAfterTaxes": value(result.profit_after_taxes),
        "marginAfterTaxes": value(result.margin_after_taxes),
        "taxStatus": result.tax_status,
        "taxCompleteness": result.tax_completeness,
        "taxMethod": result.tax_method,
        "pnlVatMode": result.pnl_vat_mode,
        "methodologyVersion": result.methodology_version,
    }
