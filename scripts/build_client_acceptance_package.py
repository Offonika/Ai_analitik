#!/usr/bin/env python3
"""Build a safe report-specific client acceptance package from the DB."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.client_acceptance import (  # noqa: E402, I001
    AcceptancePackageError,
    build_client_acceptance_package,
)
from wb_unit_economics.web.database import make_engine, make_session_factory  # noqa: E402
from wb_unit_economics.web.models import ReportRun  # noqa: E402
from wb_unit_economics.web.settings import WebSettings  # noqa: E402


def main() -> int:
    args = parse_args()
    settings = _settings(args)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        if engine.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        report = db.get(ReportRun, args.report_id)
        if report is None:
            print(f"Report not found: {args.report_id}", file=sys.stderr)
            return 2
        output_dir = args.output_dir or (
            ROOT / "reports" / "client_packages" / report.id
        )
        try:
            artifacts = build_client_acceptance_package(
                db,
                report,
                output_dir=output_dir,
            )
        except AcceptancePackageError as exc:
            print(f"Acceptance package blocked: {exc}", file=sys.stderr)
            return 1
    print(f"Markdown: {artifacts.markdown_path}")
    print(f"DOCX: {artifacts.docx_path}")
    print(f"Manifest: {artifacts.manifest_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("SHUMEYKO_DATABASE_URL", ""),
    )
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def _settings(args: argparse.Namespace) -> WebSettings:
    if args.database_url:
        return WebSettings(_env_file=None, database_url=args.database_url)
    return WebSettings(_env_file=None)


if __name__ == "__main__":
    raise SystemExit(main())
