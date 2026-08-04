#!/usr/bin/env python3
"""Create idempotent queued refresh runs for due client schedules."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ClientRefreshSchedule, SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import SourceRefreshService


def enqueue_due(
    db,
    *,
    service: SourceRefreshService,
    now: datetime,
) -> list[str]:
    statement = (
        select(ClientRefreshSchedule)
        .where(ClientRefreshSchedule.enabled.is_(True))
        .order_by(
            ClientRefreshSchedule.priority,
            ClientRefreshSchedule.client_id,
        )
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    schedules = list(db.scalars(statement))
    created: list[str] = []
    for schedule in schedules:
        due = repository.due_client_refresh_schedule_slot(schedule, now=now)
        if due is None:
            continue
        mode, slot = due
        active = repository.active_conflicting_source_refresh_run(
            db,
            tenant_id=schedule.tenant_id,
            client_id=schedule.client_id,
            mode=mode,
        )
        if active is not None:
            continue
        payload = service.enqueue(
            db,
            tenant_id=schedule.tenant_id,
            client_id=schedule.client_id,
            mode=mode,
            credential_source="tenant",
            reason=f"scheduled:{slot}",
            resume_mode="auto",
        )
        if payload.get("status") != "queued":
            continue
        refresh_run = db.get(SourceRefreshRun, str(payload["id"]))
        if refresh_run is None:
            raise RuntimeError("scheduled refresh run was not persisted")
        repository.ensure_source_refresh_task_chain(
            db,
            refresh_run,
            priority=schedule.priority,
        )
        if mode == "incremental":
            schedule.last_incremental_slot = slot
        else:
            schedule.last_full_slot = slot
        schedule.updated_at = security.utcnow()
        created.append(refresh_run.id)
    db.commit()
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--at", default="")
    args = parser.parse_args()
    settings = (
        WebSettings(_env_file=None, database_url=args.database_url)
        if args.database_url
        else WebSettings(_env_file=None)
    )
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    now = datetime.fromisoformat(args.at) if args.at else security.utcnow()
    with session_factory() as db:
        created = enqueue_due(
            db,
            service=SourceRefreshService(settings),
            now=now,
        )
    print(f"queued={len(created)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
