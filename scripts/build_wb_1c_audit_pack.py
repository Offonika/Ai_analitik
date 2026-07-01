from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import xlsxwriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_unit_economics.wb_finance import load_wb_sales_report_summary_rows

CLIENT_ID = "shumeyko-partners"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
ZERO = Decimal("0")


@dataclass(frozen=True)
class WbReportReconciliationControl:
    report_id: str
    seller_account_id: str
    detail_retail_amount: Decimal
    detail_cashback_discount: Decimal
    summary_retail_amount_sum: Decimal | None
    summary_cashback_discount_sum: Decimal | None
    summary_retail_minus_cashback: Decimal | None
    detail_row_count: int
    summary_found: bool


def main() -> int:
    args = _parse_args()
    markdown_path, workbook_path, control = build_audit_pack_from_args(args)
    print(f"Audit Markdown: {markdown_path}")
    print(f"Audit workbook: {workbook_path}")
    print(f"Detail rows: {control.detail_row_count}")
    print(f"Summary found: {control.summary_found}")
    return 0 if control.summary_found and control.detail_row_count > 0 else 1


def build_audit_pack_from_args(
    args: argparse.Namespace,
) -> tuple[Path, Path, WbReportReconciliationControl]:
    wb_finance_dir = args.wb_finance_dir or _latest_dir(Path("data/wb_finance"))
    wb_report_list_dir = args.wb_report_list_dir or _latest_dir(
        Path("data/wb_sales_report_list")
    )
    output_path = args.output or _default_output_path(args.report_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    control = build_report_reconciliation_control(
        report_id=args.report_id,
        seller_account_id=args.seller_account,
        wb_finance_dir=wb_finance_dir,
        wb_report_list_dir=wb_report_list_dir,
        period_start=args.period_start,
        period_end=args.period_end,
    )
    markdown_path = output_path.with_suffix(".md")
    workbook_path = output_path.with_suffix(".xlsx")
    markdown_path.write_text(
        _render_markdown(
            control,
            period_start=args.period_start,
            period_end=args.period_end,
            onec_dir=args.onec_dir,
        ),
        encoding="utf-8",
    )
    _write_workbook(
        workbook_path,
        control,
        period_start=args.period_start,
        period_end=args.period_end,
        onec_dir=args.onec_dir,
    )
    return markdown_path, workbook_path, control


def build_report_reconciliation_control(
    *,
    report_id: str,
    seller_account_id: str,
    wb_finance_dir: Path,
    wb_report_list_dir: Path,
    period_start: date,
    period_end: date,
) -> WbReportReconciliationControl:
    detail_rows = [
        row
        for row in _load_wb_finance_raw_rows(wb_finance_dir, seller_account_id)
        if str(_first(row, "reportId", "report_id") or "") == report_id
        and period_start <= _row_date(row, "dateFrom", "rrDate") <= period_end
    ]
    summary_rows = (
        load_wb_sales_report_summary_rows(wb_report_list_dir, client_id=CLIENT_ID)
        if (wb_report_list_dir / "manifest.json").exists()
        else []
    )
    summary = next(
        (
            row
            for row in summary_rows
            if row.report_id == report_id
            and row.seller_account_id == seller_account_id
            and row.date_from <= period_end
            and row.date_to >= period_start
        ),
        None,
    )
    return WbReportReconciliationControl(
        report_id=report_id,
        seller_account_id=seller_account_id,
        detail_retail_amount=_sum_decimal(detail_rows, "retailAmount"),
        detail_cashback_discount=_sum_decimal(detail_rows, "cashbackDiscount"),
        summary_retail_amount_sum=summary.retail_amount_sum if summary else None,
        summary_cashback_discount_sum=(
            summary.cashback_discount_sum if summary else None
        ),
        summary_retail_minus_cashback=(
            summary.retail_amount_sum - summary.cashback_discount_sum
            if summary
            else None
        ),
        detail_row_count=len(detail_rows),
        summary_found=summary is not None,
    )


def _render_markdown(
    control: WbReportReconciliationControl,
    *,
    period_start: date,
    period_end: date,
    onec_dir: Path | None,
) -> str:
    generated_at = datetime.now(tz=MOSCOW_TZ).isoformat(timespec="seconds")
    rows = _control_rows(control)
    table = "\n".join(
        f"| {label} | {value} |"
        for label, value in rows
    )
    onec_status = str(onec_dir) if onec_dir else "optional: not provided"
    return f"""# WB/1C audit pack

Generated at: {generated_at}

Period: {period_start} - {period_end}

Seller account: {control.seller_account_id}

Report ID: {control.report_id}

1C source: {onec_status}

Raw WB detail rows are not embedded in this Markdown. Use local snapshots in `data/`.

| Control | Value |
| --- | ---: |
{table}

Payout status: Нужен источник выплаты 1С. `forPaySum` не сравнивается с оборотом
взаиморасчетов 1С как с выплатой до согласования отдельного read-only источника.
"""


def _write_workbook(
    path: Path,
    control: WbReportReconciliationControl,
    *,
    period_start: date,
    period_end: date,
    onec_dir: Path | None,
) -> None:
    with xlsxwriter.Workbook(path) as workbook:
        money_fmt = workbook.add_format({"num_format": "#,##0.00"})
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#E7EEF8"})
        sheet = workbook.add_worksheet("Контроль reportId")
        sheet.write(0, 0, "WB/1C audit pack", header_fmt)
        sheet.write(1, 0, "Период")
        sheet.write(1, 1, f"{period_start} - {period_end}")
        sheet.write(2, 0, "Кабинет WB")
        sheet.write(2, 1, control.seller_account_id)
        sheet.write(3, 0, "reportId")
        sheet.write(3, 1, control.report_id)
        sheet.write(4, 0, "1С источник")
        sheet.write(4, 1, str(onec_dir) if onec_dir else "optional: not provided")
        sheet.write_row(6, 0, ["Контроль", "Значение"], header_fmt)
        for index, (label, value) in enumerate(_control_rows(control), start=7):
            sheet.write(index, 0, label)
            if isinstance(value, Decimal):
                sheet.write_number(index, 1, float(value), money_fmt)
            else:
                sheet.write(index, 1, value)
        sheet.write(14, 0, "Статус выплаты")
        sheet.write(14, 1, "Нужен источник выплаты 1С")
        sheet.set_column(0, 0, 42)
        sheet.set_column(1, 1, 28)


def _control_rows(
    control: WbReportReconciliationControl,
) -> list[tuple[str, Decimal | str | int]]:
    return [
        ("sum(detail.retailAmount)", control.detail_retail_amount),
        ("sum(detail.cashbackDiscount)", control.detail_cashback_discount),
        (
            "summary.retailAmountSum",
            _optional_decimal(control.summary_retail_amount_sum),
        ),
        (
            "summary.cashbackDiscountSum",
            _optional_decimal(control.summary_cashback_discount_sum),
        ),
        (
            "summary.retailAmountSum - cashbackDiscountSum",
            _optional_decimal(control.summary_retail_minus_cashback),
        ),
        ("detail row count", control.detail_row_count),
        ("summary row found", "yes" if control.summary_found else "no"),
    ]


def _load_wb_finance_raw_rows(
    path: Path,
    seller_account_id: str,
) -> list[dict[str, Any]]:
    manifest = _read_json_object(path / "manifest.json")
    rows: list[dict[str, Any]] = []
    for result in manifest.get("results", []):
        if not isinstance(result, dict):
            continue
        if str(result.get("seller_account_id") or "") != seller_account_id:
            continue
        if str(result.get("status") or "") not in {"", "ok"}:
            continue
        output_file = str(result.get("output_file") or "")
        if not output_file:
            continue
        rows.extend(_read_json_list(path / output_file))
    return rows


def _sum_decimal(rows: list[dict[str, Any]], key: str) -> Decimal:
    return sum((_decimal(row.get(key)) for row in rows), ZERO)


def _optional_decimal(value: Decimal | None) -> Decimal | str:
    return value if value is not None else "not found"


def _first(row: dict[str, Any], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _row_date(row: dict[str, Any], *keys: str) -> date:
    value = str(_first(row, *keys) or "")[:10]
    if not value:
        return date.min
    return date.fromisoformat(value)


def _decimal(value: object) -> Decimal:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


def _read_json_object(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _latest_dir(root: Path) -> Path:
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No snapshot directories in {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _default_output_path(report_id: str) -> Path:
    timestamp = datetime.now(tz=MOSCOW_TZ).strftime("%Y%m%dT%H%M%S")
    return Path("reports") / f"wb_1c_audit_{report_id}_{timestamp}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a proof-oriented WB/1C audit pack for one reportId."
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--seller-account", required=True)
    parser.add_argument("--onec-dir", type=Path, default=None)
    parser.add_argument("--wb-finance-dir", type=Path, default=None)
    parser.add_argument("--wb-report-list-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
