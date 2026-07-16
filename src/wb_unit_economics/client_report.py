from __future__ import annotations

import html
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from wb_unit_economics.document_exports import (
    markdown_sha256,
    render_markdown_docx,
)

CLIENT_REPORT_CONTRACT_VERSION = "client-analytical-report.v1"
DEFAULT_LOGO = Path("reports/assets/shumeiko-logo.png")

READINESS_LABELS = {
    "ready": "Готов к передаче клиенту",
    "needs_review": "Требует проверки",
    "partial_period": "Предварительный период",
    "partial_source": "Неполные источники",
    "source_coverage_gap": "Недостаточное покрытие источников",
    "failed": "Финансовая проверка не пройдена",
}


@dataclass(frozen=True)
class ClientAnalyticalReportArtifacts:
    markdown_path: Path
    docx_path: Path
    pdf_path: Path | None
    pdf_status: str
    pdf_message: str
    source_sha256: str


@dataclass(frozen=True)
class ClientReportModel:
    meta: Mapping[str, Any]
    readiness: Mapping[str, Any]
    kpis: Mapping[str, Any]
    quality: Mapping[str, Any]
    tax_context: Mapping[str, Any]
    lost_sales_coverage: Mapping[str, Any]
    unit_rows: tuple[Mapping[str, Any], ...]
    monthly: tuple[Mapping[str, Any], ...]
    expenses: tuple[Mapping[str, Any], ...]
    returns: tuple[Mapping[str, Any], ...]
    lost_sales: tuple[Mapping[str, Any], ...]
    reconciliation_monthly: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ClientReportModel:
        meta = _mapping(payload.get("meta"))
        report_id = str(meta.get("reportId") or "").strip()
        if not report_id:
            raise ValueError("client analytical report requires meta.reportId")
        return cls(
            meta=meta,
            readiness=_mapping(payload.get("readiness")),
            kpis=_mapping(payload.get("kpis")),
            quality=_mapping(payload.get("quality")),
            tax_context=_mapping(payload.get("taxContext")),
            lost_sales_coverage=_mapping(payload.get("lostSalesCoverage")),
            unit_rows=_rows(payload.get("unitRows")),
            monthly=_rows(payload.get("monthly")),
            expenses=_rows(payload.get("expenses")),
            returns=_rows(payload.get("returns")),
            lost_sales=_rows(payload.get("lostSales")),
            reconciliation_monthly=_rows(payload.get("reconciliationMonthly")),
        )


def build_client_analytical_report(
    *,
    summary: Mapping[str, Any],
    output_dir: Path,
    basename: str,
    logo_path: Path = DEFAULT_LOGO,
    branded: bool = False,
) -> ClientAnalyticalReportArtifacts:
    model = ClientReportModel.from_payload(summary)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f"{basename}.md"
    docx_path = output_dir / f"{basename}.docx"
    markdown = build_client_analytical_markdown(model)
    source_hash = markdown_sha256(markdown)
    markdown_path.write_text(markdown, encoding="utf-8")
    render_markdown_docx(
        markdown,
        docx_path,
        logo_path=logo_path if logo_path.exists() else None,
        branded=branded,
        landscape=False,
        cover_subtitle=str(model.meta.get("reportPeriod") or model.meta.get("period")),
        source_sha256=source_hash,
    )
    pdf_path, pdf_status, pdf_message = convert_client_docx_to_pdf(docx_path)
    return ClientAnalyticalReportArtifacts(
        markdown_path=markdown_path,
        docx_path=docx_path,
        pdf_path=pdf_path,
        pdf_status=pdf_status,
        pdf_message=pdf_message,
        source_sha256=source_hash,
    )


def build_client_analytical_markdown(
    payload: ClientReportModel | Mapping[str, Any],
) -> str:
    model = (
        payload
        if isinstance(payload, ClientReportModel)
        else ClientReportModel.from_payload(payload)
    )
    meta = model.meta
    kpis = model.kpis
    tax_calculated = model.tax_context.get("calculated") is True
    period = str(meta.get("reportPeriod") or meta.get("period") or "не указан")
    revenue = _decimal_or_none(kpis.get("revenue"))
    management_profit = _decimal_or_none(
        kpis.get("profitManagement", kpis.get("profitBeforeTax"))
    )
    final_profit = _decimal_or_none(kpis.get("profit")) if tax_calculated else None
    result_value = final_profit if tax_calculated else management_profit
    result_label = "Прибыль до НДФЛ" if tax_calculated else "Управленческая прибыль WB"
    result_phrase = result_label[:1].lower() + result_label[1:]
    result_margin = _ratio(result_value, revenue)
    sales = _decimal_or_zero(kpis.get("sales"))
    returns = _decimal_or_zero(kpis.get("returns"))
    return_rate = _ratio(returns, sales)
    loss_rows = _int(kpis.get("lossRows"))
    row_count = _int(kpis.get("rowCount")) or len(model.unit_rows)
    readiness = _readiness_label(model.readiness)
    ok_share = _decimal_or_none(model.quality.get("okShare"))

    lines = [
        "# Аналитический отчёт по юнит-экономике WB",
        "",
        "## Executive Summary — краткий вывод",
        "",
        (
            f"- **Результат периода.** За {period} выручка составила "
            f"{_money(revenue)}, а {result_phrase} — "
            f"{_money(result_value)} при маржинальности {_percent(result_margin)}."
        ),
        (
            f"- **Продажи и возвраты.** Продано {_quantity(sales)} шт., "
            f"возвращено {_quantity(returns)} шт.; доля возвратов — "
            f"{_percent(return_rate)}."
        ),
        _loss_summary_line(model, loss_rows=loss_rows),
        (
            f"- **Готовность данных.** Статус — {readiness}. "
            f"Строк со статусом «ОК»: {_percent(ok_share)} из "
            f"{_quantity(row_count)} строк."
        ),
        "",
        "## Параметры отчёта",
        "",
        _markdown_table(
            ["Параметр", "Значение"],
            [
                ["Клиент", meta.get("client") or "Не указан"],
                ["Период анализа", period],
                ["Статус периода", meta.get("periodStatus") or "Не указан"],
                [
                    "Покрытие источников",
                    meta.get("sourceCoverage") or "Не зафиксировано",
                ],
                ["Дата расчёта", meta.get("generatedAt") or "Не указана"],
                ["Версия методики", meta.get("methodologyVersion") or "Не указана"],
                ["Статус готовности", readiness],
                ["Идентификатор отчёта", meta.get("reportId")],
            ],
        ),
        "",
        "## Основные показатели периода",
        "",
        (
            "Показатели ниже взяты из сохранённой расчётной витрины выбранного "
            "отчёта. Они не пересчитываются из DOCX или Excel."
        ),
        "",
        _kpi_table(model, result_label=result_label, result_value=result_value),
    ]

    _append_monthly_section(
        lines,
        model,
        result_label=result_label,
        tax_calculated=tax_calculated,
    )
    _append_cabinet_section(lines, model, tax_calculated=tax_calculated)
    _append_driver_section(lines, model, tax_calculated=tax_calculated)
    _append_returns_and_lost_sales(lines, model)
    _append_quality_section(lines, model)
    _append_tax_section(lines, model)
    _append_actions(lines, model, return_rate=return_rate)
    _append_questions(lines, model)
    _append_limitations(lines, model)
    lines.extend(
        [
            "",
            (
                f"Версия контракта документа: {CLIENT_REPORT_CONTRACT_VERSION}. "
                f"Источник: сохранённый report_id {meta.get('reportId')}."
            ),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_client_report_html(
    markdown: str,
    *,
    title: str = "Аналитический отчёт по юнит-экономике WB",
) -> str:
    body = _markdown_to_html(markdown)
    source_hash = markdown_sha256(markdown)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="source-sha256" content="{source_hash}">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --navy:#003153; --blue:#2f75b5;
      --pale:#edf4fb; --ink:#262626; --muted:#595959; }}
    body {{ max-width: 1080px; margin: 0 auto; padding: 32px;
      font: 15px/1.55 Arial, sans-serif; color: var(--ink); }}
    h1 {{ color: var(--navy); font-size: 30px; }}
    h2 {{ color: var(--navy); border-bottom: 2px solid var(--blue);
      padding-bottom: 6px; margin-top: 34px; }}
    h3 {{ color: #9b6418; margin-top: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 14px 0 24px; }}
    th, td {{ border: 1px solid #d9e2f3; padding: 8px 10px; text-align: left; }}
    th {{ background: var(--navy); color: white; }}
    tbody tr:nth-child(even) {{ background: var(--pale); }}
    td:not(:first-child) {{ text-align: right; }}
    li {{ margin: 7px 0; }}
    .source {{ color: var(--muted); font-size: 12px; margin-top: 32px; }}
    @media (max-width: 720px) {{ body {{ padding: 16px; }}
      table {{ display:block; overflow-x:auto; }} }}
    @media print {{ body {{ max-width:none; padding:0; }} }}
  </style>
</head>
<body>
{body}
<p class="source">Контрольная сумма источника: {source_hash}</p>
</body>
</html>
"""


def convert_client_docx_to_pdf(docx_path: Path) -> tuple[Path | None, str, str]:
    converter = shutil.which("libreoffice") or shutil.which("soffice")
    if converter is None:
        return (
            None,
            "unavailable",
            "PDF-конвертер LibreOffice/soffice не установлен на сервере.",
        )
    expected = docx_path.with_suffix(".pdf")
    try:
        result = subprocess.run(
            [
                converter,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(docx_path.parent),
                str(docx_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "failed", f"Не удалось запустить PDF-конвертер: {exc}"
    if result.returncode != 0 or not expected.exists():
        return None, "failed", "DOCX создан, но PDF-конвертация завершилась ошибкой."
    return expected, "ok", "PDF сформирован."


def _kpi_table(
    model: ClientReportModel,
    *,
    result_label: str,
    result_value: Decimal | None,
) -> str:
    kpis = model.kpis
    sales = _decimal_or_zero(kpis.get("sales"))
    returns = _decimal_or_zero(kpis.get("returns"))
    wb_expenses = sum(
        (
            _decimal_or_zero(row.get("amount"))
            for row in model.expenses
            if str(row.get("expense") or "").casefold() != "себестоимость 1с"
        ),
        Decimal("0"),
    )
    lost_sales = _decimal_or_none(kpis.get("lostSalesRevenue"))
    management_profit = kpis.get("profitManagement", kpis.get("profitBeforeTax"))
    rows = [
        ["Выручка", _money(kpis.get("revenue"))],
        ["Продажи", f"{_quantity(sales)} шт."],
        ["Возвраты", f"{_quantity(returns)} шт."],
        ["Доля возвратов", _percent(_ratio(returns, sales))],
        ["Себестоимость 1С", _money(kpis.get("cogs"))],
        ["Расходы WB", _money(wb_expenses)],
        ["Управленческая прибыль WB", _money(management_profit)],
    ]
    if result_label != "Управленческая прибыль WB":
        rows.append([result_label, _money(result_value)])
    rows.extend(
        [
            ["Маржинальность", _percent(_ratio(result_value, kpis.get("revenue")))],
            ["Убыточные строки", _quantity(kpis.get("lossRows"))],
            ["Потенциально упущенная выручка", _money(lost_sales)],
        ]
    )
    return _markdown_table(["Показатель", "Значение"], rows)


def _append_monthly_section(
    lines: list[str],
    model: ClientReportModel,
    *,
    result_label: str,
    tax_calculated: bool,
) -> None:
    monthly_rows = _monthly_rows(model, tax_calculated=tax_calculated)
    if not monthly_rows:
        return
    lines.extend(
        [
            "",
            "## Динамика: результат по месяцам",
            "",
            (
                "Месяцы показаны только в пределах сохранённого отчёта. "
                "Неполный месяц не сравнивается с полным как равный период."
            ),
            "",
            _markdown_table(
                [
                    "Месяц",
                    "Статус",
                    "Выручка",
                    result_label,
                    "Маржинальность",
                    "Возвраты",
                ],
                [
                    [
                        row.get("month") or "Не указан",
                        row.get("status") or "",
                        _money(row.get("revenue")),
                        _money(row.get("profit")),
                        _percent(row.get("margin")),
                        _quantity(row.get("returns")),
                    ]
                    for row in monthly_rows
                ],
            ),
        ]
    )


def _append_cabinet_section(
    lines: list[str],
    model: ClientReportModel,
    *,
    tax_calculated: bool,
) -> None:
    rows = _cabinet_rows(model, tax_calculated=tax_calculated)
    if not rows:
        return
    result_label = "Прибыль до НДФЛ" if tax_calculated else "Упр. прибыль WB"
    leading = max(rows, key=lambda row: row["revenue"])
    lines.extend(
        [
            "",
            "## Кабинеты: где формируется результат",
            "",
            (
                f"Наибольшая выручка в периоде приходится на кабинет "
                f"«{_text(leading['cabinet'])}» — {_money(leading['revenue'])}. "
                "Сравнивать кабинеты следует одновременно по прибыли, "
                "маржинальности и возвратам."
            ),
            "",
            _markdown_table(
                [
                    "Кабинет WB",
                    "Выручка",
                    result_label,
                    "Маржинальность",
                    "Продажи",
                    "Возвраты",
                    "% возвратов",
                ],
                [
                    [
                        row["cabinet"],
                        _money(row["revenue"]),
                        _money(row["result"]),
                        _percent(_ratio(row["result"], row["revenue"])),
                        _quantity(row["sales"]),
                        _quantity(row["returns"]),
                        _percent(_ratio(row["returns"], row["sales"])),
                    ]
                    for row in rows
                ],
            ),
        ]
    )


def _append_driver_section(
    lines: list[str],
    model: ClientReportModel,
    *,
    tax_calculated: bool,
) -> None:
    expense_rows = sorted(
        (
            row
            for row in model.expenses
            if str(row.get("expense") or "").casefold() != "себестоимость 1с"
        ),
        key=lambda row: abs(_decimal_or_zero(row.get("amount"))),
        reverse=True,
    )
    losses = _loss_groups(model, tax_calculated=tax_calculated)
    lines.extend(["", "## Что сильнее всего влияет на прибыль", ""])
    if expense_rows:
        top_expense = expense_rows[0]
        lines.extend(
            [
                (
                    f"Крупнейшая статья расходов WB — "
                    f"{_text(top_expense.get('expense'))}: "
                    f"{_money(top_expense.get('amount'))} "
                    f"({_percent(top_expense.get('share'))} от выручки)."
                ),
                "",
                _markdown_table(
                    ["Статья", "Сумма", "Доля от выручки"],
                    [
                        [
                            row.get("expense") or "Не указана",
                            _money(row.get("amount")),
                            _percent(row.get("share")),
                        ]
                        for row in expense_rows
                    ],
                ),
            ]
        )
    else:
        lines.append("Структура расходов WB в витрине не заполнена.")

    if not losses:
        lines.extend(["", "Убыточных товаров с рассчитанным результатом нет."])
        return
    driver_counts = Counter(
        str(row["driver"] or "Причина не классифицирована") for row in losses
    )
    result_label = "Прибыль до НДФЛ" if tax_calculated else "Упр. прибыль WB"
    lines.extend(
        [
            "",
            "### Товары с наибольшим отрицательным результатом",
            "",
            (
                f"В витрине найдено {len(losses)} групп товаров с отрицательным "
                f"результатом. Наиболее частый фактор: "
                f"{driver_counts.most_common(1)[0][0]}."
            ),
            "",
            _markdown_table(
                [
                    "Товар",
                    "Артикул 1С",
                    "Кабинет",
                    "Выручка",
                    result_label,
                    "Возвраты",
                    "Фактор",
                    "Статус данных",
                ],
                [
                    [
                        row["product"],
                        row["article"],
                        row["cabinet"],
                        _money(row["revenue"]),
                        _money(row["result"]),
                        _quantity(row["returns"]),
                        row["driver"],
                        row["status"],
                    ]
                    for row in losses[:10]
                ],
            ),
        ]
    )


def _append_returns_and_lost_sales(lines: list[str], model: ClientReportModel) -> None:
    lines.extend(["", "## Возвраты и потенциально упущенные продажи", ""])
    returns = _return_groups(model)
    if returns:
        top = returns[0]
        lines.extend(
            [
                (
                    f"Больше всего возвратов в денежном выражении приходится на "
                    f"«{_text(top['product'])}»: {_money(top['return_amount'])}. "
                    "Причина возврата указывается только при наличии источника."
                ),
                "",
                _markdown_table(
                    [
                        "Товар",
                        "Кабинет",
                        "Продажи",
                        "Возвраты",
                        "% возвратов",
                        "Сумма возвратов",
                    ],
                    [
                        [
                            row["product"],
                            row["cabinet"],
                            _quantity(row["sales"]),
                            _quantity(row["returns"]),
                            _percent(_ratio(row["returns"], row["sales"])),
                            _money(row["return_amount"]),
                        ]
                        for row in returns[:7]
                    ],
                ),
            ]
        )
    else:
        lines.append("Возвраты в сохранённой витрине не выделены отдельными строками.")

    coverage = model.lost_sales_coverage
    if coverage.get("calculated") is True:
        lines.extend(
            [
                "",
                (
                    "Упущенные продажи являются оценкой по доступному окну истории "
                    "остатков и не экстраполируются на дни без источника."
                ),
                "",
                _markdown_table(
                    ["Показатель", "Значение"],
                    [
                        [
                            "Потенциально упущено, шт.",
                            _quantity(model.kpis.get("lostSalesUnits")),
                        ],
                        [
                            "Потенциально упущенная выручка",
                            _money(model.kpis.get("lostSalesRevenue")),
                        ],
                        [
                            "Потенциально упущенный маржинальный доход",
                            _money(model.kpis.get("lostContributionMargin")),
                        ],
                        [
                            "Период расчёта",
                            _coverage_period(coverage),
                        ],
                    ],
                ),
            ]
        )
        if model.lost_sales:
            lines.extend(
                [
                    "",
                    "### Товары с наибольшей оценкой упущенной выручки",
                    "",
                    _markdown_table(
                        [
                            "Товар",
                            "Кабинет",
                            "Дней без остатка",
                            "Остаток 1С",
                            "Упущено, шт.",
                            "Упущенная выручка",
                        ],
                        [
                            [
                                row.get("product") or "Не указан",
                                row.get("cabinet") or "Не указан",
                                _quantity(row.get("zeroStockDays")),
                                _quantity(row.get("onecStock")),
                                _quantity(row.get("lostUnits")),
                                _money(row.get("lostRevenue")),
                            ]
                            for row in sorted(
                                model.lost_sales,
                                key=lambda row: _decimal_or_zero(
                                    row.get("lostRevenue")
                                ),
                                reverse=True,
                            )[:7]
                        ],
                    ),
                ]
            )
    else:
        coverage_message = coverage.get("message") or (
            "нет полного источника истории остатков."
        )
        lines.extend(
            [
                "",
                (f"Упущенные продажи не рассчитаны: {coverage_message}"),
            ]
        )


def _append_quality_section(lines: list[str], model: ClientReportModel) -> None:
    quality = model.quality
    lines.extend(
        [
            "",
            "## Качество данных и сверка с 1С",
            "",
            (
                "Финансовые выводы надёжны только для строк с достаточной "
                "себестоимостью и однозначным сопоставлением WB ↔ 1С."
            ),
            "",
            _markdown_table(
                ["Контроль", "Значение"],
                [
                    ["Всего строк", _quantity(quality.get("rowCount"))],
                    ["Строк со статусом ОК", _quantity(quality.get("okRows"))],
                    ["Доля строк ОК", _percent(quality.get("okShare"))],
                    [
                        "Без себестоимости 1С",
                        _quantity(quality.get("missingCostRows")),
                    ],
                    [
                        "Требуют сопоставления WB ↔ 1С",
                        _quantity(quality.get("mappingRows")),
                    ],
                    [
                        "Проблемы сверки документов 1С",
                        _quantity(quality.get("documentReconciliationIssues")),
                    ],
                ],
            ),
        ]
    )
    if model.reconciliation_monthly:
        lines.extend(
            [
                "",
                "### Помесячная сверка WB и 1С",
                "",
                _markdown_table(
                    [
                        "Месяц",
                        "Дельта количества",
                        "Дельта себестоимости",
                        "Дельта расходов МП",
                        "Статус",
                    ],
                    [
                        [
                            row.get("month") or "Не указан",
                            _quantity(row.get("quantity_delta")),
                            _money(row.get("cogs_delta")),
                            _money(row.get("mp_expenses_delta")),
                            row.get("status") or row.get("comment") or "",
                        ]
                        for row in model.reconciliation_monthly[:12]
                    ],
                ),
            ]
        )


def _append_tax_section(lines: list[str], model: ClientReportModel) -> None:
    tax = model.tax_context
    calculated = tax.get("calculated") is True
    if calculated:
        lines.extend(
            [
                "",
                "## Налоги рассчитаны по настройкам 1С",
                "",
                (
                    "Организация, система налогообложения и применимые ставки "
                    "взяты из настроек организации 1С, сохранённых в lineage "
                    "этого report_id. Отдельное ручное подтверждение не требуется."
                ),
                "",
                _markdown_table(
                    ["Параметр", "Значение"],
                    [
                        ["Источник", "Настройки организации 1С"],
                        ["Система налогообложения", _tax_value(tax.get("taxSystem"))],
                        ["Ставка НДС", _percent(tax.get("vatRate"))],
                        ["Налог с выручки", _percent(tax.get("revenueTaxRate"))],
                        ["НДС к уплате", _money(model.kpis.get("vatPayable"))],
                        ["Налог с выручки", _money(model.kpis.get("revenueTax"))],
                        ["Прибыль до НДФЛ", _money(model.kpis.get("profit"))],
                    ],
                ),
            ]
        )
        return
    lines.extend(
        [
            "",
            "## Налоговые настройки 1С не применены к отчёту",
            "",
            (
                "Для этого report_id настройки налогообложения из 1С не были "
                "загружены либо не вошли в расчёт. Поэтому налоговые показатели "
                "не подменяются нулями, а результат показан как Управленческая "
                "прибыль WB до налогового слоя."
            ),
        ]
    )


def _append_actions(
    lines: list[str],
    model: ClientReportModel,
    *,
    return_rate: Decimal | None,
) -> None:
    actions: list[str] = []
    missing_cost = _int(model.quality.get("missingCostRows"))
    mapping_rows = _int(model.quality.get("mappingRows"))
    loss_rows = _int(model.kpis.get("lossRows"))
    if missing_cost:
        actions.append(
            f"Проверить {missing_cost} строк без себестоимости 1С и пересобрать "
            "отчёт до принятия решений по их прибыльности."
        )
    if mapping_rows:
        actions.append(
            f"Разобрать {mapping_rows} строк сопоставления WB ↔ 1С; не считать "
            "их нулевую себестоимость финансовым фактом."
        )
    if loss_rows:
        actions.append(
            "Для топ убыточных товаров проверить сценарии цены, скидки, "
            "себестоимости и расходов WB. Сценарий считать отдельно; текущий "
            "отчёт не обещает рост прибыли от изменения одного параметра."
        )
    if return_rate is not None and return_rate >= Decimal("0.10"):
        actions.append(
            "По товарам с высокой долей возвратов получить источник причин "
            "возврата и только после этого выбирать корректирующее действие."
        )
    if (
        model.lost_sales_coverage.get("calculated") is True
        and _decimal_or_zero(model.kpis.get("lostSalesRevenue")) > 0
    ):
        actions.append(
            "Сверить остатки 1С и график пополнения по товарам с наибольшей "
            "оценкой упущенной выручки; оценка не является прогнозом заказа."
        )
    if not actions:
        actions.append(
            "Сохранить текущую логику расчёта и контролировать маржинальность, "
            "возвраты и структуру расходов при следующем обновлении периода."
        )
    lines.extend(["", "## Что делать дальше", ""])
    lines.extend(f"{index}. {action}" for index, action in enumerate(actions, start=1))


def _append_questions(lines: list[str], model: ClientReportModel) -> None:
    questions: list[str] = []
    if model.tax_context.get("calculated") is not True:
        questions.append(
            "Почему настройки налогообложения организации из 1С не вошли в "
            "lineage выбранного отчёта?"
        )
    limitation = str(model.meta.get("returnReasonLimitation") or "").strip()
    if limitation:
        questions.append(limitation.rstrip(".") + ".")
    for reason in [
        *model.readiness.get("blockingReasons", []),
        *model.readiness.get("reviewReasons", []),
    ]:
        if not isinstance(reason, Mapping):
            continue
        code = str(reason.get("code") or "")
        if code in {
            "tax_profile_unconfirmed",
            "client_draft_missing",
            "client_draft_not_ready",
        }:
            continue
        message = str(reason.get("message") or "").strip()
        if message:
            questions.append(message)
    questions = list(dict.fromkeys(questions))
    if not questions:
        return
    lines.extend(["", "## Что остаётся проверить", ""])
    lines.extend(f"- {question}" for question in questions)


def _append_limitations(lines: list[str], model: ClientReportModel) -> None:
    limitations = [
        (
            "Отчёт является управленческой аналитикой, а не бухгалтерским "
            "или налоговым заключением."
        ),
        "DOCX не пересчитывает показатели: все суммы взяты из сохранённого report_id.",
        (
            "Причины возвратов и убытков показываются только при наличии "
            "рассчитанного поля или источника."
        ),
    ]
    period_status = str(model.meta.get("periodStatus") or "")
    if "неполн" in period_status.casefold() or "предвар" in period_status.casefold():
        limitations.append(
            f"Период имеет статус «{period_status}» и не сравнивается с "
            "полным периодом без поправки."
        )
    if model.lost_sales_coverage.get("calculated") is True:
        limitations.append(
            "Упущенные продажи — оценка только за фактически покрытое "
            "историей остатков окно."
        )
    lines.extend(["", "## Ограничения и допущения", ""])
    lines.extend(f"- {item}" for item in limitations)


def _loss_summary_line(model: ClientReportModel, *, loss_rows: int) -> str:
    if loss_rows:
        return (
            f"- **Главный резерв.** В отчёте {loss_rows} убыточных строк. "
            "Решения по ним следует принимать после проверки рассчитанного "
            "драйвера и качества себестоимости."
        )
    return (
        "- **Главный риск.** Убыточные строки с рассчитанным результатом не "
        "выявлены; контроль всё равно нужно повторить после обновления периода."
    )


def _cabinet_rows(
    model: ClientReportModel,
    *,
    tax_calculated: bool,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Decimal | str]] = defaultdict(
        lambda: {
            "cabinet": "Не указан",
            "revenue": Decimal("0"),
            "result": Decimal("0"),
            "sales": Decimal("0"),
            "returns": Decimal("0"),
        }
    )
    for row in model.unit_rows:
        cabinet = str(row.get("cabinet") or "Не указан")
        bucket = grouped[cabinet]
        bucket["cabinet"] = cabinet
        bucket["revenue"] += _row_revenue(row)
        bucket["result"] += _row_result(row, tax_calculated=tax_calculated)
        bucket["sales"] += _decimal_or_zero(row.get("sales"))
        bucket["returns"] += _decimal_or_zero(row.get("returns"))
    return sorted(grouped.values(), key=lambda row: row["revenue"], reverse=True)


def _monthly_rows(
    model: ClientReportModel,
    *,
    tax_calculated: bool,
) -> list[dict[str, Any]]:
    metadata = {
        str(row.get("month") or ""): row for row in model.monthly if row.get("month")
    }
    grouped: dict[str, dict[str, Any]] = {}
    for row in model.unit_rows:
        month = str(row.get("month") or "").strip()
        if not month:
            continue
        bucket = grouped.setdefault(
            month,
            {
                "month": month,
                "status": str(metadata.get(month, {}).get("status") or ""),
                "monthStart": str(metadata.get(month, {}).get("monthStart") or ""),
                "revenue": Decimal("0"),
                "profit": Decimal("0"),
                "returns": Decimal("0"),
            },
        )
        bucket["revenue"] += _row_revenue(row)
        bucket["profit"] += _row_result(row, tax_calculated=tax_calculated)
        bucket["returns"] += _decimal_or_zero(row.get("returns"))
    if not grouped:
        return [dict(row) for row in model.monthly]
    for bucket in grouped.values():
        bucket["margin"] = _ratio(bucket["profit"], bucket["revenue"])
        if not bucket["status"] and "неполн" in bucket["month"].casefold():
            bucket["status"] = "неполный месяц"
    return sorted(
        grouped.values(),
        key=lambda row: str(row.get("monthStart") or row.get("month") or ""),
    )


def _loss_groups(
    model: ClientReportModel,
    *,
    tax_calculated: bool,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in model.unit_rows:
        key = (
            str(row.get("product") or "Не указан"),
            str(row.get("article1c") or "—"),
            str(row.get("cabinet") or "Не указан"),
        )
        bucket = grouped.setdefault(
            key,
            {
                "product": key[0],
                "article": key[1],
                "cabinet": key[2],
                "revenue": Decimal("0"),
                "result": Decimal("0"),
                "returns": Decimal("0"),
                "driver": "Причина не классифицирована",
                "status": "ОК",
            },
        )
        bucket["revenue"] += _row_revenue(row)
        bucket["result"] += _row_result(row, tax_calculated=tax_calculated)
        bucket["returns"] += _decimal_or_zero(row.get("returns"))
        driver = str(row.get("lossDriver") or row.get("lossClass") or "").strip()
        if driver:
            bucket["driver"] = driver
        status = str(row.get("status") or "").strip()
        if status and status != "ОК":
            bucket["status"] = status
    result = [row for row in grouped.values() if row["result"] < 0]
    return sorted(result, key=lambda row: row["result"])


def _return_groups(model: ClientReportModel) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in model.returns:
        key = (
            str(row.get("product") or "Не указан"),
            str(row.get("cabinet") or "Не указан"),
        )
        bucket = grouped.setdefault(
            key,
            {
                "product": key[0],
                "cabinet": key[1],
                "sales": Decimal("0"),
                "returns": Decimal("0"),
                "return_amount": Decimal("0"),
            },
        )
        bucket["sales"] += _decimal_or_zero(row.get("sales"))
        bucket["returns"] += _decimal_or_zero(row.get("returns"))
        bucket["return_amount"] += _decimal_or_zero(row.get("returnAmount"))
    return sorted(grouped.values(), key=lambda row: row["return_amount"], reverse=True)


def _row_revenue(row: Mapping[str, Any]) -> Decimal:
    tax_method = str(row.get("taxMethod") or "").upper()
    if row.get("pnlVatMode") == "without_vat_for_osno" or "ОСНО" in tax_method:
        value = row.get("revenueWithoutVat")
        if value not in (None, ""):
            return _decimal_or_zero(value)
    return _decimal_or_zero(row.get("revenue"))


def _row_result(row: Mapping[str, Any], *, tax_calculated: bool) -> Decimal:
    if tax_calculated and row.get("profit") not in (None, ""):
        return _decimal_or_zero(row.get("profit"))
    if row.get("profitBeforeTax") not in (None, ""):
        return _decimal_or_zero(row.get("profitBeforeTax"))
    return _decimal_or_zero(row.get("profit"))


def _readiness_label(readiness: Mapping[str, Any]) -> str:
    status = str(readiness.get("status") or "needs_review")
    label = str(readiness.get("label") or "").strip()
    return label or READINESS_LABELS.get(status, status)


def _coverage_period(coverage: Mapping[str, Any]) -> str:
    start = str(coverage.get("calculationPeriodStart") or "").strip()
    end = str(coverage.get("calculationPeriodEnd") or "").strip()
    if start and end:
        return f"{start} — {end}"
    return str(coverage.get("message") or "Не указан")


def _tax_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "Не указано"
    return "Разные по организациям" if text == "mixed" else text


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    normalized_headers = [_table_cell(value) for value in headers]
    lines = [
        "| " + " | ".join(normalized_headers) + " |",
        "| " + " | ".join("---" for _ in normalized_headers) + " |",
    ]
    if not rows:
        rows = [["Нет данных", *("" for _ in normalized_headers[1:])]]
    for row in rows:
        padded = [*row, *("" for _ in range(max(0, len(headers) - len(row))))]
        lines.append("| " + " | ".join(_table_cell(value) for value in padded) + " |")
    return "\n".join(lines)


def _table_cell(value: Any) -> str:
    return _text(str(value or "").replace("|", " / ")).replace("\n", " ")


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    rendered: list[str] = []
    index = 0
    in_list = False
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            index += 1
            continue
        if line.startswith("|"):
            if in_list:
                rendered.append("</ul>")
                in_list = False
            table_rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [
                    cell.strip() for cell in lines[index].strip().strip("|").split("|")
                ]
                if not all(re.fullmatch(r"[:\-\s]+", cell) for cell in cells):
                    table_rows.append(cells)
                index += 1
            rendered.append(_html_table(table_rows))
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
        elif re.match(r"^[-*]\s+", line):
            if not in_list:
                rendered.append("<ul>")
                in_list = True
            rendered.append(f"<li>{_inline_html(re.sub(r'^[-*]\\s+', '', line))}</li>")
        elif re.match(r"^\d+\.\s+", line):
            if in_list:
                rendered.append("</ul>")
                in_list = False
            rendered.append(f"<p>{_inline_html(line)}</p>")
        else:
            if in_list:
                rendered.append("</ul>")
                in_list = False
            rendered.append(f"<p>{_inline_html(line)}</p>")
        index += 1
    if in_list:
        rendered.append("</ul>")
    return "\n".join(rendered)


def _html_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header, *body = rows
    head = "".join(f"<th>{_inline_html(cell)}</th>" for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_inline_html(cell)}</td>" for cell in row) + "</tr>"
        for row in body
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body_html}</tbody></table>"


def _inline_html(value: Any) -> str:
    escaped = html.escape(str(value or ""))
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_or_zero(value: Any) -> Decimal:
    return _decimal_or_none(value) or Decimal("0")


def _ratio(numerator: Any, denominator: Any) -> Decimal | None:
    left = _decimal_or_none(numerator)
    right = _decimal_or_none(denominator)
    if left is None or right in (None, 0):
        return None
    return left / right


def _int(value: Any) -> int:
    return int(_decimal_or_zero(value))


def _money(value: Any) -> str:
    number = _decimal_or_none(value)
    if number is None:
        return "Не рассчитано"
    return f"{_format_decimal(number, 2)} ₽"


def _quantity(value: Any) -> str:
    number = _decimal_or_none(value)
    if number is None:
        return "Не рассчитано"
    precision = 0 if number == number.to_integral_value() else 2
    return _format_decimal(number, precision)


def _percent(value: Any) -> str:
    number = _decimal_or_none(value)
    if number is None:
        return "Не рассчитано"
    return f"{_format_decimal(number * 100, 2)}%"


def _format_decimal(value: Decimal, precision: int) -> str:
    formatted = f"{value:,.{precision}f}"
    return formatted.replace(",", "\u00a0").replace(".", ",")


def _text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text or "Не указано"
