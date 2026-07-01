from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_finance import WbFinanceConfigError, WbFinanceSettings
from wb_unit_economics.wb_stocks import export_wb_warehouse_remains


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir or _default_output_dir()
    try:
        settings = WbFinanceSettings.from_env_file(args.env_file)
        results = export_wb_warehouse_remains(
            settings,
            output_dir,
            status_poll_seconds=args.status_poll_seconds,
            max_status_checks=args.max_status_checks,
            download_delay_seconds=args.download_delay_seconds,
            locale=args.locale,
        )
    except WbFinanceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"WB warehouse remains export: {output_dir}")
    for result in results:
        file_name = result.output_path.name if result.output_path else "-"
        details = (
            f"status={result.status}, rows={result.row_count}, "
            f"task={result.task_id or '-'}, file={file_name}"
        )
        if result.error:
            details = f"{details}, {result.error}"
        print(f"- {result.seller_account_id}: {details}")
    print("Manifest: manifest.json")
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only WB warehouse remains current snapshot."
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--status-poll-seconds", type=float, default=5.0)
    parser.add_argument("--max-status-checks", type=int, default=24)
    parser.add_argument("--download-delay-seconds", type=float, default=61.0)
    parser.add_argument("--locale", default="ru")
    return parser.parse_args()


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Europe/Moscow")).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "wb_warehouse_remains" / timestamp


if __name__ == "__main__":
    sys.exit(main())
