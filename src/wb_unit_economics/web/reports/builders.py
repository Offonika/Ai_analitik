from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from wb_unit_economics.web.reports.contracts import (
    MonthCloseControlPayload,
    TaxLoadPayload,
)
from wb_unit_economics.web.reports.month_close import normalize_month_close_osv

MONTH_CLOSE_CONTRACT_VERSION = "month-close-control-report-v2"
TAX_LOAD_CONTRACT_VERSION = "tax-load-report-v7"
FNS_TAX_BURDEN_METHODOLOGY_VERSION = "fns-tax-burden-v1-2026-07-14"
USN_INCOME_EXPENSES_METHODOLOGY_VERSION = "usn_income_expenses_v1"
CONFIRMED_EVIDENCE_STATUSES = {"loaded", "confirmed"}
OFFICIAL_INCOME_SOURCE_KINDS = {
    "financial_result_statement",
    "official_financial_results",
    "onec_financial_results",
    "onec_official_financial_results",
}


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: object) -> str | None:
    parsed = _decimal(value)
    return format(parsed, "f") if parsed is not None else None


def fns_tax_burden_ratio(paid_taxes: object, income: object) -> Decimal | None:
    numerator = _decimal(paid_taxes)
    denominator = _decimal(income)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return ((numerator / denominator) * Decimal("100")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def _is_usn_income_tax_system(value: object) -> bool:
    normalized = str(value or "").strip().casefold()
    is_usn = (
        "usn" in normalized
        or "усн" in normalized
        or "упрощ" in normalized
    )
    has_income = "income" in normalized or "доход" in normalized
    has_expenses = "expense" in normalized or "расход" in normalized
    return is_usn and has_income and not has_expenses


def _is_usn_income_expenses_tax_system(
    tax_system: object,
    tax_object: object = None,
) -> bool:
    normalized_system = str(tax_system or "").strip().casefold()
    normalized_object = str(tax_object or "").strip().casefold()
    is_usn = (
        "usn" in normalized_system
        or "усн" in normalized_system
        or "упрощ" in normalized_system
    )
    has_expenses = (
        "expense" in normalized_system
        or "расход" in normalized_system
        or "expense" in normalized_object
        or "расход" in normalized_object
    )
    return is_usn and has_expenses


def fns_paid_taxes_numerator(tax_rows: object) -> Decimal | None:
    """Sum only classified own taxes; never treat unclassified data as zero."""

    if not isinstance(tax_rows, list) or not tax_rows:
        return None
    total = Decimal("0")
    classified_rows = 0
    for row in tax_rows:
        if not isinstance(row, Mapping):
            return None
        paid = _decimal(row.get("paid"))
        included = row.get("includedInFnsTaxBurden")
        payment_kind = str(row.get("paymentKind") or "").strip().lower()
        evidence_status = str(row.get("evidenceStatus") or "").strip().lower()
        if payment_kind == "unclassified" or (
            included is not True
            and included is not False
            and payment_kind != "own_tax"
        ):
            return None
        excluded_kind = payment_kind in {
            "agent_ndfl",
            "agent_profit_tax_dividends",
            "insurance_contribution",
        }
        if included is False or excluded_kind:
            classified_rows += 1
            continue
        if included is not True and payment_kind != "own_tax":
            return None
        if evidence_status not in CONFIRMED_EVIDENCE_STATUSES:
            return None
        if paid is None:
            return None
        total += paid
        classified_rows += 1
    return total if classified_rows else None


def _meta(report: Any, evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "reportId": report.id,
        "tenantId": report.tenant_id,
        "clientId": report.client_id,
        "reportKind": report.report_kind,
        "organizationId": report.organization_id or "",
        "periodStart": report.period_start.isoformat(),
        "periodEnd": report.period_end.isoformat(),
        "methodologyVersion": report.methodology_version,
        "generatedAt": report.generated_at.isoformat(),
        "publicationStatus": report.publication_status,
        "sourceRefreshRunId": str(evidence.get("sourceRefreshRunId") or ""),
        "sourceSnapshotSetId": str(
            getattr(report, "source_snapshot_set_id", "") or ""
        ),
        "evidenceSha256": str(evidence.get("evidenceSha256") or ""),
    }


def _safe_rows(
    rows: object, allowed: tuple[str, ...], *, limit: int = 5000
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for item in rows[:limit]:
        if not isinstance(item, Mapping):
            continue
        result.append({key: item.get(key) for key in allowed})
    return result


def _safe_summary(value: object, allowed: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value.get(key) for key in allowed}


def _safe_usn_expense_breakdown(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "category": item.get("category"),
                "label": item.get("label"),
                "valueYtd": _decimal_text(item.get("value")),
                "rowCount": item.get("rowCount"),
                "monthlyValues": _safe_rows(
                    item.get("monthlyValues"),
                    ("month", "value", "status", "rowCount"),
                ),
            }
        )
    return result


def _safe_vat_books(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    row_fields = (
        "entryDate",
        "counterpartyName",
        "invoiceNumber",
        "invoiceDate",
        "vatRate",
        "amountExcludingVat",
        "vatAmount",
        "amountIncludingVat",
        "entryKind",
        "correctionStatus",
    )
    total_fields = (
        "rowCount",
        "amountExcludingVat",
        "vatAmount",
        "amountIncludingVat",
    )
    return {
        "periodStart": value.get("periodStart"),
        "periodEnd": value.get("periodEnd"),
        "salesStatus": value.get("salesStatus"),
        "purchaseStatus": value.get("purchaseStatus"),
        "salesRows": _safe_rows(value.get("salesRows"), row_fields),
        "purchaseRows": _safe_rows(value.get("purchaseRows"), row_fields),
        "salesTotals": _safe_summary(value.get("salesTotals"), total_fields),
        "purchaseTotals": _safe_summary(value.get("purchaseTotals"), total_fields),
        "vatDifference": value.get("vatDifference"),
    }


def _safe_rwb_vat_reconciliation(
    value: object,
    *,
    vat_deduction_mode: object,
) -> dict[str, Any]:
    applicability = str(vat_deduction_mode or "unknown").strip().lower()
    if applicability not in {
        "allowed",
        "not_allowed",
        "not_applicable",
        "unknown",
    }:
        applicability = "unknown"
    row_fields = (
        "rowKind",
        "documentDate",
        "documentNumber",
        "inputNumber",
        "inputDate",
        "serviceCategory",
        "serviceName",
        "amountExcludingVat",
        "vatAmount",
        "amountIncludingVat",
        "purchaseBookIncluded",
        "purchaseBookInvoiceNumber",
        "sourceKind",
    )
    total_fields = (
        "rowCount",
        "amountExcludingVat",
        "vatAmount",
        "amountIncludingVat",
    )
    raw = value if isinstance(value, Mapping) else {}
    source_status = str(raw.get("status") or "source_gap")
    status = (
        "not_applicable"
        if applicability in {"not_allowed", "not_applicable"}
        else source_status
    )
    return {
        "applicability": applicability,
        "status": status,
        "sourceStatus": raw.get("sourceStatus") or "source_gap",
        "purchaseBookStatus": raw.get("purchaseBookStatus") or "source_gap",
        "periodStart": raw.get("periodStart"),
        "periodEnd": raw.get("periodEnd"),
        "serviceTotals": _safe_summary(raw.get("serviceTotals"), total_fields),
        "purchaseBookTotals": _safe_summary(
            raw.get("purchaseBookTotals"), total_fields
        ),
        "vatDifference": raw.get("vatDifference"),
        "rows": _safe_rows(raw.get("rows"), row_fields),
    }


def build_month_close_control_payload(
    report: Any,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence or {}
    controls = _safe_rows(
        evidence.get("controls"),
        (
            "controlCode",
            "section",
            "title",
            "status",
            "sourceKind",
            "evidenceStatus",
            "issueCode",
            "nextAction",
        ),
    )
    if not controls:
        controls = [
            {
                "controlCode": code,
                "section": section,
                "title": title,
                "status": "not_confirmed",
                "sourceKind": source,
                "evidenceStatus": "missing",
                "issueCode": "evidence_required",
                "nextAction": "Проверить источник и зафиксировать подтверждение.",
            }
            for code, section, title, source in (
                ("osv", "ОСВ", "Сверка оборотов и остатков", "onec_osv"),
                ("ens", "ЕНС и налоги", "Сверка начислений и ЕНС", "onec_tax"),
                ("vat", "НДС", "Подтверждение НДС", "onec_vat"),
                ("bank", "Банк", "Сверка движений денежных средств", "onec_bank"),
                (
                    "manual_operations",
                    "Ручные операции",
                    "Проверка ручных операций",
                    "onec_operations",
                ),
                (
                    "confirmations",
                    "Подтверждения",
                    "Подтверждения бухгалтера",
                    "manual_confirmation",
                ),
            )
        ]
    coverage = _safe_rows(
        evidence.get("sourceCoverage"),
        ("sourceKind", "periodStart", "periodEnd", "status", "snapshotId"),
    )
    issues = _safe_rows(
        evidence.get("issues"),
        ("code", "severity", "section", "message", "nextAction"),
    )
    osv_summary, osv_rows, osv_issues = normalize_month_close_osv(evidence)
    issues.extend(osv_issues)
    if not coverage:
        issues.append(
            {
                "code": "source_coverage_missing",
                "severity": "warning",
                "section": "Источники",
                "message": "Нет нормализованного evidence для выбранного периода.",
                "nextAction": "Выполнить read-only загрузку и повторить расчет.",
            }
        )
    recommendation = (
        "review_required"
        if coverage and any(item.get("status") == "confirmed" for item in controls)
        else "cannot_confirm"
    )
    payload = {
        "contractVersion": MONTH_CLOSE_CONTRACT_VERSION,
        "reportKind": "month_close_control",
        "meta": _meta(report, evidence),
        "sourceCoverage": coverage,
        "controls": controls,
        "osvSummary": osv_summary,
        "osvRows": osv_rows,
        "taxSummary": _safe_summary(
            evidence.get("taxSummary"), ("status", "accrued", "paid", "balance")
        ),
        "ensSummary": _safe_summary(
            evidence.get("ensSummary"), ("status", "balance", "asOfDate")
        ),
        "vatSummary": _safe_summary(
            evidence.get("vatSummary"),
            ("status", "outputVat", "inputVat", "payableVat", "sourceKind"),
        ),
        "bankSummary": _safe_summary(
            evidence.get("bankSummary"),
            ("status", "openingBalance", "inflow", "outflow", "closingBalance"),
        ),
        "manualOperationsSummary": _safe_summary(
            evidence.get("manualOperationsSummary"),
            ("status", "operationCount", "amount"),
        ),
        "confirmations": [],
        "issues": issues,
        "businessRecommendation": recommendation,
        "accountantApproval": None,
    }
    return MonthCloseControlPayload.model_validate(payload).model_dump(mode="json")


def build_tax_load_payload(
    report: Any,
    *,
    tax_profile: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence or {}
    profile = tax_profile or {}
    derived_numerator = fns_paid_taxes_numerator(evidence.get("taxRows"))
    numerator = _decimal_text(derived_numerator)
    income_evidence = evidence.get("incomeEvidence")
    denominator: str | None = None
    if isinstance(income_evidence, Mapping):
        income_status = str(income_evidence.get("status") or "").strip().lower()
        income_source = str(income_evidence.get("sourceKind") or "").strip().lower()
        if (
            income_status in CONFIRMED_EVIDENCE_STATUSES
            and income_source in OFFICIAL_INCOME_SOURCE_KINDS
        ):
            denominator = _decimal_text(income_evidence.get("value"))
    ratio = fns_tax_burden_ratio(numerator, denominator)
    # Управленческий показатель нагрузки для УСН: знаменатель — доход по УСН без
    # НДС из поступлений (для ИП, у которого нет отчета о финансовых результатах;
    # spec: Tax Methodology Boundary, решение от 21.07.2026). Официальный
    # fns_tax_burden_ratio при этом не подменяется.
    is_usn_income = _is_usn_income_tax_system(profile.get("taxSystem"))
    is_usn_income_expenses = _is_usn_income_expenses_tax_system(
        profile.get("taxSystem"),
        profile.get("taxObject"),
    )
    is_usn = is_usn_income or is_usn_income_expenses
    usn_income_value: str | None = None
    usn_bank_income_value: str | None = None
    usn_income_ratio: Decimal | None = None
    usn_income_evidence = evidence.get("usnIncomeEvidence")
    if is_usn and isinstance(usn_income_evidence, Mapping):
        usn_status = str(usn_income_evidence.get("status") or "").strip().lower()
        if usn_status in CONFIRMED_EVIDENCE_STATUSES:
            usn_bank_income_value = _decimal_text(
                usn_income_evidence.get("value")
            )
    if is_usn_income:
        usn_income_value = usn_bank_income_value
    if is_usn_income and usn_income_value is not None:
        usn_income_ratio = fns_tax_burden_ratio(numerator, usn_income_value)
    tax_rows = _safe_rows(
        evidence.get("taxRows"),
        (
            "taxCode",
            "taxName",
            "periodKind",
            "taxBase",
            "accrued",
            "paid",
            "balance",
            "dueDate",
            "valueStatus",
            "evidenceStatus",
            "sourceKind",
            "issueCode",
            "paymentKind",
            "includedInFnsTaxBurden",
            "exclusionReason",
        ),
    )
    usn_income_monthly = (
        _safe_rows(
            usn_income_evidence.get("monthlyValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(usn_income_evidence, Mapping)
        else []
    )
    usn_unclassified_income_monthly = (
        _safe_rows(
            usn_income_evidence.get("monthlyUnclassifiedValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(usn_income_evidence, Mapping)
        else []
    )
    usn_excluded_income_monthly = (
        _safe_rows(
            usn_income_evidence.get("monthlyExcludedValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(usn_income_evidence, Mapping)
        else []
    )
    usn_classification_status = (
        str(usn_income_evidence.get("classificationStatus") or "ready")
        if isinstance(usn_income_evidence, Mapping)
        else "source_gap"
    )
    usn_unclassified_income = (
        _decimal_text(usn_income_evidence.get("unclassifiedValue"))
        if isinstance(usn_income_evidence, Mapping)
        else None
    )
    usn_excluded_income = (
        _decimal_text(usn_income_evidence.get("excludedValue"))
        if isinstance(usn_income_evidence, Mapping)
        else None
    )
    usn_loan_receipts = (
        _decimal_text(usn_income_evidence.get("loanReceiptsValue"))
        if isinstance(usn_income_evidence, Mapping)
        else None
    )
    usn_loan_receipts_monthly = (
        _safe_rows(
            usn_income_evidence.get("monthlyLoanReceiptValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(usn_income_evidence, Mapping)
        else []
    )
    usn_marketplace_breakdown = []
    if is_usn and isinstance(usn_income_evidence, Mapping):
        for item in usn_income_evidence.get("marketplaceBreakdown") or []:
            if not isinstance(item, Mapping):
                continue
            usn_marketplace_breakdown.append(
                {
                    "category": item.get("category"),
                    "label": item.get("label"),
                    "valueYtd": _decimal_text(item.get("value")),
                    "rowCount": item.get("rowCount"),
                    "monthlyValues": _safe_rows(
                        item.get("monthlyValues"),
                        ("month", "value", "status", "rowCount"),
                    ),
                }
            )
    (
        usn_marketplace_income,
        usn_marketplace_income_monthly,
    ) = _marketplace_subtotal(usn_marketplace_breakdown)
    kudir_income_evidence = evidence.get("kudirIncomeEvidence")
    kudir_income_ytd = (
        _decimal_text(kudir_income_evidence.get("value"))
        if is_usn and isinstance(kudir_income_evidence, Mapping)
        else None
    )
    kudir_income_monthly = (
        _safe_rows(
            kudir_income_evidence.get("monthlyValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(kudir_income_evidence, Mapping)
        else []
    )
    kudir_expense_evidence = evidence.get("kudirExpenseEvidence")
    kudir_expense_ytd = (
        _decimal_text(kudir_expense_evidence.get("value"))
        if is_usn_income_expenses
        and isinstance(kudir_expense_evidence, Mapping)
        else None
    )
    kudir_expense_monthly = (
        _safe_rows(
            kudir_expense_evidence.get("monthlyValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn_income_expenses
        and isinstance(kudir_expense_evidence, Mapping)
        else []
    )
    usn_expense_breakdown = (
        _safe_usn_expense_breakdown(kudir_expense_evidence.get("breakdown"))
        if is_usn_income_expenses
        and isinstance(kudir_expense_evidence, Mapping)
        else []
    )
    usn_expense_classification_status = (
        str(
            kudir_expense_evidence.get("classificationStatus")
            or "source_gap"
        )
        if is_usn_income_expenses
        and isinstance(kudir_expense_evidence, Mapping)
        else None
    )
    usn_payment_evidence = evidence.get("usnTaxPaymentEvidence")
    usn_tax_payments_monthly = (
        _safe_rows(
            usn_payment_evidence.get("monthlyValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(usn_payment_evidence, Mapping)
        else []
    )
    usn_payroll_evidence = evidence.get("usnPayrollPaymentEvidence")
    usn_payroll_payments = (
        _decimal_text(usn_payroll_evidence.get("value"))
        if is_usn and isinstance(usn_payroll_evidence, Mapping)
        else None
    )
    usn_payroll_payments_monthly = (
        _safe_rows(
            usn_payroll_evidence.get("monthlyValues"),
            ("month", "value", "status", "rowCount"),
        )
        if is_usn and isinstance(usn_payroll_evidence, Mapping)
        else []
    )
    usn_payroll_classification_status = (
        str(usn_payroll_evidence.get("classificationStatus") or "source_gap")
        if is_usn and isinstance(usn_payroll_evidence, Mapping)
        else None
    )
    usn_tax_rows = [
        row
        for row in tax_rows
        if any(
            marker in str(row.get("taxName") or "").casefold()
            for marker in ("усн", "упрощ")
        )
    ]
    usn_paid_tax: Decimal | None = None
    if usn_tax_rows and all(
        str(row.get("evidenceStatus") or "").strip().lower()
        in CONFIRMED_EVIDENCE_STATUSES
        and _decimal(row.get("paid")) is not None
        for row in usn_tax_rows
    ):
        usn_paid_tax = sum(
            (_decimal(row.get("paid")) or Decimal("0") for row in usn_tax_rows),
            Decimal("0"),
        )
    usn_due_dates = {
        str(row.get("dueDate")) for row in usn_tax_rows if row.get("dueDate")
    }
    revenue_tax_rate = _decimal(profile.get("revenueTaxRate"))
    profile_tax_rate = _decimal(profile.get("taxRate"))
    usn_tax_base: Decimal | None = None
    usn_regular_tax: Decimal | None = None
    usn_minimum_tax_reference: Decimal | None = None
    usn_minimum_tax_application_status: str | None = None
    monthly_tax_base: list[dict[str, Any]] = []
    monthly_regular_tax: list[dict[str, Any]] = []
    monthly_minimum_tax_reference: list[dict[str, Any]] = []
    monthly_calculated_tax: list[dict[str, Any]] = []
    usn_calculated_tax: Decimal | None = None
    if (
        is_usn_income
        and revenue_tax_rate is not None
        and Decimal("0") < revenue_tax_rate <= Decimal("1")
        and (usn_income_decimal := _decimal(usn_income_value)) is not None
    ):
        usn_calculated_tax = (usn_income_decimal * revenue_tax_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    elif is_usn_income_expenses:
        income_expenses_metrics = _usn_income_expenses_metrics(
            period_end=report.period_end,
            income_ytd=kudir_income_ytd,
            expense_ytd=kudir_expense_ytd,
            income_monthly=kudir_income_monthly,
            expense_monthly=kudir_expense_monthly,
            income_status=(
                kudir_income_evidence.get("status")
                if isinstance(kudir_income_evidence, Mapping)
                else None
            ),
            expense_status=(
                kudir_expense_evidence.get("status")
                if isinstance(kudir_expense_evidence, Mapping)
                else None
            ),
            tax_rate=profile_tax_rate,
        )
        usn_tax_base = _decimal(income_expenses_metrics["taxBaseYtd"])
        usn_regular_tax = _decimal(
            income_expenses_metrics["regularTaxYtd"]
        )
        usn_minimum_tax_reference = _decimal(
            income_expenses_metrics["minimumTaxReferenceYtd"]
        )
        usn_minimum_tax_application_status = str(
            income_expenses_metrics["minimumTaxApplicationStatus"]
        )
        usn_calculated_tax = _decimal(
            income_expenses_metrics["calculatedTaxYtd"]
        )
        monthly_tax_base = income_expenses_metrics["monthlyTaxBase"]
        monthly_regular_tax = income_expenses_metrics["monthlyRegularTax"]
        monthly_minimum_tax_reference = income_expenses_metrics[
            "monthlyMinimumTaxReference"
        ]
        monthly_calculated_tax = income_expenses_metrics[
            "monthlyCalculatedTax"
        ]
    usn_tax_payable = (
        (usn_calculated_tax - usn_paid_tax).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if usn_calculated_tax is not None and usn_paid_tax is not None
        else None
    )
    reconciliation_income = _decimal(usn_bank_income_value)
    reconciliation_kudir = _decimal(kudir_income_ytd)
    usn_reconciliation_delta = (
        (reconciliation_income - reconciliation_kudir).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if reconciliation_income is not None and reconciliation_kudir is not None
        else None
    )
    coverage = _safe_rows(
        evidence.get("sourceCoverage"),
        ("sourceKind", "periodStart", "periodEnd", "status", "snapshotId"),
    )
    rwb_vat_reconciliation = _safe_rwb_vat_reconciliation(
        evidence.get("rwbVatReconciliation"),
        vat_deduction_mode=profile.get("vatDeductionMode"),
    )
    issues = _safe_rows(
        evidence.get("issues"),
        ("code", "severity", "section", "message", "nextAction"),
    )
    if ratio is None:
        issues.append(
            {
                "code": "fns_ratio_source_gap",
                "severity": "warning",
                "section": "Налоговая нагрузка",
                "message": "Недостаточно подтвержденных данных для коэффициента ФНС.",
                "nextAction": "Подтвердить уплаченные налоги и доходный знаменатель.",
            }
        )
    if (
        rwb_vat_reconciliation["applicability"] == "allowed"
        and rwb_vat_reconciliation["status"]
        in {"mismatch", "partial_source", "missing", "source_gap"}
    ):
        issues.append(
            {
                "code": "rwb_vat_reconciliation_review_required",
                "severity": "warning",
                "section": "НДС РВБ",
                "message": (
                    "Входящий НДС по услугам РВБ не подтверждён книгой покупок."
                ),
                "nextAction": (
                    "Сверить УПД услуг РВБ и записи книги покупок за период."
                ),
            }
        )
    payment_schedule = [
        {
            "taxCode": row.get("taxCode"),
            "taxName": row.get("taxName"),
            "dueDate": row.get("dueDate"),
            "amount": row.get("balance"),
            "confirmationStatus": "informational",
        }
        for row in tax_rows
        if row.get("dueDate")
    ]
    if not is_usn:
        usn_detail_status = "not_applicable"
    elif usn_calculated_tax is None or usn_paid_tax is None:
        usn_detail_status = "source_gap"
    elif (
        is_usn_income_expenses
        and usn_expense_classification_status == "review_required"
    ):
        usn_detail_status = "review_required"
    elif is_usn_income_expenses:
        usn_detail_status = (
            "ready"
            if usn_expense_classification_status == "ready"
            else "source_gap"
        )
    elif (
        usn_classification_status == "review_required"
        or usn_payroll_classification_status == "review_required"
    ):
        usn_detail_status = "review_required"
    elif (
        usn_classification_status == "ready"
        and usn_payroll_classification_status == "ready"
    ):
        usn_detail_status = "ready"
    else:
        usn_detail_status = "source_gap"
    payload = {
        "contractVersion": TAX_LOAD_CONTRACT_VERSION,
        "reportKind": "tax_load",
        "meta": _meta(report, evidence),
        "ytdStart": report.period_start.replace(month=1, day=1).isoformat(),
        "ytdEnd": report.period_end.isoformat(),
        "taxProfile": {
            "taxSystem": profile.get("taxSystem"),
            "taxObject": profile.get("taxObject"),
            "taxRate": _decimal_text(profile.get("taxRate")),
            "elevatedTaxRate": _decimal_text(profile.get("elevatedTaxRate")),
            "profileStatus": profile.get("profileStatus", "missing"),
            "vatRate": _decimal_text(profile.get("vatRate")),
            "vatMode": profile.get("vatMode"),
            "vatDeductionMode": profile.get("vatDeductionMode"),
            "revenueTaxRate": _decimal_text(profile.get("revenueTaxRate")),
            "validFrom": profile.get("validFrom"),
            "validTo": profile.get("validTo"),
            "sourceKind": profile.get("sourceKind"),
            "sourceRefreshRunId": profile.get("sourceRefreshRunId"),
            "sourceSnapshotHash": profile.get("sourceSnapshotHash"),
            "profileId": profile.get("profileId"),
        },
        "sourceCoverage": coverage,
        "taxRows": tax_rows,
        "vatSummary": _safe_summary(
            evidence.get("vatSummary"),
            (
                "status",
                "periodStart",
                "periodEnd",
                "salesBookStatus",
                "purchaseBookStatus",
                "outputVat",
                "inputVat",
                "payableVat",
                "salesBookRows",
                "purchaseBookRows",
                "ytdOutputVat",
                "ytdInputVat",
                "vatDifference",
                "sourceKind",
            ),
        ),
        "vatBooks": _safe_vat_books(evidence.get("vatBooks")),
        "rwbVatReconciliation": rwb_vat_reconciliation,
        "ensSummary": _safe_summary(
            evidence.get("ensSummary"), ("status", "balance", "asOfDate")
        ),
        "paymentSchedule": payment_schedule,
        "usnDetail": (
            {
                "status": usn_detail_status,
                "calculationMode": (
                    "income_expenses"
                    if is_usn_income_expenses
                    else "income"
                ),
                "methodologyVersion": (
                    USN_INCOME_EXPENSES_METHODOLOGY_VERSION
                    if is_usn_income_expenses
                    else None
                ),
                "classificationStatus": usn_classification_status,
                "expenseClassificationStatus": (
                    usn_expense_classification_status
                ),
                "payrollClassificationStatus": (
                    usn_payroll_classification_status
                ),
                "sourceKind": (
                    "onec_kudir"
                    if is_usn_income_expenses
                    else (
                        usn_income_evidence.get("sourceKind")
                        if isinstance(usn_income_evidence, Mapping)
                        else None
                    )
                ),
                "revenueTaxRate": _decimal_text(revenue_tax_rate),
                "taxRate": _decimal_text(profile_tax_rate),
                "minimumTaxRate": (
                    "0.01" if is_usn_income_expenses else None
                ),
                "incomeYtd": (
                    kudir_income_ytd
                    if is_usn_income_expenses
                    else usn_income_value
                ),
                "cashIncomeYtd": usn_bank_income_value,
                "unclassifiedIncomeYtd": usn_unclassified_income,
                "excludedIncomeYtd": usn_excluded_income,
                "loanReceiptsYtd": usn_loan_receipts,
                "payrollPaymentsYtd": usn_payroll_payments,
                "kudirIncomeYtd": kudir_income_ytd,
                "kudirExpenseYtd": kudir_expense_ytd,
                "expenseBreakdown": usn_expense_breakdown,
                "reconciliationDelta": _decimal_text(usn_reconciliation_delta),
                "taxBaseYtd": _decimal_text(usn_tax_base),
                "regularTaxYtd": _decimal_text(usn_regular_tax),
                "minimumTaxReferenceYtd": _decimal_text(
                    usn_minimum_tax_reference
                ),
                "minimumTaxApplicationStatus": (
                    usn_minimum_tax_application_status
                ),
                "calculatedTaxYtd": _decimal_text(usn_calculated_tax),
                "paidTaxYtd": _decimal_text(usn_paid_tax),
                "taxPayable": _decimal_text(usn_tax_payable),
                "dueDate": (
                    next(iter(usn_due_dates)) if len(usn_due_dates) == 1 else None
                ),
                "monthlyIncome": usn_income_monthly,
                "monthlyUnclassifiedIncome": usn_unclassified_income_monthly,
                "monthlyExcludedIncome": usn_excluded_income_monthly,
                "monthlyLoanReceipts": usn_loan_receipts_monthly,
                "monthlyPayrollPayments": usn_payroll_payments_monthly,
                "marketplaceBreakdownStatus": (
                    usn_income_evidence.get("marketplaceBreakdownStatus")
                    or "source_gap"
                    if isinstance(usn_income_evidence, Mapping)
                    else "source_gap"
                ),
                "marketplaceIncomeBreakdown": usn_marketplace_breakdown,
                "marketplaceIncomeYtd": usn_marketplace_income,
                "monthlyMarketplaceIncome": usn_marketplace_income_monthly,
                "monthlyKudirIncome": kudir_income_monthly,
                "monthlyKudirExpense": kudir_expense_monthly,
                "monthlyTaxBase": monthly_tax_base,
                "monthlyRegularTax": monthly_regular_tax,
                "monthlyMinimumTaxReference": (
                    monthly_minimum_tax_reference
                ),
                "monthlyCalculatedTax": monthly_calculated_tax,
                "monthlyTaxPayments": usn_tax_payments_monthly,
            }
            if is_usn
            else {"status": "not_applicable"}
        ),
        "taxLoadSummary": {
            "metricKind": "fns_tax_risk",
            "numeratorKind": (
                "paid_taxes_excluding_agents_and_insurance_contributions"
            ),
            "numeratorValue": numerator,
            "denominatorKind": (
                "financial_result_income_excluding_participation_income"
            ),
            "denominatorValue": denominator,
            "fnsTaxBurdenRatio": format(ratio, "f") if ratio is not None else None,
            "calculationPeriodKind": "preliminary_ytd",
            "methodologyVersion": FNS_TAX_BURDEN_METHODOLOGY_VERSION,
            "methodologyStatus": "ready" if ratio is not None else "source_gap",
            "comparisonStatus": "pending_methodology_confirmation",
            "benchmarkYear": None,
            "benchmarkValue": None,
            "usnIncomeDenominatorKind": "usn_income_receipts_excluding_vat",
            "usnIncomeValue": usn_income_value,
            "usnIncomeTaxBurden": (
                format(usn_income_ratio, "f")
                if usn_income_ratio is not None
                else None
            ),
            "usnIncomeStatus": (
                "management_reference"
                if usn_income_ratio is not None
                else ("source_gap" if is_usn_income else None)
            ),
        },
        "issues": issues,
        "businessStatus": (
            "accountant_review_required" if ratio is not None else "preliminary"
        ),
        "accountantApproval": None,
    }
    return TaxLoadPayload.model_validate(payload).model_dump(mode="json")


def _usn_income_expenses_metrics(
    *,
    period_end: Any,
    income_ytd: object,
    expense_ytd: object,
    income_monthly: list[dict[str, Any]],
    expense_monthly: list[dict[str, Any]],
    income_status: object,
    expense_status: object,
    tax_rate: Decimal | None,
) -> dict[str, Any]:
    complete_statuses = {
        "loaded",
        "ready",
        "complete",
        "confirmed",
        "empty_expected",
    }
    sources_complete = (
        str(income_status or "").strip().lower() in complete_statuses
        and str(expense_status or "").strip().lower() in complete_statuses
    )
    income_total = _decimal(income_ytd) if sources_complete else None
    expense_total = _decimal(expense_ytd) if sources_complete else None
    valid_rate = (
        tax_rate
        if tax_rate is not None and Decimal("0") < tax_rate <= Decimal("100")
        else None
    )
    tax_base_ytd = (
        max(income_total - expense_total, Decimal("0"))
        if income_total is not None and expense_total is not None
        else None
    )
    regular_tax_ytd = (
        (tax_base_ytd * valid_rate / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if tax_base_ytd is not None and valid_rate is not None
        else None
    )
    minimum_tax_ytd = (
        (income_total * Decimal("0.01")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if income_total is not None
        else None
    )
    annual = getattr(period_end, "month", None) == 12
    if regular_tax_ytd is None or minimum_tax_ytd is None:
        calculated_tax_ytd = None
        minimum_application_status = "source_gap"
    elif annual and minimum_tax_ytd > regular_tax_ytd:
        calculated_tax_ytd = minimum_tax_ytd
        minimum_application_status = "minimum_tax_applied"
    elif annual:
        calculated_tax_ytd = regular_tax_ytd
        minimum_application_status = "regular_tax_applied"
    else:
        calculated_tax_ytd = regular_tax_ytd
        minimum_application_status = "reference_only"

    year = getattr(period_end, "year", None)
    end_month = int(getattr(period_end, "month", 0) or 0)

    def monthly_map(rows: list[dict[str, Any]]) -> dict[int, Decimal | None]:
        result: dict[int, Decimal | None] = {}
        for row in rows:
            month_text = str(row.get("month") or "")
            if year is None or not month_text.startswith(f"{year:04d}-"):
                continue
            try:
                month_number = int(month_text[5:7])
            except (TypeError, ValueError):
                continue
            if 1 <= month_number <= 12:
                result[month_number] = _decimal(row.get("value"))
        return result

    income_by_month = monthly_map(income_monthly)
    expense_by_month = monthly_map(expense_monthly)
    monthly_tax_base: list[dict[str, Any]] = []
    monthly_regular_tax: list[dict[str, Any]] = []
    monthly_minimum_tax: list[dict[str, Any]] = []
    monthly_calculated_tax: list[dict[str, Any]] = []
    cumulative_income = Decimal("0")
    cumulative_expense = Decimal("0")
    cumulative_complete = sources_complete
    for month_number in range(1, end_month + 1):
        income_value = (
            income_by_month.get(month_number, Decimal("0"))
            if sources_complete
            else None
        )
        expense_value = (
            expense_by_month.get(month_number, Decimal("0"))
            if sources_complete
            else None
        )
        if income_value is None or expense_value is None:
            cumulative_complete = False
            monthly_base = None
        else:
            cumulative_income += income_value
            cumulative_expense += expense_value
            monthly_base = max(income_value - expense_value, Decimal("0"))
        cumulative_base = (
            max(cumulative_income - cumulative_expense, Decimal("0"))
            if cumulative_complete
            else None
        )
        monthly_regular = (
            (monthly_base * valid_rate / Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if monthly_base is not None and valid_rate is not None
            else None
        )
        cumulative_regular = (
            (cumulative_base * valid_rate / Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if cumulative_base is not None and valid_rate is not None
            else None
        )
        monthly_minimum = (
            (income_value * Decimal("0.01")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if income_value is not None
            else None
        )
        cumulative_minimum = (
            (cumulative_income * Decimal("0.01")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if cumulative_complete
            else None
        )
        applicable_ytd = (
            max(cumulative_regular, cumulative_minimum)
            if month_number == 12
            and cumulative_regular is not None
            and cumulative_minimum is not None
            else cumulative_regular
        )
        month_key = f"{year:04d}-{month_number:02d}"
        value_status = "loaded" if cumulative_complete else "source_gap"
        monthly_tax_base.append(
            {
                "month": month_key,
                "value": _decimal_text(monthly_base),
                "ytdValue": _decimal_text(cumulative_base),
                "status": value_status,
            }
        )
        monthly_regular_tax.append(
            {
                "month": month_key,
                "value": _decimal_text(monthly_regular),
                "ytdValue": _decimal_text(cumulative_regular),
                "status": (
                    value_status if valid_rate is not None else "source_gap"
                ),
            }
        )
        monthly_minimum_tax.append(
            {
                "month": month_key,
                "value": _decimal_text(monthly_minimum),
                "ytdValue": _decimal_text(cumulative_minimum),
                "status": value_status,
            }
        )
        monthly_calculated_tax.append(
            {
                "month": month_key,
                "value": _decimal_text(monthly_regular),
                "ytdValue": _decimal_text(applicable_ytd),
                "status": (
                    value_status if valid_rate is not None else "source_gap"
                ),
            }
        )
    return {
        "taxBaseYtd": _decimal_text(tax_base_ytd),
        "regularTaxYtd": _decimal_text(regular_tax_ytd),
        "minimumTaxReferenceYtd": _decimal_text(minimum_tax_ytd),
        "minimumTaxApplicationStatus": minimum_application_status,
        "calculatedTaxYtd": _decimal_text(calculated_tax_ytd),
        "monthlyTaxBase": monthly_tax_base,
        "monthlyRegularTax": monthly_regular_tax,
        "monthlyMinimumTaxReference": monthly_minimum_tax,
        "monthlyCalculatedTax": monthly_calculated_tax,
    }


def _marketplace_subtotal(
    breakdown: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    categories = {
        str(item.get("category") or ""): item
        for item in breakdown
    }
    components = [categories.get("ozon"), categories.get("wildberries")]
    if not all(isinstance(item, Mapping) for item in components):
        return None, []
    ytd_values = [
        _decimal(item.get("valueYtd"))
        for item in components
        if isinstance(item, Mapping)
    ]
    ytd_value = (
        _decimal_text(
            sum(
                (value for value in ytd_values if value is not None),
                Decimal("0"),
            )
        )
        if len(ytd_values) == 2 and all(value is not None for value in ytd_values)
        else None
    )
    component_months = [
        {
            str(row.get("month") or ""): row
            for row in item.get("monthlyValues") or []
            if isinstance(row, Mapping)
        }
        for item in components
        if isinstance(item, Mapping)
    ]
    monthly_values = []
    month_keys = sorted(
        set().union(*(month_rows.keys() for month_rows in component_months))
    )
    for month in month_keys:
        rows = [month_rows.get(month) for month_rows in component_months]
        values = [
            _decimal(row.get("value"))
            for row in rows
            if isinstance(row, Mapping)
        ]
        value = (
            sum(
                (item for item in values if item is not None),
                Decimal("0"),
            )
            if len(values) == 2 and all(item is not None for item in values)
            else None
        )
        monthly_values.append(
            {
                "month": month,
                "value": _decimal_text(value),
                "status": next(
                    (
                        row.get("status")
                        for row in rows
                        if isinstance(row, Mapping) and row.get("status")
                    ),
                    "source_gap",
                ),
                "rowCount": sum(
                    int(row.get("rowCount") or 0)
                    for row in rows
                    if isinstance(row, Mapping)
                ),
            }
        )
    return ytd_value, monthly_values
