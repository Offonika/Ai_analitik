# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import Client, SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    settings = (
        WebSettings(_env_file=None, database_url=database_url)
        if database_url
        else WebSettings(_env_file=None)
    )
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    with factory() as db:
        client = _resolve_client(db, args.client)
        if client is None:
            print("Client not found.", file=sys.stderr)
            return 2
        refresh_run = (
            db.get(SourceRefreshRun, args.refresh_run_id)
            if args.refresh_run_id
            else repository.latest_calculable_ozon_refresh_run(
                db,
                tenant_id=client.tenant_id,
                client_id=client.id,
            )
        )
        if (
            refresh_run is None
            or refresh_run.tenant_id != client.tenant_id
            or refresh_run.client_id != client.id
        ):
            print("Calculable Ozon refresh run not found.", file=sys.stderr)
            return 3
        existing = repository.ozon_draft_report_for_refresh(db, refresh_run)
        print(f"Client: {client.name} ({client.id})")
        print(f"Refresh run: {refresh_run.id} ({refresh_run.status})")
        if existing is not None:
            print(f"Ozon draft already exists: {existing.id}")
            if args.apply and refresh_run.new_report_run_id != existing.id:
                refresh_run.new_report_run_id = existing.id
                db.commit()
                print("Existing draft link restored.")
            return 0
        if not args.apply:
            print("Dry-run: Ozon draft can be created; no changes were made.")
            return 0
        report = repository.materialize_ozon_draft_report(db, refresh_run)
        db.commit()
        print(f"Created Ozon draft: {report.id} ({report.status})")
    return 0


def _resolve_client(db, value: str) -> Client | None:
    direct = db.get(Client, value)
    if direct is not None:
        return direct
    return db.scalar(
        select(Client)
        .where(Client.name == value)
        .order_by(Client.created_at.desc())
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotently create a staff-only Ozon draft from a saved run."
    )
    parser.add_argument("--client", required=True, help="Client id or exact name.")
    parser.add_argument("--refresh-run-id", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
