from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_finance import (
    WbFinanceConfigError,
    WbFinanceSettings,
    export_wb_sales_report_list,
)


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir or _default_output_dir()
    try:
        settings = WbFinanceSettings.from_env_file(args.env_file)
        results = export_wb_sales_report_list(
            settings,
            output_dir,
            period_start=args.period_start,
            period_end=args.period_end,
            limit=args.limit,
            max_pages=args.max_pages,
            request_delay_seconds=args.request_delay_seconds,
            period=args.period,
        )
    except WbFinanceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"WB sales report list export: {output_dir}")
    for result in results:
        file_name = result.output_path.name if result.output_path else "-"
        details = (
            f"status={result.status}, rows={result.row_count}, "
            f"offset={result.offset}, file={file_name}"
        )
        if result.error:
            details = f"{details}, {result.error}"
        print(f"- {result.seller_account_id} page {result.page_index}: {details}")
    print("Manifest: manifest.json")
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only WB weekly sales report list."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to local env file with WB_ACCOUNT_*_API_KEY variables.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory for local raw snapshots. Defaults to "
            "data/wb_sales_report_list/<ts>."
        ),
    )
    parser.add_argument(
        "--period-start",
        type=date.fromisoformat,
        required=True,
        help="Report start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--period-end",
        type=date.fromisoformat,
        required=True,
        help="Report end date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--period",
        default="weekly",
        choices=["daily", "weekly"],
        help="WB report periodicity.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum WB reports per page, must be <= 1000.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum pages per account.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=61.0,
        help="Pause between paginated requests for the same seller account.",
    )
    return parser.parse_args()


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Europe/Moscow")).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "wb_sales_report_list" / timestamp


if __name__ == "__main__":
    sys.exit(main())
