#!/usr/bin/env python3
"""Build DB-first report marts as a safe draft or gated atomic publish."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import build_excel_mvp_from_snapshots as excel_mvp
from scripts.export_report_artifacts import (
    DEFAULT_EXCEL,
    export_report_artifacts,
)
from wb_unit_economics.calculation import build_unit_economics_report, week_bounds
from wb_unit_economics.config import tax_profiles_from_account_org_mapping
from wb_unit_economics.contracts import (
    AccountOrgMapping,
    InputVatPolicy,
    MarketplaceFinanceDailyFact,
    SalesModel,
    TaxProfile,
    VatDeductionMode,
    VatMode,
    WbApiSnapshot,
)
from wb_unit_economics.mapping import (
    build_sku_mapping_from_articles,
    build_sku_mapping_from_onec_marketplace_files,
    has_onec_marketplace_mapping_files,
    load_onec_rows,
    load_wb_card_flat_rows,
    merge_sku_mappings_with_current,
)
from wb_unit_economics.onec_cost import (
    extract_gross_profit_document_rows,
    load_provisional_cost_snapshots,
    load_sales_register_cost_snapshots,
    load_sales_register_rows,
)
from wb_unit_economics.postgres_finance import (
    default_postgres_target,
    load_cost_snapshots_from_postgres,
    load_sku_mappings_from_postgres,
    load_wb_finance_snapshots_from_postgres,
)
from wb_unit_economics.report_marts import build_report_marts
from wb_unit_economics.streaming_report import (
    build_streamed_unit_economics_from_spool,
    prepare_streamed_wb_spool,
)
from wb_unit_economics.wb_expenses import load_wb_expense_allocation_bases
from wb_unit_economics.wb_finance import (
    load_wb_finance_snapshots,
    load_wb_sales_report_summary_rows,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings


def main() -> int:
    args = parse_args()
    _validate_lineage_args(args)
    settings = _settings(args)
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    source_tax_profiles: list[TaxProfile] | None = None
    source_input_vat_policies: list[InputVatPolicy] | None = None
    if args.source_refresh_run_id:
        with session_factory() as db:
            refresh_run = db.get(SourceRefreshRun, args.source_refresh_run_id)
            if refresh_run is None:
                raise ValueError(
                    f"source refresh not found: {args.source_refresh_run_id}"
                )
            source_tax_profiles = repository.tax_profiles_for_source_refresh(
                db,
                refresh_run,
            )
            source_input_vat_policies = (
                repository.input_vat_policies_for_source_refresh(db, refresh_run)
            )
    build = build_db_first_payload(
        args,
        tax_profiles=source_tax_profiles,
        input_vat_policies=source_input_vat_policies,
    )
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
        if args.source_refresh_run_id:
            refresh_run = db.get(SourceRefreshRun, args.source_refresh_run_id)
            if refresh_run is None:
                raise ValueError(
                    f"source refresh not found: {args.source_refresh_run_id}"
                )
            repository.replace_source_loads_from_refresh(db, report, refresh_run)
        if args.stock_history_refresh_run_id:
            stock_refresh_run = db.get(
                SourceRefreshRun,
                args.stock_history_refresh_run_id,
            )
            if stock_refresh_run is None:
                raise ValueError(
                    "stock history source refresh not found: "
                    f"{args.stock_history_refresh_run_id}"
                )
            stock_collections = [
                item
                for item in stock_refresh_run.collections
                if item.source_type == "wb_stock_history_daily"
            ]
            if not stock_collections:
                raise ValueError(
                    "stock history source refresh has no wb_stock_history_daily "
                    "collection"
                )
            build_path = args.wb_stock_history_dir.resolve()
            source_paths = {
                Path(item.raw_path).resolve()
                for item in stock_collections
                if item.raw_path
            }
            if source_paths != {build_path}:
                raise ValueError(
                    "stock history build path does not match registered source "
                    "refresh path"
                )
            repository.replace_report_source_load_from_refresh(
                db,
                report,
                stock_refresh_run,
                source_type="wb_stock_history_daily",
            )
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
        if args.publish:
            repository.publish_report(db, report)
        db.commit()
    if args.publish:
        print(f"Published report: {args.report_id}")
    else:
        print(f"Saved draft report: {args.report_id}")
    print(f"Report rows: {len(build['payload'].get('unitRows', []))}")
    print(f"Lost sales rows: {len(build['payload'].get('lostSales', []))}")
    for artifact_type, record in records:
        print(f"{artifact_type}: {record['status']} {record['path']}")
    return 0


def build_db_first_payload(
    args: argparse.Namespace,
    *,
    tax_profiles: list[TaxProfile] | None = None,
    input_vat_policies: list[InputVatPolicy] | None = None,
) -> dict:
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
    onec_services_dir = getattr(args, "onec_services_dir", None)
    if onec_services_dir is None:
        onec_services_dir = excel_mvp._latest_onec_services_dir(
            Path("data/onec_marketplace_service_samples")
        )
    wb_stock_history_dir = args.wb_stock_history_dir
    if wb_stock_history_dir is None and getattr(
        args, "allow_latest_stock_history_fallback", False
    ):
        wb_stock_history_dir = excel_mvp._optional_latest_dir(
            Path("data/wb_stock_history_daily")
        )
    onec_stock_dir = (
        args.onec_stock_dir
        or excel_mvp._latest_onec_stock_dir(Path("data/onec_samples"))
        or onec_dir
    )
    report_period_start = args.report_period_start or excel_mvp._manifest_period_date(
        wb_finance_dir, "period_start", None
    )
    report_period_end = args.report_period_end or excel_mvp._manifest_period_date(
        wb_finance_dir, "period_end", None
    )
    if report_period_start is None or report_period_end is None:
        raise SystemExit(
            "Report period is missing; pass --report-period-start and "
            "--report-period-end or provide both dates in the WB manifest."
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
    source_tax_profiles = (
        tax_profiles
        if tax_profiles is not None
        else tax_profiles_from_account_org_mapping(
            args.client_id,
            account_mapping,
            onec_organization_rows=excel_mvp._organizations_from_sample(onec_dir),
            special_tax_mode_rows=excel_mvp._optional_onec_rows(
                onec_dir, "tax_special_regime_notifications"
            ),
        )
    )
    tax_profiles = _tax_profiles_for_rebuild(
        args,
        account_mapping,
        source_profiles=source_tax_profiles,
    )
    confirmed_input_vat_org_ids = _confirmed_input_vat_org_ids(
        onec_dir,
        period_start=report_period_start,
        period_end=report_period_end,
    )
    postgres_target = default_postgres_target(
        database=args.postgres_db_name,
        host=args.postgres_host,
        port=args.postgres_port,
        user=args.postgres_user,
    )
    supplied_summary_rows = getattr(args, "wb_sales_report_summary_rows", None)
    wb_summary_rows = (
        list(supplied_summary_rows)
        if supplied_summary_rows is not None
        else (
            load_wb_sales_report_summary_rows(
                args.wb_report_list_dir, client_id=args.client_id
            )
            if args.wb_report_list_dir
            and (args.wb_report_list_dir / "manifest.json").exists()
            else []
        )
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
    elif args.wb_finance_source == "daily-facts":
        supplied_daily_facts = getattr(args, "wb_daily_facts", None)
        if supplied_daily_facts is None:
            raise ValueError("daily-facts source requires wb_daily_facts")
        wb_snapshots = _wb_snapshots_from_daily_facts(supplied_daily_facts)
    else:
        wb_snapshots = []
    if args.wb_finance_source != "files-stream" and not wb_snapshots:
        raise SystemExit("No WB Finance rows found.")
    prepared_stream = (
        prepare_streamed_wb_spool(
            wb_finance_dir=wb_finance_dir,
            client_id=args.client_id,
            account_org_mapping=account_mapping,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            stream_cache_dir=args.stream_cache_dir,
            keep_stream_cache=args.keep_stream_cache,
            isolate_process=True,
        )
        if args.wb_finance_source == "files-stream"
        else None
    )

    supplied_sku_mappings = getattr(args, "sku_mappings", None)
    if args.mapping_source == "postgres" and supplied_sku_mappings is None:
        sku_mappings = load_sku_mappings_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.mapping_snapshot_id,
        )
    else:
        onec_barcodes = load_onec_rows(onec_dir, "barcodes")
        onec_nomenclature = load_onec_rows(onec_dir, "nomenclature")
        if has_onec_marketplace_mapping_files(args.onec_marketplace_mapping_dir):
            fallback_sku_mappings = build_sku_mapping_from_onec_marketplace_files(
                client_id=args.client_id,
                mapping_dir=args.onec_marketplace_mapping_dir,
                nomenclature_rows=onec_nomenclature,
                account_org_mapping=account_mapping,
            )
        else:
            fallback_sku_mappings = build_sku_mapping_from_articles(
                client_id=args.client_id,
                wb_card_rows=load_wb_card_flat_rows(wb_cards_dir),
                onec_barcode_rows=onec_barcodes,
                nomenclature_rows=onec_nomenclature,
                account_org_mapping=account_mapping,
            )
        sku_mappings = (
            merge_sku_mappings_with_current(
                fallback_sku_mappings,
                supplied_sku_mappings,
            )
            if supplied_sku_mappings is not None
            else fallback_sku_mappings
        )

    if args.cost_source == "postgres":
        cost_snapshots = load_cost_snapshots_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.cost_snapshot_id,
        )
    elif sales_register_dir:
        sales_cost_amount_field = _sales_cost_amount_field(
            args.sales_cost_amount_field,
            tax_profiles=tax_profiles,
        )
        cost_snapshots = load_sales_register_cost_snapshots(
            sales_register_dir,
            client_id=args.client_id,
            reference_dir=onec_dir,
            amount_field=sales_cost_amount_field,
            marketplace_counterparties_only=True,
            input_vat_policies=input_vat_policies or [],
            confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
        )
    else:
        cost_snapshots = load_provisional_cost_snapshots(
            onec_dir,
            client_id=args.client_id,
            amount_field=args.cost_amount_field,
        )
    expense_allocation_bases = load_wb_expense_allocation_bases(
        client_id=args.client_id,
        paid_storage_dir=args.wb_paid_storage_dir,
        promotion_stats_dir=args.wb_promotion_stats_dir,
    )
    marketplace_service_rows = excel_mvp._onec_marketplace_service_rows(
        args.client_id,
        onec_services_dir,
        reference_dir=onec_dir,
        sales_register_dir=sales_register_dir,
    )
    onec_gross_profit_rows = (
        extract_gross_profit_document_rows(
            client_id=args.client_id,
            sales_rows=load_sales_register_rows(sales_register_dir),
            marketplace_counterparties_only=True,
        )
        if sales_register_dir
        and (sales_register_dir / "sales_register.raw.json").exists()
        else []
    )
    generated_at = datetime.now(tz=excel_mvp.MOSCOW_TZ)
    if args.wb_finance_source == "files-stream":
        if prepared_stream is None:
            raise RuntimeError("streamed WB spool was not prepared")
        wb_source_row_count = prepared_stream.spool.rows_seen
        streamed = build_streamed_unit_economics_from_spool(
            prepared=prepared_stream,
            client_id=args.client_id,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_org_mapping=account_mapping,
            wb_sales_report_summary_rows=wb_summary_rows,
            expense_allocation_bases=expense_allocation_bases,
            onec_marketplace_service_rows=marketplace_service_rows,
            tax_profiles=tax_profiles,
            input_vat_policies=input_vat_policies,
            confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
            generated_at=generated_at,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            collect_daily_facts=bool(
                getattr(args, "marketplace_daily_facts_enabled", True)
            ),
        )
        report = streamed.report
        wb_row_count = streamed.wb_rows
        wb_report_period_row_count = streamed.wb_rows
        daily_facts = streamed.daily_facts
    else:
        daily_facts: list[MarketplaceFinanceDailyFact] = []
        report = build_unit_economics_report(
            client_id=args.client_id,
            wb_snapshots=wb_snapshots,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_org_mapping=account_mapping,
            wb_sales_report_summary_rows=wb_summary_rows,
            expense_allocation_bases=expense_allocation_bases,
            onec_marketplace_service_rows=marketplace_service_rows,
            tax_profiles=tax_profiles,
            input_vat_policies=input_vat_policies,
            confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
            generated_at=generated_at,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            daily_facts_sink=daily_facts,
        )
        wb_row_count = len(wb_snapshots)
        wb_source_row_count = sum(
            max(1, int(item.source_row_count)) for item in wb_snapshots
        )
        wb_report_period_row_count = sum(
            max(1, int(item.source_row_count))
            for item in wb_snapshots
            if report_period_start
            <= week_bounds(item.period_start)[1]
            <= report_period_end
        )
    marts = build_report_marts(
        report,
        cost_snapshots=cost_snapshots,
        sku_mappings=sku_mappings,
        stock_history_dir=wb_stock_history_dir,
        onec_stock_dir=onec_stock_dir,
        account_labels=account_labels,
        organization_labels=organization_labels,
        onec_gross_profit_rows=onec_gross_profit_rows,
        onec_marketplace_service_rows=marketplace_service_rows,
        wb_sales_report_summary_rows=wb_summary_rows,
        source_run_id=getattr(args, "source_refresh_run_id", ""),
        client_name=args.tenant_name,
    )
    if not report.rows:
        raise SystemExit("No WB Finance rows found in report period.")
    return {
        "payload": marts.to_dashboard_payload(),
        "report": report,
        "daily_facts": daily_facts,
        "wb_rows": wb_row_count,
        "wb_source_rows": wb_source_row_count,
        "wb_report_period_rows": wb_report_period_row_count,
        "cost_candidates": len(cost_snapshots),
        "sku_mappings": len(sku_mappings),
    }


def _wb_snapshots_from_daily_facts(
    facts: list[MarketplaceFinanceDailyFact],
) -> list[WbApiSnapshot]:
    """Recreate the calculation grain without rereading immutable WB raw pages."""
    loaded_at = datetime.now().astimezone()
    snapshots: list[WbApiSnapshot] = []
    for fact in facts:
        sales_model_text = str(fact.sales_model or SalesModel.FBO.value).lower()
        sales_model = (
            SalesModel(sales_model_text)
            if sales_model_text in {item.value for item in SalesModel}
            else SalesModel.FBO
        )
        report_type = {
            "commissioner_report": 1,
            "buyout_notice": 2,
        }.get(str(fact.document_kind))
        snapshots.append(
            WbApiSnapshot(
                client_id=fact.client_id,
                seller_account_id=fact.seller_account_id,
                organization_id=fact.organization_id,
                period_start=fact.fact_date,
                period_end=fact.fact_date,
                source_endpoint="marketplace_finance_daily_facts",
                loaded_at=loaded_at,
                wb_document_id=(
                    f"{fact.marketplace_report_id}:{fact.fact_date.isoformat()}"
                ),
                wb_report_id=fact.marketplace_report_id,
                report_type=report_type,
                nm_id=fact.nm_id,
                vendor_code=fact.vendor_code,
                barcode=fact.barcode,
                sales_model=sales_model,
                operation_type=fact.operation_group or "unknown",
                quantity=fact.quantity,
                net_revenue=fact.net_revenue,
                wb_commission=fact.wb_commission,
                logistics=fact.logistics,
                storage=fact.storage,
                acceptance=fact.acceptance,
                wb_promotion=fact.marketplace_promotion,
                penalties_and_holdbacks=fact.penalties_and_holdbacks,
                acquiring=fact.acquiring,
                vat_input_from_wb=fact.vat_input_from_marketplace,
                advertising=Decimal("0"),
                raw_payload_hash=fact.source_hash_digest,
                is_partial_source=fact.is_partial_source,
                source_row_count=max(1, int(fact.source_row_count)),
                preallocated_finance=True,
                precomputed_cogs=fact.cogs,
                precomputed_gross_profit=fact.gross_profit,
                precomputed_vat_input_from_1c=fact.vat_input_from_1c,
                precomputed_accounting_service_input_vat=(
                    fact.accounting_service_input_vat
                ),
                precomputed_spp_discount=fact.spp_discount,
            )
        )
    return snapshots


def _confirmed_input_vat_org_ids(
    onec_dir: Path,
    *,
    period_start: date,
    period_end: date,
) -> set[str]:
    """Return organizations with active purchase-book records in report scope."""
    result: set[str] = set()
    for row in load_onec_rows(onec_dir, "vat_purchase_book"):
        active = str(row.get("Active", "true")).strip().casefold()
        if active in {"false", "0", "no", "нет"}:
            continue
        organization_id = str(row.get("Организация_Key") or "").strip()
        try:
            vat_amount = Decimal(str(row.get("НДС") or "0"))
        except (ArithmeticError, ValueError):
            continue
        if vat_amount == 0:
            continue
        period_text = str(row.get("Period") or "")[:10]
        try:
            period = date.fromisoformat(period_text)
        except ValueError:
            continue
        if organization_id and period_start <= period <= period_end:
            result.add(organization_id)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--tenant-id", default="shumeyko")
    parser.add_argument("--tenant-name", default="Шумейко и Партнеры")
    parser.add_argument("--report-id", required=True)
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
    parser.add_argument("--onec-services-dir", type=Path, default=None)
    parser.add_argument("--wb-report-list-dir", type=Path, default=None)
    parser.add_argument("--wb-paid-storage-dir", type=Path, default=None)
    parser.add_argument("--wb-promotion-stats-dir", type=Path, default=None)
    parser.add_argument("--wb-stock-history-dir", type=Path, default=None)
    parser.add_argument(
        "--allow-latest-stock-history-fallback",
        action="store_true",
        help=(
            "Allow an explicit manual fallback to the latest local WB stock-history "
            "snapshot. Strict report-period coverage is still required."
        ),
    )
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
        choices=["files", "files-stream", "daily-facts", "postgres"],
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
        choices=["auto", "Себестоимость", "СебестоимостьБезНДС"],
        default="auto",
    )
    parser.add_argument("--source-refresh-run-id", default="")
    parser.add_argument(
        "--stock-history-refresh-run-id",
        default="",
        help=(
            "Registered source refresh containing the exact wb_stock_history_daily "
            "snapshot passed via --wb-stock-history-dir."
        ),
    )
    parser.add_argument(
        "--tax-system",
        default="",
        help="Audited explicit tax system for every mapped 1C organization.",
    )
    parser.add_argument("--vat-rate", type=Decimal, default=None)
    parser.add_argument(
        "--vat-mode",
        choices=[item.value for item in VatMode],
        default=VatMode.INCLUDED.value,
    )
    parser.add_argument(
        "--vat-deduction-mode",
        choices=[item.value for item in VatDeductionMode],
        default=VatDeductionMode.UNKNOWN.value,
    )
    parser.add_argument("--revenue-tax-rate", type=Decimal, default=Decimal("0"))
    parser.add_argument("--income-tax-kind", default="ip_ndfl_progressive")
    parser.add_argument(
        "--tax-profile-source",
        default="accepted_manual_profile",
        help="Safe audit label stored in report rows; never put a secret here.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "reports" / "db_first"
    )
    parser.add_argument("--excel-path", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--export-all", action="store_true")
    publication_group = parser.add_mutually_exclusive_group()
    publication_group.add_argument(
        "--publish",
        action="store_true",
        help=(
            "Publish only after the staff draft has passed the financial gate; "
            "the safe default is draft-only."
        ),
    )
    publication_group.add_argument(
        "--draft-only",
        action="store_true",
        help="Compatibility flag; draft-only is already the safe default.",
    )
    return parser.parse_args()


def _validate_lineage_args(args: argparse.Namespace) -> None:
    if args.stock_history_refresh_run_id and args.wb_stock_history_dir is None:
        raise ValueError(
            "--stock-history-refresh-run-id requires --wb-stock-history-dir"
        )
    if (
        args.source_snapshot_set_id
        and not args.source_refresh_run_id
        and not args.stock_history_refresh_run_id
    ):
        raise ValueError(
            "--source-snapshot-set-id requires --source-refresh-run-id or "
            "--stock-history-refresh-run-id; refusing an unlinked report snapshot"
        )


def _tax_profiles_for_rebuild(
    args: argparse.Namespace,
    account_mapping: list[AccountOrgMapping],
    *,
    source_profiles: list[TaxProfile],
) -> list[TaxProfile]:
    tax_system = str(getattr(args, "tax_system", "") or "").strip()
    if not tax_system:
        return source_profiles
    vat_rate = getattr(args, "vat_rate", None)
    if vat_rate is None:
        raise ValueError("--vat-rate is required with --tax-system")
    vat_mode = VatMode(str(getattr(args, "vat_mode", VatMode.INCLUDED.value)))
    vat_deduction_mode = VatDeductionMode(
        str(
            getattr(
                args,
                "vat_deduction_mode",
                VatDeductionMode.UNKNOWN.value,
            )
        )
    )
    if vat_deduction_mode is VatDeductionMode.UNKNOWN:
        raise ValueError("--vat-deduction-mode must be confirmed with --tax-system")
    revenue_tax_rate = Decimal(str(getattr(args, "revenue_tax_rate", 0)))
    income_tax_kind = str(
        getattr(args, "income_tax_kind", "ip_ndfl_progressive") or ""
    ).strip()
    source = str(
        getattr(args, "tax_profile_source", "accepted_manual_profile") or ""
    ).strip()
    if not source:
        raise ValueError("--tax-profile-source must not be empty")
    organization_ids = sorted({item.organization_id for item in account_mapping})
    return [
        TaxProfile(
            client_id=args.client_id,
            organization_id=organization_id,
            tax_system=tax_system,
            vat_rate=vat_rate,
            vat_mode=vat_mode,
            vat_deduction_mode=vat_deduction_mode,
            revenue_tax_rate=revenue_tax_rate,
            income_tax_kind=income_tax_kind,
            source=source,
        )
        for organization_id in organization_ids
    ]


def _sales_cost_amount_field(value: str, *, tax_profiles: list[object]) -> str:
    if value != "auto":
        return value
    if any(
        "осно" in str(getattr(profile, "tax_system", "")).casefold()
        or "общ" in str(getattr(profile, "tax_system", "")).casefold()
        for profile in tax_profiles
    ):
        return "СебестоимостьБезНДС"
    return "Себестоимость"


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
        and row.get("lossClass")
        not in {"Нужна проверка данных", "Штрафной инцидент без продаж"}
    ]
    if wrong:
        raise ValueError(
            "ReportMarts validation failed: unreliable rows look reliable."
        )
    coverage = payload.get("lostSalesCoverage") or {}
    if coverage.get("calculationContextVersion") == "lost-sales-filter-v1":
        lost_sales = payload.get("lostSales") or []
        missing_context = [
            item.get("id")
            for item in lost_sales
            if not isinstance(item.get("calculationContext"), dict)
            or item["calculationContext"].get("version") != "lost-sales-filter-v1"
        ]
        if missing_context:
            raise ValueError(
                "ReportMarts validation failed: lost-sales calculation context "
                "is missing."
            )


if __name__ == "__main__":
    raise SystemExit(main())
