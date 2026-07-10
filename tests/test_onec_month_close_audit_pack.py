from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts.build_onec_month_close_audit_pack import (
    BALANCE_AND_TURNOVERS_SOURCE,
    RECORDTYPE_SOURCE,
    VirtualProbe,
    _accounting_records_error,
    _balance_rows_from_balance_and_turnovers,
    _choose_osv_source,
    _fetch_accounting_records,
    _load_settings,
)
from wb_unit_economics.onec_odata import (
    BASE_URL_KEYS,
    PASSWORD_KEYS,
    USERNAME_KEYS,
    OnecODataConfigError,
)


def test_choose_osv_source_prefers_balance_and_turnovers() -> None:
    assert (
        _choose_osv_source(
            [
                VirtualProbe(name="BalanceAndTurnovers", ok=True, row_count=1),
                VirtualProbe(name="Turnovers", ok=False, status_code=404),
            ]
        )
        == BALANCE_AND_TURNOVERS_SOURCE.source_id
    )


def test_choose_osv_source_falls_back_to_recordtype() -> None:
    assert (
        _choose_osv_source(
            [
                VirtualProbe(name="BalanceAndTurnovers", ok=False, status_code=404),
                VirtualProbe(name="Turnovers", ok=True, row_count=1),
            ]
        )
        == RECORDTYPE_SOURCE.source_id
    )


def test_audit_pack_uses_environment_by_default_not_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "ONEC_ODATA_BASE_URL=https://onec.example/odata/standard.odata",
                "ONEC_ODATA_USERNAME=readonly",
            ]
        ),
        encoding="utf-8",
    )
    for key in [*BASE_URL_KEYS, *USERNAME_KEYS, *PASSWORD_KEYS]:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(OnecODataConfigError) as exc_info:
        _load_settings(None)

    message = str(exc_info.value)
    assert "ONEC_ODATA_BASE_URL" in message
    assert "ONEC_ODATA_USERNAME" in message
    assert "ONEC_ODATA_PASSWORD" in message


def test_balance_and_turnovers_rows_are_normalized_for_workbook() -> None:
    rows = [
        {
            "Account_Key": "account-68-90",
            "СуммаOpeningBalanceDt": 10,
            "СуммаOpeningBalanceCt": 2,
            "СуммаTurnoverDt": 30,
            "СуммаTurnoverCt": 20,
            "СуммаClosingBalanceDt": 18,
            "СуммаClosingBalanceCt": 0,
        }
    ]
    account_lookup = {
        "account-68-90": {
            "Code": "68.90",
            "Description": "Единый налоговый счет",
        }
    }

    result = _balance_rows_from_balance_and_turnovers(rows, account_lookup)

    assert result == [
        {
            "account_key": "account-68-90",
            "account_code": "68.90",
            "account_name": "Единый налоговый счет",
            "opening_debit": 10.0,
            "opening_credit": 2.0,
            "debit_turnover": 30.0,
            "credit_turnover": 20.0,
            "closing_debit": 18.0,
            "closing_credit": 0.0,
            "period_row_count": 1,
            "pre_period_row_count": "",
            "opening_net": 8.0,
            "closing_net": 18.0,
            "required_regulation_account": True,
        }
    ]


class _TailFetchClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def fetch_collection(
        self,
        collection_name: str,
        *,
        top: int,
        skip: int = 0,
        params: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        self.requests.append(
            {
                "collection_name": collection_name,
                "top": top,
                "skip": skip,
                "params": params or {},
            }
        )
        if params and "$filter" in params:
            return (
                {
                    "value": [
                        {
                            "Period": "2026-05-25T10:00:00",
                            "Active": True,
                            "AccountDr_Key": "account-68-90",
                            "AccountCr_Key": "",
                            "Сумма": 7,
                        }
                    ]
                },
                200,
            )
        return (
            {
                "value": [
                    {
                        "Period": "2026-04-30T23:00:00",
                        "Active": True,
                        "AccountDr_Key": "account-68-90",
                        "AccountCr_Key": "",
                        "Сумма": 10,
                    },
                    {
                        "Period": "2026-05-24T23:59:59",
                        "Active": True,
                        "AccountDr_Key": "account-68-90",
                        "AccountCr_Key": "",
                        "Сумма": 5,
                    },
                ]
            },
            200,
        )


def test_accounting_records_fetches_tail_with_period_filter(tmp_path: Path) -> None:
    client = _TailFetchClient()

    result, balance_rows, period_rows = _fetch_accounting_records(
        client=client,  # type: ignore[arg-type]
        output_dir=tmp_path,
        period_start=datetime(2026, 5, 1),
        period_end=datetime(2026, 6, 1),
        account_lookup={
            "account-68-90": {
                "Code": "68.90",
                "Description": "Единый налоговый счет",
            }
        },
        page_size=2,
        max_pages=1,
        tail_max_pages=2,
        start_skip=0,
    )

    tail_requests = [
        request for request in client.requests if "$filter" in request["params"]
    ]
    assert result.error == ""
    assert result.scanned_rows == 3
    assert len(period_rows) == 2
    assert tail_requests
    expected_filter = (
        "Period gt datetime'2026-05-24T23:59:59' "
        "and Period lt datetime'2026-06-01T00:00:00'"
    )
    assert (
        tail_requests[0]["params"]["$filter"] == expected_filter
    )
    assert balance_rows == [
        {
            "account_key": "account-68-90",
            "account_code": "68.90",
            "account_name": "Единый налоговый счет",
            "opening_net": 10.0,
            "debit_turnover": 12.0,
            "credit_turnover": 0.0,
            "closing_net": 22.0,
            "period_row_count": 2,
            "pre_period_row_count": 1,
            "opening_debit": 10.0,
            "opening_credit": 0.0,
            "closing_debit": 22.0,
            "closing_credit": 0.0,
            "required_regulation_account": True,
        }
    ]

    raw_path = tmp_path / "accounting_register_records.raw.json"
    payload = json.loads(raw_path.read_text())
    assert payload["_source"]["pagination_status"] == "main_capped_tail_completed"
    assert payload["_source"]["tail_completed"] is True
    assert payload["_source"]["tail_page_count"] == 1


class _TailFallbackClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def fetch_collection(
        self,
        collection_name: str,
        *,
        top: int,
        skip: int = 0,
        params: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], int]:
        self.requests.append(
            {
                "collection_name": collection_name,
                "top": top,
                "skip": skip,
                "params": params or {},
            }
        )
        if params and "$filter" in params:
            request = httpx.Request("GET", "https://onec.example/odata")
            response = httpx.Response(
                500,
                text='{(3, 1)}: Операция не разрешена в предложении "ГДЕ"',
                request=request,
            )
            raise httpx.HTTPStatusError(
                "filter failed",
                request=request,
                response=response,
            )
        if skip == 2:
            return (
                {
                    "value": [
                        {
                            "Period": "2026-05-25T10:00:00",
                            "Active": True,
                            "AccountDr_Key": "account-68-90",
                            "AccountCr_Key": "",
                            "Сумма": 7,
                        }
                    ]
                },
                200,
            )
        return (
            {
                "value": [
                    {
                        "Period": "2026-04-30T23:00:00",
                        "Active": True,
                        "AccountDr_Key": "account-68-90",
                        "AccountCr_Key": "",
                        "Сумма": 10,
                    },
                    {
                        "Period": "2026-05-24T23:59:59",
                        "Active": True,
                        "AccountDr_Key": "account-68-90",
                        "AccountCr_Key": "",
                        "Сумма": 5,
                    },
                ]
            },
            200,
        )


def test_accounting_records_falls_back_to_skip_tail_when_filter_fails(
    tmp_path: Path,
) -> None:
    client = _TailFallbackClient()

    result, _balance_rows, period_rows = _fetch_accounting_records(
        client=client,  # type: ignore[arg-type]
        output_dir=tmp_path,
        period_start=datetime(2026, 5, 1),
        period_end=datetime(2026, 6, 1),
        account_lookup={
            "account-68-90": {
                "Code": "68.90",
                "Description": "Единый налоговый счет",
            }
        },
        page_size=2,
        max_pages=1,
        tail_max_pages=2,
        start_skip=0,
    )

    assert result.error == ""
    assert len(period_rows) == 2
    assert any("$filter" in request["params"] for request in client.requests)
    assert any(request["skip"] == 2 for request in client.requests)
    raw_path = tmp_path / "accounting_register_records.raw.json"
    payload = json.loads(raw_path.read_text())
    assert payload["_source"]["pagination_status"] == "main_capped_tail_completed"
    assert payload["_source"]["tail_method"] == "period_filter_then_skip_continuation"
    assert "не разрешена" in payload["_source"]["tail_filter_error"]


def test_accounting_records_error_mentions_tail_failure() -> None:
    message = _accounting_records_error(
        start_skip=0,
        capped_by_max_pages=True,
        max_pages=240,
        max_date=datetime(2026, 5, 24, 23, 59, 59),
        period_start=datetime(2026, 5, 1),
        period_end=datetime(2026, 6, 1),
        tail_scan_error="Хвостовая догрузка регистра по Period не выполнена: HTTP 500",
    )

    assert "Хвостовая догрузка" in message
    assert "2026-05-01 - 2026-06-01" in message
