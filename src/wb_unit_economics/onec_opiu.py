from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from wb_unit_economics.onec_odata import extract_odata_rows

ZERO = Decimal("0")

# Current pilot mapping from 1C:UNF management accounting account keys to the
# client-facing OPIU rows visible in the 1C report.
REVENUE_ACCOUNT_KEY = "ca495cfb-658a-11ec-be7c-8e45118e8d46"
COGS_ACCOUNT_KEY = "ca495cfc-658a-11ec-be7c-8e45118e8d46"
VAT_ACCOUNT_KEY = "ec4a083e-4c2d-11ee-8dc0-005056ae0f31"
RWB_OPIU_STRUCTURAL_UNIT_KEY = "9fb8122b-658a-11ec-be7c-8e45118e8d46"

RWB_ACCOUNT_KEYS = {
    "commission": "ed809e63-2c0c-11f1-80e1-000c29cb5adf",
    "logistics": "77dcb829-46ca-11f1-80e1-000c29cb5adf",
    "promotion": "35cd6072-46c5-11f1-80e1-000c29cb5adf",
    "utilization": "26beead7-46cc-11f1-80e1-000c29cb5adf",
    "pvz": "bb46fc26-46c5-11f1-80e1-000c29cb5adf",
    "fines": "561bd92f-46ca-11f1-80e1-000c29cb5adf",
    "subscription": "c66d8f42-46cc-11f1-80e1-000c29cb5adf",
    "acquiring": "44c6bbce-46ce-11f1-80e1-000c29cb5adf",
}


@dataclass(frozen=True)
class OnecOpiuConfig:
    revenue_account_key: str = REVENUE_ACCOUNT_KEY
    cogs_account_key: str = COGS_ACCOUNT_KEY
    vat_account_key: str = VAT_ACCOUNT_KEY
    rwb_structural_unit_key: str = RWB_OPIU_STRUCTURAL_UNIT_KEY
    rwb_account_keys: dict[str, str] | None = None
    status: str = "pilot_defaults"
    source_label: str = "pilot defaults"

    @property
    def rwb_accounts(self) -> dict[str, str]:
        return self.rwb_account_keys or RWB_ACCOUNT_KEYS


@dataclass(frozen=True)
class OnecOpiuSummary:
    source_label: str
    source_row_count: int
    values: dict[str, Decimal]
    monthly_values: dict[str, dict[str, Decimal]]
    config_status: str = "pilot_defaults"
    config_source_label: str = "pilot defaults"

    def value(self, key: str) -> Decimal | None:
        return self.values.get(key)


def load_onec_opiu_summary(
    path: Path | None,
    *,
    period_start: date,
    period_end: date,
    config_path: Path | None = None,
) -> OnecOpiuSummary | None:
    if path is None:
        return None
    config = load_onec_opiu_config(config_path)
    payload_path = path / "income_expense_register.raw.json"
    if not payload_path.exists():
        return None
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    rows = _flatten_income_expense_rows(extract_odata_rows(payload))
    period_rows = [
        row
        for row in rows
        if period_start <= _row_period(row) <= period_end
        and row.get("Active", True) is True
    ]
    by_account: dict[str, dict[str, Decimal]] = {}
    monthly_values: dict[str, dict[str, Decimal]] = {}
    for row in period_rows:
        account_key = str(row.get("СчетУчета_Key") or "")
        month_key = _row_period(row).strftime("%Y-%m")
        month = monthly_values.setdefault(
            month_key,
            {"revenue": ZERO, "cogs": ZERO, "rwb_total": ZERO},
        )
        bucket = by_account.setdefault(account_key, {"income": ZERO, "expense": ZERO})
        income = _decimal(row.get("СуммаДоходов"))
        expense = _decimal(row.get("СуммаРасходов"))
        bucket["income"] += income
        bucket["expense"] += expense
        if account_key == config.revenue_account_key:
            month["revenue"] += income
        elif account_key == config.cogs_account_key:
            month["cogs"] += expense
        elif account_key in config.rwb_accounts.values() and _is_opiu_rwb_row(
            row,
            config,
        ):
            month["rwb_total"] += expense

    values: dict[str, Decimal] = {
        "revenue": _income(by_account, config.revenue_account_key),
        "cogs": _expense(by_account, config.cogs_account_key),
        "vat": _expense(by_account, config.vat_account_key),
        "rwb_total": _filtered_expense(
            period_rows,
            set(config.rwb_accounts.values()),
            config,
        ),
        "net_profit": _income(by_account, config.revenue_account_key)
        - sum((bucket["expense"] for bucket in by_account.values()), ZERO),
    }
    for name, account_key in config.rwb_accounts.items():
        values[f"rwb_{name}"] = _filtered_expense(period_rows, {account_key}, config)
    values["revenue_without_vat"] = values["revenue"] - values["vat"]

    return OnecOpiuSummary(
        source_label=f"income_expense_register: {path.name}",
        source_row_count=len(period_rows),
        values=values,
        monthly_values=monthly_values,
        config_status=config.status,
        config_source_label=config.source_label,
    )


def load_onec_opiu_config(config_path: Path | None = None) -> OnecOpiuConfig:
    if config_path is None:
        default_path = Path("config/onec_opiu_accounts.json")
        if not default_path.exists():
            return OnecOpiuConfig()
        config_path = default_path
    if not config_path.exists():
        return OnecOpiuConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    rwb_accounts = payload.get("rwb_account_keys")
    if not isinstance(rwb_accounts, dict):
        rwb_accounts = RWB_ACCOUNT_KEYS
    else:
        merged = dict(RWB_ACCOUNT_KEYS)
        merged.update({str(key): str(value) for key, value in rwb_accounts.items()})
        rwb_accounts = merged
    return OnecOpiuConfig(
        revenue_account_key=str(
            payload.get("revenue_account_key") or REVENUE_ACCOUNT_KEY
        ),
        cogs_account_key=str(payload.get("cogs_account_key") or COGS_ACCOUNT_KEY),
        vat_account_key=str(payload.get("vat_account_key") or VAT_ACCOUNT_KEY),
        rwb_structural_unit_key=str(
            payload.get("rwb_structural_unit_key") or RWB_OPIU_STRUCTURAL_UNIT_KEY
        ),
        rwb_account_keys=rwb_accounts,
        status="configured",
        source_label=str(config_path),
    )


def _flatten_income_expense_rows(rows: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for document in rows:
        if not isinstance(document, dict):
            continue
        record_set = document.get("RecordSet")
        if isinstance(record_set, list):
            result.extend(row for row in record_set if isinstance(row, dict))
    return result


def _row_period(row: dict[str, Any]) -> date:
    value = str(row.get("Period") or "")[:10]
    return datetime.fromisoformat(value).date()


def _decimal(value: object) -> Decimal:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


def _income(
    by_account: dict[str, dict[str, Decimal]],
    account_key: str,
) -> Decimal:
    return by_account.get(account_key, {}).get("income", ZERO)


def _expense(
    by_account: dict[str, dict[str, Decimal]],
    account_key: str,
) -> Decimal:
    return by_account.get(account_key, {}).get("expense", ZERO)


def _filtered_expense(
    rows: list[dict[str, Any]],
    account_keys: set[str],
    config: OnecOpiuConfig,
) -> Decimal:
    return sum(
        (
            _decimal(row.get("СуммаРасходов"))
            for row in rows
            if str(row.get("СчетУчета_Key") or "") in account_keys
            and _is_opiu_rwb_row(row, config)
        ),
        ZERO,
    )


def _is_opiu_rwb_row(row: dict[str, Any], config: OnecOpiuConfig) -> bool:
    return (
        str(row.get("СтруктурнаяЕдиница_Key") or "")
        == config.rwb_structural_unit_key
    )
