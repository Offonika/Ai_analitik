from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_expenses import export_wb_promotion_stats
from wb_unit_economics.wb_finance import WbFinanceConfigError, WbFinanceSettings


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir or _default_output_dir()
    try:
        settings = WbFinanceSettings.from_env_file(args.env_file)
        results = export_wb_promotion_stats(
            settings,
            output_dir,
            period_start=args.period_start,
            period_end=args.period_end,
            statuses=args.statuses,
            batch_size=args.batch_size,
            request_delay_seconds=args.request_delay_seconds,
            chunk_days=args.chunk_days,
            chunk_delay_seconds=args.chunk_delay_seconds,
            retry_attempts=args.retry_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    except WbFinanceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"WB promotion stats export: {output_dir}")
    for result in results:
        file_name = result.output_path.name if result.output_path else "-"
        details = (
            f"status={result.status}, rows={result.row_count}, "
            f"campaigns={len(result.campaign_ids)}, file={file_name}"
        )
        if result.error:
            details = f"{details}, {result.error}"
        print(f"- {result.seller_account_id}: {details}")
    print("Manifest: manifest.json")
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only WB campaign statistics for allocation."
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--statuses",
        type=_status_list,
        default=(7, 9, 11),
        help="Campaign statuses as comma-separated values. Default: 7,9,11.",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--request-delay-seconds", type=float, default=20.0)
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=None,
        help="Split the requested period into chunks when WB rejects long ranges.",
    )
    parser.add_argument(
        "--chunk-delay-seconds",
        type=float,
        default=70.0,
        help="Pause between date chunks for the same seller account.",
    )
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=0,
        help="Retry transient failed chunks this many times.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=70.0,
        help="Pause before retrying a transient failed chunk.",
    )
    return parser.parse_args()


def _status_list(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Europe/Moscow")).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "wb_promotion_stats" / timestamp


if __name__ == "__main__":
    sys.exit(main())
