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
TAX_LOAD_CONTRACT_VERSION = "tax-load-report-v2"
FNS_TAX_BURDEN_METHODOLOGY_VERSION = "fns-tax-burden-v1-2026-07-14"
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
    coverage = _safe_rows(
        evidence.get("sourceCoverage"),
        ("sourceKind", "periodStart", "periodEnd", "status", "snapshotId"),
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
    payload = {
        "contractVersion": TAX_LOAD_CONTRACT_VERSION,
        "reportKind": "tax_load",
        "meta": _meta(report, evidence),
        "ytdStart": report.period_start.replace(month=1, day=1).isoformat(),
        "ytdEnd": report.period_end.isoformat(),
        "taxProfile": {
            "taxSystem": profile.get("taxSystem"),
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
            ("status", "outputVat", "inputVat", "payableVat", "sourceKind"),
        ),
        "ensSummary": _safe_summary(
            evidence.get("ensSummary"), ("status", "balance", "asOfDate")
        ),
        "paymentSchedule": payment_schedule,
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
        },
        "issues": issues,
        "businessStatus": (
            "accountant_review_required" if ratio is not None else "preliminary"
        ),
        "accountantApproval": None,
    }
    return TaxLoadPayload.model_validate(payload).model_dump(mode="json")
