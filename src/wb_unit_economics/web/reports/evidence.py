from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from wb_unit_economics.onec_services import classify_marketplace_service
from wb_unit_economics.web.report_kinds import MONTH_CLOSE_CONTROL, TAX_LOAD

MONTH_CLOSE_EVIDENCE_VERSION = "month-close-evidence-v2"
TAX_LOAD_EVIDENCE_VERSION = "tax-load-evidence-v7"

COMPLETE_SOURCE_STATUSES = frozenset(
    {"loaded", "ready", "complete", "confirmed", "empty_expected"}
)

USN_MARKETPLACE_CATEGORIES = (
    ("ozon", "Ozon (Интернет Решения)"),
    ("wildberries", "Wildberries (РВБ)"),
    ("other", "Другие покупатели"),
)

USN_EXPENSE_CATEGORIES = (
    ("goods", "Товары (признанные расходы КУДиР)"),
    ("services", "Услуги сторонних организаций"),
    ("payroll", "Оплата труда"),
    ("contributions", "Страховые взносы"),
    ("other", "Прочие признанные расходы"),
    ("review_required", "Прочие расходы (требуют проверки)"),
)


@dataclass(frozen=True)
class AccountingEvidenceSource:
    source_type: str
    status: str
    snapshot_id: str
    rows: tuple[Mapping[str, Any], ...]


def materialize_accounting_evidence(
    *,
    report_kind: str,
    organization_id: str,
    period_start: date,
    period_end: date,
    refresh_run_id: str,
    sources: Mapping[str, AccountingEvidenceSource],
) -> dict[str, Any]:
    if report_kind == MONTH_CLOSE_CONTROL:
        payload = _month_close_evidence(
            organization_id=organization_id,
            period_start=period_start,
            period_end=period_end,
            sources=sources,
        )
        payload["contractVersion"] = MONTH_CLOSE_EVIDENCE_VERSION
    elif report_kind == TAX_LOAD:
        payload = _tax_load_evidence(
            organization_id=organization_id,
            period_start=period_start,
            period_end=period_end,
            sources=sources,
        )
        payload["contractVersion"] = TAX_LOAD_EVIDENCE_VERSION
    else:
        raise ValueError("unsupported accounting evidence report kind")
    payload["organizationId"] = organization_id
    payload["sourceRefreshRunId"] = refresh_run_id
    payload["periodStart"] = period_start.isoformat()
    payload["periodEnd"] = period_end.isoformat()
    payload["evidenceSha256"] = _payload_sha256(payload)
    return payload


def _month_close_evidence(
    *,
    organization_id: str,
    period_start: date,
    period_end: date,
    sources: Mapping[str, AccountingEvidenceSource],
) -> dict[str, Any]:
    chart = _account_lookup(sources.get("onec_accounting_chart"))
    primary = sources.get("onec_accounting_balance_and_turnovers")
    normalized_fallback = sources.get("onec_accounting_register_balances")
    raw_fallback = sources.get("onec_accounting_register_records")
    fallback = normalized_fallback or raw_fallback
    primary_rows = _balance_and_turnover_rows(primary, chart, organization_id)
    fallback_rows = (
        _balance_and_turnover_rows(normalized_fallback, chart, organization_id)
        if normalized_fallback is not None
        else _record_type_rows(
            raw_fallback,
            chart,
            organization_id,
            period_start=period_start,
            period_end=period_end,
        )
    )
    tax_rows = _organization_period_rows(
        sources.get("onec_accounting_taxes"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    ens_rows = _organization_period_rows(
        sources.get("onec_accounting_ens"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    vat_sales = _organization_period_rows(
        sources.get("onec_vat_sales_book"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    vat_purchase = _organization_period_rows(
        sources.get("onec_vat_purchase_book"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    bank_in = _organization_period_rows(
        sources.get("onec_accounting_bank_in"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Date",),
    )
    bank_out = _organization_period_rows(
        sources.get("onec_accounting_bank_out"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Date",),
    )
    manual_sources = (
        "onec_accounting_manual_operations",
        "onec_accounting_register_corrections",
        "onec_accounting_purchase_corrections",
        "onec_accounting_sales_corrections",
    )
    manual_rows = [
        row
        for source_type in manual_sources
        for row in _organization_period_rows(
            sources.get(source_type),
            organization_id,
            period_start,
            period_end,
            date_fields=("Date", "Period"),
        )
    ]
    coverage = _coverage(sources, period_start, period_end)
    issues = _source_gap_issues(
        sources,
        {
            "onec_accounting_taxes": "Налоги",
            "onec_accounting_ens": "ЕНС",
            "onec_accounting_bank_out": "Банк",
        },
    )
    if not primary_rows and not fallback_rows:
        issues.append(
            {
                "code": "osv_source_gap",
                "severity": "warning",
                "section": "ОСВ",
                "message": "Ни штатная ОСВ, ни резервный источник не дали строк.",
                "nextAction": (
                    "Проверить публикацию 1С и повторить загрузку только для чтения."
                ),
            }
        )
    controls = [
        _control("osv", "ОСВ", "Сверка оборотов и остатков", primary or fallback),
        _control(
            "ens",
            "ЕНС и налоги",
            "Сверка начислений и ЕНС",
            sources.get("onec_accounting_ens"),
        ),
        _control("vat", "НДС", "Подтверждение НДС", sources.get("onec_vat_sales_book")),
        _control(
            "bank",
            "Банк",
            "Сверка движений денежных средств",
            sources.get("onec_accounting_bank_out"),
        ),
        _control(
            "manual_operations",
            "Ручные операции",
            "Проверка ручных операций",
            sources.get("onec_accounting_manual_operations"),
        ),
        {
            "controlCode": "confirmations",
            "section": "Подтверждения",
            "title": "Подтверждения бухгалтера",
            "status": "not_confirmed",
            "sourceKind": "manual_confirmation",
            "evidenceStatus": "missing",
            "issueCode": "accountant_confirmation_deferred",
            "nextAction": "Зафиксировать подтверждение после согласования процесса.",
        },
    ]
    return {
        "sourceCoverage": coverage,
        "controls": controls,
        "osvBalanceAndTurnovers": {
            "status": primary.status if primary is not None else "missing",
            "rows": primary_rows,
        },
        "osvRecordTypeFallback": {
            "status": fallback.status if fallback is not None else "missing",
            "rows": fallback_rows,
        },
        "taxSummary": {
            "status": _source_status(sources.get("onec_accounting_taxes")),
            "accrued": _sum_rows(tax_rows, ("Сумма", "Amount")),
            "paid": None,
            "balance": None,
        },
        "ensSummary": {
            "status": _source_status(sources.get("onec_accounting_ens")),
            "balance": _sum_rows(ens_rows, ("Сумма", "Amount")),
            "asOfDate": period_end.isoformat(),
        },
        "vatSummary": {
            "status": _combined_status(
                sources.get("onec_vat_sales_book"),
                sources.get("onec_vat_purchase_book"),
            ),
            "outputVat": _sum_rows(vat_sales, ("НДС", "VAT")),
            "inputVat": _sum_rows(vat_purchase, ("НДС", "VAT")),
            "payableVat": None,
            "sourceKind": "onec_vat_books",
        },
        "bankSummary": {
            "status": _combined_status(
                sources.get("onec_accounting_bank_in"),
                sources.get("onec_accounting_bank_out"),
            ),
            "openingBalance": None,
            "inflow": _sum_rows(bank_in, ("СуммаДокумента", "Сумма", "Amount")),
            "outflow": _sum_rows(bank_out, ("СуммаДокумента", "Сумма", "Amount")),
            "closingBalance": None,
        },
        "manualOperationsSummary": {
            "status": "loaded" if manual_rows else "missing",
            "operationCount": len(manual_rows),
            "amount": _sum_rows(manual_rows, ("СуммаДокумента", "Сумма", "Amount")),
        },
        "issues": issues,
    }


def _tax_load_evidence(
    *,
    organization_id: str,
    period_start: date,
    period_end: date,
    sources: Mapping[str, AccountingEvidenceSource],
) -> dict[str, Any]:
    ytd_start = period_start.replace(month=1, day=1)
    tax_lookup = _description_lookup(sources.get("onec_tax_kinds"))
    raw_tax_rows = _organization_period_rows(
        sources.get("onec_accounting_taxes"),
        organization_id,
        ytd_start,
        period_end,
        date_fields=("Period",),
    )
    payment_source = sources.get("onec_accounting_taxes_on_ens")
    raw_payment_rows = _organization_period_rows(
        payment_source,
        organization_id,
        ytd_start,
        period_end,
        date_fields=("Period", "Date", "СрокУплаты"),
    )
    bank_payment_source = sources.get("onec_accounting_bank_out")
    raw_bank_payment_rows = _organization_period_rows(
        bank_payment_source,
        organization_id,
        ytd_start,
        period_end,
        date_fields=("Period", "Date", "Дата"),
    )
    bank_paid_by_kind, bank_payments_classified = _bank_tax_payments(
        raw_bank_payment_rows
    )
    paid_by_tax: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for row in raw_payment_rows:
        tax_code = str(row.get("ВидНалога_Key") or row.get("Tax_Key") or "").strip()
        paid = _first_decimal(
            row,
            (
                "СуммаУплаты",
                "Уплачено",
                "PaidAmount",
                "TaxPaidAmount",
            ),
        )
        payment_due_date = _date_text(row.get("СрокУплаты") or row.get("DueDate"))
        if tax_code and paid is not None:
            paid_by_tax[(tax_code, payment_due_date or "")] += paid
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in raw_tax_rows:
        tax_code = str(row.get("ВидНалога_Key") or row.get("Tax_Key") or "").strip()
        due_date = _date_text(row.get("СрокУплаты") or row.get("DueDate"))
        key = (tax_code, due_date or "")
        item = grouped.setdefault(
            key,
            {
                "taxCode": tax_code or "unclassified",
                "taxName": tax_lookup.get(
                    tax_code, tax_code or "Налог не классифицирован"
                ),
                "periodKind": "ytd",
                "taxBase": None,
                "accrued": Decimal("0"),
                "paid": None,
                "balance": None,
                "dueDate": due_date,
                "valueStatus": "partial",
                "evidenceStatus": "partial_source",
                "sourceKind": "onec_tax_register",
                "issueCode": "paid_tax_fact_unconfirmed",
            },
        )
        item["accrued"] += _first_decimal(row, ("Сумма", "Amount")) or Decimal("0")
    tax_rows: list[dict[str, Any]] = []
    tax_code_counts: dict[str, int] = defaultdict(int)
    tax_kind_counts: dict[str, int] = defaultdict(int)
    for tax_code, _due_date in grouped:
        tax_code_counts[tax_code] += 1
    for item in grouped.values():
        tax_kind = _tax_payment_match_kind(str(item["taxName"]))
        if tax_kind:
            tax_kind_counts[tax_kind] += 1
    included_tax_kinds = {
        _tax_payment_match_kind(str(item["taxName"]))
        for item in grouped.values()
        if _tax_classification(str(item["taxName"]))[1]
    }
    bank_payment_fallback_ready = (
        not raw_payment_rows
        and bank_payments_classified
        and None not in included_tax_kinds
        and all(
            tax_kind_counts[tax_kind] == 1 and tax_kind in bank_paid_by_kind
            for tax_kind in included_tax_kinds
        )
        and all(tax_kind_counts[tax_kind] == 1 for tax_kind in bank_paid_by_kind)
    )
    bank_payment_fallback_used = False
    for item in grouped.values():
        payment_kind, included, exclusion_reason = _tax_classification(
            str(item["taxName"])
        )
        tax_code = str(item["taxCode"])
        paid = paid_by_tax.get((tax_code, str(item["dueDate"] or "")))
        if paid is None and tax_code_counts[tax_code] == 1:
            paid = paid_by_tax.get((tax_code, ""))
        paid_source = payment_source
        if paid is None and bank_payment_fallback_ready:
            tax_kind = _tax_payment_match_kind(str(item["taxName"]))
            paid = bank_paid_by_kind.get(tax_kind or "")
            if paid is not None:
                paid_source = bank_payment_source
                bank_payment_fallback_used = True
        item["accrued"] = _decimal_text(item["accrued"])
        item["paid"] = _decimal_text(paid) if paid is not None else None
        item["valueStatus"] = "loaded" if paid is not None else "partial"
        item["evidenceStatus"] = (
            "loaded"
            if paid is not None
            and paid_source is not None
            and paid_source.status in {"loaded", "ready", "complete"}
            else "partial_source"
        )
        item["sourceKind"] = (
            paid_source.source_type
            if paid is not None and paid_source is not None
            else "onec_tax_register"
        )
        item["issueCode"] = None if paid is not None else "paid_tax_fact_unconfirmed"
        item["paymentKind"] = payment_kind
        item["includedInFnsTaxBurden"] = included
        item["exclusionReason"] = exclusion_reason
        tax_rows.append(item)
    tax_rows.sort(key=lambda item: (str(item["taxName"]), str(item["dueDate"] or "")))

    vat_sales_source = sources.get("onec_vat_sales_book")
    vat_purchase_source = sources.get("onec_vat_purchase_book")
    vat_sales = _organization_period_rows(
        vat_sales_source,
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    vat_purchase = _organization_period_rows(
        vat_purchase_source,
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    vat_sales_ytd = _organization_period_rows(
        vat_sales_source,
        organization_id,
        ytd_start,
        period_end,
        date_fields=("Period",),
    )
    vat_purchase_ytd = _organization_period_rows(
        vat_purchase_source,
        organization_id,
        ytd_start,
        period_end,
        date_fields=("Period",),
    )
    ens_rows = _organization_period_rows(
        sources.get("onec_accounting_ens"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    income_source = sources.get("onec_official_financial_results")
    income_rows = _organization_rows(income_source, organization_id)
    income_value = _sum_rows(
        income_rows,
        ("ДоходыБезУчастия", "IncomeExcludingParticipationIncome"),
    )
    income_evidence = {
        "value": income_value,
        "status": _source_status(income_source),
        "sourceKind": "onec_official_financial_results",
        "snapshotId": income_source.snapshot_id if income_source else "",
    }
    bank_income_source = sources.get("onec_accounting_bank_in")
    bank_income_rows = _organization_period_rows(
        bank_income_source,
        organization_id,
        ytd_start,
        period_end,
        date_fields=("Date", "Period", "Дата"),
    )
    counterparty_source = sources.get("onec_accounting_counterparties")
    counterparty_names = _description_lookup(counterparty_source)
    vat_sales_rows = _vat_book_rows(
        vat_sales_ytd,
        book_kind="sales",
        counterparty_names=counterparty_names,
    )
    vat_purchase_rows = _vat_book_rows(
        vat_purchase_ytd,
        book_kind="purchase",
        counterparty_names=counterparty_names,
    )
    vat_sales_month_totals = _vat_book_totals(vat_sales, vat_sales_source)
    vat_purchase_month_totals = _vat_book_totals(vat_purchase, vat_purchase_source)
    vat_sales_totals = _vat_book_totals(vat_sales_ytd, vat_sales_source)
    vat_purchase_totals = _vat_book_totals(vat_purchase_ytd, vat_purchase_source)
    vat_difference = _decimal_difference(
        vat_sales_totals.get("vatAmount"),
        vat_purchase_totals.get("vatAmount"),
    )
    rwb_vat_reconciliation = _rwb_vat_reconciliation(
        sources=sources,
        organization_id=organization_id,
        period_start=ytd_start,
        period_end=period_end,
        counterparty_names=counterparty_names,
        purchase_book_rows=vat_purchase_rows,
        purchase_book_source=vat_purchase_source,
    )
    counterparty_categories = _usn_marketplace_counterparty_categories(
        counterparty_source
    )
    bank_income_groups = _classify_usn_bank_income_rows(
        bank_income_rows,
        counterparty_categories=counterparty_categories,
    )
    confirmed_bank_income = bank_income_groups["confirmed"]
    unclassified_bank_income = bank_income_groups["unclassified"]
    excluded_bank_income = bank_income_groups["excluded"]
    loan_bank_income = bank_income_groups["loans"]
    bank_income_status = _source_status(bank_income_source)
    bank_income_available = bank_income_status in {
        "loaded",
        "ready",
        "complete",
        "confirmed",
        "empty_expected",
    }
    bank_income_amounts_complete = all(
        row.get("incomeNetAmount") not in (None, "")
        for rows in bank_income_groups.values()
        for row in rows
    )
    marketplace_breakdown_available = (
        bank_income_available
        and bank_income_amounts_complete
        and _source_status(counterparty_source)
        in {"loaded", "ready", "complete", "confirmed"}
    )
    usn_income_evidence = {
        "value": (
            _complete_sum_rows(confirmed_bank_income, ("incomeNetAmount",))
            if bank_income_available
            else None
        ),
        "status": bank_income_status,
        "classificationStatus": (
            "source_gap"
            if not bank_income_available or not bank_income_amounts_complete
            else ("review_required" if unclassified_bank_income else "ready")
        ),
        "sourceKind": "onec_accounting_bank_in",
        "snapshotId": bank_income_source.snapshot_id if bank_income_source else "",
        "monthlyValues": _monthly_values(
            confirmed_bank_income,
            date_fields=("Date",),
            amount_fields=("incomeNetAmount",),
            source_status=bank_income_status,
        ),
        "unclassifiedValue": (
            _complete_sum_rows(unclassified_bank_income, ("incomeNetAmount",))
            if bank_income_available
            else None
        ),
        "monthlyUnclassifiedValues": _monthly_values(
            unclassified_bank_income,
            date_fields=("Date",),
            amount_fields=("incomeNetAmount",),
            source_status=bank_income_status,
        ),
        "excludedValue": (
            _complete_sum_rows(excluded_bank_income, ("incomeNetAmount",))
            if bank_income_available
            else None
        ),
        "monthlyExcludedValues": _monthly_values(
            excluded_bank_income,
            date_fields=("Date",),
            amount_fields=("incomeNetAmount",),
            source_status=bank_income_status,
        ),
        "loanReceiptsValue": (
            _complete_sum_rows(loan_bank_income, ("incomeNetAmount",))
            if bank_income_available
            else None
        ),
        "monthlyLoanReceiptValues": _monthly_values(
            loan_bank_income,
            date_fields=("Date",),
            amount_fields=("incomeNetAmount",),
            source_status=bank_income_status,
        ),
        "confirmedRowCount": len(confirmed_bank_income),
        "unclassifiedRowCount": len(unclassified_bank_income),
        "excludedRowCount": len(excluded_bank_income),
        "loanReceiptRowCount": len(loan_bank_income),
        "marketplaceBreakdownStatus": (
            "ready" if marketplace_breakdown_available else "source_gap"
        ),
        "marketplaceBreakdown": (
            _usn_marketplace_breakdown(
                confirmed_bank_income,
                period_start=ytd_start,
                period_end=period_end,
                source_status=bank_income_status,
            )
            if marketplace_breakdown_available
            else []
        ),
    }
    # КУДиР остается контрольной YTD-сверкой. В текущей 1С Period регистра
    # может быть квартальной датой и не является календарным месяцем поступления.
    usn_income_source = sources.get("onec_kudir")
    usn_income_rows = [
        row
        for row in _organization_period_rows(
            usn_income_source,
            organization_id,
            ytd_start,
            period_end,
            date_fields=("Period", "Date", "Дата"),
        )
        if _is_kudir_income_row(row)
    ]
    usn_expense_rows = [
        row
        for row in _organization_period_rows(
            usn_income_source,
            organization_id,
            ytd_start,
            period_end,
            date_fields=("Period", "Date", "Дата"),
        )
        if _is_kudir_expense_row(row)
    ]
    kudir_status = _source_status(usn_income_source)
    kudir_income_evidence = {
        "value": _confirmed_sum_rows(
            usn_income_rows,
            ("ДоходБаза",),
            source_status=kudir_status,
        ),
        "status": kudir_status,
        "sourceKind": "onec_kudir",
        "snapshotId": usn_income_source.snapshot_id if usn_income_source else "",
        "monthlyValues": _monthly_values(
            usn_income_rows,
            date_fields=("Period", "Date", "Дата"),
            amount_fields=("ДоходБаза",),
            source_status=kudir_status,
        ),
    }
    expense_breakdown, expense_classification_status = _kudir_expense_breakdown(
        usn_expense_rows,
        source_status=kudir_status,
    )
    kudir_expense_evidence = {
        "value": _confirmed_sum_rows(
            usn_expense_rows,
            ("РасходБаза",),
            source_status=kudir_status,
        ),
        "status": kudir_status,
        "classificationStatus": expense_classification_status,
        "sourceKind": "onec_kudir",
        "snapshotId": usn_income_source.snapshot_id if usn_income_source else "",
        "monthlyValues": _monthly_values(
            usn_expense_rows,
            date_fields=("Period", "Date", "Дата"),
            amount_fields=("РасходБаза",),
            source_status=kudir_status,
        ),
        "breakdown": expense_breakdown,
    }
    usn_bank_payment_rows = [
        row
        for row in raw_bank_payment_rows
        if row.get("Posted") is True
        and row.get("DeletionMark") is not True
        and str(row.get("ВидОперации") or "").strip().casefold() == "налоги"
        and _tax_payment_match_kind(
            " ".join(
                str(row.get(key) or "")
                for key in ("НазначениеПлатежа", "Комментарий")
            )
        )
        == "usn"
    ]
    usn_tax_payment_evidence = {
        "status": (
            _source_status(bank_payment_source)
            if bank_payments_classified
            else "partial_source"
        ),
        "sourceKind": "onec_accounting_bank_out",
        "snapshotId": (
            bank_payment_source.snapshot_id if bank_payment_source else ""
        ),
        "monthlyValues": (
            _monthly_values(
                usn_bank_payment_rows,
                date_fields=("Period", "Date", "Дата"),
                amount_fields=("СуммаДокумента", "Сумма", "Amount"),
                source_status=_source_status(bank_payment_source),
            )
            if bank_payments_classified
            else []
        ),
    }
    usn_payroll_payment_evidence = _usn_payroll_payment_evidence(
        raw_bank_payment_rows,
        source=bank_payment_source,
    )
    required_sources = {
        "onec_accounting_taxes": "Налоги",
        "onec_official_financial_results": "Доходный знаменатель",
    }
    if not bank_payment_fallback_used:
        required_sources["onec_accounting_taxes_on_ens"] = "Платежи"
    issues = _source_gap_issues(sources, required_sources)
    if any(
        row.get("counterpartyName") == "Не определён"
        for row in (*vat_sales_rows, *vat_purchase_rows)
    ):
        issues.append(
            {
                "code": "vat_book_counterparty_unresolved",
                "severity": "warning",
                "section": "НДС",
                "message": (
                    "В части строк книги продаж или покупок не определено "
                    "название контрагента."
                ),
                "nextAction": (
                    "Проверить полноту справочника контрагентов 1С, доступного "
                    "только для чтения."
                ),
            }
        )
    if any(row.get("paid") is None for row in tax_rows):
        issues.append(
            {
                "code": "paid_tax_fact_unconfirmed",
                "severity": "warning",
                "section": "Налоговая нагрузка",
                "message": (
                    "Начисления загружены, но факт уплаты по видам налогов "
                    "не подтвержден."
                ),
                "nextAction": (
                    "Получить подтвержденную расшифровку платежей по налогам."
                ),
            }
        )
    if unclassified_bank_income:
        issues.append(
            {
                "code": "usn_bank_income_classification_required",
                "severity": "warning",
                "section": "Доход УСН",
                "message": (
                    "Часть банковских поступлений имеет вид операции «Прочее» "
                    "и не включена в подтвержденный доход автоматически."
                ),
                "nextAction": (
                    "Классифицировать прочие поступления до подтверждения "
                    "налоговой базы."
                ),
            }
        )
    if not bank_income_amounts_complete:
        issues.append(
            {
                "code": "usn_bank_income_amount_unconfirmed",
                "severity": "warning",
                "section": "Доход УСН",
                "message": (
                    "Не для всех банковских поступлений подтверждена сумма "
                    "без НДС по расшифровке платежа."
                ),
                "nextAction": (
                    "Проверить сумму платежа и НДС в расшифровке документов 1С."
                ),
            }
        )
    if (
        usn_payroll_payment_evidence["classificationStatus"]
        == "review_required"
    ):
        issues.append(
            {
                "code": "usn_payroll_classification_required",
                "severity": "warning",
                "section": "Денежные потоки УСН",
                "message": (
                    "Не во всех банковских списаниях заполнен вид операции; "
                    "сумма заработной платы требует проверки."
                ),
                "nextAction": (
                    "Проверить вид операции в проведенных банковских "
                    "документах 1С."
                ),
            }
        )
    elif usn_payroll_payment_evidence["classificationStatus"] == "source_gap":
        issues.append(
            {
                "code": "usn_payroll_source_gap",
                "severity": "warning",
                "section": "Денежные потоки УСН",
                "message": (
                    "Выплаты заработной платы по банковским списаниям "
                    "не подтверждены полностью."
                ),
                "nextAction": (
                    "Проверить полноту банковских списаний и суммы документов "
                    "1С за период."
                ),
            }
        )
    if expense_classification_status == "review_required":
        issues.append(
            {
                "code": "usn_kudir_expense_classification_required",
                "severity": "warning",
                "section": "Расходы УСН",
                "message": (
                    "Часть признанных расходов КУДиР имеет ручной или "
                    "неизвестный вид записи."
                ),
                "nextAction": (
                    "Проверить вид записи КУДиР; общая признанная сумма "
                    "расходов уже сохранена в расчёте."
                ),
            }
        )
    elif expense_classification_status == "source_gap":
        issues.append(
            {
                "code": "usn_kudir_expense_source_gap",
                "severity": "warning",
                "section": "Расходы УСН",
                "message": (
                    "Источник признанных расходов КУДиР неполный или не "
                    "содержит подтверждённую сумму РасходБаза."
                ),
                "nextAction": (
                    "Повторить read-only загрузку КУДиР и проверить ресурс "
                    "РасходБаза."
                ),
            }
        )
    return {
        "sourceCoverage": _coverage(sources, ytd_start, period_end),
        "taxRows": tax_rows,
        "incomeEvidence": income_evidence,
        "usnIncomeEvidence": usn_income_evidence,
        "kudirIncomeEvidence": kudir_income_evidence,
        "kudirExpenseEvidence": kudir_expense_evidence,
        "usnTaxPaymentEvidence": usn_tax_payment_evidence,
        "usnPayrollPaymentEvidence": usn_payroll_payment_evidence,
        "vatSummary": {
            "status": _combined_status(
                vat_sales_source,
                vat_purchase_source,
            ),
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "salesBookStatus": _source_status(vat_sales_source),
            "purchaseBookStatus": _source_status(vat_purchase_source),
            "outputVat": vat_sales_month_totals.get("vatAmount"),
            "inputVat": vat_purchase_month_totals.get("vatAmount"),
            "payableVat": None,
            "salesBookRows": len(vat_sales_rows),
            "purchaseBookRows": len(vat_purchase_rows),
            "ytdOutputVat": vat_sales_totals.get("vatAmount"),
            "ytdInputVat": vat_purchase_totals.get("vatAmount"),
            "vatDifference": vat_difference,
            "sourceKind": "onec_vat_books",
        },
        "vatBooks": {
            "periodStart": ytd_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "salesStatus": _source_status(vat_sales_source),
            "purchaseStatus": _source_status(vat_purchase_source),
            "salesRows": vat_sales_rows,
            "purchaseRows": vat_purchase_rows,
            "salesTotals": vat_sales_totals,
            "purchaseTotals": vat_purchase_totals,
            "vatDifference": vat_difference,
        },
        "rwbVatReconciliation": rwb_vat_reconciliation,
        "ensSummary": {
            "status": _source_status(sources.get("onec_accounting_ens")),
            "balance": _sum_rows(ens_rows, ("Сумма", "Amount")),
            "asOfDate": period_end.isoformat(),
        },
        "issues": issues,
    }


def _coverage(
    sources: Mapping[str, AccountingEvidenceSource],
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    return [
        {
            "sourceKind": source.source_type,
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "status": source.status,
            "snapshotId": source.snapshot_id,
        }
        for source in sorted(sources.values(), key=lambda item: item.source_type)
    ]


def _control(
    code: str,
    section: str,
    title: str,
    source: AccountingEvidenceSource | None,
) -> dict[str, Any]:
    loaded = source is not None and source.status in {"loaded", "ready", "complete"}
    return {
        "controlCode": code,
        "section": section,
        "title": title,
        "status": "confirmed" if loaded else "not_confirmed",
        "sourceKind": source.source_type if source else "missing",
        "evidenceStatus": source.status if source else "missing",
        "issueCode": None if loaded else "source_gap",
        "nextAction": "Проверить источник и расхождения перед подтверждением.",
    }


def _source_gap_issues(
    sources: Mapping[str, AccountingEvidenceSource],
    required: Mapping[str, str],
) -> list[dict[str, Any]]:
    result = []
    for source_type, section in required.items():
        source = sources.get(source_type)
        if source is not None and source.status in {"loaded", "ready", "complete"}:
            continue
        result.append(
            {
                "code": f"{source_type}_gap",
                "severity": "warning",
                "section": section,
                "message": f"Источник «{section}» не подтверждён за выбранный период.",
                "nextAction": (
                    "Проверить публикацию 1С и повторить загрузку только для чтения."
                ),
            }
        )
    return result


def _account_lookup(
    source: AccountingEvidenceSource | None,
) -> dict[str, Mapping[str, Any]]:
    if source is None:
        return {}
    return {
        str(row.get("Ref_Key") or ""): row
        for row in source.rows
        if str(row.get("Ref_Key") or "")
    }


def _description_lookup(
    source: AccountingEvidenceSource | None,
) -> dict[str, str]:
    if source is None:
        return {}
    return {
        str(row.get("Ref_Key") or ""): str(
            row.get("Description") or row.get("Наименование") or ""
        )
        for row in source.rows
        if str(row.get("Ref_Key") or "")
    }


def _organization_rows(
    source: AccountingEvidenceSource | None,
    organization_id: str,
) -> list[Mapping[str, Any]]:
    if source is None:
        return []
    result = []
    for row in source.rows:
        row_organization = _first_text(
            row,
            ("Организация_Key", "Organization_Key", "Organization", "Организация"),
        )
        if row_organization != organization_id:
            continue
        result.append(row)
    return result


def _organization_period_rows(
    source: AccountingEvidenceSource | None,
    organization_id: str,
    period_start: date,
    period_end: date,
    *,
    date_fields: tuple[str, ...],
) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    for row in _organization_rows(source, organization_id):
        row_date = next(
            (
                parsed
                for field in date_fields
                if (parsed := _parse_date(row.get(field))) is not None
            ),
            None,
        )
        if row_date is None or not (period_start <= row_date <= period_end):
            continue
        result.append(row)
    return result


def _balance_and_turnover_rows(
    source: AccountingEvidenceSource | None,
    chart: Mapping[str, Mapping[str, Any]],
    organization_id: str,
) -> list[dict[str, Any]]:
    result = []
    for row in _organization_rows(source, organization_id):
        account_key = _first_text(
            row,
            ("Account_Key", "Счет_Key", "Account", "Счет"),
        )
        account = chart.get(account_key, {})
        account_code = _first_text(
            row,
            ("Account_Code", "Счет_Code", "Code", "КодСчета", "НомерСчета"),
        ) or str(account.get("Code") or "")
        if not account_code:
            continue
        result.append(
            {
                "accountCode": account_code,
                "accountName": _first_text(
                    row,
                    ("Account_Description", "Счет_Description", "Account_Name"),
                )
                or str(account.get("Description") or ""),
                "openingDebit": _amount_by_alias(row, "opening", "debit"),
                "openingCredit": _amount_by_alias(row, "opening", "credit"),
                "debitTurnover": _amount_by_alias(row, "turnover", "debit"),
                "creditTurnover": _amount_by_alias(row, "turnover", "credit"),
                "closingDebit": _amount_by_alias(row, "closing", "debit"),
                "closingCredit": _amount_by_alias(row, "closing", "credit"),
            }
        )
    return result


def _record_type_rows(
    source: AccountingEvidenceSource | None,
    chart: Mapping[str, Mapping[str, Any]],
    organization_id: str,
    *,
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in _organization_rows(source, organization_id):
        row_date = _parse_date(row.get("Period"))
        if row_date is None or row_date < period_start or row_date > period_end:
            continue
        amount = _first_decimal(row, ("Сумма", "Amount"))
        if amount is None:
            continue
        for side, key_name in (("debit", "AccountDr_Key"), ("credit", "AccountCr_Key")):
            account_key = str(row.get(key_name) or "")
            account = chart.get(account_key, {})
            account_code = str(account.get("Code") or account_key)
            if not account_code:
                continue
            item = buckets.setdefault(
                account_code,
                {
                    "accountCode": account_code,
                    "accountName": str(account.get("Description") or ""),
                    "openingDebit": None,
                    "openingCredit": None,
                    "debitTurnover": Decimal("0"),
                    "creditTurnover": Decimal("0"),
                    "closingDebit": None,
                    "closingCredit": None,
                },
            )
            field = "debitTurnover" if side == "debit" else "creditTurnover"
            item[field] += amount
    result = []
    for item in buckets.values():
        item["debitTurnover"] = _decimal_text(item["debitTurnover"])
        item["creditTurnover"] = _decimal_text(item["creditTurnover"])
        result.append(item)
    return sorted(result, key=lambda item: str(item["accountCode"]))


def _amount_by_alias(
    row: Mapping[str, Any], balance_kind: str, side: str
) -> str | None:
    aliases = {
        ("opening", "debit"): (
            "OpeningDebit",
            "OpeningBalanceDt",
            "СуммаOpeningBalanceDt",
            "НачальноеСальдоДт",
        ),
        ("opening", "credit"): (
            "OpeningCredit",
            "OpeningBalanceCt",
            "СуммаOpeningBalanceCt",
            "НачальноеСальдоКт",
        ),
        ("turnover", "debit"): (
            "DebitTurnover",
            "TurnoverDt",
            "СуммаTurnoverDt",
            "ОборотДт",
        ),
        ("turnover", "credit"): (
            "CreditTurnover",
            "TurnoverCt",
            "СуммаTurnoverCt",
            "ОборотКт",
        ),
        ("closing", "debit"): (
            "ClosingDebit",
            "ClosingBalanceDt",
            "СуммаClosingBalanceDt",
            "КонечноеСальдоДт",
        ),
        ("closing", "credit"): (
            "ClosingCredit",
            "ClosingBalanceCt",
            "СуммаClosingBalanceCt",
            "КонечноеСальдоКт",
        ),
    }
    value = _first_decimal(row, aliases[(balance_kind, side)])
    return _decimal_text(value) if value is not None else None


def _tax_classification(name: str) -> tuple[str, bool, str | None]:
    normalized = name.casefold()
    if "страх" in normalized or "взнос" in normalized:
        return "insurance_contribution", False, "insurance_contribution"
    if "ндфл" in normalized:
        return "agent_ndfl", False, "agent_payment"
    if "дивиденд" in normalized:
        return "agent_profit_tax_dividends", False, "agent_payment"
    if not normalized.strip() or "не классифицирован" in normalized:
        return "unclassified", False, "unclassified"
    return "own_tax", True, None


def _tax_payment_match_kind(value: str) -> str | None:
    normalized = value.casefold()
    markers = {
        "insurance": ("страх", "взнос"),
        "ndfl": ("ндфл",),
        "dividend_tax": ("дивиденд",),
        "vat": ("ндс",),
        "usn": ("усн", "упрощ"),
        "profit_tax": ("прибыл",),
        "property_tax": ("имуще",),
        "transport_tax": ("транспорт",),
        "land_tax": ("земел",),
    }
    matches = {
        tax_kind
        for tax_kind, values in markers.items()
        if any(marker in normalized for marker in values)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _bank_tax_payments(
    rows: list[Mapping[str, Any]],
) -> tuple[dict[str, Decimal], bool]:
    tax_rows = [
        row
        for row in rows
        if row.get("Posted") is True
        and row.get("DeletionMark") is not True
        and str(row.get("ВидОперации") or "").strip().casefold() == "налоги"
    ]
    if not tax_rows:
        return {}, False
    paid_by_kind: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in tax_rows:
        tax_kind = _tax_payment_match_kind(
            " ".join(
                str(row.get(key) or "")
                for key in ("НазначениеПлатежа", "Комментарий")
            )
        )
        paid = _first_decimal(row, ("СуммаДокумента", "Сумма", "Amount"))
        if tax_kind is None or paid is None:
            return {}, False
        paid_by_kind[tax_kind] += paid
    return dict(paid_by_kind), True


def _sum_rows(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> str | None:
    values = [_first_decimal(row, keys) for row in rows]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return _decimal_text(sum(present, Decimal("0")))


def _vat_rate_label(value: Any) -> str:
    normalized = "".join(str(value or "").strip().casefold().split())
    if not normalized:
        return "Не указано"
    if "безндс" in normalized or "необлага" in normalized:
        return "Без НДС"
    numbers = re.findall(r"\d+", normalized)
    if len(numbers) >= 2:
        return f"{numbers[0]}/{numbers[1]}"
    if numbers:
        return f"{numbers[0]} %"
    return "Не определено"


def _vat_book_rows(
    rows: list[Mapping[str, Any]],
    *,
    book_kind: str,
    counterparty_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    if book_kind not in {"sales", "purchase"}:
        raise ValueError("unsupported VAT book kind")
    counterparty_key = "Покупатель_Key" if book_kind == "sales" else "Поставщик_Key"
    invoice_number_keys = (
        ("НомерСчетаФактурыНаАванс", "НомерДокументаОплаты")
        if book_kind == "sales"
        else ("НомерСчетаФактуры", "НомерДокументаОплаты")
    )
    invoice_date_keys = (
        ("ДатаСчетаФактурыНаАванс", "ДатаДокументаОплаты")
        if book_kind == "sales"
        else ("ДатаСчетаФактуры", "ДатаДокументаОплаты")
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("Active") is False:
            continue
        amount_excluding_vat = _first_decimal(row, ("СуммаБезНДС",))
        vat_amount = _first_decimal(row, ("НДС", "VAT"))
        amount_including_vat = (
            amount_excluding_vat + vat_amount
            if amount_excluding_vat is not None and vat_amount is not None
            else None
        )
        counterparty_id = str(row.get(counterparty_key) or "").strip()
        is_additional = row.get("ЗаписьДополнительногоЛиста")
        is_correction = row.get("Исправление")
        result.append(
            {
                "entryDate": _date_text(row.get("Period") or row.get("ДатаСобытия")),
                "counterpartyName": (
                    counterparty_names.get(counterparty_id) or "Не определён"
                ),
                "invoiceNumber": _first_text(row, invoice_number_keys) or "Не указан",
                "invoiceDate": next(
                    (
                        parsed
                        for key in invoice_date_keys
                        if (parsed := _date_text(row.get(key))) is not None
                    ),
                    None,
                ),
                "vatRate": _vat_rate_label(row.get("СтавкаНДС")),
                "amountExcludingVat": (
                    _decimal_text(amount_excluding_vat)
                    if amount_excluding_vat is not None
                    else None
                ),
                "vatAmount": (
                    _decimal_text(vat_amount) if vat_amount is not None else None
                ),
                "amountIncludingVat": (
                    _decimal_text(amount_including_vat)
                    if amount_including_vat is not None
                    else None
                ),
                "entryKind": (
                    "Дополнительный лист"
                    if is_additional is True
                    else ("Основная запись" if is_additional is False else "Не указано")
                ),
                "correctionStatus": (
                    "Исправление"
                    if is_correction is True
                    else ("Без исправления" if is_correction is False else "Не указано")
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            str(item.get("entryDate") or ""),
            str(item.get("counterpartyName") or ""),
            str(item.get("invoiceNumber") or ""),
        ),
    )


def _vat_book_totals(
    rows: list[Mapping[str, Any]],
    source: AccountingEvidenceSource | None,
) -> dict[str, Any]:
    active_rows = [row for row in rows if row.get("Active") is not False]
    status = _source_status(source)
    if status not in COMPLETE_SOURCE_STATUSES:
        return {
            "rowCount": len(active_rows),
            "amountExcludingVat": None,
            "vatAmount": None,
            "amountIncludingVat": None,
        }
    amount_excluding_vat = _complete_sum_rows(active_rows, ("СуммаБезНДС",))
    vat_amount = _complete_sum_rows(active_rows, ("НДС", "VAT"))
    including_vat = (
        _decimal_text(Decimal(amount_excluding_vat) + Decimal(vat_amount))
        if amount_excluding_vat is not None and vat_amount is not None
        else None
    )
    return {
        "rowCount": len(active_rows),
        "amountExcludingVat": amount_excluding_vat,
        "vatAmount": vat_amount,
        "amountIncludingVat": including_vat,
    }


def _rwb_vat_reconciliation(
    *,
    sources: Mapping[str, AccountingEvidenceSource],
    organization_id: str,
    period_start: date,
    period_end: date,
    counterparty_names: Mapping[str, str],
    purchase_book_rows: list[dict[str, Any]],
    purchase_book_source: AccountingEvidenceSource | None,
) -> dict[str, Any]:
    rwb_counterparty_ids = {
        counterparty_id
        for counterparty_id, name in counterparty_names.items()
        if _is_rwb_counterparty_name(name)
    }
    counterparty_source = sources.get("onec_accounting_counterparties")
    nomenclature_source = sources.get("onec_nomenclature")
    nomenclature_names = _description_lookup(nomenclature_source)
    supplier_receipts_source = sources.get("onec_supplier_receipts")
    supplier_expenses_source = sources.get("onec_supplier_receipt_expenses")
    incoming_invoices_source = sources.get("onec_incoming_invoices")

    supplier_receipts = _rwb_receipt_headers(
        supplier_receipts_source,
        organization_id=organization_id,
        period_start=period_start,
        period_end=period_end,
        rwb_counterparty_ids=rwb_counterparty_ids,
    )
    supplier_rows = _rwb_supplier_service_rows(
        supplier_receipts,
        supplier_expenses_source,
        nomenclature_names=nomenclature_names,
    )
    incoming_receipts = _rwb_receipt_headers(
        incoming_invoices_source,
        organization_id=organization_id,
        period_start=period_start,
        period_end=period_end,
        rwb_counterparty_ids=rwb_counterparty_ids,
    )
    incoming_rows = _rwb_incoming_invoice_service_rows(
        incoming_receipts,
        nomenclature_names=nomenclature_names,
    )

    supplier_status = _combined_status(
        counterparty_source,
        nomenclature_source,
        supplier_receipts_source,
        supplier_expenses_source,
    )
    incoming_status = _combined_status(
        counterparty_source,
        nomenclature_source,
        incoming_invoices_source,
    )
    if supplier_rows:
        service_rows = supplier_rows
        service_status = supplier_status
    elif incoming_rows:
        service_rows = incoming_rows
        service_status = (
            incoming_status
            if incoming_status in COMPLETE_SOURCE_STATUSES
            else "partial_source"
        )
    else:
        service_rows = []
        incomplete_headers = (
            bool(supplier_receipts)
            and supplier_status not in COMPLETE_SOURCE_STATUSES
        ) or (
            bool(incoming_receipts)
            and incoming_status not in COMPLETE_SOURCE_STATUSES
        )
        if incomplete_headers:
            service_status = "partial_source"
        elif (
            supplier_status in COMPLETE_SOURCE_STATUSES
            or incoming_status in COMPLETE_SOURCE_STATUSES
        ):
            service_status = "empty_expected"
        elif supplier_status == "missing" and incoming_status == "missing":
            service_status = "missing"
        else:
            service_status = "partial_source"

    rwb_purchase_rows = [
        row
        for row in purchase_book_rows
        if _is_rwb_counterparty_name(str(row.get("counterpartyName") or ""))
    ]
    purchase_status = _source_status(purchase_book_source)
    for row in service_rows:
        included, invoice_number = _rwb_purchase_book_match(
            row,
            rwb_purchase_rows,
            purchase_status=purchase_status,
        )
        row["purchaseBookIncluded"] = included
        row["purchaseBookInvoiceNumber"] = invoice_number

    service_totals = _rwb_service_totals(service_rows, service_status)
    purchase_totals = _rwb_service_totals(rwb_purchase_rows, purchase_status)
    vat_difference = _decimal_difference(
        purchase_totals.get("vatAmount"),
        service_totals.get("vatAmount"),
    )
    if (
        service_status not in COMPLETE_SOURCE_STATUSES
        or purchase_status not in COMPLETE_SOURCE_STATUSES
        or vat_difference is None
    ):
        status = (
            "missing"
            if service_status == "missing" and purchase_status == "missing"
            else "partial_source"
        )
    elif not service_rows and not rwb_purchase_rows:
        status = "empty_expected"
    elif Decimal(vat_difference) == Decimal("0"):
        status = "matched"
    else:
        status = "mismatch"

    return {
        "status": status,
        "sourceStatus": service_status,
        "purchaseBookStatus": purchase_status,
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "serviceTotals": service_totals,
        "purchaseBookTotals": purchase_totals,
        "vatDifference": vat_difference,
        "rows": sorted(
            service_rows,
            key=lambda item: (
                str(item.get("documentDate") or ""),
                str(item.get("documentNumber") or ""),
                str(item.get("serviceCategory") or ""),
                str(item.get("serviceName") or ""),
            ),
        ),
    }


def _rwb_receipt_headers(
    source: AccountingEvidenceSource | None,
    *,
    organization_id: str,
    period_start: date,
    period_end: date,
    rwb_counterparty_ids: set[str],
) -> list[Mapping[str, Any]]:
    return [
        row
        for row in _organization_period_rows(
            source,
            organization_id,
            period_start,
            period_end,
            date_fields=("Date", "Дата"),
        )
        if row.get("Posted") is True
        and row.get("DeletionMark") is not True
        and _first_text(row, ("Контрагент_Key", "Counterparty_Key"))
        in rwb_counterparty_ids
    ]


def _rwb_supplier_service_rows(
    receipts: list[Mapping[str, Any]],
    expense_source: AccountingEvidenceSource | None,
    *,
    nomenclature_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    receipts_by_id = {
        _first_text(row, ("Ref_Key",)): row
        for row in receipts
        if _first_text(row, ("Ref_Key",))
    }
    if expense_source is None or not receipts_by_id:
        return []
    result: list[dict[str, Any]] = []
    for expense in expense_source.rows:
        receipt_id = _first_text(expense, ("Ref_Key", "Recorder", "Документ_Key"))
        receipt = receipts_by_id.get(receipt_id)
        if receipt is None:
            continue
        result.append(
            _rwb_service_row(
                receipt,
                expense,
                nomenclature_names=nomenclature_names,
                source_kind="onec_supplier_receipt_expenses",
            )
        )
    return result


def _rwb_incoming_invoice_service_rows(
    receipts: list[Mapping[str, Any]],
    *,
    nomenclature_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for receipt in receipts:
        expense_rows = receipt.get("Расходы") or receipt.get("Услуги")
        if not isinstance(expense_rows, list):
            continue
        for expense in expense_rows:
            if not isinstance(expense, Mapping):
                continue
            result.append(
                _rwb_service_row(
                    receipt,
                    expense,
                    nomenclature_names=nomenclature_names,
                    source_kind="onec_incoming_invoices",
                )
            )
    return result


def _rwb_service_row(
    receipt: Mapping[str, Any],
    expense: Mapping[str, Any],
    *,
    nomenclature_names: Mapping[str, str],
    source_kind: str,
) -> dict[str, Any]:
    service_name = _first_text(
        expense,
        ("Содержание", "Наименование", "Description"),
    )
    if not service_name:
        service_name = nomenclature_names.get(
            _first_text(expense, ("Номенклатура_Key",)),
            "",
        )
    if not service_name:
        service_name = "Не определено"
    amount_excluding_vat, vat_amount, amount_including_vat = _rwb_service_amounts(
        receipt,
        expense,
    )
    return {
        "rowKind": "detail",
        "documentDate": _date_text(receipt.get("Date") or receipt.get("Дата")),
        "documentNumber": _first_text(receipt, ("Number", "Номер"))
        or "Не указан",
        "inputNumber": _first_text(
            receipt,
            ("НомерВходящегоДокумента", "InputDocumentNumber"),
        )
        or "Не указан",
        "inputDate": _date_text(
            receipt.get("ДатаВходящегоДокумента")
            or receipt.get("InputDocumentDate")
        ),
        "serviceCategory": (
            classify_marketplace_service(service_name)
            if service_name != "Не определено"
            else "Не определено"
        ),
        "serviceName": service_name,
        "amountExcludingVat": amount_excluding_vat,
        "vatAmount": vat_amount,
        "amountIncludingVat": amount_including_vat,
        "purchaseBookIncluded": "unknown",
        "purchaseBookInvoiceNumber": "",
        "sourceKind": source_kind,
    }


def _rwb_service_amounts(
    receipt: Mapping[str, Any],
    expense: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    amount = _first_decimal(expense, ("СуммаБезНДС", "Сумма", "Amount"))
    vat = _first_decimal(expense, ("СуммаНДС", "НДС", "VAT"))
    total = _first_decimal(expense, ("Всего", "СуммаСНДС", "Total"))
    includes_vat = receipt.get("СуммаВключаетНДС") is True
    if amount is None and total is not None and vat is not None:
        amount = total - vat
    elif amount is not None and vat is not None:
        if includes_vat or (total is not None and total == amount):
            total = total if total is not None else amount
            amount = amount - vat
        elif total is None:
            total = amount + vat
    return (
        _decimal_text(amount) if amount is not None else None,
        _decimal_text(vat) if vat is not None else None,
        _decimal_text(total) if total is not None else None,
    )


def _rwb_purchase_book_match(
    service_row: Mapping[str, Any],
    purchase_rows: list[dict[str, Any]],
    *,
    purchase_status: str,
) -> tuple[str, str]:
    if purchase_status not in COMPLETE_SOURCE_STATUSES:
        return "unknown", ""
    input_number = _document_number_key(service_row.get("inputNumber"))
    input_date = str(service_row.get("inputDate") or "")
    if not input_number or not input_date:
        return "unknown", ""
    number_match_without_date = False
    for purchase_row in purchase_rows:
        invoice_number = _document_number_key(purchase_row.get("invoiceNumber"))
        if not invoice_number or invoice_number != input_number:
            continue
        invoice_date = str(purchase_row.get("invoiceDate") or "")
        if not invoice_date:
            number_match_without_date = True
            continue
        if input_date != invoice_date:
            continue
        return "yes", str(purchase_row.get("invoiceNumber") or "")
    if number_match_without_date:
        return "unknown", ""
    return "no", ""


def _rwb_service_totals(
    rows: list[Mapping[str, Any]],
    source_status: str,
) -> dict[str, Any]:
    if source_status not in COMPLETE_SOURCE_STATUSES:
        return {
            "rowCount": len(rows),
            "amountExcludingVat": None,
            "vatAmount": None,
            "amountIncludingVat": None,
        }
    return {
        "rowCount": len(rows),
        "amountExcludingVat": _complete_sum_rows(rows, ("amountExcludingVat",)),
        "vatAmount": _complete_sum_rows(rows, ("vatAmount",)),
        "amountIncludingVat": _complete_sum_rows(rows, ("amountIncludingVat",)),
    }


def _is_rwb_counterparty_name(value: str) -> bool:
    normalized = "".join(
        character for character in value.casefold() if character.isalnum()
    )
    return any(
        marker in normalized for marker in ("рвб", "wildberries", "вайлдберриз")
    )


def _document_number_key(value: Any) -> str:
    normalized = "".join(
        character for character in str(value or "").casefold() if character.isalnum()
    )
    return "" if normalized in {"", "неуказан"} else normalized


def _decimal_difference(left: Any, right: Any) -> str | None:
    try:
        if left is None or right is None:
            return None
        return _decimal_text(Decimal(str(left)) - Decimal(str(right)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _complete_sum_rows(
    rows: list[Mapping[str, Any]], keys: tuple[str, ...]
) -> str | None:
    values = [_first_decimal(row, keys) for row in rows]
    if any(value is None for value in values):
        return None
    return _decimal_text(
        sum((value for value in values if value is not None), Decimal("0"))
    )


def _confirmed_sum_rows(
    rows: list[Mapping[str, Any]],
    keys: tuple[str, ...],
    *,
    source_status: str,
) -> str | None:
    if source_status not in COMPLETE_SOURCE_STATUSES:
        return None
    return _complete_sum_rows(rows, keys)


def _normalized_kudir_record_kind(row: Mapping[str, Any]) -> str:
    return "".join(
        character
        for character in str(row.get("ВидЗаписи") or "").casefold()
        if character.isalnum()
    )


def _kudir_expense_category(row: Mapping[str, Any]) -> str:
    record_kind = _normalized_kudir_record_kind(row)
    if "расходынатовары" in record_kind:
        return "goods"
    if "расходынауслуги" in record_kind:
        return "services"
    if "расходынаоплатутруда" in record_kind:
        return "payroll"
    if (
        "расходынастраховыевзносы" in record_kind
        or "расходынавзносыподлежащиеуплатеип" in record_kind
    ):
        return "contributions"
    if record_kind in {
        "расходынаосинма",
        "расходыпрочие",
        "расходынатаможенныеплатежи",
        "расходыенп",
    }:
        return "other"
    return "review_required"


def _is_kudir_expense_row(row: Mapping[str, Any]) -> bool:
    if row.get("Active") is False:
        return False
    record_kind = _normalized_kudir_record_kind(row)
    if not record_kind or "доход" in record_kind or "приход" in record_kind:
        return False
    if _kudir_expense_category(row) != "review_required":
        return True
    if "расход" in record_kind:
        return True
    expense_amount = _first_decimal(row, ("РасходБаза", "РасходВсего"))
    return expense_amount is not None and expense_amount != 0


def _kudir_expense_breakdown(
    rows: list[Mapping[str, Any]],
    *,
    source_status: str,
) -> tuple[list[dict[str, Any]], str]:
    source_complete = source_status in COMPLETE_SOURCE_STATUSES
    amounts_complete = all(
        _first_decimal(row, ("РасходБаза",)) is not None for row in rows
    )
    review_required = any(
        _kudir_expense_category(row) == "review_required" for row in rows
    )
    if not source_complete or not amounts_complete:
        classification_status = "source_gap"
    elif review_required:
        classification_status = "review_required"
    else:
        classification_status = "ready"

    result: list[dict[str, Any]] = []
    for category, label in USN_EXPENSE_CATEGORIES:
        category_rows = [
            row for row in rows if _kudir_expense_category(row) == category
        ]
        result.append(
            {
                "category": category,
                "label": label,
                "value": (
                    _complete_sum_rows(category_rows, ("РасходБаза",))
                    if source_complete
                    else None
                ),
                "rowCount": len(category_rows),
                "monthlyValues": _monthly_values(
                    category_rows,
                    date_fields=("Period", "Date", "Дата"),
                    amount_fields=("РасходБаза",),
                    source_status=source_status,
                ),
            }
        )
    return result, classification_status


def _bank_income_category(row: Mapping[str, Any]) -> str:
    normalized = _normalized_bank_operation(row)
    if normalized in {"отпокупателя", "оплатаотпокупателя"}:
        return "confirmed"
    if "личн" in normalized and "предприним" in normalized:
        return "excluded"
    if _is_loan_operation(normalized):
        return "loans"
    return "unclassified"


def _normalized_bank_operation(row: Mapping[str, Any]) -> str:
    return "".join(
        character
        for character in str(row.get("ВидОперации") or "").casefold()
        if character.isalnum()
    )


def _is_loan_operation(normalized_operation: str) -> bool:
    return "кредит" in normalized_operation or "займ" in normalized_operation


def _is_payroll_operation(normalized_operation: str) -> bool:
    return (
        "зарплат" in normalized_operation
        or "оплататруда" in normalized_operation
        or (
            "заработн" in normalized_operation
            and "плат" in normalized_operation
        )
    )


def _is_kudir_income_row(row: Mapping[str, Any]) -> bool:
    if row.get("Active") is False:
        return False
    record_kind = str(row.get("ВидЗаписи") or "").strip().casefold()
    if not record_kind or "доход" in record_kind or "приход" in record_kind:
        return True
    income_amount = _first_decimal(row, ("ДоходБаза", "ДоходВсего"))
    return income_amount is not None and income_amount != 0


def _bank_income_net_amount(row: Mapping[str, Any]) -> Decimal | None:
    document_total = _first_decimal(
        row, ("СуммаДокумента", "Сумма", "Amount")
    )
    raw_breakdown = row.get("РасшифровкаПлатежа")
    if isinstance(raw_breakdown, list) and raw_breakdown:
        payment_total = Decimal("0")
        vat_total = Decimal("0")
        for item in raw_breakdown:
            if not isinstance(item, Mapping):
                return None
            payment = _first_decimal(
                item, ("СуммаПлатежа", "PaymentAmount", "Amount")
            )
            vat = _first_decimal(item, ("СуммаНДС", "VAT"))
            item_vat_mode = str(item.get("НалогообложениеНДС") or "").casefold()
            if vat is None and "необлагается" in item_vat_mode:
                vat = Decimal("0")
            if payment is None or vat is None:
                return None
            payment_total += payment
            vat_total += vat
        if document_total is not None and payment_total != document_total:
            return None
        net_amount = payment_total - vat_total
        return net_amount if net_amount >= 0 else None
    vat_mode = str(row.get("НалогообложениеНДС") or "").casefold()
    if document_total is not None and "необлагается" in vat_mode:
        return document_total if document_total >= 0 else None
    return None


def _usn_marketplace_counterparty_categories(
    source: AccountingEvidenceSource | None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    if source is None:
        return result
    for row in source.rows:
        if row.get("DeletionMark") is True:
            continue
        counterparty_id = str(row.get("Ref_Key") or "").strip()
        normalized_name = "".join(
            character
            for character in str(row.get("Description") or "").casefold()
            if character.isalnum()
        )
        if not counterparty_id:
            continue
        if "интернетрешения" in normalized_name:
            result[counterparty_id] = "ozon"
        elif "рвб" in normalized_name:
            result[counterparty_id] = "wildberries"
    return result


def _classify_usn_bank_income_rows(
    rows: list[Mapping[str, Any]],
    *,
    counterparty_categories: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "confirmed": [],
        "unclassified": [],
        "excluded": [],
        "loans": [],
    }
    for row in rows:
        if row.get("Posted") is not True or row.get("DeletionMark") is True:
            continue
        net_amount = _bank_income_net_amount(row)
        income_category = _bank_income_category(row)
        normalized = {
            "Date": row.get("Date") or row.get("Period") or row.get("Дата"),
            "incomeNetAmount": (
                _decimal_text(net_amount) if net_amount is not None else None
            ),
        }
        if income_category == "confirmed":
            counterparty_id = str(row.get("Контрагент_Key") or "").strip()
            normalized["marketplaceCategory"] = (
                (counterparty_categories or {}).get(counterparty_id) or "other"
            )
        result[income_category].append(normalized)
    return result


def _usn_payroll_payment_evidence(
    rows: list[Mapping[str, Any]],
    *,
    source: AccountingEvidenceSource | None,
) -> dict[str, Any]:
    source_status = _source_status(source)
    source_available = source_status in COMPLETE_SOURCE_STATUSES
    posted_rows = [
        row
        for row in rows
        if row.get("Posted") is True and row.get("DeletionMark") is not True
    ]
    operations_complete = all(
        bool(_normalized_bank_operation(row)) for row in posted_rows
    )
    payroll_rows = [
        row
        for row in posted_rows
        if _is_payroll_operation(_normalized_bank_operation(row))
    ]
    amounts_complete = all(
        _first_decimal(row, ("СуммаДокумента", "Сумма", "Amount")) is not None
        for row in payroll_rows
    )
    if not source_available or not amounts_complete:
        classification_status = "source_gap"
    elif not operations_complete:
        classification_status = "review_required"
    else:
        classification_status = "ready"
    value = (
        _complete_sum_rows(
            payroll_rows,
            ("СуммаДокумента", "Сумма", "Amount"),
        )
        if source_available and operations_complete and amounts_complete
        else None
    )
    return {
        "value": value,
        "status": source_status,
        "classificationStatus": classification_status,
        "sourceKind": "onec_accounting_bank_out",
        "snapshotId": source.snapshot_id if source else "",
        "monthlyValues": _monthly_values(
            payroll_rows,
            date_fields=("Period", "Date", "Дата"),
            amount_fields=("СуммаДокумента", "Сумма", "Amount"),
            source_status=source_status,
        ),
        "rowCount": len(payroll_rows),
    }


def _usn_marketplace_breakdown(
    rows: list[Mapping[str, Any]],
    *,
    period_start: date,
    period_end: date,
    source_status: str,
) -> list[dict[str, Any]]:
    month_keys = _month_keys(period_start, period_end)
    result: list[dict[str, Any]] = []
    for category, label in USN_MARKETPLACE_CATEGORIES:
        category_rows = [
            row for row in rows if row.get("marketplaceCategory") == category
        ]
        monthly_by_key = {
            str(item.get("month") or ""): item
            for item in _monthly_values(
                category_rows,
                date_fields=("Date",),
                amount_fields=("incomeNetAmount",),
                source_status=source_status,
            )
        }
        result.append(
            {
                "category": category,
                "label": label,
                "value": _complete_sum_rows(
                    category_rows, ("incomeNetAmount",)
                ),
                "rowCount": len(category_rows),
                "monthlyValues": [
                    monthly_by_key.get(month)
                    or {
                        "month": month,
                        "value": "0",
                        "status": source_status,
                        "rowCount": 0,
                    }
                    for month in month_keys
                ],
            }
        )
    return result


def _month_keys(period_start: date, period_end: date) -> list[str]:
    current = period_start.replace(day=1)
    last = period_end.replace(day=1)
    result: list[str] = []
    while current <= last:
        result.append(current.strftime("%Y-%m"))
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return result


def _monthly_values(
    rows: list[Mapping[str, Any]],
    *,
    date_fields: tuple[str, ...],
    amount_fields: tuple[str, ...],
    source_status: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_date = next(
            (
                parsed
                for field in date_fields
                if (parsed := _parse_date(row.get(field))) is not None
            ),
            None,
        )
        if row_date is None:
            continue
        month = row_date.strftime("%Y-%m")
        bucket = buckets.setdefault(
            month,
            {
                "month": month,
                "total": Decimal("0"),
                "rowCount": 0,
                "missingAmount": False,
            },
        )
        bucket["rowCount"] += 1
        amount = _first_decimal(row, amount_fields)
        if amount is None:
            bucket["missingAmount"] = True
        else:
            bucket["total"] += amount
    return [
        {
            "month": month,
            "value": (
                None if item["missingAmount"] else _decimal_text(item["total"])
            ),
            "status": "partial_source" if item["missingAmount"] else source_status,
            "rowCount": item["rowCount"],
        }
        for month, item in sorted(buckets.items())
    ]


def _first_decimal(row: Mapping[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        if key not in row or row.get(key) in (None, ""):
            continue
        try:
            return Decimal(str(row.get(key)).replace(" ", "").replace(",", "."))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _first_text(row: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _date_text(value: Any) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif value:
        try:
            parsed = date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.year >= 1900 else None


def _source_status(source: AccountingEvidenceSource | None) -> str:
    return source.status if source is not None else "missing"


def _combined_status(*sources: AccountingEvidenceSource | None) -> str:
    statuses = {_source_status(source) for source in sources}
    if statuses and statuses.issubset(COMPLETE_SOURCE_STATUSES):
        return "loaded"
    if statuses == {"missing"}:
        return "missing"
    return "partial_source"


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
