#!/usr/bin/env python3
"""Export DB-first report artifacts from a saved report_id."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.report_exports import (
    artifact_record,
    convert_docx_to_pdf,
    write_csv_marts,
    write_docx_summary,
    write_excel_from_marts,
    write_html_summary,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun
from wb_unit_economics.web.settings import WebSettings

DEFAULT_EXCEL = ROOT / "reports" / "shumeyko_wb_excel_mvp.xlsx"


def main() -> int:
    args = parse_args()
    settings = _settings(args)
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = db.get(ReportRun, args.report_id)
        if report is None:
            raise SystemExit(f"Report not found: {args.report_id}")
        summary = repository.report_full_payload(db, report)
        records = export_report_artifacts(
            summary,
            report_id=report.id,
            output_dir=args.output_dir,
            excel_path=args.excel_path,
            excel=args.excel or args.all,
            docx=args.docx or args.all,
            pdf=args.pdf or args.all,
            html=args.html or args.all,
            csv=args.csv or args.all,
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
        db.commit()
    for artifact_type, record in records:
        print(f"{artifact_type}: {record['status']} {record['path']}")
    return 0


def export_report_artifacts(
    summary: dict,
    *,
    report_id: str,
    output_dir: Path,
    excel_path: Path,
    excel: bool,
    docx: bool,
    pdf: bool,
    html: bool,
    csv: bool,
) -> list[tuple[str, dict]]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = f"{report_id}_db_first"
    records: list[tuple[str, dict]] = []
    docx_path: Path | None = None
    if excel:
        path = write_excel_from_marts(summary, excel_path.resolve())
        records.append(("excel", artifact_record(path)))
    if csv:
        for path in write_csv_marts(summary, output_dir / "csv"):
            records.append(("csv", artifact_record(path)))
    if html:
        path = write_html_summary(summary, output_dir / f"{basename}.html")
        records.append(("html", artifact_record(path)))
    if docx or pdf:
        docx_path = write_docx_summary(summary, output_dir / f"{basename}.docx")
        records.append(("docx", artifact_record(docx_path)))
    if pdf and docx_path is not None:
        pdf_path, status, message = convert_docx_to_pdf(docx_path)
        if pdf_path is not None:
            records.append(("pdf", artifact_record(pdf_path, status=status)))
        else:
            print(f"pdf: {status} {message}", file=sys.stderr)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "reports" / "db_first"
    )
    parser.add_argument("--excel-path", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--excel", action="store_true")
    parser.add_argument("--docx", action="store_true")
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--html", action="store_true")
    parser.add_argument("--csv", action="store_true")
    parser.add_argument("--all", action="store_true")
    return parser.parse_args()


def _settings(args: argparse.Namespace) -> WebSettings:
    if args.database_url:
        return WebSettings(_env_file=None, database_url=args.database_url)
    return WebSettings(_env_file=None)


if __name__ == "__main__":
    raise SystemExit(main())
