from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from wb_unit_economics.contracts import (
    AccountOrgMapping,
    DataQualityStatus,
    ExpenseAllocationRow,
    MappingStatus,
    OnecMarketplaceServiceRow,
    OnecReportKind,
    OnecReportProductRow,
    OnecReportReconciliationRow,
    OnecUnfCostSnapshot,
    ReportReconciliationRow,
    ReportStatus,
    SkuMapping,
    TaxInputReconciliationRow,
    TaxProfile,
    UnitEconomicsReport,
    UnitEconomicsRow,
    VatDeductionMode,
    VatMode,
    WbApiSnapshot,
    WbExpenseAllocationBase,
    WbSalesReportSummaryRow,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_REPORT_PERIOD_START = date(2026, 3, 1)
DEFAULT_REPORT_PERIOD_END = date(2026, 6, 17)
METHODOLOGY_VERSION = "excel-mvp-q2-2026-v6-osno-reconciled"
GOODS_MOVEMENT_OPERATIONS = {"sale", "sales", "продажа", "return", "возврат"}
VAT_5_INCLUDED_RATIO = Decimal("5") / Decimal("105")
USN_1_REVENUE_RATE = Decimal("0.01")
TAX_METHOD = "legacy: НДС внутри цены 5/105; налог с выручки 1%"
MISSING_TAX_PROFILE_METHOD = "Налоговый профиль не найден"
IP_NDFL_PROGRESSIVE_KIND = "ip_ndfl_progressive"
VAT_INPUT_CONFIRMED = "confirmed"
VAT_INPUT_PARTIAL = "partial"
VAT_INPUT_MISSING = "missing"
VAT_INPUT_MISMATCH = "mismatch"
VAT_INPUT_DIFF_TOLERANCE = Decimal("1.00")
VAT_INPUT_SERVICE_RATE = Decimal("22")
VAT_INPUT_SERVICE_INCLUDED_RATIO = VAT_INPUT_SERVICE_RATE / (
    Decimal("100") + VAT_INPUT_SERVICE_RATE
)
VAT_INPUT_COMMISSION_LOGISTICS_GROUP = "Комиссия WB + Логистика"
PNL_VAT_MODE_LEGACY = "legacy_tax_layer"
PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO = "without_vat_for_osno"

STATUS_PRIORITY = {
    DataQualityStatus.ACCOUNT_ORG_MISMATCH: 90,
    DataQualityStatus.PARTIAL_SOURCE: 80,
    DataQualityStatus.EXPENSE_WITHOUT_SKU: 70,
    DataQualityStatus.MISSING_MAPPING: 60,
    DataQualityStatus.AMBIGUOUS_MAPPING: 50,
    DataQualityStatus.MISSING_COST: 40,
    DataQualityStatus.WB_DOCUMENT_MISSING: 35,
    DataQualityStatus.EXCLUDED: 30,
    DataQualityStatus.PAYOUT_SOURCE_MISSING: 25,
    DataQualityStatus.OPIU_PILOT_DEFAULTS: 25,
    DataQualityStatus.REPORT_TYPE_FALLBACK: 22,
    DataQualityStatus.TAX_PROFILE_MISSING: 21,
    DataQualityStatus.TAX_REVIEW: 21,
    DataQualityStatus.NEEDS_REVIEW: 20,
    DataQualityStatus.WB_DOCUMENT_DOWNLOADED: 5,
    DataQualityStatus.RELIABLE: 0,
}

EXPENSE_STORAGE = "Хранение"
EXPENSE_WB_PROMOTION = "WB Продвижение"
CONTROLLED_EXPENSES = (EXPENSE_STORAGE, EXPENSE_WB_PROMOTION)
ALLOCATION_STATUS_BY_DETAIL = "Распределено по API, приведено к фин. отчету WB"
ALLOCATION_STATUS_BY_EXPENSE_API = (
    "Распределено по отдельному API WB, приведено к фин. отчету WB"
)
ALLOCATION_STATUS_BY_REVENUE = "Нет базы API, распределено по выручке, нужна проверка"
ALLOCATION_STATUS_BY_EQUAL_SHARE = (
    "Нет базы API и выручки, распределено поровну, нужна проверка"
)
ALLOCATION_STATUS_NO_SKU_BY_DETAIL = (
    "Расход без товара распределен по товарной детализации"
)
ALLOCATION_STATUS_NO_SKU_BY_REVENUE = "Расход без товара распределен по выручке"
ALLOCATION_STATUS_NO_SKU_BY_EQUAL_SHARE = (
    "Расход без товара распределен поровну, нужна проверка"
)
ALLOCATION_STATUS_NO_EXPENSE = "Расход отсутствует в недельном отчете WB"
ALLOCATION_STATUS_NO_CONTROL = "Нет недельного фин. отчета WB, взята детализация"


@dataclass(frozen=True)
class _CategoryAllocation:
    allocated: Decimal
    api_base_amount: Decimal
    distribution_base_amount: Decimal
    api_total_amount: Decimal
    control_amount: Decimal | None
    scaling_coefficient: Decimal | None
    distribution_method: str
    allocation_status: str
    wb_report_ids: tuple[str, ...]
    source_row_count: int = 1


@dataclass(frozen=True)
class _ControlledExpenses:
    storage: _CategoryAllocation
    wb_promotion: _CategoryAllocation


@dataclass(frozen=True)
class _VatInputAllocation:
    from_wb: Decimal
    from_1c: Decimal
    completeness: str


@dataclass(frozen=True)
class _SppAllocation:
    discount: Decimal
    control_amount: Decimal | None
    distribution_method: str
    source_status: str


@dataclass(frozen=True)
class _CostIndex:
    by_item: dict[tuple[str, str, str, str], list[OnecUnfCostSnapshot]]
    by_article: dict[tuple[str, str, str], list[OnecUnfCostSnapshot]]


@dataclass(frozen=True)
class TaxCalculation:
    revenue_without_vat: Decimal
    vat: Decimal
    vat_output: Decimal
    vat_input: Decimal
    vat_payable: Decimal
    revenue_tax: Decimal
    income_tax_kind: str
    income_tax_base: Decimal
    income_tax: Decimal
    income_tax_included: bool
    tax_completeness: str
    profit_after_taxes: Decimal
    tax_method: str
    tax_profile_source: str
    pnl_vat_mode: str
    data_quality_status: DataQualityStatus


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return (numerator / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _worse_vat_input_completeness(current: str, candidate: str) -> str:
    priority = {
        VAT_INPUT_MISMATCH: 30,
        VAT_INPUT_PARTIAL: 20,
        VAT_INPUT_MISSING: 10,
        VAT_INPUT_CONFIRMED: 0,
    }
    current_key = current if current in priority else VAT_INPUT_CONFIRMED
    candidate_key = candidate if candidate in priority else VAT_INPUT_CONFIRMED
    return (
        candidate_key
        if priority[candidate_key] > priority[current_key]
        else current_key
    )


def _merge_vat_input_completeness(
    service_completeness: str,
    *,
    cost_input_vat_available: bool,
    cost_input_vat_missing: bool,
    service_input_vat_missing: bool = False,
) -> str:
    completeness = service_completeness.strip().lower() or VAT_INPUT_CONFIRMED
    if service_input_vat_missing:
        completeness = _worse_vat_input_completeness(completeness, VAT_INPUT_PARTIAL)
    elif completeness == VAT_INPUT_MISSING and cost_input_vat_available:
        completeness = VAT_INPUT_CONFIRMED
    if cost_input_vat_missing:
        return _worse_vat_input_completeness(completeness, VAT_INPUT_PARTIAL)
    return completeness


def tax_amounts_from_revenue(net_revenue: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    vat = money(net_revenue * VAT_5_INCLUDED_RATIO)
    usn = money(net_revenue * USN_1_REVENUE_RATE)
    revenue_without_vat = money(net_revenue - vat)
    return revenue_without_vat, vat, usn


def calculate_tax_amounts(
    net_revenue: Decimal,
    gross_profit: Decimal,
    tax_profile: TaxProfile | None = None,
    *,
    vat_input: Decimal = Decimal("0"),
    vat_input_available: bool = False,
    vat_input_completeness: str = VAT_INPUT_CONFIRMED,
    profile_required: bool = False,
) -> TaxCalculation:
    if tax_profile is not None and not tax_profile_is_confirmed(tax_profile):
        tax_profile = None
        profile_required = True
    if tax_profile is None:
        if profile_required:
            return TaxCalculation(
                revenue_without_vat=net_revenue,
                vat=Decimal("0"),
                vat_output=Decimal("0"),
                vat_input=Decimal("0"),
                vat_payable=Decimal("0"),
                revenue_tax=Decimal("0"),
                income_tax_kind="",
                income_tax_base=Decimal("0"),
                income_tax=Decimal("0"),
                income_tax_included=False,
                tax_completeness="missing_tax_profile",
                profit_after_taxes=gross_profit,
                tax_method=MISSING_TAX_PROFILE_METHOD,
                tax_profile_source="missing",
                pnl_vat_mode=PNL_VAT_MODE_LEGACY,
                data_quality_status=DataQualityStatus.TAX_PROFILE_MISSING,
            )
        revenue_without_vat, vat, revenue_tax = tax_amounts_from_revenue(net_revenue)
        return TaxCalculation(
            revenue_without_vat=revenue_without_vat,
            vat=vat,
            vat_output=vat,
            vat_input=Decimal("0"),
            vat_payable=vat,
            revenue_tax=revenue_tax,
            income_tax_kind="",
            income_tax_base=Decimal("0"),
            income_tax=Decimal("0"),
            income_tax_included=False,
            tax_completeness="legacy_complete",
            profit_after_taxes=money(gross_profit - vat - revenue_tax),
            tax_method=TAX_METHOD,
            tax_profile_source="legacy-default",
            pnl_vat_mode=PNL_VAT_MODE_LEGACY,
            data_quality_status=DataQualityStatus.RELIABLE,
        )

    vat_rate = tax_profile.vat_rate
    if tax_profile.vat_mode is VatMode.INCLUDED and vat_rate:
        vat_output = money(net_revenue * vat_rate / (Decimal("100") + vat_rate))
        revenue_without_vat = money(net_revenue - vat_output)
    elif tax_profile.vat_mode is VatMode.EXCLUDED and vat_rate:
        vat_output = money(net_revenue * vat_rate / Decimal("100"))
        revenue_without_vat = net_revenue
    else:
        vat_output = Decimal("0")
        revenue_without_vat = net_revenue

    if tax_profile_is_osno(tax_profile):
        income_tax_kind = tax_profile.income_tax_kind or IP_NDFL_PROGRESSIVE_KIND
        if vat_output != 0 and not vat_input_available:
            return TaxCalculation(
                revenue_without_vat=revenue_without_vat,
                vat=Decimal("0"),
                vat_output=vat_output,
                vat_input=Decimal("0"),
                vat_payable=Decimal("0"),
                revenue_tax=Decimal("0"),
                income_tax_kind=income_tax_kind,
                income_tax_base=Decimal("0"),
                income_tax=Decimal("0"),
                income_tax_included=False,
                tax_completeness="input_vat_missing",
                profit_after_taxes=gross_profit,
                tax_method=_tax_method_label(tax_profile, input_vat_available=False),
                tax_profile_source=tax_profile.source,
                pnl_vat_mode=PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
                data_quality_status=DataQualityStatus.TAX_REVIEW,
            )
        vat_input = money(vat_input)
        vat_payable = money(vat_output - vat_input)
        income_tax_base = money(gross_profit)
        completeness = vat_input_completeness.strip().lower() or VAT_INPUT_CONFIRMED
        tax_completeness = (
            "vat_confirmed_ndfl_not_allocated"
            if completeness == VAT_INPUT_CONFIRMED
            else f"vat_input_{completeness}_ndfl_not_allocated"
        )
        data_quality_status = (
            DataQualityStatus.RELIABLE
            if completeness == VAT_INPUT_CONFIRMED
            else DataQualityStatus.TAX_REVIEW
        )
        return TaxCalculation(
            revenue_without_vat=revenue_without_vat,
            vat=vat_payable,
            vat_output=vat_output,
            vat_input=vat_input,
            vat_payable=vat_payable,
            revenue_tax=Decimal("0"),
            income_tax_kind=income_tax_kind,
            income_tax_base=income_tax_base,
            income_tax=Decimal("0"),
            income_tax_included=False,
            tax_completeness=tax_completeness,
            profit_after_taxes=income_tax_base,
            tax_method=_tax_method_label(tax_profile, input_vat_available=True),
            tax_profile_source=tax_profile.source,
            pnl_vat_mode=PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO,
            data_quality_status=data_quality_status,
        )

    vat = vat_output
    revenue_tax = money(net_revenue * tax_profile.revenue_tax_rate)
    return TaxCalculation(
        revenue_without_vat=revenue_without_vat,
        vat=vat,
        vat_output=vat_output,
        vat_input=Decimal("0"),
        vat_payable=vat,
        revenue_tax=revenue_tax,
        income_tax_kind=tax_profile.income_tax_kind,
        income_tax_base=Decimal("0"),
        income_tax=Decimal("0"),
        income_tax_included=False,
        tax_completeness="profile_complete",
        profit_after_taxes=money(gross_profit - vat - revenue_tax),
        tax_method=_tax_method_label(tax_profile),
        tax_profile_source=tax_profile.source,
        pnl_vat_mode=PNL_VAT_MODE_LEGACY,
        data_quality_status=DataQualityStatus.RELIABLE,
    )


def week_bounds(value: date) -> tuple[date, date]:
    week_start = value - timedelta(days=value.weekday())
    return week_start, week_start + timedelta(days=6)


def tax_profile_is_osno(tax_profile: TaxProfile) -> bool:
    tax_system = tax_profile.tax_system.casefold()
    return "осно" in tax_system or "общ" in tax_system


def tax_profile_method_supported(tax_profile: TaxProfile) -> bool:
    tax_system = re.sub(
        r"[\s_\-]+",
        " ",
        tax_profile.tax_system.casefold(),
    ).strip()
    if tax_profile_is_osno(tax_profile):
        return True
    is_usn = "усн" in tax_system or "упрощ" in tax_system
    return is_usn and "доход" in tax_system and "расход" not in tax_system


def tax_profile_is_confirmed(tax_profile: TaxProfile) -> bool:
    return (
        tax_profile.vat_deduction_mode is not VatDeductionMode.UNKNOWN
        and tax_profile_method_supported(tax_profile)
    )


def _tax_profile_uses_without_vat_pnl(tax_profile: TaxProfile | None) -> bool:
    return (
        tax_profile is not None
        and tax_profile_is_confirmed(tax_profile)
        and tax_profile_is_osno(tax_profile)
    )


def _revenue_without_vat_for_profile(
    net_revenue: Decimal,
    tax_profile: TaxProfile | None,
) -> Decimal:
    if tax_profile is None or not tax_profile_is_confirmed(tax_profile):
        return net_revenue
    vat_rate = tax_profile.vat_rate
    if tax_profile.vat_mode is VatMode.INCLUDED and vat_rate:
        return money(net_revenue - net_revenue * vat_rate / (Decimal("100") + vat_rate))
    if tax_profile.vat_mode is VatMode.EXCLUDED or tax_profile.vat_mode is VatMode.NONE:
        return net_revenue
    return net_revenue


def _tax_method_label(
    tax_profile: TaxProfile,
    *,
    input_vat_available: bool | None = None,
) -> str:
    parts = [tax_profile.tax_system or "Налоговый профиль"]
    if tax_profile.vat_mode is VatMode.INCLUDED and tax_profile.vat_rate:
        parts.append(f"НДС {tax_profile.vat_rate.normalize()}% внутри цены")
    elif tax_profile.vat_mode is VatMode.EXCLUDED and tax_profile.vat_rate:
        parts.append(f"НДС {tax_profile.vat_rate.normalize()}% сверху")
    else:
        parts.append("без НДС")
    if tax_profile.revenue_tax_rate:
        rate = (tax_profile.revenue_tax_rate * Decimal("100")).normalize()
        parts.append(f"налог с выручки {rate}%")
    else:
        parts.append("налог с выручки 0%")
    if tax_profile_is_osno(tax_profile):
        if input_vat_available is False:
            parts.append("входящий НДС не подтвержден")
        elif input_vat_available is True:
            parts.append("входящий НДС учтен")
        parts.append("НДФЛ ИП сверху")
    return "; ".join(parts)


def calculate_progressive_income_tax(annual_tax_base: Decimal) -> Decimal:
    if annual_tax_base <= 0:
        return Decimal("0.00")
    brackets = (
        (Decimal("2400000"), Decimal("0.13")),
        (Decimal("5000000"), Decimal("0.15")),
        (Decimal("20000000"), Decimal("0.18")),
        (Decimal("50000000"), Decimal("0.20")),
        (None, Decimal("0.22")),
    )
    lower = Decimal("0")
    tax = Decimal("0")
    for upper, rate in brackets:
        taxable_to = annual_tax_base if upper is None else min(annual_tax_base, upper)
        if taxable_to > lower:
            tax += (taxable_to - lower) * rate
        if upper is None or annual_tax_base <= upper:
            break
        lower = upper
    return money(tax)


def _tax_profiles_by_org(
    tax_profiles: list[TaxProfile] | None,
) -> dict[str, list[TaxProfile]]:
    if tax_profiles is None:
        return {}
    result: dict[str, list[TaxProfile]] = defaultdict(list)
    for profile in tax_profiles:
        result[profile.organization_id].append(profile)
    for profiles in result.values():
        profiles.sort(
            key=lambda profile: (
                profile.valid_from or date.min,
                profile.valid_to or date.max,
            )
        )
    return result


def _tax_profile_for(
    profiles_by_org: dict[str, list[TaxProfile]],
    organization_id: str,
    calculation_date: date,
) -> TaxProfile | None:
    candidates = profiles_by_org.get(organization_id, [])
    for profile in reversed(candidates):
        if profile.valid_from is not None and calculation_date < profile.valid_from:
            continue
        if profile.valid_to is not None and calculation_date > profile.valid_to:
            continue
        return profile
    return None


def _cost_input_vat_value(cost: OnecUnfCostSnapshot | None) -> Decimal | None:
    if cost is None:
        return None
    return cost.input_vat_value


def is_partial_week(
    week_start: date, week_end: date, period_start: date, period_end: date
) -> bool:
    return week_start < period_start or week_end > period_end


def overlaps_period(
    item_start: date,
    item_end: date,
    period_start: date,
    period_end: date,
) -> bool:
    return item_start <= period_end and item_end >= period_start


def _snapshots_in_report_period(
    snapshots: list[WbApiSnapshot],
    *,
    period_start: date,
    period_end: date,
) -> list[WbApiSnapshot]:
    return [
        snapshot
        for snapshot in snapshots
        if period_start <= week_bounds(snapshot.period_start)[1] <= period_end
    ]


def _snapshot_coverage(
    snapshots: list[WbApiSnapshot],
) -> tuple[date | None, date | None]:
    if not snapshots:
        return None, None
    return (
        min(snapshot.period_start for snapshot in snapshots),
        max(snapshot.period_end for snapshot in snapshots),
    )


def _summary_rows_in_report_period(
    rows: list[WbSalesReportSummaryRow] | None,
    *,
    period_start: date,
    period_end: date,
) -> list[WbSalesReportSummaryRow]:
    return [
        row
        for row in rows or []
        if row.date_from == date.min
        or period_start <= row.date_to <= period_end
    ]


def _expense_bases_in_report_period(
    bases: list[WbExpenseAllocationBase] | None,
    *,
    period_start: date,
    period_end: date,
) -> list[WbExpenseAllocationBase]:
    return [
        base
        for base in bases or []
        if period_start <= base.week_end <= period_end
    ]


def _service_rows_in_report_period(
    rows: list[OnecMarketplaceServiceRow] | None,
    *,
    period_start: date,
    period_end: date,
) -> list[OnecMarketplaceServiceRow]:
    return [
        row
        for row in rows or []
        if period_start <= row.week_end <= period_end
    ]


def _controlled_expense_allocations(
    snapshots: list[WbApiSnapshot],
    summary_rows: list[WbSalesReportSummaryRow],
    expense_allocation_bases: list[WbExpenseAllocationBase] | None = None,
) -> list[_ControlledExpenses]:
    summary_controls = _summary_controls_by_key(summary_rows)
    report_kind_by_report_id = _summary_report_kinds_by_report_id(summary_rows)
    external_bases = _expense_bases_by_key(expense_allocation_bases or [])
    snapshots_by_key: dict[
        tuple[str, str, date, date, OnecReportKind],
        list[tuple[int, WbApiSnapshot]],
    ] = defaultdict(list)
    for index, snapshot in enumerate(snapshots):
        key = _expense_allocation_key(snapshot, report_kind_by_report_id)
        snapshots_by_key[key].append((index, snapshot))

    result = [
        _ControlledExpenses(
            storage=_empty_category_allocation(snapshot.storage),
            wb_promotion=_empty_category_allocation(snapshot.wb_promotion),
        )
        for snapshot in snapshots
    ]
    for key, items in snapshots_by_key.items():
        control = summary_controls.get(key)
        report_ids = tuple(sorted(control["report_ids"])) if control else ()
        storage_control = control["storage"] if control else None
        promotion_control = control["wb_promotion"] if control else None
        storage_allocations = _category_allocations_for_items(
            items,
            category=EXPENSE_STORAGE,
            control_amount=storage_control,
            report_ids=report_ids,
            expense_bases=external_bases.get(
                (key[0], key[1], key[2], key[3], EXPENSE_STORAGE), []
            ),
        )
        promotion_allocations = _category_allocations_for_items(
            items,
            category=EXPENSE_WB_PROMOTION,
            control_amount=promotion_control,
            report_ids=report_ids,
            expense_bases=external_bases.get(
                (key[0], key[1], key[2], key[3], EXPENSE_WB_PROMOTION), []
            ),
        )
        for item_index, (snapshot_index, _snapshot) in enumerate(items):
            result[snapshot_index] = _ControlledExpenses(
                storage=storage_allocations[item_index],
                wb_promotion=promotion_allocations[item_index],
            )
    return result


def _vat_input_allocations(
    snapshots: list[WbApiSnapshot],
    expense_allocations: list[_ControlledExpenses],
    service_rows: list[OnecMarketplaceServiceRow],
) -> list[_VatInputAllocation]:
    wb_allocated = [
        Decimal("0")
        if _is_penalty_only_snapshot(snapshot)
        else money(snapshot.vat_input_from_wb)
        for snapshot in snapshots
    ]
    if not snapshots:
        return []

    service_vat_by_key: dict[tuple[str, str, date, date, str], Decimal] = defaultdict(
        Decimal
    )
    for row in service_rows:
        if row.vat == 0 or _is_penalty_service_category(row.service_category):
            continue
        service_vat_by_key[
            (
                row.client_id,
                row.organization_id,
                row.week_start,
                row.week_end,
                _vat_reconciliation_category(row.service_category),
            )
        ] += row.vat

    snapshots_by_key: dict[
        tuple[str, str, date, date],
        list[tuple[int, WbApiSnapshot]],
    ] = defaultdict(list)
    for index, snapshot in enumerate(snapshots):
        week_start, week_end = week_bounds(snapshot.period_start)
        snapshots_by_key[
            (snapshot.client_id, snapshot.organization_id, week_start, week_end)
        ].append((index, snapshot))

    onec_allocated = [Decimal("0") for _snapshot in snapshots]
    group_completeness: dict[tuple[str, str, date, date], str] = {}
    for group_key, items in snapshots_by_key.items():
        service_keys = [key for key in service_vat_by_key if key[:4] == group_key]
        if not service_keys:
            group_completeness[group_key] = _completeness_from_wb_rows(items)
            continue
        completeness = VAT_INPUT_CONFIRMED
        for service_key in service_keys:
            category = service_key[4]
            vat_total = money(service_vat_by_key[service_key])
            for snapshot_index, item in items:
                if item.vat_input_from_wb != 0:
                    continue
                wb_allocated[snapshot_index] += _service_input_vat_from_gross(
                    _vat_category_weight(
                        item,
                        expense_allocations[snapshot_index],
                        category,
                    )
                )
            weights = [
                abs(
                    _vat_category_weight(
                        item,
                        expense_allocations[snapshot_index],
                        category,
                    )
                )
                for snapshot_index, item in items
            ]
            if sum(weights, Decimal("0")) == 0:
                weights = [abs(item.net_revenue) for _snapshot_index, item in items]
                completeness = _worse_vat_input_completeness(
                    completeness,
                    VAT_INPUT_PARTIAL,
                )
            if sum(weights, Decimal("0")) == 0:
                weights = [Decimal("1") for _snapshot_index, _item in items]
                completeness = _worse_vat_input_completeness(
                    completeness,
                    VAT_INPUT_PARTIAL,
                )
            allocated_values = _allocate_by_weights(vat_total, weights)
            for (snapshot_index, _item), allocated in zip(
                items,
                allocated_values,
                strict=True,
            ):
                onec_allocated[snapshot_index] += allocated
        wb_total = money(
            sum((wb_allocated[index] for index, _item in items), Decimal("0"))
        )
        onec_total = money(
            sum((service_vat_by_key[key] for key in service_keys), Decimal("0"))
        )
        completeness = _worse_vat_input_completeness(
            completeness,
            _vat_input_reconciliation_status(wb_total, onec_total),
        )
        group_completeness[group_key] = completeness

    return [
        _VatInputAllocation(
            from_wb=money(wb_allocated[index]),
            from_1c=money(onec_allocated[index]),
            completeness=group_completeness.get(
                (
                    snapshot.client_id,
                    snapshot.organization_id,
                    *week_bounds(snapshot.period_start),
                ),
                VAT_INPUT_MISSING,
            ),
        )
        for index, snapshot in enumerate(snapshots)
    ]


def _completeness_from_wb_rows(
    items: list[tuple[int, WbApiSnapshot]],
) -> str:
    return (
        VAT_INPUT_PARTIAL
        if any(item.vat_input_from_wb != 0 for _index, item in items)
        else VAT_INPUT_MISSING
    )


def _service_input_vat_from_gross(gross_amount: Decimal) -> Decimal:
    if gross_amount == 0:
        return Decimal("0")
    return money(gross_amount * VAT_INPUT_SERVICE_INCLUDED_RATIO)


def _deductible_service_input_vat(allocation: _VatInputAllocation) -> Decimal:
    if allocation.from_wb != 0:
        return allocation.from_wb
    return allocation.from_1c


def _vat_reconciliation_category(category: str) -> str:
    if category in {"Комиссия WB", "Логистика"}:
        return VAT_INPUT_COMMISSION_LOGISTICS_GROUP
    return category


def _is_penalty_service_category(category: str) -> bool:
    normalized = category.strip().casefold()
    return any(marker in normalized for marker in ("штраф", "пеня", "неустой"))


def _vat_input_reconciliation_status(
    vat_input_from_wb: Decimal,
    vat_input_from_1c: Decimal,
) -> str:
    if vat_input_from_wb == 0 and vat_input_from_1c == 0:
        return VAT_INPUT_MISSING
    if vat_input_from_wb == 0 or vat_input_from_1c == 0:
        return VAT_INPUT_PARTIAL
    if abs(vat_input_from_1c - vat_input_from_wb) > VAT_INPUT_DIFF_TOLERANCE:
        return VAT_INPUT_MISMATCH
    return VAT_INPUT_CONFIRMED


def _vat_category_weight(
    snapshot: WbApiSnapshot,
    controlled_expenses: _ControlledExpenses,
    category: str,
) -> Decimal:
    if category == VAT_INPUT_COMMISSION_LOGISTICS_GROUP:
        return snapshot.wb_commission + snapshot.logistics
    if category == "Комиссия WB":
        return snapshot.wb_commission
    if category == "Логистика":
        return snapshot.logistics
    if category == EXPENSE_STORAGE or category == "Хранение":
        return controlled_expenses.storage.allocated
    if category == "Приемка":
        return snapshot.acceptance
    if category == EXPENSE_WB_PROMOTION:
        return controlled_expenses.wb_promotion.allocated
    if category == "Штрафы/доплаты":
        return snapshot.penalties_and_holdbacks
    if category == "Эквайринг":
        return snapshot.acquiring
    return Decimal("0")


def _spp_discount_allocations(
    snapshots: list[WbApiSnapshot],
    summary_rows: list[WbSalesReportSummaryRow],
) -> list[_SppAllocation]:
    summary_controls = _summary_controls_by_key(summary_rows)
    report_kind_by_report_id = _summary_report_kinds_by_report_id(summary_rows)
    snapshots_by_key: dict[
        tuple[str, str, date, date, OnecReportKind],
        list[tuple[int, WbApiSnapshot]],
    ] = defaultdict(list)
    for index, snapshot in enumerate(snapshots):
        key = _expense_allocation_key(snapshot, report_kind_by_report_id)
        snapshots_by_key[key].append((index, snapshot))

    result = [
        _SppAllocation(
            discount=Decimal("0.00"),
            control_amount=None,
            distribution_method="СПП не распределялся",
            source_status="СПП не передается текущим источником",
        )
        for _snapshot in snapshots
    ]
    for key, items in snapshots_by_key.items():
        control = summary_controls.get(key)
        if control is None:
            continue
        control_amount = money(Decimal(str(control["spp_discount"])))
        weights = [abs(item.net_revenue) for _index, item in items]
        if sum(weights, Decimal("0")) == 0:
            weights = [Decimal("1") for _index, _item in items]
            method = "Равная доля по строкам"
        else:
            method = "Доля по выручке WB после СПП"
        allocated_values = _allocate_by_weights(control_amount, weights)
        for (snapshot_index, _snapshot), discount in zip(
            items, allocated_values, strict=True
        ):
            result[snapshot_index] = _SppAllocation(
                discount=discount,
                control_amount=control_amount,
                distribution_method=method,
                source_status=(
                    "СПП из WB sales-reports/list cashbackDiscountSum; "
                    f"распределение: {method}"
                ),
            )
    return result


def _empty_category_allocation(amount: Decimal) -> _CategoryAllocation:
    return _CategoryAllocation(
        allocated=money(amount),
        api_base_amount=amount,
        distribution_base_amount=amount,
        api_total_amount=amount,
        control_amount=None,
        scaling_coefficient=None,
        distribution_method="Фактическая детализация WB",
        allocation_status=ALLOCATION_STATUS_NO_CONTROL,
        wb_report_ids=(),
        source_row_count=1,
    )


def _summary_controls_by_key(
    summary_rows: list[WbSalesReportSummaryRow],
) -> dict[tuple[str, str, date, date, OnecReportKind], dict[str, object]]:
    controls: dict[
        tuple[str, str, date, date, OnecReportKind],
        dict[str, object],
    ] = {}
    for row in summary_rows:
        if row.date_from == date.min or row.date_to == date.min:
            continue
        key = (
            row.client_id,
            row.seller_account_id,
            row.date_from,
            row.date_to,
            _summary_report_kind(row.report_type),
        )
        if key not in controls:
            controls[key] = {
                "storage": Decimal("0"),
                "wb_promotion": Decimal("0"),
                "spp_discount": Decimal("0"),
                "report_ids": set(),
            }
        controls[key]["storage"] += row.paid_storage_sum
        controls[key]["wb_promotion"] += row.deduction_sum
        controls[key]["spp_discount"] += row.cashback_discount_sum
        if row.report_id:
            controls[key]["report_ids"].add(row.report_id)
    return controls


def _summary_create_dates_by_report_id(
    summary_rows: list[WbSalesReportSummaryRow],
) -> dict[str, date]:
    return {row.report_id: row.create_date for row in summary_rows if row.report_id}


def _wb_report_date(
    snapshot: WbApiSnapshot,
    week_end: date,
    report_dates: dict[str, date],
) -> str:
    if snapshot.wb_report_id and snapshot.wb_report_id in report_dates:
        return report_dates[snapshot.wb_report_id].isoformat()
    return (week_end + timedelta(days=1)).isoformat()


def _category_allocations_for_items(
    items: list[tuple[int, WbApiSnapshot]],
    *,
    category: str,
    control_amount: Decimal | None,
    report_ids: tuple[str, ...],
    expense_bases: list[WbExpenseAllocationBase] | None = None,
) -> list[_CategoryAllocation]:
    external_values, external_source_counts = _external_base_values_for_items(
        items,
        expense_bases or [],
    )
    uses_external_api = bool(expense_bases) and sum(external_values, Decimal("0")) != 0
    if uses_external_api:
        api_values = external_values
        source_counts = external_source_counts
    else:
        api_values = [
            item.storage if category == EXPENSE_STORAGE else item.wb_promotion
            for _index, item in items
        ]
        source_counts = [1 for _index, _item in items]
    api_total = sum(api_values, Decimal("0"))
    product_indexes = _product_item_indexes(items)
    unattributed_api_total = sum(
        api_value
        for item_index, api_value in enumerate(api_values)
        if item_index not in product_indexes
    )
    has_unattributed_expense = bool(product_indexes) and unattributed_api_total != 0
    if control_amount is None:
        if has_unattributed_expense:
            return _allocate_category_to_product_items(
                items,
                target_amount=money(api_total),
                api_values=api_values,
                source_counts=source_counts,
                api_total=api_total,
                control_amount=None,
                scaling_coefficient=None,
                report_ids=report_ids,
                product_indexes=product_indexes,
                uses_external_api=uses_external_api,
                status_by_api=ALLOCATION_STATUS_NO_SKU_BY_DETAIL,
                status_by_revenue=ALLOCATION_STATUS_NO_SKU_BY_REVENUE,
                status_by_equal_share=ALLOCATION_STATUS_NO_SKU_BY_EQUAL_SHARE,
            )
        return [
            _CategoryAllocation(
                allocated=money(api_value),
                api_base_amount=api_value,
                distribution_base_amount=api_value,
                api_total_amount=api_total,
                control_amount=None,
                scaling_coefficient=None,
                distribution_method="Фактическая детализация WB",
                allocation_status=ALLOCATION_STATUS_NO_CONTROL,
                wb_report_ids=report_ids,
                source_row_count=source_count,
            )
            for api_value, source_count in zip(api_values, source_counts, strict=True)
        ]

    control_amount = money(control_amount)
    if control_amount == 0 and api_total == 0:
        return [
            _CategoryAllocation(
                allocated=Decimal("0.00"),
                api_base_amount=api_value,
                distribution_base_amount=Decimal("0"),
                api_total_amount=api_total,
                control_amount=control_amount,
                scaling_coefficient=None,
                distribution_method="Расход отсутствует",
                allocation_status=ALLOCATION_STATUS_NO_EXPENSE,
                wb_report_ids=report_ids,
                source_row_count=source_count,
            )
            for api_value, source_count in zip(api_values, source_counts, strict=True)
        ]

    if has_unattributed_expense:
        scaling_coefficient = control_amount / api_total if api_total != 0 else None
        return _allocate_category_to_product_items(
            items,
            target_amount=control_amount,
            api_values=api_values,
            source_counts=source_counts,
            api_total=api_total,
            control_amount=control_amount,
            scaling_coefficient=scaling_coefficient,
            report_ids=report_ids,
            product_indexes=product_indexes,
            uses_external_api=uses_external_api,
            status_by_api=ALLOCATION_STATUS_NO_SKU_BY_DETAIL,
            status_by_revenue=ALLOCATION_STATUS_NO_SKU_BY_REVENUE,
            status_by_equal_share=ALLOCATION_STATUS_NO_SKU_BY_EQUAL_SHARE,
        )

    if api_total != 0:
        allocated_values = _allocate_by_weights(control_amount, api_values)
        scaling_coefficient = control_amount / api_total
        return [
            _CategoryAllocation(
                allocated=allocated,
                api_base_amount=api_value,
                distribution_base_amount=api_value,
                api_total_amount=api_total,
                control_amount=control_amount,
                scaling_coefficient=scaling_coefficient,
                distribution_method=(
                    "Доля по отдельному API WB"
                    if uses_external_api
                    else "Доля по API-детализации"
                ),
                allocation_status=(
                    ALLOCATION_STATUS_BY_EXPENSE_API
                    if uses_external_api
                    else ALLOCATION_STATUS_BY_DETAIL
                ),
                wb_report_ids=report_ids,
                source_row_count=source_count,
            )
            for api_value, allocated, source_count in zip(
                api_values,
                allocated_values,
                source_counts,
                strict=True,
            )
        ]

    if product_indexes:
        revenue_weights = [
            abs(item.net_revenue) if item_index in product_indexes else Decimal("0")
            for item_index, (_index, item) in enumerate(items)
        ]
    else:
        revenue_weights = [abs(item.net_revenue) for _index, item in items]
    if sum(revenue_weights, Decimal("0")) != 0:
        allocated_values = _allocate_by_weights(control_amount, revenue_weights)
        return [
            _CategoryAllocation(
                allocated=allocated,
                api_base_amount=api_value,
                distribution_base_amount=weight,
                api_total_amount=api_total,
                control_amount=control_amount,
                scaling_coefficient=None,
                distribution_method="Доля по выручке WB",
                allocation_status=ALLOCATION_STATUS_BY_REVENUE,
                wb_report_ids=report_ids,
                source_row_count=source_count,
            )
            for api_value, weight, allocated, source_count in zip(
                api_values,
                revenue_weights,
                allocated_values,
                source_counts,
                strict=True,
            )
        ]

    if product_indexes:
        equal_weights = [
            Decimal("1") if item_index in product_indexes else Decimal("0")
            for item_index, _item in enumerate(items)
        ]
    else:
        equal_weights = [Decimal("1") for _index, _item in items]
    allocated_values = _allocate_by_weights(control_amount, equal_weights)
    return [
        _CategoryAllocation(
            allocated=allocated,
            api_base_amount=api_value,
            distribution_base_amount=weight,
            api_total_amount=api_total,
            control_amount=control_amount,
            scaling_coefficient=None,
            distribution_method="Равная доля по строкам",
            allocation_status=ALLOCATION_STATUS_BY_EQUAL_SHARE,
            wb_report_ids=report_ids,
            source_row_count=1,
        )
        for api_value, weight, allocated in zip(
            api_values, equal_weights, allocated_values, strict=True
        )
    ]


def _product_item_indexes(items: list[tuple[int, WbApiSnapshot]]) -> set[int]:
    return {
        item_index
        for item_index, (_index, item) in enumerate(items)
        if _has_product_identity(item)
    }


def _has_product_identity(item: WbApiSnapshot) -> bool:
    return (
        _is_real_nm_id(item.nm_id)
        or bool(item.vendor_code.strip())
        or bool(item.barcode.strip())
    )


def _is_real_nm_id(nm_id: int | None) -> bool:
    return nm_id is not None and nm_id > 0


def _allocate_category_to_product_items(
    items: list[tuple[int, WbApiSnapshot]],
    *,
    target_amount: Decimal,
    api_values: list[Decimal],
    source_counts: list[int],
    api_total: Decimal,
    control_amount: Decimal | None,
    scaling_coefficient: Decimal | None,
    report_ids: tuple[str, ...],
    product_indexes: set[int],
    uses_external_api: bool,
    status_by_api: str,
    status_by_revenue: str,
    status_by_equal_share: str,
) -> list[_CategoryAllocation]:
    product_api_weights = [
        api_value if item_index in product_indexes else Decimal("0")
        for item_index, api_value in enumerate(api_values)
    ]
    if sum(product_api_weights, Decimal("0")) != 0:
        weights = product_api_weights
        distribution_method = (
            "Доля по отдельному API WB"
            if uses_external_api
            else "Доля по товарной детализации WB"
        )
        allocation_status = status_by_api
    else:
        revenue_weights = [
            abs(item.net_revenue) if item_index in product_indexes else Decimal("0")
            for item_index, (_index, item) in enumerate(items)
        ]
        if sum(revenue_weights, Decimal("0")) != 0:
            weights = revenue_weights
            distribution_method = "Доля по выручке WB"
            allocation_status = status_by_revenue
        else:
            weights = [
                Decimal("1") if item_index in product_indexes else Decimal("0")
                for item_index, _item in enumerate(items)
            ]
            distribution_method = "Равная доля по товарам"
            allocation_status = status_by_equal_share

    allocated_values = _allocate_by_weights(target_amount, weights)
    return [
        _CategoryAllocation(
            allocated=allocated,
            api_base_amount=api_value,
            distribution_base_amount=weight,
            api_total_amount=api_total,
            control_amount=control_amount,
            scaling_coefficient=scaling_coefficient,
            distribution_method=distribution_method,
            allocation_status=allocation_status,
            wb_report_ids=report_ids,
            source_row_count=source_count,
        )
        for api_value, weight, allocated, source_count in zip(
            api_values,
            weights,
            allocated_values,
            source_counts,
            strict=True,
        )
    ]


def _external_base_values_for_items(
    items: list[tuple[int, WbApiSnapshot]],
    expense_bases: list[WbExpenseAllocationBase],
) -> tuple[list[Decimal], list[int]]:
    if not expense_bases:
        return [Decimal("0") for _index, _item in items], [1 for _index, _item in items]

    base_by_product: dict[tuple[object, ...], dict[str, object]] = {}
    for base in expense_bases:
        product_key = _expense_product_key(
            nm_id=base.nm_id,
            vendor_code=base.vendor_code,
            barcode=base.barcode,
        )
        if product_key not in base_by_product:
            base_by_product[product_key] = {
                "amount": Decimal("0"),
                "source_row_count": 0,
            }
        base_by_product[product_key]["amount"] += base.amount
        base_by_product[product_key]["source_row_count"] += base.source_row_count

    item_product_keys = [
        _expense_product_key(
            nm_id=item.nm_id,
            vendor_code=item.vendor_code,
            barcode=item.barcode,
        )
        for _index, item in items
    ]
    product_to_item_indexes: dict[tuple[object, ...], list[int]] = defaultdict(list)
    for item_index, product_key in enumerate(item_product_keys):
        product_to_item_indexes[product_key].append(item_index)

    values = [Decimal("0") for _index, _item in items]
    source_counts = [1 for _index, _item in items]
    for product_key, item_indexes in product_to_item_indexes.items():
        base_bucket = base_by_product.get(product_key)
        if not base_bucket:
            continue
        amount = base_bucket["amount"]
        weights = [abs(items[index][1].net_revenue) for index in item_indexes]
        if sum(weights, Decimal("0")) == 0:
            weights = [Decimal("1") for _index in item_indexes]
        allocated = _allocate_by_weights(amount, weights)
        for offset, (item_index, item_value) in enumerate(
            zip(item_indexes, allocated, strict=True)
        ):
            values[item_index] = item_value
            source_counts[item_index] = (
                int(base_bucket["source_row_count"]) if offset == 0 else 0
            )
    return values, source_counts


def _expense_product_key(
    *,
    nm_id: int | None,
    vendor_code: str,
    barcode: str,
) -> tuple[object, ...]:
    if _is_real_nm_id(nm_id):
        return ("nm", nm_id)
    vendor_key = _vendor_code_key(vendor_code)
    if vendor_key or barcode:
        return ("vendor_barcode", vendor_key, barcode)
    return ("empty",)


def _expense_bases_by_key(
    expense_allocation_bases: list[WbExpenseAllocationBase],
) -> dict[tuple[str, str, date, date, str], list[WbExpenseAllocationBase]]:
    result: dict[tuple[str, str, date, date, str], list[WbExpenseAllocationBase]] = (
        defaultdict(list)
    )
    for base in expense_allocation_bases:
        result[
            (
                base.client_id,
                base.seller_account_id,
                base.week_start,
                base.week_end,
                base.expense_category,
            )
        ].append(base)
    return result


def _allocate_by_weights(
    control_amount: Decimal,
    weights: list[Decimal],
) -> list[Decimal]:
    control_amount = money(control_amount)
    if not weights:
        return []
    weight_total = sum(weights, Decimal("0"))
    if weight_total == 0:
        return [Decimal("0.00") for _weight in weights]
    unrounded = [control_amount * weight / weight_total for weight in weights]
    rounded = [money(value) for value in unrounded]
    residual = money(control_amount - sum(rounded, Decimal("0")))
    if residual == 0:
        return rounded

    residual_cents = int((residual * Decimal("100")).to_integral_value())
    if residual_cents == 0:
        return rounded
    if residual_cents > 0:
        order = sorted(
            range(len(weights)),
            key=lambda index: (
                unrounded[index] - rounded[index],
                abs(unrounded[index]),
            ),
            reverse=True,
        )
        step = Decimal("0.01")
    else:
        order = sorted(
            range(len(weights)),
            key=lambda index: (
                unrounded[index] - rounded[index],
                -abs(unrounded[index]),
            ),
        )
        step = Decimal("-0.01")
    for offset in range(abs(residual_cents)):
        rounded[order[offset % len(order)]] += step
    return rounded


def _expense_allocation_key(
    snapshot: WbApiSnapshot,
    report_kind_by_report_id: dict[str, OnecReportKind] | None = None,
) -> tuple[str, str, date, date, OnecReportKind]:
    week_start, week_end = week_bounds(snapshot.period_start)
    return (
        snapshot.client_id,
        snapshot.seller_account_id,
        week_start,
        week_end,
        _report_kind_for_snapshot(snapshot, report_kind_by_report_id)[0],
    )


def _summary_report_kind(report_type: int | None) -> OnecReportKind:
    if report_type == 2:
        return OnecReportKind.BUYOUT_NOTICE
    return OnecReportKind.COMMISSIONER_REPORT


def _summary_report_kinds_by_report_id(
    summary_rows: list[WbSalesReportSummaryRow],
) -> dict[str, OnecReportKind]:
    return {
        row.report_id: _summary_report_kind(row.report_type)
        for row in summary_rows
        if row.report_id and row.report_type is not None
    }


def _report_kind_for_snapshot(
    snapshot: WbApiSnapshot,
    report_kind_by_report_id: dict[str, OnecReportKind] | None = None,
) -> tuple[OnecReportKind, DataQualityStatus]:
    if report_kind_by_report_id is None:
        return _onec_report_kind(snapshot.wb_report_id), DataQualityStatus.RELIABLE
    if snapshot.wb_report_id:
        report_kind = report_kind_by_report_id.get(snapshot.wb_report_id)
        if report_kind is not None:
            return report_kind, DataQualityStatus.RELIABLE
    return (
        _onec_report_kind(snapshot.wb_report_id),
        DataQualityStatus.REPORT_TYPE_FALLBACK,
    )


def build_unit_economics_report(
    *,
    client_id: str,
    wb_snapshots: list[WbApiSnapshot],
    cost_snapshots: list[OnecUnfCostSnapshot],
    sku_mappings: list[SkuMapping],
    account_org_mapping: list[AccountOrgMapping],
    tax_profiles: list[TaxProfile] | None = None,
    wb_sales_report_summary_rows: list[WbSalesReportSummaryRow] | None = None,
    expense_allocation_bases: list[WbExpenseAllocationBase] | None = None,
    onec_marketplace_service_rows: list[OnecMarketplaceServiceRow] | None = None,
    generated_at: datetime | None = None,
    as_of_date: date | None = None,
    report_period_start: date = DEFAULT_REPORT_PERIOD_START,
    report_period_end: date = DEFAULT_REPORT_PERIOD_END,
    methodology_version: str = METHODOLOGY_VERSION,
) -> UnitEconomicsReport:
    generated_at = generated_at or datetime.now(tz=MOSCOW_TZ)
    as_of_date = as_of_date or generated_at.date()
    source_coverage_start, source_coverage_end = _snapshot_coverage(wb_snapshots)
    wb_snapshots = _snapshots_in_report_period(
        wb_snapshots,
        period_start=report_period_start,
        period_end=report_period_end,
    )
    wb_sales_report_summary_rows = _summary_rows_in_report_period(
        wb_sales_report_summary_rows,
        period_start=report_period_start,
        period_end=report_period_end,
    )
    expense_allocation_bases = _expense_bases_in_report_period(
        expense_allocation_bases,
        period_start=report_period_start,
        period_end=report_period_end,
    )
    onec_marketplace_service_rows = _service_rows_in_report_period(
        onec_marketplace_service_rows,
        period_start=report_period_start,
        period_end=report_period_end,
    )
    account_to_org = {
        item.seller_account_id: item.organization_id for item in account_org_mapping
    }
    tax_profiles_by_org = _tax_profiles_by_org(tax_profiles)
    tax_profile_required = tax_profiles is not None
    mapping_index = _index_mappings(sku_mappings)
    cost_index = _index_costs(cost_snapshots)
    expense_allocations = _controlled_expense_allocations(
        wb_snapshots,
        wb_sales_report_summary_rows,
        expense_allocation_bases,
    )
    vat_input_allocations = _vat_input_allocations(
        wb_snapshots,
        expense_allocations,
        onec_marketplace_service_rows,
    )
    spp_allocations = _spp_discount_allocations(
        wb_snapshots,
        wb_sales_report_summary_rows,
    )
    report_kind_by_report_id = (
        _summary_report_kinds_by_report_id(wb_sales_report_summary_rows)
        if wb_sales_report_summary_rows
        else None
    )
    wb_report_dates = _summary_create_dates_by_report_id(wb_sales_report_summary_rows)
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    report_grouped: dict[tuple[object, ...], dict[str, object]] = {}
    onec_report_grouped: dict[tuple[object, ...], dict[str, object]] = {}
    onec_product_grouped: dict[tuple[object, ...], dict[str, object]] = {}
    allocation_grouped: dict[tuple[object, ...], dict[str, object]] = {}
    tax_input_grouped: dict[tuple[object, ...], dict[str, object]] = {}

    for snapshot_index, snapshot in enumerate(wb_snapshots):
        controlled_expenses = expense_allocations[snapshot_index]
        vat_input_allocation = vat_input_allocations[snapshot_index]
        spp_allocation = spp_allocations[snapshot_index]
        week_start, week_end = week_bounds(snapshot.period_start)
        wb_report_id = snapshot.wb_report_id or "Без номера"
        wb_report_date = _wb_report_date(snapshot, week_end, wb_report_dates)
        document_kind, report_type_status = _report_kind_for_snapshot(
            snapshot,
            report_kind_by_report_id,
        )
        document_date = (
            week_end
            if document_kind is OnecReportKind.COMMISSIONER_REPORT
            else week_end + timedelta(days=1)
        )
        document_label = _onec_document_label(document_kind)
        document_report = _document_report_filter_label(
            document_label,
            week_start,
            week_end,
            report_period_start,
            report_period_end,
        )
        mapping = _find_mapping(snapshot, mapping_index)
        mapped_onec_item_id = mapping.onec_item_id if mapping else None
        cost = _find_cost(snapshot, mapping, cost_index)
        tax_profile = _tax_profile_for(
            tax_profiles_by_org,
            snapshot.organization_id,
            week_start,
        )
        without_vat_pnl = _tax_profile_uses_without_vat_pnl(tax_profile)
        effective_onec_item_id = cost.onec_item_id if cost else mapped_onec_item_id
        quality_status = _quality_status(
            snapshot,
            mapping,
            cost,
            account_to_org,
            report_type_status=report_type_status,
        )
        goods_quantity = _goods_quantity(snapshot)
        cost_input_vat = _cost_input_vat_value(cost)
        cogs = (
            _pnl_cost_value(mapping, cost, cost_input_vat)
            if without_vat_pnl
            else _usable_cost_value(mapping, cost)
        ) * goods_quantity
        product_input_vat = (
            cost_input_vat * goods_quantity
            if cost_input_vat is not None
            else Decimal("0")
        )
        service_input_vat = _deductible_service_input_vat(vat_input_allocation)
        input_vat = product_input_vat + service_input_vat
        cost_input_vat_available = (
            cost_input_vat is not None
            or cogs == 0
            or (without_vat_pnl and _cost_value_is_without_vat(cost))
        )
        service_input_vat_missing = (
            without_vat_pnl
            and _service_vat_required(snapshot, controlled_expenses)
            and vat_input_allocation.completeness == VAT_INPUT_MISSING
        )
        input_vat_available = cost_input_vat_available
        input_vat_completeness = _merge_vat_input_completeness(
            vat_input_allocation.completeness,
            cost_input_vat_available=cost_input_vat_available,
            cost_input_vat_missing=not cost_input_vat_available,
            service_input_vat_missing=service_input_vat_missing,
        )
        revenue_for_pnl = (
            _revenue_without_vat_for_profile(snapshot.net_revenue, tax_profile)
            if without_vat_pnl
            else snapshot.net_revenue
        )
        service_vat_for_pnl = service_input_vat if without_vat_pnl else Decimal("0")
        gross_profit = (
            revenue_for_pnl
            - snapshot.wb_commission
            - snapshot.logistics
            - controlled_expenses.storage.allocated
            - snapshot.acceptance
            - controlled_expenses.wb_promotion.allocated
            - snapshot.penalties_and_holdbacks
            - snapshot.acquiring
            + service_vat_for_pnl
            - cogs
        )
        key = (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.organization_id,
            week_start,
            week_end,
            document_kind,
            snapshot.nm_id,
            snapshot.vendor_code,
            snapshot.barcode,
            effective_onec_item_id,
            snapshot.sales_model,
        )
        if key not in grouped:
            grouped[key] = {
                "sales_quantity": Decimal("0"),
                "return_quantity": Decimal("0"),
                "quantity": Decimal("0"),
                "return_amount": Decimal("0"),
                "spp_discount": Decimal("0"),
                "spp_source_statuses": set(),
                "net_revenue": Decimal("0"),
                "wb_commission": Decimal("0"),
                "logistics": Decimal("0"),
                "storage": Decimal("0"),
                "acceptance": Decimal("0"),
                "wb_promotion": Decimal("0"),
                "penalties_and_holdbacks": Decimal("0"),
                "acquiring": Decimal("0"),
                "cogs": Decimal("0"),
                "vat_input": Decimal("0"),
                "vat_input_from_wb": Decimal("0"),
                "vat_input_from_1c": Decimal("0"),
                "vat_input_completeness": VAT_INPUT_CONFIRMED,
                "vat_input_available": True,
                "gross_profit": Decimal("0"),
                "status": DataQualityStatus.RELIABLE,
                "statuses": set(),
                "hashes": [],
                "document_reports": set(),
                "wb_report_ids": set(),
                "wb_report_dates": set(),
            }
        bucket = grouped[key]
        if goods_quantity > 0:
            bucket["sales_quantity"] += goods_quantity
        elif goods_quantity < 0:
            bucket["return_quantity"] += abs(goods_quantity)
            bucket["return_amount"] += abs(snapshot.net_revenue)
        bucket["quantity"] += goods_quantity
        bucket["spp_discount"] += spp_allocation.discount
        bucket["spp_source_statuses"].add(spp_allocation.source_status)
        bucket["net_revenue"] += snapshot.net_revenue
        bucket["wb_commission"] += snapshot.wb_commission
        bucket["logistics"] += snapshot.logistics
        bucket["storage"] += controlled_expenses.storage.allocated
        bucket["acceptance"] += snapshot.acceptance
        bucket["wb_promotion"] += controlled_expenses.wb_promotion.allocated
        bucket["penalties_and_holdbacks"] += snapshot.penalties_and_holdbacks
        bucket["acquiring"] += snapshot.acquiring
        bucket["cogs"] += cogs
        bucket["vat_input"] += input_vat
        bucket["vat_input_from_wb"] += vat_input_allocation.from_wb
        bucket["vat_input_from_1c"] += vat_input_allocation.from_1c
        bucket["vat_input_completeness"] = _worse_vat_input_completeness(
            str(bucket["vat_input_completeness"]),
            input_vat_completeness,
        )
        bucket["vat_input_available"] = (
            bucket["vat_input_available"] and input_vat_available
        )
        bucket["gross_profit"] += gross_profit
        bucket["status"] = _worse_status(bucket["status"], quality_status)
        bucket["statuses"].add(quality_status)
        bucket["hashes"].append(snapshot.raw_payload_hash)
        bucket["document_reports"].add(document_report)
        bucket["wb_report_ids"].add(wb_report_id)
        bucket["wb_report_dates"].add(wb_report_date)

        report_key = (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.organization_id,
            week_start,
            week_end,
            wb_report_id,
        )
        if report_key not in report_grouped:
            report_grouped[report_key] = {
                "sales_quantity": Decimal("0"),
                "return_quantity": Decimal("0"),
                "quantity": Decimal("0"),
                "spp_discount": Decimal("0"),
                "spp_source_statuses": set(),
                "net_revenue": Decimal("0"),
                "wb_commission": Decimal("0"),
                "logistics": Decimal("0"),
                "storage": Decimal("0"),
                "acceptance": Decimal("0"),
                "wb_promotion": Decimal("0"),
                "penalties_and_holdbacks": Decimal("0"),
                "acquiring": Decimal("0"),
                "cogs": Decimal("0"),
                "vat_input": Decimal("0"),
                "vat_input_from_wb": Decimal("0"),
                "vat_input_from_1c": Decimal("0"),
                "vat_input_completeness": VAT_INPUT_CONFIRMED,
                "vat_input_available": True,
                "gross_profit": Decimal("0"),
                "status": DataQualityStatus.RELIABLE,
                "source_row_count": 0,
            }
        report_bucket = report_grouped[report_key]
        if goods_quantity > 0:
            report_bucket["sales_quantity"] += goods_quantity
        elif goods_quantity < 0:
            report_bucket["return_quantity"] += abs(goods_quantity)
        report_bucket["quantity"] += goods_quantity
        report_bucket["spp_discount"] += spp_allocation.discount
        report_bucket["spp_source_statuses"].add(spp_allocation.source_status)
        report_bucket["net_revenue"] += snapshot.net_revenue
        report_bucket["wb_commission"] += snapshot.wb_commission
        report_bucket["logistics"] += snapshot.logistics
        report_bucket["storage"] += controlled_expenses.storage.allocated
        report_bucket["acceptance"] += snapshot.acceptance
        report_bucket["wb_promotion"] += controlled_expenses.wb_promotion.allocated
        report_bucket["penalties_and_holdbacks"] += snapshot.penalties_and_holdbacks
        report_bucket["acquiring"] += snapshot.acquiring
        report_bucket["cogs"] += cogs
        report_bucket["vat_input"] += input_vat
        report_bucket["vat_input_from_wb"] += vat_input_allocation.from_wb
        report_bucket["vat_input_from_1c"] += vat_input_allocation.from_1c
        report_bucket["vat_input_completeness"] = _worse_vat_input_completeness(
            str(report_bucket["vat_input_completeness"]),
            input_vat_completeness,
        )
        report_bucket["vat_input_available"] = (
            report_bucket["vat_input_available"] and input_vat_available
        )
        report_bucket["gross_profit"] += gross_profit
        report_bucket["status"] = _worse_status(report_bucket["status"], quality_status)
        report_bucket["source_row_count"] += 1

        tax_input_key = (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.organization_id,
            week_start,
            week_end,
        )
        if tax_input_key not in tax_input_grouped:
            tax_input_grouped[tax_input_key] = {
                "vat_input_from_wb": Decimal("0"),
                "vat_input_from_1c": Decimal("0"),
                "vat_input_completeness": VAT_INPUT_CONFIRMED,
                "source_row_count": 0,
            }
        tax_input_bucket = tax_input_grouped[tax_input_key]
        tax_input_bucket["vat_input_from_wb"] += vat_input_allocation.from_wb
        tax_input_bucket["vat_input_from_1c"] += vat_input_allocation.from_1c
        tax_input_bucket["vat_input_completeness"] = _worse_vat_input_completeness(
            str(tax_input_bucket["vat_input_completeness"]),
            input_vat_completeness,
        )
        tax_input_bucket["source_row_count"] += 1

        onec_report_key = (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.organization_id,
            document_date,
            week_start,
            week_end,
            document_kind,
            document_label,
        )
        if onec_report_key not in onec_report_grouped:
            onec_report_grouped[onec_report_key] = _new_onec_bucket()
        _add_to_onec_bucket(
            onec_report_grouped[onec_report_key],
            snapshot=snapshot,
            goods_quantity=goods_quantity,
            cogs=cogs,
            input_vat=input_vat,
            input_vat_from_wb=vat_input_allocation.from_wb,
            input_vat_from_1c=vat_input_allocation.from_1c,
            input_vat_completeness=input_vat_completeness,
            input_vat_available=input_vat_available,
            gross_profit=gross_profit,
            storage=controlled_expenses.storage.allocated,
            wb_promotion=controlled_expenses.wb_promotion.allocated,
            spp_discount=spp_allocation.discount,
            spp_source_status=spp_allocation.source_status,
            quality_status=quality_status,
        )

        onec_product_key = (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.organization_id,
            document_date,
            week_start,
            week_end,
            document_kind,
            document_label,
            snapshot.nm_id,
            snapshot.vendor_code,
            snapshot.barcode,
            effective_onec_item_id,
            snapshot.sales_model,
        )
        if onec_product_key not in onec_product_grouped:
            onec_product_grouped[onec_product_key] = _new_onec_bucket(
                include_hashes=True
            )
        _add_to_onec_bucket(
            onec_product_grouped[onec_product_key],
            snapshot=snapshot,
            goods_quantity=goods_quantity,
            cogs=cogs,
            input_vat=input_vat,
            input_vat_from_wb=vat_input_allocation.from_wb,
            input_vat_from_1c=vat_input_allocation.from_1c,
            input_vat_completeness=input_vat_completeness,
            input_vat_available=input_vat_available,
            gross_profit=gross_profit,
            storage=controlled_expenses.storage.allocated,
            wb_promotion=controlled_expenses.wb_promotion.allocated,
            spp_discount=spp_allocation.discount,
            spp_source_status=spp_allocation.source_status,
            quality_status=quality_status,
        )
        _add_expense_allocation_rows(
            allocation_grouped,
            snapshot=snapshot,
            week_start=week_start,
            week_end=week_end,
            document_label=document_label,
            mapped_onec_item_id=effective_onec_item_id,
            storage=controlled_expenses.storage,
            wb_promotion=controlled_expenses.wb_promotion,
        )

    rows = []
    for key, bucket in grouped.items():
        (
            row_client_id,
            seller_account_id,
            organization_id,
            week_start,
            week_end,
            document_kind,
            nm_id,
            vendor_code,
            barcode,
            onec_item_id,
            sales_model,
        ) = key
        net_revenue = money(bucket["net_revenue"])
        spp_discount = money(bucket["spp_discount"])
        revenue_before_spp = money(net_revenue + spp_discount)
        gross_profit = money(bucket["gross_profit"])
        tax = calculate_tax_amounts(
            net_revenue,
            gross_profit,
            _tax_profile_for(tax_profiles_by_org, organization_id, week_start),
            vat_input=money(bucket["vat_input"]),
            vat_input_available=bool(bucket["vat_input_available"]),
            vat_input_completeness=str(bucket["vat_input_completeness"]),
            profile_required=tax_profile_required,
        )
        margin_base = (
            tax.revenue_without_vat
            if tax.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO
            else net_revenue
        )
        row_status = _worse_status(
            _grouped_quality_status(
                bucket["statuses"],
                quantity=Decimal(bucket["quantity"]),
            ),
            tax.data_quality_status,
        )
        rows.append(
            UnitEconomicsRow(
                client_id=row_client_id,
                seller_account_id=seller_account_id,
                organization_id=organization_id,
                week_start=week_start,
                week_end=week_end,
                is_partial_week=is_partial_week(
                    week_start, week_end, report_period_start, report_period_end
                ),
                document_report=", ".join(sorted(bucket["document_reports"])),
                wb_report_id=", ".join(sorted(bucket["wb_report_ids"])),
                wb_report_date=", ".join(sorted(bucket["wb_report_dates"])),
                nm_id=nm_id,
                vendor_code=vendor_code,
                barcode=barcode,
                onec_item_id=onec_item_id,
                sales_model=sales_model,
                quantity=bucket["quantity"],
                sales_quantity=bucket["sales_quantity"],
                return_quantity=bucket["return_quantity"],
                return_amount=money(bucket["return_amount"]),
                return_rate_by_quantity=ratio(
                    bucket["return_quantity"], bucket["sales_quantity"]
                ),
                revenue_before_spp=revenue_before_spp,
                spp_discount=spp_discount,
                spp_discount_rate=ratio(spp_discount, revenue_before_spp),
                revenue_after_spp=net_revenue,
                spp_source_status=_spp_source_status(bucket["spp_source_statuses"]),
                net_revenue=net_revenue,
                wb_commission=money(bucket["wb_commission"]),
                logistics=money(bucket["logistics"]),
                storage=money(bucket["storage"]),
                acceptance=money(bucket["acceptance"]),
                wb_promotion=money(bucket["wb_promotion"]),
                penalties_and_holdbacks=money(bucket["penalties_and_holdbacks"]),
                acquiring=money(bucket["acquiring"]),
                cogs_from_1c_with_extra_costs=money(bucket["cogs"]),
                revenue_without_vat=tax.revenue_without_vat,
                gross_profit=gross_profit,
                vat_5_from_revenue=tax.vat,
                vat_output=tax.vat_output,
                vat_input=tax.vat_input,
                vat_input_from_wb=money(bucket["vat_input_from_wb"]),
                vat_input_from_1c=money(bucket["vat_input_from_1c"]),
                vat_input_difference=money(
                    bucket["vat_input_from_1c"] - bucket["vat_input_from_wb"]
                ),
                vat_input_completeness=str(bucket["vat_input_completeness"]),
                vat_payable=tax.vat_payable,
                usn_1_from_revenue=tax.revenue_tax,
                income_tax_kind=tax.income_tax_kind,
                income_tax_base=tax.income_tax_base,
                income_tax=tax.income_tax,
                income_tax_included=tax.income_tax_included,
                tax_completeness=tax.tax_completeness,
                profit_after_taxes=tax.profit_after_taxes,
                margin=ratio(gross_profit, margin_base),
                margin_after_taxes=ratio(tax.profit_after_taxes, margin_base),
                profit_per_unit=(
                    ratio(gross_profit, bucket["quantity"])
                    if bucket["quantity"] > 0
                    else None
                ),
                profit_after_taxes_per_unit=(
                    ratio(tax.profit_after_taxes, bucket["quantity"])
                    if bucket["quantity"] > 0
                    else None
                ),
                tax_method=tax.tax_method,
                tax_profile_source=tax.tax_profile_source,
                pnl_vat_mode=tax.pnl_vat_mode,
                data_quality_status=row_status,
                methodology_version=methodology_version,
                source_snapshot_hashes=tuple(sorted(set(bucket["hashes"]))),
            )
        )

    report_reconciliation_rows = []
    for key, bucket in report_grouped.items():
        (
            row_client_id,
            seller_account_id,
            organization_id,
            week_start,
            week_end,
            wb_report_id,
        ) = key
        net_revenue = money(bucket["net_revenue"])
        spp_discount = money(bucket["spp_discount"])
        revenue_before_spp = money(net_revenue + spp_discount)
        gross_profit = money(bucket["gross_profit"])
        tax = calculate_tax_amounts(
            net_revenue,
            gross_profit,
            _tax_profile_for(tax_profiles_by_org, organization_id, week_start),
            vat_input=money(bucket["vat_input"]),
            vat_input_available=bool(bucket["vat_input_available"]),
            vat_input_completeness=str(bucket["vat_input_completeness"]),
            profile_required=tax_profile_required,
        )
        margin_base = (
            tax.revenue_without_vat
            if tax.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO
            else net_revenue
        )
        row_status = _worse_status(bucket["status"], tax.data_quality_status)
        report_reconciliation_rows.append(
            ReportReconciliationRow(
                client_id=row_client_id,
                seller_account_id=seller_account_id,
                organization_id=organization_id,
                week_start=week_start,
                week_end=week_end,
                wb_report_id=wb_report_id,
                sales_quantity=bucket["sales_quantity"],
                return_quantity=bucket["return_quantity"],
                quantity=bucket["quantity"],
                revenue_before_spp=revenue_before_spp,
                spp_discount=spp_discount,
                spp_discount_rate=ratio(spp_discount, revenue_before_spp),
                revenue_after_spp=net_revenue,
                spp_source_status=_spp_source_status(bucket["spp_source_statuses"]),
                net_revenue=net_revenue,
                wb_commission=money(bucket["wb_commission"]),
                logistics=money(bucket["logistics"]),
                storage=money(bucket["storage"]),
                acceptance=money(bucket["acceptance"]),
                wb_promotion=money(bucket["wb_promotion"]),
                penalties_and_holdbacks=money(bucket["penalties_and_holdbacks"]),
                acquiring=money(bucket["acquiring"]),
                cogs_from_1c_with_extra_costs=money(bucket["cogs"]),
                revenue_without_vat=tax.revenue_without_vat,
                gross_profit=gross_profit,
                vat_5_from_revenue=tax.vat,
                vat_output=tax.vat_output,
                vat_input=tax.vat_input,
                vat_input_from_wb=money(bucket["vat_input_from_wb"]),
                vat_input_from_1c=money(bucket["vat_input_from_1c"]),
                vat_input_difference=money(
                    bucket["vat_input_from_1c"] - bucket["vat_input_from_wb"]
                ),
                vat_input_completeness=str(bucket["vat_input_completeness"]),
                vat_payable=tax.vat_payable,
                usn_1_from_revenue=tax.revenue_tax,
                income_tax_kind=tax.income_tax_kind,
                income_tax_base=tax.income_tax_base,
                income_tax=tax.income_tax,
                income_tax_included=tax.income_tax_included,
                tax_completeness=tax.tax_completeness,
                profit_after_taxes=tax.profit_after_taxes,
                margin=ratio(gross_profit, margin_base),
                margin_after_taxes=ratio(tax.profit_after_taxes, margin_base),
                tax_method=tax.tax_method,
                tax_profile_source=tax.tax_profile_source,
                pnl_vat_mode=tax.pnl_vat_mode,
                data_quality_status=row_status,
                source_row_count=int(bucket["source_row_count"]),
            )
        )

    onec_report_reconciliation_rows = []
    for key, bucket in onec_report_grouped.items():
        (
            row_client_id,
            seller_account_id,
            organization_id,
            document_date,
            week_start,
            week_end,
            document_kind,
            document_label,
        ) = key
        net_revenue = money(bucket["net_revenue"])
        spp_discount = money(bucket["spp_discount"])
        revenue_before_spp = money(net_revenue + spp_discount)
        gross_profit = money(bucket["gross_profit"])
        tax = calculate_tax_amounts(
            net_revenue,
            gross_profit,
            _tax_profile_for(tax_profiles_by_org, organization_id, document_date),
            vat_input=money(bucket["vat_input"]),
            vat_input_available=bool(bucket["vat_input_available"]),
            vat_input_completeness=str(bucket["vat_input_completeness"]),
            profile_required=tax_profile_required,
        )
        margin_base = (
            tax.revenue_without_vat
            if tax.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO
            else net_revenue
        )
        row_status = _worse_status(bucket["status"], tax.data_quality_status)
        onec_report_reconciliation_rows.append(
            OnecReportReconciliationRow(
                client_id=row_client_id,
                seller_account_id=seller_account_id,
                organization_id=organization_id,
                document_date=document_date,
                week_start=week_start,
                week_end=week_end,
                document_kind=document_kind,
                document_label=document_label,
                wb_report_ids=tuple(sorted(bucket["wb_report_ids"])),
                sales_quantity=bucket["sales_quantity"],
                return_quantity=bucket["return_quantity"],
                quantity=bucket["quantity"],
                sales_amount=money(bucket["sales_amount"]),
                return_amount=money(bucket["return_amount"]),
                revenue_before_spp=revenue_before_spp,
                spp_discount=spp_discount,
                spp_discount_rate=ratio(spp_discount, revenue_before_spp),
                revenue_after_spp=net_revenue,
                spp_source_status=_spp_source_status(bucket["spp_source_statuses"]),
                net_revenue=net_revenue,
                wb_commission=money(bucket["wb_commission"]),
                logistics=money(bucket["logistics"]),
                storage=money(bucket["storage"]),
                acceptance=money(bucket["acceptance"]),
                wb_promotion=money(bucket["wb_promotion"]),
                penalties_and_holdbacks=money(bucket["penalties_and_holdbacks"]),
                acquiring=money(bucket["acquiring"]),
                cogs_from_1c_with_extra_costs=money(bucket["cogs"]),
                revenue_without_vat=tax.revenue_without_vat,
                gross_profit=gross_profit,
                vat_5_from_revenue=tax.vat,
                vat_output=tax.vat_output,
                vat_input=tax.vat_input,
                vat_input_from_wb=money(bucket["vat_input_from_wb"]),
                vat_input_from_1c=money(bucket["vat_input_from_1c"]),
                vat_input_difference=money(
                    bucket["vat_input_from_1c"] - bucket["vat_input_from_wb"]
                ),
                vat_input_completeness=str(bucket["vat_input_completeness"]),
                vat_payable=tax.vat_payable,
                usn_1_from_revenue=tax.revenue_tax,
                income_tax_kind=tax.income_tax_kind,
                income_tax_base=tax.income_tax_base,
                income_tax=tax.income_tax,
                income_tax_included=tax.income_tax_included,
                tax_completeness=tax.tax_completeness,
                profit_after_taxes=tax.profit_after_taxes,
                margin=ratio(gross_profit, margin_base),
                margin_after_taxes=ratio(tax.profit_after_taxes, margin_base),
                tax_method=tax.tax_method,
                tax_profile_source=tax.tax_profile_source,
                pnl_vat_mode=tax.pnl_vat_mode,
                data_quality_status=row_status,
                source_row_count=int(bucket["source_row_count"]),
            )
        )

    onec_report_product_rows = []
    for key, bucket in onec_product_grouped.items():
        (
            row_client_id,
            seller_account_id,
            organization_id,
            document_date,
            week_start,
            week_end,
            document_kind,
            document_label,
            nm_id,
            vendor_code,
            barcode,
            onec_item_id,
            sales_model,
        ) = key
        net_revenue = money(bucket["net_revenue"])
        spp_discount = money(bucket["spp_discount"])
        revenue_before_spp = money(net_revenue + spp_discount)
        gross_profit = money(bucket["gross_profit"])
        tax = calculate_tax_amounts(
            net_revenue,
            gross_profit,
            _tax_profile_for(tax_profiles_by_org, organization_id, document_date),
            vat_input=money(bucket["vat_input"]),
            vat_input_available=bool(bucket["vat_input_available"]),
            vat_input_completeness=str(bucket["vat_input_completeness"]),
            profile_required=tax_profile_required,
        )
        margin_base = (
            tax.revenue_without_vat
            if tax.pnl_vat_mode == PNL_VAT_MODE_WITHOUT_VAT_FOR_OSNO
            else net_revenue
        )
        row_status = _worse_status(bucket["status"], tax.data_quality_status)
        onec_report_product_rows.append(
            OnecReportProductRow(
                client_id=row_client_id,
                seller_account_id=seller_account_id,
                organization_id=organization_id,
                document_date=document_date,
                week_start=week_start,
                week_end=week_end,
                document_kind=document_kind,
                document_label=document_label,
                wb_report_ids=tuple(sorted(bucket["wb_report_ids"])),
                nm_id=nm_id,
                vendor_code=vendor_code,
                barcode=barcode,
                onec_item_id=onec_item_id,
                sales_model=sales_model,
                sales_quantity=bucket["sales_quantity"],
                return_quantity=bucket["return_quantity"],
                quantity=bucket["quantity"],
                sales_amount=money(bucket["sales_amount"]),
                return_amount=money(bucket["return_amount"]),
                revenue_before_spp=revenue_before_spp,
                spp_discount=spp_discount,
                spp_discount_rate=ratio(spp_discount, revenue_before_spp),
                revenue_after_spp=net_revenue,
                spp_source_status=_spp_source_status(bucket["spp_source_statuses"]),
                net_revenue=net_revenue,
                wb_commission=money(bucket["wb_commission"]),
                logistics=money(bucket["logistics"]),
                storage=money(bucket["storage"]),
                acceptance=money(bucket["acceptance"]),
                wb_promotion=money(bucket["wb_promotion"]),
                penalties_and_holdbacks=money(bucket["penalties_and_holdbacks"]),
                acquiring=money(bucket["acquiring"]),
                cogs_from_1c_with_extra_costs=money(bucket["cogs"]),
                revenue_without_vat=tax.revenue_without_vat,
                gross_profit=gross_profit,
                vat_5_from_revenue=tax.vat,
                vat_output=tax.vat_output,
                vat_input=tax.vat_input,
                vat_input_from_wb=money(bucket["vat_input_from_wb"]),
                vat_input_from_1c=money(bucket["vat_input_from_1c"]),
                vat_input_difference=money(
                    bucket["vat_input_from_1c"] - bucket["vat_input_from_wb"]
                ),
                vat_input_completeness=str(bucket["vat_input_completeness"]),
                vat_payable=tax.vat_payable,
                usn_1_from_revenue=tax.revenue_tax,
                income_tax_kind=tax.income_tax_kind,
                income_tax_base=tax.income_tax_base,
                income_tax=tax.income_tax,
                income_tax_included=tax.income_tax_included,
                tax_completeness=tax.tax_completeness,
                profit_after_taxes=tax.profit_after_taxes,
                margin=ratio(gross_profit, margin_base),
                margin_after_taxes=ratio(tax.profit_after_taxes, margin_base),
                profit_per_unit=(
                    ratio(gross_profit, bucket["quantity"])
                    if bucket["quantity"] > 0
                    else None
                ),
                profit_after_taxes_per_unit=(
                    ratio(tax.profit_after_taxes, bucket["quantity"])
                    if bucket["quantity"] > 0
                    else None
                ),
                tax_method=tax.tax_method,
                tax_profile_source=tax.tax_profile_source,
                pnl_vat_mode=tax.pnl_vat_mode,
                data_quality_status=row_status,
                source_row_count=int(bucket["source_row_count"]),
                source_snapshot_hashes=tuple(sorted(set(bucket["hashes"]))),
            )
        )

    expense_allocation_rows = []
    for key, bucket in allocation_grouped.items():
        (
            row_client_id,
            seller_account_id,
            organization_id,
            week_start,
            week_end,
            document_label,
            expense_category,
            nm_id,
            vendor_code,
            barcode,
            onec_item_id,
        ) = key
        control_amount = bucket["control_amount"]
        scaling_coefficient = bucket["scaling_coefficient"]
        expense_allocation_rows.append(
            ExpenseAllocationRow(
                client_id=row_client_id,
                seller_account_id=seller_account_id,
                organization_id=organization_id,
                week_start=week_start,
                week_end=week_end,
                document_label=document_label,
                wb_report_ids=tuple(sorted(bucket["wb_report_ids"])),
                expense_category=expense_category,
                nm_id=nm_id,
                vendor_code=vendor_code,
                barcode=barcode,
                onec_item_id=onec_item_id,
                api_base_amount=money(bucket["api_base_amount"]),
                distribution_base_amount=money(bucket["distribution_base_amount"]),
                api_total_amount=money(bucket["api_total_amount"]),
                control_amount=(
                    None if control_amount is None else money(control_amount)
                ),
                allocated_amount=money(bucket["allocated_amount"]),
                scaling_coefficient=(
                    None
                    if scaling_coefficient is None
                    else scaling_coefficient.quantize(
                        Decimal("0.000001"), rounding=ROUND_HALF_UP
                    )
                ),
                distribution_method=str(bucket["distribution_method"]),
                allocation_status=str(bucket["allocation_status"]),
                source_row_count=int(bucket["source_row_count"]),
            )
        )

    tax_input_reconciliation_rows = []
    for key, bucket in tax_input_grouped.items():
        (
            row_client_id,
            seller_account_id,
            organization_id,
            week_start,
            week_end,
        ) = key
        vat_input_from_wb = money(bucket["vat_input_from_wb"])
        vat_input_from_1c = money(bucket["vat_input_from_1c"])
        reconciliation_status = _worse_vat_input_completeness(
            str(bucket["vat_input_completeness"]),
            _vat_input_reconciliation_status(vat_input_from_wb, vat_input_from_1c),
        )
        tax_input_reconciliation_rows.append(
            TaxInputReconciliationRow(
                client_id=row_client_id,
                seller_account_id=seller_account_id,
                organization_id=organization_id,
                week_start=week_start,
                week_end=week_end,
                vat_input_from_wb=vat_input_from_wb,
                vat_input_from_1c=vat_input_from_1c,
                vat_input_difference=money(vat_input_from_1c - vat_input_from_wb),
                vat_input_completeness=reconciliation_status,
                source_row_count=int(bucket["source_row_count"]),
            )
        )

    status = (
        ReportStatus.PARTIAL_PERIOD
        if as_of_date <= report_period_end
        else ReportStatus.FINAL
    )
    return UnitEconomicsReport(
        client_id=client_id,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        source_coverage_start=source_coverage_start,
        source_coverage_end=source_coverage_end,
        generated_at=generated_at,
        status=status,
        methodology_version=methodology_version,
        rows=sorted(
            rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.organization_id,
                row.nm_id or 0,
                row.vendor_code,
            ),
        ),
        report_reconciliation_rows=sorted(
            report_reconciliation_rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.organization_id,
                row.wb_report_id,
            ),
        ),
        onec_report_reconciliation_rows=sorted(
            onec_report_reconciliation_rows,
            key=lambda row: (
                row.week_start,
                row.document_kind.value,
                row.seller_account_id,
                row.organization_id,
            ),
        ),
        onec_report_product_rows=sorted(
            onec_report_product_rows,
            key=lambda row: (
                row.week_start,
                row.document_kind.value,
                row.seller_account_id,
                row.organization_id,
                row.nm_id or 0,
                row.vendor_code,
            ),
        ),
        expense_allocation_rows=sorted(
            expense_allocation_rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.document_label,
                row.expense_category,
                row.nm_id or 0,
                row.vendor_code,
            ),
        ),
        tax_input_reconciliation_rows=sorted(
            tax_input_reconciliation_rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.organization_id,
            ),
        ),
        wb_sales_report_summary_rows=sorted(
            wb_sales_report_summary_rows,
            key=lambda row: (
                row.date_from,
                row.seller_account_id,
                row.report_type or 0,
                row.report_id,
            ),
        ),
    )


def _index_mappings(
    mappings: list[SkuMapping],
) -> dict[tuple[str, str, int | None, str, str], SkuMapping]:
    return {
        (
            item.client_id,
            item.seller_account_id,
            item.nm_id,
            _vendor_code_key(item.vendor_code),
            item.barcode,
        ): item
        for item in mappings
    }


def _index_costs(
    costs: list[OnecUnfCostSnapshot],
) -> _CostIndex:
    by_item: dict[tuple[str, str, str, str], list[OnecUnfCostSnapshot]] = defaultdict(
        list
    )
    by_article: dict[tuple[str, str, str], list[OnecUnfCostSnapshot]] = defaultdict(
        list
    )
    for item in costs:
        by_item[
            (
                item.client_id,
                item.organization_id,
                item.onec_item_id,
                item.characteristic,
            )
        ].append(item)
        article_key = _vendor_code_key(item.article)
        if article_key:
            by_article[(item.client_id, item.organization_id, article_key)].append(item)
    return _CostIndex(by_item=by_item, by_article=by_article)


def _find_mapping(
    snapshot: WbApiSnapshot,
    mapping_index: dict[tuple[str, str, int | None, str, str], SkuMapping],
) -> SkuMapping | None:
    candidates = [
        (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.nm_id,
            _vendor_code_key(snapshot.vendor_code),
            snapshot.barcode,
        ),
        (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.nm_id,
            _vendor_code_key(snapshot.vendor_code),
            "",
        ),
        (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.nm_id,
            "",
            snapshot.barcode,
        ),
    ]
    for candidate in candidates:
        if candidate in mapping_index:
            return mapping_index[candidate]
    return None


def _find_cost(
    snapshot: WbApiSnapshot,
    mapping: SkuMapping | None,
    cost_index: _CostIndex,
) -> OnecUnfCostSnapshot | None:
    if mapping is None or not mapping.onec_item_id:
        return None
    candidates = cost_index.by_item.get(
        (
            snapshot.client_id,
            snapshot.organization_id,
            mapping.onec_item_id,
            mapping.onec_characteristic,
        ),
        [],
    )
    if not candidates and not mapping.onec_characteristic:
        item_candidates = [
            item
            for key, values in cost_index.by_item.items()
            if key[:3]
            == (snapshot.client_id, snapshot.organization_id, mapping.onec_item_id)
            for item in values
        ]
        characteristics = {item.characteristic for item in item_candidates}
        if len(characteristics) == 1:
            candidates = item_candidates
    article_fallback = False
    if not candidates and mapping.onec_article and not mapping.onec_characteristic:
        article_candidates = cost_index.by_article.get(
            (
                snapshot.client_id,
                snapshot.organization_id,
                _vendor_code_key(mapping.onec_article),
            ),
            [],
        )
        item_ids = {item.onec_item_id for item in article_candidates}
        characteristics = {item.characteristic for item in article_candidates}
        if len(item_ids) == 1 and len(characteristics) == 1:
            candidates = article_candidates
            article_fallback = True
    effective = [
        item
        for item in candidates
        if item.is_effective_for(snapshot.period_start, snapshot.period_end)
    ]
    if effective:
        valued_effective = [item for item in effective if _cost_has_value(item)]
        if valued_effective:
            cost = max(valued_effective, key=lambda item: item.effective_from)
        else:
            valued_candidates = [item for item in candidates if _cost_has_value(item)]
            cost = (
                _mark_cost_needs_review(
                    min(
                        valued_candidates,
                        key=lambda item: _cost_distance_key(
                            item,
                            snapshot.period_start,
                            snapshot.period_end,
                        ),
                    ),
                    (
                        "nearest non-zero 1C cost because effective cost is zero "
                        f"for {snapshot.period_start.isoformat()}.."
                        f"{snapshot.period_end.isoformat()}"
                    ),
                )
                if valued_candidates
                else max(effective, key=lambda item: item.effective_from)
            )
        if article_fallback:
            return _mark_cost_needs_review(
                cost,
                (
                    "article fallback because mapped 1C item "
                    f"{mapping.onec_item_id} has no cost snapshot"
                ),
            )
        return cost
    nearest = min(
        candidates,
        key=lambda item: _cost_distance_key(
            item,
            snapshot.period_start,
            snapshot.period_end,
        ),
        default=None,
    )
    if nearest is None:
        return None
    if not _cost_has_value(nearest):
        valued_candidates = [item for item in candidates if _cost_has_value(item)]
        if valued_candidates:
            nearest = _mark_cost_needs_review(
                min(
                    valued_candidates,
                    key=lambda item: _cost_distance_key(
                        item,
                        snapshot.period_start,
                        snapshot.period_end,
                    ),
                ),
                (
                    "nearest non-zero 1C cost because nearest available cost is "
                    f"zero for {snapshot.period_start.isoformat()}.."
                    f"{snapshot.period_end.isoformat()}"
                ),
            )
    cost = _mark_cost_needs_review(
        nearest,
        (
            "nearest available cost for "
            f"{snapshot.period_start.isoformat()}..{snapshot.period_end.isoformat()}"
        ),
    )
    if article_fallback:
        cost = _mark_cost_needs_review(
            cost,
            (
                "article fallback because mapped 1C item "
                f"{mapping.onec_item_id} has no cost snapshot"
            ),
        )
    return cost


def _cost_has_value(cost: OnecUnfCostSnapshot) -> bool:
    return cost.cost_with_extra_costs != 0


def _mark_cost_needs_review(
    cost: OnecUnfCostSnapshot,
    reason: str,
) -> OnecUnfCostSnapshot:
    if "needs_review" in cost.cost_method and reason in cost.source_document:
        return cost
    cost_method = cost.cost_method
    if "needs_review" not in cost_method:
        cost_method = f"{cost_method}_needs_review"
    return cost.model_copy(
        update={
            "cost_method": cost_method,
            "source_document": f"{cost.source_document}; {reason}",
        }
    )


def _cost_distance_key(
    cost: OnecUnfCostSnapshot,
    period_start: date,
    period_end: date,
) -> tuple[int, int, int]:
    if cost.effective_to is not None and cost.effective_to < period_start:
        return (
            (period_start - cost.effective_to).days,
            0,
            -cost.effective_from.toordinal(),
        )
    if cost.effective_from > period_end:
        return (
            (cost.effective_from - period_end).days,
            1,
            cost.effective_from.toordinal(),
        )
    return (0, 0, -cost.effective_from.toordinal())


def _usable_cost_value(
    mapping: SkuMapping | None,
    cost: OnecUnfCostSnapshot | None,
) -> Decimal:
    if mapping is None or mapping.status != MappingStatus.MATCHED or cost is None:
        return Decimal("0")
    return cost.cost_with_extra_costs


def _cost_value_is_without_vat(cost: OnecUnfCostSnapshot | None) -> bool:
    if cost is None:
        return False
    markers = (
        cost.cost_method.casefold(),
        cost.source_document.casefold(),
    )
    return any(
        "without_vat" in marker
        or "безндс" in marker.replace(" ", "")
        or "себестоимостьбезндс" in marker.replace(" ", "")
        for marker in markers
    )


def _pnl_cost_value(
    mapping: SkuMapping | None,
    cost: OnecUnfCostSnapshot | None,
    cost_input_vat: Decimal | None,
) -> Decimal:
    cost_value = _usable_cost_value(mapping, cost)
    if cost_value == 0 or cost is None or _cost_value_is_without_vat(cost):
        return cost_value
    if cost_input_vat is None:
        return cost_value
    return cost_value - cost_input_vat


def _goods_quantity(snapshot: WbApiSnapshot) -> Decimal:
    if (
        snapshot.operation_type.strip().lower() in GOODS_MOVEMENT_OPERATIONS
        and snapshot.net_revenue != 0
    ):
        return snapshot.quantity
    return Decimal("0")


def _service_vat_required(
    snapshot: WbApiSnapshot,
    controlled_expenses: _ControlledExpenses,
) -> bool:
    service_gross = (
        snapshot.wb_commission
        + snapshot.logistics
        + controlled_expenses.storage.allocated
        + snapshot.acceptance
        + controlled_expenses.wb_promotion.allocated
        + snapshot.acquiring
    )
    return service_gross != 0


def _is_penalty_only_snapshot(snapshot: WbApiSnapshot) -> bool:
    return (
        snapshot.quantity == 0
        and snapshot.net_revenue == 0
        and snapshot.wb_commission == 0
        and snapshot.logistics == 0
        and snapshot.storage == 0
        and snapshot.acceptance == 0
        and snapshot.wb_promotion == 0
        and snapshot.acquiring == 0
        and snapshot.penalties_and_holdbacks != 0
    )


def _new_onec_bucket(*, include_hashes: bool = False) -> dict[str, object]:
    bucket: dict[str, object] = {
        "sales_quantity": Decimal("0"),
        "return_quantity": Decimal("0"),
        "quantity": Decimal("0"),
        "sales_amount": Decimal("0"),
        "return_amount": Decimal("0"),
        "spp_discount": Decimal("0"),
        "spp_source_statuses": set(),
        "net_revenue": Decimal("0"),
        "wb_commission": Decimal("0"),
        "logistics": Decimal("0"),
        "storage": Decimal("0"),
        "acceptance": Decimal("0"),
        "wb_promotion": Decimal("0"),
        "penalties_and_holdbacks": Decimal("0"),
        "acquiring": Decimal("0"),
        "cogs": Decimal("0"),
        "vat_input": Decimal("0"),
        "vat_input_from_wb": Decimal("0"),
        "vat_input_from_1c": Decimal("0"),
        "vat_input_completeness": VAT_INPUT_CONFIRMED,
        "vat_input_available": True,
        "gross_profit": Decimal("0"),
        "status": DataQualityStatus.RELIABLE,
        "source_row_count": 0,
        "wb_report_ids": set(),
    }
    if include_hashes:
        bucket["hashes"] = []
    return bucket


def _add_to_onec_bucket(
    bucket: dict[str, object],
    *,
    snapshot: WbApiSnapshot,
    goods_quantity: Decimal,
    cogs: Decimal,
    input_vat: Decimal,
    input_vat_from_wb: Decimal,
    input_vat_from_1c: Decimal,
    input_vat_completeness: str,
    input_vat_available: bool,
    gross_profit: Decimal,
    storage: Decimal,
    wb_promotion: Decimal,
    spp_discount: Decimal,
    spp_source_status: str,
    quality_status: DataQualityStatus,
) -> None:
    if goods_quantity > 0:
        bucket["sales_quantity"] += goods_quantity
        bucket["sales_amount"] += snapshot.net_revenue
    elif goods_quantity < 0:
        bucket["return_quantity"] += abs(goods_quantity)
        bucket["return_amount"] += abs(snapshot.net_revenue)
    bucket["quantity"] += goods_quantity
    bucket["spp_discount"] += spp_discount
    bucket["spp_source_statuses"].add(spp_source_status)
    bucket["net_revenue"] += snapshot.net_revenue
    bucket["wb_commission"] += snapshot.wb_commission
    bucket["logistics"] += snapshot.logistics
    bucket["storage"] += storage
    bucket["acceptance"] += snapshot.acceptance
    bucket["wb_promotion"] += wb_promotion
    bucket["penalties_and_holdbacks"] += snapshot.penalties_and_holdbacks
    bucket["acquiring"] += snapshot.acquiring
    bucket["cogs"] += cogs
    bucket["vat_input"] += input_vat
    bucket["vat_input_from_wb"] += input_vat_from_wb
    bucket["vat_input_from_1c"] += input_vat_from_1c
    bucket["vat_input_completeness"] = _worse_vat_input_completeness(
        str(bucket["vat_input_completeness"]),
        input_vat_completeness,
    )
    bucket["vat_input_available"] = (
        bucket["vat_input_available"] and input_vat_available
    )
    bucket["gross_profit"] += gross_profit
    bucket["status"] = _worse_status(bucket["status"], quality_status)
    bucket["source_row_count"] += 1
    bucket["wb_report_ids"].add(snapshot.wb_report_id or "Без номера")
    if "hashes" in bucket:
        bucket["hashes"].append(snapshot.raw_payload_hash)


def _add_expense_allocation_rows(
    allocation_grouped: dict[tuple[object, ...], dict[str, object]],
    *,
    snapshot: WbApiSnapshot,
    week_start: date,
    week_end: date,
    document_label: str,
    mapped_onec_item_id: str | None,
    storage: _CategoryAllocation,
    wb_promotion: _CategoryAllocation,
) -> None:
    for expense_category, allocation in (
        (EXPENSE_STORAGE, storage),
        (EXPENSE_WB_PROMOTION, wb_promotion),
    ):
        if (
            allocation.api_base_amount == 0
            and allocation.distribution_base_amount == 0
            and allocation.allocated == 0
            and (allocation.control_amount is None or allocation.control_amount == 0)
        ):
            continue
        key = (
            snapshot.client_id,
            snapshot.seller_account_id,
            snapshot.organization_id,
            week_start,
            week_end,
            document_label,
            expense_category,
            snapshot.nm_id,
            snapshot.vendor_code,
            snapshot.barcode,
            mapped_onec_item_id,
        )
        if key not in allocation_grouped:
            allocation_grouped[key] = {
                "api_base_amount": Decimal("0"),
                "distribution_base_amount": Decimal("0"),
                "api_total_amount": allocation.api_total_amount,
                "control_amount": allocation.control_amount,
                "allocated_amount": Decimal("0"),
                "scaling_coefficient": allocation.scaling_coefficient,
                "distribution_method": allocation.distribution_method,
                "allocation_status": allocation.allocation_status,
                "source_row_count": 0,
                "wb_report_ids": set(allocation.wb_report_ids),
            }
        bucket = allocation_grouped[key]
        bucket["api_base_amount"] += allocation.api_base_amount
        bucket["distribution_base_amount"] += allocation.distribution_base_amount
        bucket["api_total_amount"] = allocation.api_total_amount
        bucket["control_amount"] = allocation.control_amount
        bucket["allocated_amount"] += allocation.allocated
        bucket["scaling_coefficient"] = allocation.scaling_coefficient
        bucket["distribution_method"] = allocation.distribution_method
        bucket["allocation_status"] = allocation.allocation_status
        bucket["source_row_count"] += allocation.source_row_count
        bucket["wb_report_ids"].update(allocation.wb_report_ids)


def _onec_report_kind(wb_report_id: str) -> OnecReportKind:
    report_id = wb_report_id.strip()
    if report_id.isdigit() and len(report_id) >= 15 and report_id.endswith("1"):
        return OnecReportKind.BUYOUT_NOTICE
    return OnecReportKind.COMMISSIONER_REPORT


def _onec_document_label(kind: OnecReportKind) -> str:
    if kind is OnecReportKind.BUYOUT_NOTICE:
        return "Уведомление о выкупе"
    return "Отчет комиссионера"


def _document_report_filter_label(
    document_label: str,
    week_start: date,
    week_end: date,
    report_period_start: date,
    report_period_end: date,
) -> str:
    display_start = max(week_start, report_period_start)
    display_end = min(week_end, report_period_end)
    return (
        f"{document_label} · "
        f"{display_start:%d.%m.%Y}-{display_end:%d.%m.%Y} · "
        f"закрытие {week_end:%d.%m.%Y}"
    )


def _quality_status(
    snapshot: WbApiSnapshot,
    mapping: SkuMapping | None,
    cost: OnecUnfCostSnapshot | None,
    account_to_org: dict[str, str],
    *,
    report_type_status: DataQualityStatus = DataQualityStatus.RELIABLE,
) -> DataQualityStatus:
    if account_to_org.get(snapshot.seller_account_id) != snapshot.organization_id:
        return DataQualityStatus.ACCOUNT_ORG_MISMATCH
    if not _has_product_identity(snapshot):
        return DataQualityStatus.EXPENSE_WITHOUT_SKU
    if mapping is None or mapping.status == MappingStatus.MISSING:
        return DataQualityStatus.MISSING_MAPPING
    if mapping.status == MappingStatus.AMBIGUOUS:
        return DataQualityStatus.AMBIGUOUS_MAPPING
    if mapping.status == MappingStatus.EXCLUDED:
        return DataQualityStatus.EXCLUDED
    if cost is None:
        return DataQualityStatus.MISSING_COST
    if _goods_quantity(snapshot) != 0 and cost.cost_with_extra_costs == 0:
        return DataQualityStatus.MISSING_COST
    if "needs_review" in cost.cost_method:
        return DataQualityStatus.NEEDS_REVIEW
    if snapshot.is_partial_source:
        return DataQualityStatus.PARTIAL_SOURCE
    if report_type_status is DataQualityStatus.REPORT_TYPE_FALLBACK:
        return DataQualityStatus.REPORT_TYPE_FALLBACK
    return DataQualityStatus.RELIABLE


def _worse_status(
    left: DataQualityStatus, right: DataQualityStatus
) -> DataQualityStatus:
    return left if STATUS_PRIORITY[left] >= STATUS_PRIORITY[right] else right


def _grouped_quality_status(
    statuses: set[DataQualityStatus],
    *,
    quantity: Decimal,
) -> DataQualityStatus:
    effective = set(statuses)
    if quantity == 0:
        effective.discard(DataQualityStatus.MISSING_COST)
        effective.discard(DataQualityStatus.NEEDS_REVIEW)
    if not effective:
        return DataQualityStatus.RELIABLE
    return max(effective, key=STATUS_PRIORITY.__getitem__)


def _spp_source_status(statuses: object) -> str:
    if not isinstance(statuses, set) or not statuses:
        return "СПП не передается текущим источником"
    if any("cashbackDiscountSum" in str(status) for status in statuses):
        return "СПП из WB sales-reports/list cashbackDiscountSum"
    return "СПП не передается текущим источником"


def _vendor_code_key(value: str) -> str:
    return value.strip().lower()
