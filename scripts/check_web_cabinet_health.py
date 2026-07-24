#!/usr/bin/env python3
"""Smoke check the Shumeyko web cabinet runtime without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-url", default="http://127.0.0.1:8097/api/health")
    parser.add_argument("--service", default="shumeiko-web-prod.service")
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = {
        "service": systemd_is_active(args.service),
        "health": http_health(args.health_url),
        "database": database_summary(args.database_url),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["service"] == "active" and result["health"] == "ok" else 1


def systemd_is_active(service: str) -> str:
    command = ["systemctl", "is-active", service]
    response = subprocess.run(command, text=True, capture_output=True, check=False)
    return response.stdout.strip() or response.stderr.strip() or "unknown"


def http_health(url: str) -> str:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("status", "unknown")
    except Exception as exc:
        return f"error: {exc.__class__.__name__}"


def database_summary(database_url: str) -> dict[str, object]:
    if not database_url:
        return {"status": "not_configured"}
    try:
        from sqlalchemy import func, select

        from wb_unit_economics.web.database import (
            make_engine,
            make_session_factory,
            schema_version,
        )
        from wb_unit_economics.web.models import ReportRun, SourceRefreshRun, User

        os.chdir(ROOT)
        engine = make_engine(database_url)
        session_factory = make_session_factory(engine)
        with session_factory() as db:
            report_count = db.scalar(select(func.count()).select_from(ReportRun)) or 0
            user_count = db.scalar(select(func.count()).select_from(User)) or 0
            latest = db.scalar(
                select(ReportRun).order_by(ReportRun.generated_at.desc())
            )
            latest_published = db.scalar(
                select(ReportRun)
                .where(
                    ReportRun.publication_status == "published",
                    ReportRun.is_current.is_(True),
                )
                .order_by(ReportRun.generated_at.desc())
            )
            latest_refresh = db.scalar(
                select(SourceRefreshRun).order_by(SourceRefreshRun.created_at.desc())
            )
        database_type = engine.dialect.name
        return {
            "status": "ok",
            "databaseType": database_type,
            "schemaVersion": schema_version(engine),
            "reportRuns": int(report_count),
            "users": int(user_count),
            "latestReportGeneratedAt": (
                latest.generated_at.isoformat() if latest else ""
            ),
            "latestPublishedReportId": latest_published.id if latest_published else "",
            "latestPublishedGeneratedAt": (
                latest_published.generated_at.isoformat() if latest_published else ""
            ),
            "latestSourceRefresh": {
                "id": latest_refresh.id if latest_refresh else "",
                "status": latest_refresh.status if latest_refresh else "",
                "finishedAt": (
                    latest_refresh.finished_at.isoformat()
                    if latest_refresh and latest_refresh.finished_at
                    else ""
                ),
            },
            "publicationBlocked": database_type == "sqlite",
            "warning": (
                "SQLite is local/dev/test only; use SHUMEYKO_DATABASE_URL=Postgres "
                "for live publication."
                if database_type == "sqlite"
                else ""
            ),
        }
    except Exception as exc:
        return {"status": f"error: {exc.__class__.__name__}"}


if __name__ == "__main__":
    raise SystemExit(main())
