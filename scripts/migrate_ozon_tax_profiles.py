#!/usr/bin/env python3
"""Dry-run/apply Ozon company links, tax profiles, and snapshot uniqueness."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun


DEFAULT_LOCAL_POSTGRES_URL = (
    "postgresql+psycopg://postgres@/shumeyko_web_cabinet"
    "?host=/var/run/postgresql&port=55433"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("SHUMEYKO_DATABASE_URL") or DEFAULT_LOCAL_POSTGRES_URL,
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    engine = make_engine(args.database_url, statement_timeout_ms=120000)
    summary = _dry_run_summary(engine)
    target_run_ids = _target_run_ids(engine)
    summary["targetRuns"] = len(target_run_ids)
    _print_summary("DRY RUN", summary)
    if not args.apply:
        return 0
    if summary["activeRefreshes"]:
        print("APPLY BLOCKED: wait for active source refreshes to finish.")
        return 3
    if summary["positionDuplicateGroups"]:
        print("APPLY BLOCKED: duplicate source row positions must be reviewed.")
        return 2

    init_db(engine, run_backfill=False)
    _ensure_snapshot_position_index(engine)
    session_factory = make_session_factory(engine)
    applied = defaultdict(int)
    with session_factory() as db:
        prefix = (
            ""
            if db.get_bind().dialect.name == "sqlite"
            else "wb_unit_economics."
        )
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text(
                    "LOCK TABLE wb_unit_economics.source_refresh_runs, "
                    "wb_unit_economics.source_snapshot_rows "
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
        active_refreshes = int(
            db.execute(
                text(
                    f"SELECT count(*) FROM {prefix}source_refresh_runs "
                    "WHERE status IN ('queued', 'running', 'rebuilding')"
                )
            ).scalar_one()
        )
        if active_refreshes:
            db.rollback()
            print("APPLY BLOCKED: source refresh became active before mutation.")
            return 3
        locked_target_run_ids = list(
            db.execute(text(_target_runs_sql(prefix))).scalars()
        )
        if set(locked_target_run_ids) != set(target_run_ids):
            db.rollback()
            print("APPLY BLOCKED: target runs changed after dry-run.")
            return 3
        position_duplicates = int(
            db.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT refresh_run_id, collection_id, row_number "
                    f"FROM {prefix}source_snapshot_rows "
                    "GROUP BY refresh_run_id, collection_id, row_number "
                    "HAVING count(*) > 1"
                    ") duplicate_positions"
                )
            ).scalar_one()
        )
        if position_duplicates:
            db.rollback()
            print("APPLY BLOCKED: duplicate source row positions must be reviewed.")
            return 2
        runs = list(
            db.scalars(
                select(SourceRefreshRun)
                .where(SourceRefreshRun.id.in_(target_run_ids))
                .order_by(SourceRefreshRun.created_at.desc())
            )
        )
        for run in runs:
            if not any(
                item.source_type == "onec_tax_profiles" for item in run.collections
            ):
                collection = repository.sync_organization_tax_profiles(db, run)
                applied["taxProfileRows"] += int(collection.row_count or 0)
                applied["taxProfileRuns"] += 1
            if not any(
                item.source_type == "snapshot_duplicate_control"
                for item in run.collections
            ):
                duplicate_control = repository.validate_source_snapshot_duplicates(
                    db, run
                )
                applied["duplicateControls"] += 1
                if duplicate_control.status == "needs_review":
                    run.status = "needs_review"
                    applied["runsBlockedByDuplicates"] += 1
        db.commit()

    final_summary = _dry_run_summary(engine)
    final_summary.update(applied)
    _print_summary("APPLIED", final_summary)
    return 0


def _dry_run_summary(engine) -> dict[str, int]:  # type: ignore[no-untyped-def]
    schema = None if str(engine.url).startswith("sqlite") else "wb_unit_economics"
    inspector = inspect(engine)
    if not inspector.has_table("source_snapshot_rows", schema=schema):
        return {
            "activeClients": 0,
            "activeRefreshes": 0,
            "activeCompanies": 0,
            "organizationLinkCandidates": 0,
            "ozonCabinetLinkCandidates": 0,
            "positionDuplicateGroups": 0,
            "payloadDuplicateGroups": 0,
            "targetRuns": 0,
        }
    prefix = "" if schema is None else f"{schema}."
    target_runs = _target_runs_sql(prefix)
    company_columns = {
        item["name"]
        for item in inspector.get_columns("client_companies", schema=schema)
    }
    organization_column = (
        "COALESCE(onec_organization_id, '')"
        if "onec_organization_id" in company_columns
        else "''"
    )
    with engine.connect() as connection:
        active_clients = int(
            connection.execute(
                text(f"SELECT count(*) FROM {prefix}clients WHERE status = 'active'")
            ).scalar_one()
        )
        active_refreshes = int(
            connection.execute(
                text(
                    f"SELECT count(*) FROM {prefix}source_refresh_runs "
                    "WHERE status IN ('queued', 'running', 'rebuilding')"
                )
            ).scalar_one()
        )
        companies = connection.execute(
            text(
                "SELECT id, client_id, display_name, source_key, "
                f"{organization_column} AS onec_organization_id "
                f"FROM {prefix}client_companies WHERE status = 'active'"
            )
        ).mappings().all()
        organization_links = _organization_link_candidates(
            connection,
            prefix=prefix,
            companies=companies,
        )
        cabinet_links = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT c.client_id "
                    f"FROM {prefix}client_companies c "
                    f"JOIN {prefix}wb_cabinets w ON w.client_id = c.client_id "
                    "WHERE c.status = 'active' AND w.status = 'active' "
                    "AND lower(w.provider) LIKE 'ozon%' "
                    "AND COALESCE(w.client_company_id, '') = '' "
                    "GROUP BY c.client_id "
                    "HAVING count(DISTINCT c.id) = 1 AND count(DISTINCT w.id) = 1"
                    ") candidate"
                )
            ).scalar_one()
        )
        position_duplicates = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT refresh_run_id, collection_id, row_number "
                    f"FROM {prefix}source_snapshot_rows "
                    "GROUP BY refresh_run_id, collection_id, row_number "
                    "HAVING count(*) > 1"
                    ") duplicate_positions"
                )
            ).scalar_one()
        )
        payload_duplicates = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT refresh_run_id, source_type, wb_cabinet_id, "
                    "raw_payload_hash "
                    f"FROM {prefix}source_snapshot_rows "
                    f"WHERE refresh_run_id IN ({target_runs}) "
                    "AND raw_payload_hash <> '' "
                    "GROUP BY refresh_run_id, source_type, wb_cabinet_id, "
                    "raw_payload_hash HAVING count(*) > 1"
                    ") duplicate_payloads"
                )
            ).scalar_one()
        )
        target_run_count = int(
            connection.execute(
                text(f"SELECT count(*) FROM ({target_runs}) target_runs")
            ).scalar_one()
        )
    return {
        "activeClients": active_clients,
        "activeRefreshes": active_refreshes,
        "activeCompanies": len(companies),
        "organizationLinkCandidates": organization_links,
        "ozonCabinetLinkCandidates": cabinet_links,
        "positionDuplicateGroups": position_duplicates,
        "payloadDuplicateGroups": payload_duplicates,
        "targetRuns": target_run_count,
    }


def _target_runs_sql(prefix: str) -> str:
    return (
        "SELECT id FROM ("
        "SELECT r.id, row_number() OVER ("
        "PARTITION BY r.client_id ORDER BY r.created_at DESC"
        ") AS rank "
        f"FROM {prefix}source_refresh_runs r "
        f"JOIN {prefix}clients c ON c.id = r.client_id "
        "WHERE c.status = 'active' AND EXISTS ("
        "SELECT 1 "
        f"FROM {prefix}source_snapshot_rows s "
        "WHERE s.refresh_run_id = r.id "
        "AND s.source_type = 'onec_organizations'"
        ")"
        ") ranked_runs WHERE rank = 1"
    )


def _target_run_ids(engine) -> list[str]:  # type: ignore[no-untyped-def]
    sqlite = str(engine.url).startswith("sqlite")
    schema = None if sqlite else "wb_unit_economics"
    if not inspect(engine).has_table("source_snapshot_rows", schema=schema):
        return []
    prefix = "" if sqlite else "wb_unit_economics."
    with engine.connect() as connection:
        return list(connection.execute(text(_target_runs_sql(prefix))).scalars())


def _organization_link_candidates(
    connection,
    *,
    prefix: str,
    companies: list[dict[str, Any]],
) -> int:  # type: ignore[no-untyped-def]
    run_rows = connection.execute(
        text(
            "SELECT r.id, r.client_id, r.created_at "
            f"FROM {prefix}source_refresh_runs r "
            f"JOIN {prefix}source_refresh_collections c "
            "ON c.refresh_run_id = r.id "
            "WHERE c.source_type = 'onec_organizations' "
            "ORDER BY r.created_at DESC"
        )
    ).mappings().all()
    latest_run_by_client: dict[str, str] = {}
    for item in run_rows:
        latest_run_by_client.setdefault(str(item["client_id"]), str(item["id"]))
    organizations_by_client: dict[str, dict[str, dict[str, Any]]] = {}
    for client_id, run_id in latest_run_by_client.items():
        rows = connection.execute(
            text(
                "SELECT row_payload "
                f"FROM {prefix}source_snapshot_rows "
                "WHERE refresh_run_id = :run_id "
                "AND source_type = 'onec_organizations'"
            ),
            {"run_id": run_id},
        ).scalars()
        organizations_by_client[client_id] = {
            str(payload.get("Ref_Key") or ""): payload
            for payload in rows
            if isinstance(payload, dict) and payload.get("Ref_Key")
        }
    result = 0
    for company in companies:
        client_id = str(company["client_id"])
        organizations = organizations_by_client.get(client_id, {})
        current = str(company["onec_organization_id"] or "")
        if current in organizations:
            continue
        source_key = str(company["source_key"] or "")
        if source_key in organizations:
            result += 1
            continue
        company_name = _exact_name(str(company["display_name"] or ""))
        candidates = [
            organization_id
            for organization_id, payload in organizations.items()
            if company_name
            in {
                _exact_name(str(payload.get(key) or ""))
                for key in (
                    "Description",
                    "НаименованиеПолное",
                    "НаименованиеСокращенное",
                )
            }
        ]
        if len(set(candidates)) == 1:
            result += 1
    return result


def _exact_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _ensure_snapshot_position_index(engine) -> None:  # type: ignore[no-untyped-def]
    table = (
        "source_snapshot_rows"
        if str(engine.url).startswith("sqlite")
        else "wb_unit_economics.source_snapshot_rows"
    )
    index_name = "uq_source_snapshot_row_position"
    if str(engine.url).startswith("sqlite"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table} (refresh_run_id, collection_id, row_number)"
                )
            )
        return
    connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {index_name} "
                f"ON {table} (refresh_run_id, collection_id, row_number)"
            )
        )
    except Exception:
        connection.execute(
            text(
                "DROP INDEX CONCURRENTLY IF EXISTS "
                f"wb_unit_economics.{index_name}"
            )
        )
        raise
    finally:
        connection.close()


def _print_summary(label: str, summary: dict[str, int]) -> None:
    values = " ".join(f"{key}={value}" for key, value in sorted(summary.items()))
    print(f"{label}: {values}")


if __name__ == "__main__":
    raise SystemExit(main())
