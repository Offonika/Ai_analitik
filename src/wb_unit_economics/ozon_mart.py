from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

_ARTICLE_LABELS = {
    "revenue": "Выручка 1C Ozon SKU",
    "commission": "Базовое вознаграждение Ozon",
    "services": "Услуги Ozon",
    "partner_services": "Услуги партнеров / перевыставление",
    "logistics": "Услуги доставки Ozon",
    "storage": "Хранение / размещение",
    "promotion": "Реклама и продвижение",
    "compensation": "Компенсации",
    "other": "Другие услуги Ozon",
    "cogs": "Себестоимость продаж 1C",
    "profit": "Прибыль до налогов",
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
    _allocate_period_expenses(
        all_rows,
        amount=_decimal_or_none(period_expense_amount),
        articles=period_expense_articles or (),
        basis=period_expense_basis,
    )
    summary = _summary_for_rows(all_rows)
    totals = _totals_for_rows(all_rows)
    _mark_partial_expense_totals(totals, summary)

    row_count = len(all_rows)
    rows = all_rows[:preview_limit] if preview_limit else []
    status = _mart_status(row_count, summary)
    return {
        "status": status,
        "message": _mart_message(status, summary),
        "basis": "staff_only_ozon_unit_economics_mart_v1",
        "rowCount": row_count,
        "previewLimit": preview_limit,
        "previewRowCount": len(rows),
        "previewLimited": row_count > len(rows),
        "summary": summary,
        "totals": totals,
        "articleRows": _mart_article_rows(all_rows, totals),
        "articleDrilldown": _mart_article_drilldown_rows(all_rows),
        "issues": _mart_issues(summary),
        "rows": rows,
    }


def _empty_summary() -> dict[str, int]:
    return {
        "ready": 0,
        "partialSource": 0,
        "missingMapping": 0,
        "ambiguousMapping": 0,
        "missingCost": 0,
        "missing1cCommissioner": 0,
        "buyoutPeriodOnly": 0,
        "partialExpenses": 0,
    }


def _empty_totals() -> dict[str, float | None]:
    return {
        "quantity": 0.0,
        "onecRevenue": 0.0,
        "cogs": 0.0,
        "ozonExpenses": 0.0,
        "profit": 0.0,
        "margin": None,
    }


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
            str(mapping.get("offerId") or context.candidate.get("offerId") or ""),
            str(mapping.get("productId") or context.candidate.get("productId") or ""),
            str(mapping.get("sku") or context.candidate.get("sku") or ""),
            str(mapping.get("barcode") or context.candidate.get("barcode") or ""),
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
        identity = (
            str(mapping.get("offerId") or ""),
            str(mapping.get("productId") or ""),
            str(mapping.get("sku") or ""),
            str(mapping.get("barcode") or ""),
        )
        identities[onec_item_id].add(identity)
    return {key: len(value) for key, value in identities.items()}


def _mart_row_payload(
    *,
    index: int,
    group: dict[str, Any],
    revenue_by_item: Mapping[str, dict[str, Decimal]],
    has_commissioner: bool,
    unit_costs: Mapping[str, Decimal],
    identity_count_by_onec_item: Mapping[str, int],
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    mapping = group["mapping"]
    candidate = group["candidate"]
    onec_item_id = str(mapping.get("onecItemId") or "")
    mapping_status = str(mapping.get("status") or "")
    quantity = group["quantity"]
    expenses = dict(group["expenses"])
    expense_status = "loaded" if group["expensesLoaded"] else "partial_source"
    ozon_expenses = (
        sum(expenses.values(), Decimal("0")) if expense_status == "loaded" else None
    )
    expense_articles = _direct_expense_articles(expenses)
    revenue_bucket = revenue_by_item.get(onec_item_id)
    allocation_conflict = (
        mapping_status == "matched"
        and onec_item_id
        and int(identity_count_by_onec_item.get(onec_item_id) or 0) > 1
    )
    unit_cost = unit_costs.get(onec_item_id) if mapping_status == "matched" else None
    cogs = (
        quantity * unit_cost
        if unit_cost is not None
        and quantity > 0
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
        "cogs": _json_number(cogs),
        "cogsAmount": _json_number(cogs),
        "ozonCommission": _json_number(expenses.get("commission")),
        "ozonServices": _json_number(expenses.get("services")),
        "ozonPartnerServices": _json_number(expenses.get("partner_services")),
        "ozonLogistics": _json_number(expenses.get("logistics")),
        "ozonStorage": _json_number(expenses.get("storage")),
        "ozonOtherExpenses": _json_number(expenses.get("other")),
        "ozonExpenses": _json_number(ozon_expenses),
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
        "expenseAllocationBasis": "",
        "expenseAllocationShare": None,
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
    if unit_cost is None:
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
        "expenseArticles": [],
        "profit": None,
        "profitAmount": None,
        "margin": None,
        "mappingStatus": "",
        "qualityStatus": "buyout_period_only",
        "expenseStatus": "not_applicable",
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
        "buyout_period_only": "buyoutPeriodOnly",
    }.get(quality_status)
    if key:
        summary[key] = int(summary.get(key) or 0) + 1
    if expense_status == "partial_source":
        summary["partialExpenses"] = int(summary.get("partialExpenses") or 0) + 1


def _increment_totals(totals: dict[str, float | None], row: Mapping[str, Any]) -> None:
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
    return summary


def _totals_for_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
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
) -> None:
    if amount is None or amount <= 0 or not basis:
        return
    article_specs = _period_expense_article_specs(amount, articles)
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
        return

    allocated: dict[str, Decimal] = defaultdict(Decimal)
    cents = Decimal("0.01")
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
    profit = (
        revenue - cogs - expense_amount
        if revenue is not None and cogs is not None
        else None
    )
    margin = profit / revenue if profit is not None and revenue else None
    buckets = _legacy_buckets_from_articles(expense_articles)
    row["ozonCommission"] = _json_number(buckets.get("commission"))
    row["ozonServices"] = _json_number(buckets.get("services"))
    row["ozonPartnerServices"] = _json_number(buckets.get("partner_services"))
    row["ozonLogistics"] = _json_number(buckets.get("logistics"))
    row["ozonStorage"] = _json_number(buckets.get("storage"))
    row["ozonOtherExpenses"] = _json_number(buckets.get("other"))
    row["ozonExpenses"] = _json_number(expense_amount)
    row["expenseArticles"] = list(expense_articles)
    row["profit"] = _json_number(profit)
    row["profitAmount"] = _json_number(profit)
    row["margin"] = _json_number(margin)
    row["expenseStatus"] = "allocated_period_expense"
    row["expenseBasis"] = basis
    row["expenseAllocationBasis"] = "onec_revenue_share"
    row["expenseAllocationShare"] = _json_number(share)
    if row.get("qualityStatus") == "partial_source":
        row["qualityStatus"] = "ready" if cogs is not None else "missing_cost"
    if row.get("qualityStatus") == "ready":
        reason = (
            "Расходы Ozon за период распределены по доле 1C-выручки товара."
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
    if "отчет о реализации" in text:
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
) -> dict[str, Any]:
    return {
        "articleId": article_id,
        "label": label,
        "group": group,
        "amount": _json_number(amount),
        "effectAmount": _json_number(-amount),
        "includedInProfit": True,
        "basis": basis,
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
            result.append(
                {
                    "kind": "sku_allocation",
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
                    "allocationShare": item.get("allocationShare"),
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
    totals: dict[str, float | None],
    summary: Mapping[str, int],
) -> None:
    if not int(summary.get("partialExpenses") or 0):
        return
    totals["ozonExpenses"] = None
    totals["profit"] = None
    totals["margin"] = None


def _mart_status(row_count: int, summary: Mapping[str, int]) -> str:
    if not row_count:
        return "not_started"
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
    return abs(quantity - abs(returns))


def _realization_amount(item: dict[str, Any]) -> Decimal | None:
    return _first_decimal(
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
    for key in keys:
        if key not in payload:
            continue
        value = _decimal_or_none(payload.get(key))
        if value is not None:
            return value, True
        return None, True
    return None, False


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
