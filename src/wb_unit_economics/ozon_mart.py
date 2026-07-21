from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from wb_unit_economics.calculation import (
    VAT_INPUT_CONFIRMED,
    VAT_INPUT_PARTIAL,
    calculate_tax_amounts,
    tax_profile_is_configured,
    tax_profile_is_confirmed,
    tax_profile_is_osno,
)
from wb_unit_economics.contracts import TaxProfile

_ARTICLE_LABELS = {
    "revenue": "Выручка 1C Ozon SKU (без выкупов)",
    "commission": "Базовое вознаграждение Ozon",
    "services": "Услуги Ozon",
    "partner_services": "Услуги партнеров / перевыставление",
    "logistics": "Услуги доставки Ozon",
    "storage": "Хранение / размещение",
    "promotion": "Реклама и продвижение",
    "compensation": "Компенсации",
    "other": "Другие услуги Ozon",
    "cogs": "Себестоимость 1C по SKU (НДС не выделен)",
    "profit": "Прибыль до налогов по SKU",
}

_ARTICLE_GROUPS = {
    "revenue": "revenue",
    "commission": "marketplace_fee",
    "services": "services",
    "partner_services": "services",
    "logistics": "logistics",
    "storage": "storage",
    "promotion": "promotion",
    "compensation": "compensation",
    "other": "other",
    "cogs": "cogs",
    "profit": "result",
}

_ARTICLE_SORT = {
    "revenue": 10,
    "commission": 30,
    "logistics": 40,
    "storage": 45,
    "services": 50,
    "partner_services": 55,
    "promotion": 60,
    "other": 70,
    "compensation": 75,
    "cogs": 90,
    "profit": 100,
}

_COST_MIN_REFERENCE_MONTHS = 2
_COST_LOW_RATIO = Decimal("0.5")
_COST_HIGH_RATIO = Decimal("2")
_COST_MATERIALITY_MINIMUM = Decimal("100000")
_COST_MATERIALITY_REVENUE_RATE = Decimal("0.005")


class OzonSourceRow(Protocol):
    row_number: int
    source_row_id: str
    row_payload: dict[str, Any] | None


MappingResolver = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass
class _MartContext:
    row_number: int
    source_row_id: str
    candidate: dict[str, Any]
    mapping: dict[str, Any]
    quantity: Decimal
    realization_amount: Decimal | None
    expenses: dict[str, Decimal]
    expenses_loaded: bool


def empty_ozon_mart_payload(limit: int = 0) -> dict[str, Any]:
    return {
        "status": "not_started",
        "message": "Запустите Ozon + 1C, чтобы увидеть расчетную витрину Ozon.",
        "basis": "staff_only_ozon_unit_economics_mart_v1",
        "rowCount": 0,
        "previewLimit": limit,
        "previewRowCount": 0,
        "previewLimited": False,
        "summary": _empty_summary(),
        "totals": _empty_totals(),
        "closedPeriodTotals": _empty_totals(),
        "excludedOpenPeriods": [],
        "excludedIncompletePeriods": [],
        "monthly": [],
        "costQuality": _empty_cost_quality(),
        "reconciliationTotals": _empty_reconciliation_totals(),
        "taxProfile": _tax_profile_payload(None, required=True),
        "profitAliasDeprecated": True,
        "expenseAttribution": _empty_expense_attribution(),
        "articleRows": [],
        "articleDrilldown": [],
        "issues": [],
        "rows": [],
    }


def build_ozon_unit_economics_mart(
    *,
    realization_rows: Sequence[OzonSourceRow],
    commissioner_rows: Sequence[OzonSourceRow],
    unit_costs: Mapping[str, Decimal],
    mapping_resolver: MappingResolver,
    buyout_reconciliation: Mapping[str, Any] | None = None,
    period_expense_amount: Any = None,
    period_expense_articles: Sequence[Mapping[str, Any]] | None = None,
    period_expense_basis: str = "",
    period_start: date | None = None,
    period_end: date | None = None,
    preview_limit: int = 50,
    tax_profile: TaxProfile | None = None,
    tax_profile_required: bool = True,
    input_vat_by_item: Mapping[str, Decimal] | None = None,
    reference_unit_costs: Mapping[str, Sequence[Decimal]] | None = None,
    direct_1c_cost_control: Mapping[str, Any] | None = None,
    cost_materiality_minimum: Decimal = _COST_MATERIALITY_MINIMUM,
    cost_materiality_revenue_rate: Decimal = _COST_MATERIALITY_REVENUE_RATE,
    organization_scope_status: str = "ready",
) -> dict[str, Any]:
    preview_limit = max(0, int(preview_limit))
    revenue_by_item, has_commissioner = _onec_commissioner_revenue_by_item(
        commissioner_rows,
        period_start=period_start,
        period_end=period_end,
    )
    contexts = _realization_contexts(realization_rows, mapping_resolver)
    groups = _group_contexts(contexts)
    identity_count_by_onec_item = _identity_count_by_onec_item(groups)

    all_rows: list[dict[str, Any]] = []
    summary = _empty_summary()
    totals = _empty_totals()
    for index, group in enumerate(groups, start=1):
        row = _mart_row_payload(
            index=index,
            group=group,
            revenue_by_item=revenue_by_item,
            has_commissioner=has_commissioner,
            unit_costs=unit_costs,
            identity_count_by_onec_item=identity_count_by_onec_item,
            input_vat_by_item=input_vat_by_item or {},
            period_start=period_start,
            period_end=period_end,
        )
        all_rows.append(row)
        _increment_summary(summary, row["qualityStatus"], row["expenseStatus"])
        _increment_totals(totals, row)

    _append_buyout_row(
        all_rows,
        summary=summary,
        totals=totals,
        reconciliation=buyout_reconciliation or {},
        period_start=period_start,
        period_end=period_end,
    )
    expense_attribution = _allocate_period_expenses(
        all_rows,
        amount=_decimal_or_none(period_expense_amount),
        articles=period_expense_articles or (),
        basis=period_expense_basis,
    )
    cost_quality = _apply_cost_quality(
        all_rows,
        reference_unit_costs=reference_unit_costs or {},
        direct_1c_cost_control=direct_1c_cost_control or {},
        materiality_minimum=cost_materiality_minimum,
        materiality_revenue_rate=cost_materiality_revenue_rate,
    )
    if organization_scope_status == "missing_1c_organization":
        _apply_missing_organization_scope(all_rows, cost_quality)
        expense_attribution = _empty_expense_attribution()
        expense_attribution.update(
            {
                "status": "blocked",
                "message": "Выберите организацию 1C до расчета расходов Ozon.",
            }
        )
    _apply_tax_profile_to_rows(
        all_rows,
        tax_profile=tax_profile,
        profile_required=tax_profile_required,
    )
    summary = _summary_for_rows(all_rows)
    totals = _totals_for_rows(all_rows)
    _apply_tax_totals(totals, all_rows)
    _mark_partial_expense_totals(totals, summary)
    if int(summary.get("missing1cCommissioner") or 0):
        for key in (
            "onecRevenue",
            "cogs",
            "ozonExpenses",
            "profit",
            "margin",
            "profitBeforeTax",
            "marginBeforeTax",
            "profitBeforeIncomeTax",
            "profitAfterTax",
            "marginAfterTax",
        ):
            totals[key] = None

    row_count = len(all_rows)
    rows = all_rows[:preview_limit] if preview_limit else []
    status = _mart_status(row_count, summary)
    if status == "ready" and cost_quality["status"] == "blocked":
        status = "partial_source"
    _block_incomplete_profit_totals(
        totals,
        summary=summary,
        cost_quality=cost_quality,
    )
    open_period = bool(int(summary.get("missing1cCommissioner") or 0))
    incomplete_reasons = (
        []
        if open_period
        else _incomplete_period_reasons(summary, cost_quality=cost_quality)
    )
    period_is_eligible = status == "ready" and cost_quality["status"] in {
        "complete",
        "warning",
    }
    return {
        "status": status,
        "message": _mart_message_with_cost_quality(status, summary, cost_quality),
        "basis": "staff_only_ozon_unit_economics_mart_v1",
        "rowCount": row_count,
        "previewLimit": preview_limit,
        "previewRowCount": len(rows),
        "previewLimited": row_count > len(rows),
        "summary": summary,
        "totals": totals,
        "closedPeriodTotals": dict(totals) if period_is_eligible else _empty_totals(),
        "excludedOpenPeriods": (
            [
                {
                    "periodStart": period_start.isoformat() if period_start else None,
                    "periodEnd": period_end.isoformat() if period_end else None,
                    "reason": "missing_1c_commissioner",
                }
            ]
            if open_period
            else []
        ),
        "excludedIncompletePeriods": (
            [
                {
                    "periodStart": period_start.isoformat() if period_start else None,
                    "periodEnd": period_end.isoformat() if period_end else None,
                    "reason": incomplete_reasons[0],
                    "reasons": incomplete_reasons,
                }
            ]
            if incomplete_reasons
            else []
        ),
        "monthly": [],
        "costQuality": cost_quality,
        "reconciliationTotals": _empty_reconciliation_totals(),
        "taxProfile": _tax_profile_payload(
            tax_profile,
            required=tax_profile_required,
        ),
        "organizationScopeStatus": organization_scope_status,
        "profitAliasDeprecated": True,
        "expenseAttribution": expense_attribution,
        "articleRows": _mart_article_rows(all_rows, totals),
        "articleDrilldown": _mart_article_drilldown_rows(all_rows),
        "issues": [*_mart_issues(summary), *_cost_quality_issues(cost_quality)],
        "rows": rows,
        "periodFilter": {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
        },
    }


def combine_ozon_monthly_marts(
    monthly_marts: Sequence[Mapping[str, Any]],
    *,
    preview_limit: int = 50,
) -> dict[str, Any]:
    preview_limit = max(0, int(preview_limit))
    all_rows: list[dict[str, Any]] = []
    monthly: list[dict[str, Any]] = []
    excluded_open_periods: list[dict[str, Any]] = []
    excluded_incomplete_periods: list[dict[str, Any]] = []
    closed_marts: list[Mapping[str, Any]] = []
    row_count = 0
    for mart in monthly_marts:
        period_filter = mart.get("periodFilter") or {}
        period_start = period_filter.get("periodStart")
        period_end = period_filter.get("periodEnd")
        mart_rows = [dict(item) for item in mart.get("rows") or []]
        row_count += int(mart.get("rowCount") or len(mart_rows))
        period_key = str(period_start or "period")[:7]
        for index, row in enumerate(mart_rows, start=1):
            row["id"] = f"ozon-mart-{period_key}-{index}"
        all_rows.extend(mart_rows)
        summary = dict(mart.get("summary") or {})
        monthly.append(
            {
                "periodStart": period_start,
                "periodEnd": period_end,
                "status": mart.get("status") or "not_started",
                "rowCount": int(mart.get("rowCount") or len(mart_rows)),
                "previewLimited": bool(mart.get("previewLimited")),
                "summary": summary,
                "totals": dict(mart.get("totals") or {}),
                "taxProfile": dict(mart.get("taxProfile") or {}),
                "costQuality": dict(mart.get("costQuality") or {}),
                "organizationScopeStatus": mart.get("organizationScopeStatus")
                or "ready",
            }
        )
        mart_open_periods = [
            dict(item) for item in mart.get("excludedOpenPeriods") or []
        ]
        if mart_open_periods:
            excluded_open_periods.extend(mart_open_periods)
        elif int(summary.get("missing1cCommissioner") or 0):
            excluded_open_periods.append(
                {
                    "periodStart": period_start,
                    "periodEnd": period_end,
                    "reason": "missing_1c_commissioner",
                }
            )
        else:
            cost_quality = dict(mart.get("costQuality") or _empty_cost_quality())
            mart_incomplete_periods = [
                dict(item) for item in mart.get("excludedIncompletePeriods") or []
            ]
            reasons = (
                list(mart_incomplete_periods[0].get("reasons") or [])
                if mart_incomplete_periods
                else _incomplete_period_reasons(summary, cost_quality=cost_quality)
            )
            if (
                not reasons
                and int(mart.get("rowCount") or len(mart_rows)) == 0
                and mart.get("status") != "ready"
            ):
                reasons = ["missing_ozon_realization"]
            if reasons:
                if mart_incomplete_periods:
                    excluded_incomplete_periods.extend(mart_incomplete_periods)
                else:
                    excluded_incomplete_periods.append(
                        {
                            "periodStart": period_start,
                            "periodEnd": period_end,
                            "reason": reasons[0],
                            "reasons": reasons,
                        }
                    )
            elif mart.get("status") == "ready" and cost_quality.get(
                "status"
            ) in {"complete", "warning"}:
                closed_marts.append(mart)

    summary = _combine_monthly_summaries(monthly_marts)
    totals = _combine_monthly_totals(monthly_marts)
    closed_totals = _combine_monthly_totals(closed_marts)
    if excluded_open_periods or excluded_incomplete_periods:
        for key in (
            "profit",
            "margin",
            "profitBeforeTax",
            "marginBeforeTax",
            "profitBeforeIncomeTax",
            "profitAfterTax",
            "marginAfterTax",
        ):
            totals[key] = None
    rows = all_rows[:preview_limit] if preview_limit else []
    status = (
        "partial_source"
        if excluded_open_periods or excluded_incomplete_periods
        else _mart_status(row_count, summary)
    )
    cost_quality = _combine_cost_quality(monthly_marts)
    tax_profiles = [
        dict(item.get("taxProfile") or {})
        for item in monthly_marts
        if item.get("taxProfile")
    ]
    tax_profile = (
        tax_profiles[0]
        if tax_profiles
        else _tax_profile_payload(None, required=True)
    )
    if any(item != tax_profile for item in tax_profiles[1:]):
        tax_profile = {
            "status": "mixed",
            "taxSystem": "mixed",
            "source": "mixed",
        }
    return {
        "status": status,
        "message": (
            "Диапазон содержит незакрытый месяц; общая прибыль скрыта. "
            "Используйте итоги закрытых периодов."
            if excluded_open_periods
            else (
                "Диапазон содержит закрытый месяц с неполными данными; "
                "общая прибыль скрыта. Используйте итоги надежных периодов."
                if excluded_incomplete_periods
                else _mart_message_with_cost_quality(status, summary, cost_quality)
            )
        ),
        "basis": "staff_only_ozon_unit_economics_mart_v2_monthly",
        "rowCount": row_count,
        "previewLimit": preview_limit,
        "previewRowCount": len(rows),
        "previewLimited": row_count > len(rows),
        "summary": summary,
        "totals": totals,
        "closedPeriodTotals": closed_totals,
        "excludedOpenPeriods": excluded_open_periods,
        "excludedIncompletePeriods": excluded_incomplete_periods,
        "monthly": monthly,
        "costQuality": cost_quality,
        "reconciliationTotals": _empty_reconciliation_totals(),
        "taxProfile": tax_profile,
        "expenseAttribution": _combine_expense_attribution(monthly_marts),
        "articleRows": _combine_monthly_article_rows(monthly_marts, totals),
        "articleDrilldown": [
            dict(item)
            for mart in monthly_marts
            for item in mart.get("articleDrilldown") or []
        ],
        "issues": [*_mart_issues(summary), *_cost_quality_issues(cost_quality)],
        "rows": rows,
        "periodFilter": {
            "periodStart": monthly[0]["periodStart"] if monthly else None,
            "periodEnd": monthly[-1]["periodEnd"] if monthly else None,
        },
        "profitAliasDeprecated": True,
    }


def _combine_monthly_summaries(
    monthly_marts: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    result = _empty_summary()
    for mart in monthly_marts:
        summary = mart.get("summary") or {}
        for field in result:
            result[field] += int(summary.get(field) or 0)
    return result


def _combine_monthly_totals(
    monthly_marts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not monthly_marts:
        return _empty_totals()
    source_totals = [dict(mart.get("totals") or {}) for mart in monthly_marts]
    result = _empty_totals()

    def sum_available(field: str) -> float:
        return _json_number(
            sum(
                (
                    _decimal_or_none(item.get(field)) or Decimal("0")
                    for item in source_totals
                ),
                Decimal("0"),
            )
        ) or 0.0

    def complete_sum(field: str) -> float | None:
        values = [_decimal_or_none(item.get(field)) for item in source_totals]
        if any(value is None for value in values):
            return None
        return _json_number(
            sum((value for value in values if value is not None), Decimal("0"))
        )

    result["quantity"] = sum_available("quantity")
    for field in (
        "onecRevenue",
        "cogs",
        "ozonExpenses",
        "profit",
        "profitBeforeTax",
        "vatOutput",
        "vatInput",
        "vatPayable",
        "revenueTax",
        "incomeTax",
        "profitBeforeIncomeTax",
        "profitAfterTax",
    ):
        result[field] = complete_sum(field)
    revenue = _decimal_or_none(result.get("onecRevenue"))
    profit_before_tax = _decimal_or_none(result.get("profitBeforeTax"))
    profit_after_tax = _decimal_or_none(result.get("profitAfterTax"))
    result["margin"] = (
        _json_number(profit_before_tax / revenue)
        if revenue and profit_before_tax is not None
        else None
    )
    result["marginBeforeTax"] = result["margin"]
    result["marginAfterTax"] = (
        _json_number(profit_after_tax / revenue)
        if revenue and profit_after_tax is not None
        else None
    )
    categorical_values: dict[str, str] = {}
    for field, default in (
        ("taxSystem", ""),
        ("taxProfileSource", "missing"),
        ("taxCompleteness", "missing_tax_profile"),
    ):
        values = {str(item.get(field) or default) for item in source_totals}
        categorical_values[field] = (
            next(iter(values)) if len(values) == 1 else "mixed"
        )
        result[field] = categorical_values[field]
    if (
        categorical_values["taxSystem"] == "mixed"
        or categorical_values["taxCompleteness"] == "mixed"
    ):
        for field in (
            "vatOutput",
            "vatInput",
            "vatPayable",
            "revenueTax",
            "incomeTax",
            "profitBeforeIncomeTax",
            "profitAfterTax",
            "marginAfterTax",
        ):
            result[field] = None
    return result


def _combine_monthly_article_rows(
    monthly_marts: Sequence[Mapping[str, Any]],
    totals: Mapping[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for mart in monthly_marts:
        for item in mart.get("articleRows") or []:
            article_id = str(item.get("articleId") or "")
            if not article_id:
                continue
            target = grouped.setdefault(
                article_id,
                {
                    **dict(item),
                    "amount": Decimal("0"),
                    "effectAmount": Decimal("0"),
                    "effectComplete": True,
                    "sourceLabels": set(),
                },
            )
            amount = _decimal_or_none(item.get("amount"))
            effect = _decimal_or_none(item.get("effectAmount"))
            if amount is not None:
                target["amount"] += amount
            if effect is None:
                target["effectComplete"] = False
            else:
                target["effectAmount"] += effect
            target["sourceLabels"].update(item.get("sourceLabels") or [])

    total_fields = {"revenue": "onecRevenue", "cogs": "cogs", "profit": "profit"}
    result: list[dict[str, Any]] = []
    for article_id, item in grouped.items():
        total_field = total_fields.get(article_id)
        if total_field:
            amount = _decimal_or_none(totals.get(total_field))
            effect = amount if article_id in {"revenue", "profit"} else (
                -amount if amount is not None else None
            )
        else:
            amount = item["amount"]
            effect = item["effectAmount"] if item["effectComplete"] else None
        result.append(
            {
                **{
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "amount",
                        "effectAmount",
                        "effectComplete",
                        "sourceLabels",
                    }
                },
                "amount": _json_number(amount),
                "effectAmount": _json_number(effect),
                "sourceLabels": sorted(item["sourceLabels"]),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            int(item.get("sortOrder") or 80),
            str(item.get("articleId") or ""),
        ),
    )


def _empty_summary() -> dict[str, int]:
    return {
        "ready": 0,
        "partialSource": 0,
        "missingMapping": 0,
        "ambiguousMapping": 0,
        "missingCost": 0,
        "missing1cCommissioner": 0,
        "missing1cOrganization": 0,
        "buyoutPeriodOnly": 0,
        "partialExpenses": 0,
        "taxProfileMissing": 0,
        "taxMethodUnsupported": 0,
        "taxInputVatReview": 0,
    }


_TAX_PROFILE_MISSING_COMPLETENESS = frozenset({"missing_tax_profile"})
_TAX_METHOD_UNSUPPORTED_COMPLETENESS = frozenset({"unsupported_tax_method"})
_TAX_INPUT_VAT_REVIEW_COMPLETENESS = frozenset(
    {
        "input_vat_missing",
        "vat_input_partial_ndfl_not_allocated",
        "vat_input_missing_ndfl_not_allocated",
        "vat_input_mismatch_ndfl_not_allocated",
    }
)


def _increment_tax_summary(summary: dict[str, int], tax_completeness: str) -> None:
    if tax_completeness in _TAX_PROFILE_MISSING_COMPLETENESS:
        summary["taxProfileMissing"] = int(summary.get("taxProfileMissing") or 0) + 1
    elif tax_completeness in _TAX_METHOD_UNSUPPORTED_COMPLETENESS:
        summary["taxMethodUnsupported"] = (
            int(summary.get("taxMethodUnsupported") or 0) + 1
        )
    elif tax_completeness in _TAX_INPUT_VAT_REVIEW_COMPLETENESS:
        summary["taxInputVatReview"] = int(summary.get("taxInputVatReview") or 0) + 1


def _empty_totals() -> dict[str, Any]:
    return {
        "quantity": 0.0,
        "onecRevenue": 0.0,
        "cogs": 0.0,
        "ozonExpenses": 0.0,
        "profit": 0.0,
        "margin": None,
        "profitBeforeTax": 0.0,
        "marginBeforeTax": None,
        "vatOutput": None,
        "vatInput": None,
        "vatPayable": None,
        "revenueTax": None,
        "incomeTax": None,
        "profitBeforeIncomeTax": None,
        "profitAfterTax": None,
        "marginAfterTax": None,
        "taxSystem": "",
        "taxProfileSource": "missing",
        "taxCompleteness": "missing_tax_profile",
    }


def _empty_reconciliation_totals() -> dict[str, Any]:
    return {
        "basis": "onec_sales_register",
        "quantity": None,
        "onecRevenue": None,
        "cogs": None,
        "revenueStatus": "not_available",
        "cogsStatus": "not_available",
        "revenueDeltaVsSku": None,
        "cogsDeltaVsSku": None,
    }


def _empty_cost_quality() -> dict[str, Any]:
    return {
        "status": "complete",
        "revenueAmount": 0.0,
        "coveredRevenueAmount": 0.0,
        "revenueCoveragePct": None,
        "eligibleRevenueAmount": 0.0,
        "coveredEligibleRevenueAmount": 0.0,
        "eligibleRevenueCoveragePct": None,
        "quantity": 0.0,
        "coveredQuantity": 0.0,
        "quantityCoveragePct": None,
        "unmappedQuantity": 0.0,
        "ambiguousQuantity": 0.0,
        "unmappedRevenueRowCount": 0,
        "ambiguousRevenueRowCount": 0,
        "missingCostCount": 0,
        "anomalyCount": 0,
        "insufficientHistoryCount": 0,
        "estimatedImpactAmount": 0.0,
        "materialityThresholdAmount": _json_number(_COST_MATERIALITY_MINIMUM),
        "materialityThresholdMode": "monthly",
        "materialityThresholdMinAmount": _json_number(
            _COST_MATERIALITY_MINIMUM
        ),
        "materialityThresholdMaxAmount": _json_number(
            _COST_MATERIALITY_MINIMUM
        ),
        "materialityMinimumAmount": _json_number(_COST_MATERIALITY_MINIMUM),
        "materialityRevenueRate": _json_number(
            _COST_MATERIALITY_REVENUE_RATE
        ),
        "martQuantity": 0.0,
        "martCogs": 0.0,
        "martAverageUnitCost": None,
        "direct1cQuantity": None,
        "direct1cCogs": None,
        "direct1cAverageUnitCost": None,
        "direct1cDeviationPct": None,
        "direct1cEstimatedImpact": None,
        "direct1cStatus": "not_available",
        "direct1cReason": "missing_control",
        "blockingReasons": [],
    }


def _apply_cost_quality(
    rows: Sequence[dict[str, Any]],
    *,
    reference_unit_costs: Mapping[str, Sequence[Decimal]],
    direct_1c_cost_control: Mapping[str, Any],
    materiality_minimum: Decimal,
    materiality_revenue_rate: Decimal,
) -> dict[str, Any]:
    result = _empty_cost_quality()
    eligible_revenue = Decimal("0")
    covered_eligible_revenue = Decimal("0")
    quantity = Decimal("0")
    covered_quantity = Decimal("0")
    unmapped_quantity = Decimal("0")
    ambiguous_quantity = Decimal("0")
    unmapped_revenue_row_count = 0
    ambiguous_revenue_row_count = 0
    mart_cogs = Decimal("0")
    anomaly_impact = Decimal("0")
    anomaly_rows: list[dict[str, Any]] = []
    missing_count = 0
    insufficient_history_count = 0

    for row in rows:
        row.update(
            {
                "costQualityStatus": "not_applicable",
                "referenceUnitCost": None,
                "unitCostDeviationPct": None,
                "estimatedCostImpact": None,
                "costQualityReason": "not_applicable",
            }
        )
        if row.get("rowType") != "realization_item":
            continue
        quality_status = str(row.get("qualityStatus") or "")
        row_quantity = _decimal_or_none(row.get("quantity")) or Decimal("0")
        realization_amount = _decimal_or_none(row.get("realizationAmount"))
        if row_quantity > 0:
            quantity += row_quantity
        if quality_status == "missing_mapping":
            unmapped_quantity += max(row_quantity, Decimal("0"))
            if realization_amount is not None and realization_amount != 0:
                unmapped_revenue_row_count += 1
        elif quality_status == "ambiguous_mapping":
            ambiguous_quantity += max(row_quantity, Decimal("0"))
            if realization_amount is not None and realization_amount != 0:
                ambiguous_revenue_row_count += 1
        if quality_status in {
            "missing_mapping",
            "ambiguous_mapping",
            "missing_1c_commissioner",
            "missing_1c_organization",
        }:
            continue
        row_revenue = _decimal_or_none(row.get("onecRevenue"))
        unit_cost = _decimal_or_none(row.get("unitCost"))
        cogs = _decimal_or_none(row.get("cogs"))
        if row_revenue is not None and row_revenue > 0:
            eligible_revenue += row_revenue
        if unit_cost is None or unit_cost <= 0 or cogs is None:
            row["costQualityStatus"] = "blocked"
            row["costQualityReason"] = (
                "nonpositive_unit_cost"
                if unit_cost is not None and unit_cost <= 0
                else "missing_cost"
            )
            missing_count += 1
            continue
        if row_revenue is not None and row_revenue > 0:
            covered_eligible_revenue += row_revenue
        if row_quantity > 0:
            covered_quantity += row_quantity
            mart_cogs += cogs
        history = _valid_cost_history(
            reference_unit_costs.get(str(row.get("onecItemId") or ""), ())
        )
        if len(history) < _COST_MIN_REFERENCE_MONTHS:
            row["costQualityStatus"] = "warning"
            row["costQualityReason"] = "insufficient_history"
            insufficient_history_count += 1
            continue
        reference = _decimal_median(history)
        deviation = (unit_cost - reference) / reference
        impact = abs(unit_cost - reference) * max(row_quantity, Decimal("0"))
        row["referenceUnitCost"] = _json_number(reference)
        row["unitCostDeviationPct"] = _json_number(deviation)
        row["estimatedCostImpact"] = _json_number(impact)
        ratio = unit_cost / reference
        if ratio < _COST_LOW_RATIO or ratio > _COST_HIGH_RATIO:
            row["costQualityStatus"] = "warning"
            row["costQualityReason"] = "unit_cost_outlier"
            anomaly_rows.append(row)
            anomaly_impact += impact
        else:
            row["costQualityStatus"] = "complete"
            row["costQualityReason"] = "within_reference_range"

    threshold = max(
        abs(materiality_minimum),
        abs(eligible_revenue) * abs(materiality_revenue_rate),
    )
    mart_average = (
        mart_cogs / covered_quantity if covered_quantity > 0 else None
    )
    direct_quantity = _decimal_or_none(direct_1c_cost_control.get("quantity"))
    direct_cogs = _decimal_or_none(direct_1c_cost_control.get("cogs"))
    direct_average = (
        direct_cogs / direct_quantity
        if (
            direct_quantity is not None
            and direct_quantity > 0
            and direct_cogs is not None
            and direct_cogs > 0
        )
        else None
    )
    direct_deviation = (
        (mart_average - direct_average) / direct_average
        if mart_average is not None and direct_average
        else None
    )
    direct_impact = (
        abs(mart_average - direct_average) * covered_quantity
        if mart_average is not None and direct_average is not None
        else None
    )
    blocking_reasons: list[str] = []
    if missing_count:
        blocking_reasons.append("missing_cost")
    if anomaly_rows and anomaly_impact >= threshold:
        blocking_reasons.append("material_unit_cost_outlier")
        for row in anomaly_rows:
            row["costQualityStatus"] = "blocked"
    status = "complete"
    if blocking_reasons:
        status = "blocked"
    elif anomaly_rows or insufficient_history_count:
        status = "warning"
    direct_status = "not_available"
    direct_reason = "missing_control"
    if direct_average is not None:
        direct_status = "available"
        direct_reason = "available"
    elif direct_quantity is not None and direct_quantity <= 0:
        direct_reason = "nonpositive_quantity"
    elif direct_cogs is not None and direct_cogs <= 0:
        direct_reason = "nonpositive_cost"

    result.update(
        {
            "status": status,
            "revenueAmount": _json_number(eligible_revenue),
            "coveredRevenueAmount": _json_number(covered_eligible_revenue),
            "revenueCoveragePct": (
                None
                if unmapped_revenue_row_count or ambiguous_revenue_row_count
                else _ratio_or_none(covered_eligible_revenue, eligible_revenue)
            ),
            "eligibleRevenueAmount": _json_number(eligible_revenue),
            "coveredEligibleRevenueAmount": _json_number(
                covered_eligible_revenue
            ),
            "eligibleRevenueCoveragePct": _ratio_or_none(
                covered_eligible_revenue,
                eligible_revenue,
            ),
            "quantity": _json_number(quantity),
            "coveredQuantity": _json_number(covered_quantity),
            "quantityCoveragePct": _ratio_or_none(
                covered_quantity,
                quantity,
            ),
            "unmappedQuantity": _json_number(unmapped_quantity),
            "ambiguousQuantity": _json_number(ambiguous_quantity),
            "unmappedRevenueRowCount": unmapped_revenue_row_count,
            "ambiguousRevenueRowCount": ambiguous_revenue_row_count,
            "missingCostCount": missing_count,
            "anomalyCount": len(anomaly_rows),
            "insufficientHistoryCount": insufficient_history_count,
            "estimatedImpactAmount": _json_number(anomaly_impact),
            "materialityThresholdAmount": _json_number(threshold),
            "materialityThresholdMode": "monthly",
            "materialityThresholdMinAmount": _json_number(threshold),
            "materialityThresholdMaxAmount": _json_number(threshold),
            "materialityMinimumAmount": _json_number(materiality_minimum),
            "materialityRevenueRate": _json_number(materiality_revenue_rate),
            "martQuantity": _json_number(covered_quantity),
            "martCogs": _json_number(mart_cogs),
            "martAverageUnitCost": _json_number(mart_average),
            "direct1cQuantity": _json_number(direct_quantity),
            "direct1cCogs": _json_number(direct_cogs),
            "direct1cAverageUnitCost": _json_number(direct_average),
            "direct1cDeviationPct": _json_number(direct_deviation),
            "direct1cEstimatedImpact": _json_number(direct_impact),
            "direct1cStatus": direct_status,
            "direct1cReason": direct_reason,
            "blockingReasons": blocking_reasons,
        }
    )
    return result


def _apply_missing_organization_scope(
    rows: Sequence[dict[str, Any]],
    cost_quality: dict[str, Any],
) -> None:
    quantity = Decimal("0")
    for row in rows:
        if row.get("rowType") != "realization_item":
            continue
        row_quantity = _decimal_or_none(row.get("quantity")) or Decimal("0")
        if row_quantity > 0:
            quantity += row_quantity
        row.update(
            {
                "onecRevenue": None,
                "revenueAmount": None,
                "revenueBasis": "none",
                "unitCost": None,
                "confirmedInputVat": None,
                "cogs": None,
                "cogsAmount": None,
                "ozonCommission": None,
                "ozonServices": None,
                "ozonPartnerServices": None,
                "ozonLogistics": None,
                "ozonStorage": None,
                "ozonOtherExpenses": None,
                "ozonExpenses": None,
                "skuAttributedExpenseAmount": None,
                "periodUnattributedExpenseAmount": None,
                "expenseArticles": [],
                "profit": None,
                "profitAmount": None,
                "margin": None,
                "qualityStatus": "missing_1c_organization",
                "expenseStatus": "not_applicable",
                "costQualityStatus": "blocked",
                "costQualityReason": "missing_1c_organization",
                "problemReason": "Для кабинета Ozon не выбрана организация 1C.",
                "statusReason": "Для кабинета Ozon не выбрана организация 1C.",
                "actionText": "Выберите организацию 1C.",
            }
        )
    cost_quality.update(
        {
            "status": "blocked",
            "revenueAmount": 0.0,
            "coveredRevenueAmount": 0.0,
            "revenueCoveragePct": None,
            "eligibleRevenueAmount": 0.0,
            "coveredEligibleRevenueAmount": 0.0,
            "eligibleRevenueCoveragePct": None,
            "quantity": _json_number(quantity),
            "coveredQuantity": 0.0,
            "quantityCoveragePct": 0.0 if quantity else None,
            "martQuantity": 0.0,
            "martCogs": 0.0,
            "martAverageUnitCost": None,
            "direct1cQuantity": None,
            "direct1cCogs": None,
            "direct1cAverageUnitCost": None,
            "direct1cDeviationPct": None,
            "direct1cEstimatedImpact": None,
            "direct1cStatus": "not_available",
            "direct1cReason": "missing_control",
            "blockingReasons": ["missing_1c_organization"],
        }
    )


def _valid_cost_history(values: Sequence[Decimal]) -> list[Decimal]:
    result: list[Decimal] = []
    for value in values:
        number = _decimal_or_none(value)
        if number is not None and number > 0:
            result.append(number)
    return result


def _decimal_median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _ratio_or_none(numerator: Decimal, denominator: Decimal) -> float | None:
    return _json_number(numerator / denominator) if denominator else None


def _combine_cost_quality(
    monthly_marts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    items = [
        dict(item.get("costQuality") or {})
        for item in monthly_marts
        if item.get("costQuality")
    ]
    if not items:
        return _empty_cost_quality()
    result = _empty_cost_quality()

    def total(field: str) -> Decimal:
        return sum(
            (_decimal_or_none(item.get(field)) or Decimal("0") for item in items),
            Decimal("0"),
        )

    eligible_revenue = total("eligibleRevenueAmount")
    covered_eligible_revenue = total("coveredEligibleRevenueAmount")
    quantity = total("quantity")
    covered_quantity = total("coveredQuantity")
    unmapped_quantity = total("unmappedQuantity")
    ambiguous_quantity = total("ambiguousQuantity")
    unmapped_revenue_row_count = sum(
        int(item.get("unmappedRevenueRowCount") or 0) for item in items
    )
    ambiguous_revenue_row_count = sum(
        int(item.get("ambiguousRevenueRowCount") or 0) for item in items
    )
    monthly_thresholds = [
        threshold
        for item in items
        if (
            threshold := _decimal_or_none(
                item.get("materialityThresholdAmount")
            )
        )
        is not None
    ]
    mart_quantity = total("martQuantity")
    mart_cogs = total("martCogs")
    direct_quantity = total("direct1cQuantity")
    direct_cogs = total("direct1cCogs")
    mart_average = mart_cogs / mart_quantity if mart_quantity else None
    direct_statuses = {
        str(item.get("direct1cStatus") or "not_available") for item in items
    }
    direct_reasons = {
        str(item.get("direct1cReason") or "missing_control") for item in items
    }
    direct_average = (
        direct_cogs / direct_quantity
        if (
            direct_statuses == {"available"}
            and direct_quantity > 0
            and direct_cogs > 0
        )
        else None
    )
    direct_deviation = (
        (mart_average - direct_average) / direct_average
        if mart_average is not None and direct_average
        else None
    )
    statuses = {str(item.get("status") or "complete") for item in items}
    status = (
        "blocked"
        if "blocked" in statuses
        else "warning"
        if "warning" in statuses
        else "complete"
    )
    blocking_reasons = sorted(
        {
            str(reason)
            for item in items
            for reason in item.get("blockingReasons") or []
            if reason
        }
    )
    result.update(
        {
            "status": status,
            "revenueAmount": _json_number(eligible_revenue),
            "coveredRevenueAmount": _json_number(covered_eligible_revenue),
            "revenueCoveragePct": (
                None
                if unmapped_revenue_row_count or ambiguous_revenue_row_count
                else _ratio_or_none(covered_eligible_revenue, eligible_revenue)
            ),
            "eligibleRevenueAmount": _json_number(eligible_revenue),
            "coveredEligibleRevenueAmount": _json_number(
                covered_eligible_revenue
            ),
            "eligibleRevenueCoveragePct": _ratio_or_none(
                covered_eligible_revenue,
                eligible_revenue,
            ),
            "quantity": _json_number(quantity),
            "coveredQuantity": _json_number(covered_quantity),
            "quantityCoveragePct": _ratio_or_none(covered_quantity, quantity),
            "unmappedQuantity": _json_number(unmapped_quantity),
            "ambiguousQuantity": _json_number(ambiguous_quantity),
            "unmappedRevenueRowCount": unmapped_revenue_row_count,
            "ambiguousRevenueRowCount": ambiguous_revenue_row_count,
            "missingCostCount": sum(
                int(item.get("missingCostCount") or 0) for item in items
            ),
            "anomalyCount": sum(
                int(item.get("anomalyCount") or 0) for item in items
            ),
            "insufficientHistoryCount": sum(
                int(item.get("insufficientHistoryCount") or 0) for item in items
            ),
            "estimatedImpactAmount": _json_number(total("estimatedImpactAmount")),
            "materialityThresholdAmount": _json_number(
                monthly_thresholds[0]
                if len(items) == 1 and len(monthly_thresholds) == 1
                else None
            ),
            "materialityThresholdMode": "monthly",
            "materialityThresholdMinAmount": _json_number(
                min(monthly_thresholds) if monthly_thresholds else None
            ),
            "materialityThresholdMaxAmount": _json_number(
                max(monthly_thresholds) if monthly_thresholds else None
            ),
            "martQuantity": _json_number(mart_quantity),
            "martCogs": _json_number(mart_cogs),
            "martAverageUnitCost": _json_number(mart_average),
            "direct1cQuantity": _json_number(direct_quantity),
            "direct1cCogs": _json_number(direct_cogs),
            "direct1cAverageUnitCost": _json_number(direct_average),
            "direct1cDeviationPct": _json_number(direct_deviation),
            "direct1cEstimatedImpact": _json_number(
                abs(mart_average - direct_average) * mart_quantity
                if mart_average is not None and direct_average is not None
                else None
            ),
            "direct1cStatus": (
                "not_available"
                if direct_average is None
                else "available"
            ),
            "direct1cReason": (
                "available"
                if direct_average is not None
                else "nonpositive_cost"
                if "nonpositive_cost" in direct_reasons
                else "nonpositive_quantity"
                if "nonpositive_quantity" in direct_reasons
                else "missing_control"
            ),
            "blockingReasons": blocking_reasons,
        }
    )
    return result


def _empty_expense_attribution() -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "basis": "",
        "allocationBasis": "",
        "periodExpenseAmount": None,
        "skuAttributedExpenseAmount": 0.0,
        "unattributedExpenseAmount": 0.0,
        "allocatedUnattributedExpenseAmount": 0.0,
        "overAttributedExpenseAmount": 0.0,
        "roundingDeltaAmount": 0.0,
        "periodExpenseDeltaAmount": None,
        "message": "",
    }


def _tax_profile_payload(
    profile: TaxProfile | None,
    *,
    required: bool,
) -> dict[str, Any]:
    if profile is None:
        return {
            "status": "missing" if required else "not_required",
            "taxSystem": "",
            "taxObject": "",
            "taxRate": None,
            "elevatedTaxRate": None,
            "vatRate": None,
            "vatMode": "",
            "vatDeductionMode": "unknown",
            "revenueTaxRate": None,
            "incomeTaxKind": "",
            "validFrom": None,
            "validTo": None,
            "source": "missing",
        }
    configured = tax_profile_is_configured(profile)
    calculation_supported = tax_profile_is_confirmed(profile)
    return {
        "status": (
            "override"
            if profile.source == "manual_override" and configured
            else "ready"
            if configured
            else "unconfirmed"
        ),
        "calculationSupported": calculation_supported,
        "taxSystem": profile.tax_system,
        "taxObject": profile.tax_object,
        "taxRate": _json_number(profile.tax_rate),
        "elevatedTaxRate": _json_number(profile.elevated_tax_rate),
        "vatRate": _json_number(profile.vat_rate),
        "vatMode": profile.vat_mode.value,
        "vatDeductionMode": profile.vat_deduction_mode.value,
        "revenueTaxRate": _json_number(profile.revenue_tax_rate),
        "incomeTaxKind": profile.income_tax_kind,
        "validFrom": profile.valid_from.isoformat() if profile.valid_from else None,
        "validTo": profile.valid_to.isoformat() if profile.valid_to else None,
        "source": profile.source,
    }


def _apply_tax_profile_to_rows(
    rows: Sequence[dict[str, Any]],
    *,
    tax_profile: TaxProfile | None,
    profile_required: bool,
) -> None:
    if tax_profile is not None and not tax_profile_is_configured(tax_profile):
        tax_profile = None
        profile_required = True
    calculation_supported = bool(
        tax_profile is not None and tax_profile_is_confirmed(tax_profile)
    )
    for row in rows:
        profit_before_tax = _decimal_or_none(row.get("profit"))
        revenue = _decimal_or_none(row.get("onecRevenue"))
        row.update(
            {
                "profitBeforeTax": _json_number(profit_before_tax),
                "marginBeforeTax": row.get("margin"),
                "vatOutput": None,
                "vatInput": None,
                "vatPayable": None,
                "revenueTax": None,
                "incomeTax": None,
                "profitBeforeIncomeTax": None,
                "profitAfterTax": None,
                "marginAfterTax": None,
                "taxSystem": tax_profile.tax_system if tax_profile else "",
                "taxProfileSource": tax_profile.source if tax_profile else "missing",
                "taxCompleteness": (
                    "not_calculated"
                    if profit_before_tax is None or revenue is None
                    else "missing_tax_profile"
                ),
                "profitAliasDeprecated": True,
            }
        )
        if profit_before_tax is None or revenue is None:
            continue
        if tax_profile is None:
            if not profile_required:
                row["taxCompleteness"] = "not_required"
            continue
        if not calculation_supported:
            row["taxCompleteness"] = "unsupported_tax_method"
            row["taxMethod"] = (
                "Профиль загружен; метод расчёта налога пока не поддерживается"
            )
            continue
        is_osno = tax_profile_is_osno(tax_profile)
        confirmed_vat_input = _decimal_or_none(row.get("confirmedInputVat"))
        vat_input_completeness = VAT_INPUT_CONFIRMED
        if is_osno and confirmed_vat_input is not None:
            # Расходы услуг Ozon (комиссия, логистика, хранение) несут входящий
            # НДС внутри, но его вычет не подтвержден отдельным источником 1С.
            # Подтвержден только товарный входящий НДС из регистра продаж, поэтому
            # при наличии сервисных расходов входящий НДС неполон -> review.
            service_expenses = _decimal_or_none(row.get("ozonExpenses"))
            if service_expenses is not None and service_expenses > 0:
                vat_input_completeness = VAT_INPUT_PARTIAL
        tax = calculate_tax_amounts(
            revenue,
            profit_before_tax,
            tax_profile,
            vat_input=confirmed_vat_input or Decimal("0"),
            vat_input_available=(
                confirmed_vat_input is not None if is_osno else True
            ),
            vat_input_completeness=vat_input_completeness,
            profile_required=profile_required,
        )
        row["vatOutput"] = _json_number(tax.vat_output)
        row["vatInput"] = _json_number(tax.vat_input)
        row["vatPayable"] = _json_number(tax.vat_payable)
        row["revenueTax"] = _json_number(tax.revenue_tax)
        row["incomeTax"] = _json_number(tax.income_tax)
        row["taxCompleteness"] = tax.tax_completeness
        row["taxMethod"] = tax.tax_method
        if is_osno:
            # Ozon mutual-settlement expenses do not yet provide a confirmed
            # deductible service-VAT split. Do not manufacture an after-tax P&L.
            if confirmed_vat_input is None:
                row["vatInput"] = None
                row["vatPayable"] = None
                row["incomeTax"] = None
                row["profitBeforeIncomeTax"] = None
                row["profitAfterTax"] = None
                row["marginAfterTax"] = None
                continue
            profit_before_income_tax = (
                profit_before_tax - tax.vat_output + tax.vat_input
            )
            row["incomeTax"] = None
            row["profitBeforeIncomeTax"] = _json_number(
                profit_before_income_tax
            )
            row["profitAfterTax"] = None
            row["marginAfterTax"] = None
            continue
        profit_after_tax = tax.profit_after_taxes
        row["profitBeforeIncomeTax"] = _json_number(profit_after_tax)
        row["profitAfterTax"] = _json_number(profit_after_tax)
        row["marginAfterTax"] = (
            _json_number(profit_after_tax / revenue) if revenue else None
        )


def _apply_tax_totals(
    totals: dict[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    eligible = [
        row
        for row in rows
        if row.get("rowType") == "realization_item"
        and _decimal_or_none(row.get("profitBeforeTax")) is not None
    ]
    profit_before_tax = _decimal_or_none(totals.get("profit"))
    revenue = _decimal_or_none(totals.get("onecRevenue"))
    totals["profitBeforeTax"] = _json_number(profit_before_tax)
    totals["marginBeforeTax"] = (
        _json_number(profit_before_tax / revenue)
        if revenue and profit_before_tax is not None
        else None
    )

    def complete_sum(field: str) -> float | None:
        values = [_decimal_or_none(row.get(field)) for row in eligible]
        if not values or any(value is None for value in values):
            return None
        return _json_number(
            sum((value for value in values if value is not None), Decimal("0"))
        )

    for field in (
        "vatOutput",
        "vatInput",
        "vatPayable",
        "revenueTax",
        "incomeTax",
        "profitBeforeIncomeTax",
        "profitAfterTax",
    ):
        totals[field] = complete_sum(field)
    profit_after_tax = _decimal_or_none(totals.get("profitAfterTax"))
    totals["marginAfterTax"] = (
        _json_number(profit_after_tax / revenue)
        if revenue and profit_after_tax is not None
        else None
    )
    tax_systems = {str(row.get("taxSystem") or "") for row in eligible}
    sources = {str(row.get("taxProfileSource") or "missing") for row in eligible}
    completeness = {
        str(row.get("taxCompleteness") or "not_calculated") for row in eligible
    }
    totals["taxSystem"] = next(iter(tax_systems)) if len(tax_systems) == 1 else "mixed"
    totals["taxProfileSource"] = (
        next(iter(sources)) if len(sources) == 1 else "mixed"
    )
    totals["taxCompleteness"] = (
        next(iter(completeness)) if len(completeness) == 1 else "mixed_or_incomplete"
    )


def _combine_expense_attribution(
    monthly_marts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result = _empty_expense_attribution()
    items = [
        item.get("expenseAttribution") or {}
        for item in monthly_marts
        if item.get("expenseAttribution")
    ]
    if not items:
        return result
    for field in (
        "periodExpenseAmount",
        "skuAttributedExpenseAmount",
        "unattributedExpenseAmount",
        "allocatedUnattributedExpenseAmount",
        "overAttributedExpenseAmount",
        "roundingDeltaAmount",
        "periodExpenseDeltaAmount",
    ):
        values = [_decimal_or_none(item.get(field)) for item in items]
        result[field] = _json_number(
            sum((value for value in values if value is not None), Decimal("0"))
        )
    statuses = {str(item.get("status") or "not_applicable") for item in items}
    result["status"] = next(iter(statuses)) if len(statuses) == 1 else "mixed"
    result["basis"] = "monthly"
    result["allocationBasis"] = "onec_revenue_share"
    result["message"] = "Расходы агрегированы из помесячных расчетов."
    return result


def _realization_contexts(
    rows: Sequence[OzonSourceRow],
    mapping_resolver: MappingResolver,
) -> list[_MartContext]:
    contexts: list[_MartContext] = []
    for row in rows:
        for item in _iter_realization_items(row.row_payload or {}):
            candidate = _mapping_candidate(row, item)
            mapping = mapping_resolver(candidate) if candidate else None
            if not mapping:
                mapping = _mapping_preview_row(
                    candidate
                    or {
                        "rowNumber": row.row_number,
                        "sourceRowId": row.source_row_id,
                    },
                    status="no_key",
                )
            expenses, expenses_loaded = _realization_expenses(item)
            contexts.append(
                _MartContext(
                    row_number=row.row_number,
                    source_row_id=row.source_row_id,
                    candidate=candidate or {},
                    mapping=mapping,
                    quantity=_realization_quantity(item),
                    realization_amount=_realization_amount(item),
                    expenses=expenses,
                    expenses_loaded=expenses_loaded,
                )
            )
    return contexts


def _group_contexts(contexts: Sequence[_MartContext]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for context in contexts:
        mapping = context.mapping
        key = (
            *_ozon_item_identity(mapping, context.candidate),
            str(mapping.get("onecItemId") or ""),
            str(mapping.get("status") or ""),
        )
        group = groups.setdefault(
            key,
            {
                "rowNumber": context.row_number,
                "sourceRowId": context.source_row_id,
                "mapping": mapping,
                "candidate": context.candidate,
                "quantity": Decimal("0"),
                "realizationAmount": Decimal("0"),
                "hasRealizationAmount": False,
                "expenses": defaultdict(Decimal),
                "expensesLoaded": True,
            },
        )
        group["quantity"] += context.quantity
        if context.realization_amount is not None:
            group["realizationAmount"] += context.realization_amount
            group["hasRealizationAmount"] = True
        for key_name, amount in context.expenses.items():
            group["expenses"][key_name] += amount
        if not context.expenses_loaded:
            group["expensesLoaded"] = False
    return list(groups.values())


def _identity_count_by_onec_item(groups: Sequence[dict[str, Any]]) -> dict[str, int]:
    identities: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    for group in groups:
        mapping = group["mapping"]
        if mapping.get("status") != "matched":
            continue
        onec_item_id = str(mapping.get("onecItemId") or "")
        if not onec_item_id:
            continue
        identity = _ozon_item_identity(mapping, group.get("candidate") or {})
        identities[onec_item_id].add(identity)
    return {key: len(value) for key, value in identities.items()}


def _ozon_item_identity(
    mapping: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[str, str, str, str]:
    offer_id = str(mapping.get("offerId") or candidate.get("offerId") or "")
    if offer_id:
        return (offer_id, "", "", "")
    return (
        "",
        str(mapping.get("productId") or candidate.get("productId") or ""),
        str(mapping.get("sku") or candidate.get("sku") or ""),
        str(mapping.get("barcode") or candidate.get("barcode") or ""),
    )


def _mart_row_payload(
    *,
    index: int,
    group: dict[str, Any],
    revenue_by_item: Mapping[str, dict[str, Decimal]],
    has_commissioner: bool,
    unit_costs: Mapping[str, Decimal],
    identity_count_by_onec_item: Mapping[str, int],
    input_vat_by_item: Mapping[str, Decimal],
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    mapping = group["mapping"]
    candidate = group["candidate"]
    onec_item_id = str(mapping.get("onecItemId") or "")
    mapping_status = str(mapping.get("status") or "")
    quantity = group["quantity"]
    expenses = dict(group["expenses"])
    expense_status = (
        "not_calculated_open_period"
        if not has_commissioner
        else "loaded"
        if group["expensesLoaded"]
        else "partial_source"
    )
    ozon_expenses = (
        sum(expenses.values(), Decimal("0")) if expense_status == "loaded" else None
    )
    expense_articles = (
        _direct_expense_articles(expenses) if expense_status == "loaded" else []
    )
    revenue_bucket = revenue_by_item.get(onec_item_id)
    allocation_conflict = (
        mapping_status == "matched"
        and onec_item_id
        and int(identity_count_by_onec_item.get(onec_item_id) or 0) > 1
    )
    unit_cost = unit_costs.get(onec_item_id) if mapping_status == "matched" else None
    confirmed_input_vat = (
        input_vat_by_item.get(onec_item_id)
        if mapping_status == "matched"
        and not allocation_conflict
        and has_commissioner
        else None
    )
    cogs = (
        quantity * unit_cost
        if unit_cost is not None
        and not allocation_conflict
        and has_commissioner
        else None
    )
    onec_revenue = (
        revenue_bucket["amount"]
        if has_commissioner
        and revenue_bucket is not None
        and mapping_status == "matched"
        and not allocation_conflict
        else None
    )
    quality_status = _quality_status(
        has_commissioner=has_commissioner,
        mapping_status=mapping_status,
        onec_item_id=onec_item_id,
        onec_revenue=onec_revenue,
        unit_cost=unit_cost,
        expense_status=expense_status,
        allocation_conflict=allocation_conflict,
    )
    profit = (
        onec_revenue - cogs - ozon_expenses
        if quality_status == "ready"
        and onec_revenue is not None
        and cogs is not None
        and ozon_expenses is not None
        else None
    )
    margin = profit / onec_revenue if profit is not None and onec_revenue else None
    problem_reason = _problem_reason(
        quality_status,
        expense_status=expense_status,
        allocation_conflict=allocation_conflict,
    )
    return {
        "id": f"ozon-mart-{index}",
        "rowType": "realization_item",
        "periodStart": period_start.isoformat() if period_start else None,
        "periodEnd": period_end.isoformat() if period_end else None,
        "rowNumber": group["rowNumber"],
        "sourceRowId": group["sourceRowId"],
        "offerId": mapping.get("offerId") or candidate.get("offerId") or "",
        "productId": mapping.get("productId") or candidate.get("productId") or "",
        "sku": mapping.get("sku") or candidate.get("sku") or "",
        "barcode": mapping.get("barcode") or candidate.get("barcode") or "",
        "productName": (
            str(mapping.get("productName") or candidate.get("productName") or "")[:240]
        ),
        "onecItemId": onec_item_id,
        "onecName": mapping.get("onecName") or "",
        "quantity": _json_number(quantity),
        "realizationAmount": _json_number(
            group["realizationAmount"] if group["hasRealizationAmount"] else None
        ),
        "onecRevenue": _json_number(onec_revenue),
        "revenueAmount": _json_number(onec_revenue),
        "revenueBasis": "onec_commissioner_sku" if onec_revenue is not None else "none",
        "unitCost": _json_number(unit_cost),
        "confirmedInputVat": _json_number(confirmed_input_vat),
        "cogs": _json_number(cogs),
        "cogsAmount": _json_number(cogs),
        "ozonCommission": _json_number(
            expenses.get("commission") if expense_status == "loaded" else None
        ),
        "ozonServices": _json_number(
            expenses.get("services") if expense_status == "loaded" else None
        ),
        "ozonPartnerServices": _json_number(
            expenses.get("partner_services")
            if expense_status == "loaded"
            else None
        ),
        "ozonLogistics": _json_number(
            expenses.get("logistics") if expense_status == "loaded" else None
        ),
        "ozonStorage": _json_number(
            expenses.get("storage") if expense_status == "loaded" else None
        ),
        "ozonOtherExpenses": _json_number(
            expenses.get("other") if expense_status == "loaded" else None
        ),
        "ozonExpenses": _json_number(ozon_expenses),
        "skuAttributedExpenseAmount": _json_number(ozon_expenses)
        if expense_status == "loaded"
        else None,
        "periodUnattributedExpenseAmount": 0.0
        if expense_status == "loaded"
        else None,
        "expenseArticles": expense_articles,
        "profit": _json_number(profit),
        "profitAmount": _json_number(profit),
        "margin": _json_number(margin),
        "mappingStatus": mapping_status,
        "qualityStatus": quality_status,
        "expenseStatus": expense_status,
        "expenseBasis": "ozon_realization_sku_fields"
        if expense_status == "loaded"
        else "",
        "expenseAttributionType": "sku_direct" if expense_status == "loaded" else "",
        "expenseAllocationBasis": "",
        "expenseAllocationShare": None,
        "costQualityStatus": "not_evaluated",
        "referenceUnitCost": None,
        "unitCostDeviationPct": None,
        "estimatedCostImpact": None,
        "costQualityReason": "not_evaluated",
        "problemReason": problem_reason,
        "statusReason": problem_reason,
        "actionText": _action_text(quality_status, expense_status),
    }


def _quality_status(
    *,
    has_commissioner: bool,
    mapping_status: str,
    onec_item_id: str,
    onec_revenue: Decimal | None,
    unit_cost: Decimal | None,
    expense_status: str,
    allocation_conflict: bool,
) -> str:
    if not has_commissioner:
        return "missing_1c_commissioner"
    if allocation_conflict or mapping_status == "ambiguous":
        return "ambiguous_mapping"
    if mapping_status in {"missing", "no_key", ""} or not onec_item_id:
        return "missing_mapping"
    if onec_revenue is None:
        return "partial_source"
    if unit_cost is None or unit_cost <= 0:
        return "missing_cost"
    if expense_status != "loaded":
        return "partial_source"
    return "ready"


def _problem_reason(
    status: str,
    *,
    expense_status: str,
    allocation_conflict: bool,
) -> str:
    if allocation_conflict:
        return (
            "Одна номенклатура 1C связана с несколькими товарами Ozon; "
            "выручку не распределяем."
        )
    if status == "ready":
        return "Можно читать прибыль Ozon по товару."
    if status == "missing_mapping":
        return "Нужно добавить связь Ozon -> 1C в 1C ИС_Маркетплейс или ручном файле."
    if status == "ambiguous_mapping":
        return "Нужно выбрать одну правильную номенклатуру 1C."
    if status == "missing_cost":
        return "Есть сопоставление и 1C-выручка, но нет себестоимости 1C."
    if status == "missing_1c_commissioner":
        return "Отчет Ozon есть, но в 1C нет выручки отчета комиссионера по товару."
    if expense_status == "partial_source":
        return (
            "Расходы Ozon загружены по периоду, но не распределены по этой "
            "товарной строке."
        )
    if status == "buyout_period_only":
        return "Выкуп подтвержден агрегатом периода, без номера отчета из API."
    return "Нужно проверить источники Ozon + 1C."


def _action_text(status: str, expense_status: str) -> str:
    if status == "missing_mapping":
        return "Добавить связь Ozon -> 1C в 1C ИС_Маркетплейс или ручном файле."
    if status == "ambiguous_mapping":
        return (
            "Выбрать правильную номенклатуру 1C в 1C ИС_Маркетплейс "
            "или ручном файле."
        )
    if status == "missing_cost":
        return "Проверить себестоимость 1C по номенклатуре."
    if status == "missing_1c_commissioner":
        return "Закрыть или загрузить отчет комиссионера Ozon в 1C."
    if expense_status == "partial_source":
        return (
            "Смотреть сверку расходов по статьям; по SKU не распределяем без "
            "подтвержденной методики."
        )
    if status == "buyout_period_only":
        return "Оставить ограничением сверки: Ozon API не вернул номер отчета."
    return "Действие не требуется."


def _append_buyout_row(
    rows: list[dict[str, Any]],
    *,
    summary: dict[str, int],
    totals: dict[str, float | None],
    reconciliation: Mapping[str, Any],
    period_start: date | None,
    period_end: date | None,
) -> None:
    matched_without_number = int(reconciliation.get("matchedWithoutReportNumber") or 0)
    if not matched_without_number:
        return
    amount = _decimal_or_none(reconciliation.get("buyoutAmount"))
    quantity = _decimal_or_none(reconciliation.get("buyoutQuantity"))
    row = {
        "id": f"ozon-mart-{len(rows) + 1}",
        "rowType": "buyout_reconciliation",
        "periodStart": period_start.isoformat() if period_start else None,
        "periodEnd": period_end.isoformat() if period_end else None,
        "rowNumber": None,
        "sourceRowId": "",
        "offerId": "",
        "productId": "",
        "sku": "",
        "barcode": "",
        "productName": "Выкупы Ozon",
        "onecItemId": "",
        "onecName": "",
        "quantity": _json_number(quantity),
        "realizationAmount": None,
        "onecRevenue": _json_number(amount),
        "revenueAmount": _json_number(amount),
        "revenueBasis": "ozon_buyout_period_total",
        "unitCost": None,
        "cogs": None,
        "cogsAmount": None,
        "ozonCommission": None,
        "ozonServices": None,
        "ozonPartnerServices": None,
        "ozonLogistics": None,
        "ozonStorage": None,
        "ozonOtherExpenses": None,
        "ozonExpenses": None,
        "skuAttributedExpenseAmount": None,
        "periodUnattributedExpenseAmount": None,
        "expenseArticles": [],
        "profit": None,
        "profitAmount": None,
        "margin": None,
        "mappingStatus": "",
        "qualityStatus": "buyout_period_only",
        "expenseStatus": "not_applicable",
        "expenseBasis": "",
        "expenseAttributionType": "",
        "expenseAllocationBasis": "",
        "expenseAllocationShare": None,
        "costQualityStatus": "not_applicable",
        "referenceUnitCost": None,
        "unitCostDeviationPct": None,
        "estimatedCostImpact": None,
        "costQualityReason": "not_applicable",
        "problemReason": _problem_reason(
            "buyout_period_only",
            expense_status="not_applicable",
            allocation_conflict=False,
        ),
        "statusReason": _problem_reason(
            "buyout_period_only",
            expense_status="not_applicable",
            allocation_conflict=False,
        ),
        "actionText": _action_text("buyout_period_only", "not_applicable"),
    }
    rows.append(row)
    _increment_summary(summary, "buyout_period_only", "not_applicable")


def _increment_summary(
    summary: dict[str, int],
    quality_status: str,
    expense_status: str,
) -> None:
    key = {
        "ready": "ready",
        "partial_source": "partialSource",
        "missing_mapping": "missingMapping",
        "ambiguous_mapping": "ambiguousMapping",
        "missing_cost": "missingCost",
        "missing_1c_commissioner": "missing1cCommissioner",
        "missing_1c_organization": "missing1cOrganization",
        "buyout_period_only": "buyoutPeriodOnly",
    }.get(quality_status)
    if key:
        summary[key] = int(summary.get(key) or 0) + 1
    if expense_status == "partial_source":
        summary["partialExpenses"] = int(summary.get("partialExpenses") or 0) + 1


def _increment_totals(totals: dict[str, Any], row: Mapping[str, Any]) -> None:
    for source_key, total_key in (
        ("quantity", "quantity"),
        ("onecRevenue", "onecRevenue"),
        ("cogs", "cogs"),
        ("ozonExpenses", "ozonExpenses"),
        ("profit", "profit"),
    ):
        value = _decimal_or_none(row.get(source_key))
        if value is not None:
            totals[total_key] = _json_number(
                (_decimal_or_none(totals.get(total_key)) or Decimal("0")) + value
            )
    revenue = _decimal_or_none(totals.get("onecRevenue"))
    profit = _decimal_or_none(totals.get("profit"))
    totals["margin"] = (
        _json_number(profit / revenue) if revenue and profit is not None else None
    )


def _summary_for_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    summary = _empty_summary()
    for row in rows:
        _increment_summary(
            summary,
            str(row.get("qualityStatus") or ""),
            str(row.get("expenseStatus") or ""),
        )
        _increment_tax_summary(summary, str(row.get("taxCompleteness") or ""))
    return summary


def _totals_for_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = _empty_totals()
    for row in rows:
        if row.get("rowType") == "buyout_reconciliation":
            continue
        _increment_totals(totals, row)
    return totals


def _allocate_period_expenses(
    rows: Sequence[dict[str, Any]],
    *,
    amount: Decimal | None,
    articles: Sequence[Mapping[str, Any]],
    basis: str,
) -> dict[str, Any]:
    summary = _empty_expense_attribution()
    summary["basis"] = basis
    summary["periodExpenseAmount"] = _json_number(amount)
    if amount is None or amount <= 0 or not basis:
        return summary
    article_specs = _period_expense_article_specs(amount, articles)
    direct_article_totals = _direct_article_totals(rows)
    direct_total = sum(direct_article_totals.values(), Decimal("0"))
    tolerance = _expense_attribution_tolerance(amount)
    residual_specs: list[dict[str, Any]] = []
    global_residual = amount - direct_total
    over_attributed = max(-global_residual, Decimal("0"))
    rounding_delta = Decimal("0")
    matched_direct_total = min(direct_total, amount)
    if global_residual > tolerance and _has_period_expense_article_detail(articles):
        for spec in article_specs:
            article_id = str(spec["articleId"])
            article_amount = Decimal(spec["amount"])
            direct_amount = direct_article_totals.get(article_id, Decimal("0"))
            residual = max(article_amount - direct_amount, Decimal("0"))
            if residual > 0:
                residual_spec = dict(spec)
                residual_spec["amount"] = residual
                residual_specs.append(residual_spec)
        residual_specs = _fit_expense_specs_to_total(
            residual_specs,
            total=global_residual,
        )
    elif global_residual > tolerance:
        residual_specs = [
            {
                "articleId": "services",
                "label": _ARTICLE_LABELS["services"],
                "group": _ARTICLE_GROUPS["services"],
                "amount": global_residual,
                "sourceLabel": "Ozon period expenses",
            }
        ]

    residual_total = sum(
        (Decimal(item["amount"]) for item in residual_specs),
        Decimal("0"),
    )
    allocated_total = Decimal("0")
    if residual_total > tolerance:
        allocated_total = _allocate_residual_expense_specs(
            rows,
            article_specs=residual_specs,
            basis=basis,
        )
    else:
        rounding_delta += residual_total

    delta = amount - matched_direct_total - allocated_total
    if abs(delta) <= tolerance:
        rounding_delta += delta
        delta = Decimal("0")

    summary.update(
        {
            "status": _expense_attribution_status(
                direct_total=direct_total,
                allocated_total=allocated_total,
                over_attributed=over_attributed,
                delta=delta,
            ),
            "allocationBasis": "onec_revenue_share" if allocated_total else "",
            "skuAttributedExpenseAmount": _json_number(direct_total),
            "unattributedExpenseAmount": _json_number(residual_total)
            if residual_total > tolerance
            else 0.0,
            "allocatedUnattributedExpenseAmount": _json_number(allocated_total),
            "overAttributedExpenseAmount": _json_number(over_attributed),
            "roundingDeltaAmount": _json_number(rounding_delta),
            "periodExpenseDeltaAmount": _json_number(delta),
        }
    )
    summary["message"] = _expense_attribution_message(summary)
    return summary


def _fit_expense_specs_to_total(
    specs: Sequence[Mapping[str, Any]],
    *,
    total: Decimal,
) -> list[dict[str, Any]]:
    positive = [dict(item) for item in specs if Decimal(item["amount"]) > 0]
    source_total = sum((Decimal(item["amount"]) for item in positive), Decimal("0"))
    if not positive or source_total <= 0:
        return [
            {
                "articleId": "services",
                "label": _ARTICLE_LABELS["services"],
                "group": _ARTICLE_GROUPS["services"],
                "amount": total,
                "sourceLabel": "Ozon period expenses",
            }
        ]
    if source_total < total:
        positive.append(
            {
                "articleId": "services",
                "label": _ARTICLE_LABELS["services"],
                "group": _ARTICLE_GROUPS["services"],
                "amount": total - source_total,
                "sourceLabel": "Ozon period expenses",
            }
        )
        return positive
    if source_total == total:
        return positive
    cents = Decimal("0.01")
    allocated = Decimal("0")
    for index, spec in enumerate(positive):
        amount = (
            total - allocated
            if index == len(positive) - 1
            else (total * Decimal(spec["amount"]) / source_total).quantize(cents)
        )
        spec["amount"] = max(amount, Decimal("0"))
        allocated += Decimal(spec["amount"])
    return [item for item in positive if Decimal(item["amount"]) > 0]


def _has_period_expense_article_detail(
    articles: Sequence[Mapping[str, Any]],
) -> bool:
    for item in articles:
        if not item.get("includedInExpense"):
            continue
        amount = _decimal_or_none(item.get("expenseEffectAmount"))
        if amount is not None and amount > 0:
            return True
    return False


def _allocate_residual_expense_specs(
    rows: Sequence[dict[str, Any]],
    *,
    article_specs: Sequence[Mapping[str, Any]],
    basis: str,
) -> Decimal:
    eligible: list[tuple[dict[str, Any], Decimal]] = []
    for row in rows:
        if row.get("rowType") != "realization_item":
            continue
        revenue = _decimal_or_none(row.get("onecRevenue"))
        if revenue is None or revenue <= 0:
            continue
        if str(row.get("mappingStatus") or "") != "matched":
            continue
        eligible.append((row, revenue))
    revenue_total = sum((revenue for _, revenue in eligible), Decimal("0"))
    if revenue_total <= 0:
        return Decimal("0")

    allocated: dict[str, Decimal] = defaultdict(Decimal)
    cents = Decimal("0.01")
    allocated_total = Decimal("0")
    for index, (row, revenue) in enumerate(eligible):
        share = revenue / revenue_total
        row_articles: list[dict[str, Any]] = []
        for spec in article_specs:
            article_amount = Decimal(spec["amount"])
            article_id = str(spec["articleId"])
            if index == len(eligible) - 1:
                expense_amount = article_amount - allocated[article_id]
            else:
                expense_amount = (article_amount * share).quantize(cents)
                allocated[article_id] += expense_amount
            if expense_amount:
                row_articles.append(
                    _expense_article_payload(
                        article_id=article_id,
                        label=str(spec["label"]),
                        group=str(spec["group"]),
                        amount=expense_amount,
                        basis=basis,
                        source_label=str(spec.get("sourceLabel") or ""),
                        allocation_share=share,
                        attribution_type="period_unattributed",
                    )
                )
        expense_amount = sum(
            (_decimal_or_none(item.get("amount")) or Decimal("0"))
            for item in row_articles
        )
        _apply_allocated_expense_to_row(
            row,
            expense_amount=expense_amount,
            expense_articles=row_articles,
            basis=basis,
            share=share,
        )
        allocated_total += expense_amount
    return allocated_total


def _direct_article_totals(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = defaultdict(Decimal)
    for row in rows:
        if row.get("rowType") != "realization_item":
            continue
        for item in row.get("expenseArticles") or []:
            if not isinstance(item, Mapping):
                continue
            if item.get("attributionType") not in {"", None, "sku_direct"}:
                continue
            article_id = str(item.get("articleId") or "other")
            amount = _decimal_or_none(item.get("amount"))
            if amount is not None:
                result[article_id] += amount
    return result


def _expense_attribution_tolerance(amount: Decimal) -> Decimal:
    return max(abs(amount) * Decimal("0.0005"), Decimal("1"))


def _expense_attribution_status(
    *,
    direct_total: Decimal,
    allocated_total: Decimal,
    over_attributed: Decimal,
    delta: Decimal,
) -> str:
    if allocated_total > 0 and direct_total > 0:
        return "mixed_sku_and_period_unattributed"
    if allocated_total > 0:
        return "allocated_period_expense"
    if over_attributed > 0 or delta < 0:
        return "sku_detail_above_period"
    if direct_total > 0:
        return "sku_direct"
    return "not_allocated"


def _expense_attribution_message(summary: Mapping[str, Any]) -> str:
    status = str(summary.get("status") or "")
    if status == "mixed_sku_and_period_unattributed":
        return "Расходы Ozon взяты по SKU, остаток периода распределен по выручке."
    if status == "allocated_period_expense":
        return "SKU-расходов нет; расходы периода распределены по выручке."
    if status == "sku_detail_above_period":
        return (
            "Ozon detail больше mutual settlement; отрицательный остаток "
            "не распределен."
        )
    if status == "sku_direct":
        return (
            "Расходы по SKU из Ozon detail; mutual settlement использован "
            "как контроль."
        )
    return "Нет базы для распределения расходов Ozon."


def _apply_allocated_expense_to_row(
    row: dict[str, Any],
    *,
    expense_amount: Decimal,
    expense_articles: Sequence[Mapping[str, Any]],
    basis: str,
    share: Decimal,
) -> None:
    revenue = _decimal_or_none(row.get("onecRevenue"))
    cogs = _decimal_or_none(row.get("cogs"))
    current_expense = _decimal_or_none(row.get("ozonExpenses")) or Decimal("0")
    direct_expense = (
        _decimal_or_none(row.get("skuAttributedExpenseAmount")) or Decimal("0")
    )
    previous_unattributed = (
        _decimal_or_none(row.get("periodUnattributedExpenseAmount"))
        or Decimal("0")
    )
    total_expense = current_expense + expense_amount
    profit = (
        revenue - cogs - total_expense
        if revenue is not None and cogs is not None
        else None
    )
    margin = profit / revenue if profit is not None and revenue else None
    combined_articles = list(row.get("expenseArticles") or []) + list(
        expense_articles
    )
    buckets = _legacy_buckets_from_articles(combined_articles)
    row["ozonCommission"] = _json_number(buckets.get("commission"))
    row["ozonServices"] = _json_number(buckets.get("services"))
    row["ozonPartnerServices"] = _json_number(buckets.get("partner_services"))
    row["ozonLogistics"] = _json_number(buckets.get("logistics"))
    row["ozonStorage"] = _json_number(buckets.get("storage"))
    row["ozonOtherExpenses"] = _json_number(buckets.get("other"))
    row["ozonExpenses"] = _json_number(total_expense)
    row["skuAttributedExpenseAmount"] = _json_number(direct_expense)
    row["periodUnattributedExpenseAmount"] = _json_number(
        previous_unattributed + expense_amount
    )
    row["expenseArticles"] = combined_articles
    row["profit"] = _json_number(profit)
    row["profitAmount"] = _json_number(profit)
    row["margin"] = _json_number(margin)
    is_mixed = direct_expense > 0
    row["expenseStatus"] = (
        "mixed_sku_and_period_unattributed"
        if is_mixed
        else "allocated_period_expense"
    )
    row["expenseBasis"] = (
        "mixed_sku_and_period_unattributed" if is_mixed else basis
    )
    row["expenseAttributionType"] = (
        "mixed_sku_and_period_unattributed"
        if is_mixed
        else "period_unattributed"
    )
    row["expenseAllocationBasis"] = "onec_revenue_share"
    row["expenseAllocationShare"] = _json_number(share)
    if row.get("qualityStatus") == "partial_source":
        row["qualityStatus"] = "ready" if cogs is not None else "missing_cost"
    if row.get("qualityStatus") == "ready":
        reason = (
            "Расходы Ozon по SKU сохранены, остаток периода распределен "
            "по доле 1C-выручки товара."
            if is_mixed
            else "Расходы Ozon за период распределены по доле 1C-выручки товара."
        )
        action = "Сверить итог в блоке расходов по статьям."
    elif row.get("qualityStatus") == "missing_cost":
        reason = (
            "Расходы Ozon распределены по выручке 1C, но нет себестоимости 1C."
        )
        action = "Проверить себестоимость 1C по номенклатуре."
    else:
        reason = str(row.get("problemReason") or "")
        action = str(row.get("actionText") or "")
    row["problemReason"] = reason
    row["statusReason"] = reason
    row["actionText"] = action


def _direct_expense_articles(expenses: Mapping[str, Decimal]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for article_id in ("commission", "logistics", "storage", "services", "other"):
        amount = expenses.get(article_id)
        if amount is None:
            continue
        result.append(
            _expense_article_payload(
                article_id=article_id,
                label=_ARTICLE_LABELS[article_id],
                group=_ARTICLE_GROUPS[article_id],
                amount=abs(amount),
                basis="ozon_realization_sku_fields",
                attribution_type="sku_direct",
            )
        )
    return result


def _period_expense_article_specs(
    amount: Decimal,
    articles: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in articles:
        if not item.get("includedInExpense"):
            continue
        item_amount = _decimal_or_none(item.get("expenseEffectAmount"))
        if item_amount is None or item_amount <= 0:
            continue
        label = str(item.get("label") or item.get("category") or "").strip()
        article_id = _period_expense_article_id(label)
        bucket = result.setdefault(
            article_id,
            {
                "articleId": article_id,
                "label": _ARTICLE_LABELS.get(article_id) or label or article_id,
                "group": _ARTICLE_GROUPS.get(article_id) or "services",
                "amount": Decimal("0"),
                "sourceLabel": label,
            },
        )
        bucket["amount"] = Decimal(bucket["amount"]) + abs(item_amount)
        if label and label not in str(bucket.get("sourceLabel") or ""):
            bucket["sourceLabel"] = f"{bucket['sourceLabel']} / {label}"

    if not result:
        return [
            {
                "articleId": "services",
                "label": _ARTICLE_LABELS["services"],
                "group": _ARTICLE_GROUPS["services"],
                "amount": amount,
                "sourceLabel": "Ozon period expenses",
            }
        ]

    article_total = sum(
        (Decimal(item["amount"]) for item in result.values()),
        Decimal("0"),
    )
    if article_total > 0 and article_total != amount:
        ratio = amount / article_total
        for item in result.values():
            item["amount"] = Decimal(item["amount"]) * ratio

    return sorted(
        result.values(),
        key=lambda item: (
            _ARTICLE_SORT.get(str(item.get("articleId") or ""), 80),
            str(item.get("label") or ""),
        ),
    )


def _period_expense_article_id(label: str) -> str:
    text = label.casefold()
    if "комисс" in text or "вознагражден" in text:
        return "commission"
    if "перевыстав" in text:
        return "partner_services"
    if "акт выполненных работ" in text:
        return "services"
    if "логист" in text or "достав" in text:
        return "logistics"
    if "хран" in text or "размещ" in text:
        return "storage"
    if "продвиж" in text or "реклам" in text:
        return "promotion"
    if "компен" in text:
        return "compensation"
    return "other"


def _expense_article_payload(
    *,
    article_id: str,
    label: str,
    group: str,
    amount: Decimal,
    basis: str,
    source_label: str = "",
    allocation_share: Decimal | None = None,
    attribution_type: str = "",
) -> dict[str, Any]:
    return {
        "articleId": article_id,
        "label": label,
        "group": group,
        "amount": _json_number(amount),
        "effectAmount": _json_number(-amount),
        "includedInProfit": True,
        "basis": basis,
        "expenseBasis": basis,
        "attributionType": attribution_type,
        "sourceLabel": source_label,
        "allocationShare": _json_number(allocation_share),
    }


def _iter_allocated_articles(
    rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for row in rows:
        for item in row.get("expenseArticles") or []:
            if isinstance(item, Mapping):
                result.append(item)
    return result


def _legacy_buckets_from_articles(
    articles: Sequence[Mapping[str, Any]],
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = defaultdict(Decimal)
    for item in articles:
        article_id = str(item.get("articleId") or "")
        group = str(item.get("group") or "")
        amount = _decimal_or_none(item.get("amount"))
        if amount is None:
            continue
        if article_id == "commission" or group == "marketplace_fee":
            result["commission"] += amount
        elif article_id == "partner_services":
            result["partner_services"] += amount
        elif group == "logistics":
            result["logistics"] += amount
        elif group == "storage":
            result["storage"] += amount
        elif group in {"other", "compensation"}:
            result["other"] += amount
        else:
            result["services"] += amount
    return result


def _mart_article_drilldown_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("id") or row.get("sourceRowId") or "")
        for item in row.get("expenseArticles") or []:
            if not isinstance(item, Mapping):
                continue
            attribution_type = str(item.get("attributionType") or "sku_direct")
            result.append(
                {
                    "kind": attribution_type,
                    "articleId": item.get("articleId") or "other",
                    "label": (
                        item.get("label") or item.get("articleId") or "Статья Ozon"
                    ),
                    "group": item.get("group") or "services",
                    "sourceLabel": item.get("sourceLabel") or "",
                    "sourceRowId": row.get("sourceRowId") or "",
                    "martRowId": row_id,
                    "offerId": row.get("offerId") or "",
                    "productId": row.get("productId") or "",
                    "sku": row.get("sku") or "",
                    "barcode": row.get("barcode") or "",
                    "productName": row.get("productName") or "",
                    "onecItemId": row.get("onecItemId") or "",
                    "onecName": row.get("onecName") or "",
                    "amount": item.get("amount"),
                    "effectAmount": item.get("effectAmount"),
                    "includedInSkuProfit": True,
                    "basis": item.get("basis") or row.get("expenseBasis") or "",
                    "expenseBasis": item.get("expenseBasis")
                    or row.get("expenseBasis")
                    or "",
                    "attributionType": attribution_type,
                    "allocationShare": item.get("allocationShare"),
                    "periodExpenseAmount": row.get("periodUnattributedExpenseAmount"),
                    "skuAttributedExpenseAmount": row.get(
                        "skuAttributedExpenseAmount"
                    ),
                    "unattributedExpenseAmount": row.get(
                        "periodUnattributedExpenseAmount"
                    ),
                    "qualityStatus": row.get("qualityStatus") or "",
                    "expenseStatus": row.get("expenseStatus") or "",
                    "status": row.get("qualityStatus") or "",
                    "note": row.get("problemReason") or "",
                    "actionText": row.get("actionText") or "",
                }
            )
    return result


def _mart_article_rows(
    rows: Sequence[Mapping[str, Any]],
    totals: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    revenue = _decimal_or_none(totals.get("onecRevenue"))
    cogs = _decimal_or_none(totals.get("cogs"))
    profit = _decimal_or_none(totals.get("profit"))
    if revenue is not None:
        result.append(_summary_article("revenue", revenue, effect=revenue))

    article_totals: dict[str, Decimal] = defaultdict(Decimal)
    article_sources: dict[str, set[str]] = defaultdict(set)
    for item in _iter_allocated_articles(rows):
        if not item.get("includedInProfit"):
            continue
        amount = _decimal_or_none(item.get("amount"))
        article_id = str(item.get("articleId") or "other")
        if amount is None:
            continue
        article_totals[article_id] += amount
        source_label = str(item.get("sourceLabel") or "").strip()
        if source_label:
            article_sources[article_id].add(source_label)

    for article_id, amount in sorted(
        article_totals.items(),
        key=lambda item: (_ARTICLE_SORT.get(item[0], 80), item[0]),
    ):
        result.append(
            _summary_article(
                article_id,
                amount,
                effect=-amount,
                source_labels=sorted(article_sources.get(article_id) or []),
            )
        )

    if cogs is not None:
        result.append(_summary_article("cogs", cogs, effect=-cogs))
    if profit is not None:
        result.append(_summary_article("profit", profit, effect=profit))
    return result


def _summary_article(
    article_id: str,
    amount: Decimal,
    *,
    effect: Decimal,
    source_labels: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "articleId": article_id,
        "label": _ARTICLE_LABELS.get(article_id) or article_id,
        "group": _ARTICLE_GROUPS.get(article_id) or "other",
        "amount": _json_number(amount),
        "effectAmount": _json_number(effect),
        "sourceLabels": list(source_labels),
        "sortOrder": _ARTICLE_SORT.get(article_id, 80),
    }


def _mark_partial_expense_totals(
    totals: dict[str, Any],
    summary: Mapping[str, int],
) -> None:
    if not int(summary.get("partialExpenses") or 0):
        return
    totals["ozonExpenses"] = None
    totals["profit"] = None
    totals["margin"] = None
    totals["profitBeforeTax"] = None
    totals["marginBeforeTax"] = None
    totals["profitBeforeIncomeTax"] = None
    totals["profitAfterTax"] = None
    totals["marginAfterTax"] = None


def _block_incomplete_profit_totals(
    totals: dict[str, Any],
    *,
    summary: Mapping[str, int],
    cost_quality: Mapping[str, Any],
) -> None:
    if not _incomplete_period_reasons(summary, cost_quality=cost_quality):
        return
    for key in (
        "profit",
        "margin",
        "profitBeforeTax",
        "marginBeforeTax",
        "revenueTax",
        "incomeTax",
        "profitBeforeIncomeTax",
        "profitAfterTax",
        "marginAfterTax",
    ):
        totals[key] = None


def _incomplete_period_reasons(
    summary: Mapping[str, int],
    *,
    cost_quality: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    for field, reason in (
        ("missing1cOrganization", "missing_1c_organization"),
        ("missingCost", "missing_cost"),
        ("ambiguousMapping", "ambiguous_mapping"),
        ("missingMapping", "missing_mapping"),
        ("partialExpenses", "partial_expenses"),
        ("partialSource", "partial_source"),
    ):
        if int(summary.get(field) or 0):
            reasons.append(reason)
    if cost_quality.get("status") == "blocked" and not any(
        item in reasons for item in ("missing_cost", "missing_1c_organization")
    ):
        reasons.append("cost_quality_blocked")
    return reasons


def _mart_message_with_cost_quality(
    status: str,
    summary: Mapping[str, int],
    cost_quality: Mapping[str, Any],
) -> str:
    if int(summary.get("missing1cOrganization") or 0):
        return (
            "Прибыль Ozon не рассчитана: выберите организацию 1C для этого "
            "кабинета."
        )
    if cost_quality.get("status") == "blocked" and status == "partial_source":
        return (
            "Прибыль Ozon не рассчитана: себестоимость отсутствует или "
            "аномалии превышают порог существенности."
        )
    message = _mart_message(status, summary)
    if status == "ready" and cost_quality.get("status") == "warning":
        return f"{message} Есть несущественные предупреждения по себестоимости."
    return message


def _cost_quality_issues(
    cost_quality: Mapping[str, Any],
) -> list[dict[str, str]]:
    status = str(cost_quality.get("status") or "complete")
    if status == "complete":
        return []
    if status == "blocked":
        return [
            {
                "code": "ozon_mart_cost_quality_blocked",
                "title": "Себестоимость блокирует прибыль",
                "detail": (
                    "Проверить отсутствующие или существенные аномалии COGS "
                    "в строках Ozon."
                ),
            }
        ]
    return [
        {
            "code": "ozon_mart_cost_quality_warning",
            "title": "Предупреждение по себестоимости",
            "detail": (
                "Проверить SKU с недостаточной историей или несущественным "
                "отклонением стоимости."
            ),
        }
    ]


def _mart_status(row_count: int, summary: Mapping[str, int]) -> str:
    if not row_count:
        return "not_started"
    if int(summary.get("missing1cOrganization") or 0):
        return "partial_source"
    if int(summary.get("missing1cCommissioner") or 0):
        return "partial_source"
    if int(summary.get("missingMapping") or 0) or int(
        summary.get("ambiguousMapping") or 0
    ):
        return "needs_review"
    if int(summary.get("missingCost") or 0) or int(summary.get("partialSource") or 0):
        return "partial_source"
    return "ready"


def _mart_message(status: str, summary: Mapping[str, int]) -> str:
    if status == "ready":
        return (
            "Расчетная витрина Ozon готова для внутренней проверки "
            "экономики по товарам."
        )
    if int(summary.get("missing1cOrganization") or 0):
        return "Выберите организацию 1C для расчета Ozon."
    if int(summary.get("missing1cCommissioner") or 0):
        return "Есть строки Ozon, но нет закрытия Ozon в 1C."
    if status == "needs_review":
        return (
            "Нужно проверить сопоставление товаров перед расчетом "
            "прибыли по товарам."
        )
    if status == "partial_source":
        return (
            "Расчет Ozon частичный: не все строки имеют себестоимость, "
            "выручку 1C или надежное распределение расходов Ozon по SKU."
        )
    return "Расчет Ozon ожидает строки отчета Ozon."


def _mart_issues(summary: Mapping[str, int]) -> list[dict[str, str]]:
    specs = [
        (
            "missing1cOrganization",
            "ozon_mart_missing_1c_organization",
            "Не выбрана организация 1C",
            "Выберите организацию 1C для кабинета Ozon.",
        ),
        (
            "ambiguousMapping",
            "ozon_mart_ambiguous_mapping",
            "Неоднозначное сопоставление",
            (
                "Выбрать правильную номенклатуру 1C в 1C ИС_Маркетплейс "
                "или ручном файле."
            ),
        ),
        (
            "missingMapping",
            "ozon_mart_missing_mapping",
            "Нет связи Ozon -> 1C",
            (
                "Добавить связь Ozon -> 1C в 1C ИС_Маркетплейс "
                "или ручном файле."
            ),
        ),
        (
            "missingCost",
            "ozon_mart_missing_cost",
            "Нет себестоимости",
            "Проверить себестоимость 1C по номенклатуре.",
        ),
        (
            "missing1cCommissioner",
            "ozon_mart_missing_1c_commissioner",
            "Нет выручки 1C",
            "Проверить отчет комиссионера Ozon или регистр продаж 1C.",
        ),
        (
            "partialExpenses",
            "ozon_mart_partial_expenses",
            "Расходы Ozon без SKU-распределения",
            (
                "Расходы Ozon API загружены по периоду; сверку по статьям "
                "смотреть отдельно."
            ),
        ),
        (
            "buyoutPeriodOnly",
            "ozon_mart_buyout_period_only",
            "Выкупы Ozon",
            "Выкуп подтвержден агрегатом периода, но без номера отчета API.",
        ),
        (
            "taxProfileMissing",
            "ozon_mart_tax_profile_missing",
            "Налоговый профиль не загружен",
            "Настройки налогообложения из 1С не загружены или не применены.",
        ),
        (
            "taxMethodUnsupported",
            "ozon_mart_tax_method_unsupported",
            "Метод расчёта налога не поддерживается",
            (
                "Профиль 1С загружен, но налог по объекту «доходы минус "
                "расходы» текущей методикой не рассчитывается."
            ),
        ),
        (
            "taxInputVatReview",
            "ozon_mart_tax_input_vat_review",
            "Проверка входящего НДС",
            (
                "Входящий НДС по услугам Ozon не подтвержден: "
                "НДС к уплате требует проверки."
            ),
        ),
    ]
    result: list[dict[str, str]] = []
    for summary_key, code, title, detail in specs:
        count = int(summary.get(summary_key) or 0)
        if count:
            result.append(
                {
                    "code": code,
                    "title": title,
                    "value": f"{count} строк",
                    "detail": detail,
                    "tone": "review",
                }
            )
    if not result and int(summary.get("ready") or 0):
        result.append(
            {
                "code": "ozon_mart_ready",
                "title": "Расчет Ozon",
                "value": "готово",
                "detail": "Можно читать внутреннюю экономику Ozon по товарам.",
                "tone": "ok",
            }
        )
    return result


def _onec_commissioner_revenue_by_item(
    rows: Sequence[OzonSourceRow],
    *,
    period_start: date | None,
    period_end: date | None,
) -> tuple[dict[str, dict[str, Decimal]], bool]:
    source_payloads = [row.row_payload or {} for row in rows]
    counterparty_ids = {
        counterparty_id
        for counterparty_id in (
            _safe_text(payload, "Контрагент_Key", "counterparty_id")
            for payload in source_payloads
            if _is_ozon_commissioner_payload(payload)
        )
        if counterparty_id
    }
    matched_payloads = [
        payload
        for payload in source_payloads
        if (
            _is_ozon_commissioner_payload(payload)
            or _safe_text(payload, "Контрагент_Key", "counterparty_id")
            in counterparty_ids
        )
        and _payload_matches_period(
            payload,
            period_start=period_start,
            period_end=period_end,
        )
    ]
    revenue_by_item: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"amount": Decimal("0"), "quantity": Decimal("0")}
    )
    for payload in matched_payloads:
        _add_commissioner_table(
            revenue_by_item,
            payload.get("Запасы"),
            sign=Decimal("1"),
        )
        _add_commissioner_table(
            revenue_by_item,
            payload.get("ЗапасыВозвраты"),
            sign=Decimal("-1"),
        )
    return dict(revenue_by_item), bool(matched_payloads)


def _add_commissioner_table(
    result: dict[str, dict[str, Decimal]],
    value: Any,
    *,
    sign: Decimal,
) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        onec_item_id = _safe_text(
            item,
            "Номенклатура_Key",
            "НоменклатураKey",
            "onec_item_id",
            "item_id",
        )
        if not onec_item_id:
            continue
        result[onec_item_id]["amount"] += sign * _payload_decimal(
            item,
            "Всего",
            "Сумма",
            "amount",
        )
        result[onec_item_id]["quantity"] += sign * _payload_decimal(
            item,
            "Количество",
            "quantity",
            "qty",
        )


def _iter_realization_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "rows", "data", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested_item = payload.get("item")
    if isinstance(nested_item, dict):
        normalized = dict(payload)
        normalized.update(nested_item)
        delivery_commission = payload.get("delivery_commission")
        if isinstance(delivery_commission, dict) and "quantity" not in normalized:
            normalized["quantity"] = delivery_commission.get("quantity")
        return [normalized]
    return [payload]


def _mapping_candidate(
    row: OzonSourceRow,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    product_name = _first_text(
        payload,
        "Название товара",
        "Номенклатура Ozon",
        "product_name",
        "Product name",
        "name",
    )
    offer_id = _first_text(
        payload,
        "offer_id",
        "offerId",
        "Offer ID",
        "offer id",
        "vendor_code",
        "vendorCode",
        "Артикул",
        "Артикул продавца",
        "Артикул Seller",
    )
    product_id = _first_text(
        payload,
        "product_id",
        "productId",
        "Product ID",
        "Ozon Product ID",
        "ID товара",
        "Идентификатор товара",
        "id",
    )
    sku = _first_text(
        payload,
        "sku",
        "SKU",
        "ozon_sku",
        "Ozon SKU",
        "fbo_sku",
        "FBO SKU",
        "fbs_sku",
        "FBS SKU",
    )
    barcode = _first_text(
        payload,
        "barcode",
        "barcodes",
        "Barcode",
        "Штрихкод",
        "Баркод",
        "Штрихкод (Серийный номер / EAN)",
    )
    if not any((product_name, offer_id, product_id, sku, barcode)):
        return None
    return {
        "rowNumber": row.row_number,
        "sourceRowId": row.source_row_id,
        "productName": product_name,
        "offerId": offer_id,
        "productId": product_id,
        "sku": sku,
        "barcode": barcode,
    }


def _mapping_preview_row(candidate: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {
        "rowNumber": candidate.get("rowNumber"),
        "sourceRowId": candidate.get("sourceRowId"),
        "productName": candidate.get("productName") or "",
        "offerId": candidate.get("offerId") or "",
        "productId": candidate.get("productId") or "",
        "sku": candidate.get("sku") or "",
        "barcode": candidate.get("barcode") or "",
        "status": status,
        "matchMethod": "",
        "matchKey": "",
        "onecItemId": "",
        "onecName": "",
        "onecArticle": "",
    }


def _realization_quantity(item: dict[str, Any]) -> Decimal:
    quantity = _payload_decimal(
        item,
        "sale_qty",
        "saleQuantity",
        "quantity",
        "qty",
        "Количество",
        "items_count",
    )
    returns = _payload_decimal(
        item,
        "return_qty",
        "returnQuantity",
        "returns_qty",
        "КоличествоВозврат",
    )
    return quantity - abs(returns)


def _realization_amount(item: dict[str, Any]) -> Decimal | None:
    amount = _first_decimal(
        item,
        "sale_amount",
        "saleAmount",
        "amount",
        "sum",
        "seller_price",
        "sellerPrice",
        "retail_price",
        "retailPrice",
        "price",
        "Всего",
        "Сумма",
    )
    if amount is not None:
        return amount
    delivery_commission = item.get("delivery_commission")
    if isinstance(delivery_commission, dict):
        return _first_decimal(
            delivery_commission,
            "amount",
            "sale_amount",
            "saleAmount",
            "price",
        )
    return None


def _realization_expenses(item: dict[str, Any]) -> tuple[dict[str, Decimal], bool]:
    specs = {
        "commission": (
            "commission",
            "commission_amount",
            "commissionAmount",
            "sale_commission",
            "saleCommission",
            "seller_commission",
            "sellerCommission",
            "reward",
            "seller_reward",
            "sellerReward",
            "Вознаграждение",
            "Комиссия",
        ),
        "services": (
            "services",
            "services_amount",
            "servicesAmount",
            "service",
            "service_amount",
            "serviceAmount",
            "additional_services",
        ),
        "logistics": (
            "logistics",
            "logistics_amount",
            "logisticsAmount",
            "delivery_amount",
            "deliveryAmount",
            "delivery_service",
            "deliveryService",
        ),
        "storage": ("storage", "storage_amount", "storageAmount", "Хранение"),
        "other": (
            "other_amount",
            "otherAmount",
            "penalties",
            "penalty",
            "penalties_and_holdbacks",
            "acquiring",
            "payment_processing",
        ),
    }
    result: dict[str, Decimal] = {}
    found_any = False
    for bucket, keys in specs.items():
        amount, found = _first_decimal_with_presence(item, *keys)
        if found and amount is not None:
            found_any = True
            result[bucket] = abs(amount)
    return result, found_any


def _is_ozon_commissioner_payload(payload: dict[str, Any]) -> bool:
    text = _safe_text(
        payload,
        "Комментарий",
        "НомерВходящегоДокумента",
        "Контрагент",
        "КонтрагентНаименование",
        "counterparty",
        "counterpartyName",
    ).casefold()
    return "озон" in text or "ozon" in text or "интернет решения" in text


def _payload_matches_period(
    payload: dict[str, Any],
    *,
    period_start: date | None,
    period_end: date | None,
) -> bool:
    if period_start is None and period_end is None:
        return True
    document_date = _date_or_none(
        _safe_text(payload, "Date", "Дата", "date", "Period", "Период")
    )
    if document_date is None:
        return False
    if period_start is not None and document_date < period_start:
        return False
    return not (period_end is not None and document_date > period_end)


def _date_or_none(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [
        text,
        text.split("T", 1)[0],
        text.split(" ", 1)[0],
    ]
    for candidate in candidates:
        for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(candidate, pattern).date()
            except ValueError:
                continue
    for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], pattern).date()
        except ValueError:
            continue
    return None


def _payload_decimal(payload: dict[str, Any], *keys: str) -> Decimal:
    return _first_decimal(payload, *keys) or Decimal("0")


def _first_decimal(payload: dict[str, Any], *keys: str) -> Decimal | None:
    value, found = _first_decimal_with_presence(payload, *keys)
    return value if found else None


def _first_decimal_with_presence(
    payload: dict[str, Any],
    *keys: str,
) -> tuple[Decimal | None, bool]:
    found = False
    for key in keys:
        if key not in payload:
            continue
        found = True
        value = _decimal_or_none(payload.get(key))
        if value is not None:
            return value, True
    return None, found


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = next((item for item in value if item not in (None, "")), "")
        text = str(value).strip()
        if text:
            return text
    return ""


def _safe_text(payload: dict[str, Any], *keys: str) -> str:
    return _first_text(payload, *keys)


def _json_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
