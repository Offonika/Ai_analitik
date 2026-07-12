from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from wb_unit_economics.web.database import (
    _ensure_source_refresh_resume_columns,
    make_engine,
)


def test_make_engine_recycles_and_pre_pings_non_sqlite() -> None:
    engine = make_engine("postgresql+psycopg://user:pass@localhost/db")

    assert getattr(engine.pool, "_pre_ping", False) is True
    assert getattr(engine.pool, "_recycle", -1) == 1800


def test_make_engine_keeps_sqlite_file_setup(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "web.sqlite3"
    engine = make_engine(f"sqlite:///{db_path}")

    assert db_path.parent.exists()
    assert getattr(engine.pool, "_pre_ping", False) is False


def test_source_refresh_worker_and_lineage_migration_is_idempotent(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE source_refresh_runs (id VARCHAR PRIMARY KEY)")
        )
        connection.execute(
            text("CREATE TABLE source_refresh_collections (id VARCHAR PRIMARY KEY)")
        )

    _ensure_source_refresh_resume_columns(engine)
    _ensure_source_refresh_resume_columns(engine)

    run_columns = {
        item["name"] for item in inspect(engine).get_columns("source_refresh_runs")
    }
    assert {
        "resumed_from_run_id",
        "base_source_refresh_run_id",
        "blocked_by_run_id",
        "worker_id",
        "failure_code",
        "heartbeat_at",
    }.issubset(run_columns)
