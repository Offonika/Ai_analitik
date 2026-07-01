from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_finance import (  # noqa: E402
    WbFinanceConfigError,
    WbFinanceSettings,
    export_wb_finance_by_report_ids,
)


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir or _default_output_dir()
    try:
        settings = WbFinanceSettings.from_env_file(args.env_file)
        results = export_wb_finance_by_report_ids(
            settings,
            output_dir,
            report_ids=args.report_id,
            limit=args.limit,
            max_pages=args.max_pages,
            request_delay_seconds=args.request_delay_seconds,
        )
    except WbFinanceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"WB finance reportId export: {output_dir}")
    for result in results:
        file_name = result.output_path.name if result.output_path else "-"
        details = (
            f"report_id={result.wb_report_id}, status={result.status}, "
            f"rows={result.row_count}, rrd_next={result.rrd_id_next}, "
            f"file={file_name}"
        )
        if result.error:
            details = f"{details}, {result.error}"
        print(f"- {result.seller_account_id} page {result.page_index}: {details}")
    print("Manifest: manifest.json")
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only WB Finance sales report details by reportId."
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
        help="Directory for local raw snapshots. Defaults to data/wb_finance/<ts>.",
    )
    parser.add_argument(
        "--report-id",
        action="append",
        required=True,
        help="Weekly WB reportId to export. Repeat for multiple reports.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100000,
        help="Maximum WB rows per page, must be <= 100000.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Maximum pages per report and account.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=61.0,
        help="Pause between requests for the same seller account.",
    )
    return parser.parse_args()


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Europe/Moscow")).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "wb_finance" / timestamp


if __name__ == "__main__":
    sys.exit(main())
