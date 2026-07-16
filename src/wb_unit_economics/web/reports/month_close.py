from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

OSV_SOURCE_BALANCE_AND_TURNOVERS = "balance_and_turnovers"
OSV_SOURCE_RECORD_TYPE_FALLBACK = "record_type_fallback"
OSV_AMOUNT_FIELDS = (
    "openingDebit",
    "openingCredit",
    "debitTurnover",
    "creditTurnover",
    "closingDebit",
    "closingCredit",
)
OSV_ROW_FIELDS = ("accountCode", "accountName", *OSV_AMOUNT_FIELDS)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _candidate(value: object) -> tuple[str, list[Mapping[str, Any]]] | None:
    if not isinstance(value, Mapping):
        return None
    rows = value.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        return None
    status = str(value.get("status") or "").strip().lower()
    accepted_statuses = {"loaded", "ready", "complete", "partial", "partial_source"}
    if status not in accepted_statuses:
        return None
    if not rows and status not in {"loaded", "ready", "complete"}:
        return None
    return status or "loaded", rows


def _normalized_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows[:10000]:
        account_code = str(row.get("accountCode") or "").strip()
        if not account_code:
            continue
        item = grouped.setdefault(
            account_code,
            {
                "accountCode": account_code,
                "accountName": str(row.get("accountName") or "").strip(),
                **{field: None for field in OSV_AMOUNT_FIELDS},
            },
        )
        if not item["accountName"]:
            item["accountName"] = str(row.get("accountName") or "").strip()
        for field in OSV_AMOUNT_FIELDS:
            value = _decimal(row.get(field))
            existing = _decimal(item.get(field))
            if value is not None:
                item[field] = _decimal_text((existing or Decimal("0")) + value)
    return sorted(grouped.values(), key=lambda item: str(item["accountCode"]))


def _reconcile_rows(
    rows: list[dict[str, Any]], reference_rows: object
) -> tuple[list[dict[str, Any]], str, int | None]:
    if not isinstance(reference_rows, list):
        return (
            [{**row, "reconciliationStatus": "not_checked"} for row in rows],
            "not_checked",
            None,
        )
    normalized_reference = _normalized_rows(
        [row for row in reference_rows if isinstance(row, Mapping)]
    )
    reference_by_account = {
        str(row["accountCode"]): row for row in normalized_reference
    }
    actual_by_account = {str(row["accountCode"]): row for row in rows}
    mismatches = 0
    reconciled: list[dict[str, Any]] = []
    for row in rows:
        reference = reference_by_account.get(str(row["accountCode"]))
        item = dict(row)
        row_missing = reference is None
        row_mismatch = False
        for field in OSV_AMOUNT_FIELDS:
            actual = _decimal(row.get(field))
            expected = _decimal(reference.get(field)) if reference else None
            delta_field = f"{field}Delta"
            if actual is None or expected is None:
                item[delta_field] = None
                row_missing = True
                continue
            delta = actual - expected
            item[delta_field] = _decimal_text(delta)
            if delta != 0:
                row_mismatch = True
        if row_mismatch:
            mismatches += 1
            item["reconciliationStatus"] = "warning"
        elif row_missing:
            item["reconciliationStatus"] = "missing"
        else:
            item["reconciliationStatus"] = "matched"
        reconciled.append(item)
    for account_code, reference in reference_by_account.items():
        if account_code in actual_by_account:
            continue
        item = {
            "accountCode": account_code,
            "accountName": reference.get("accountName") or "",
            **{field: None for field in OSV_AMOUNT_FIELDS},
            **{f"{field}Delta": None for field in OSV_AMOUNT_FIELDS},
            "reconciliationStatus": "missing",
        }
        reconciled.append(item)
    reconciled.sort(key=lambda item: str(item["accountCode"]))
    if mismatches:
        status = "warning"
    elif any(item["reconciliationStatus"] == "missing" for item in reconciled):
        status = "partial"
    else:
        status = "matched"
    return reconciled, status, mismatches


def normalize_month_close_osv(
    evidence: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Choose a normalized OSV source and reconcile it without raw 1C rows.

    BalanceAndTurnovers is preferred. RecordType is used only when the preferred
    normalized candidate is unavailable. Accounts are compared independently,
    so parent and subaccount rows are never summed together.
    """

    selected = _candidate(evidence.get("osvBalanceAndTurnovers"))
    source_kind = OSV_SOURCE_BALANCE_AND_TURNOVERS
    if selected is None:
        selected = _candidate(evidence.get("osvRecordTypeFallback"))
        source_kind = OSV_SOURCE_RECORD_TYPE_FALLBACK
    issues: list[dict[str, Any]] = []
    if selected is None:
        issues.append(
            {
                "code": "osv_source_missing",
                "severity": "warning",
                "section": "ОСВ",
                "message": "Нет нормализованного источника ОСВ за выбранный период.",
                "nextAction": "Проверить BalanceAndTurnovers и fallback RecordType.",
            }
        )
        return (
            {
                "sourceKind": None,
                "sourceStatus": "missing",
                "reconciliationStatus": "not_checked",
                "mismatchCount": None,
            },
            [],
            issues,
        )
    source_status, candidate_rows = selected
    rows = _normalized_rows(candidate_rows)
    rows, reconciliation_status, mismatch_count = _reconcile_rows(
        rows, evidence.get("osvReferenceRows")
    )
    if reconciliation_status == "warning":
        issues.append(
            {
                "code": "osv_nonzero_delta",
                "severity": "warning",
                "section": "ОСВ",
                "message": (
                    f"ОСВ содержит ненулевые дельты по {mismatch_count or 0} счетам."
                ),
                "nextAction": "Сверить одинаковый период, организацию и счет.",
            }
        )
    if any(item.get("reconciliationStatus") == "missing" for item in rows):
        issues.append(
            {
                "code": "osv_reconciliation_missing_values",
                "severity": "warning",
                "section": "ОСВ",
                "message": "Часть значений ОСВ отсутствует; дельта оставлена null.",
                "nextAction": "Дозагрузить отсутствующие остатки и обороты.",
            }
        )
    return (
        {
            "sourceKind": source_kind,
            "sourceStatus": source_status,
            "reconciliationStatus": reconciliation_status,
            "mismatchCount": mismatch_count,
        },
        rows,
        issues,
    )
