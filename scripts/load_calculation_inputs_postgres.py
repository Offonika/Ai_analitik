from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.build_excel_mvp_from_snapshots import (  # noqa: E402
    CLIENT_ID,
    _account_org_mapping,
    _latest_dir,
    _latest_sales_register_dir,
)
from wb_unit_economics.mapping import (  # noqa: E402
    build_sku_mapping_from_articles,
    build_sku_mapping_from_onec_marketplace_files,
    has_onec_marketplace_mapping_files,
    load_onec_rows,
    load_wb_card_flat_rows,
)
from wb_unit_economics.onec_cost import (  # noqa: E402
    load_provisional_cost_snapshots,
    load_sales_register_cost_snapshots,
)
from wb_unit_economics.postgres_finance import (  # noqa: E402
    CalculationInputsPostgresSummary,
    default_postgres_target,
    load_cost_snapshots_to_postgres,
    load_sku_mappings_to_postgres,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def main() -> int:
    args = _parse_args()
    wb_finance_dir = args.wb_finance_dir or _latest_dir(Path("data/wb_finance"))
    wb_cards_dir = args.wb_cards_dir or _latest_dir(Path("data/wb_product_cards"))
    onec_dir = args.onec_dir or _latest_dir(Path("data/onec_samples"))
    sales_register_dir = args.sales_register_dir or _latest_sales_register_dir(
        Path("data/onec_gross_profit_samples")
    )
    snapshot_id = args.snapshot_id or datetime.now(tz=MOSCOW_TZ).strftime(
        "%Y%m%d-%H%M%S"
    )

    account_mapping = _account_org_mapping(args.client_id, wb_finance_dir, onec_dir)
    onec_barcodes = load_onec_rows(onec_dir, "barcodes")
    onec_nomenclature = load_onec_rows(onec_dir, "nomenclature")

    if has_onec_marketplace_mapping_files(args.onec_marketplace_mapping_dir):
        sku_mappings = build_sku_mapping_from_onec_marketplace_files(
            client_id=args.client_id,
            mapping_dir=args.onec_marketplace_mapping_dir,
            nomenclature_rows=onec_nomenclature,
            account_org_mapping=account_mapping,
        )
        mapping_source = "1C marketplace mapping export"
    else:
        sku_mappings = build_sku_mapping_from_articles(
            client_id=args.client_id,
            wb_card_rows=load_wb_card_flat_rows(wb_cards_dir),
            onec_barcode_rows=onec_barcodes,
            nomenclature_rows=onec_nomenclature,
            account_org_mapping=account_mapping,
        )
        mapping_source = "WB cards + 1C article auto-match"

    if sales_register_dir:
        cost_snapshots = load_sales_register_cost_snapshots(
            sales_register_dir,
            client_id=args.client_id,
            reference_dir=onec_dir,
            amount_field=args.sales_cost_amount_field,
            marketplace_counterparties_only=True,
        )
        cost_source = (
            f"AccumulationRegister_Продажи/{args.sales_cost_amount_field} "
            f"({sales_register_dir.name})"
        )
    else:
        cost_snapshots = load_provisional_cost_snapshots(
            onec_dir,
            client_id=args.client_id,
            amount_field=args.cost_amount_field,
        )
        cost_source = f"AccumulationRegister_Запасы/{args.cost_amount_field}"

    target = default_postgres_target(
        database=args.postgres_db_name,
        host=args.postgres_host,
        port=args.postgres_port,
        user=args.postgres_user,
    )
    mapping_count = load_sku_mappings_to_postgres(
        sku_mappings,
        target=target,
        schema_path=args.schema_path,
        snapshot_id=snapshot_id,
        replace_snapshot=args.replace_snapshot,
    )
    cost_count = load_cost_snapshots_to_postgres(
        cost_snapshots,
        target=target,
        schema_path=args.schema_path,
        snapshot_id=snapshot_id,
        replace_snapshot=args.replace_snapshot,
    )
    summary = CalculationInputsPostgresSummary(
        snapshot_id=snapshot_id,
        sku_mapping_count=mapping_count,
        cost_snapshot_count=cost_count,
    )
    print(f"Snapshot: {summary.snapshot_id}")
    print(f"SKU mappings streamed: {summary.sku_mapping_count}")
    print(f"1C cost snapshots streamed: {summary.cost_snapshot_count}")
    print(f"Mapping source: {mapping_source}")
    print(f"Cost source: {cost_source}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load local SKU mapping and 1C cost snapshots into Postgres."
    )
    parser.add_argument("--client-id", default=CLIENT_ID)
    parser.add_argument("--wb-finance-dir", type=Path, default=None)
    parser.add_argument("--wb-cards-dir", type=Path, default=None)
    parser.add_argument("--onec-dir", type=Path, default=None)
    parser.add_argument(
        "--onec-marketplace-mapping-dir",
        type=Path,
        default=Path("data/onec_marketplace_mapping"),
    )
    parser.add_argument("--sales-register-dir", type=Path, default=None)
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--postgres-db-name", default="shumeyko_wb_unit_economics")
    parser.add_argument("--postgres-host", default="")
    parser.add_argument("--postgres-port", type=int, default=55433)
    parser.add_argument("--postgres-user", default="")
    parser.add_argument(
        "--replace-snapshot",
        action="store_true",
        help="Delete existing mapping/cost rows for snapshot id before loading.",
    )
    parser.add_argument(
        "--schema-path",
        type=Path,
        default=Path("sql/postgres_schema.sql"),
    )
    parser.add_argument(
        "--cost-amount-field",
        default="Сумма",
        choices=["Сумма", "СуммаБезНДС"],
    )
    parser.add_argument(
        "--sales-cost-amount-field",
        default="СебестоимостьБезНДС",
        choices=["Себестоимость", "СебестоимостьБезНДС"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
