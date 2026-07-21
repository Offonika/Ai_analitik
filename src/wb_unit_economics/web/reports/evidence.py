from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from wb_unit_economics.web.report_kinds import MONTH_CLOSE_CONTROL, TAX_LOAD

MONTH_CLOSE_EVIDENCE_VERSION = "month-close-evidence-v2"
TAX_LOAD_EVIDENCE_VERSION = "tax-load-evidence-v2"


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
                "message": "Ни штатная ОСВ, ни RecordType fallback не дали строк.",
                "nextAction": "Проверить публикацию 1С и повторить read-only загрузку.",
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
    tax_lookup = _description_lookup(sources.get("onec_tax_kinds"))
    raw_tax_rows = _organization_period_rows(
        sources.get("onec_accounting_taxes"),
        organization_id,
        period_start,
        period_end,
        date_fields=("Period",),
    )
    payment_source = sources.get("onec_accounting_taxes_on_ens")
    raw_payment_rows = _organization_period_rows(
        payment_source,
        organization_id,
        period_start,
        period_end,
        date_fields=("Period", "Date", "СрокУплаты"),
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
    for tax_code, _due_date in grouped:
        tax_code_counts[tax_code] += 1
    for item in grouped.values():
        payment_kind, included, exclusion_reason = _tax_classification(
            str(item["taxName"])
        )
        tax_code = str(item["taxCode"])
        paid = paid_by_tax.get((tax_code, str(item["dueDate"] or "")))
        if paid is None and tax_code_counts[tax_code] == 1:
            paid = paid_by_tax.get((tax_code, ""))
        item["accrued"] = _decimal_text(item["accrued"])
        item["paid"] = _decimal_text(paid) if paid is not None else None
        item["valueStatus"] = "loaded" if paid is not None else "partial"
        item["evidenceStatus"] = (
            "loaded"
            if paid is not None
            and payment_source is not None
            and payment_source.status in {"loaded", "ready", "complete"}
            else "partial_source"
        )
        item["sourceKind"] = (
            "onec_accounting_taxes_on_ens" if paid is not None else "onec_tax_register"
        )
        item["issueCode"] = None if paid is not None else "paid_tax_fact_unconfirmed"
        item["paymentKind"] = payment_kind
        item["includedInFnsTaxBurden"] = included
        item["exclusionReason"] = exclusion_reason
        tax_rows.append(item)
    tax_rows.sort(key=lambda item: (str(item["taxName"]), str(item["dueDate"] or "")))

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
    # Доход-база по УСН без НДС из КУДиР (AccumulationRegister
    # КнигаУчетаДоходовИРасходов, ресурс ДоходБаза) — управленческий знаменатель
    # для ИП на УСН, у которого нет отчета о финансовых результатах (spec: Tax
    # Methodology Boundary, решение от 21.07.2026).
    usn_income_source = sources.get("onec_kudir")
    usn_income_rows = _organization_period_rows(
        usn_income_source,
        organization_id,
        period_start.replace(month=1, day=1),
        period_end,
        date_fields=("Period", "Date", "Дата"),
    )
    usn_income_evidence = {
        "value": _sum_rows(usn_income_rows, ("ДоходБаза", "ДоходВсего")),
        "status": _source_status(usn_income_source),
        "sourceKind": "onec_kudir",
        "snapshotId": usn_income_source.snapshot_id if usn_income_source else "",
    }
    issues = _source_gap_issues(
        sources,
        {
            "onec_accounting_taxes": "Налоги",
            "onec_accounting_taxes_on_ens": "Платежи",
            "onec_official_financial_results": "Доходный знаменатель",
        },
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
    return {
        "sourceCoverage": _coverage(
            sources, period_start.replace(month=1, day=1), period_end
        ),
        "taxRows": tax_rows,
        "incomeEvidence": income_evidence,
        "usnIncomeEvidence": usn_income_evidence,
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
                "message": (
                    f"Источник {source_type} не подтвержден за выбранный период."
                ),
                "nextAction": "Проверить публикацию 1С и повторить read-only загрузку.",
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


def _sum_rows(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> str | None:
    values = [_first_decimal(row, keys) for row in rows]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return _decimal_text(sum(present, Decimal("0")))


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
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _source_status(source: AccountingEvidenceSource | None) -> str:
    return source.status if source is not None else "missing"


def _combined_status(*sources: AccountingEvidenceSource | None) -> str:
    statuses = {_source_status(source) for source in sources}
    if statuses and statuses.issubset({"loaded", "ready", "complete"}):
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
