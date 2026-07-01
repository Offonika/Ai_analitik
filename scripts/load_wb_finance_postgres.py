from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from build_excel_mvp_from_snapshots import _account_org_mapping, _latest_dir

from wb_unit_economics.postgres_finance import (
    default_postgres_target,
    load_wb_finance_export_to_postgres,
    print_summary,
)

CLIENT_ID = "shumeyko-partners"


def main() -> int:
    args = _parse_args()
    wb_finance_dir = args.wb_finance_dir or _latest_dir(Path("data/wb_finance"))
    onec_dir = args.onec_dir or _latest_dir(Path("data/onec_samples"))
    account_mapping = _account_org_mapping(args.client_id, wb_finance_dir, onec_dir)
    target = default_postgres_target(
        database=args.db_name,
        host=args.host,
        port=args.port,
        user=args.user,
    )
    summary = load_wb_finance_export_to_postgres(
        wb_finance_dir,
        client_id=args.client_id,
        account_org_mapping=account_mapping,
        target=target,
        schema_path=args.schema_path,
        snapshot_id=args.snapshot_id,
    )
    print_summary(summary)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load local WB Finance raw snapshots into local Postgres."
    )
    parser.add_argument("--client-id", default=CLIENT_ID)
    parser.add_argument("--wb-finance-dir", type=Path, default=None)
    parser.add_argument("--onec-dir", type=Path, default=None)
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument(
        "--schema-path",
        type=Path,
        default=Path("sql/postgres_schema.sql"),
        help="Postgres schema SQL file.",
    )
    parser.add_argument("--db-name", default="shumeyko_wb_unit_economics")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default="")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
