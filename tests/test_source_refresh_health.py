from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory


def test_source_refresh_health_ok_failed_missing_and_stale(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    session_factory = _seed_health_db(database_url)
    with session_factory() as db:
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="daily-ok",
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 22),
            reason="test",
        )
        repository.update_source_refresh_run(
            db,
            run,
            status="source_loaded",
            finished_at=security.utcnow(),
        )
        repository.add_source_refresh_collection(
            db,
            run,
            source_type="wb_finance_detail",
            source_label="WB Finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        db.commit()

    ok = _run_health(tmp_path, database_url, "--tenant", "shumeyko", "--mode", "daily")
    assert ok.returncode == 0
    assert "Health: ok" in ok.stdout
    assert "Active run: none" in ok.stdout
    assert "Source root free GiB:" in ok.stdout
    assert "wb_finance_detail" in ok.stdout

    with session_factory() as db:
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-failed",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 22),
            reason="test",
        )
        repository.update_source_refresh_run(
            db,
            run,
            status="failed",
            finished_at=security.utcnow(),
        )
        db.commit()

    failed = _run_health(
        tmp_path,
        database_url,
        "--tenant",
        "shumeyko",
        "--mode",
        "full",
    )
    assert failed.returncode == 1
    assert "Health: failed" in failed.stdout

    with session_factory() as db:
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="weekly",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="weekly-blocked",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 22),
            reason="test",
        )
        repository.update_source_refresh_run(
            db,
            run,
            status="blocked_low_disk",
            finished_at=security.utcnow(),
        )
        db.commit()

    blocked = _run_health(
        tmp_path,
        database_url,
        "--tenant",
        "shumeyko",
        "--mode",
        "weekly",
    )
    assert blocked.returncode == 1
    assert "blocked_low_disk" in blocked.stdout
    assert "Health: failed" in blocked.stdout

    missing = _run_health(
        tmp_path,
        database_url,
        "--tenant",
        "shumeyko",
        "--mode",
        "onec-only",
    )
    assert missing.returncode == 2
    assert "No source refresh run" in missing.stdout

    with session_factory() as db:
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="onec-stale",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 22),
            reason="test",
        )
        stale_at = security.utcnow() - timedelta(hours=5)
        run.created_at = stale_at
        run.updated_at = stale_at
        run.finished_at = stale_at
        run.status = "source_loaded"
        db.commit()

    stale = _run_health(
        tmp_path,
        database_url,
        "--tenant",
        "shumeyko",
        "--mode",
        "onec-only",
        "--max-age-hours",
        "1",
    )
    assert stale.returncode == 2
    assert "Health: stale" in stale.stdout


def _seed_health_db(database_url: str):
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        repository.ensure_tenant(db, "shumeyko", "Шумейко и Партнеры")
        db.commit()
    return session_factory


def _run_health(tmp_path: Path, database_url: str, *args: str):
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/check_source_refresh_health.py",
            "--database-url",
            database_url,
            *args,
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
