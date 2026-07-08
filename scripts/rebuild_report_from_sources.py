#!/usr/bin/env python3
"""Build DB-first report marts from read-only sources and publish atomically."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import build_excel_mvp_from_snapshots as excel_mvp
from scripts.export_report_artifacts import (
    DEFAULT_EXCEL,
    export_report_artifacts,
)
from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.mapping import (
    build_sku_mapping_from_articles,
    build_sku_mapping_from_onec_marketplace_files,
    has_onec_marketplace_mapping_files,
    load_onec_rows,
    load_wb_card_flat_rows,
)
from wb_unit_economics.onec_cost import (
    load_provisional_cost_snapshots,
    load_sales_register_cost_snapshots,
)
from wb_unit_economics.postgres_finance import (
    default_postgres_target,
    load_cost_snapshots_from_postgres,
    load_sku_mappings_from_postgres,
    load_wb_finance_snapshots_from_postgres,
)
from wb_unit_economics.report_marts import build_report_marts
from wb_unit_economics.streaming_report import build_streamed_unit_economics_report
from wb_unit_economics.wb_expenses import load_wb_expense_allocation_bases
from wb_unit_economics.wb_finance import (
    load_wb_finance_snapshots,
    load_wb_sales_report_summary_rows,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.settings import WebSettings

DEFAULT_REPORT_ID = "excel_mvp_2026_03_01_2026_06_17"


def main() -> int:
    args = parse_args()
    settings = _settings(args)
    build = build_db_first_payload(args)
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    records = []
    with session_factory() as db:
        report = repository.save_report_marts(
            db,
            build["payload"],
            tenant_id=args.tenant_id,
            tenant_name=args.tenant_name,
            report_id=args.report_id,
            publication_status="draft",
            publish=False,
            source_snapshot_set_id=args.source_snapshot_set_id,
        )
        _validate_marts(build["payload"])
        db.flush()
        if args.export_all:
            records = export_report_artifacts(
                repository.report_full_payload(db, report),
                report_id=report.id,
                output_dir=args.output_dir,
                excel_path=args.excel_path,
                excel=True,
                docx=True,
                pdf=True,
                html=True,
                csv=True,
            )
            for artifact_type, record in records:
                repository.record_report_artifact(
                    db,
                    report,
                    artifact_type=artifact_type,
                    path=record["path"],
                    sha256=record["hash"],
                    byte_size=record["byte_size"],
                    status=record["status"],
                )
        repository.publish_report(db, report)
        db.commit()
    print(f"Published report: {args.report_id}")
    print(f"Report rows: {len(build['payload'].get('unitRows', []))}")
    print(f"Lost sales rows: {len(build['payload'].get('lostSales', []))}")
    for artifact_type, record in records:
        print(f"{artifact_type}: {record['status']} {record['path']}")
    return 0


def build_db_first_payload(args: argparse.Namespace) -> dict:
    wb_finance_dir = args.wb_finance_dir or excel_mvp._latest_dir(
        Path("data/wb_finance")
    )
    wb_cards_dir = args.wb_cards_dir or excel_mvp._latest_dir(
        Path("data/wb_product_cards")
    )
    onec_dir = args.onec_dir or excel_mvp._latest_onec_reference_dir(
        Path("data/onec_samples")
    )
    sales_register_dir = (
        args.sales_register_dir
        or excel_mvp._latest_sales_register_dir(Path("data/onec_gross_profit_samples"))
    )
    wb_stock_history_dir = args.wb_stock_history_dir or excel_mvp._optional_latest_dir(
        Path("data/wb_stock_history_daily")
    )
    onec_stock_dir = (
        args.onec_stock_dir
        or excel_mvp._latest_onec_stock_dir(Path("data/onec_samples"))
        or onec_dir
    )
    report_period_start = args.report_period_start or excel_mvp._manifest_period_date(
        wb_finance_dir, "period_start", date(2026, 3, 1)
    )
    report_period_end = args.report_period_end or excel_mvp._manifest_period_date(
        wb_finance_dir, "period_end", date(2026, 6, 17)
    )

    account_mapping = excel_mvp._account_org_mapping(
        args.client_id,
        wb_finance_dir,
        onec_dir,
    )
    account_labels = {
        item.seller_account_id: item.organization_name for item in account_mapping
    }
    organization_labels = {
        item.organization_id: item.organization_name for item in account_mapping
    }
    postgres_target = default_postgres_target(
        database=args.postgres_db_name,
        host=args.postgres_host,
        port=args.postgres_port,
        user=args.postgres_user,
    )
    if args.wb_finance_source == "postgres":
        wb_snapshots = load_wb_finance_snapshots_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.postgres_snapshot_id,
        )
    elif args.wb_finance_source == "files":
        wb_snapshots = load_wb_finance_snapshots(
            wb_finance_dir,
            client_id=args.client_id,
            account_org_mapping=account_mapping,
        )
    else:
        wb_snapshots = []
    if args.wb_finance_source != "files-stream" and not wb_snapshots:
        raise SystemExit("No WB Finance rows found.")

    if args.mapping_source == "postgres":
        sku_mappings = load_sku_mappings_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.mapping_snapshot_id,
        )
    else:
        onec_barcodes = load_onec_rows(onec_dir, "barcodes")
        onec_nomenclature = load_onec_rows(onec_dir, "nomenclature")
        if has_onec_marketplace_mapping_files(args.onec_marketplace_mapping_dir):
            sku_mappings = build_sku_mapping_from_onec_marketplace_files(
                client_id=args.client_id,
                mapping_dir=args.onec_marketplace_mapping_dir,
                nomenclature_rows=onec_nomenclature,
                account_org_mapping=account_mapping,
            )
        else:
            sku_mappings = build_sku_mapping_from_articles(
                client_id=args.client_id,
                wb_card_rows=load_wb_card_flat_rows(wb_cards_dir),
                onec_barcode_rows=onec_barcodes,
                nomenclature_rows=onec_nomenclature,
                account_org_mapping=account_mapping,
            )

    if args.cost_source == "postgres":
        cost_snapshots = load_cost_snapshots_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.cost_snapshot_id,
        )
    elif sales_register_dir:
        cost_snapshots = load_sales_register_cost_snapshots(
            sales_register_dir,
            client_id=args.client_id,
            reference_dir=onec_dir,
            amount_field=args.sales_cost_amount_field,
            marketplace_counterparties_only=True,
        )
    else:
        cost_snapshots = load_provisional_cost_snapshots(
            onec_dir,
            client_id=args.client_id,
            amount_field=args.cost_amount_field,
        )
    wb_summary_rows = (
        load_wb_sales_report_summary_rows(
            args.wb_report_list_dir, client_id=args.client_id
        )
        if args.wb_report_list_dir
        and (args.wb_report_list_dir / "manifest.json").exists()
        else []
    )
    expense_allocation_bases = load_wb_expense_allocation_bases(
        client_id=args.client_id,
        paid_storage_dir=args.wb_paid_storage_dir,
        promotion_stats_dir=args.wb_promotion_stats_dir,
    )
    generated_at = datetime.now(tz=excel_mvp.MOSCOW_TZ)
    if args.wb_finance_source == "files-stream":
        streamed = build_streamed_unit_economics_report(
            client_id=args.client_id,
            wb_finance_dir=wb_finance_dir,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_org_mapping=account_mapping,
            wb_sales_report_summary_rows=wb_summary_rows,
            expense_allocation_bases=expense_allocation_bases,
            generated_at=generated_at,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            stream_cache_dir=args.stream_cache_dir,
            keep_stream_cache=args.keep_stream_cache,
        )
        report = streamed.report
        wb_row_count = streamed.wb_rows
    else:
        report = build_unit_economics_report(
            client_id=args.client_id,
            wb_snapshots=wb_snapshots,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_org_mapping=account_mapping,
            wb_sales_report_summary_rows=wb_summary_rows,
            expense_allocation_bases=expense_allocation_bases,
            generated_at=generated_at,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
        )
        wb_row_count = len(wb_snapshots)
    marts = build_report_marts(
        report,
        cost_snapshots=cost_snapshots,
        sku_mappings=sku_mappings,
        stock_history_dir=wb_stock_history_dir,
        onec_stock_dir=onec_stock_dir,
        account_labels=account_labels,
        organization_labels=organization_labels,
        client_name=args.tenant_name,
    )
    if not report.rows:
        raise SystemExit("No WB Finance rows found in report period.")
    return {
        "payload": marts.to_dashboard_payload(),
        "report": report,
        "wb_rows": wb_row_count,
        "cost_candidates": len(cost_snapshots),
        "sku_mappings": len(sku_mappings),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--tenant-id", default="shumeyko")
    parser.add_argument("--tenant-name", default="Шумейко и Партнеры")
    parser.add_argument("--report-id", default=DEFAULT_REPORT_ID)
    parser.add_argument("--source-snapshot-set-id", default="")
    parser.add_argument("--client-id", default=excel_mvp.CLIENT_ID)
    parser.add_argument("--wb-finance-dir", type=Path, default=None)
    parser.add_argument("--wb-cards-dir", type=Path, default=None)
    parser.add_argument("--onec-dir", type=Path, default=None)
    parser.add_argument(
        "--onec-marketplace-mapping-dir",
        type=Path,
        default=Path("data/onec_marketplace_mapping"),
    )
    parser.add_argument("--sales-register-dir", type=Path, default=None)
    parser.add_argument("--wb-report-list-dir", type=Path, default=None)
    parser.add_argument("--wb-paid-storage-dir", type=Path, default=None)
    parser.add_argument("--wb-promotion-stats-dir", type=Path, default=None)
    parser.add_argument("--wb-stock-history-dir", type=Path, default=None)
    parser.add_argument("--onec-stock-dir", type=Path, default=None)
    parser.add_argument(
        "--report-period-start",
        type=date.fromisoformat,
        default=None,
        help=(
            "Business report_period start. If omitted, local rebuild falls back "
            "to WB Finance manifest source coverage for compatibility."
        ),
    )
    parser.add_argument(
        "--report-period-end",
        type=date.fromisoformat,
        default=None,
        help=(
            "Business report_period end. If omitted, local rebuild falls back "
            "to WB Finance manifest source coverage for compatibility."
        ),
    )
    parser.add_argument(
        "--wb-finance-source",
        choices=["files", "files-stream", "postgres"],
        default="files",
    )
    parser.add_argument(
        "--stream-cache-dir",
        type=Path,
        default=Path("data/.cache/wb_stream_rebuild"),
        help="Ignored local directory for temporary files-stream bucket files.",
    )
    parser.add_argument(
        "--keep-stream-cache",
        action="store_true",
        help="Keep temporary files-stream bucket files for diagnostics.",
    )
    parser.add_argument(
        "--mapping-source", choices=["files", "postgres"], default="files"
    )
    parser.add_argument("--cost-source", choices=["files", "postgres"], default="files")
    parser.add_argument("--postgres-db-name", default="shumeyko_wb_unit_economics")
    parser.add_argument("--postgres-host", default="")
    parser.add_argument("--postgres-port", type=int, default=55433)
    parser.add_argument("--postgres-user", default="")
    parser.add_argument("--postgres-snapshot-id", default=None)
    parser.add_argument("--mapping-snapshot-id", default=None)
    parser.add_argument("--cost-snapshot-id", default=None)
    parser.add_argument(
        "--cost-amount-field", choices=["Сумма", "СуммаБезНДС"], default="Сумма"
    )
    parser.add_argument(
        "--sales-cost-amount-field",
        choices=["Себестоимость", "СебестоимостьБезНДС"],
        default="Себестоимость",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "reports" / "db_first"
    )
    parser.add_argument("--excel-path", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--export-all", action="store_true")
    return parser.parse_args()


def _settings(args: argparse.Namespace) -> WebSettings:
    if args.database_url:
        return WebSettings(_env_file=None, database_url=args.database_url)
    return WebSettings(_env_file=None)


def _validate_marts(payload: dict) -> None:
    if not payload.get("unitRows"):
        raise ValueError("ReportMarts validation failed: unitRows is empty.")
    blocked = {
        "Нет себестоимости 1С",
        "Нет сопоставления WB-1С",
        "Неоднозначное сопоставление",
        "Неполный источник",
    }
    wrong = [
        row
        for row in payload["unitRows"]
        if row.get("status") in blocked
        and row.get("lossClass") != "Нужна проверка данных"
    ]
    if wrong:
        raise ValueError(
            "ReportMarts validation failed: unreliable rows look reliable."
        )


if __name__ == "__main__":
    raise SystemExit(main())
