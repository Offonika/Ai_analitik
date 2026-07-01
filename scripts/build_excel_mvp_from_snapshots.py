from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.contracts import AccountOrgMapping
from wb_unit_economics.excel import build_excel_report
from wb_unit_economics.mapping import (
    build_sku_mapping_from_articles,
    build_sku_mapping_from_onec_marketplace_files,
    has_onec_marketplace_mapping_files,
    load_onec_rows,
    load_wb_card_flat_rows,
)
from wb_unit_economics.onec_cost import (
    attach_document_metadata_to_documents,
    attach_settlement_totals_to_documents,
    extract_gross_profit_document_rows,
    load_marketplace_document_metadata,
    load_marketplace_settlement_totals,
    load_provisional_cost_snapshots,
    load_sales_register_cost_snapshots,
    load_sales_register_rows,
)
from wb_unit_economics.onec_opiu import load_onec_opiu_summary
from wb_unit_economics.onec_services import load_onec_marketplace_service_rows
from wb_unit_economics.postgres_finance import (
    default_postgres_target,
    load_cost_snapshots_from_postgres,
    load_sku_mappings_from_postgres,
    load_wb_finance_snapshots_from_postgres,
)
from wb_unit_economics.wb_expenses import load_wb_expense_allocation_bases
from wb_unit_economics.wb_finance import (
    load_wb_finance_snapshots,
    load_wb_sales_report_summary_rows,
)

CLIENT_ID = "shumeyko-partners"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class ExcelMvpBuildResult:
    output_path: Path
    wb_rows: int
    sku_mappings: int
    mapping_source: str
    sales_register_source: str
    cost_candidates: int
    wb_weekly_summary_rows: int
    marketplace_service_rows: int
    onec_opiu_source: str
    wb_expense_allocation_rows: int
    wb_stock_history_source: str
    onec_stock_source: str
    report_rows: int
    report_status: str


def main() -> int:
    args = _parse_args()
    result = build_excel_mvp_from_args(args)
    print(f"Excel MVP: {result.output_path}")
    print(f"WB rows: {result.wb_rows}")
    print(f"SKU mappings: {result.sku_mappings}")
    print(f"Mapping source: {result.mapping_source}")
    print(f"1C sales register source: {result.sales_register_source}")
    print(f"1C cost candidates: {result.cost_candidates}")
    print(f"WB weekly summary rows: {result.wb_weekly_summary_rows}")
    print(f"1C marketplace service rows: {result.marketplace_service_rows}")
    print(f"1C OPIU source: {result.onec_opiu_source}")
    print(f"WB expense allocation base rows: {result.wb_expense_allocation_rows}")
    print(f"WB stock history source: {result.wb_stock_history_source}")
    print(f"1C stock source: {result.onec_stock_source}")
    print(f"Report rows: {result.report_rows}")
    print(f"Report status: {result.report_status}")
    return 0


def build_excel_mvp_from_args(args: argparse.Namespace) -> ExcelMvpBuildResult:
    wb_finance_dir = args.wb_finance_dir or _latest_dir(Path("data/wb_finance"))
    wb_cards_dir = args.wb_cards_dir or _latest_dir(Path("data/wb_product_cards"))
    onec_dir = args.onec_dir or _latest_onec_reference_dir(Path("data/onec_samples"))
    marketplace_mapping_dir = args.onec_marketplace_mapping_dir
    sales_register_dir = args.sales_register_dir or _latest_sales_register_dir(
        Path("data/onec_gross_profit_samples")
    )
    wb_stock_history_dir = args.wb_stock_history_dir or _optional_latest_dir(
        Path("data/wb_stock_history_daily")
    )
    onec_stock_dir = (
        args.onec_stock_dir
        or _latest_onec_stock_dir(Path("data/onec_samples"))
        or onec_dir
    )
    onec_opiu_dir = args.onec_opiu_dir or _latest_onec_opiu_dir(
        Path("data/onec_gross_profit_samples")
    )
    onec_services_dir = args.onec_services_dir or _latest_onec_services_dir(
        Path("data/onec_marketplace_service_samples")
    )
    output_path = args.output or _default_output_path()
    report_period_start = args.report_period_start or _manifest_period_date(
        wb_finance_dir, "period_start", date(2026, 3, 1)
    )
    report_period_end = args.report_period_end or _manifest_period_date(
        wb_finance_dir, "period_end", date(2026, 6, 17)
    )

    account_mapping = _account_org_mapping(args.client_id, wb_finance_dir, onec_dir)
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
    else:
        wb_snapshots = load_wb_finance_snapshots(
            wb_finance_dir,
            client_id=args.client_id,
            account_org_mapping=account_mapping,
        )
    if not wb_snapshots:
        print(
            "No WB Finance rows found. Check data/wb_finance manifest.",
            file=sys.stderr,
        )
        return 1

    if args.mapping_source == "postgres":
        sku_mappings = load_sku_mappings_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.mapping_snapshot_id,
        )
        mapping_source = "local Postgres sku_mapping_snapshot"
    else:
        onec_barcodes = load_onec_rows(onec_dir, "barcodes")
        onec_nomenclature = load_onec_rows(onec_dir, "nomenclature")
        if has_onec_marketplace_mapping_files(marketplace_mapping_dir):
            sku_mappings = build_sku_mapping_from_onec_marketplace_files(
                client_id=args.client_id,
                mapping_dir=marketplace_mapping_dir,
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
    if args.cost_source == "postgres":
        cost_snapshots = load_cost_snapshots_from_postgres(
            target=postgres_target,
            client_id=args.client_id,
            snapshot_id=args.cost_snapshot_id,
        )
        cost_note = (
            "Себестоимость 1С загружена из локального Postgres слоя "
            "onec_cost_snapshot; распределенные допрасходы уже включены и "
            "отдельно не прибавляются."
        )
    else:
        if sales_register_dir:
            cost_snapshots = load_sales_register_cost_snapshots(
                sales_register_dir,
                client_id=args.client_id,
                reference_dir=onec_dir,
                amount_field=args.sales_cost_amount_field,
                marketplace_counterparties_only=True,
            )
            cost_note = (
                "Себестоимость 1С: средневзвешенная по строкам "
                "ОтчетКомиссионера РВБ/WB в регистре Продажи "
                f"({args.sales_cost_amount_field}, {sales_register_dir.name}); "
                "распределенные допрасходы уже "
                "включены и отдельно не прибавляются."
            )
        else:
            cost_snapshots = load_provisional_cost_snapshots(
                onec_dir,
                client_id=args.client_id,
                amount_field=args.cost_amount_field,
            )
            cost_note = (
                "Себестоимость 1С provisional: фиксированные приходные строки "
                "регистра Запасы."
            )
    gross_profit_rows = _gross_profit_document_rows(
        args.client_id,
        sales_register_dir,
    )
    onec_opiu_summary = load_onec_opiu_summary(
        onec_opiu_dir,
        period_start=report_period_start,
        period_end=report_period_end,
        config_path=args.onec_opiu_config,
    )
    wb_summary_rows = _wb_sales_report_summary_rows(
        args.client_id,
        args.wb_report_list_dir,
    )
    marketplace_service_rows = _onec_marketplace_service_rows(
        args.client_id,
        onec_services_dir,
        reference_dir=onec_dir,
        sales_register_dir=sales_register_dir,
    )
    expense_allocation_bases = load_wb_expense_allocation_bases(
        client_id=args.client_id,
        paid_storage_dir=args.wb_paid_storage_dir,
        promotion_stats_dir=args.wb_promotion_stats_dir,
    )
    report = build_unit_economics_report(
        client_id=args.client_id,
        wb_snapshots=wb_snapshots,
        cost_snapshots=cost_snapshots,
        sku_mappings=sku_mappings,
        account_org_mapping=account_mapping,
        wb_sales_report_summary_rows=wb_summary_rows,
        expense_allocation_bases=expense_allocation_bases,
        generated_at=datetime.now(tz=MOSCOW_TZ),
        report_period_start=report_period_start,
        report_period_end=report_period_end,
    )
    notes = [
        _wb_source_note(args.wb_finance_source, args.postgres_snapshot_id),
        *_wb_finance_manifest_notes(wb_finance_dir, account_labels),
        cost_note,
        f"Маппинг: {mapping_source}.",
        (
            "Основной расчет использует Себестоимость; СебестоимостьБезНДС "
            "доступна только для сверки."
        ),
        (
            "Сверка с валовой прибылью 1С требует, чтобы в sales_register "
            "попали все движения периода: отчеты комиссионера и расходные "
            "накладные по выкупам WB."
        ),
        (
            "WB Продвижение включается отдельной статьей из deduction/"
            "deductionSum и сверяется с 1С УПД."
        ),
        (
            "Хранение и WB Продвижение в товарных строках распределяются по "
            "долям отдельного API WB, если он загружен, иначе по детализации "
            "Finance; итог приводится к контрольной сумме недельного "
            "финансового отчета WB."
        ),
        (
            "НДС 5% выделяется из выручки товара по ставке 5/105; УСН 1% "
            "распределяется по выручке. Строки ОПиУ/1С используются для "
            "сверки контрольных сумм."
        ),
        (
            "СПП берется из WB sales-reports/list cashbackDiscountSum; "
            "контрольная выручка для 1С/ОПиУ — выручка после СПП."
        ),
        "Связка WB кабинет -> организация 1С требует подтверждения на пилоте.",
        (
            "Отдельный API рекламы используется только как база распределения "
            "WB Продвижение, если загружен; итоговая сумма берется из недельного "
            "финансового отчета WB."
        ),
    ]
    build_excel_report(
        report,
        output_path,
        cost_snapshots=cost_snapshots,
        sku_mappings=sku_mappings,
        source_notes=notes,
        account_labels=account_labels,
        organization_labels=organization_labels,
        onec_gross_profit_rows=gross_profit_rows,
        wb_sales_report_summary_rows=wb_summary_rows,
        onec_marketplace_service_rows=marketplace_service_rows,
        onec_opiu_summary=onec_opiu_summary,
        stock_history_dir=wb_stock_history_dir,
        onec_stock_dir=onec_stock_dir,
    )
    return ExcelMvpBuildResult(
        output_path=output_path,
        wb_rows=len(wb_snapshots),
        sku_mappings=len(sku_mappings),
        mapping_source=mapping_source,
        sales_register_source=str(sales_register_dir or "not found"),
        cost_candidates=len(cost_snapshots),
        wb_weekly_summary_rows=len(wb_summary_rows),
        marketplace_service_rows=len(marketplace_service_rows),
        onec_opiu_source=(
            onec_opiu_summary.source_label if onec_opiu_summary else "not found"
        ),
        wb_expense_allocation_rows=len(expense_allocation_bases),
        wb_stock_history_source=str(wb_stock_history_dir or "not found"),
        onec_stock_source=str(onec_stock_dir or "not found"),
        report_rows=len(report.rows),
        report_status=report.status.value,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Shumeyko Excel MVP from local raw snapshots."
    )
    parser.add_argument("--client-id", default=CLIENT_ID)
    parser.add_argument("--wb-finance-dir", type=Path, default=None)
    parser.add_argument(
        "--wb-finance-source",
        choices=["files", "postgres"],
        default="files",
        help="Read WB Finance facts from local raw files or local Postgres.",
    )
    parser.add_argument("--postgres-db-name", default="shumeyko_wb_unit_economics")
    parser.add_argument("--postgres-host", default="")
    parser.add_argument("--postgres-port", type=int, default=55433)
    parser.add_argument("--postgres-user", default="")
    parser.add_argument("--postgres-snapshot-id", default=None)
    parser.add_argument(
        "--mapping-source",
        choices=["files", "postgres"],
        default="files",
        help="Read SKU mapping from local files or local Postgres.",
    )
    parser.add_argument("--mapping-snapshot-id", default=None)
    parser.add_argument(
        "--cost-source",
        choices=["files", "postgres"],
        default="files",
        help="Read 1C cost snapshots from local files or local Postgres.",
    )
    parser.add_argument("--cost-snapshot-id", default=None)
    parser.add_argument("--wb-cards-dir", type=Path, default=None)
    parser.add_argument("--onec-dir", type=Path, default=None)
    parser.add_argument(
        "--onec-marketplace-mapping-dir",
        type=Path,
        default=Path("data/onec_marketplace_mapping"),
        help="Directory with 1C marketplace product matching TXT exports.",
    )
    parser.add_argument("--sales-register-dir", type=Path, default=None)
    parser.add_argument("--wb-report-list-dir", type=Path, default=None)
    parser.add_argument("--wb-paid-storage-dir", type=Path, default=None)
    parser.add_argument("--wb-promotion-stats-dir", type=Path, default=None)
    parser.add_argument("--wb-stock-history-dir", type=Path, default=None)
    parser.add_argument("--onec-services-dir", type=Path, default=None)
    parser.add_argument("--onec-stock-dir", type=Path, default=None)
    parser.add_argument("--onec-opiu-dir", type=Path, default=None)
    parser.add_argument(
        "--onec-opiu-config",
        type=Path,
        default=None,
        help="Non-secret JSON config for 1C OPIU account and unit GUID mapping.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--report-period-start",
        type=date.fromisoformat,
        default=None,
        help=(
            "Business report_period start shown in Excel and used for filters. "
            "If omitted, local rebuild falls back to WB Finance manifest "
            "source coverage for backward compatibility."
        ),
    )
    parser.add_argument(
        "--report-period-end",
        type=date.fromisoformat,
        default=None,
        help=(
            "Business report_period end shown in Excel and used for status. "
            "If omitted, local rebuild falls back to WB Finance manifest "
            "source coverage for backward compatibility."
        ),
    )
    parser.add_argument(
        "--cost-amount-field",
        default="Сумма",
        choices=["Сумма", "СуммаБезНДС"],
        help="1C amount field for provisional unit cost candidates.",
    )
    parser.add_argument(
        "--sales-cost-amount-field",
        default="Себестоимость",
        choices=["Себестоимость", "СебестоимостьБезНДС"],
        help="1C sales register amount field for unit COGS candidates.",
    )
    return parser.parse_args()


def _wb_source_note(source: str, snapshot_id: str | None) -> str:
    if source == "postgres":
        suffix = f" snapshot {snapshot_id}" if snapshot_id else ""
        return (
            "WB факт загружен из локального Postgres слоя "
            f"wb_finance_detail_raw{suffix}."
        )
    return "WB факт загружен из нового Finance sales-reports/detailed endpoint."


def _gross_profit_document_rows(client_id: str, sales_register_dir: Path | None):
    if sales_register_dir is None:
        return []
    sales_register_path = sales_register_dir / "sales_register.raw.json"
    if not sales_register_path.exists():
        return []
    rows = extract_gross_profit_document_rows(
        client_id=client_id,
        sales_rows=load_sales_register_rows(sales_register_dir),
        marketplace_counterparties_only=True,
    )
    settlement_totals = load_marketplace_settlement_totals(sales_register_dir)
    if settlement_totals:
        rows = attach_settlement_totals_to_documents(rows, settlement_totals)
    document_metadata = load_marketplace_document_metadata(sales_register_dir)
    if document_metadata:
        rows = attach_document_metadata_to_documents(rows, document_metadata)
    return rows


def _wb_sales_report_summary_rows(client_id: str, path: Path | None):
    if path is None or not (path / "manifest.json").exists():
        return []
    return load_wb_sales_report_summary_rows(path, client_id=client_id)


def _onec_marketplace_service_rows(
    client_id: str,
    path: Path | None,
    *,
    reference_dir: Path,
    sales_register_dir: Path | None,
):
    if path is None:
        return []
    return load_onec_marketplace_service_rows(
        path,
        client_id=client_id,
        reference_dir=reference_dir,
        sales_register_dir=sales_register_dir,
    )


def _account_org_mapping(
    client_id: str,
    wb_finance_dir: Path,
    onec_dir: Path,
) -> list[AccountOrgMapping]:
    seller_accounts = _seller_accounts_from_manifest(wb_finance_dir)
    organizations = _organizations_from_sample(onec_dir)
    result: list[AccountOrgMapping] = []
    used_org_indexes: set[int] = set()
    for index, account in enumerate(seller_accounts):
        fallback_org_id = f"1C_ORG_{index + 1}"
        organization_index, organization = _best_organization_for_account(
            account,
            organizations,
            used_org_indexes,
            fallback_index=index,
        )
        if organization_index is not None:
            used_org_indexes.add(organization_index)
        organization_id = str(organization.get("Ref_Key") or fallback_org_id)
        organization_name = str(
            organization.get("Description")
            or organization.get("НаименованиеСокращенное")
            or organization_id
        )
        result.append(
            AccountOrgMapping(
                client_id=client_id,
                seller_account_id=account["seller_account_id"],
                organization_id=organization_id,
                seller_account_name=account["account_name"],
                organization_name=organization_name,
            )
        )
    return result


def _best_organization_for_account(
    account: dict[str, str],
    organizations: list[dict[str, Any]],
    used_org_indexes: set[int],
    *,
    fallback_index: int,
) -> tuple[int | None, dict[str, Any]]:
    account_name = _normalize_match_text(account.get("account_name", ""))
    best_index: int | None = None
    best_score = 0
    for index, organization in enumerate(organizations):
        if index in used_org_indexes:
            continue
        organization_name = _normalize_match_text(
            str(
                organization.get("Description")
                or organization.get("НаименованиеСокращенное")
                or ""
            )
        )
        score = _name_match_score(account_name, organization_name)
        if score > best_score:
            best_index = index
            best_score = score
    if best_index is not None and best_score > 0:
        return best_index, organizations[best_index]
    if fallback_index < len(organizations) and fallback_index not in used_org_indexes:
        return fallback_index, organizations[fallback_index]
    for index, organization in enumerate(organizations):
        if index not in used_org_indexes:
            return index, organization
    return None, {}


def _name_match_score(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if left in right or right in left:
        return min(len(left), len(right))
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    return sum(len(token) for token in left_tokens & right_tokens if len(token) >= 3)


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zа-яё]+", " ", value.lower())).strip()


def _seller_accounts_from_manifest(path: Path) -> list[dict[str, str]]:
    manifest = _read_json_object(path / "manifest.json")
    accounts: dict[str, str] = {}
    for row in manifest.get("results", []):
        if not isinstance(row, dict):
            continue
        seller_account_id = str(row.get("seller_account_id") or "")
        if not seller_account_id:
            continue
        accounts.setdefault(seller_account_id, str(row.get("account_name") or ""))
    return [
        {"seller_account_id": account_id, "account_name": name or account_id}
        for account_id, name in sorted(accounts.items())
    ]


def _wb_finance_manifest_notes(
    wb_finance_dir: Path,
    account_labels: dict[str, str],
) -> list[str]:
    manifest_path = wb_finance_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = _read_json_object(manifest_path)
    notes: list[str] = []
    for row in manifest.get("results", []):
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "")
        if not status or status in {"ok", "no_data"}:
            continue
        seller_account_id = str(row.get("seller_account_id") or "")
        account_name = str(row.get("account_name") or seller_account_id)
        account_label = account_labels.get(seller_account_id) or account_name
        page_index = row.get("page_index")
        error = str(row.get("error") or row.get("error_type") or status)
        notes.append(
            f"WB кабинет {account_label} ({account_name}) загружен не полностью: "
            f"страница {page_index}, статус {status}, ошибка {error}."
        )
    return notes


def _organizations_from_sample(path: Path) -> list[dict[str, Any]]:
    try:
        return load_onec_rows(path, "organizations")
    except FileNotFoundError:
        return []


def _latest_dir(base: Path) -> Path:
    candidates = [item for item in base.iterdir() if item.is_dir()]
    if not candidates:
        raise SystemExit(f"No snapshot directories found under {base}")
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _optional_latest_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [item for item in base.iterdir() if item.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _latest_sales_register_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [
        item
        for item in base.iterdir()
        if item.is_dir() and (item / "sales_register.raw.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _latest_onec_reference_dir(base: Path) -> Path:
    required_files = (
        "barcodes.raw.json",
        "nomenclature.raw.json",
        "organizations.raw.json",
    )
    candidates = [
        item
        for item in base.iterdir()
        if item.is_dir()
        and all((item / file_name).exists() for file_name in required_files)
    ]
    if not candidates:
        raise SystemExit(f"No full 1C sample directories found under {base}")
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _latest_onec_stock_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [
        item
        for item in base.iterdir()
        if item.is_dir() and (item / "stock_by_warehouse.raw.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _latest_onec_opiu_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [
        item
        for item in base.iterdir()
        if item.is_dir() and (item / "income_expense_register.raw.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _latest_onec_services_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    required_files = (
        "supplier_receipts.raw.json",
        "supplier_receipt_expenses.raw.json",
    )
    candidates = [
        item
        for item in base.iterdir()
        if item.is_dir()
        and all((item / file_name).exists() for file_name in required_files)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _default_output_path() -> Path:
    return Path("reports") / "shumeyko_wb_excel_mvp.xlsx"


def _manifest_period_date(path: Path, key: str, fallback: date) -> date:
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return fallback
    value = _read_json_object(manifest_path).get(key)
    if not value:
        return fallback
    return date.fromisoformat(str(value))


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


if __name__ == "__main__":
    sys.exit(main())
