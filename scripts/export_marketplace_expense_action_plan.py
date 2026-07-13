#!/usr/bin/env python3
"""Export an action-oriented WB/1C marketplace expense reconciliation report."""

# ruff: noqa: E402, E501

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun, ReportUnitRow
from wb_unit_economics.web.settings import WebSettings

GROUP_LABELS = {
    "promotion": "WB Продвижение",
    "penalties": "Штрафы/доплаты",
    "core_services": "Основные услуги WB",
}
STATUS_LABELS = {
    "mismatch": "Есть расхождение",
    "missing_onec_document": "Нет документа 1С",
}
CSV_COLUMNS = [
    "Приоритет",
    "Кабинет",
    "Неделя",
    "Контрольная группа",
    "WB, с НДС",
    "1С, с НДС",
    "Дельта 1С − WB",
    "Статус",
    "Документы 1С",
    "Что установлено",
    "Возможная причина",
    "Уверенность",
    "Что исправить или проверить в 1С",
]


def main() -> int:
    args = parse_args()
    output_dir = _validated_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = WebSettings(
        _env_file=None,
        database_url=args.database_url or WebSettings(_env_file=None).database_url,
    )
    session_factory = make_session_factory(
        make_engine(settings.database_url, statement_timeout_ms=120_000)
    )
    with session_factory() as db:
        report = db.get(ReportRun, args.report_id)
        if report is None:
            raise SystemExit(f"Report not found: {args.report_id}")
        cabinets = list(
            db.execute(
                select(
                    ReportUnitRow.wb_cabinet_id,
                    ReportUnitRow.cabinet,
                )
                .where(ReportUnitRow.report_run_id == report.id)
                .distinct()
                .order_by(ReportUnitRow.cabinet)
            )
        )
        cabinet_results = [
            (
                cabinet_name,
                repository.query_marketplace_expense_reconciliation(
                    db,
                    report,
                    period_start=args.period_start,
                    period_end=args.period_end,
                    wb_cabinet_id=cabinet_id,
                    limit=5_000,
                ),
            )
            for cabinet_id, cabinet_name in cabinets
        ]

    problem_rows = _problem_rows(cabinet_results)
    cabinet_rows = _cabinet_rows(cabinet_results)
    summary = _summary(cabinet_results, problem_rows)
    csv_path = output_dir / "problem_weeks.csv"
    artifact_path = output_dir / "artifact.json"
    notes_path = output_dir / "report_notes.json"
    _write_csv(csv_path, problem_rows)
    artifact_path.write_text(
        json.dumps(
            _artifact(
                report=report,
                period_start=args.period_start,
                period_end=args.period_end,
                summary=summary,
                cabinet_rows=cabinet_rows,
                problem_rows=problem_rows,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    notes_path.write_text(
        json.dumps(
            {
                "grain": "cabinet x service week x control group",
                "comparison": "1C amount with VAT minus WB amount with VAT",
                "sourceReportId": report.id,
                "sourceSnapshotSetId": report.source_snapshot_set_id,
                "chartMap": [
                    {
                        "segment": "Cabinet comparison",
                        "question": "Do cabinet deltas offset each other?",
                        "type": "bar",
                        "fields": ["cabinet", "delta"],
                        "claim": (
                            "Cabinet-level deltas must be checked separately; the "
                            "combined difference is not a pass criterion."
                        ),
                    }
                ],
                "confidenceRule": (
                    "Missing document is verified at the normalized report grain; "
                    "all mismatch causes remain hypotheses until the 1C document is checked."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"CSV: {csv_path}")
    print(f"Artifact: {artifact_path}")
    print(f"Problems: {len(problem_rows)}")
    return 0


def _problem_rows(
    cabinet_results: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for cabinet_name, payload in cabinet_results:
        service_items = [
            item
            for item in payload.get("items", [])
            if item.get("rowType") == "onec_service"
        ]
        problem_groups = [
            group
            for group in payload.get("groups", [])
            if group.get("status") != "matched"
        ]
        for group in problem_groups:
            documents = _documents_for_group(group, service_items)
            delta = _decimal_or_none(group.get("delta"))
            cause, confidence, action = _diagnosis(group, delta, documents)
            result.append(
                {
                    "priority": _priority(group.get("status"), delta),
                    "cabinet": cabinet_name,
                    "period": _period_label(
                        str(group.get("periodStart") or ""),
                        str(group.get("periodEnd") or ""),
                    ),
                    "controlGroup": GROUP_LABELS.get(
                        str(group.get("controlGroup") or ""),
                        str(group.get("controlGroupLabel") or ""),
                    ),
                    "wbAmount": _number(group.get("wbAmountWithVat")),
                    "onecAmount": _nullable_number(group.get("onecAmountWithVat")),
                    "delta": _nullable_number(group.get("delta")),
                    "status": STATUS_LABELS.get(
                        str(group.get("status") or ""),
                        str(group.get("status") or ""),
                    ),
                    "documents": "; ".join(documents) if documents else "Не найден",
                    "verifiedFact": _verified_fact(group, delta, documents),
                    "likelyReason": cause,
                    "confidence": confidence,
                    "action": action,
                    "periodStart": group.get("periodStart"),
                    "controlGroupCode": group.get("controlGroup"),
                }
            )
    priority_order = {"Срочно": 0, "Высокий": 1, "Средний": 2, "Низкий": 3}
    return sorted(
        result,
        key=lambda row: (
            priority_order.get(str(row["priority"]), 9),
            -abs(float(row["delta"] or row["wbAmount"] or 0)),
            str(row["cabinet"]),
            str(row["periodStart"]),
            str(row["controlGroupCode"]),
        ),
    )


def _cabinet_rows(
    cabinet_results: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    result = []
    for cabinet_name, payload in cabinet_results:
        kpis = payload.get("kpis") or {}
        statuses = Counter(
            str(item.get("status") or "") for item in payload.get("groups", [])
        )
        result.append(
            {
                "cabinet": cabinet_name,
                "cabinetShort": _cabinet_short(cabinet_name),
                "wbAmount": _number(kpis.get("wbMarketplaceDocumentExpensesWithVat")),
                "onecAmount": _nullable_number(
                    kpis.get("onecMarketplaceExpensesWithVat")
                ),
                "delta": _nullable_number(kpis.get("marketplaceExpenseDeltaWithVat")),
                "matched": statuses.get("matched", 0),
                "mismatch": statuses.get("mismatch", 0),
                "missing": statuses.get("missing_onec_document", 0),
            }
        )
    return result


def _summary(
    cabinet_results: list[tuple[str, dict[str, Any]]],
    problems: list[dict[str, Any]],
) -> dict[str, Any]:
    wb_total = sum(
        (
            Decimal(
                str(
                    (payload.get("kpis") or {}).get(
                        "wbMarketplaceDocumentExpensesWithVat"
                    )
                    or 0
                )
            )
            for _name, payload in cabinet_results
        ),
        Decimal("0"),
    )
    onec_total = sum(
        (
            Decimal(
                str(
                    (payload.get("kpis") or {}).get("onecMarketplaceExpensesWithVat")
                    or 0
                )
            )
            for _name, payload in cabinet_results
        ),
        Decimal("0"),
    )
    matched = sum(
        1
        for _name, payload in cabinet_results
        for group in payload.get("groups", [])
        if group.get("status") == "matched"
    )
    return {
        "wbAmount": float(wb_total),
        "onecAmount": float(onec_total),
        "delta": float(onec_total - wb_total),
        "problemGroups": len(problems),
        "missingDocuments": sum(
            row["status"] == "Нет документа 1С" for row in problems
        ),
        "matchedGroups": matched,
    }


def _artifact(
    *,
    report: ReportRun,
    period_start: date,
    period_end: date,
    summary: dict[str, Any],
    cabinet_rows: list[dict[str, Any]],
    problem_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    generated_at = datetime.now().astimezone().isoformat()
    period_text = _period_text(period_start, period_end)
    cabinet_count = len(cabinet_rows)
    action_source = {
        "id": "expense_action_csv",
        "label": "План сверки расходов WB ↔ 1С",
        "path": "problem_weeks.csv",
    }
    cabinet_source = {
        "id": "cabinet_delta_sql",
        "label": "Агрегат расходов по кабинетам",
    }
    cabinet_sql = f"""
WITH wb AS (
    SELECT wb_cabinet_id, cabinet,
           SUM(commission + logistics + storage + acceptance + promotion + penalties + acquiring) AS wb_amount
    FROM wb_unit_economics.report_unit_rows
    WHERE report_run_id = '{report.id}'
      AND accounting_period_date BETWEEN DATE '{period_start.isoformat()}' AND DATE '{period_end.isoformat()}'
    GROUP BY wb_cabinet_id, cabinet
), onec AS (
    SELECT wb_cabinet_id, SUM(amount_with_vat) AS onec_amount
    FROM wb_unit_economics.report_marketplace_expense_rows
    WHERE report_run_id = '{report.id}'
      AND recognition_date BETWEEN DATE '{period_start.isoformat()}' AND DATE '{period_end.isoformat()}'
      AND match_status = 'matched_marketplace_pair'
    GROUP BY wb_cabinet_id
)
SELECT wb.cabinet, wb.wb_amount, onec.onec_amount,
       onec.onec_amount - wb.wb_amount AS delta
FROM wb
LEFT JOIN onec USING (wb_cabinet_id)
ORDER BY wb.cabinet
""".strip()
    action_sql = f"""
WITH wb_week AS (
    SELECT week AS period_start, week + 6 AS period_end, wb_cabinet_id, cabinet,
           SUM(promotion) AS promotion,
           SUM(penalties) AS penalties,
           SUM(commission + logistics + storage + acceptance + acquiring) AS core_services
    FROM wb_unit_economics.report_unit_rows
    WHERE report_run_id = '{report.id}'
      AND accounting_period_date BETWEEN DATE '{period_start.isoformat()}' AND DATE '{period_end.isoformat()}'
    GROUP BY week, wb_cabinet_id, cabinet
), wb_groups AS (
    SELECT period_start, period_end, wb_cabinet_id, cabinet,
           group_row.control_group, group_row.wb_amount
    FROM wb_week
    CROSS JOIN LATERAL (
        VALUES ('promotion', promotion),
               ('penalties', penalties),
               ('core_services', core_services)
    ) AS group_row(control_group, wb_amount)
    WHERE group_row.wb_amount <> 0
), onec_groups AS (
    SELECT period_start, period_end, wb_cabinet_id, control_group,
           SUM(amount_with_vat) AS onec_amount,
           STRING_AGG(DISTINCT document_number, ', ') AS document_numbers
    FROM wb_unit_economics.report_marketplace_expense_rows
    WHERE report_run_id = '{report.id}'
      AND recognition_date BETWEEN DATE '{period_start.isoformat()}' AND DATE '{period_end.isoformat()}'
      AND match_status = 'matched_marketplace_pair'
    GROUP BY period_start, period_end, wb_cabinet_id, control_group
)
SELECT COALESCE(wb.period_start, onec.period_start) AS period_start,
       COALESCE(wb.period_end, onec.period_end) AS period_end,
       wb.cabinet,
       COALESCE(wb.control_group, onec.control_group) AS control_group,
       wb.wb_amount, onec.onec_amount,
       onec.onec_amount - wb.wb_amount AS delta,
       onec.document_numbers
FROM wb_groups wb
FULL OUTER JOIN onec_groups onec
  USING (period_start, period_end, wb_cabinet_id, control_group)
ORDER BY cabinet, period_start, control_group
""".strip()
    visible_problems = []
    for row in problem_rows:
        visible = {
            key: value
            for key, value in row.items()
            if key not in {"periodStart", "controlGroupCode"}
        }
        visible["diagnosis"] = (
            f"{row['likelyReason']} Уверенность: {row['confidence']}."
        )
        visible["cabinetShort"] = _cabinet_short(str(row["cabinet"]))
        visible["rowKey"] = (
            f"{visible['cabinetShort']} · {row['period']} · {row['controlGroup']}"
        )
        onec_amount = (
            "нет документа"
            if row["onecAmount"] is None
            else f"{float(row['onecAmount']):,.2f} ₽"
        )
        delta = (
            "не рассчитана"
            if row["delta"] is None
            else f"{float(row['delta']):+,.2f} ₽"
        )
        visible["amountComparison"] = (
            f"WB {float(row['wbAmount']):,.2f} ₽; 1С {onec_amount}; Δ {delta}"
        ).replace(",", " ")
        visible["diagnosisAction"] = f"{visible['diagnosis']} Действие: {row['action']}"
        visible["statusKey"] = (
            f"{row['priority']} · {row['status']} · {visible['rowKey']}"
        )
        visible["documentAction"] = (
            f"Документы: {row['documents']}. {visible['diagnosisAction']}"
        )
        visible_problems.append(visible)
    summary_body = (
        "## Executive Summary\n\n"
        f"- **Найдено {summary['problemGroups']} проблемных групп:** "
        f"{summary['missingDocuments']} без документа 1С, остальные имеют расхождение суммы.\n"
        f"- **Общая дельта за период составляет {summary['delta']:,.2f} ₽ (1С − WB).** "
        f"Она агрегирует {cabinet_count} кабинет(а), поэтому общий итог не является "
        "критерием успешной сверки отдельных кабинетов.\n"
        f"- **Сверено {summary['matchedGroups']} групп.** Их не нужно исправлять; "
        "работа начинается со строк «Срочно» и «Высокий»."
    ).replace(",", " ")
    findings_body = (
        "## Расхождения сосредоточены в документах и периодах, а не в WB P&L\n\n"
        "Таблица ниже сравнивает одинаковую денежную базу — суммы с НДС — на уровне "
        "недели и контрольной группы. Положительная дельта означает, что 1С выше WB; "
        "отрицательная — что в 1С сумма ниже. Причина в колонке «Возможная причина» "
        "является гипотезой до просмотра документа 1С."
    )
    problem_register_parts = [
        "## Проблемные недели и документы",
        "",
        "Полная табличная версия с отдельными колонками находится в `problem_weeks.csv`. "
        "Ниже — тот же реестр в формате, удобном для чтения без горизонтальной прокрутки.",
    ]
    for number, row in enumerate(visible_problems, start=1):
        problem_register_parts.extend(
            [
                "",
                f"### {number}. {row['statusKey']}",
                "",
                f"- **Что не сходится:** {row['amountComparison']}.",
                f"- **Документы 1С:** {row['documents']}.",
                f"- **Возможная причина:** {row['diagnosis']}",
                f"- **Что исправить в 1С:** {row['action']}",
            ]
        )
    problem_register_body = "\n".join(problem_register_parts)
    actions_body = (
        "## Рекомендуемый порядок исправления\n\n"
        f"1. Найти {summary['missingDocuments']} отсутствующих документов или строк "
        "услуг и проверить их дату проведения.\n"
        "2. Проверить крупные дельты основной группы услуг: состав комиссии, логистики, хранения, приёмки и эквайринга.\n"
        "3. Для продвижения сверить отдельные удержания WB и не переносить их в общую комиссию.\n"
        "4. Для штрафов проверить дату входящего документа и знак корректировки.\n"
        "5. После исправлений запустить full refresh и требовать допуск не более 1 ₽ по каждой группе."
    )
    return {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "План сверки расходов WB и 1С",
            "description": (
                f"Проблемные недели и документы за {period_start:%d.%m.%Y}–"
                f"{period_end:%d.%m.%Y}."
            ),
            "generatedAt": generated_at,
            "charts": [
                {
                    "id": "cabinet_delta",
                    "title": "Дельта расходов по кабинетам",
                    "subtitle": (
                        f"{period_text}, 1С − WB, суммы с НДС; положительное значение означает, что 1С выше."
                    ),
                    "type": "bar",
                    "dataset": "cabinetSummary",
                    "sourceId": "cabinet_delta_sql",
                    "encodings": {
                        "x": {
                            "field": "cabinetShort",
                            "type": "nominal",
                            "label": "Кабинет",
                        },
                        "y": {
                            "field": "delta",
                            "type": "quantitative",
                            "label": "Дельта, ₽",
                            "format": "number",
                        },
                    },
                    "valueFormat": "number",
                    "layout": "full",
                }
            ],
            "tables": [
                {
                    "id": "cabinet_summary",
                    "title": "Итог по кабинетам",
                    "subtitle": (
                        f"{period_text}, суммы с НДС; дельта рассчитана как 1С − WB."
                    ),
                    "dataset": "cabinetSummary",
                    "sourceId": "cabinet_delta_sql",
                    "columns": [
                        {"field": "cabinetShort", "label": "Кабинет", "type": "text"},
                        {"field": "wbAmount", "label": "WB, ₽", "format": "number"},
                        {"field": "onecAmount", "label": "1С, ₽", "format": "number"},
                        {
                            "field": "delta",
                            "label": "Дельта, ₽",
                            "format": "number",
                            "movement": True,
                        },
                    ],
                },
            ],
            "sources": [cabinet_source, action_source],
            "blocks": [
                {
                    "id": "title",
                    "type": "markdown",
                    "body": "# План сверки расходов WB и 1С",
                },
                {"id": "executive_summary", "type": "markdown", "body": summary_body},
                {
                    "id": "definition",
                    "type": "markdown",
                    "body": (
                        "## Сравнение построено в единой базе\n\n"
                        f"Период — {period_text}, зерно — кабинет × неделя услуги × контрольная группа. "
                        "WB остаётся источником расходов товарного P&L; 1С используется для документальной проверки."
                    ),
                },
                {
                    "id": "cabinet_intro",
                    "type": "markdown",
                    "sourceId": "cabinet_delta_sql",
                    "body": (
                        f"## Кабинеты требуют отдельной проверки\n\nВ отчёте "
                        f"{cabinet_count} кабинет(а). Их дельты нельзя взаимозачитывать."
                    ),
                },
                {
                    "id": "cabinet_chart",
                    "type": "chart",
                    "chartId": "cabinet_delta",
                    "layout": "full",
                },
                {
                    "id": "cabinet_table",
                    "type": "table",
                    "tableId": "cabinet_summary",
                    "layout": "full",
                },
                {
                    "id": "findings",
                    "type": "markdown",
                    "sourceId": "expense_action_csv",
                    "body": findings_body,
                },
                {
                    "id": "problem_register",
                    "type": "markdown",
                    "sourceId": "expense_action_csv",
                    "body": problem_register_body,
                },
                {"id": "actions", "type": "markdown", "body": actions_body},
                {
                    "id": "questions",
                    "type": "markdown",
                    "body": (
                        "## Что нужно уточнить при проверке\n\n"
                        "- Совпадает ли период услуги в УПД с неделей WB?\n"
                        "- Не включены ли продвижение и штрафы в общую комиссию повторно?\n"
                        "- Есть ли корректировка или сторно, проведённые соседней датой?"
                    ),
                },
                {
                    "id": "caveats",
                    "type": "markdown",
                    "body": (
                        "## Ограничения\n\n"
                        "Статус отсутствия документа подтверждён в нормализованном отчёте. "
                        "Причины денежных расхождений — рабочие гипотезы; окончательное подтверждение возможно только после просмотра проводок и первички 1С."
                    ),
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "cabinetSummary": cabinet_rows,
                "problemWeeks": visible_problems,
            },
        },
        "sources": [
            {
                **cabinet_source,
                "query": {
                    "engine": "postgresql",
                    "sql": cabinet_sql,
                    "tables_used": [
                        "wb_unit_economics.report_unit_rows",
                        "wb_unit_economics.report_marketplace_expense_rows",
                    ],
                    "description": (
                        f"Агрегирует расходы WB и документы 1С по кабинету за {period_text}."
                    ),
                },
            },
            {
                **action_source,
                "query": {
                    "engine": "postgresql",
                    "sql": action_sql,
                    "tables_used": [
                        "wb_unit_economics.report_unit_rows",
                        "wb_unit_economics.report_marketplace_expense_rows",
                    ],
                    "description": (
                        "Воспроизводит недельные контрольные группы, суммы и номера документов; "
                        "скрипт добавляет приоритет, гипотезу причины и действие в 1С."
                    ),
                },
            },
        ],
    }


def _documents_for_group(
    group: dict[str, Any], items: list[dict[str, Any]]
) -> list[str]:
    matched = []
    for item in items:
        if (
            item.get("periodStart") != group.get("periodStart")
            or item.get("periodEnd") != group.get("periodEnd")
            or item.get("controlGroup") != group.get("controlGroup")
        ):
            continue
        parts = []
        if item.get("documentNumber"):
            parts.append(f"№ {item['documentNumber']}")
        if item.get("inputNumber"):
            parts.append(f"вх. {item['inputNumber']}")
        if parts:
            matched.append(" / ".join(parts))
    return sorted(set(matched))


def _cabinet_short(value: str) -> str:
    return value


def _diagnosis(
    group: dict[str, Any],
    delta: Decimal | None,
    documents: list[str],
) -> tuple[str, str, str]:
    status = str(group.get("status") or "")
    group_code = str(group.get("controlGroup") or "")
    if status == "missing_onec_document":
        return (
            "Документ или строка услуги проведены другой датой, другой статьёй либо отсутствуют.",
            "Высокая для факта отсутствия; причина не подтверждена",
            (
                "Найти УПД/приходную накладную WB за эту неделю; проверить организацию, "
                "контрагента, дату проведения и наличие строки нужной группы."
            ),
        )
    direction = "выше" if delta is not None and delta > 0 else "ниже"
    if group_code == "promotion":
        return (
            f"Сумма продвижения в 1С {direction} WB; вероятны другая неделя или включение в общую комиссию.",
            "Средняя",
            (
                "Сверить удержание «Продвижение» по УПД с неделей WB; исключить перенос "
                "и повторное включение в комиссию."
            ),
        )
    if group_code == "penalties":
        return (
            f"Штрафы/доплаты в 1С {direction} WB; вероятны другая дата входящего документа или неверный знак.",
            "Средняя",
            (
                "Проверить дату входящего документа, знак штрафа/доплаты и соседнюю неделю; "
                "сторно должно сохранять отрицательный знак."
            ),
        )
    document_hint = "найденным документам" if documents else "строкам 1С"
    return (
        f"Общая группа услуг в 1С {direction} WB по {document_hint}; состав статей не совпадает.",
        "Средняя",
        (
            "Открыть строки документа и разложить комиссию, логистику, хранение, приёмку, "
            "эквайринг и прочие услуги; проверить НДС и период услуги."
        ),
    )


def _verified_fact(
    group: dict[str, Any], delta: Decimal | None, documents: list[str]
) -> str:
    if group.get("status") == "missing_onec_document":
        return "В нормализованных строках 1С нет документа этой недели и группы."
    return (
        f"Найдено документов: {len(documents)}; дельта воспроизводится до копейки"
        if delta is not None
        else "Дельта не рассчитана"
    )


def _priority(status: Any, delta: Decimal | None) -> str:
    if status == "missing_onec_document":
        return "Срочно"
    magnitude = abs(delta or Decimal("0"))
    if magnitude >= Decimal("50000"):
        return "Высокий"
    if magnitude >= Decimal("10000"):
        return "Средний"
    return "Низкий"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Приоритет": row["priority"],
                    "Кабинет": row["cabinet"],
                    "Неделя": row["period"],
                    "Контрольная группа": row["controlGroup"],
                    "WB, с НДС": row["wbAmount"],
                    "1С, с НДС": row["onecAmount"],
                    "Дельта 1С − WB": row["delta"],
                    "Статус": row["status"],
                    "Документы 1С": row["documents"],
                    "Что установлено": row["verifiedFact"],
                    "Возможная причина": row["likelyReason"],
                    "Уверенность": row["confidence"],
                    "Что исправить или проверить в 1С": row["action"],
                }
            )


def _period_label(start: str, end: str) -> str:
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        return f"{start}–{end}"
    return f"{start_date:%d.%m.%Y}–{end_date:%d.%m.%Y}"


def _period_text(period_start: date, period_end: date) -> str:
    return f"{period_start:%d.%m.%Y}–{period_end:%d.%m.%Y}"


def _validated_output_dir(path: Path) -> Path:
    output_dir = path.resolve()
    try:
        output_dir.relative_to(ROOT)
    except ValueError:
        return output_dir
    allowed_roots = ((ROOT / "data").resolve(), (ROOT / "reports").resolve())
    if not any(
        output_dir == allowed or allowed in output_dir.parents
        for allowed in allowed_roots
    ):
        raise SystemExit(
            "Output inside the repository is allowed only under data/ or reports/."
        )
    return output_dir


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _number(value: Any) -> float:
    return float(Decimal(str(value or 0)))


def _nullable_number(value: Any) -> float | None:
    return None if value is None or value == "" else _number(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--period-start", type=date.fromisoformat, required=True)
    parser.add_argument("--period-end", type=date.fromisoformat, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
