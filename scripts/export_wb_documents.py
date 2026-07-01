from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_documents import (
    DEFAULT_DOCUMENT_CATEGORY_KEYWORDS,
    default_wb_documents_output_dir,
    export_wb_documents,
)
from wb_unit_economics.wb_finance import WbFinanceSettings


def main() -> int:
    args = _parse_args()
    output_dir = args.output_dir or default_wb_documents_output_dir()
    settings = WbFinanceSettings.from_env_file(args.env_file)
    results = export_wb_documents(
        settings=settings,
        output_dir=output_dir,
        period_start=args.period_start,
        period_end=args.period_end,
        category_keywords=tuple(args.category_keyword),
        download=args.download,
        locale=args.locale,
    )
    print(f"WB Documents: {output_dir}")
    for result in results:
        print(
            f"{result.seller_account_id}: {result.status}, "
            f"documents={result.row_count}, downloaded={result.downloaded_count}"
        )
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only WB document metadata and optional files."
    )
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--locale", default="ru")
    parser.add_argument(
        "--category-keyword",
        action="append",
        default=list(DEFAULT_DOCUMENT_CATEGORY_KEYWORDS),
        help="Case-insensitive keyword for document name/category filtering.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download selected ZIP/PDF documents into data/wb_documents.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
