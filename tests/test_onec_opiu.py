from __future__ import annotations

import json
from datetime import date

from wb_unit_economics.onec_opiu import load_onec_opiu_summary


def test_load_onec_opiu_summary_from_income_expense_register(tmp_path) -> None:
    payload = {
        "value": [
            {
                "Recorder": "DOC-1",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-03-31T23:59:59",
                        "СчетУчета_Key": "ca495cfb-658a-11ec-be7c-8e45118e8d46",
                        "СуммаДоходов": "1000",
                        "СуммаРасходов": "0",
                    },
                    {
                        "Active": True,
                        "Period": "2026-03-31T23:59:59",
                        "СчетУчета_Key": "ca495cfc-658a-11ec-be7c-8e45118e8d46",
                        "СуммаДоходов": "0",
                        "СуммаРасходов": "300",
                    },
                    {
                        "Active": True,
                        "Period": "2026-03-31T23:59:59",
                        "СчетУчета_Key": "ed809e63-2c0c-11f1-80e1-000c29cb5adf",
                        "СтруктурнаяЕдиница_Key": (
                            "9fb8122b-658a-11ec-be7c-8e45118e8d46"
                        ),
                        "СуммаДоходов": "0",
                        "СуммаРасходов": "150",
                    },
                    {
                        "Active": True,
                        "Period": "2026-02-28T23:59:59",
                        "СчетУчета_Key": "ca495cfb-658a-11ec-be7c-8e45118e8d46",
                        "СуммаДоходов": "999",
                        "СуммаРасходов": "0",
                    },
                ],
            }
        ]
    }
    source_dir = tmp_path / "opiu"
    source_dir.mkdir()
    (source_dir / "income_expense_register.raw.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = load_onec_opiu_summary(
        source_dir,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 6, 17),
    )

    assert summary is not None
    assert summary.value("revenue") == 1000
    assert summary.value("cogs") == 300
    assert summary.value("rwb_commission") == 150
    assert summary.value("rwb_total") == 150
    assert summary.value("net_profit") == 550
    assert summary.monthly_values["2026-03"]["cogs"] == 300
    assert summary.monthly_values["2026-03"]["rwb_total"] == 150
    assert summary.config_status == "pilot_defaults"


def test_load_onec_opiu_summary_uses_non_secret_config(tmp_path) -> None:
    payload = {
        "value": [
            {
                "Recorder": "DOC-1",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-03-31T23:59:59",
                        "СчетУчета_Key": "REVENUE-GUID",
                        "СуммаДоходов": "2000",
                        "СуммаРасходов": "0",
                    },
                    {
                        "Active": True,
                        "Period": "2026-03-31T23:59:59",
                        "СчетУчета_Key": "RWB-COMMISSION-GUID",
                        "СтруктурнаяЕдиница_Key": "RWB-UNIT-GUID",
                        "СуммаДоходов": "0",
                        "СуммаРасходов": "250",
                    },
                ],
            }
        ]
    }
    source_dir = tmp_path / "opiu"
    source_dir.mkdir()
    (source_dir / "income_expense_register.raw.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    config_path = tmp_path / "onec_opiu_accounts.json"
    config_path.write_text(
        json.dumps(
            {
                "revenue_account_key": "REVENUE-GUID",
                "rwb_structural_unit_key": "RWB-UNIT-GUID",
                "rwb_account_keys": {"commission": "RWB-COMMISSION-GUID"},
            }
        ),
        encoding="utf-8",
    )

    summary = load_onec_opiu_summary(
        source_dir,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 6, 17),
        config_path=config_path,
    )

    assert summary is not None
    assert summary.config_status == "configured"
    assert summary.value("revenue") == 2000
    assert summary.value("rwb_commission") == 250
    assert summary.value("rwb_total") == 250
