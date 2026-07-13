from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from scripts.build_wb_1c_audit_pack import build_report_reconciliation_control
from wb_unit_economics.source_integrity import canonical_payload_hash


def test_report_reconciliation_control_calculates_retail_cashback_sums(
    tmp_path,
) -> None:
    finance_dir = tmp_path / "wb_finance"
    finance_dir.mkdir()
    finance_rows = [
        {
            "reportId": "R-1",
            "dateFrom": "2026-06-02",
            "retailAmount": "100",
            "cashbackDiscount": "10",
        },
        {
            "reportId": "R-1",
            "dateFrom": "2026-06-03",
            "retailAmount": "50",
            "cashbackDiscount": "5",
        },
        {
            "reportId": "OTHER",
            "dateFrom": "2026-06-03",
            "retailAmount": "999",
            "cashbackDiscount": "99",
        },
    ]
    (finance_dir / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "status": "ok",
                        "row_count": len(finance_rows),
                        "raw_payload_hash": canonical_payload_hash(finance_rows),
                        "output_file": "finance.json",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (finance_dir / "finance.json").write_text(
        json.dumps(finance_rows),
        encoding="utf-8",
    )
    report_list_dir = tmp_path / "wb_sales_report_list"
    report_list_dir.mkdir()
    summary_rows = [
        {
            "reportId": "R-1",
            "dateFrom": "2026-06-01",
            "dateTo": "2026-06-07",
            "createDate": "2026-06-08",
            "reportType": 1,
            "retailAmountSum": "150",
            "cashbackDiscountSum": "15",
        }
    ]
    (report_list_dir / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "account_name": "WB test",
                        "status": "ok",
                        "status_code": 200,
                        "row_count": len(summary_rows),
                        "raw_payload_hash": canonical_payload_hash(summary_rows),
                        "output_file": "summary.json",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (report_list_dir / "summary.json").write_text(
        json.dumps(summary_rows),
        encoding="utf-8",
    )

    control = build_report_reconciliation_control(
        report_id="R-1",
        seller_account_id="WB_ACCOUNT_1",
        wb_finance_dir=finance_dir,
        wb_report_list_dir=report_list_dir,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 7),
    )

    assert control.detail_retail_amount == Decimal("150")
    assert control.detail_cashback_discount == Decimal("15")
    assert control.summary_retail_amount_sum == Decimal("150")
    assert control.summary_cashback_discount_sum == Decimal("15")
    assert control.summary_retail_minus_cashback == Decimal("135")
    assert control.detail_row_count == 2
    assert control.summary_found is True
