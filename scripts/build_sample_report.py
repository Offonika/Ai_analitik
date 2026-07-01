from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fixtures import (
    CLIENT_ID,
    account_org_mapping,
    cost_snapshots,
    sku_mappings,
    wb_snapshots,
)
from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.excel import build_excel_report


def main() -> None:
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=wb_snapshots(),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        as_of_date=date(2026, 6, 16),
    )
    output = build_excel_report(
        report,
        Path("reports/sample_excel_mvp.xlsx"),
        cost_snapshots=cost_snapshots(),
        sku_mappings=sku_mappings(),
    )
    print(output)


if __name__ == "__main__":
    main()
