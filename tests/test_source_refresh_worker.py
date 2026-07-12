from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.check_source_refresh_worker import cli_worker_process_exists
from scripts.run_source_refresh_worker import (
    WorkerInterrupted,
    claim_next_run,
    process_run,
    recover_stale_worker_runs,
)
from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import source_refresh_progress_payload
from wb_unit_economics.web.source_refresh_worker import (
    SourceRefreshWorkerLaunchError,
    SystemdSourceRefreshWorkerLauncher,
    launch_source_refresh_worker,
    production_source_refresh_worker_launcher,
)


def test_production_worker_launcher_uses_systemd_without_shell(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "wb_unit_economics.web.source_refresh_worker.subprocess.run",
        fake_run,
    )
    settings = WebSettings(
        _env_file=None,
        database_url="postgresql+psycopg://localhost/example",
    )
    launcher = production_source_refresh_worker_launcher(settings)

    assert launcher is not None
    unit = launcher.launch("source_refresh_123")

    assert unit == "shumeiko-source-refresh-worker@source_refresh_123.service"
    assert calls[0][0] == ["systemctl", "start", "--no-block", unit]
    assert calls[0][1]["timeout"] == 15


def test_worker_launcher_is_not_used_for_local_sqlite() -> None:
    settings = WebSettings(_env_file=None, database_url="sqlite:///:memory:")

    assert production_source_refresh_worker_launcher(settings) is None


def test_worker_launcher_rejects_unsafe_run_id() -> None:
    launcher = SystemdSourceRefreshWorkerLauncher(WebSettings(_env_file=None))

    with pytest.raises(SourceRefreshWorkerLaunchError):
        launcher.launch("../../unsafe")


def test_launch_failure_marks_queued_run_failed_without_deleting_data(
    tmp_path: Path,
) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="launch-failure")
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="1C sales register",
            required=True,
            status="loaded",
            row_count=4,
        )
        refresh_run_id = refresh_run.id
        db.commit()

    class _FailingLauncher:
        def launch(self, _refresh_run_id: str) -> str:
            raise SourceRefreshWorkerLaunchError("worker start failed")

    with factory() as db, pytest.raises(SourceRefreshWorkerLaunchError):
        launch_source_refresh_worker(
            db,
            refresh_run_id=refresh_run_id,
            worker_launcher=_FailingLauncher(),
        )

    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "failed"
        assert refresh_run.failure_code == "worker_launch_failed"
        assert len(refresh_run.collections) == 1
        assert refresh_run.collections[0].row_count == 4


def test_external_worker_launch_records_systemd_owner(tmp_path: Path) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="external-launch")
        refresh_run_id = refresh_run.id
        db.commit()
    launched: list[str] = []

    class _Launcher:
        def launch(self, run_id: str) -> str:
            launched.append(run_id)
            return f"shumeiko-source-refresh-worker@{run_id}.service"

    with factory() as db:
        payload = launch_source_refresh_worker(
            db,
            refresh_run_id=refresh_run_id,
            worker_launcher=_Launcher(),
        )

    assert launched == [refresh_run_id]
    assert payload["status"] == "queued"
    assert payload["workerAssigned"] is True
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.worker_id == f"systemd:{refresh_run_id}"
        assert refresh_run.heartbeat_at is not None


def test_cli_worker_process_check_requires_live_refresh_command(monkeypatch) -> None:
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: b"python\0scripts/run_source_refresh.py\0",
    )
    assert cli_worker_process_exists("cli:123:source_refresh_1") is True
    assert cli_worker_process_exists("cli:source_refresh_1") is False


def test_cli_worker_process_check_rejects_missing_pid(monkeypatch) -> None:
    def missing(_path):
        raise FileNotFoundError

    monkeypatch.setattr(Path, "read_bytes", missing)
    assert cli_worker_process_exists("cli:123:source_refresh_1") is False


def test_source_refresh_progress_reads_only_safe_manifest_aggregates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source_refresh"
    run_root = root / "full-progress"
    finance = run_root / "wb_finance"
    finance.mkdir(parents=True)
    page = finance / "account_page_1.raw.json"
    page.write_text("[]", encoding="utf-8")
    (finance / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "seller_account_id": "SECRET_ACCOUNT",
                        "page_index": 1,
                        "status": "ok",
                        "row_count": 100000,
                        "output_file": page.name,
                    },
                    {
                        "seller_account_id": "SECRET_ACCOUNT",
                        "page_index": 2,
                        "status": "no_data",
                        "row_count": 0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    now = datetime.now().astimezone()
    refresh_run = SourceRefreshRun(
        id="source_refresh_progress",
        tenant_id="shumeyko",
        client_id="shumeyko",
        mode="full",
        credential_source="tenant",
        dry_run=False,
        status="running",
        reason="",
        snapshot_set_id=run_root.name,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 7, 10),
        root_dir=str(run_root),
        workbook_path="",
        error_message="",
        worker_id="worker",
        failure_code="",
        created_at=now,
        updated_at=now,
    )

    payload = source_refresh_progress_payload(refresh_run, source_root=root)
    last_activity_at = payload.pop("lastActivityAt")

    assert payload == {
        "stage": "wb_finance",
        "currentSource": "WB",
        "completedSources": 0,
        "totalSources": 0,
        "wbAccountsCompleted": 1,
        "wbAccountsTotal": 1,
        "pagesLoaded": 1,
        "rowsLoaded": 100000,
        "bytesWritten": 2,
    }
    assert last_activity_at is not None
    assert datetime.fromisoformat(last_activity_at).tzinfo is not None
    assert "SECRET_ACCOUNT" not in str(payload)


def _worker_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'worker.sqlite3'}")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        repository.ensure_tenant(db, "tenant-1", "Tenant 1")
        db.commit()
    return factory


def _queued_run(db, *, suffix: str):
    return repository.create_source_refresh_run(
        db,
        tenant_id="tenant-1",
        client_id="tenant-1",
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=f"snapshot-{suffix}",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        reason=f"worker test {suffix}",
    )


def test_worker_claims_queued_run_once(tmp_path: Path) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="claim")
        refresh_run_id = refresh_run.id
        db.commit()
    with factory() as db:
        claimed = claim_next_run(db, worker_id="systemd-source-refresh-worker:test")
        assert claimed is not None
        assert claimed.id == refresh_run_id
        repository.update_source_refresh_run(db, claimed, status="running")
        db.commit()
    with factory() as db:
        assert claim_next_run(db, worker_id="another-worker") is None


def test_worker_stale_recovery_preserves_collections(tmp_path: Path) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="stale")
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="rebuilding",
            worker_id="systemd-source-refresh-worker:old",
            heartbeat_at=security.utcnow() - timedelta(minutes=10),
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="1C sales register",
            required=True,
            status="loaded",
            row_count=35,
        )
        refresh_run_id = refresh_run.id
        db.commit()
    with factory() as db:
        assert recover_stale_worker_runs(
            db,
            worker_name="systemd-source-refresh-worker",
            stale_after_seconds=300,
        ) == 1
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "failed"
        assert refresh_run.failure_code == "worker_heartbeat_stale"
        assert len(refresh_run.collections) == 1
        assert refresh_run.collections[0].row_count == 35


def test_worker_interruption_marks_run_failed_and_preserves_collections(
    tmp_path: Path,
) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="interrupt")
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            worker_id=f"systemd:{refresh_run.id}",
            heartbeat_at=security.utcnow(),
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="1C sales register",
            required=True,
            status="loaded",
            row_count=8,
        )
        refresh_run_id = refresh_run.id
        db.commit()

    class _InterruptedService:
        def run_existing(self, _db, _refresh_run_id):
            raise WorkerInterrupted("SIGTERM")

    with pytest.raises(WorkerInterrupted):
        process_run(
            factory,
            _InterruptedService(),
            refresh_run_id,
            heartbeat_seconds=30,
        )

    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "failed"
        assert refresh_run.failure_code == "worker_interrupted"
        assert len(refresh_run.collections) == 1
        assert refresh_run.collections[0].row_count == 8


def test_worker_unit_has_memory_limit_and_failure_repair() -> None:
    project_root = Path(__file__).resolve().parents[1]
    unit = (
        project_root / "deploy/systemd/shumeiko-source-refresh-worker@.service"
    ).read_text(encoding="utf-8")

    assert "scripts/run_source_refresh_worker.py" in unit
    assert "MemoryHigh=3G" in unit
    assert "MemoryMax=4G" in unit
    assert "MemorySwapMax=1G" in unit
    assert "ManagedOOMMemoryPressure=auto" in unit
    assert "OOMScoreAdjust=500" in unit
    assert "OOMPolicy=stop" in unit
    assert "TasksMax=256" in unit
    assert "repair_source_refresh_run.py" in unit
    assert "RuntimeMaxSec=2h" in unit
    assert "TimeoutStopSec=60" in unit
