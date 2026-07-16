#!/usr/bin/env python3
"""Build a client analytical report from a saved DB-first report_id."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.client_report import (  # noqa: E402
    DEFAULT_LOGO,
    ClientAnalyticalReportArtifacts,
    build_client_analytical_report,
)
from wb_unit_economics.web import repository  # noqa: E402
from wb_unit_economics.web.database import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import ReportRun  # noqa: E402
from wb_unit_economics.web.settings import WebSettings  # noqa: E402

DEFAULT_BASENAME = "Аналитический отчёт по юнит-экономике WB"


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
    basename = args.basename or _basename(report, branded=args.branded)
    artifacts = build_client_analytical_report(
        summary=summary,
        output_dir=args.output_dir,
        basename=basename,
        logo_path=args.logo,
        branded=args.branded,
    )
    _print_artifacts(artifacts)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "analytical_reports",
    )
    parser.add_argument("--basename", default="")
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument("--branded", action="store_true")
    return parser.parse_args()


def _settings(args: argparse.Namespace) -> WebSettings:
    if args.database_url:
        return WebSettings(_env_file=None, database_url=args.database_url)
    return WebSettings(_env_file=None)


def _basename(report: ReportRun, *, branded: bool) -> str:
    period = f"{report.period_start:%d.%m.%Y}-{report.period_end:%d.%m.%Y}"
    prefix = "Фирменный аналитический отчёт" if branded else DEFAULT_BASENAME
    return f"{prefix} за период {period}"


def _print_artifacts(artifacts: ClientAnalyticalReportArtifacts) -> None:
    print(f"Markdown: {artifacts.markdown_path}")
    print(f"DOCX: {artifacts.docx_path}")
    if artifacts.pdf_path is not None:
        print(f"PDF: {artifacts.pdf_path}")
    else:
        print(f"PDF: {artifacts.pdf_status} - {artifacts.pdf_message}")


if __name__ == "__main__":
    raise SystemExit(main())
