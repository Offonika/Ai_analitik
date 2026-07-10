#!/usr/bin/env python3
"""Build a safe draft summary for input VAT reconciliation without publishing."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import build_excel_mvp_from_snapshots as excel_mvp
from scripts import rebuild_report_from_sources as rebuild
from wb_unit_economics.calculation import (
    _service_input_vat_from_gross,
    _service_rows_in_report_period,
    _vat_reconciliation_category,
)
from wb_unit_economics.contracts import UnitEconomicsReport

MOSCOW_TZ = excel_mvp.MOSCOW_TZ
ZERO = Decimal("0")
DIAGNOSTIC_DIFF_THRESHOLD = Decimal("1000")


def main() -> int:
    args = parse_args()
    summary, markdown_path, json_path = build_tax_input_reconciliation_draft(args)
    totals = summary["totals"]
    print(f"VAT draft Markdown: {markdown_path}")
    print(f"VAT draft JSON: {json_path}")
    print(f"WB rows: {summary['wbRows']}")
    print(f"Unit rows: {summary['unitRows']}")
    print(f"Tax reconciliation rows: {summary['taxReconciliationRows']}")
    print(f"Statuses: {summary['statusCounts']}")
    print(f"VAT input WB: {totals['vatInputFromWb']}")
    print(f"VAT input 1C: {totals['vatInputFrom1c']}")
    print(f"VAT input difference: {totals['vatInputDifference']}")
    return 0


def build_tax_input_reconciliation_draft(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Path, Path]:
    build = rebuild.build_db_first_payload(args)
    summary = build_tax_input_summary(build["payload"], wb_rows=build["wb_rows"])
    summary["discrepancyReasons"] = build_discrepancy_reasons(
        build["report"],
        args=args,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = args.basename or _default_basename()
    markdown_path = output_dir / f"{basename}.md"
    json_path = output_dir / f"{basename}.json"
    markdown_path.write_text(render_tax_input_markdown(summary), encoding="utf-8")
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary, markdown_path, json_path


def build_tax_input_summary(
    payload: dict[str, Any],
    *,
    wb_rows: int,
) -> dict[str, Any]:
    rows = list(payload.get("taxInputReconciliation") or [])
    status_counts = Counter(str(row.get("vatInputCompleteness") or "") for row in rows)
    totals = {
        "vatInputFromWb": _format_decimal(
            sum(_decimal(row.get("vatInputFromWb")) for row in rows)
        ),
        "vatInputFrom1c": _format_decimal(
            sum(_decimal(row.get("vatInputFrom1c")) for row in rows)
        ),
        "vatInputDifference": _format_decimal(
            sum(_decimal(row.get("vatInputDifference")) for row in rows)
        ),
    }
    return {
        "generatedAt": datetime.now(tz=MOSCOW_TZ).isoformat(timespec="seconds"),
        "meta": payload.get("meta") or {},
        "wbRows": wb_rows,
        "unitRows": len(payload.get("unitRows") or []),
        "taxReconciliationRows": len(rows),
        "statusCounts": dict(sorted(status_counts.items())),
        "totals": totals,
        "methodNote": (
            "Входящий НДС по услугам WB считается из WB-сумм с НДС внутри "
            "по расчетной ставке 22/122 и сверяется с 1С услугами/УПД. "
            "1С используется как контроль, а не как второй вычет. "
            "Комиссия WB и Логистика для НДС-сверки объединяются в один "
            "контрольный блок, но в P&L остаются раздельными расходами."
        ),
        "sourceNote": _source_note(totals),
        "rows": [_safe_row(row) for row in rows],
    }


def build_discrepancy_reasons(
    report: UnitEconomicsReport,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    service_rows = _service_rows_for_args(args, report=report)
    organization_labels = _organization_labels(args)
    onec_by_key: dict[tuple[str, date, date, str], dict[str, Any]] = {}
    categories_by_period: dict[tuple[str, date, date], set[str]] = {}
    for row in service_rows:
        if row.vat == 0:
            continue
        category = _vat_reconciliation_category(row.service_category)
        key = (row.organization_id, row.week_start, row.week_end, category)
        bucket = onec_by_key.setdefault(
            key,
            {
                "onecVat": ZERO,
                "onecAmount": ZERO,
                "serviceNames": Counter(),
            },
        )
        bucket["onecVat"] += row.vat
        bucket["onecAmount"] += row.amount
        bucket["serviceNames"][row.service_name or "(empty)"] += 1
        categories_by_period.setdefault(
            (row.organization_id, row.week_start, row.week_end),
            set(),
        ).add(category)

    wb_by_key: dict[tuple[str, date, date, str], dict[str, Decimal]] = {}
    for row in report.rows:
        period_key = (row.organization_id, row.week_start, row.week_end)
        for category in categories_by_period.get(period_key, set()):
            gross = _wb_gross_for_vat_category(row, category)
            key = (*period_key, category)
            bucket = wb_by_key.setdefault(
                key,
                {
                    "wbGross": ZERO,
                    "wbVat": ZERO,
                },
            )
            bucket["wbGross"] += gross
            bucket["wbVat"] += _service_input_vat_from_gross(gross)

    category_totals: dict[str, dict[str, Any]] = {}
    weekly_rows: list[dict[str, Any]] = []
    all_keys = set(onec_by_key) | set(wb_by_key)
    for key in all_keys:
        organization_id, week_start, week_end, category = key
        onec = onec_by_key.get(
            key,
            {"onecVat": ZERO, "onecAmount": ZERO, "serviceNames": Counter()},
        )
        wb = wb_by_key.get(key, {"wbGross": ZERO, "wbVat": ZERO})
        difference = money(onec["onecVat"] - wb["wbVat"])
        total = category_totals.setdefault(
            category,
            {
                "category": category,
                "wbGross": ZERO,
                "vatInputFromWb": ZERO,
                "onecAmount": ZERO,
                "vatInputFrom1c": ZERO,
                "vatInputDifference": ZERO,
                "groups": 0,
                "serviceNames": Counter(),
            },
        )
        total["wbGross"] += wb["wbGross"]
        total["vatInputFromWb"] += wb["wbVat"]
        total["onecAmount"] += onec["onecAmount"]
        total["vatInputFrom1c"] += onec["onecVat"]
        total["vatInputDifference"] += difference
        total["groups"] += 1
        total["serviceNames"].update(onec["serviceNames"])
        if (
            abs(difference) >= DIAGNOSTIC_DIFF_THRESHOLD
            or category == "Прочие услуги WB"
        ):
            weekly_rows.append(
                {
                    "week": f"{week_start}..{week_end}",
                    "organization": organization_labels.get(
                        organization_id,
                        organization_id,
                    ),
                    "category": category,
                    "wbGross": _format_decimal(wb["wbGross"]),
                    "vatInputFromWb": _format_decimal(wb["wbVat"]),
                    "onecAmount": _format_decimal(onec["onecAmount"]),
                    "vatInputFrom1c": _format_decimal(onec["onecVat"]),
                    "vatInputDifference": _format_decimal(difference),
                    "reason": _discrepancy_reason(category, difference),
                    "recommendation": _discrepancy_recommendation(category),
                }
            )

    category_rows = [
        _safe_reason_category_row(row)
        for row in sorted(
            category_totals.values(),
            key=lambda item: abs(item["vatInputDifference"]),
            reverse=True,
        )
    ]
    weekly_rows = sorted(
        weekly_rows,
        key=lambda item: abs(_decimal(item["vatInputDifference"])),
        reverse=True,
    )
    return {
        "categoryTotals": category_rows,
        "topWeeklyDifferences": weekly_rows[:20],
    }


def render_tax_input_markdown(summary: dict[str, Any]) -> str:
    meta = summary.get("meta") or {}
    totals = summary["totals"]
    status_rows = "\n".join(
        f"| {status or 'empty'} | {count} |"
        for status, count in (summary.get("statusCounts") or {}).items()
    )
    reconciliation_rows = "\n".join(
        _markdown_row(row) for row in summary.get("rows", [])
    )
    if not reconciliation_rows:
        reconciliation_rows = "| нет строк | 0 | 0 | 0 |  |"
    reason_rows = _reason_category_rows_markdown(summary)
    weekly_reason_rows = _weekly_reason_rows_markdown(summary)
    return f"""# Draft-сверка входящего НДС

Generated at: {summary["generatedAt"]}

Client: {meta.get("client", "")}

Period: {meta.get("period", "")}

Methodology: {meta.get("methodologyVersion", "")}

Этот файл содержит только агрегированную расчетную сверку. Raw WB/1C строки,
ключи, токены и исходные документы не включены.

## Итог

| Показатель | Значение |
| --- | ---: |
| WB raw rows | {summary["wbRows"]} |
| Unit rows | {summary["unitRows"]} |
| Строк сверки НДС | {summary["taxReconciliationRows"]} |
| НДС входящий WB | {totals["vatInputFromWb"]} |
| НДС входящий 1С | {totals["vatInputFrom1c"]} |
| Расхождение НДС | {totals["vatInputDifference"]} |

## Статусы

| Статус | Строк |
| --- | ---: |
{status_rows}

## Методика

{summary["methodNote"]}

{summary["sourceNote"]}

## Причины расхождений

| Категория | WB база | НДС WB | 1С сумма | НДС 1С | Разница | Причина | Что делать |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
{reason_rows}

## Крупные хвосты по неделям

| Неделя | Организация | Категория | НДС WB | НДС 1С | Расхождение | Причина |
| --- | --- | --- | ---: | ---: | ---: | --- |
{weekly_reason_rows}

## Сверка по периодам

| Период | НДС WB | НДС 1С | Расхождение | Полнота |
| --- | ---: | ---: | ---: | --- |
{reconciliation_rows}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", default=excel_mvp.CLIENT_ID)
    parser.add_argument("--tenant-name", default="Шумейко и Партнеры")
    parser.add_argument("--wb-finance-dir", type=Path, default=None)
    parser.add_argument("--wb-cards-dir", type=Path, default=None)
    parser.add_argument("--onec-dir", type=Path, default=None)
    parser.add_argument("--onec-services-dir", type=Path, default=None)
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
    )
    parser.add_argument(
        "--report-period-end",
        type=date.fromisoformat,
        default=None,
    )
    parser.add_argument(
        "--wb-finance-source",
        choices=["files", "files-stream", "postgres"],
        default="files-stream",
    )
    parser.add_argument(
        "--stream-cache-dir",
        type=Path,
        default=Path("data/.cache/wb_stream_rebuild"),
    )
    parser.add_argument("--keep-stream-cache", action="store_true")
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
        default="СебестоимостьБезНДС",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "tax_input_reconciliation",
    )
    parser.add_argument("--basename", default="")
    return parser.parse_args()


def _safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "week": row.get("week") or "",
        "cabinet": row.get("cabinet") or "",
        "organization": row.get("organization") or "",
        "vatInputFromWb": _format_decimal(_decimal(row.get("vatInputFromWb"))),
        "vatInputFrom1c": _format_decimal(_decimal(row.get("vatInputFrom1c"))),
        "vatInputDifference": _format_decimal(
            _decimal(row.get("vatInputDifference"))
        ),
        "vatInputCompleteness": row.get("vatInputCompleteness") or "",
        "sourceRows": row.get("sourceRows") or 0,
    }


def _safe_reason_category_row(row: dict[str, Any]) -> dict[str, Any]:
    category = row["category"]
    service_names = row.get("serviceNames", Counter())
    return {
        "category": category,
        "groups": row["groups"],
        "wbGross": _format_decimal(row["wbGross"]),
        "vatInputFromWb": _format_decimal(row["vatInputFromWb"]),
        "onecAmount": _format_decimal(row["onecAmount"]),
        "vatInputFrom1c": _format_decimal(row["vatInputFrom1c"]),
        "vatInputDifference": _format_decimal(row["vatInputDifference"]),
        "reason": _discrepancy_reason(category, row["vatInputDifference"]),
        "recommendation": _discrepancy_recommendation(category),
        "topServiceNames": [
            name
            for name, _count in service_names.most_common(5)
        ],
    }


def _markdown_row(row: dict[str, Any]) -> str:
    period = str(row.get("week") or "")
    if row.get("cabinet") or row.get("organization"):
        period = f"{period} / {row.get('cabinet', '')} / {row.get('organization', '')}"
    return (
        f"| {period} | {row['vatInputFromWb']} | {row['vatInputFrom1c']} | "
        f"{row['vatInputDifference']} | {row['vatInputCompleteness']} |"
    )


def _reason_category_rows_markdown(summary: dict[str, Any]) -> str:
    rows = (summary.get("discrepancyReasons") or {}).get("categoryTotals") or []
    if not rows:
        return "| нет строк | 0 | 0 | 0 | 0 | 0 |  |  |"
    return "\n".join(
        (
            f"| {row['category']} | {row['wbGross']} | {row['vatInputFromWb']} | "
            f"{row['onecAmount']} | {row['vatInputFrom1c']} | "
            f"{row['vatInputDifference']} | {row['reason']} | "
            f"{row['recommendation']} |"
        )
        for row in rows
    )


def _weekly_reason_rows_markdown(summary: dict[str, Any]) -> str:
    rows = (summary.get("discrepancyReasons") or {}).get("topWeeklyDifferences") or []
    if not rows:
        return "| нет строк |  |  | 0 | 0 | 0 |  |"
    return "\n".join(
        (
            f"| {row['week']} | {row['organization']} | {row['category']} | "
            f"{row['vatInputFromWb']} | {row['vatInputFrom1c']} | "
            f"{row['vatInputDifference']} | {row['reason']} |"
        )
        for row in rows
    )


def _source_note(totals: dict[str, str]) -> str:
    wb_total = _decimal(totals["vatInputFromWb"])
    onec_total = _decimal(totals["vatInputFrom1c"])
    if wb_total == ZERO and onec_total != ZERO:
        return (
            "Текущий draft показывает `partial`: в нормализованном WB-снимке "
            "не удалось рассчитать входящий НДС по WB-базе, а контроль 1С по "
            "услугам/УПД есть."
        )
    if wb_total != ZERO and onec_total == ZERO:
        return (
            "Текущий draft показывает `partial`: WB-расчет входящего НДС есть, "
            "но контроль 1С по услугам/УПД не найден."
        )
    return "Текущий draft показывает состояние сверки по доступным источникам."


def _service_rows_for_args(
    args: argparse.Namespace,
    *,
    report: UnitEconomicsReport,
) -> list:
    wb_finance_dir = args.wb_finance_dir or excel_mvp._latest_dir(
        Path("data/wb_finance")
    )
    onec_dir = args.onec_dir or excel_mvp._latest_onec_reference_dir(
        Path("data/onec_samples")
    )
    sales_register_dir = (
        args.sales_register_dir
        or excel_mvp._latest_sales_register_dir(Path("data/onec_gross_profit_samples"))
    )
    services_dir = args.onec_services_dir or excel_mvp._latest_onec_services_dir(
        Path("data/onec_marketplace_service_samples")
    )
    if services_dir is None:
        return []
    _ = wb_finance_dir
    return _service_rows_in_report_period(
        excel_mvp._onec_marketplace_service_rows(
            args.client_id,
            services_dir,
            reference_dir=onec_dir,
            sales_register_dir=sales_register_dir,
        ),
        period_start=report.report_period_start,
        period_end=report.report_period_end,
    )


def _organization_labels(args: argparse.Namespace) -> dict[str, str]:
    wb_finance_dir = args.wb_finance_dir or excel_mvp._latest_dir(
        Path("data/wb_finance")
    )
    onec_dir = args.onec_dir or excel_mvp._latest_onec_reference_dir(
        Path("data/onec_samples")
    )
    return {
        item.organization_id: item.organization_name
        for item in excel_mvp._account_org_mapping(
            args.client_id,
            wb_finance_dir,
            onec_dir,
        )
    }


def _wb_gross_for_vat_category(row: Any, category: str) -> Decimal:
    if category == "Комиссия WB + Логистика":
        return row.wb_commission + row.logistics
    if category == "WB Продвижение":
        return row.wb_promotion
    if category == "Эквайринг":
        return row.acquiring
    return ZERO


def _discrepancy_reason(category: str, difference: Decimal) -> str:
    if category == "Прочие услуги WB":
        return "1С услуга есть, WB-база для SKU не найдена"
    if category == "WB Продвижение":
        return "разный период или состав рекламных начислений"
    if category == "Эквайринг":
        return "сдвиг периода или отличающаяся база эквайринга"
    if category == "Комиссия WB + Логистика":
        if abs(difference) <= DIAGNOSTIC_DIFF_THRESHOLD:
            return "сходится в пределах допуска"
        return "остаток после объединения комиссии и логистики"
    return "нужна ручная классификация"


def _discrepancy_recommendation(category: str) -> str:
    if category == "Прочие услуги WB":
        return "вести отдельной статьей или распределять по выручке после согласования"
    if category == "WB Продвижение":
        return "сверять помесячно и проверить рекламные данные за хвостовые недели"
    if category == "Эквайринг":
        return "сверять помесячно и проверить дату закрывашки"
    if category == "Комиссия WB + Логистика":
        return "оставить общий контрольный блок и разбирать только крупные недели"
    return "подтвердить правило с бухгалтерией"


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


def _format_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _default_basename() -> str:
    return "tax_input_reconciliation_draft_" + datetime.now(tz=MOSCOW_TZ).strftime(
        "%Y%m%d-%H%M%S"
    )


if __name__ == "__main__":
    raise SystemExit(main())
