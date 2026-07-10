from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from scripts.probe_onec_month_close_osv import (
    _load_settings,
    probe_virtual_accounting_tables,
)
from wb_unit_economics.onec_odata import (
    BASE_URL_KEYS,
    PASSWORD_KEYS,
    USERNAME_KEYS,
    OnecODataConfigError,
    OnecODataSettings,
)


def test_osv_probe_uses_environment_by_default_not_dotenv(
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


def test_osv_probe_sends_get_requests_and_returns_sanitized_summary() -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if "BalanceAndTurnovers" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "Account_Key": "account-1",
                            "OpeningBalance": 100,
                            "ClosingBalance": 150,
                        }
                    ]
                },
            )
        return httpx.Response(
            404,
            json={
                "odata.error": {
                    "message": {"value": "virtual table is not published"}
                }
            },
        )

    settings = OnecODataSettings(
        base_url="https://onec.example/base/odata/standard.odata",
        username="readonly",
        password="secret",
    )

    probes = probe_virtual_accounting_tables(
        settings=settings,
        register_name="AccountingRegister_Управленческий",
        period_start=datetime(2026, 5, 1),
        period_end=datetime(2026, 6, 1),
        transport=httpx.MockTransport(handler),
    )

    assert [request.method for request in requested] == ["GET", "GET", "GET"]
    assert requested[0].url.params["$format"] == "json"
    assert requested[0].url.params["$top"] == "5"
    assert probes[0].ok is True
    assert probes[0].row_count == 1
    assert probes[0].fields == ["Account_Key", "ClosingBalance", "OpeningBalance"]
    assert probes[1].ok is False
    assert probes[1].error == "virtual table is not published"
    assert "account-1" not in str([asdict(probe) for probe in probes])
