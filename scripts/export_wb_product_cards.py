from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_content import (
    WbContentConfigError,
    WbContentSettings,
    export_wb_product_cards,
)


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir or _default_output_dir()
    try:
        settings = WbContentSettings.from_env_file(args.env_file)
        results = export_wb_product_cards(
            settings,
            output_dir,
            limit=args.limit,
            max_pages=args.max_pages,
            locale=args.locale,
            include_trash=args.include_trash,
            request_delay_seconds=args.request_delay_seconds,
        )
    except WbContentConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"WB product cards export: {output_dir}")
    for result in results:
        status = "ok" if result.ok else "error"
        file_name = result.output_path.name if result.output_path else "-"
        flat_file = result.flat_output_path.name if result.flat_output_path else "-"
        details = (
            f"cards={result.card_count}, flat_rows={result.flat_row_count}, "
            f"file={file_name}, flat={flat_file}"
        )
        if result.error:
            details = f"{details}, {result.error}"
        print(
            f"- {result.seller_account_id} {result.cards_source} "
            f"page {result.page_index}: {status}, {details}"
        )
    print("Manifest: manifest.json")
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only WB product card details for mapping discovery."
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
        help="Directory for local raw samples. Defaults to data/wb_product_cards/<ts>.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum product cards per page.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum pages per account.",
    )
    parser.add_argument(
        "--locale",
        default="ru",
        help="WB response locale.",
    )
    parser.add_argument(
        "--include-trash",
        action="store_true",
        help="Also export product cards from WB trash, useful for historical mapping.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=0.65,
        help="Pause between paginated WB requests.",
    )
    return parser.parse_args()


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Europe/Moscow")).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "wb_product_cards" / timestamp


if __name__ == "__main__":
    sys.exit(main())
