from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.onec_odata import (
    DEFAULT_SAMPLE_COLLECTIONS,
    GROSS_PROFIT_SAMPLE_COLLECTIONS,
    OnecODataConfigError,
    OnecODataSettings,
    OnecSampleCollection,
    export_onec_samples,
)


def main() -> int:
    args = _parse_args()
    collections = _select_collections(args.collection)
    output_dir = args.output_dir or _default_output_dir()

    try:
        settings = OnecODataSettings.from_env_file(args.env_file)
        results = export_onec_samples(
            settings,
            collections,
            output_dir,
            top=args.top,
        )
    except OnecODataConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"1C OData sample export: {output_dir}")
    for result in results:
        status = "ok" if result.ok else "error"
        file_name = result.output_path.name if result.output_path else "-"
        details = f"rows={result.row_count}, file={file_name}"
        if result.error:
            details = f"{details}, {result.error}"
        print(f"- {result.sample_id}: {status}, {details}")
    print("Manifest: manifest.json")
    return 0 if all(result.ok for result in results) else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export small read-only samples from the 1C OData service."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to local env file with ONEC_ODATA_* variables.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for local raw samples. Defaults to data/onec_samples/<ts>.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Maximum rows per collection.",
    )
    parser.add_argument(
        "--collection",
        action="append",
        default=[],
        help="Sample id to export. Can be repeated. Defaults to all MVP samples.",
    )
    return parser.parse_args()


def _select_collections(selected_ids: list[str]) -> list[OnecSampleCollection]:
    if not selected_ids:
        return list(DEFAULT_SAMPLE_COLLECTIONS)
    by_id = {
        item.sample_id: item
        for item in [*DEFAULT_SAMPLE_COLLECTIONS, *GROSS_PROFIT_SAMPLE_COLLECTIONS]
    }
    unknown = sorted(set(selected_ids) - set(by_id))
    if unknown:
        known = ", ".join(sorted(by_id))
        unknown_ids = ", ".join(unknown)
        raise SystemExit(f"Unknown collection id(s): {unknown_ids}. Known: {known}")
    return [by_id[item] for item in selected_ids]


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=ZoneInfo("Europe/Moscow")).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "onec_samples" / timestamp


if __name__ == "__main__":
    sys.exit(main())
