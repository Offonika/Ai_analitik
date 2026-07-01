from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

EXPORT_SHEETS = {
    "unitRows": "Юнит экономика",
    "monthly": "Динамика",
    "expenses": "Расходы WB",
    "returns": "Возвраты",
    "lostSales": "Упущенные продажи",
    "documentReconciliation": "Сверка документов 1С",
    "reconciliationMonthly": "Сверка с 1С ОПиУ",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path, status: str = "ready") -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "hash": file_sha256(path) if path.exists() else "",
        "byte_size": path.stat().st_size if path.exists() else 0,
        "status": status,
    }


def write_excel_from_marts(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    readme = workbook.active
    readme.title = "README"
    _write_readme(readme, summary)
    for key, sheet_name in EXPORT_SHEETS.items():
        _write_rows_sheet(workbook.create_sheet(sheet_name), summary.get(key, []))
    _write_methodology(workbook.create_sheet("Методика"), summary)
    workbook.save(output_path)
    return output_path


def write_csv_marts(summary: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for key in (
        "unitRows",
        "lostSales",
        "reconciliationMonthly",
        "documentReconciliation",
    ):
        path = output_dir / f"{key}.csv"
        _write_csv(path, summary.get(key, []))
        paths.append(path)
    readme_path = output_dir / "README.md"
    readme_path.write_text(build_markdown_summary(summary), encoding="utf-8")
    paths.append(readme_path)
    return paths


def write_html_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = summary.get("meta", {})
    rows = summary.get("unitRows", [])
    lost = summary.get("lostSales", [])
    body = [
        '<!doctype html><html lang="ru"><meta charset="utf-8">',
        "<title>DB-first report marts</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;color:#1f2933}"
        "table{border-collapse:collapse;width:100%;margin:16px 0}"
        "th,td{border:1px solid #d9e2ec;padding:6px;font-size:12px}"
        "th{background:#edf4fb;text-align:left}</style>",
        f"<h1>{_html(meta.get('title', 'DB-first report marts'))}</h1>",
        f"<p>{_html(meta.get('client', ''))} · {_html(meta.get('period', ''))}</p>",
        f"<p><strong>Период отчета:</strong> "
        f"{_html(meta.get('reportPeriod', meta.get('period', '')))}</p>",
        f"<p><strong>Покрытие источников:</strong> "
        f"{_html(meta.get('sourceCoverage', ''))}</p>",
        f"<p><strong>Статус готовности:</strong> "
        f"{_html(_readiness_label(summary))}</p>",
        _html_table("KPI", _kpi_rows(rows)),
        _html_table("Упущенные продажи", lost[:50]),
        "</html>",
    ]
    output_path.write_text("\n".join(body), encoding="utf-8")
    return output_path


def write_markdown_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_markdown_summary(summary), encoding="utf-8")
    return output_path


def write_docx_summary(summary: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = summary.get("meta", {})
    doc = Document()
    doc.add_heading(str(meta.get("title") or "DB-first report marts"), level=1)
    doc.add_paragraph(f"{meta.get('client', '')} · {meta.get('period', '')}")
    doc.add_paragraph(
        f"Период отчета: {meta.get('reportPeriod', meta.get('period', ''))}"
    )
    doc.add_paragraph(f"Покрытие источников: {meta.get('sourceCoverage', '')}")
    doc.add_paragraph(f"Статус готовности: {_readiness_label(summary)}")
    doc.add_heading("KPI", level=2)
    for row in _kpi_rows(summary.get("unitRows", [])):
        doc.add_paragraph(f"{row['metric']}: {row['value']}")
    doc.add_heading("Упущенные продажи", level=2)
    for row in summary.get("lostSales", [])[:20]:
        doc.add_paragraph(
            f"{row.get('product', '')}: {row.get('lostRevenue', 0)} руб., "
            f"1С остаток {row.get('onecStock', 0)}"
        )
    doc.save(output_path)
    return output_path


def convert_docx_to_pdf(docx_path: Path) -> tuple[Path | None, str, str]:
    converter = shutil.which("libreoffice") or shutil.which("soffice")
    if converter is None:
        return None, "unavailable", "LibreOffice/soffice не найден."
    output_dir = docx_path.parent
    expected = docx_path.with_suffix(".pdf")
    try:
        result = subprocess.run(
            [
                converter,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(docx_path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "failed", str(exc)
    if result.returncode != 0 or not expected.exists():
        return None, "failed", "DOCX создан, PDF не сформирован."
    return expected, "ready", "PDF сформирован."


def build_markdown_summary(summary: dict[str, Any]) -> str:
    meta = summary.get("meta", {})
    lines = [
        f"# {meta.get('title', 'DB-first report marts')}",
        "",
        f"- Клиент: {meta.get('client', '')}",
        f"- Период: {meta.get('period', '')}",
        f"- Период отчета: {meta.get('reportPeriod', meta.get('period', ''))}",
        f"- Покрытие источников: {meta.get('sourceCoverage', '')}",
        f"- Статус готовности: {_readiness_label(summary)}",
        f"- Методика: {meta.get('methodologyVersion', '')}",
        f"- Lineage: {meta.get('lineageType', '')}",
        "",
        "## KPI",
    ]
    for row in _kpi_rows(summary.get("unitRows", [])):
        lines.append(f"- {row['metric']}: {row['value']}")
    lines.extend(["", "## Упущенные продажи"])
    for row in summary.get("lostSales", [])[:20]:
        lines.append(
            f"- {row.get('product', '')}: lostRevenue={row.get('lostRevenue', 0)}, "
            f"onecStock={row.get('onecStock', 0)}"
        )
    return "\n".join(lines) + "\n"


def _write_readme(sheet: Any, summary: dict[str, Any]) -> None:
    meta = summary.get("meta", {})
    rows = [
        ("Источник", "DB report marts"),
        ("Клиент", meta.get("client", "")),
        ("Период", meta.get("period", "")),
        ("Период отчета", meta.get("reportPeriod", meta.get("period", ""))),
        ("Покрытие источников", meta.get("sourceCoverage", "")),
        ("Статус готовности", _readiness_label(summary)),
        ("Версия методики", meta.get("methodologyVersion", "")),
        ("Lineage", meta.get("lineageType", "")),
        ("Строк юнит-экономики", len(summary.get("unitRows", []))),
        ("Строк упущенных продаж", len(summary.get("lostSales", []))),
    ]
    for index, row in enumerate(rows, start=1):
        sheet.cell(index, 1, row[0])
        sheet.cell(index, 2, row[1])
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 80


def _write_rows_sheet(sheet: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        sheet.cell(1, 1, "Нет строк")
        return
    headers = sorted({key for row in rows for key in row})
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(1, column, header)
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for row_index, row in enumerate(rows, start=2):
        for column, header in enumerate(headers, start=1):
            sheet.cell(row_index, column, row.get(header))
    for column in range(1, len(headers) + 1):
        sheet.column_dimensions[sheet.cell(1, column).column_letter].width = 18


def _write_methodology(sheet: Any, summary: dict[str, Any]) -> None:
    rows = [
        ("Правило", "Значение"),
        ("Источник правды", "Опубликованная расчетная БД"),
        ("Excel", "Только экспорт из report marts"),
        ("Web", "Читает опубликованный report_id из БД"),
        ("Raw snapshots", "Не публикуются через клиентское API"),
        ("Lineage", summary.get("meta", {}).get("lineageType", "")),
    ]
    for index, row in enumerate(rows, start=1):
        sheet.cell(index, 1, row[0])
        sheet.cell(index, 2, row[1])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    headers = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _readiness_label(summary: dict[str, Any]) -> str:
    readiness = summary.get("readiness", {})
    status = str(readiness.get("status") or "").strip()
    label = str(readiness.get("label") or "").strip()
    if status and label:
        return f"{status} ({label})"
    return status or label


def _kpi_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    revenue = sum(float(row.get("revenue") or 0) for row in rows)
    profit = sum(float(row.get("profit") or 0) for row in rows)
    sales = sum(float(row.get("sales") or 0) for row in rows)
    returns = sum(float(row.get("returns") or 0) for row in rows)
    margin = profit / revenue if revenue else None
    return [
        {"metric": "Строк отчета", "value": len(rows)},
        {"metric": "Выручка", "value": round(revenue, 2)},
        {"metric": "Прибыль", "value": round(profit, 2)},
        {"metric": "Маржа", "value": round(margin, 4) if margin is not None else ""},
        {"metric": "Продажи, шт", "value": round(sales, 2)},
        {"metric": "Возвраты, шт", "value": round(returns, 2)},
    ]


def _html_table(title: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"<h2>{_html(title)}</h2><p>Нет строк</p>"
    headers = sorted({key for row in rows for key in row})
    header_html = "".join(f"<th>{_html(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append(
            "<tr>"
            + "".join(f"<td>{_html(row.get(header, ''))}</td>" for header in headers)
            + "</tr>"
        )
    return (
        f"<h2>{_html(title)}</h2><table><thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _html(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
