#!/usr/bin/env python3
"""Build a client analytical report from a saved DB-first report_id."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.client_report import (  # noqa: E402
    DEFAULT_LOGO,
    ClientAnalyticalReportArtifacts,
    build_client_analytical_report,
)
from wb_unit_economics.web.database import (  # noqa: E402
    init_db,
    make_engine,
    make_session_factory,
)
from wb_unit_economics.web.models import ReportRun  # noqa: E402
from wb_unit_economics.web.report_scope import (  # noqa: E402
    report_summary_for_period,
)
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
        summary = _report_summary(
            db,
            report,
            period_start=args.period_start,
            period_end=args.period_end,
        )
    basename = args.basename or _basename(
        report,
        branded=args.branded,
        period_start=args.period_start,
        period_end=args.period_end,
    )
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
    parser.add_argument(
        "--period-start",
        type=date.fromisoformat,
        help="First accounting date of a scoped report, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--period-end",
        type=date.fromisoformat,
        help="Last accounting date of a scoped report, YYYY-MM-DD.",
    )
    return parser.parse_args()


def _settings(args: argparse.Namespace) -> WebSettings:
    if args.database_url:
        return WebSettings(_env_file=None, database_url=args.database_url)
    return WebSettings(_env_file=None)


def _basename(
    report: ReportRun,
    *,
    branded: bool,
    period_start: date | None = None,
    period_end: date | None = None,
) -> str:
    start = period_start or report.period_start
    end = period_end or report.period_end
    period = f"{start:%d.%m.%Y}-{end:%d.%m.%Y}"
    prefix = "Фирменный аналитический отчёт" if branded else DEFAULT_BASENAME
    return f"{prefix} за период {period}"


def _report_summary(
    db: Any,
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    try:
        return report_summary_for_period(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _print_artifacts(artifacts: ClientAnalyticalReportArtifacts) -> None:
    print(f"Markdown: {artifacts.markdown_path}")
    print(f"DOCX: {artifacts.docx_path}")
    if artifacts.pdf_path is not None:
        print(f"PDF: {artifacts.pdf_path}")
    else:
        print(f"PDF: {artifacts.pdf_status} - {artifacts.pdf_message}")


if __name__ == "__main__":
    raise SystemExit(main())
